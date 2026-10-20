"""Read a .docx with zipfile + ElementTree only (ATS spec 4 and 5).

Reading order (the "ATS view"):
- the body is walked in document order: paragraphs, tables row by row, content controls, and
  mc:AlternateContent (the mc:Choice branch; the mc:Fallback duplicate is skipped);
- a table row becomes one line: the first line of every non-empty cell joined with " | ", followed by
  the remaining lines of each cell in cell order (so bullets inside a cell stay separate lines);
- text-box content is emitted where it is anchored (before the anchoring paragraph's text when the
  anchor comes first, else after), with where="textbox";
- header and footer parts are read separately into doc["header_footer"] (where header|footer).
Text: w:t is text, w:tab/w:ptab a tab, w:br/w:cr a line break, w:sym a symbol character; deleted
text (w:del, w:moveFrom) and field instructions are skipped; inserted text (w:ins) is kept.
Structure facts (tables, text boxes, columns, images, charts, SmartArt, hidden text, tracked changes,
comments, fields, OLE objects, symbols, caps formatting, tab-merged tokens) go into doc["signals"].
"""
import posixpath
import re

from hp.ingest.limits import SafeZip, RefusedInput, MAX_DEPTH, MAX_LINES
from hp.ingest.assemble import ParagraphBuilder, Collector
from hp.ingest.normalize import has_contact, has_date_range, looks_like_heading

W_NS = ("http://schemas.openxmlformats.org/wordprocessingml/2006/main",
        "http://purl.oclc.org/ooxml/wordprocessingml/main")
R_NS = ("http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "http://purl.oclc.org/ooxml/officeDocument/relationships")
WP_NS = ("http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
         "http://purl.oclc.org/ooxml/drawingml/wordprocessingDrawing")
PIC_NS = ("http://schemas.openxmlformats.org/drawingml/2006/picture",
          "http://purl.oclc.org/ooxml/drawingml/picture")
C_NS = ("http://schemas.openxmlformats.org/drawingml/2006/chart",
        "http://purl.oclc.org/ooxml/drawingml/chart")
DGM_NS = ("http://schemas.openxmlformats.org/drawingml/2006/diagram",
          "http://purl.oclc.org/ooxml/drawingml/diagram")
M_NS = ("http://schemas.openxmlformats.org/officeDocument/2006/math",
        "http://purl.oclc.org/ooxml/officeDocument/math")
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
V_NS = "urn:schemas-microsoft-com:vml"

EMU_PER_TWIP = 635
EMU_PER_PT = 12700
DEFAULT_PAGE_TWIPS = (12240, 15840)          # US Letter
SMALL_ICON_EMU = 548640                      # 0.6 inch: icons for phone/email/LinkedIn
BACKGROUND_SHAPE_MIN_EMU = 228600            # 0.25 inch: thinner shapes are divider lines
DESIGN_TOOL_RE = re.compile(r"(?i)\b(canva|indesign|illustrator|photoshop|figma|affinity|sketch|pages|keynote)\b")
DESIGN_TOOL_NAMES = {"canva": "Canva", "indesign": "InDesign", "illustrator": "Illustrator",
                     "photoshop": "Photoshop", "figma": "Figma", "affinity": "Affinity",
                     "sketch": "Sketch", "pages": "Pages", "keynote": "Keynote"}
TRACKED_TAGS = set(["ins", "del", "moveFrom", "moveTo", "rPrChange", "pPrChange", "sectPrChange",
                    "tblPrChange", "trPrChange", "tcPrChange", "tblGridChange", "numberingChange",
                    "cellIns", "cellDel", "cellMerge"])


# --- small XML helpers ------------------------------------------------------------------------------
def _local(el):
    tag = el.tag
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def _ns(el):
    tag = el.tag
    if isinstance(tag, str) and tag.startswith("{"):
        return tag[1:].split("}", 1)[0]
    return ""


def _is(el, local, namespaces=W_NS):
    return _local(el) == local and _ns(el) in namespaces


def _attr(el, name, namespaces=W_NS):
    if el is None:
        return None
    for ns in namespaces:
        v = el.get("{%s}%s" % (ns, name))
        if v is not None:
            return v
    return el.get(name)


def _child(el, local, namespaces=W_NS):
    if el is None:
        return None
    for c in el:
        if _is(c, local, namespaces):
            return c
    return None


def _on(el):
    """OOXML toggle property: present and not explicitly switched off."""
    if el is None:
        return None
    v = _attr(el, "val")
    return v is None or v.strip().lower() not in ("0", "false", "off", "none")


def _int(v, default=None):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


def _is_whiteish(hexval):
    v = (hexval or "").strip().lstrip("#").upper()
    if not re.match(r"^[0-9A-F]{6}$", v):
        return False
    return all(int(v[i:i + 2], 16) >= 0xF5 for i in (0, 2, 4))


def _colored(hexval):
    """A fill that is set, not automatic and not white."""
    v = (hexval or "").strip().lstrip("#").upper()
    if not v or v == "AUTO" or v == "NONE":
        return False
    if re.match(r"^[0-9A-F]{6}$", v):
        return not _is_whiteish(v)
    return False


def _choose(alt):
    """mc:AlternateContent -> the first mc:Choice (or mc:Fallback when there is no Choice)."""
    fallback = None
    for c in alt:
        if _local(c) == "Choice":
            return c
        if _local(c) == "Fallback":
            fallback = c
    return fallback if fallback is not None else []


def iter_no_fallback(root):
    """Iterate all elements except the content of mc:Fallback branches (duplicates of mc:Choice)."""
    stack = [root]
    while stack:
        el = stack.pop()
        yield el
        kids = [c for c in el if not (_local(c) == "Fallback" and _ns(c) == MC_NS)]
        stack.extend(reversed(kids))


# --- styles and numbering ---------------------------------------------------------------------------
def parse_rpr(rpr):
    """Explicit run properties of one w:rPr element."""
    out = {}
    if rpr is None:
        return out
    for c in rpr:
        ln = _local(c)
        if ln == "b":
            out["b"] = _on(c)
        elif ln in ("caps", "smallCaps"):
            if _on(c):
                out["caps"] = True
            elif "caps" not in out:
                out["caps"] = False
        elif ln == "vanish":
            out["vanish"] = _on(c)
        elif ln == "color":
            val = _attr(c, "val")
            theme = (_attr(c, "themeColor") or "").lower()
            if val and val.lower() != "auto":
                out["white"] = _is_whiteish(val)
            else:
                out["white"] = theme in ("background1", "light1")
        elif ln == "sz":
            sz = _int(_attr(c, "val"))
            if sz is not None:
                out["sz"] = sz
        elif ln == "shd":
            if _shd_el_colored(c):
                out["bg"] = True
        elif ln == "highlight":
            val = (_attr(c, "val") or "").lower()
            if val and val not in ("none", "white"):
                out["bg"] = True
    return out


def _shd_el_colored(shd):
    """A w:shd element that paints a non-white background (fill colour, or a solid pattern colour)."""
    if shd is None:
        return False
    pattern = (_attr(shd, "val") or "").lower()
    return _colored(_attr(shd, "fill")) or (pattern == "solid" and _colored(_attr(shd, "color")))


def _shd_colored(props):
    """Shading set directly in a w:pPr / w:tcPr / w:tblPr."""
    return _shd_el_colored(_child(props, "shd"))


class Styles(object):
    """styles.xml: names, basedOn chains, list numbering, run properties and shading per style id."""

    def __init__(self, root):
        self.by_id = {}
        self.default_para = None
        self.defaults = {}
        self._cache = {}
        if root is None:
            return
        for el in root:
            ln = _local(el)
            if ln == "docDefaults":
                rpr_default = _child(el, "rPrDefault")
                self.defaults = parse_rpr(_child(rpr_default, "rPr"))
            elif ln == "style":
                sid = _attr(el, "styleId")
                if sid is None:
                    continue
                name_el = _child(el, "name")
                based = _child(el, "basedOn")
                ppr = _child(el, "pPr")
                numpr = _child(ppr, "numPr")
                num = None
                if numpr is not None:
                    num = (_attr(_child(numpr, "numId"), "val"), _attr(_child(numpr, "ilvl"), "val"))
                stype = (_attr(el, "type") or "paragraph").lower()
                has_shd = any(_local(x) == "shd" and _shd_el_colored(x) for x in el.iter())
                self.by_id[sid] = {
                    "type": stype,
                    "name": _attr(name_el, "val") if name_el is not None else sid,
                    "based": _attr(based, "val") if based is not None else None,
                    "num": num,
                    "rpr": parse_rpr(_child(el, "rPr")),
                    "shaded": has_shd,
                }
                if stype == "paragraph" and _on_attr(el.get("{%s}default" % W_NS[0]) or el.get("{%s}default" % W_NS[1])):
                    self.default_para = sid

    def chain(self, sid):
        """Styles from the root ancestor down to sid (cycle-safe)."""
        seen = []
        cur = sid
        while cur and cur in self.by_id and cur not in seen and len(seen) < 20:
            seen.append(cur)
            cur = self.by_id[cur]["based"]
        return [self.by_id[s] for s in reversed(seen)]

    def name(self, sid):
        if not sid:
            return None
        st = self.by_id.get(sid)
        return st["name"] if st else sid

    def numpr(self, sid):
        for st in reversed(self.chain(sid)):
            if st["num"]:
                return st["num"]
        return None

    def shaded(self, sid):
        return any(st["shaded"] for st in self.chain(sid)) if sid else False

    def run_props(self, para_sid, char_sid, direct):
        key = (para_sid, char_sid)
        base = self._cache.get(key)
        if base is None:
            base = dict(self.defaults)
            for st in self.chain(para_sid or self.default_para):
                base.update(st["rpr"])
            for st in self.chain(char_sid):
                base.update(st["rpr"])
            self._cache[key] = base
        if not direct:
            return base
        merged = dict(base)
        merged.update(direct)
        return merged


def _on_attr(v):
    return v is not None and v.strip().lower() in ("1", "true", "on")


class Numbering(object):
    """numId + ilvl -> numFmt ("bullet", "decimal", ...)."""

    def __init__(self, root):
        self.abstract = {}
        self.nums = {}
        if root is None:
            return
        for el in root:
            ln = _local(el)
            if ln == "abstractNum":
                aid = _attr(el, "abstractNumId")
                self.abstract[aid] = self._levels(el)
            elif ln == "num":
                nid = _attr(el, "numId")
                aid = _attr(_child(el, "abstractNumId"), "val")
                overrides = {}
                for ov in el:
                    if _local(ov) == "lvlOverride":
                        lvl = _child(ov, "lvl")
                        if lvl is not None:
                            overrides.update(self._levels_from([lvl], _attr(ov, "ilvl")))
                self.nums[nid] = (aid, overrides)

    def _levels(self, abstract):
        return self._levels_from([c for c in abstract if _local(c) == "lvl"])

    @staticmethod
    def _levels_from(lvls, ilvl_default=None):
        out = {}
        for lvl in lvls:
            ilvl = _attr(lvl, "ilvl") or ilvl_default or "0"
            fmt = _attr(_child(lvl, "numFmt"), "val")
            out[str(ilvl)] = (fmt or "").lower()
        return out

    def fmt(self, num_id, ilvl):
        if num_id not in self.nums:
            return None
        aid, overrides = self.nums[num_id]
        key = str(ilvl or "0")
        if key in overrides:
            return overrides[key]
        return self.abstract.get(aid, {}).get(key)


# --- the walker -------------------------------------------------------------------------------------
class DocxWalker(object):
    def __init__(self, styles, numbering, page_emu, colored_background):
        self.styles = styles
        self.numbering = numbering
        self.page_emu = page_emu
        self.colored_background = colored_background   # page colour or large coloured shapes exist
        self.collector = None
        self.count_structure = True
        self.depth = 0
        self.table_depth = 0
        self.bg_depth = 0
        self.fields = []
        self.depth_warning = False
        # facts
        self.tables = {"count": 0, "nested": 0, "holds_experience": False}
        self.text_boxes = {"count": 0, "chars": 0, "has_contact": False, "has_heading": False}
        self.images = {"count": 0, "large": 0, "charts": 0, "smartart": 0, "small_icons": 0}
        self.field_counts = {"docproperty": 0, "mergefield": 0, "ole": 0}
        self.symbols = 0
        self.placeholders = 0
        self.alt_chunks = 0
        self.page_breaks = 0
        self.rendered_breaks = 0

    # block level
    def container(self, el, where):
        lines = []
        if self.depth >= MAX_DEPTH:
            self.depth_warning = True
            return lines
        self.depth += 1
        try:
            for child in el:
                ln = _local(child)
                if ln == "p":
                    lines.extend(self.paragraph(child, where))
                elif ln == "tbl":
                    lines.extend(self.table(child, where))
                elif ln == "sdt":
                    self._sdt_props(child)
                    content = _child(child, "sdtContent")
                    if content is not None:
                        lines.extend(self.container(content, where))
                elif ln in ("customXml", "smartTag", "ins", "moveTo", "sdtContent", "txbxContent"):
                    lines.extend(self.container(child, where))
                elif ln == "AlternateContent":
                    lines.extend(self.container(_choose(child), where))
                elif ln == "altChunk":
                    self.alt_chunks += 1
        finally:
            self.depth -= 1
        return lines

    def _sdt_props(self, sdt):
        pr = _child(sdt, "sdtPr")
        if pr is not None and _child(pr, "showingPlcHdr") is not None:
            self.placeholders += 1

    def paragraph(self, p, where):
        ppr = _child(p, "pPr")
        style_id = _attr(_child(ppr, "pStyle"), "val")
        numpr = _child(ppr, "numPr")
        num = None
        if numpr is not None:
            num = (_attr(_child(numpr, "numId"), "val"), _attr(_child(numpr, "ilvl"), "val"))
        elif style_id:
            num = self.styles.numpr(style_id)
        is_list = bool(num and num[0] not in (None, "0"))
        bullet = is_list and self.numbering.fmt(num[0], num[1]) == "bullet"
        shaded = _shd_colored(ppr) or self.styles.shaded(style_id)
        pb = ParagraphBuilder()
        ctx = {"style": style_id}
        if shaded:
            self.bg_depth += 1
        try:
            for child in p:
                self.inline(child, pb, ctx, where, 0)
        finally:
            if shaded:
                self.bg_depth -= 1
        return pb.finish(self.collector, self.styles.name(style_id), is_list, bullet, where)

    def table(self, tbl, where):
        if self.count_structure:
            self.tables["count"] += 1
            if self.table_depth > 0:
                self.tables["nested"] += 1
        tblpr = _child(tbl, "tblPr")
        tbl_style = _attr(_child(tblpr, "tblStyle"), "val")
        tbl_bg = _shd_colored(tblpr) or self.styles.shaded(tbl_style)
        line_where = where if where in ("textbox", "header", "footer") else "table"
        out = []
        if self.depth >= MAX_DEPTH:
            self.depth_warning = True
            return out
        self.table_depth += 1
        self.depth += 1
        try:
            for row in self._children(tbl, "tr"):
                cells = []
                for tc in self._children(row, "tc"):
                    cell_bg = tbl_bg or _shd_colored(_child(tc, "tcPr"))
                    if cell_bg:
                        self.bg_depth += 1
                    try:
                        cell_lines = self.container(tc, line_where)
                    finally:
                        if cell_bg:
                            self.bg_depth -= 1
                    if self.count_structure and not self.tables["holds_experience"]:
                        for ln in cell_lines:
                            if has_date_range(ln["text"]) or looks_like_heading(ln["text"], ln["style"], ln["bold"]):
                                self.tables["holds_experience"] = True
                                break
                    cells.append(cell_lines)
                out.extend(self._join_row(cells, line_where))
        finally:
            self.table_depth -= 1
            self.depth -= 1
        return out

    def _children(self, el, local, depth=0):
        """Rows of a table / cells of a row, looking through w:sdt and w:customXml wrappers."""
        out = []
        for c in el:
            ln = _local(c)
            if ln == local:
                out.append(c)
            elif ln in ("sdt", "customXml", "sdtContent") and depth < 5:
                out.extend(self._children(c, local, depth + 1))
        return out

    @staticmethod
    def _join_row(cells, where):
        cells = [c for c in cells if c]
        if not cells:
            return []
        firsts = [c[0] for c in cells]
        if len(firsts) == 1:
            head = dict(firsts[0])
        else:
            head = {"text": " | ".join(l["text"] for l in firsts), "style": None, "list": False,
                    "bold": all(l["bold"] for l in firsts), "where": where}
        out = [head]
        for c in cells:
            out.extend(c[1:])
        return out

    # inline level
    def inline(self, el, pb, ctx, where, depth):
        if depth > MAX_DEPTH:
            self.depth_warning = True
            return
        ln = _local(el)
        ns = _ns(el)
        if ln == "r" and ns in W_NS:
            self.run(el, pb, ctx, where)
        elif ln in ("hyperlink", "smartTag", "customXml", "ins", "moveTo", "dir", "bdo", "sdtContent",
                    "fldSimple") and ns in W_NS:
            if ln == "fldSimple":
                self._count_field(_attr(el, "instr"))
            for c in el:
                self.inline(c, pb, ctx, where, depth + 1)
        elif ln == "sdt" and ns in W_NS:
            self._sdt_props(el)
            for c in el:
                if _local(c) == "sdtContent":
                    for cc in c:
                        self.inline(cc, pb, ctx, where, depth + 1)
        elif ln == "AlternateContent":
            for c in _choose(el):
                self.inline(c, pb, ctx, where, depth + 1)
        elif ln in ("oMath", "oMathPara") and ns in M_NS:
            text = "".join(t.text or "" for t in el.iter() if _local(t) == "t")
            pb.text(text)
        # w:del, w:moveFrom (deleted text), bookmarks, proofing marks, comments ranges: nothing to read

    def _run_format(self, r, ctx):
        rpr = _child(r, "rPr")
        char_sid = _attr(_child(rpr, "rStyle"), "val")
        eff = self.styles.run_props(ctx.get("style"), char_sid, parse_rpr(rpr))
        hidden = None
        if eff.get("vanish"):
            hidden = "vanish"
        elif eff.get("white") and not (eff.get("bg") or self.bg_depth > 0 or self.colored_background):
            hidden = "white"
        elif eff.get("sz") is not None and eff["sz"] < 12:
            hidden = "tiny"
        return hidden, bool(eff.get("b")), bool(eff.get("caps"))

    def run(self, r, pb, ctx, where):
        fmt = self._run_format(r, ctx)
        for c in r:
            self._run_child(c, pb, fmt, where, 0)

    def _run_child(self, c, pb, fmt, where, depth):
        ln = _local(c)
        hidden, bold, caps = fmt
        if ln == "t":
            if not any(not f["sep"] for f in self.fields):
                pb.text(c.text or "", hidden, bold, caps)
        elif ln in ("tab", "ptab"):
            pb.tab()
        elif ln == "br":
            if (_attr(c, "type") or "").lower() == "page":
                self.page_breaks += 1
            pb.br()
        elif ln == "cr":
            pb.br()
        elif ln == "noBreakHyphen":
            pb.text("-", hidden, bold, caps)
        elif ln == "sym":
            self.symbols += 1
            code = _int_hex(_attr(c, "char"))
            if code is not None:
                if code < 0x100:
                    code += 0xF000          # symbol fonts map their bytes into the private-use area
                try:
                    pb.text(chr(code), hidden, bold, caps)
                except (ValueError, OverflowError):
                    pass
        elif ln == "drawing":
            self.graphic(c, pb, where, None, False, 0)
        elif ln == "pict":
            self.vml(c, pb, where, False, 0)
        elif ln == "object":
            self.field_counts["ole"] += 1
        elif ln == "AlternateContent":
            if depth < 8:
                for cc in _choose(c):
                    self._run_child(cc, pb, fmt, where, depth + 1)
        elif ln == "fldChar":
            t = (_attr(c, "fldCharType") or "").lower()
            if t == "begin":
                if len(self.fields) < 50:
                    self.fields.append({"instr": "", "sep": False})
            elif t == "separate" and self.fields:
                self.fields[-1]["sep"] = True
            elif t == "end" and self.fields:
                self._count_field(self.fields.pop()["instr"])
        elif ln == "instrText":
            if self.fields and len(self.fields[-1]["instr"]) < 2000:
                self.fields[-1]["instr"] += c.text or ""
        elif ln == "lastRenderedPageBreak":
            self.rendered_breaks += 1
        # w:delText, w:delInstrText, note/comment references, w:softHyphen: not visible text

    def _count_field(self, instr):
        words = (instr or "").strip().split()
        if not words:
            return
        kind = words[0].upper()
        if kind == "DOCPROPERTY":
            self.field_counts["docproperty"] += 1
        elif kind == "MERGEFIELD":
            self.field_counts["mergefield"] += 1

    # graphics: DrawingML and VML
    def graphic(self, el, pb, where, ext, filled, depth):
        if depth > MAX_DEPTH:
            self.depth_warning = True
            return
        for c in el:
            ln = _local(c)
            ns = _ns(c)
            if ln == "AlternateContent":
                self.graphic(_choose(c), pb, where, ext, filled, depth + 1)
            elif ln in ("inline", "anchor") and ns in WP_NS:
                self.graphic(c, pb, where, _extent(c) or ext, filled, depth + 1)
            elif ln == "pic" and ns in PIC_NS:
                self._image(ext)
            elif ln == "chart" and ns in C_NS:
                self.images["charts"] += 1
                self._image(ext, counted_as="chart")
            elif ln == "relIds" and ns in DGM_NS:
                self.images["smartart"] += 1
                self._image(ext, counted_as="smartart")
            elif ln == "wsp":
                self.graphic(c, pb, where, ext, filled or shape_filled(c), depth + 1)
            elif ln == "txbxContent":
                self.textbox(c, pb, where, filled)
            elif ln == "Fallback":
                continue
            else:
                self.graphic(c, pb, where, ext, filled, depth + 1)

    def vml(self, el, pb, where, filled, depth):
        if depth > MAX_DEPTH:
            self.depth_warning = True
            return
        for c in el:
            ln = _local(c)
            ns = _ns(c)
            if ns == V_NS and ln in ("shape", "rect", "roundrect", "oval", "group", "line", "polyline"):
                fill = c.get("fillcolor")
                is_filled = filled or (_colored(_vml_color(fill)) and c.get("filled", "t").lower() not in ("f", "false"))
                if any(_local(x) == "imagedata" for x in c):
                    self._image(_vml_extent(c))
                self.vml(c, pb, where, is_filled, depth + 1)
            elif ln == "txbxContent":
                self.textbox(c, pb, where, filled)
            elif ln == "AlternateContent":
                self.vml(_choose(c), pb, where, filled, depth + 1)
            elif ns == V_NS:                      # v:textbox and other VML wrappers
                self.vml(c, pb, where, filled, depth + 1)

    def _image(self, ext, counted_as="picture"):
        self.images["count"] += 1
        if not ext:
            return
        cx, cy = ext
        page_area = float(self.page_emu[0]) * float(self.page_emu[1])
        if page_area > 0 and cx * cy > 0.25 * page_area:
            self.images["large"] += 1
        elif counted_as == "picture" and max(cx, cy) <= SMALL_ICON_EMU:
            self.images["small_icons"] += 1

    def textbox(self, txbx, pb, where, filled):
        box_where = "textbox" if where in ("body", "table", "textbox") else where
        if filled:
            self.bg_depth += 1
        try:
            lines = self.container(txbx, box_where)
        finally:
            if filled:
                self.bg_depth -= 1
        if self.count_structure and box_where == "textbox":
            self.text_boxes["count"] += 1
            self.text_boxes["chars"] += sum(len(l["text"]) for l in lines)
            for l in lines:
                if has_contact(l["text"]):
                    self.text_boxes["has_contact"] = True
                if looks_like_heading(l["text"], l["style"], l["bold"]):
                    self.text_boxes["has_heading"] = True
        pb.box(lines)


def _int_hex(v):
    try:
        return int(str(v).strip(), 16)
    except (TypeError, ValueError):
        return None


def _extent(anchor):
    for c in anchor:
        if _local(c) == "extent":
            cx = _int(c.get("cx"), 0)
            cy = _int(c.get("cy"), 0)
            if cx > 0 and cy > 0:
                return (cx, cy)
    return None


def _vml_color(v):
    v = (v or "").strip().split()[0] if (v or "").strip() else ""
    named = {"white": "FFFFFF", "black": "000000"}
    if v.lower() in named:
        return named[v.lower()]
    return v.lstrip("#")


def _vml_extent(shape):
    style = shape.get("style") or ""
    dims = {}
    for part in style.split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            k = k.strip().lower()
            m = re.match(r"\s*([\d.]+)\s*(pt|in|px|cm|mm)?", v)
            if k in ("width", "height") and m:
                n = float(m.group(1))
                unit = m.group(2) or "px"
                emu = {"pt": EMU_PER_PT, "in": 914400, "px": 9525, "cm": 360000, "mm": 36000}[unit]
                dims[k] = int(n * emu)
    if "width" in dims and "height" in dims:
        return (dims["width"], dims["height"])
    return None


def shape_filled(wsp):
    """True when a DrawingML shape has a visible non-white fill."""
    sppr = None
    style = None
    for c in wsp:
        if _local(c) == "spPr":
            sppr = c
        elif _local(c) == "style":
            style = c
    if sppr is not None:
        for c in sppr:
            ln = _local(c)
            if ln == "noFill":
                return False
            if ln in ("gradFill", "blipFill", "pattFill"):
                return True
            if ln == "solidFill":
                for clr in c:
                    cl = _local(clr)
                    val = clr.get("val") or ""
                    if cl == "srgbClr":
                        return _colored(val)
                    if cl == "schemeClr":
                        return val.lower() not in ("bg1", "lt1", "light1", "background1")
                    if cl == "prstClr":
                        return val.lower() != "white"
                    return True
                return True
    if style is not None:
        for c in style:
            if _local(c) == "fillRef":
                return (c.get("idx") or "0") != "0"
    return False


def _prescan_backgrounds(roots, page_emu):
    """True when a page colour or a sizeable coloured shape/picture could sit behind white text."""
    for root in roots:
        for el in iter_no_fallback(root):
            ln = _local(el)
            ns = _ns(el)
            if ln == "background" and ns in W_NS and _colored(_attr(el, "color")):
                return True
            if ln == "anchor" and ns in WP_NS:
                ext = _extent(el)
                big = ext and min(ext) >= BACKGROUND_SHAPE_MIN_EMU
                if not big:
                    continue
                behind = _on_attr(el.get("behindDoc"))
                for sub in iter_no_fallback(el):
                    sl = _local(sub)
                    # Filled text boxes are handled where their own text is read; only plain
                    # shapes (banners, sidebars) count as a background for other text.
                    if sl == "wsp" and shape_filled(sub) and not any(_local(x) == "txbx" for x in sub):
                        return True
                    if sl == "pic" and behind:
                        return True
            if ns == V_NS and ln in ("rect", "roundrect", "shape", "oval"):
                ext = _vml_extent(el)
                if ext and min(ext) >= BACKGROUND_SHAPE_MIN_EMU and _colored(_vml_color(el.get("fillcolor"))) \
                        and not any(_local(x) == "textbox" for x in el):
                    return True
    return False


# --- package helpers --------------------------------------------------------------------------------
def _find_name(z, name):
    if z.has(name):
        return name
    low = name.lower()
    for n in z.names():
        if n.lower() == low:
            return n
    return None


def _rels(z, part):
    """Relationships of one part: list of (type_suffix, target_part_or_None, external)."""
    d, base = posixpath.split(part)
    rel_name = _find_name(z, posixpath.join(d, "_rels", base + ".rels"))
    if not rel_name:
        return []
    root = z.read_xml(rel_name)
    out = []
    for el in root:
        if _local(el) != "Relationship":
            continue
        rtype = (el.get("Type") or "").rsplit("/", 1)[-1]
        target = el.get("Target") or ""
        external = (el.get("TargetMode") or "").lower() == "external"
        if external:
            out.append((rtype, None, True, el.get("Id")))
            continue
        if target.startswith("/"):
            resolved = target.lstrip("/")
        else:
            resolved = posixpath.normpath(posixpath.join(d, target))
        out.append((rtype, _find_name(z, resolved), False, el.get("Id")))
    return out


def _optional_xml(z, part, doc, label):
    """Parse a supporting part (styles, numbering, headers, comments, app.xml). A damaged one is
    skipped with a warning; a DTD/entity declaration or a size refusal still refuses the whole file."""
    if not part:
        return None
    try:
        return z.read_xml(part)
    except RefusedInput as e:
        if e.code != "corrupt_file":
            raise
        doc["warnings"].append("the %s part could not be read and was skipped" % label)
        return None


def _natural_key(name):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name or "")]


def _first_sectpr(body):
    for el in iter_no_fallback(body):
        if _local(el) == "sectPr":
            return el
    return None


def read_docx(data, doc, ctx, encrypted_office=False):
    """Fill `doc` from .docx bytes. Raises RefusedInput for safety refusals (caught by the caller).
    `ctx` is the ingest Context (text statistics and hidden-text samples)."""
    sig = doc["signals"]
    if encrypted_office:
        sig["encrypted"] = True
        raise RefusedInput("encrypted", "this Word file is password protected; remove the password "
                                        "(File > Info > Protect Document) and upload it again")
    z = SafeZip(data)
    main = None
    pkg_rels = _rels(z, "")
    for rtype, target, external, _rid in pkg_rels:
        if rtype == "officeDocument" and target:
            main = target
            break
    if main is None:
        main = _find_name(z, "word/document.xml")
    if main is None:
        raise RefusedInput("corrupt_file", "no Word document part was found inside the file")
    root = z.read_xml(main)
    body = None
    for c in root:
        if _local(c) == "body":
            body = c
    if body is None:
        raise RefusedInput("corrupt_file", "the Word document has no body")
    rels = _rels(z, main)

    def part_of(kind):
        for rtype, target, external, _rid in rels:
            if rtype == kind and target:
                return target
        return None

    styles_part = part_of("styles") or _find_name(z, "word/styles.xml")
    styles = Styles(_optional_xml(z, styles_part, doc, "styles"))
    numbering_part = part_of("numbering") or _find_name(z, "word/numbering.xml")
    numbering = Numbering(_optional_xml(z, numbering_part, doc, "list numbering"))

    # Page size for "large image" checks.
    sect = _first_sectpr(body)
    pg = _child(sect, "pgSz")
    w = _int(_attr(pg, "w"), DEFAULT_PAGE_TWIPS[0]) or DEFAULT_PAGE_TWIPS[0]
    h = _int(_attr(pg, "h"), DEFAULT_PAGE_TWIPS[1]) or DEFAULT_PAGE_TWIPS[1]
    page_emu = (w * EMU_PER_TWIP, h * EMU_PER_TWIP)

    hf_parts = []
    for rtype, target, external, _rid in rels:
        if rtype in ("header", "footer") and target:
            hf_parts.append((rtype, target))
    hf_parts = sorted(set(hf_parts), key=lambda t: (0 if t[0] == "header" else 1, _natural_key(t[1])))
    hf_roots = []
    for kind, part in hf_parts:
        hroot = _optional_xml(z, part, doc, kind)
        if hroot is not None:
            hf_roots.append((kind, part, hroot))

    colored = _prescan_backgrounds([root] + [r for _, _, r in hf_roots], page_emu)
    walker = DocxWalker(styles, numbering, page_emu, colored)
    collector = Collector(ctx.stats)
    walker.collector = collector

    lines = walker.container(body, "body")
    walker.fields = []
    walker.count_structure = False
    header_footer = []
    seen = set()
    for kind, part, hroot in hf_roots:
        walker.fields = []
        for ln in walker.container(hroot, kind):
            key = (kind, ln["text"])
            if key in seen:
                continue
            seen.add(key)
            header_footer.append({"where": kind, "text": ln["text"]})

    if len(lines) > MAX_LINES:
        doc["warnings"].append("text truncated to the first %d lines" % MAX_LINES)
        lines = lines[:MAX_LINES]
    doc["lines"] = lines
    doc["header_footer"] = header_footer
    doc["method"] = "docx-xml"

    # Structure facts that do not depend on reading order.
    tracked = 0
    ole_extra = 0
    multi_col = False
    for r in [root] + [hr for _, _, hr in hf_roots]:
        for el in iter_no_fallback(r):
            ln = _local(el)
            ns = _ns(el)
            if ns in W_NS and ln in TRACKED_TAGS:
                tracked += 1
            elif ln == "OLEObject":
                ole_extra += 1
            elif ln == "cols" and ns in W_NS:
                num = _int(_attr(el, "num"), 1) or 1
                cols = [c for c in el if _local(c) == "col"]
                if num > 1 or len(cols) > 1:
                    multi_col = True
    comments = 0
    cpart = part_of("comments")
    if cpart:
        croot = _optional_xml(z, cpart, doc, "comments")
        if croot is not None:
            comments = sum(1 for c in croot if _local(c) == "comment")
    fields = dict(walker.field_counts)
    fields["ole"] = max(fields["ole"], ole_extra)

    sig["tables"] = walker.tables
    sig["text_boxes"] = walker.text_boxes
    sig["images"] = walker.images
    sig["columns"]["docx_multi_column"] = multi_col
    sig["hidden_text"]["vanish"] = collector.hidden["vanish"]
    sig["hidden_text"]["white"] = collector.hidden["white"]
    sig["hidden_text"]["tiny"] = collector.hidden["tiny"]
    sig["caps_formatting"] = collector.caps_paragraphs
    sig["fields"] = fields
    sig["tracked_changes"] = tracked
    sig["comments"] = comments
    sig["symbols"] = walker.symbols
    sig["tab_merged_tokens"] = collector.tab_merged
    ctx.hidden_samples.extend(collector.hidden_samples)

    # docProps/app.xml: page count "as last saved by Word" and the authoring application.
    app_part = None
    for rtype, target, external, _rid in pkg_rels:
        if rtype == "extended-properties" and target:
            app_part = target
    app_part = app_part or _find_name(z, "docProps/app.xml")
    pages = None
    if app_part:
        app = _optional_xml(z, app_part, doc, "document properties")
        if app is not None:
            for el in app:
                ln = _local(el)
                if ln == "Pages":
                    pages = _int(el.text)
                elif ln == "Application" and el.text:
                    doc["creator"] = re.sub(r"\s+", " ", el.text).strip()[:80] or None
    if pages is None:
        # No app.xml: fall back to where Word last broke pages, then to explicit page breaks.
        if walker.rendered_breaks:
            pages = walker.rendered_breaks + 1
        elif walker.page_breaks:
            pages = walker.page_breaks + 1
    doc["pages"] = pages if (pages is None or pages > 0) else None
    if doc.get("creator"):
        m = DESIGN_TOOL_RE.search(doc["creator"])
        if m:
            sig["design_tool"] = DESIGN_TOOL_NAMES[m.group(1).lower()]

    if walker.alt_chunks:
        doc["warnings"].append("%d imported content chunk(s) (altChunk) could not be read; parsers often skip them too"
                               % walker.alt_chunks)
    if walker.placeholders:
        doc["warnings"].append("%d template placeholder prompt(s) left in content controls" % walker.placeholders)
    if walker.depth_warning:
        doc["warnings"].append("very deeply nested content was skipped")
    if any(n.lower().endswith("vbaproject.bin") for n in z.names()):
        doc["warnings"].append("the file contains macros; they were not run")
    return doc
