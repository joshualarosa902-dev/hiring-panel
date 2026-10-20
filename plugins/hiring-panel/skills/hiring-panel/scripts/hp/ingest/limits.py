"""Hard limits and safe readers for untrusted resume files (ARCHITECTURE.md 5.2, ATS spec 3).

Everything a student uploads is treated as hostile data:
- files over MAX_FILE_BYTES are not read at all;
- a .docx (zip) may expand to at most MAX_ZIP_EXPANDED bytes and MAX_ZIP_ENTRIES entries, checked both
  against the declared sizes and against the bytes actually inflated;
- an XML part that declares a DTD or an entity (<!DOCTYPE / <!ENTITY) is refused before any parser sees it;
- PDF streams are inflated with per-stream and total caps, inside a wall-clock budget.
Nothing here executes content or follows URLs.
"""
import io
import re
import time
import zipfile
import xml.etree.ElementTree as ET

# --- size limits -------------------------------------------------------------------------------------
MAX_FILE_BYTES = 15 * 1024 * 1024          # refuse to read larger inputs
PARSE_LIMIT_BYTES = int(2.5 * 1024 * 1024)  # Greenhouse's documented parse limit -> signals.too_large
MAX_ZIP_EXPANDED = 50 * 1024 * 1024         # total inflated bytes we will read from one zip
MAX_ZIP_ENTRIES = 2000
MAX_XML_PART = 25 * 1024 * 1024             # a single XML part (document.xml is usually < 1 MB)
MAX_PDF_STREAM = 20 * 1024 * 1024           # one inflated PDF stream
MAX_PDF_TOTAL = 100 * 1024 * 1024           # all inflated PDF streams together
PROBE_BUDGET_S = 5.0                        # PDF structure probe wall-clock budget
PDFKIT_TIMEOUT_S = 20                       # macOS PDFKit (osascript) subprocess timeout
MAX_PDF_PAGES = 60                          # pages we extract text from
MAX_TEXT_CHARS = 1000000                    # text we keep after extraction (a resume is ~5k chars)
MAX_LINES = 20000
MAX_DEPTH = 60                              # nesting depth for tables/text boxes/groups we walk

_DTD_RE = re.compile(rb"<!\s*(?:DOCTYPE|ENTITY)", re.IGNORECASE)
_DTD_STR_RE = re.compile(r"<!\s*(?:DOCTYPE|ENTITY)", re.IGNORECASE)


class RefusedInput(Exception):
    """Raised inside ingest when a file breaks a safety rule. Always caught by ingest_file."""

    def __init__(self, code, detail=""):
        Exception.__init__(self, "%s: %s" % (code, detail))
        self.code = code
        self.detail = detail


class Budget(object):
    """A simple wall-clock budget. `expired()` is cheap enough to call inside loops."""

    def __init__(self, seconds):
        self.seconds = seconds
        self.start = time.monotonic()

    def expired(self):
        return (time.monotonic() - self.start) > self.seconds


def has_dtd(raw):
    """True when an XML byte string declares a DTD or an entity, in UTF-8 or UTF-16 form."""
    if _DTD_RE.search(raw):
        return True
    head = raw[:4]
    if head[:2] in (b"\xff\xfe", b"\xfe\xff") or head in (b"<\x00?\x00", b"\x00<\x00?"):
        for enc in ("utf-16", "utf-16-le", "utf-16-be"):
            try:
                if _DTD_STR_RE.search(raw.decode(enc, "ignore")):
                    return True
            except Exception:  # pragma: no cover - decode with "ignore" does not raise
                pass
    return False


def parse_xml(raw, part_name="xml"):
    """Parse one XML part safely. Refuses DTD/entity declarations and oversized parts."""
    if raw is None:
        raise RefusedInput("corrupt_file", "missing XML part %s" % part_name)
    if len(raw) > MAX_XML_PART:
        raise RefusedInput("too_large", "XML part %s is larger than %d bytes" % (part_name, MAX_XML_PART))
    if has_dtd(raw):
        raise RefusedInput("xml_dtd_refused",
                           "%s declares a DTD or entity; resumes never need one, so the file was not parsed"
                           % part_name)
    try:
        return ET.fromstring(raw)
    except ET.ParseError as e:
        raise RefusedInput("corrupt_file", "XML part %s could not be parsed (%s)" % (part_name, e))
    except RecursionError:
        raise RefusedInput("corrupt_file", "XML part %s is nested too deeply" % part_name)


class SafeZip(object):
    """Read-only zip access with entry-count, declared-size and inflated-size limits."""

    def __init__(self, data):
        try:
            self.zf = zipfile.ZipFile(io.BytesIO(data))
            infos = self.zf.infolist()
        except (zipfile.BadZipFile, zipfile.LargeZipFile, ValueError, EOFError, OSError,
                NotImplementedError, OverflowError, KeyError, IndexError, TypeError) as e:
            raise RefusedInput("corrupt_file", "the zip container could not be opened (%s)" % type(e).__name__)
        if len(infos) > MAX_ZIP_ENTRIES:
            raise RefusedInput("zip_bomb", "the file holds %d zip entries (limit %d)" % (len(infos), MAX_ZIP_ENTRIES))
        declared = 0
        for info in infos:
            declared += max(0, int(info.file_size))
        if declared > MAX_ZIP_EXPANDED:
            raise RefusedInput("zip_bomb", "the file would expand to %d bytes (limit %d)" % (declared, MAX_ZIP_EXPANDED))
        # Last entry wins for duplicate names (that is what most readers do).
        self.infos = {}
        for info in infos:
            self.infos[info.filename] = info
        self.remaining = MAX_ZIP_EXPANDED

    def names(self):
        return sorted(self.infos)

    def has(self, name):
        return name in self.infos

    def read(self, name, limit=None):
        """Return the inflated bytes of one entry, or None when it does not exist."""
        info = self.infos.get(name)
        if info is None:
            return None
        if info.flag_bits & 0x1:
            raise RefusedInput("encrypted", "zip entry %s is password protected" % name)
        cap = self.remaining if limit is None else min(limit, self.remaining)
        try:
            with self.zf.open(info) as f:
                data = f.read(cap + 1)
        except RefusedInput:
            raise
        except Exception as e:  # BadZipFile (bad CRC), zlib.error, NotImplementedError, RuntimeError, ...
            if "encrypt" in str(e).lower() or "password" in str(e).lower():
                raise RefusedInput("encrypted", "zip entry %s is password protected" % name)
            raise RefusedInput("corrupt_file", "zip entry %s could not be read (%s)" % (name, type(e).__name__))
        if len(data) > cap:
            if limit is not None and cap == limit and limit < self.remaining:
                raise RefusedInput("too_large", "zip entry %s is larger than %d bytes" % (name, limit))
            raise RefusedInput("zip_bomb", "the file expands beyond %d bytes" % MAX_ZIP_EXPANDED)
        self.remaining -= len(data)
        return data

    def read_xml(self, name):
        """Parse one entry as XML (None if missing)."""
        raw = self.read(name, MAX_XML_PART)
        if raw is None:
            return None
        return parse_xml(raw, name)
