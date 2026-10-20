"""hp.ingest: resume file -> Document dict (ARCHITECTURE.md section 5).

    from hp.ingest import ingest_file, ingest_text, doc_to_resume_md, write_ats_view
    doc = ingest_file(path)        # never raises on bad content; problems go in doc["errors"]/signals
    doc = ingest_text(text)        # pasted or transcribed text (format "txt")
    md  = doc_to_resume_md(doc)    # canonical resume.md text
    write_ats_view(doc, path)      # ats_view.txt

Extras for the integrator:
    needs_transcription(doc) -> bool       image-only / garbled / unreadable file: Claude transcribes
    transcription_reason(doc) -> str|None  image_only|garbled|encrypted|legacy_format|refused|unreadable|no_text
    apply_resume_text(file_doc, text)      --resume-text: text from the transcript, signals from the file

Error codes in doc["errors"]: not_found, unreadable, empty_file, file_too_large, too_large, zip_bomb,
xml_dtd_refused, corrupt_file, encrypted, legacy_format, unsupported_format, no_text, garbled_text,
internal_error, needs_transcription.
"""
from hp.ingest.core import ingest_file, ingest_text, apply_resume_text
from hp.ingest.view import doc_to_resume_md, write_ats_view, ats_view_text
from hp.ingest.document import needs_transcription, transcription_reason

__all__ = ["ingest_file", "ingest_text", "doc_to_resume_md", "write_ats_view", "ats_view_text",
           "needs_transcription", "transcription_reason", "apply_resume_text"]
