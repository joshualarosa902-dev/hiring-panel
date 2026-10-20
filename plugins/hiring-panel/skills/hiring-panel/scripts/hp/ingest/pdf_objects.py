"""Minimal PDF object model for the built-in reader and the structure probe.

PdfDoc indexes "N G obj" definitions (skipping matches inside stream data), expands object streams,
finds the trailer (classic or cross-reference stream), resolves references, decodes stream filters
(Flate, ASCIIHex, ASCII85) with per-stream and total caps, walks the page tree and builds font
decoders (ToUnicode CMaps, simple encodings with /Differences). Broken files give partial results.
"""
import base64
import re
import unicodedata
import zlib

from hp.ingest.limits import MAX_PDF_STREAM, MAX_PDF_TOTAL
from hp.ingest.pdf_lex import Parser, Name, Op, Ref, EOF

OBJ_RE = re.compile(rb"(?<![0-9])(\d{1,10})[\x00\t\n\x0c\r ]+(\d{1,5})[\x00\t\n\x0c\r ]+obj\b")
MAX_OBJECTS = 200000
MAX_PAGES_WALK = 2000


def _get(d, key, default=None):
    if isinstance(d, dict):
        return d.get(key, default)
    return default


class PdfDoc(object):
    def __init__(self, data, budget=None):
        self.data = data
        self.budget = budget
        self.objects = {}            # num -> [value, (start, end) of raw stream data or None]
        self.trailer = {}
        self.inflated_total = 0
        self.warnings = []
        self.truncated_budget = False
        try:
            self._index()
            self._object_streams()
            self._find_trailer()
        except RecursionError:
            self.warnings.append("PDF structure nested too deeply; partial read")

    # -- indexing ----------------------------------------------------------------------------------
    def _expired(self):
        if self.budget is not None and self.budget.expired():
            self.truncated_budget = True
            return True
        return False

    def _index(self):
        data = self.data
        skip_until = 0
        count = 0
        for m in OBJ_RE.finditer(data):
            if m.start() < skip_until:
                continue
            count += 1
            if count > MAX_OBJECTS or (count % 200 == 0 and self._expired()):
                break
            num = int(m.group(1))
            p = Parser(data, m.end())
            val, _s, _e = p.value()
            nxt = p.tok()
            stream = None
            if isinstance(nxt[0], Op) and nxt[0] == "stream" and isinstance(val, dict):
                start = nxt[2]
                if data[start:start + 2] == b"\r\n":
                    start += 2
                elif data[start:start + 1] in (b"\n", b"\r"):
                    start += 1
                end = None
                length = val.get("Length")
                if isinstance(length, int) and length >= 0 and start + length <= len(data):
                    tail = data[start + length:start + length + 32]
                    if b"endstream" in tail:
                        end = start + length
                if end is None:
                    idx = data.find(b"endstream", start)
                    end = idx if idx >= 0 else len(data)
                    while end > start and data[end - 1:end] in (b"\n", b"\r"):
                        end -= 1
                stream = (start, end)
                skip_until = end
            if val is EOF:
                continue
            self.objects[num] = [val, stream]

    def _object_streams(self):
        for num in sorted(self.objects):
            val, stream = self.objects[num]
            if not (isinstance(val, dict) and val.get("Type") == "ObjStm" and stream):
                continue
            if self._expired():
                return
            raw = self.stream_data(num)
            if not raw:
                continue
            n = val.get("N")
            first = val.get("First")
            if not isinstance(n, int) or not isinstance(first, int) or n <= 0 or n > 100000:
                continue
            p = Parser(raw, 0, first)
            pairs = []
            for _ in range(n):
                a = p.tok()[0]
                b = p.tok()[0]
                if not isinstance(a, int) or not isinstance(b, int):
                    break
                pairs.append((a, b))
            for objnum, off in pairs:
                if objnum in self.objects:
                    continue
                vp = Parser(raw, first + off)
                v, _s, _e = vp.value()
                if v is not EOF:
                    self.objects[objnum] = [v, None]

    def _find_trailer(self):
        trailer = {}
        for m in re.finditer(rb"trailer", self.data):
            p = Parser(self.data, m.end())
            v, _s, _e = p.value()
            if isinstance(v, dict):
                trailer.update(v)
        for num in sorted(self.objects):
            val = self.objects[num][0]
            if isinstance(val, dict) and val.get("Type") == "XRef":
                for k in ("Root", "Info", "Encrypt"):
                    if k in val and k not in trailer:
                        trailer[k] = val[k]
        self.trailer = trailer

    # -- access ------------------------------------------------------------------------------------
    def resolve(self, v, depth=0):
        while isinstance(v, Ref) and depth < 32:
            entry = self.objects.get(v.num)
            v = entry[0] if entry else None
            depth += 1
        return v

    def stream_of(self, v):
        """Return the object number holding a stream for a Ref (or None)."""
        if isinstance(v, Ref) and v.num in self.objects and self.objects[v.num][1]:
            return v.num
        return None

    def stream_data(self, num):
        """Decoded bytes of stream object `num` (None when undecodable)."""
        entry = self.objects.get(num)
        if not entry or not entry[1]:
            return None
        d, (s, e) = entry
        raw = self.data[s:e]
        filters = self.resolve(_get(d, "Filter"))
        if isinstance(filters, Name):
            filters = [filters]
        if not isinstance(filters, list):
            filters = []
        out = raw
        for f in filters:
            f = self.resolve(f)
            if f in ("FlateDecode", "Fl"):
                out = self._inflate(out)
            elif f in ("ASCIIHexDecode", "AHx"):
                digits = re.sub(rb"[^0-9A-Fa-f]", b"", out.split(b">")[0])
                if len(digits) % 2:
                    digits += b"0"
                try:
                    out = bytes.fromhex(digits.decode("ascii"))
                except ValueError:
                    return None
            elif f in ("ASCII85Decode", "A85"):
                body = out.strip()
                if body.startswith(b"<~"):
                    body = body[2:]
                body = body.split(b"~>")[0]
                try:
                    out = base64.a85decode(re.sub(rb"\s+", b"", body))
                except Exception:
                    return None
            else:
                return None          # images (DCT/JPX/CCITT/JBIG2) and rare filters (LZW, RunLength)
            if out is None:
                return None
        return out

    def _inflate(self, raw):
        """Inflate with caps; salvage the readable prefix of a truncated or corrupt stream."""
        room = min(MAX_PDF_STREAM, MAX_PDF_TOTAL - self.inflated_total)
        if room <= 0:
            if "PDF decompression limit reached" not in self.warnings:
                self.warnings.append("PDF decompression limit reached")
            return None
        state = {"d": zlib.decompressobj(), "out": [], "size": 0}

        def feed(chunk):
            """Feed one chunk; False when the data is corrupt from here on."""
            d = state["d"]
            data = chunk
            while data and state["size"] < room and not d.eof:
                piece = d.decompress(data, room - state["size"])
                state["out"].append(piece)
                state["size"] += len(piece)
                data = d.unconsumed_tail
                if not piece and data:
                    break
            return True

        pos = 0
        step = 1 << 14
        while pos < len(raw) and state["size"] < room and not state["d"].eof:
            chunk = raw[pos:pos + step]
            pos += step
            saved = state["d"].copy()
            saved_len, saved_size = len(state["out"]), state["size"]
            try:
                feed(chunk)
            except zlib.error:
                # Corrupt data inside this chunk: keep the longest prefix that still inflates (once a
                # prefix fails, every longer one fails too, so a binary search finds it).
                lo, hi = 0, len(chunk)
                while lo < hi:
                    mid = (lo + hi + 1) // 2
                    probe = saved.copy()
                    try:
                        probe.decompress(chunk[:mid], room - saved_size)
                        lo = mid
                    except zlib.error:
                        hi = mid - 1
                state["d"] = saved
                del state["out"][saved_len:]
                state["size"] = saved_size
                try:
                    feed(chunk[:lo])
                except zlib.error:  # pragma: no cover - the prefix was just checked
                    pass
                break
        size = state["size"]
        self.inflated_total += size
        if size >= room and not state["d"].eof:
            self.warnings.append("a PDF stream was larger than the %d MB limit and was cut" % max(1, MAX_PDF_STREAM // (1 << 20)))
        if not size:
            return None
        return b"".join(state["out"])

    def encrypted(self):
        return "Encrypt" in self.trailer and self.trailer.get("Encrypt") is not None

    def catalog(self):
        root = self.resolve(self.trailer.get("Root"))
        if isinstance(root, dict):
            return root
        for num in sorted(self.objects):
            v = self.objects[num][0]
            if isinstance(v, dict) and v.get("Type") == "Catalog":
                return v
        return None

    def pages(self):
        """Page dicts in page-tree order, with inherited /Resources resolved into '_res'."""
        out = []
        cat = self.catalog()
        start = self.resolve(_get(cat, "Pages")) if cat else None
        seen = set()

        def walk(node, inherited, depth):
            if len(out) >= MAX_PAGES_WALK or depth > 40 or not isinstance(node, dict) or id(node) in seen:
                return
            seen.add(id(node))
            res = self.resolve(node.get("Resources")) if "Resources" in node else inherited
            kids = self.resolve(node.get("Kids"))
            if node.get("Type") == "Pages" or (isinstance(kids, list) and node.get("Type") != "Page"):
                for k in kids if isinstance(kids, list) else []:
                    walk(self.resolve(k), res, depth + 1)
            else:
                page = dict(node)
                page["_res"] = res
                out.append(page)

        if start is not None:
            walk(start, None, 0)
        if not out:
            for num in sorted(self.objects):
                v = self.objects[num][0]
                if isinstance(v, dict) and v.get("Type") == "Page":
                    page = dict(v)
                    page["_res"] = self.resolve(v.get("Resources"))
                    out.append(page)
        return out

    def page_content(self, page):
        contents = self.resolve(page.get("Contents"))
        refs = []
        raw = page.get("Contents")
        if isinstance(raw, Ref):
            if isinstance(contents, list):
                refs = contents
            else:
                refs = [raw]
        elif isinstance(raw, list):
            refs = raw
        parts = []
        for r in refs[:200]:
            num = self.stream_of(r)
            if num is None:
                continue
            data = self.stream_data(num)
            if data:
                parts.append(data)
        return b"\n".join(parts)


# --- fonts ------------------------------------------------------------------------------------------
_HEX_RE = re.compile(rb"<([0-9A-Fa-f\s]*)>")


def _hexint(b):
    digits = re.sub(rb"\s", b"", b)
    return (int(digits, 16) if digits else 0), max(1, len(digits) // 2)


def _utf16(b):
    digits = re.sub(rb"\s", b"", b)
    if len(digits) % 2:
        digits += b"0"
    try:
        raw = bytes.fromhex(digits.decode("ascii"))
    except ValueError:
        return ""
    if len(raw) % 2:
        raw = b"\x00" + raw
    return raw.decode("utf-16-be", "replace")


def parse_cmap(data, limit=70000):
    """Parse a ToUnicode CMap -> (code_lengths, {code: text})."""
    mapping = {}
    lengths = set()
    if not data:
        return lengths, mapping
    for block in re.finditer(rb"begincodespacerange(.*?)endcodespacerange", data, re.S):
        for h in _HEX_RE.finditer(block.group(1)):
            lengths.add(_hexint(h.group(1))[1])
    for block in re.finditer(rb"beginbfchar(.*?)endbfchar", data, re.S):
        toks = re.findall(rb"<[0-9A-Fa-f\s]*>|/[^\s<>\[\]/]+", block.group(1))
        for i in range(0, len(toks) - 1, 2):
            src, dst = toks[i], toks[i + 1]
            if not src.startswith(b"<"):
                continue
            code, n = _hexint(src[1:-1])
            lengths.add(n)
            if dst.startswith(b"<"):
                mapping[code] = _utf16(dst[1:-1])
            else:
                mapping[code] = glyph_to_unicode(dst[1:].decode("latin-1"))
            if len(mapping) > limit:
                return lengths, mapping
    for block in re.finditer(rb"beginbfrange(.*?)endbfrange", data, re.S):
        body = block.group(1)
        for m in re.finditer(rb"<([0-9A-Fa-f\s]*)>\s*<([0-9A-Fa-f\s]*)>\s*(<[0-9A-Fa-f\s]*>|\[[^\]]*\])", body):
            lo, n = _hexint(m.group(1))
            hi, _ = _hexint(m.group(2))
            lengths.add(n)
            if hi < lo or hi - lo > 65535:
                continue
            dst = m.group(3)
            if dst.startswith(b"["):
                items = _HEX_RE.findall(dst)
                for i, item in enumerate(items[:hi - lo + 1]):
                    mapping[lo + i] = _utf16(item)
            else:
                digits = re.sub(rb"\s", b"", dst[1:-1])
                text = _utf16(digits)
                if not text:
                    continue
                base = ord(text[-1])
                prefix = text[:-1]
                for i in range(hi - lo + 1):
                    cp = base + i
                    mapping[lo + i] = prefix + (chr(cp) if cp < 0x110000 else "\ufffd")
            if len(mapping) > limit:
                return lengths, mapping
    return lengths, mapping


_AGL = {
    "space": " ", "exclam": "!", "quotedbl": '"', "numbersign": "#", "dollar": "$", "percent": "%",
    "ampersand": "&", "quotesingle": "'", "quoteright": "\u2019", "quoteleft": "\u2018",
    "parenleft": "(", "parenright": ")", "asterisk": "*", "plus": "+", "comma": ",", "hyphen": "-",
    "minus": "\u2212", "period": ".", "slash": "/", "colon": ":", "semicolon": ";", "less": "<",
    "equal": "=", "greater": ">", "question": "?", "at": "@", "bracketleft": "[", "backslash": "\\",
    "bracketright": "]", "asciicircum": "^", "underscore": "_", "grave": "`", "braceleft": "{",
    "bar": "|", "braceright": "}", "asciitilde": "~", "bullet": "\u2022", "endash": "\u2013",
    "emdash": "\u2014", "quotedblleft": "\u201c", "quotedblright": "\u201d", "quotesinglbase": "\u201a",
    "quotedblbase": "\u201e", "ellipsis": "\u2026", "periodcentered": "\u00b7", "copyright": "\u00a9",
    "registered": "\u00ae", "trademark": "\u2122", "degree": "\u00b0", "fi": "fi", "fl": "fl",
    "ff": "ff", "ffi": "ffi", "ffl": "ffl", "nbspace": " ", "uni00A0": " ", "sterling": "\u00a3",
    "Euro": "\u20ac", "euro": "\u20ac", "yen": "\u00a5", "section": "\u00a7", "paragraph": "\u00b6",
    "dagger": "\u2020", "daggerdbl": "\u2021", "guillemotleft": "\u00ab", "guillemotright": "\u00bb",
    "multiply": "\u00d7", "divide": "\u00f7", "plusminus": "\u00b1", "germandbls": "\u00df",
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
    "seven": "7", "eight": "8", "nine": "9", "dotlessi": "\u0131", "ae": "\u00e6", "AE": "\u00c6",
    "oe": "\u0153", "OE": "\u0152", "oslash": "\u00f8", "Oslash": "\u00d8", "check": "\u2713",
}
_ACCENTS = {"acute": "ACUTE", "grave": "GRAVE", "circumflex": "CIRCUMFLEX", "dieresis": "DIAERESIS",
            "tilde": "TILDE", "ring": "RING ABOVE", "cedilla": "CEDILLA", "caron": "CARON"}


def glyph_to_unicode(name):
    """Map an Adobe glyph name to text; unknown names give U+FFFD."""
    if not name:
        return "\ufffd"
    base = name.split(".", 1)[0].split("_", 1)[0]
    if len(base) == 1 and base.isalpha():
        return base
    if base in _AGL:
        return _AGL[base]
    m = re.match(r"^uni([0-9A-Fa-f]{4})", base)
    if m:
        try:
            return chr(int(m.group(1), 16))
        except ValueError:
            return "\ufffd"
    m = re.match(r"^u([0-9A-Fa-f]{4,6})$", base)
    if m:
        try:
            return chr(int(m.group(1), 16))
        except (ValueError, OverflowError):
            return "\ufffd"
    if len(base) > 1 and base[0].isalpha():
        for suffix, uname in _ACCENTS.items():
            if base.endswith(suffix) and len(base) == len(suffix) + 1:
                letter = base[0]
                case = "CAPITAL" if letter.isupper() else "SMALL"
                try:
                    return unicodedata.lookup("LATIN %s LETTER %s WITH %s" % (case, letter.upper(), uname))
                except KeyError:
                    return letter
    return "\ufffd"


def _simple_base(encoding_name):
    if encoding_name == "MacRomanEncoding":
        return "mac_roman"
    return "cp1252"


class FontDecoder(object):
    """Decode string bytes shown with one font into text, and measure their advance width.

    Widths come from /Widths (simple fonts) or the descendant font's /W and /DW (Type0), in 1/1000 em;
    the built-in reader uses them to tell a word gap from a glyph-by-glyph positioning move.
    """

    def __init__(self, pdf, font):
        self.ok = True
        self.type0 = False
        self.unicode_cmap = False
        self.lengths = set([1])
        self.map = {}
        self.base = "cp1252"
        self.diff = {}
        self.widths = {}
        self.default_width = 500.0
        self.scale = 1.0
        if not isinstance(font, dict):
            return
        subtype = pdf.resolve(font.get("Subtype"))
        enc = pdf.resolve(font.get("Encoding"))
        if subtype == "Type0":
            self.type0 = True
            self.lengths = set([2])
            if isinstance(enc, Name) and enc.startswith("Uni") and ("UCS2" in enc or "UTF16" in enc):
                self.unicode_cmap = True
        tu = font.get("ToUnicode")
        num = pdf.stream_of(tu)
        if num is not None:
            lengths, mapping = parse_cmap(pdf.stream_data(num) or b"")
            if mapping:
                self.map = mapping
                if lengths:
                    self.lengths = lengths
        if self.type0 and not self.map and not self.unicode_cmap:
            self.ok = False            # glyph ids with no text mapping: cannot be read
        if not self.type0:
            if isinstance(enc, Name):
                self.base = _simple_base(enc)
            elif isinstance(enc, dict):
                self.base = _simple_base(pdf.resolve(enc.get("BaseEncoding")))
                diffs = pdf.resolve(enc.get("Differences"))
                code = None
                for item in diffs if isinstance(diffs, list) else []:
                    item = pdf.resolve(item)
                    if isinstance(item, int):
                        code = item
                    elif isinstance(item, Name) and code is not None:
                        self.diff[code] = glyph_to_unicode(item)
                        code += 1
        try:
            self._load_widths(pdf, font, subtype)
        except (TypeError, ValueError, OverflowError):
            self.widths = {}

    def _load_widths(self, pdf, font, subtype):
        if self.type0:
            desc = pdf.resolve(font.get("DescendantFonts"))
            cid = pdf.resolve(desc[0]) if isinstance(desc, list) and desc else None
            if not isinstance(cid, dict):
                self.default_width = 1000.0
                return
            dw = pdf.resolve(cid.get("DW"))
            self.default_width = float(dw) if isinstance(dw, (int, float)) else 1000.0
            w = pdf.resolve(cid.get("W"))
            items = [pdf.resolve(x) for x in w] if isinstance(w, list) else []
            i = 0
            while i < len(items) and len(self.widths) < 70000:
                first = items[i]
                if not isinstance(first, int):
                    break
                nxt = items[i + 1] if i + 1 < len(items) else None
                if isinstance(nxt, list):
                    for k, wv in enumerate(nxt):
                        wv = pdf.resolve(wv)
                        if isinstance(wv, (int, float)):
                            self.widths[first + k] = float(wv)
                    i += 2
                elif isinstance(nxt, int) and i + 2 < len(items) and isinstance(items[i + 2], (int, float)):
                    last = min(nxt, first + 65535)
                    for c in range(first, last + 1):
                        self.widths[c] = float(items[i + 2])
                    i += 3
                else:
                    break
            return
        first = pdf.resolve(font.get("FirstChar"))
        widths = pdf.resolve(font.get("Widths"))
        if isinstance(first, int) and isinstance(widths, list):
            for k, wv in enumerate(widths[:256]):
                wv = pdf.resolve(wv)
                if isinstance(wv, (int, float)):
                    self.widths[first + k] = float(wv)
        descriptor = pdf.resolve(font.get("FontDescriptor"))
        missing = pdf.resolve(descriptor.get("MissingWidth")) if isinstance(descriptor, dict) else None
        if isinstance(missing, (int, float)) and missing > 0:
            self.default_width = float(missing)
        if subtype == "Type3":
            matrix = pdf.resolve(font.get("FontMatrix"))
            if isinstance(matrix, list) and matrix and isinstance(matrix[0], (int, float)):
                self.scale = abs(float(matrix[0])) * 1000.0 or 1.0

    def _codes(self, b):
        """Split shown bytes into (code, is_single_byte_space) using the font's code lengths."""
        if self.unicode_cmap and not self.map:
            return [(int.from_bytes(b[i:i + 2], "big"), False) for i in range(0, len(b), 2)]
        if self.type0 or (self.map and max(self.lengths) > 1):
            out = []
            i = 0
            lens = sorted(self.lengths, reverse=True) or [2]
            while i < len(b):
                for n in lens:
                    code = int.from_bytes(b[i:i + n], "big")
                    if code in self.map or n == lens[-1]:
                        out.append((code, False))
                        i += n
                        break
            return out
        return [(byte, byte == 32) for byte in bytearray(b)]

    def _char(self, code):
        if self.unicode_cmap and not self.map:
            try:
                return chr(code)
            except ValueError:
                return "\ufffd"
        if self.type0 or (self.map and max(self.lengths) > 1):
            if not self.ok:
                return "\ufffd"
            return self.map.get(code, "\ufffd")
        if code in self.map:
            return self.map[code]
        if code in self.diff:
            return self.diff[code]
        try:
            return bytes([code]).decode(self.base)
        except UnicodeDecodeError:
            return bytes([code]).decode("latin-1")

    def decode_ex(self, b):
        """Return (text, advance in 1/1000 em, number of single-byte spaces)."""
        if not b:
            return "", 0.0, 0
        text = []
        width = 0.0
        spaces = 0
        for code, is_space in self._codes(b):
            text.append(self._char(code))
            width += self.widths.get(code, self.default_width) * self.scale
            if is_space:
                spaces += 1
        return "".join(text), width, spaces

    def decode(self, b):
        return self.decode_ex(b)[0]
