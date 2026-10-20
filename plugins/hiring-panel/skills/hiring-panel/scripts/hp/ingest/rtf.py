"""Read .rtf with the standard library (ATS spec 3: "strip control words").

Handles groups, ignorable destinations (font/colour/style tables, pictures, objects, field
instructions, comments), \\'hh and \\uN characters (with \\ucN fallbacks), paragraphs, line breaks,
tabs, tables (cells joined with " | " like the .docx reader), header/footer destinations, shape text
boxes, list text, and the formatting needed for hidden-text facts (\\v, white \\cf colours, \\fs < 12).
Iterative (no recursion), so deeply nested braces cannot overflow the stack.
"""
import re
import types

from hp.ingest.assemble import ParagraphBuilder, Collector
from hp.ingest.limits import MAX_LINES
from hp.ingest.normalize import has_contact, has_date_range, looks_like_heading

_TOKEN_RE = re.compile(rb"\\([a-zA-Z]{1,32})(-?\d{1,10})? ?|\\'([0-9a-fA-F]{2})|\\([^a-zA-Z'])|([{}])|[\r\n]+|([^\\{}\r\n]+)", re.S)
SKIP = set("""fonttbl colortbl stylesheet info pict object themedata colorschememapping latentstyles datastore
xmlnsdecl listtable listoverridetable rsidtbl generator mmathPr pgdsctbl fldinst filetbl revtbl bkmkstart
bkmkend xe tc nonshppict blipuid sp sn sv pntxtb pntxta footnote annotation atnid atnauthor atrfstart atrfend
atnref atndate atnicn template userprops docvar password passwordhash wgrffmtfilter panose falt fname
listpicture formfield ffname ffdeftext background shppict do dptxbxtext hlinkbase""".split())
HEADER_DESTS = {"header": "header", "headerl": "header", "headerr": "header", "headerf": "header",
                "footer": "footer", "footerl": "footer", "footerr": "footer", "footerf": "footer"}
SPECIAL = {"emdash": "\u2014", "endash": "\u2013", "bullet": "\u2022", "lquote": "\u2018", "rquote": "\u2019",
           "ldblquote": "\u201c", "rdblquote": "\u201d", "emspace": " ", "enspace": " ", "qmspace": " "}


class _State(object):
    """Character and destination state of one RTF group (copied on "{", restored on "}")."""
    __slots__ = ("dest", "hidden", "bold", "caps", "fs", "cf", "uc")

    def __init__(self):
        self.dest = "body"
        self.hidden = False
        self.bold = False
        self.caps = False
        self.fs = 24
        self.cf = 0
        self.uc = 1

    def copy(self):
        s = _State()
        for k in self.__slots__:
            setattr(s, k, getattr(self, k))
        return s


def _skip_group(data, pos):
    """Return the position just after the brace closing the current group."""
    depth = 1
    n = len(data)
    special = re.compile(rb"[{}\\]")
    while pos < n:
        m = special.search(data, pos)
        if not m:
            return n
        c = data[m.start():m.start() + 1]
        pos = m.end()
        if c == b"\\":
            bm = re.match(rb"bin(\d{1,9}) ?", data[pos:pos + 16])
            if bm:
                pos += bm.end() + int(bm.group(1))
            else:
                pos += 1
        elif c == b"{":
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return pos
    return n


def _colortable(raw):
    colors = []
    for entry in raw.split(b";")[:-1] if b";" in raw else []:
        r = re.search(rb"\\red(\d+)", entry)
        g = re.search(rb"\\green(\d+)", entry)
        b = re.search(rb"\\blue(\d+)", entry)
        if r and g and b:
            colors.append((int(r.group(1)), int(g.group(1)), int(b.group(1))))
        else:
            colors.append(None)
    return colors


def read_rtf(data, doc, ctx):
    sig = doc["signals"]
    collector = Collector(ctx.stats)
    codec = "cp1252"
    m = re.search(rb"\\ansicpg(\d{3,5})", data[:4096])
    if m:
        cand = "cp" + m.group(1).decode("ascii")
        try:
            b"a".decode(cand)
            codec = cand
        except LookupError:
            pass
    colors = []
    stack = []
    st = _State()
    builders = {}
    para_props = {"intbl": False, "list": False}
    out = {"body": [], "header": [], "footer": []}
    row_cells = []
    cell_lines = []
    # Parser flags shared with the helper closures below.
    ps = types.SimpleNamespace(in_table=False, textboxes=0, pending_skip=0, group_start=False, ignorable=False)

    def builder(dest):
        b = builders.get(dest)
        if b is None:
            b = builders[dest] = ParagraphBuilder()
        return b

    def add_text(s):
        if not s:
            return
        if ps.pending_skip:            # \uN is followed by \ucN fallback characters to drop
            k = min(ps.pending_skip, len(s))
            s = s[k:]
            ps.pending_skip -= k
            if not s:
                return
        hidden = None
        if st.hidden:
            hidden = "vanish"
        elif 0 < st.cf < len(colors) and colors[st.cf] and all(c >= 245 for c in colors[st.cf]):
            hidden = "white"
        elif st.fs < 12:
            hidden = "tiny"
        builder(st.dest).text(s, hidden, st.bold, st.caps)

    def finish_para(dest, end_of_cell=False):
        b = builders.pop(dest, None)
        where = dest
        if dest == "body":
            where = "table" if (para_props["intbl"] or end_of_cell) else "body"
        lines = b.finish(collector, None, para_props["list"], False, where) if b else []
        if dest in ("header", "footer"):
            out[dest].extend(lines)
        elif dest == "textbox":
            out["body"].extend(lines)
        elif para_props["intbl"] or end_of_cell:
            cell_lines.extend(lines)
        else:
            ps.in_table = False
            out["body"].extend(lines)

    def finish_row():
        if builders.get("body") is not None and builders["body"].pieces:
            finish_para("body", end_of_cell=True)
            row_cells.append(list(cell_lines))
            del cell_lines[:]
        cells = [c for c in row_cells if c]
        if cells:
            if not ps.in_table:
                sig["tables"]["count"] += 1
                ps.in_table = True
            for c in cells:
                for ln in c:
                    if has_date_range(ln["text"]) or looks_like_heading(ln["text"], None, ln["bold"]):
                        sig["tables"]["holds_experience"] = True
            firsts = [c[0] for c in cells]
            if len(firsts) == 1:
                head = dict(firsts[0])
            else:
                head = {"text": " | ".join(l["text"] for l in firsts), "style": None, "list": False,
                        "bold": all(l["bold"] for l in firsts), "where": "table"}
            out["body"].append(head)
            for c in cells:
                out["body"].extend(c[1:])
        del row_cells[:]

    pos = 0
    n = len(data)
    while pos < n:
        tm = _TOKEN_RE.match(data, pos)
        if not tm:
            pos += 1
            continue
        pos = tm.end()
        word, arg, hexbyte, sym, brace, text = tm.group(1), tm.group(2), tm.group(3), tm.group(4), tm.group(5), tm.group(6)
        if brace == b"{":
            if len(stack) > 2000:
                pos = _skip_group(data, pos)
                continue
            stack.append(st)
            st = st.copy()
            ps.group_start = True
            ps.ignorable = False
            continue
        if brace == b"}":
            if st.dest == "textbox" and stack and stack[-1].dest != "textbox":
                if builders.get("textbox") is not None:
                    finish_para("textbox")
            st = stack.pop() if stack else _State()
            ps.group_start = False
            continue
        was_start = ps.group_start
        ps.group_start = False
        if sym is not None:
            if sym == b"*":
                ps.ignorable = True
                ps.group_start = was_start
            elif sym == b"~":
                add_text("\u00a0")
            elif sym == b"_":
                add_text("-")
            elif sym in (b"\\", b"{", b"}"):
                add_text(sym.decode("latin-1"))
            elif sym in (b"\n", b"\r"):
                finish_para(st.dest)
            elif sym == b"\t":
                builder(st.dest).tab()
            continue
        if hexbyte is not None:
            try:
                ch = bytes([int(hexbyte, 16)]).decode(codec)
            except (UnicodeDecodeError, ValueError):
                ch = bytes([int(hexbyte, 16)]).decode("latin-1")
            add_text(ch)
            continue
        if text is not None:
            try:
                add_text(text.decode(codec))
            except UnicodeDecodeError:
                add_text(text.decode("latin-1"))
            continue
        if word is None:
            continue   # newlines between tokens carry no meaning in RTF
        w = word.decode("ascii")
        num = int(arg) if arg is not None else None
        if was_start and (ps.ignorable or w in SKIP):
            if w == "colortbl":
                end = _skip_group(data, pos)
                colors = _colortable(data[pos:end])   # index = the \cfN number
                pos = end
                st = stack.pop() if stack else _State()
                continue
            if w == "pict" or w == "shppict":
                sig["images"]["count"] += 1
            elif w == "object":
                sig["fields"]["ole"] += 1
            elif w == "annotation":
                sig["comments"] += 1
            elif w == "fldinst":
                end = _skip_group(data, pos)
                inst = data[pos:end]
                if re.search(rb"MERGEFIELD", inst):
                    sig["fields"]["mergefield"] += 1
                if re.search(rb"DOCPROPERTY", inst):
                    sig["fields"]["docproperty"] += 1
                pos = end
                st = stack.pop() if stack else _State()
                continue
            if w in HEADER_DESTS or w == "shptxt" or w == "listtext" or w == "pntext" or w == "shpinst" \
                    or w == "fldrslt" or w == "field" or w == "shp":
                pass   # readable destinations, even when marked ignorable
            else:
                pos = _skip_group(data, pos)
                st = stack.pop() if stack else _State()
                continue
        if w in HEADER_DESTS:
            st.dest = HEADER_DESTS[w]
        elif w == "shptxt":
            st.dest = "textbox"
            ps.textboxes += 1
        elif w == "par":
            finish_para(st.dest)
        elif w == "line":
            builder(st.dest).br()
        elif w == "tab":
            builder(st.dest).tab()
        elif w in ("cell", "nestcell"):
            finish_para("body", end_of_cell=True)
            row_cells.append(list(cell_lines))
            del cell_lines[:]
        elif w in ("row", "nestrow"):
            finish_row()
        elif w == "pard":
            para_props["intbl"] = False
            para_props["list"] = False
        elif w == "intbl":
            para_props["intbl"] = True
        elif w in ("ls", "ilvl", "pnlvlblt"):
            para_props["list"] = True
        elif w == "plain":
            st.hidden, st.bold, st.caps, st.fs, st.cf = False, False, False, 24, 0
        elif w == "v":
            st.hidden = num != 0
        elif w == "b":
            st.bold = num != 0
        elif w in ("caps", "scaps"):
            st.caps = num != 0
        elif w == "fs":
            st.fs = num if num is not None else 24
        elif w == "cf":
            st.cf = num or 0
        elif w == "uc":
            st.uc = max(0, num or 0)
        elif w == "u":
            if num is not None:
                cp = num + 65536 if num < 0 else num
                try:
                    add_text(chr(cp))
                except (ValueError, OverflowError):
                    pass
                ps.pending_skip = st.uc
            continue
        elif w in SPECIAL:
            add_text(SPECIAL[w])
    # flush
    for dest in list(builders):
        if dest == "body" and (para_props["intbl"] or cell_lines):
            finish_para("body", end_of_cell=True)
            row_cells.append(list(cell_lines))
            del cell_lines[:]
            finish_row()
        else:
            finish_para(dest)
    if row_cells:
        finish_row()

    lines = out["body"]
    if len(lines) > MAX_LINES:
        doc["warnings"].append("text truncated to the first %d lines" % MAX_LINES)
        lines = lines[:MAX_LINES]
    doc["lines"] = lines
    seen = set()
    hf = []
    for kind in ("header", "footer"):
        for ln in out[kind]:
            key = (kind, ln["text"])
            if key not in seen:
                seen.add(key)
                hf.append({"where": kind, "text": ln["text"]})
    doc["header_footer"] = hf
    doc["method"] = "rtf"
    tb = [l for l in lines if l["where"] == "textbox"]
    sig["text_boxes"]["count"] = ps.textboxes
    sig["text_boxes"]["chars"] = sum(len(l["text"]) for l in tb)
    sig["text_boxes"]["has_contact"] = any(has_contact(l["text"]) for l in tb)
    sig["text_boxes"]["has_heading"] = any(looks_like_heading(l["text"], None, l["bold"]) for l in tb)
    sig["hidden_text"]["vanish"] = collector.hidden["vanish"]
    sig["hidden_text"]["white"] = collector.hidden["white"]
    sig["hidden_text"]["tiny"] = collector.hidden["tiny"]
    sig["caps_formatting"] = collector.caps_paragraphs
    sig["tab_merged_tokens"] = collector.tab_merged
    ctx.hidden_samples.extend(collector.hidden_samples)
    return doc
