"""Interpret PDF content streams: text for the built-in reader plus invisible-text facts.

Positions are tracked in the text-matrix coordinate space (user space before the CTM):
- a new output line starts when a show happens at a y that differs from the current line by more
  than LINE_SHIFT_EM of the font size (Td/TD/T*/'/" and Tm all move y);
- a space is inserted when a same-line move (Td, Tm) or a TJ offset leaves a gap wider than
  WORD_GAP_EM of the font size after the advance of the glyphs already shown (widths come from the
  font), so glyph-by-glyph positioning (Chrome/Skia) does not turn into "A v e r y".
It is the low-confidence fallback reader: simple fonts and Type0 fonts with ToUnicode maps.

Invisible text: render mode 3 or 7, or white fill before any non-white fill, shading or image was
painted on the page (white text on a coloured banner is design, not hiding).
"""
from hp.ingest.pdf_lex import Lexer, Name, Op, Ref, ARR_OPEN, ARR_CLOSE, DICT_OPEN, DICT_CLOSE, EOF
from hp.ingest.pdf_objects import FontDecoder

MAX_OPS_PER_PAGE = 400000
WHITE = 0.96
WORD_GAP_EM = 0.15          # a gap wider than this (in em) between glyph runs is a word space
LINE_SHIFT_EM = 0.4         # a y change larger than this (in em) starts a new line
TJ_GAP = -150               # TJ offsets below this (thousandths of an em) are word spaces


class PageText(object):
    def __init__(self):
        self.lines = []           # [[(text, hidden_bool), ...], ...]
        self.text_ops = 0
        self.invisible_ops = 0
        self.white_ops = 0
        self.images = 0
        self.unmapped = 0


class _GState(object):
    __slots__ = ("tr", "fill_white")

    def __init__(self):
        self.tr = 0
        self.fill_white = False

    def copy(self):
        g = _GState()
        g.tr, g.fill_white = self.tr, self.fill_white
        return g


class _TextState(object):
    """Text state and the current line origin for one content stream."""

    def __init__(self):
        self.font = None
        self.size = 1.0
        self.leading = 0.0
        self.char_space = 0.0
        self.word_space = 0.0
        self.hscale = 1.0
        self.a = 1.0            # text matrix x scale
        self.d = 1.0            # text matrix y scale
        self.lx = 0.0           # line origin (user space)
        self.ly = 0.0
        self.adv = 0.0          # advance since the line origin (text space units)
        self.gap = False        # a word gap is pending before the next glyphs


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _is_white(op, vals):
    if op == "g" and len(vals) >= 1:
        return vals[-1] >= WHITE
    if op == "rg" and len(vals) >= 3:
        return all(v >= WHITE for v in vals[-3:])
    if op == "k" and len(vals) >= 4:
        return all(v <= 1 - WHITE for v in vals[-4:])
    if op in ("sc", "scn"):
        if len(vals) == 1:
            return vals[0] >= WHITE
        if len(vals) == 3:
            return all(v >= WHITE for v in vals)
        if len(vals) == 4:
            return all(v <= 1 - WHITE for v in vals)
    return False


class Interpreter(object):
    def __init__(self, pdf, budget=None):
        self.pdf = pdf
        self.budget = budget
        self._font_cache = {}

    def _fonts(self, resources):
        fonts = {}
        res = self.pdf.resolve(resources)
        fdict = self.pdf.resolve(res.get("Font")) if isinstance(res, dict) else None
        if isinstance(fdict, dict):
            for name, ref in fdict.items():
                key = ref if isinstance(ref, Ref) else id(ref)
                if key not in self._font_cache:
                    self._font_cache[key] = FontDecoder(self.pdf, self.pdf.resolve(ref))
                fonts[name] = self._font_cache[key]
        return fonts

    def _xobjects(self, resources):
        res = self.pdf.resolve(resources)
        xd = self.pdf.resolve(res.get("XObject")) if isinstance(res, dict) else None
        return xd if isinstance(xd, dict) else {}

    def page(self, page):
        return self.run_stream(self.pdf.page_content(page), page.get("_res"))

    def run_stream(self, data, resources=None):
        out = PageText()
        state = {"bg": False, "line": [], "line_y": None, "end": None}
        self._run(data, resources, out, state, 0)
        if state["line"]:
            out.lines.append(state["line"])
        return out

    # -- helpers ---------------------------------------------------------------------------------------
    @staticmethod
    def _newline(out, state):
        if state["line"]:
            out.lines.append(state["line"])
        state["line"] = []

    def _show(self, out, state, ts, g, pieces):
        """Show strings (bytes) and TJ offsets (numbers) at the current position."""
        em = abs(ts.size * ts.d) or 1.0
        if state["line_y"] is None:
            state["line_y"] = ts.ly
        elif abs(ts.ly - state["line_y"]) > LINE_SHIFT_EM * em:
            self._newline(out, state)
            state["line_y"] = ts.ly
            ts.gap = False
        invisible = g.tr in (3, 7)
        white = (not invisible) and g.fill_white and not state["bg"] and g.tr in (0, 2, 4, 6)
        hidden = invisible or white
        out.text_ops += 1
        if invisible:
            out.invisible_ops += 1
        if white:
            out.white_ops += 1
        line = state["line"]
        for piece in pieces:
            if _num(piece):
                if piece < TJ_GAP:
                    ts.gap = True
                ts.adv -= piece / 1000.0 * ts.size * ts.hscale
                continue
            if not isinstance(piece, bytes) or not piece:
                continue
            if ts.font is None:
                try:
                    text = piece.decode("cp1252")
                except UnicodeDecodeError:
                    text = piece.decode("latin-1")
                width, spaces = 500.0 * len(piece), piece.count(b" ")
            else:
                text, width, spaces = ts.font.decode_ex(piece)
            if not text:
                continue
            if ts.gap and line and not line[-1][0].endswith(" ") and not text.startswith(" "):
                line.append((" ", hidden))
            ts.gap = False
            line.append((text, hidden))
            if "\ufffd" in text:
                out.unmapped += text.count("\ufffd")
            ts.adv += (width / 1000.0 * ts.size + ts.char_space * len(text) + ts.word_space * spaces) * ts.hscale
        state["end"] = (ts.lx + ts.adv * ts.a, ts.ly, abs(ts.size * ts.a) or 1.0, 1.0 if ts.a >= 0 else -1.0)

    @staticmethod
    def _move_to(state, ts, x, y):
        """Start a new line origin at (x, y). When it stays on the line of the last glyphs shown and
        leaves a gap after where they ended (state["end"], kept across BT/ET), a word space is due."""
        end = state.get("end")
        if end is not None:
            end_x, end_y, end_em, direction = end
            if abs(y - end_y) <= LINE_SHIFT_EM * end_em and (x - end_x) * direction > WORD_GAP_EM * end_em:
                ts.gap = True
        ts.lx, ts.ly, ts.adv = x, y, 0.0

    # -- the operator loop -----------------------------------------------------------------------------
    def _run(self, data, resources, out, state, depth):
        if not data or depth > 6:
            return
        fonts = self._fonts(resources) if resources is not None else {}
        xobjs = self._xobjects(resources) if resources is not None else {}
        lex = Lexer(data)
        operands = []
        g = _GState()
        gstack = []
        ts = _TextState()
        ops = 0
        while True:
            tok, _s, _e = lex.next()
            if tok is EOF:
                break
            ops += 1
            if ops > MAX_OPS_PER_PAGE or (ops % 5000 == 0 and self.budget is not None and self.budget.expired()):
                break
            if tok is ARR_OPEN:
                arr = []
                level = 0
                while True:
                    t2, _a, _b = lex.next()
                    if t2 is EOF:
                        break
                    if t2 is ARR_CLOSE:
                        if level == 0:
                            break
                        level -= 1
                        continue
                    if t2 is ARR_OPEN:
                        level += 1
                        continue
                    if len(arr) < 100000:
                        arr.append(t2)
                operands.append(arr)
                continue
            if tok is DICT_OPEN:
                level = 1          # inline property dictionaries (marked content): skip to the matching >>
                while level:
                    t2, _a, _b = lex.next()
                    if t2 is EOF:
                        break
                    if t2 is DICT_OPEN:
                        level += 1
                    elif t2 is DICT_CLOSE:
                        level -= 1
                operands.append({})
                continue
            if not isinstance(tok, Op):
                operands.append(tok)
                if len(operands) > 64:
                    operands = operands[-64:]
                continue
            op = str(tok)
            nums = [float(x) for x in operands if _num(x)]
            if op == "BT":
                ts.a, ts.d, ts.adv, ts.lx, ts.ly = 1.0, 1.0, 0.0, 0.0, 0.0
            elif op == "Tf":
                if len(operands) >= 2 and isinstance(operands[-2], Name):
                    ts.font = fonts.get(operands[-2])
                    if _num(operands[-1]):
                        ts.size = float(operands[-1])
            elif op == "Tr":
                if nums:
                    g.tr = int(nums[-1])
            elif op == "Tc":
                if nums:
                    ts.char_space = nums[-1]
            elif op == "Tw":
                if nums:
                    ts.word_space = nums[-1]
            elif op == "Tz":
                if nums:
                    ts.hscale = nums[-1] / 100.0
            elif op == "TL":
                if nums:
                    ts.leading = nums[-1]
            elif op in ("Td", "TD"):
                if len(nums) >= 2:
                    tx, ty = nums[-2], nums[-1]
                    if op == "TD":
                        ts.leading = -ty
                    self._move_to(state, ts, ts.lx + tx * ts.a, ts.ly + ty * ts.d)
            elif op == "Tm":
                if len(nums) >= 6:
                    a, _b, _c, d, e, f = nums[-6:]
                    ts.a = a or 1.0
                    ts.d = d or ts.a
                    self._move_to(state, ts, e, f)
            elif op == "T*":
                self._move_to(state, ts, ts.lx, ts.ly - (ts.leading or ts.size) * ts.d)
            elif op in ("Tj", "'", '"'):
                if op in ("'", '"'):
                    if op == '"' and len(nums) >= 2:
                        ts.word_space, ts.char_space = nums[0], nums[1]
                    self._move_to(state, ts, ts.lx, ts.ly - (ts.leading or ts.size) * ts.d)
                if operands and isinstance(operands[-1], bytes):
                    self._show(out, state, ts, g, [operands[-1]])
            elif op == "TJ":
                if operands and isinstance(operands[-1], list):
                    self._show(out, state, ts, g, operands[-1])
            elif op in ("g", "rg", "k", "sc", "scn"):
                pattern = bool(operands) and isinstance(operands[-1], Name)
                g.fill_white = (not pattern) and _is_white(op, nums)
            elif op == "cs":
                g.fill_white = False
            elif op == "q":
                if len(gstack) < 64:
                    gstack.append(g.copy())
            elif op == "Q":
                if gstack:
                    g = gstack.pop()
            elif op in ("f", "F", "f*", "B", "B*", "b", "b*"):
                if not g.fill_white:
                    state["bg"] = True
            elif op == "sh":
                state["bg"] = True
            elif op == "BI":
                state["bg"] = True                   # inline image: skip its binary data
                out.images += 1
                idx = data.find(b"ID", lex.pos)
                end = data.find(b"EI", idx + 2 if idx >= 0 else lex.pos)
                lex.pos = (end + 2) if end >= 0 else len(data)
            elif op == "Do":
                if operands and isinstance(operands[-1], Name):
                    ref = xobjs.get(operands[-1])
                    xo = self.pdf.resolve(ref)
                    if isinstance(xo, dict):
                        sub = xo.get("Subtype")
                        if sub == "Image":
                            state["bg"] = True
                            out.images += 1
                        elif sub == "Form":
                            num = self.pdf.stream_of(ref)
                            if num is not None:
                                inner = self.pdf.stream_data(num)
                                res = xo.get("Resources") if "Resources" in xo else resources
                                self._run(inner, res, out, state, depth + 1)
            operands = []


def lines_text(page_text, include_hidden):
    """Join a PageText's pieces into strings (optionally without hidden pieces)."""
    out = []
    for line in page_text.lines:
        out.append("".join(t for t, hidden in line if include_hidden or not hidden))
    return out


def hidden_texts(page_text):
    """Contiguous hidden stretches of text, one per unbroken run on a line."""
    out = []
    for line in page_text.lines:
        buf = []
        for t, hidden in line:
            if hidden:
                buf.append(t)
            elif buf:
                out.append("".join(buf))
                buf = []
        if buf:
            out.append("".join(buf))
    return [s for s in out if s.strip()]
