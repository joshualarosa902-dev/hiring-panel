"""A small, defensive PDF tokenizer and object parser (standard library only).

It understands enough PDF syntax to walk pages, fonts and content streams of ordinary resumes.
It never raises on malformed input: unknown bytes become Op tokens, unbalanced structures end at EOF,
and nesting is capped.
"""
import re

MAX_NEST = 64


class Name(str):
    """A PDF name object (/Font -> Name('Font'))."""
    __slots__ = ()


class Op(str):
    """A bare keyword: content-stream operators, obj/endobj/stream, true/false/null, R."""
    __slots__ = ()


class Ref(tuple):
    """An indirect reference (num, gen)."""
    __slots__ = ()

    def __new__(cls, num, gen):
        return tuple.__new__(cls, (num, gen))

    @property
    def num(self):
        return self[0]


class _Marker(object):
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return self.name


DICT_OPEN = _Marker("<<")
DICT_CLOSE = _Marker(">>")
ARR_OPEN = _Marker("[")
ARR_CLOSE = _Marker("]")
BRACE = _Marker("{}")
EOF = _Marker("EOF")

_TOKEN_RE = re.compile(
    rb"(?P<ws>[\x00\t\n\x0c\r ]+)"
    rb"|(?P<comment>%[^\r\n]*)"
    rb"|(?P<name>/[^\x00\t\n\x0c\r ()<>\[\]{}/%]*)"
    rb"|(?P<dopen><<)|(?P<dclose>>>)"
    rb"|(?P<hex><[0-9A-Fa-f\x00\t\n\x0c\r ]*>)"
    rb"|(?P<lpar>\()"
    rb"|(?P<aopen>\[)|(?P<aclose>\])"
    rb"|(?P<brace>[{}])"
    rb"|(?P<regular>[^\x00\t\n\x0c\r ()<>\[\]{}/%]+)"
    rb"|(?P<other>.)", re.S)
_NUMBER_RE = re.compile(rb"^[+-]?(?:\d+\.?\d*|\.\d+)$")
_INT_RE = re.compile(rb"^[+-]?\d+$")
_STRING_SPECIAL = re.compile(rb"[()\\]")
_ESCAPES = {ord("n"): b"\n", ord("r"): b"\r", ord("t"): b"\t", ord("b"): b"\b", ord("f"): b"\f",
            ord("("): b"(", ord(")"): b")", ord("\\"): b"\\"}
_NAME_ESC = re.compile(rb"#([0-9A-Fa-f]{2})")


def _decode_name(raw):
    try:
        raw = _NAME_ESC.sub(lambda m: bytes([int(m.group(1), 16)]), raw)
        return Name(raw.decode("latin-1"))
    except Exception:  # pragma: no cover - latin-1 decodes every byte
        return Name("")


def read_literal(data, pos, end):
    """Parse a literal string starting just after '('. Returns (bytes, new_pos)."""
    out = bytearray()
    depth = 1
    while pos < end:
        m = _STRING_SPECIAL.search(data, pos, end)
        if not m:
            out += data[pos:end]
            return bytes(out), end
        out += data[pos:m.start()]
        c = data[m.start()]
        pos = m.start() + 1
        if c == 0x28:      # (
            depth += 1
            out.append(c)
        elif c == 0x29:    # )
            depth -= 1
            if depth == 0:
                return bytes(out), pos
            out.append(c)
        else:              # backslash escape
            if pos >= end:
                break
            e = data[pos]
            if e in _ESCAPES:
                out += _ESCAPES[e]
                pos += 1
            elif 0x30 <= e <= 0x37:
                j = pos
                while j < end and j < pos + 3 and 0x30 <= data[j] <= 0x37:
                    j += 1
                out.append(int(data[pos:j], 8) & 0xFF)
                pos = j
            elif e == 0x0D:
                pos += 1
                if pos < end and data[pos] == 0x0A:
                    pos += 1
            elif e == 0x0A:
                pos += 1
            else:
                out.append(e)
                pos += 1
    return bytes(out), end


def _hex(raw):
    digits = re.sub(rb"[^0-9A-Fa-f]", b"", raw)
    if len(digits) % 2:
        digits += b"0"
    try:
        return bytes.fromhex(digits.decode("ascii"))
    except ValueError:
        return b""


class Lexer(object):
    """Yields (token, start, end). Strings are bytes; numbers int/float; names Name; keywords Op."""

    def __init__(self, data, pos=0, end=None):
        self.data = data
        self.pos = pos
        self.end = len(data) if end is None else min(end, len(data))

    def next(self):
        data, end = self.data, self.end
        while self.pos < end:
            m = _TOKEN_RE.match(data, self.pos, end)
            if not m:   # pragma: no cover - "other" matches any byte
                self.pos += 1
                continue
            kind = m.lastgroup
            start = self.pos
            self.pos = m.end()
            if kind in ("ws", "comment"):
                continue
            if kind == "name":
                return _decode_name(m.group()[1:]), start, self.pos
            if kind == "dopen":
                return DICT_OPEN, start, self.pos
            if kind == "dclose":
                return DICT_CLOSE, start, self.pos
            if kind == "hex":
                return _hex(m.group()[1:-1]), start, self.pos
            if kind == "lpar":
                s, self.pos = read_literal(data, self.pos, end)
                return s, start, self.pos
            if kind == "aopen":
                return ARR_OPEN, start, self.pos
            if kind == "aclose":
                return ARR_CLOSE, start, self.pos
            if kind == "brace":
                return BRACE, start, self.pos
            raw = m.group()
            if kind == "regular" and _NUMBER_RE.match(raw):
                try:
                    if _INT_RE.match(raw):
                        return int(raw), start, self.pos
                    return float(raw), start, self.pos
                except ValueError:  # pragma: no cover
                    return Op(raw.decode("latin-1")), start, self.pos
            return Op(raw.decode("latin-1")), start, self.pos
        return EOF, self.pos, self.pos


class Parser(object):
    """Parses PDF objects from a Lexer, with one level of token push-back for references."""

    def __init__(self, data, pos=0, end=None):
        self.lex = Lexer(data, pos, end)
        self.buf = []

    def tok(self):
        if self.buf:
            return self.buf.pop()
        return self.lex.next()

    def push(self, t):
        self.buf.append(t)

    def value(self, depth=0):
        """Return (value, start, end); value may be a marker (ARR_CLOSE, DICT_CLOSE, EOF)."""
        t = self.tok()
        v, s, e = t
        if depth > MAX_NEST:
            return EOF, s, e
        if v is DICT_OPEN:
            d = {}
            while True:
                k, ks, ke = self.tok()
                if k is DICT_CLOSE or k is EOF:
                    return d, s, ke
                if isinstance(k, Name):
                    val, vs, ve = self.value(depth + 1)
                    if val is DICT_CLOSE or val is EOF:
                        d[k] = None
                        return d, s, ve
                    d[k] = val
                # anything else inside a dict is junk; skip it
        if v is ARR_OPEN:
            arr = []
            while True:
                val, vs, ve = self.value(depth + 1)
                if val is ARR_CLOSE or val is EOF:
                    return arr, s, ve
                if val is DICT_CLOSE:
                    continue
                arr.append(val)
        if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
            t2 = self.tok()
            if isinstance(t2[0], int) and t2[0] >= 0:
                t3 = self.tok()
                if isinstance(t3[0], Op) and t3[0] == "R":
                    return Ref(v, t2[0]), s, t3[2]
                self.push(t3)
            self.push(t2)
        if isinstance(v, Op):
            if v == "true":
                return True, s, e
            if v == "false":
                return False, s, e
            if v == "null":
                return None, s, e
        return v, s, e


def decode_text_string(b):
    """Decode a PDF text string (Info dict values): UTF-16BE with BOM, UTF-8 with BOM, else Latin-1."""
    if not isinstance(b, (bytes, bytearray)):
        return None
    try:
        if b[:2] == b"\xfe\xff":
            return b[2:].decode("utf-16-be", "replace")
        if b[:2] == b"\xff\xfe":
            return b[2:].decode("utf-16-le", "replace")
        if b[:3] == b"\xef\xbb\xbf":
            return b[3:].decode("utf-8", "replace")
        return b.decode("latin-1")
    except Exception:  # pragma: no cover
        return None
