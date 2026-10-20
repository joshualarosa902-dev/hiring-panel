"""A small pure-Python PDF writer (last resort before "skip").

Uses the PDF base-14 fonts Helvetica / Helvetica-Bold / Helvetica-Oblique with WinAnsiEncoding, so no
font files are needed. Helvetica has the same advance widths as Arial, so the Word file, the Chrome
PDF and this writer break lines in the same places; the same layout object also estimates the page
count for any engine.

Limits: Western European (Windows-1252) text only. A letter outside that set raises Unencodable and
the caller skips this engine (no '?' boxes in a candidate's name). Pictographs are dropped.
Text is always drawn in visible colors; this writer never makes white, tiny or invisible text.
"""
import re
import unicodedata
import zlib

# Helvetica advance widths for WinAnsi codes 32..255 (from the Adobe AFM files; Arial matches).
_W_REG = ("278,278,355,556,556,889,667,191,333,333,389,584,278,333,278,278,556,556,556,556,556,556,556,556,556,556,278,278,584,584,584,556,"
          "1015,667,667,722,722,667,611,778,722,278,500,667,556,833,722,778,667,778,722,667,611,722,667,944,667,667,611,278,278,278,469,556,"
          "333,556,556,500,556,556,278,556,556,222,222,500,222,833,556,556,556,556,333,500,278,556,500,722,500,500,500,334,260,334,584,278,"
          "556,0,222,556,333,1000,556,556,333,1000,667,333,1000,0,611,0,0,222,222,333,333,350,556,1000,333,1000,500,333,944,0,500,667,"
          "278,333,556,556,556,556,260,556,333,737,370,556,584,333,737,333,400,584,333,333,333,556,537,278,333,333,365,556,834,834,834,611,"
          "667,667,667,667,667,667,1000,722,667,667,667,667,278,278,278,278,722,722,778,778,778,778,778,584,778,722,722,722,722,667,667,611,"
          "556,556,556,556,556,556,889,500,556,556,556,556,278,278,278,278,556,556,556,556,556,556,556,584,611,556,556,556,556,500,556,500")
_W_BOLD = ("278,333,474,556,556,889,722,238,333,333,389,584,278,333,278,278,556,556,556,556,556,556,556,556,556,556,333,333,584,584,584,611,"
           "975,722,722,722,722,667,611,778,722,278,556,722,611,833,722,778,667,778,722,667,611,722,667,944,667,667,611,333,278,333,584,556,"
           "333,556,611,556,611,556,333,611,611,278,278,556,278,889,611,611,611,611,389,556,333,611,556,778,556,556,500,389,280,389,584,278,"
           "556,0,278,556,500,1000,556,556,333,1000,667,333,1000,0,611,0,0,278,278,500,500,350,556,1000,333,1000,556,333,944,0,500,667,"
           "278,333,556,556,556,556,280,556,333,737,370,556,584,333,737,333,400,584,333,333,333,611,556,278,333,333,365,556,834,834,834,611,"
           "722,722,722,722,722,722,1000,722,667,667,667,667,278,278,278,278,722,722,778,778,778,778,778,584,778,722,722,722,722,667,667,611,"
           "556,556,556,556,556,556,889,556,556,556,556,556,278,278,278,278,611,611,611,611,611,611,611,584,611,611,611,611,611,556,611,556")
WIDTHS = {"R": [int(v) for v in _W_REG.split(",")], "B": [int(v) for v in _W_BOLD.split(",")]}
WIDTHS["I"] = WIDTHS["R"]   # Helvetica-Oblique shares Helvetica's advance widths
FONT_NAMES = {"R": "Helvetica", "B": "Helvetica-Bold", "I": "Helvetica-Oblique"}
TRANSLIT = {"→": "->", "←": "<-", "≤": "<=", "≥": ">=", "−": "-", "‐": "-",
            "‑": "-", " ": " ", " ": " ", " ": " ", "​": "", "✓": "", "✕": "x"}


class Unencodable(Exception):
    """Raised when text holds a letter the WinAnsi fonts cannot show."""


def to_winansi(s, strict=False):
    out = bytearray()
    for ch in s or "":
        ch = TRANSLIT.get(ch, ch)
        try:
            out += ch.encode("cp1252")
        except UnicodeEncodeError:
            base = unicodedata.normalize("NFKD", ch).encode("cp1252", "ignore")
            cat = unicodedata.category(ch[:1] or " ")
            if strict or (cat[0] in "LN"):
                # A letter we cannot draw faithfully (e.g. Vietnamese or CJK): refuse the engine.
                raise Unencodable(ch)
            out += base  # symbols and emoji with no Latin form are dropped
    return bytes(out)


def text_width(b, style, size):
    w = WIDTHS.get(style, WIDTHS["R"])
    return sum(w[c - 32] if 32 <= c <= 255 else 500 for c in b) * size / 1000.0


def pdf_str(b):
    out = []
    for c in b:
        if c in (0x28, 0x29, 0x5C):
            out.append("\\" + chr(c))
        elif 32 <= c < 127:
            out.append(chr(c))
        else:
            out.append("\\%03o" % c)
    return "(" + "".join(out) + ")"


def rgb(hx):
    hx = (hx or "000000").lstrip("#")
    if not re.match(r"^[0-9A-Fa-f]{6}$", hx):
        hx = "000000"
    return tuple(int(hx[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def style_of(r):
    if r.get("b"):
        return "B"
    if r.get("i"):
        return "I"
    return "R"


def wrap_runs(runs, size, max_w):
    """Greedy word wrap over styled runs -> lines; a line is a list of (bytes, style, hl, color)."""
    words = []
    for r in runs:
        st = style_of(r)
        for tok in re.split(r"(\s+)", r.get("t") or ""):
            if tok == "":
                continue
            words.append((to_winansi(tok), st, bool(r.get("hl")), r.get("c"), tok.isspace()))
    lines, cur, cur_w = [], [], 0.0
    for b, st, hl, col, is_space in words:
        if is_space:
            if cur:
                cur.append((b" ", st, hl, col))
                cur_w += text_width(b" ", st, size)
            continue
        w = text_width(b, st, size)
        if cur and cur_w + w > max_w:
            while cur and cur[-1][0] == b" ":
                cur_w -= text_width(b" ", cur[-1][1], size)
                cur.pop()
            lines.append(cur)
            cur, cur_w = [], 0.0
        cur.append((b, st, hl, col))
        cur_w += w
    while cur and cur[-1][0] == b" ":
        cur.pop()
    if cur:
        lines.append(cur)
    return lines or [[]]


def segs_width(segs, size):
    return sum(text_width(b, st, size) for b, st, _hl, _c in segs)


class PdfLayout:
    """Places text on pages. Used to write the builtin PDF and to estimate fill for any engine."""

    def __init__(self, page_w, page_h, margin_pt, line=1.2):
        self.pw, self.ph = page_w, page_h
        self.m = margin_pt
        self.x0, self.x1 = self.m, self.pw - self.m
        self.width = self.x1 - self.x0
        self.line = line
        self.pages = [[]]
        self.links = [[]]
        self.y = self.ph - self.m

    # -- primitives ------------------------------------------------------------------------------
    def lh(self, size):
        return size * self.line

    def need(self, height):
        """Start a new page when the next `height` points would cross the bottom margin."""
        if self.y - height < self.m - 0.01:
            self.new_page()

    def new_page(self):
        self.pages.append([])
        self.links.append([])
        self.y = self.ph - self.m

    @staticmethod
    def _coalesce(segs):
        """Join neighbouring segments with the same style, highlight and color into one string, so each
        line is a few Tj operators (smaller file, friendlier to simple text extractors)."""
        out = []
        for bts, st, hl, col in segs:
            if out and out[-1][1:] == (st, hl, col):
                out[-1] = (out[-1][0] + bts, st, hl, col)
            else:
                out.append((bts, st, hl, col))
        return out

    def draw_segs(self, segs, size, x, baseline, color):
        cmds = []
        for bts, st, hl, col in self._coalesce(segs):
            if not bts:
                continue
            w = text_width(bts, st, size)
            if hl:
                cmds.append("q 1 0.95 0.64 rg %.2f %.2f %.2f %.2f re f Q" % (x, baseline - size * 0.22, w, size * 1.05))
            r, g, b = rgb(col or color)
            cmds.append("BT /F%s %.2f Tf %.3f %.3f %.3f rg %.2f %.2f Td %s Tj ET" % (st, size, r, g, b, x, baseline, pdf_str(bts)))
            x += w
        if cmds:
            self.pages[-1].append("\n".join(cmds))
        return x

    def fill_rect(self, x, y, w, h, color, radius=0):
        r, g, b = rgb(color)
        if radius <= 0:
            self.pages[-1].append("q %.3f %.3f %.3f rg %.2f %.2f %.2f %.2f re f Q" % (r, g, b, x, y, w, h))
            return
        k = 0.5523 * radius   # Bezier approximation of a rounded corner
        x1, y1 = x + w, y + h
        p = ("q %.3f %.3f %.3f rg %.2f %.2f m %.2f %.2f l %.2f %.2f %.2f %.2f %.2f %.2f c %.2f %.2f l "
             "%.2f %.2f %.2f %.2f %.2f %.2f c %.2f %.2f l %.2f %.2f %.2f %.2f %.2f %.2f c %.2f %.2f l "
             "%.2f %.2f %.2f %.2f %.2f %.2f c f Q") % (
            r, g, b, x + radius, y, x1 - radius, y, x1 - radius + k, y, x1, y + radius - k, x1, y + radius,
            x1, y1 - radius, x1, y1 - radius + k, x1 - radius + k, y1, x1 - radius, y1,
            x + radius, y1, x + radius - k, y1, x, y1 - radius + k, x, y1 - radius,
            x, y + radius, x, y + radius - k, x + radius - k, y, x + radius, y)
        self.pages[-1].append(p)

    def hline(self, x0, x1, y, width, color):
        r, g, b = rgb(color)
        self.pages[-1].append("q %.2f w %.3f %.3f %.3f RG %.2f %.2f m %.2f %.2f l S Q" % (width, r, g, b, x0, y, x1, y))

    def paragraph(self, runs, size, color, indent=0.0, width=None, after=0.0, bullet=None, keep=False):
        """Wrap and draw runs; returns the number of lines. `bullet` = (bytes, hanging_pt)."""
        width = (self.width - indent) if width is None else width
        lines = wrap_runs(runs, size, width)
        if keep:
            self.need(len(lines) * self.lh(size))
        for li, segs in enumerate(lines):
            self.need(self.lh(size))
            self.y -= self.lh(size)
            base = self.y + size * 0.22
            if bullet and li == 0:
                # Helvetica's bullet is small at body size; draw it a little larger, on the same baseline
                self.draw_segs([(bullet[0], "R", False, None)], size * 1.3, self.x0 + indent - bullet[1], base - size * 0.06, color)
            self.draw_segs(segs, size, self.x0 + indent, base, color)
        self.y -= after
        return len(lines)

    # -- resume ----------------------------------------------------------------------------------
    def place_resume(self, blocks, theme):
        t = theme
        body = t["body_pt"]
        for i, bl in enumerate(blocks):
            k = bl["k"]
            nxt = blocks[i + 1] if i + 1 < len(blocks) else None
            if k == "name":
                size = t["name_pt"]
                bts = to_winansi(bl["text"], strict=True)
                w = text_width(bts, "B", size)
                self.y -= size * 0.95
                self.draw_segs([(bts, "B", False, None)], size, (self.pw - w) / 2, self.y, t["accent"])
                self.y -= size * 0.25 + 2.5
            elif k == "headline":
                size = t["headline_pt"]
                bts = to_winansi(bl["text"])
                self.y -= self.lh(size)
                self.draw_segs([(bts, "R", False, None)], size, (self.pw - text_width(bts, "R", size)) / 2,
                               self.y + size * 0.22, t["muted"])
                self.y -= 1
            elif k == "contact":
                self._contact(bl, t)
            elif k == "h":
                size = t["heading_pt"]
                self.need(t["heading_before_pt"] + self.lh(size) + 3 + 3 * self.lh(body))
                self.y -= t["heading_before_pt"] + self.lh(size)
                bts = to_winansi(bl["text"].upper())
                r, g, b = rgb(t["accent"])
                # 0.6 pt letter spacing, matching the HTML/Word headings
                self.pages[-1].append("BT /FB %.2f Tf 0.6 Tc %.3f %.3f %.3f rg %.2f %.2f Td %s Tj ET 0 Tc"
                                      % (size, r, g, b, self.x0, self.y + size * 0.22, pdf_str(bts)))
                ly = self.y - 1.5
                self.hline(self.x0, self.x1, ly, 0.75, t["rule"])
                self.y -= 1.5 + t["heading_after_pt"]
            elif k == "row":
                size = body
                if bl.get("first"):
                    follow = 2 if (nxt and nxt["k"] == "row") else 1
                    gap = 0 if (i and blocks[i - 1]["k"] == "h") else t["entry_before_pt"]
                    self.need(gap + (follow + 1) * self.lh(size))
                    self.y -= gap
                right = to_winansi(bl.get("right") or "")
                rw = text_width(right, "R", size)
                lines = wrap_runs(bl["left"], size, self.width - rw - 12)
                for li, segs in enumerate(lines):
                    self.need(self.lh(size))
                    self.y -= self.lh(size)
                    if li == 0 and right:
                        # trailing space: text extractors that concatenate strings keep a word break
                        segs = segs + [(b" ", "R", False, None)]
                    self.draw_segs(segs, size, self.x0, self.y + size * 0.22, t["ink"])
                    if li == 0 and right:
                        self.draw_segs([(right, "R", False, None)], size, self.x1 - rw, self.y + size * 0.22, t["ink"])
            elif k == "bullet":
                self.paragraph(bl["runs"], body, t["ink"], indent=t["bullet_indent_pt"], after=t["bullet_after_pt"],
                               bullet=(b"\x95", t["bullet_hanging_pt"]))
            elif k == "para":
                self.paragraph(bl["runs"], body, t["ink"], after=t["bullet_after_pt"])
        return self

    def _contact(self, bl, t):
        size = t["contact_pt"]
        sep = b"  |  "
        sep_w = text_width(sep, "R", size)
        rows, cur, cur_w = [], [], 0.0
        for part in bl["parts"]:
            bts = to_winansi(part["t"])
            w = text_width(bts, "R", size)
            if cur and cur_w + sep_w + w > self.width:
                rows.append((cur, cur_w))
                cur, cur_w = [], 0.0
            cur_w += (sep_w if cur else 0) + w
            cur.append((bts, w, part.get("url")))
        if cur:
            rows.append((cur, cur_w))
        for parts, total in rows:
            self.y -= self.lh(size)
            x = (self.pw - total) / 2
            segs = []
            cx = x
            for j, (bts, w, url) in enumerate(parts):
                if j:
                    segs.append((sep, "R", False, None))
                    cx += sep_w
                segs.append((bts, "R", False, None))
                if url:
                    self.links[-1].append((cx, self.y - 2, cx + w, self.y + size, url))
                cx += w
            self.draw_segs(segs, size, x, self.y + size * 0.22, t["muted"])
        self.y -= 3

    def fill(self):
        """(pages, share of the last page used)."""
        used = (self.ph - self.m) - self.y
        return len(self.pages), max(0.0, min(1.0, used / (self.ph - 2 * self.m)))


def write_pdf_bytes(layout, title, author, lang="en-US"):
    """Serialize a PdfLayout into PDF 1.4 bytes with a correct xref table."""
    objs = []

    def add(o):
        objs.append(o)
        return len(objs)

    font_ids = {}
    for key in ("R", "B", "I"):
        font_ids[key] = add("<< /Type /Font /Subtype /Type1 /BaseFont /%s /Encoding /WinAnsiEncoding >>" % FONT_NAMES[key])
    page_ids, pending = [], []
    for pi, cmds in enumerate(layout.pages):
        stream = zlib.compress("\n".join(cmds).encode("latin-1"), 9)
        cid = add(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(stream) + stream + b"\nendstream")
        annots = []
        for (x1, y1, x2, y2, url) in layout.links[pi]:
            try:
                target = pdf_str(to_winansi(url))
            except Unencodable:
                continue
            annots.append(add("<< /Type /Annot /Subtype /Link /Rect [%.2f %.2f %.2f %.2f] /Border [0 0 0] "
                              "/A << /S /URI /URI %s >> >>" % (x1, y1, x2, y2, target)))
        pid = add(None)
        pending.append((pid, cid, annots))
        page_ids.append(pid)
    pages_id = add(None)
    res = "<< /Font << %s >> >>" % " ".join("/F%s %d 0 R" % (k, v) for k, v in sorted(font_ids.items()))
    for pid, cid, annots in pending:
        a = (" /Annots [%s]" % " ".join("%d 0 R" % i for i in annots)) if annots else ""
        objs[pid - 1] = ("<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.2f %.2f] /Resources %s /Contents %d 0 R%s >>"
                         % (pages_id, layout.pw, layout.ph, res, cid, a))
    objs[pages_id - 1] = "<< /Type /Pages /Kids [%s] /Count %d >>" % (" ".join("%d 0 R" % p for p in page_ids), len(page_ids))
    lang_tag = lang if re.match(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})?$", lang or "") else "en-US"
    cat_id = add("<< /Type /Catalog /Pages %d 0 R /Lang (%s) >>" % (pages_id, lang_tag))
    info_id = add("<< /Title %s /Author %s >>" % (pdf_str(to_winansi(title)), pdf_str(to_winansi(author))))
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        body = o if isinstance(o, bytes) else o.encode("latin-1")
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, cat_id, info_id, xref)
    return bytes(out)
