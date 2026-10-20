"""run_screening: Document + job posting -> screening.json dict (ARCHITECTURE 6, ATS spec 6-17).

Deterministic: the same Document, posting text, as-of date, terms and dictionary version give
byte-identical JSON. The only date in the output is the as-of date (generated_at == as_of).
"""
import hashlib
import re

from .. import __version__
from ..util import today_iso
from . import constants as C
from .contact import extract_contact
from .content import analyze_bullets, readability
from .dates import as_of_month
from .entries import entry_record, mark_implied_bullets, segment_entries, timeline
from .issues import (IssueSet, detect_contact, detect_content, detect_dates, detect_keywords,
                     detect_parse, detect_sections)
from .jd import guess_platform, guess_title, parse_jd, split_jd_lines
from .knockouts import find_knockouts, graduation_info
from .lexicon import load_lexicon
from .match import ResumeText, match_row
from .scoring import keyword_score, rank_issues, score_all
from .sections import assign_sections, build_lines
from .terms import extract_terms, resume_acronym_defs, verify_llm_terms
from .textutil import clip, detect_language
from .tokens import stem, tokenize

_METHODS = ("docx-xml", "pdfplumber", "pypdf", "pdfkit", "builtin-pdf", "text", "rtf", "none")
_FORMATS = ("docx", "pdf", "txt", "md", "rtf", "doc", "pages", "odt", "image", "unknown")
_LOCALE_RE = re.compile(r"^[a-z]{2,3}(?:-[A-Z]{2})?$")
_AS_OF_RE = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$")


def _text(v):
    if v is None:
        return ""
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    return v if isinstance(v, str) else ""


def _sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _int_or_none(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def _str_or_none(v, n=200):
    return clip(v, n) if isinstance(v, str) and v.strip() else None


def run_screening(doc, jd_text, *, stage="student", as_of=None, locale="en-US", jd_url=None, jd_title=None,
                  terms=None, data_dir=None):
    """Screen one resume Document against one job posting. Returns the screening.json dict.

    Never raises on bad content. Raises hp.screen.LexiconError if a dictionary file is missing.
    """
    lex = load_lexicon(data_dir)
    warnings = []
    doc = dict(doc) if isinstance(doc, dict) else {}       # shallow copy: the caller's dict is not changed
    for key, typ in (("warnings", list), ("errors", list), ("lines", list), ("header_footer", list),
                     ("signals", dict)):
        if not isinstance(doc.get(key), typ):
            doc[key] = typ()
    jd_text = _text(jd_text)
    if not isinstance(as_of, str) or not _AS_OF_RE.match(as_of):
        if as_of is not None:
            warnings.append("as_of was not a YYYY-MM-DD date; today's date was used.")
        as_of = today_iso()
    if stage not in C.STAGES:
        warnings.append("Unknown stage; 'student' was used.")
        stage = "student"
    if not isinstance(locale, str) or not _LOCALE_RE.match(locale):
        warnings.append("Unknown locale; 'en-US' was used.")
        locale = "en-US"
    as_of_m = as_of_month(as_of)
    norms = lex.norms_for(locale)
    doc_word = "CV" if str(norms.get("word", "resume")).upper() == "CV" else "resume"
    for w in doc["warnings"][:20]:
        if isinstance(w, str) and w.strip():
            warnings.append(clip(w, 200))

    # ------------------------------------------------------------ resume structure
    lines, hf, splits = build_lines(doc, as_of_m, warnings, lex)
    detected, order = assign_sections(lines, lex)
    has_headings = any(rl.heading for rl in lines)
    top_count = next((k for k, rl in enumerate(lines) if rl.heading and rl.section != "contact"), len(lines))
    contact, cdetails = extract_contact(lines, hf, top_count, lex, locale)
    # No Experience/Projects-type heading recognized: dated groups elsewhere still count as entries.
    fallback = not any(d["canonical"] in C.ENTRY_SECTIONS and not d["inline"] for d in detected)
    lines = mark_implied_bullets(lines, lex, fallback)
    entries = segment_entries(lines, fallback, lex)
    tl = timeline(entries, as_of_m)
    bm, bdetails, content_bullets = analyze_bullets(lines, entries, lex, has_headings)
    has_text = bool(lines)
    body_text = "\n".join(rl.text for rl in lines)
    language, _lang_details = detect_language(body_text, lex.stopwords_en) if has_text else ("und", {})
    english = has_text and language == "en"
    if has_text and not english:
        warnings.append("This %s does not look like English, so keyword and content checks were skipped." % doc_word)
    if any(re.search(r"(?i)\b(?:ignore|disregard) (?:all |any )?(?:previous|prior|above) instructions\b|"
                     r"\bas an ai\b|\b(?:chatgpt|language model|llm)\b.{0,40}\b(?:rank|score|select|hire)\b",
                     t) for t in [rl.text for rl in lines] + [h["text"] for h in hf]):
        warnings.append("The %s contains text addressed to AI tools. It was treated as plain text." % doc_word)

    # ------------------------------------------------------------ job posting
    parsed = parse_jd(jd_text, lex)
    jd_chars = len(jd_text.strip())
    has_jd = bool(split_jd_lines(jd_text))
    title = guess_title(parsed, lex, jd_title) if (has_jd or jd_title) else None
    platform = guess_platform(jd_url, jd_text)
    jd_lang = "en"
    if has_jd:
        jd_lang, _ = detect_language("\n".join(ln["text"] for ln in parsed["lines"]), lex.stopwords_en)
    llm_terms, term_stats = verify_llm_terms(terms, jd_text, parsed, warnings) if has_jd else ([], {
        "provided": len(terms) if isinstance(terms, list) else 0, "accepted": 0,
        "rejected": len(terms) if isinstance(terms, list) else 0})
    if not has_jd and isinstance(terms, list) and terms:
        warnings.append("terms: ignored because no job description was provided")

    kw_status = "checked"
    km_band_null = None
    km_reason = None
    if not has_jd:
        kw_status, km_band_null = "no_jd", C.KM_BAND_NO_JD
    elif not has_text:
        kw_status, km_band_null = "no_text", C.KM_BAND_NO_TEXT
    elif not english or jd_lang != "en":
        kw_status, km_band_null, km_reason = "not_english", C.KM_BAND_NOT_ENGLISH, C.KM_REASON_NOT_ENGLISH

    term_rows = []
    rt = None
    if kw_status in ("checked",):
        resume_defs = resume_acronym_defs([rl.text for rl in lines])
        term_list, extra_index = extract_terms(parsed, lex, resume_defs, llm_terms, warnings)
        rt = ResumeText(lines, hf, lex, extra_index, has_headings)
        for t in term_list:
            m = match_row(t, rt, lex)
            row = dict(t)
            row.update(m)
            term_rows.append(row)
        n_terms = len(term_rows)
        if jd_chars < C.KM_MIN_JD_CHARS or n_terms < C.KM_MIN_TERMS:
            kw_status, km_band_null = "thin_jd", C.KM_BAND_THIN

    # ------------------------------------------------------------ job title match
    title_match = _title_match(title, lines, entries, lex, contact["name"]) if has_jd else {
        "jd_title": None, "resume_titles": [], "match": "unknown"}

    # ------------------------------------------------------------ knockouts
    knockouts = []
    if has_jd:
        edu_lines = [rl.text for rl in lines if rl.block == "education" and not rl.heading]
        grad_m, grad_text = graduation_info(entries, as_of)
        edu_expected = any(e.section == "education" and (e.expected or (e.period(as_of_m)[1] or 0) >= as_of_m)
                           for e in entries)
        resume_texts = [rl.text for rl in lines]

        def cert_evidence(text):
            toks = tokenize(text)
            for i, n, key, fk, fj, via in lex.index.scan(toks, longest_only=True):
                e = lex.by_id[key]
                if e["kind"] != "cert":
                    continue
                if rt is not None:
                    for o in rt.hits.get(key, ()):
                        return o["row"]["text"]
                else:
                    for t in resume_texts:
                        if any(h[2] == key for h in lex.index.scan(tokenize(t), longest_only=False)):
                            return t
            return None
        knockouts = find_knockouts(parsed, {
            "education_lines": edu_lines, "total_months": tl["total_months_experience"],
            "contact_location": contact["location"], "resume_texts": resume_texts,
            "cert_evidence": cert_evidence, "graduation_month": grad_m, "graduation_text": grad_text,
            "edu_expected": edu_expected, "as_of": as_of})

    # ------------------------------------------------------------ issues
    iss = IssueSet(doc_word)
    ctx = {"stage": stage, "locale": locale, "norms": norms, "english": english, "as_of_m": as_of_m,
           "contact_where": cdetails["where"], "splits": splits}
    detect_parse(iss, doc, lines, hf, ctx)
    if has_text:
        detect_contact(iss, contact, ctx)
        if english:
            detect_sections(iss, lines, detected, ctx, entries, lex)
            detect_dates(iss, lines, entries, tl, ctx)
            detect_content(iss, lines, entries, bm, bdetails, ctx, lex)
    kw = None
    km = {"value_raw": None, "band_null": km_band_null, "impacts": {}, "explanation": ""}
    if kw_status == "checked":
        kw = keyword_score(term_rows)
        detect_keywords(iss, kw, kw["value_raw"], title_match)
        km["value_raw"] = kw["value_raw"]
        km["impacts"] = {k: v for k, v in kw["impacts"].items() if iss.has(k)}
        km["basis_found"] = sum(1 for t in kw["basis_terms"] if t["found"])
        km["basis_total"] = len(kw["basis_terms"])
    issues = iss.list()
    km["explanation"] = _km_explanation(kw_status, kw, term_rows, km_reason)
    cs_null_band = C.CS_BAND_NO_TEXT if not has_text else C.CS_BAND_NOT_ENGLISH
    if kw_status == "checked":
        method = C.OVERALL_METHOD
    elif has_text and english:
        method = C.OVERALL_METHOD_NO_KM
    else:
        method = C.OVERALL_METHOD_PS_ONLY
    scores = score_all(issues, bm, iss.counts, km,
                       {"has_text": has_text, "english": english, "cs_null_band": cs_null_band,
                        "overall_method": method})
    scores["precision_note"] = C.PRECISION_NOTE
    rank_issues(issues)

    # ------------------------------------------------------------ keywords block
    keywords = _keywords_block(kw_status, term_rows, kw, title_match, km_reason)

    # ------------------------------------------------------------ assemble
    method_name = doc.get("method") if doc.get("method") in _METHODS else ("none" if not has_text else "unknown")
    fmt = doc.get("format") if doc.get("format") in _FORMATS else "unknown"
    column_check = _column_check(doc, fmt)
    limitations = [s.replace("{method}", method_name).replace("{columns}", C.COLUMN_TEXT[column_check])
                   for s in C.LIMITATIONS_BASE]
    if not has_jd:
        limitations.append(C.LIMITATION_NO_JD)
    elif kw_status == "thin_jd":
        limitations.append(C.LIMITATION_THIN_JD)
    if has_text and not english:
        limitations.append(C.LIMITATION_NOT_ENGLISH.replace("{doc}", doc_word))
    disclaimer = C.DISCLAIMER            # fixed text, never localized or edited
    platform_notes = [{"text": t, "source_refs": refs} for t, refs in C.PLATFORM_NOTES.get(platform, [])]

    sha = doc.get("sha256") if isinstance(doc.get("sha256"), str) else None
    out = {
        "schema_version": C.SCHEMA_VERSION,
        "tool": {"name": C.TOOL_NAME, "version": __version__, "lexicon_version": lex.version},
        "mode": "script",
        "generated_at": as_of,
        "as_of": as_of,
        "level": stage,
        "locale": locale,
        "language": language,
        "inputs": {
            "resume": {"format": fmt, "sha256": sha, "bytes": _int_or_none(doc.get("bytes")),
                       "pages": _int_or_none(doc.get("pages")), "producer": _str_or_none(doc.get("producer")),
                       "creator": _str_or_none(doc.get("creator"))},
            "job_description": {"sha256": _sha(jd_text) if has_jd else None, "chars": jd_chars,
                                "title_guess": title, "url": _str_or_none(jd_url, 500),
                                "platform_guess": platform, "language": jd_lang if has_jd else None,
                                "blocks": parsed["blocks"]},
            "terms": term_stats,
        },
        "extraction": {
            "method": method_name, "text_chars": len(body_text), "lines": len(lines), "ats_view_file": None,
            "header_footer_text": clip(" | ".join(h["text"] for h in hf), 500) if hf else None,
            "column_check": column_check, "warnings": _dedupe(warnings),
        },
        "scores": scores,
        "issues": issues,
        "keywords": keywords,
        "knockout_signals": knockouts,
        "sections": {"detected": detected, "missing_core": _missing_core(detected, stage) if english else [],
                     "order": order},
        "contact": contact,
        "experience": {
            "entries": [entry_record(e, as_of_m) for e in entries],
            "gaps": tl["gaps"],
            "months_since_last_activity": tl["months_since_last_activity"],
            "total_months_experience": tl["total_months_experience"],
            "date_formats_consistent": not iss.has("DATE-004"),
            "reverse_chronological": (not iss.has("DATE-007")) if tl["dated_count"] >= 2 else None,
        },
        "bullets": bm,
        "readability": readability([rl.btext for rl in content_bullets]),
        "platform": {"guess": platform, "notes": platform_notes},
        "limitations": limitations,
        "disclaimer": disclaimer,
    }
    return out


def _dedupe(items):
    out = []
    for x in items:
        if x not in out:
            out.append(x)
    return out[:40]


def _column_check(doc, fmt):
    sig = doc.get("signals") if isinstance(doc.get("signals"), dict) else {}
    cols = sig.get("columns") if isinstance(sig.get("columns"), dict) else {}
    if cols.get("pdf_check") == "performed":
        return "performed"
    if fmt == "docx":
        return "docx_section_only"
    if fmt in ("txt", "md"):
        return "not_applicable"
    return "unavailable"


def _missing_core(detected, stage):
    present = {d["canonical"] for d in detected}
    core = (["education"] if stage == "student" else []) + ["experience", "skills"]
    return [c for c in core if c not in present]


def _public_term(t):
    return {
        "term": clip(t["term"], 120), "canonical": clip(t["canonical"], 120), "kind": t["kind"],
        "importance": t["importance"], "weight": t["weight"], "jd_frequency": t["jd_frequency"],
        "jd_quote": clip(t["jd_quote"], 200), "source": t["source"], "confidence": t["confidence"],
        "found": t["found"], "match_type": t["match_type"], "credit": t["credit"],
        "resume_wording": t["resume_wording"], "evidence_level": t["evidence_level"],
        "resume_locations": t["resume_locations"], "snippets": t["snippets"],
        "group": t.get("group"), "alternatives": [clip(a, 80) for a in t.get("alternatives") or []],
        "matched_alternative": clip(t["matched_alternative"], 80) if t.get("matched_alternative") else None,
    }


def _keywords_block(status, rows, kw, title_match, reason):
    req = [r for r in rows if r["importance"] == "required"]
    pref = [r for r in rows if r["importance"] in ("preferred", "responsibility")]
    other = [r for r in rows if r["importance"] == "unspecified"]

    def found(ts):
        return sum(1 for t in ts if t["found"])

    def listed(ts):
        return sum(1 for t in ts if t["found"] and t["evidence_level"] == "listed")
    basis = kw["basis_terms"] if kw else req
    cov = {
        "required_found": found(req), "required_total": len(req), "required_listed_only": listed(req),
        "preferred_found": found(pref), "preferred_total": len(pref),
        "other_found": found(other), "other_total": len(other),
        "basis": kw["basis"] if kw else None,
        "basis_found": found(basis), "basis_total": len(basis), "basis_listed_only": listed(basis),
        "required_weighted": round(kw["R"], 2) if kw else None,
        "preferred_weighted": round(kw["P"], 2) if (kw and kw["P"] is not None) else None,
        "evidence_share": round(kw["E"], 2) if kw else None,
        "listed_only": [t["term"] for t in rows if t["found"] and t["evidence_level"] == "listed"],
    }
    return {"status": status, "note": reason, "required": [_public_term(t) for t in req],
            "preferred": [_public_term(t) for t in pref], "other": [_public_term(t) for t in other],
            "job_title": title_match, "coverage": cov}


def _km_explanation(status, kw, rows, reason):
    if status == "no_jd":
        return "No job posting was provided, so job keywords were not checked."
    if status == "no_text":
        return "No resume text could be read, so job keywords were not checked."
    if status == "not_english":
        return "Not checked: the %s." % reason
    req = [r for r in rows if r["importance"] == "required"]
    pref = [r for r in rows if r["importance"] in ("preferred", "responsibility")]
    if status == "thin_jd":
        return ("The posting is too short or has too few job terms (under 300 characters or under 5 "
                "terms) to score fairly. Terms found: %d of %d." % (sum(1 for r in rows if r["found"]), len(rows)))
    if kw["basis"] == "all_terms":
        n = len(kw["basis_terms"])
        f = sum(1 for t in kw["basis_terms"] if t["found"])
        lo = sum(1 for t in kw["basis_terms"] if t["found"] and t["evidence_level"] == "listed")
        return ("The posting has no separate requirements list, so all %d job terms count: %d of %d found "
                "(%d only in your skills list)." % (n, f, n, lo))
    f = sum(1 for t in req if t["found"])
    lo = sum(1 for t in req if t["found"] and t["evidence_level"] == "listed")
    s = "Required terms: %d of %d found (%d only in your skills list)." % (f, len(req), lo)
    if pref:
        s += " Preferred terms: %d of %d found." % (sum(1 for t in pref if t["found"]), len(pref))
    s += (" Weighted 70% required, 20% preferred and duties, 10% shown in experience."
          if kw["basis"] == "required_preferred" else " Weighted 90% required, 10% shown in experience.")
    return s


_TITLE_EQUIV = {"internship": "intern", "co-op": "intern", "coop": "intern"}


def _title_words(s, lex):
    out = []
    for t in tokenize(s):
        w = _TITLE_EQUIV.get(t.cf, t.cf)
        if w in lex.stopwords_en or not any(c.isalpha() for c in w):
            continue
        out.append(stem(w)[0])
    return out


def _title_match(title, lines, entries, lex, name=None):
    """Does the posting's job title appear on the resume (entry headers or the top lines)?
    The candidate's name and contact lines are never listed as titles."""
    if not title:
        return {"jd_title": None, "resume_titles": [], "match": "unknown"}
    cands = []
    for e in entries:
        if e.section in ("experience", "leadership_activities", "volunteer", "projects") and e.header_lines:
            for rl in e.header_lines[:2]:
                if rl.text not in cands:
                    cands.append(rl.text)
    for rl in lines:
        if rl.heading:
            break
        if "@" in rl.text or rl.text == name or rl.text in cands or re.search(r"\d{3}", rl.text):
            continue
        cands.append(rl.text)
    for rl in lines:
        if rl.section == "summary" and not rl.heading and rl.text not in cands:
            cands.append(rl.text)
            break
    want = _title_words(title, lex)
    best = "none"
    if want:
        for c in cands:
            have = _title_words(c, lex)
            n = len(want)
            if any(have[i:i + n] == want for i in range(len(have) - n + 1)):
                best = "exact"
                break
            hits = sum(1 for w in want if w in have)
            if n >= 2 and hits >= max(2, -(-2 * n // 3)):
                best = "close"
    return {"jd_title": title, "resume_titles": [clip(c, 80) for c in cands[:8]], "match": best}
