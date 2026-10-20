"""ingest_file / ingest_text: sniff, enforce limits, dispatch to a reader, finalize. Never raises."""
import copy
import hashlib
import os
import stat

from hp.ingest.document import Context, new_document, add_error, add_warning, finalize
from hp.ingest.limits import MAX_FILE_BYTES, RefusedInput
from hp.ingest.normalize import normalize_line
from hp.ingest.sniff import sniff

LEGACY_HINTS = {
    "doc": "an old Word .doc file; open it in Word or Google Docs and save it as .docx",
    "pages": "an Apple Pages file; use File > Export To > Word (.docx) or PDF",
    "odt": "an OpenDocument file; save it as .docx or PDF",
    "wpd": "a WordPerfect file; save it as .docx or PDF",
    "ole": "an old Office file that is not a Word document",
}


def ingest_file(path, pdf_backends=None):
    """Read a resume file into a Document dict (ARCHITECTURE.md 5.2). Never raises on bad content:
    problems are reported in doc["errors"] / doc["warnings"] / doc["signals"].
    `pdf_backends` optionally restricts the PDF ladder (tests); default is the full ladder."""
    doc = new_document()
    ctx = Context(doc)
    try:
        _ingest_path(path, doc, ctx, pdf_backends)
    except RefusedInput as e:
        doc["lines"] = []
        doc["header_footer"] = []
        if e.code == "encrypted":
            doc["signals"]["encrypted"] = True
        add_error(doc, e.code, e.detail)
    except MemoryError:
        doc["lines"], doc["header_footer"] = [], []
        add_error(doc, "too_large", "the file needed more memory than allowed")
    except RecursionError:
        doc["lines"], doc["header_footer"] = [], []
        add_error(doc, "corrupt_file", "the file is nested too deeply to read")
    except Exception as e:  # last-resort guard: ingest must never raise on content
        add_error(doc, "internal_error", "%s: %s" % (type(e).__name__, str(e)[:200]))
    try:
        finalize(doc, ctx)
    except Exception as e:  # pragma: no cover - finalize is defensive already
        add_error(doc, "internal_error", "finalize failed: %s" % type(e).__name__)
    return doc


def _ingest_path(path, doc, ctx, pdf_backends):
    if not isinstance(path, (str, bytes, os.PathLike)):
        # An int would be taken as a file descriptor (stdin!); only real paths are accepted.
        add_error(doc, "unreadable", "the path is not a file name")
        return
    path = os.fspath(path)
    try:
        st = os.stat(path)
    except (OSError, TypeError, ValueError) as e:
        add_error(doc, "not_found" if isinstance(e, FileNotFoundError) else "unreadable",
                  "the file could not be opened (%s)" % type(e).__name__)
        return
    if not stat.S_ISREG(st.st_mode):
        add_error(doc, "unreadable", "not a regular file")
        return
    doc["bytes"] = int(st.st_size)
    name = path.decode("utf-8", "replace") if isinstance(path, bytes) else str(path)
    if st.st_size > MAX_FILE_BYTES:
        doc["signals"]["too_large"] = True
        try:
            with open(path, "rb") as f:
                head = f.read(8192)
                h = hashlib.sha256(head)
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            doc["sha256"] = h.hexdigest()
            doc["format"] = sniff(head, name)[0]
        except OSError:
            pass
        add_error(doc, "file_too_large", "the file is %d bytes; the limit is %d (15 MB). Most resume "
                                         "systems want files under 2.5 MB" % (st.st_size, MAX_FILE_BYTES))
        return
    try:
        with open(path, "rb") as f:
            data = f.read(MAX_FILE_BYTES + 1)
    except OSError as e:
        add_error(doc, "unreadable", "the file could not be read (%s)" % type(e).__name__)
        return
    doc["bytes"] = len(data)
    doc["sha256"] = hashlib.sha256(data).hexdigest()
    fmt, legacy, facts = sniff(data, name)
    doc["format"] = fmt
    doc["signals"]["legacy_format"] = legacy
    if not data:
        add_error(doc, "empty_file", "the file is empty")
        return
    if fmt == "docx":
        from hp.ingest.docx import read_docx
        read_docx(data, doc, ctx, encrypted_office=bool(facts.get("encrypted_office")))
    elif fmt == "pdf":
        read_pdf(name, data, doc, ctx, pdf_backends)
    elif fmt == "rtf":
        from hp.ingest.rtf import read_rtf
        read_rtf(data, doc, ctx)
    elif fmt in ("txt", "md"):
        from hp.ingest.plain import decode_bytes, html_to_text, text_to_lines
        text, _enc, binary = decode_bytes(data)
        if binary:
            doc["format"] = "unknown"
            add_error(doc, "unsupported_format", "the file is not a resume format we can read; upload a "
                                                 ".docx or PDF, or paste the text")
            return
        if facts.get("html"):
            text = html_to_text(text)
            add_warning(doc, "a web page (HTML) was read as plain text")
        doc["lines"] = text_to_lines(text, ctx, markdown=True)
        doc["method"] = "text"
    elif fmt == "image":
        doc["signals"]["image_only"] = True
        add_warning(doc, "the file is an image (%s); it has no text a parser can read" % facts.get("image", "image"))
    elif fmt in ("doc", "pages", "odt") or legacy:
        add_error(doc, "legacy_format", "this is %s" % LEGACY_HINTS.get(legacy or fmt, "an unsupported format"))
    else:
        add_error(doc, "unsupported_format", "the file type was not recognised; upload a .docx or PDF, "
                                             "or paste the text")


def read_pdf(path, data, doc, ctx, backends=None):
    """Probe a PDF's structure, run the text ladder and fill the Document."""
    from hp.ingest.pdf_probe import probe_pdf
    from hp.ingest.pdf_text import extract_pdf_text
    sig = doc["signals"]
    facts = probe_pdf(data)
    sig["encrypted"] = bool(facts["encrypted"])
    sig["fonts"] = {"type0": facts["type0"], "tounicode": facts["tounicode"], "type3": facts["type3"]}
    sig["images"]["count"] = facts["images"]
    sig["design_tool"] = facts["design_tool"]
    sig["hidden_text"]["pdf_invisible"] = facts["invisible_spans"]
    doc["producer"] = facts["producer"]
    doc["creator"] = facts["creator"] or facts["creator_tool"]
    for w in facts["warnings"]:
        add_warning(doc, w)
    res = extract_pdf_text(path, facts, backends)
    for w in res["warnings"]:
        add_warning(doc, w)
    sig["columns"]["pdf_check"] = res["pdf_check"]
    sig["columns"]["pdf_gutter_pages"] = list(res["gutter_pages"])
    # Text drawn invisibly is reported (warnings) but kept out of the canonical lines, so hidden keywords
    # never count as resume evidence. The built-in reader already leaves it out.
    hidden = []
    if res["method"] != "builtin-pdf" and not facts["ocr_layer"]:
        for _kind, s in facts["hidden_samples"]:
            h = normalize_line(s)
            if len(h) >= 8:
                hidden.append(h)
    pages_lines = []
    for page in res["pages"]:
        plines = []
        for raw in page.replace("\r\n", "\n").replace("\r", "\n").replace("\x0c", "\n").split("\n"):
            t = normalize_line(raw, ctx.stats)
            for h in hidden:
                if h in t:
                    t = normalize_line(t.replace(h, " "))
            if t:
                plines.append(t)
        pages_lines.append(plines)
    ctx.pages_lines = pages_lines
    doc["lines"] = [{"text": t, "style": None, "list": t.startswith("\u2022 "), "bold": False, "where": "body"}
                    for plines in pages_lines for t in plines]
    doc["method"] = res["method"]
    doc["pages"] = res["page_count"] or facts["pages"]
    chars = sum(len("".join(t.split())) for plines in pages_lines for t in plines)
    sig["text_layer"] = True if chars > 0 else facts["text_layer"]
    npages = doc["pages"] or 1
    # ATS spec 5: image-only = images and no text layer, or images with < 200 characters per page.
    # When the content could not be opened (encrypted), there is no way to tell, so it stays False.
    if facts["images"] > 0 and sig["text_layer"] is not None and \
            (sig["text_layer"] is False or chars / float(npages) < 200):
        sig["image_only"] = True
    if res["locked"] and chars == 0:
        add_error(doc, "encrypted", "the PDF needs a password to open; ask for an unprotected copy")
    elif sig["encrypted"] and chars > 0:
        add_warning(doc, "the PDF is encrypted but opened without a password (permission restrictions only)")
    if not facts["ocr_layer"]:
        ctx.hidden_samples.extend(facts["hidden_samples"])
    if facts["truncated"] and chars == 0:
        add_error(doc, "corrupt_file", "the PDF is damaged or incomplete")


def ingest_text(text):
    """Read pasted or transcribed text (format "txt", method "text"). Never raises."""
    doc = new_document("txt")
    ctx = Context(doc)
    try:
        from hp.ingest.plain import decode_bytes, text_to_lines
        if text is None:
            text = ""
        if isinstance(text, (bytes, bytearray)):
            text, _enc, binary = decode_bytes(bytes(text))
            if binary:
                text = ""
                add_error(doc, "unsupported_format", "the text looks like binary data")
        if not isinstance(text, str):
            text = str(text)
        raw = text.encode("utf-8", "replace")
        doc["sha256"] = hashlib.sha256(raw).hexdigest()
        doc["bytes"] = len(raw)
        doc["lines"] = text_to_lines(text, ctx, markdown=True)
        doc["method"] = "text"
    except Exception as e:  # pragma: no cover - defensive
        add_error(doc, "internal_error", "%s: %s" % (type(e).__name__, str(e)[:200]))
    try:
        finalize(doc, ctx)
    except Exception as e:  # pragma: no cover
        add_error(doc, "internal_error", "finalize failed: %s" % type(e).__name__)
    return doc


def apply_resume_text(file_doc, text):
    """ARCHITECTURE.md 5.3 --resume-text: content from a transcript or pasted text, structure signals
    from the original file (so PARSE-001 for an image-only file stays). Returns a new Document."""
    text_doc = ingest_text(text)
    doc = copy.deepcopy(file_doc)
    doc["lines"] = text_doc["lines"]
    doc["header_footer"] = []
    doc["text_chars"] = text_doc["text_chars"]
    doc["words"] = text_doc["words"]
    doc["method"] = "text"
    doc["errors"] = [e for e in doc["errors"] if e["code"] not in ("needs_transcription", "no_text", "garbled_text")]
    doc["errors"].extend(e for e in text_doc["errors"] if e["code"] != "needs_transcription")
    add_warning(doc, "the resume text came from a transcript or pasted text; structure checks still come "
                     "from the original file, and pasted text may be cleaner than what a parser extracts")
    return doc
