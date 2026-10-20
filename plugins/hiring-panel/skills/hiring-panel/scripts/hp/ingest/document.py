"""The Document dict (ARCHITECTURE.md 5.2), shared finalization, and the needs-transcription signal.

Every reader fills lines/header_footer/method and its own structure facts; finalize() then computes
the text-level facts the same way for every format (text_chars, words, private-use and replacement
characters, letter spacing, garbling, page furniture, header/footer contact, image-only) and records
problems in errors/warnings.

needs-transcription signal (for the integrator): when the file has no usable text, finalize() appends
{"code": "needs_transcription", "detail": "<reason>: <what to do>"} to doc["errors"].
Use needs_transcription(doc) -> bool and transcription_reason(doc) -> str|None instead of parsing it.
Reasons: image_only (scan, photo or image file), garbled (text extracts as junk), encrypted
(password protected), legacy_format (.doc/.pages/.odt/...), refused (a safety rule refused the file),
unreadable (corrupt or unknown file), no_text (no text found). Plain .txt/.md and pasted text never
need transcription (there is nothing else to read).
"""
import copy

from hp.ingest.normalize import (TextStats, is_garbled, letter_spaced_count, has_contact, word_count,
                                 page_number_lines, repeated_page_lines)
from hp.ingest.limits import PARSE_LIMIT_BYTES

MIN_USABLE_CHARS = 40          # fewer non-space characters than this = no usable text
IMAGE_ONLY_CHARS_PER_PAGE = 200
HIDDEN_WARNING_PREFIX = "hidden text ("

_SIGNALS = {
    "encrypted": False, "text_layer": None, "image_only": False, "garbled": False,
    "too_large": False, "legacy_format": None,
    "images": {"count": 0, "large": 0, "charts": 0, "smartart": 0, "small_icons": 0},
    "tables": {"count": 0, "nested": 0, "holds_experience": False},
    "text_boxes": {"count": 0, "chars": 0, "has_contact": False, "has_heading": False},
    "columns": {"docx_multi_column": False, "pdf_check": "unavailable", "pdf_gutter_pages": []},
    "header_footer": {"has_text": False, "has_contact": False},
    "hidden_text": {"vanish": 0, "white": 0, "tiny": 0, "pdf_invisible": 0},
    "caps_formatting": 0, "fields": {"docproperty": 0, "mergefield": 0, "ole": 0},
    "tracked_changes": 0, "comments": 0, "symbols": 0,
    "fonts": {"type0": 0, "tounicode": 0, "type3": 0},
    "design_tool": None, "private_use_chars": 0, "replacement_chars": 0,
    "letter_spaced": 0, "repeated_footer_lines": 0, "tab_merged_tokens": 0,
}

TRANSCRIPTION_HINTS = {
    "image_only": "the file is a picture of a resume (no selectable text); transcribe it word for word, "
                  "keeping typos, and confirm with the student",
    "garbled": "the file's text comes out as junk characters; transcribe it word for word from the "
               "visible page, keeping typos, and confirm with the student",
    "encrypted": "the file is password protected; ask for an unprotected copy or the pasted text",
    "legacy_format": "this file format cannot be read here; ask the student to save it as .docx or PDF, "
                     "or to paste the text",
    "refused": "the file was refused for safety reasons; ask for a freshly saved .docx or PDF, or the "
               "pasted text",
    "unreadable": "the file could not be read; ask for a .docx or PDF, or the pasted text",
    "no_text": "no text could be found in the file; ask for a .docx or PDF, or the pasted text",
}
_REFUSAL_CODES = ("xml_dtd_refused", "zip_bomb", "file_too_large", "too_large")
_UNREADABLE_CODES = ("corrupt_file", "unreadable", "unsupported_format", "internal_error")


class Context(object):
    """Per-ingest scratch state that is not part of the Document."""

    def __init__(self, doc):
        self.stats = TextStats()
        self.hidden_samples = []          # [(kind, text)]
        self.pages_lines = None           # PDF: per-page normalized lines
        self.warnings = doc["warnings"]


def new_document(fmt="unknown"):
    return {
        "format": fmt, "sha256": None, "bytes": 0, "pages": None, "producer": None, "creator": None,
        "method": "none", "lines": [], "header_footer": [], "text_chars": 0, "words": 0,
        "signals": copy.deepcopy(_SIGNALS), "warnings": [], "errors": [],
    }


def add_error(doc, code, detail=""):
    for e in doc["errors"]:
        if e["code"] == code and e["detail"] == detail:
            return
    doc["errors"].append({"code": code, "detail": detail})


def add_warning(doc, text):
    if text and text not in doc["warnings"]:
        doc["warnings"].append(text)


def _usable_chars(doc):
    n = sum(len("".join(l["text"].split())) for l in doc["lines"])
    n += sum(len("".join(h["text"].split())) for h in doc["header_footer"])
    return n


def transcription_reason(doc):
    """Why this Document needs Claude to transcribe the original (None when it does not)."""
    for e in doc.get("errors") or []:
        if e.get("code") == "needs_transcription":
            return (e.get("detail") or "no_text").split(":", 1)[0]
    return None


def needs_transcription(doc):
    return transcription_reason(doc) is not None


def _compute_reason(doc):
    sig = doc["signals"]
    if doc["format"] in ("txt", "md"):
        return None
    codes = set(e["code"] for e in doc["errors"])
    if doc["sha256"] is None or "empty_file" in codes:
        return None            # nothing was read: there is no file to transcribe (bad path, empty file)
    if sig["image_only"] or doc["format"] == "image":
        return "image_only"
    usable = _usable_chars(doc)
    if usable < MIN_USABLE_CHARS:
        if sig["encrypted"]:
            return "encrypted"
        if sig["legacy_format"] or doc["format"] in ("doc", "pages", "odt"):
            return "legacy_format"
        if codes & set(_REFUSAL_CODES):
            return "refused"
        if codes & set(_UNREADABLE_CODES) or doc["format"] == "unknown":
            return "unreadable"
        return "no_text"
    if sig["garbled"]:
        return "garbled"
    return None


def finalize(doc, ctx):
    """Compute text-level facts and the needs-transcription signal. Mutates and returns doc."""
    sig = doc["signals"]
    body = [l["text"] for l in doc["lines"]]
    hf = [h["text"] for h in doc["header_footer"]]
    all_lines = body + hf
    all_text = "\n".join(all_lines)

    doc["text_chars"] = sum(len(t) for t in all_lines)
    doc["words"] = word_count(all_text)
    sig["too_large"] = bool(sig["too_large"] or doc["bytes"] > PARSE_LIMIT_BYTES)
    sig["private_use_chars"] = ctx.stats.private_use
    sig["replacement_chars"] = ctx.stats.replacement
    sig["letter_spaced"] = sum(letter_spaced_count(t) for t in all_lines)
    sig["garbled"] = bool(all_text.strip()) and is_garbled(all_text)
    furniture = page_number_lines(body)
    if ctx.pages_lines:
        furniture += repeated_page_lines(ctx.pages_lines)
    sig["repeated_footer_lines"] = furniture
    sig["header_footer"]["has_text"] = any(t.strip() for t in hf)
    sig["header_footer"]["has_contact"] = any(has_contact(t) for t in hf)

    usable = _usable_chars(doc)
    codes = set(e["code"] for e in doc["errors"])
    if doc["format"] in ("docx", "rtf", "txt", "md"):
        if usable > 0:
            sig["text_layer"] = True
        elif codes & set(_REFUSAL_CODES + _UNREADABLE_CODES + ("encrypted",)):
            sig["text_layer"] = None      # never opened (refused, damaged or locked): unknown, not "no text"
        else:
            sig["text_layer"] = False
    elif doc["format"] == "image":
        sig["text_layer"] = False
    if doc["format"] == "image":
        sig["image_only"] = True
    elif doc["format"] == "docx" and sig["images"]["count"] > 0 and usable < MIN_USABLE_CHARS:
        sig["image_only"] = True      # a resume pasted into Word as a picture

    for kind, text in ctx.hidden_samples:
        label = {"vanish": "hidden formatting", "white": "white text", "tiny": "tiny text",
                 "pdf": "invisible PDF text"}.get(kind, kind)
        add_warning(doc, '%s%s): "%s"' % (HIDDEN_WARNING_PREFIX, label, text))

    if not all_text.strip():
        # A readable document format that yielded nothing (image formats and unknown files have their
        # own error codes already).
        if doc["sha256"] is not None and doc["format"] in ("pdf", "docx", "rtf", "txt", "md"):
            add_error(doc, "no_text", "no text could be extracted")
    elif sig["garbled"]:
        add_error(doc, "garbled_text", "the extracted text is mostly junk characters")

    reason = _compute_reason(doc)
    if reason:
        add_error(doc, "needs_transcription", "%s: %s" % (reason, TRANSCRIPTION_HINTS[reason]))
    return doc
