"""resume.md (canonical text) and ats_view.txt (ARCHITECTURE.md 5.3).

resume.md: each header/footer line prefixed "[header] " or "[footer] ", then every lines[].text in
order, one per line; text-box lines get a "[text box] " prefix; table rows keep their " | " joins.
Verbatim: nothing is re-ordered or corrected. A blank line separates the header/footer block.

ats_view.txt:
    # extraction: <method>
    # roughly what parsing software reads; order matters
    <blank>
    <body lines>
    <blank>
    # header/footer (some systems skip this):
    <header/footer lines>
and, only when hidden text was found, a final block quoting it (people cannot see it; software can).
"""
from hp.util import write_text
from hp.ingest.document import HIDDEN_WARNING_PREFIX

TEXT_BOX_PREFIX = "[text box] "


def _clean(s):
    return (s or "").replace("\r", " ").replace("\n", " ")


def _body_line(line):
    text = _clean(line.get("text"))
    if line.get("where") == "textbox":
        return TEXT_BOX_PREFIX + text
    return text


def _hf_line(entry):
    where = "footer" if entry.get("where") == "footer" else "header"
    return "[%s] %s" % (where, _clean(entry.get("text")))


def doc_to_resume_md(doc):
    """Return the canonical resume text (always ends with a newline)."""
    hf = [_hf_line(e) for e in doc.get("header_footer") or [] if _clean(e.get("text")).strip()]
    body = [_body_line(l) for l in doc.get("lines") or [] if _clean(l.get("text")).strip()]
    parts = []
    if hf:
        parts.extend(hf)
        if body:
            parts.append("")
    parts.extend(body)
    return "\n".join(parts) + "\n"


def ats_view_text(doc):
    out = ["# extraction: %s" % (doc.get("method") or "none"),
           "# roughly what parsing software reads; order matters", ""]
    body = [_body_line(l) for l in doc.get("lines") or [] if _clean(l.get("text")).strip()]
    out.extend(body if body else ["# (no text could be extracted)"])
    out.append("")
    out.append("# header/footer (some systems skip this):")
    hf = [_hf_line(e) for e in doc.get("header_footer") or [] if _clean(e.get("text")).strip()]
    out.extend(hf if hf else ["# (none)"])
    hidden = [w for w in doc.get("warnings") or [] if w.startswith(HIDDEN_WARNING_PREFIX)]
    if hidden:
        out.append("")
        out.append("# hidden text (people can't see it; parsing software still reads it):")
        out.extend(hidden)
    return "\n".join(out) + "\n"


def write_ats_view(doc, path):
    """Write ats_view.txt (UTF-8, atomic)."""
    write_text(path, ats_view_text(doc))
    return path
