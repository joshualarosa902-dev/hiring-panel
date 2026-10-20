"""Student-facing Markdown (screening.md) and the compact subagent brief (brief.json, ARCHITECTURE 6.3).

Both read only the screening.json dict. Contact details are masked. Wording rules: always "Simulated
screening check", never "ATS score", plain language, no em dashes.
"""
import re

from .textutil import bullet_split, clip, mask_all

_SEV_LABEL = {"critical": "Critical", "high": "High", "medium": "Medium", "low": "Low", "info": "Note"}
_KO_STATUS = {"appears_met": "Looks met", "appears_unmet": "Looks unmet", "unclear": "Unclear",
              "not_on_resume_by_design": "Application question"}
_KO_TYPE = {"work_authorization": "Work authorization", "sponsorship": "Visa sponsorship",
            "onsite_hybrid": "On-site or hybrid", "location": "Location", "relocation": "Relocation",
            "years_experience": "Years of experience", "degree": "Degree", "major": "Major", "gpa": "GPA",
            "graduation_window": "Graduation date", "certification": "Certification", "license": "License",
            "clearance": "Security clearance", "travel": "Travel", "schedule": "Schedule",
            "physical": "Physical requirements", "age": "Minimum age", "language": "Language",
            "background_check": "Background check", "other": "Other"}
_LEVEL = {"demonstrated": "shown in your experience", "listed": "only in a list", "claimed": "only in your summary",
          "none": ""}
_SECTION_NAME = {"contact": "top lines", "summary": "Summary", "experience": "Experience", "education": "Education",
                 "skills": "Skills", "projects": "Projects", "certifications": "Certifications",
                 "leadership_activities": "Leadership", "volunteer": "Volunteer", "awards": "Awards",
                 "publications": "Publications", "coursework": "Coursework", "languages": "Languages",
                 "interests": "Interests", "references": "References", "other": "Other",
                 "header_footer": "header or footer"}


def _g(d, *path, default=None):
    cur = d
    for p in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(p)
    return default if cur is None else cur


def _esc(s):
    """Neutralize untrusted text for Markdown: no raw HTML, no table breaks, one line."""
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s.replace("<", "&lt;").replace(">", "&gt;").replace("|", "\\|")


def _join_ev(items):
    parts = [str(x).strip().rstrip(".;") for x in items if str(x).strip()]
    return ("; ".join(parts) + ".") if parts else ""


def _score_line(label, sc):
    v = _g(sc, "value")
    b = _g(sc, "band", default="")
    if v is None:
        return "- %s: %s" % (label, b)
    return "- %s: %d (%s)" % (label, v, b)


def required_line(result):
    """The report's exact keyword sentence, or None when keywords were not scored."""
    cov = _g(result, "keywords", "coverage", default={})
    status = _g(result, "keywords", "status")
    if status not in ("checked", "thin_jd"):
        return None
    if cov.get("basis") == "all_terms":
        return "Job terms: %d of %d found (%d only in your skills list)." % (
            cov.get("basis_found", 0), cov.get("basis_total", 0), cov.get("basis_listed_only", 0))
    return "Required terms: %d of %d found (%d only in your skills list)." % (
        cov.get("required_found", 0), cov.get("required_total", 0), cov.get("required_listed_only", 0))


def _status(t):
    mt = t.get("match_type")
    if t.get("found"):
        alt = t.get("matched_alternative")
        via = ' ("%s")' % alt if alt and alt != t.get("term") else ""
        if mt in ("alias", "acronym"):
            return "Found (different wording)" + via
        if mt == "implied":
            return "Found (related skill)" + via
        return "Found" + via
    if mt in ("partial", "ambiguous"):
        return "Partly found"
    return "Not found"


def render_screening_md(result):
    """Student-facing summary of one screening result. Contact details are masked."""
    r = result if isinstance(result, dict) else {}
    s = _g(r, "scores", default={})
    out = ["# Simulated screening check", ""]
    out.append("This is a simulation, not a real applicant tracking system. The note at the end explains "
               "what it can and can't tell you.")
    out.append("")
    ov = _g(s, "overall", default={})
    if _g(ov, "value") is not None:
        out.append("**Overall: %d (%s)**" % (ov["value"], _g(ov, "band", default="")))
    else:
        out.append("**Overall: %s**" % _g(ov, "band", default="not available"))
    out.append("")
    out.append(_score_line("Machine readability", _g(s, "parse_safety")))
    km_line = _score_line("Job-keyword match", _g(s, "keyword_match"))
    req = required_line(r)
    if req:
        km_line += ". " + req
    out.append(km_line)
    out.append(_score_line("Content signals", _g(s, "content_signals")))
    out.append("")
    if _g(s, "precision_note"):
        out.append(_esc(s["precision_note"]))
        out.append("")
    if _g(ov, "explanation"):
        out.append(_esc(ov["explanation"]))
        out.append("")
    issues = [i for i in _g(r, "issues", default=[]) if isinstance(i, dict)]
    ranked = [i for i in issues if i.get("severity") != "info"]
    notes = [i for i in issues if i.get("severity") == "info"]
    out.append("## Biggest issues first")
    out.append("")
    if not ranked:
        out.append("No scored issues were found.")
        out.append("")
    for n, it in enumerate(ranked, 1):
        out.append("%d. **%s** (%s, %s)" % (n, _esc(it.get("title")), _SEV_LABEL.get(it.get("severity"), ""),
                                           _esc(it.get("id"))))
        if it.get("evidence"):
            out.append("   - Seen: %s" % _esc(_join_ev(it["evidence"][:3])))
        out.append("   - Why it matters: %s" % _esc(it.get("why_it_matters")))
        out.append("   - Fix: %s" % _esc(it.get("fix")))
        if it.get("honesty_note"):
            out.append("   - Honesty: %s" % _esc(it["honesty_note"]))
    if ranked:
        out.append("")
    if notes:
        out.append("## Notes (not scored)")
        out.append("")
        for it in notes:
            ev = (" Seen: %s" % _esc(_join_ev(it["evidence"][:2]))) if it.get("evidence") else ""
            out.append("- **%s** (%s). %s%s" % (_esc(it.get("title")), _esc(it.get("id")), _esc(it.get("fix")), ev))
        out.append("")
    kw = _g(r, "keywords", default={})
    label = {"required": "Required", "preferred": "Preferred", "responsibility": "Duties", "unspecified": "Other"}
    rows = [(label.get(t.get("importance"), "Other"), t) for t in
            list(kw.get("required") or []) + list(kw.get("preferred") or []) + list(kw.get("other") or [])
            if isinstance(t, dict)]
    out.append("## Job keywords")
    out.append("")
    if kw.get("status") == "no_jd":
        out.append("No job posting was provided, so job keywords were not checked.")
    elif kw.get("status") == "not_english":
        out.append("Not checked: the %s." % _esc(kw.get("note") or "keyword dictionary is English-only"))
    elif kw.get("status") == "no_text":
        out.append("Not checked: no text could be read from the file.")
    elif not rows:
        out.append("No job terms were found in the posting.")
    else:
        if kw.get("status") == "thin_jd":
            out.append("The posting is short, so these terms are a rough guide and have no score.")
            out.append("")
        out.append("| Term | Importance | Status | Where on your resume |")
        out.append("|---|---|---|---|")
        for label, t in rows[:40]:
            where = ", ".join(_SECTION_NAME.get(x, x) for x in (t.get("resume_locations") or []))
            lvl = _LEVEL.get(t.get("evidence_level"), "")
            if where and lvl:
                where = "%s (%s)" % (where, lvl)
            out.append("| %s | %s | %s | %s |" % (_esc(t.get("term")), label, _status(t), _esc(where) or "-"))
        out.append("")
        out.append("Only add a term you can back up in an interview.")
    out.append("")
    kos = [k for k in _g(r, "knockout_signals", default=[]) if isinstance(k, dict)]
    if kos:
        out.append("## Questions the application may ask (not scored)")
        out.append("")
        for k in kos:
            quote = bullet_split(str(k.get("jd_quote") or ""))[1]
            out.append("- **%s** (%s): \"%s\" %s" % (_KO_TYPE.get(k.get("type"), "Other"),
                                                   _KO_STATUS.get(k.get("status"), "Unclear"),
                                                   _esc(clip(quote, 160)), _esc(k.get("advice"))))
        out.append("")
    out.append("## What the parser read")
    out.append("")
    c = _g(r, "contact", default={})
    bits = []
    for key, label in (("name", "name"), ("email", "email"), ("phone", "phone"), ("location", "location"),
                       ("linkedin", "LinkedIn")):
        bits.append("%s %s" % (label, "found" if c.get(key) else "not found"))
    out.append("- Contact: %s." % ", ".join(bits))
    if c.get("email") or c.get("phone"):
        shown = ", ".join(x for x in (c.get("email"), c.get("phone")) if x)
        out.append("- Contact as read (masked): %s" % _esc(mask_all(shown)))
    order = _g(r, "sections", "order", default=[])
    out.append("- Sections in order: %s." % (", ".join(_SECTION_NAME.get(x, x) for x in order) or "none found"))
    ents = _g(r, "experience", "entries", default=[])
    gaps = _g(r, "experience", "gaps", default=[])
    out.append("- Dated entries: %d. Gaps longer than 6 months: %d (for your information only)." % (
        sum(1 for e in ents if isinstance(e, dict) and e.get("date_text")), len(gaps)))
    out.append("- Text was read with: %s." % _esc(_g(r, "extraction", "method", default="unknown")))
    out.append("")
    notes = _g(r, "platform", "notes", default=[])
    if notes:
        out.append("## Notes for this application site")
        out.append("")
        for n in notes:
            out.append("- %s" % _esc(_g(n, "text", default="")))
        out.append("")
    lims = _g(r, "limitations", default=[])
    if lims:
        out.append("## Limitations")
        out.append("")
        for x in lims:
            out.append("- %s" % _esc(x))
        out.append("")
    out.append("## About this check")
    out.append("")
    out.append(_esc(_g(r, "disclaimer", default="")))
    text = "\n".join(out).rstrip() + "\n"
    return mask_all(text).replace("—", "-")


def _brief_title(jt):
    if not isinstance(jt, dict):
        return None
    return {"jd_title": jt.get("jd_title"), "match": jt.get("match"),
            "resume_titles": [clip(x, 60) for x in (jt.get("resume_titles") or [])[:3]]}


def make_brief(result):
    """Compact summary for reviewer subagents (ARCHITECTURE 6.3, about 2k tokens or less)."""
    r = result if isinstance(result, dict) else {}
    s = _g(r, "scores", default={})

    def sv(name):
        return {"value": _g(s, name, "value"), "band": _g(s, name, "band")}
    issues = [i for i in _g(r, "issues", default=[]) if isinstance(i, dict)]
    top = []
    for it in issues[:12]:
        top.append({"id": it.get("id"), "severity": it.get("severity"), "title": it.get("title"),
                    "evidence": clip(mask_all(clip(_join_ev([e for e in (it.get("evidence") or [])
                                                             if isinstance(e, str)]), 400)), 160)})
    kw = _g(r, "keywords", default={})
    rows = list(kw.get("required") or []) + list(kw.get("preferred") or []) + list(kw.get("other") or [])
    kws = []
    for t in rows[:30]:
        kws.append({"term": clip(t.get("term"), 60), "importance": t.get("importance"), "found": t.get("found"),
                    "match_type": t.get("match_type"), "evidence_level": t.get("evidence_level"),
                    "resume_wording": clip(t.get("resume_wording"), 60) if t.get("resume_wording") else None})
    cov = dict(kw.get("coverage") or {})
    cov.pop("listed_only", None)
    cov["status"] = kw.get("status")
    cov["summary"] = required_line(r)
    kos = []
    for k in _g(r, "knockout_signals", default=[])[:8]:
        kos.append({"type": k.get("type"), "importance": k.get("importance"),
                    "jd_quote": clip(k.get("jd_quote"), 120), "status": k.get("status")})
    return {
        "scores": {"overall": sv("overall"), "parse_safety": sv("parse_safety"),
                   "keyword_match": sv("keyword_match"), "content_signals": sv("content_signals")},
        "precision_note": _g(s, "precision_note"),
        "disclaimer": _g(r, "disclaimer"),
        "top_issues": top,
        "keywords": kws,
        "coverage": cov,
        "knockouts": kos,
        "job_title": _brief_title(_g(r, "keywords", "job_title")),
        "platform_guess": _g(r, "platform", "guess"),
        "language": _g(r, "language"),
    }
