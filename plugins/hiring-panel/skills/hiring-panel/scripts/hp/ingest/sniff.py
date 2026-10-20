"""Detect a file's format from its first bytes, never from its extension alone (ATS spec 3).

The extension is used only to break ties that bytes cannot settle (.md vs .txt) and to name an
encrypted Office file. Returns one of the Document "format" values plus a few facts for the reader.
"""
import os
import re
import zipfile
import io

IMAGE_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpeg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"II*\x00", "tiff"),
    (b"MM\x00*", "tiff"),
)
HEIF_BRANDS = (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"avif", b"heim", b"heis")
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
WORDPERFECT_MAGIC = b"\xffWPC"


def _ext(filename):
    return os.path.splitext(filename or "")[1].lower().lstrip(".")


def _image_kind(data):
    for sig, kind in IMAGE_SIGNATURES:
        if data.startswith(sig):
            return kind
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in HEIF_BRANDS:
        return "heic"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if len(data) >= 26 and data[:2] == b"BM":
        # BMP: bytes 2..6 hold the file size; require it to match so text starting with "BM" is safe.
        size = int.from_bytes(data[2:6], "little")
        if size == len(data):
            return "bmp"
    return None


def _zip_kind(data):
    """Classify a zip container by its member names. Unreadable zips are reported as docx candidates
    only when they still look like Office files; the docx reader reports the corruption."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        names = set(zf.namelist()[:5000])
    except Exception:
        # A truncated zip: look for Word part names in the local headers.
        if b"word/document" in data[:200000] or b"[Content_Types].xml" in data[:200000]:
            return "docx", None
        return "unknown", None
    if "word/document.xml" in names or any(re.match(r"word/document\d*\.xml$", n) for n in names):
        return "docx", None
    if "[Content_Types].xml" in names and any(n.startswith("word/") for n in names):
        return "docx", None
    if "mimetype" in names:
        try:
            mt = zf.read("mimetype")[:100]
        except Exception:
            mt = b""
        if mt.startswith(b"application/vnd.oasis.opendocument.text"):
            return "odt", "odt"
    if any(n.startswith("Index/") and n.endswith(".iwa") for n in names) or "index.xml" in names \
            or any(n.endswith(".pages/Index.zip") for n in names):
        return "pages", "pages"
    return "unknown", None


def sniff(data, filename=""):
    """Return (format, legacy_format, facts) for raw file bytes.

    facts may hold: image (kind), encrypted_office (bool), html (bool).
    """
    facts = {}
    ext = _ext(filename)
    if not data:
        return ("md" if ext in ("md", "markdown") else "txt"), None, facts
    head = data[:2048]
    if head.startswith(b"PK\x03\x04") or head.startswith(b"PK\x05\x06"):
        fmt, legacy = _zip_kind(data)
        return fmt, legacy, facts
    if b"%PDF-" in data[:1024]:
        return "pdf", None, facts
    if data.startswith(OLE_MAGIC):
        sample = data[:min(len(data), 4 * 1024 * 1024)]
        if "EncryptedPackage".encode("utf-16-le") in sample:
            # A password-protected .docx/.xlsx/.pptx is stored inside an OLE container.
            facts["encrypted_office"] = True
            return "docx", None, facts
        if "WordDocument".encode("utf-16-le") in sample:
            return "doc", "doc", facts
        return "unknown", "ole", facts
    if data.startswith(WORDPERFECT_MAGIC):
        return "unknown", "wpd", facts
    kind = _image_kind(data)
    if kind:
        facts["image"] = kind
        return "image", None, facts
    stripped = data.lstrip(b"\xef\xbb\xbf \t\r\n")
    if stripped[:5] == b"{\\rtf":
        return "rtf", None, facts
    # Everything else is text (the text reader decides whether it is really binary junk).
    low = stripped[:512].lower()
    if low.startswith(b"<!doctype html") or low.startswith(b"<html") or \
            (b"<html" in low[:200] and b"<body" in data[:4096].lower()):
        facts["html"] = True
    return ("md" if ext in ("md", "markdown") else "txt"), None, facts
