"""Release gate on the generated resume files (ARCHITECTURE.md section 13, `render`).

After the renderer writes First_Last_Resume.{docx,pdf,md}, the gate reads the .docx and the .pdf back
the way parsing software would (hp.ingest), re-runs the simulated screening check on each with the same
job posting and terms ("screening after"), and checks:

  parse      parse_safety >= 90 and no critical or high PARSE-* issue
  merged     no words glued together where a tab or column was dropped (ingest's tab_merged_tokens
             for the .docx, plus a scan for extracted words that are two source words joined)
  recovery   at least 98% of the words in the .md come back out of the file (multiset recall)
  order      at least 90% of those words come back in the same order (reading order)
  content    every non-empty org, role, name, school, degree, field, minor, context and location string and
             every bullet in resume.json comes back out of the .docx, the .pdf and the .md (normalized
             words, in order). The other checks compare the files with the .md, which is rendered from
             the same blocks, so only this one catches a renderer that drops a field everywhere.

The .md is the comparison text because it is rendered from the same blocks as the .docx and the .pdf.
`run_gate()` writes work/screening/after/<docx|pdf>/{screening.json, screening.md, ats_view.txt} and
returns the gate dict; the CLI writes work/gate.json and decides whether to retry with the inline
layout (only for merged-word or reading-order failures, never to hide a parse problem).

Deterministic: no timestamps or absolute paths in the result.
"""
import collections
import difflib
import os
import re

from hp.util import norm_text, write_json, write_text

GATE_VERSION = "1.0"
MIN_PARSE_SAFETY = 90
MIN_RECOVERY = 0.98
MIN_ORDER = 0.90
BLOCKING_SEVERITIES = ("critical", "high")
RETRY_CODES = ("merged_tokens", "reading_order")   # failures the inline layout can fix

_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)


def words(text):
    """Casefolded word tokens of a text (letters and digits; punctuation and bullets dropped)."""
    return _WORD_RE.findall(norm_text(text or "").casefold())


def md_words(md_text):
    """Word tokens of the rendered Markdown. Its syntax (#, -, **, *, ==, backslash escapes, " | ") is
    all punctuation, which words() drops, so no Markdown parsing is needed."""
    return words(md_text)


def doc_text(doc):
    """Everything an extractor got out of a file: header/footer lines plus body lines."""
    parts = [h.get("text") or "" for h in doc.get("header_footer") or [] if isinstance(h, dict)]
    parts += [ln.get("text") or "" for ln in doc.get("lines") or [] if isinstance(ln, dict)]
    return "\n".join(parts)


def recovery(src_tokens, out_tokens):
    """Share of source tokens found in the extracted tokens (counting repeats)."""
    if not src_tokens:
        return 1.0
    src, out = collections.Counter(src_tokens), collections.Counter(out_tokens)
    hit = sum(min(n, out[t]) for t, n in src.items())
    return hit / float(len(src_tokens))


def order_match(src_tokens, out_tokens):
    """Share of source tokens that come back in the same relative order (longest matching blocks)."""
    if not src_tokens:
        return 1.0
    sm = difflib.SequenceMatcher(None, src_tokens, out_tokens, autojunk=False)
    return sum(b.size for b in sm.get_matching_blocks()) / float(len(src_tokens))


def merged_tokens(src_tokens, out_tokens, limit=10):
    """Extracted words that are two source words glued together ("AustinAustin", "StatisticsExpected")."""
    vocab = set(src_tokens)
    found = []
    for t in out_tokens:
        if t in vocab or len(t) < 4 or t in found:
            continue
        for i in range(2, len(t) - 1):
            if t[:i] in vocab and t[i:] in vocab:
                found.append(t)
                break
        if len(found) >= limit:
            break
    return found


CONTENT_FIELDS = ("org", "role", "name", "school", "degree", "field", "minor", "context", "location")
_PH_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")


def _s(x):
    return x if isinstance(x, str) else ("" if x is None else str(x))


def _bullet_variants(b, placeholders):
    """Ways the bullet may legitimately read in a file: answered placeholders filled in; the honest
    textIfUnknown; or (a draft) only the words around each placeholder."""
    text = _s(b.get("text"))
    out = []
    if not _PH_RE.search(text):
        return [[text]]
    filled, open_ = text, False
    for pid in _PH_RE.findall(text):
        ph = placeholders.get(pid) if isinstance(placeholders, dict) else None
        value = _s((ph or {}).get("value")).strip() if isinstance(ph, dict) else ""
        if isinstance(ph, dict) and ph.get("status") == "answered" and value:
            filled = re.sub(r"\{\{\s*%s\s*\}\}" % re.escape(pid), lambda _m, v=value: v, filled)
        else:
            open_ = True
    if not open_:
        out.append([filled])
    if _s(b.get("textIfUnknown")).strip():
        out.append([_s(b.get("textIfUnknown"))])
    out.append([seg for seg in _PH_RE.split(text)[::2] if seg.strip()])
    return out


def expected_content(resume):
    """What resume.json says the files must show: [{"where", "field", "text", "variants": [[segment, ...]],
    "sec": section number, "title": section title}] for every non-empty entry field in CONTENT_FIELDS and
    every bullet. Placeholder bullets accept the filled-in text, the honest textIfUnknown, or (drafts) the
    words around the placeholder."""
    out = []
    if not isinstance(resume, dict):
        return out
    placeholders = resume.get("placeholders") if isinstance(resume.get("placeholders"), dict) else {}
    for si, sec in enumerate(resume.get("sections") or []):
        if not isinstance(sec, dict):
            continue
        sid = _s(sec.get("id")) or "section%d" % (si + 1)
        title = _s(sec.get("title")).strip() or _s(sec.get("type")).strip().title() or "Custom"
        for ii, it in enumerate(sec.get("items") or []):
            if not isinstance(it, dict):
                continue
            eid = _s(it.get("id")) or "%s.item%d" % (sid, ii + 1)
            for f in CONTENT_FIELDS:
                v = _s(it.get(f)).strip()
                if v:
                    out.append({"where": eid, "field": f, "text": v, "variants": [[v]], "sec": si, "title": title})
            for bi, b in enumerate(it.get("bullets") or []):
                if isinstance(b, str):
                    b = {"text": b}
                if not isinstance(b, dict) or not _s(b.get("text")).strip():
                    continue
                bid = _s(b.get("id")) or "%s.b%d" % (eid, bi + 1)
                out.append({"where": bid, "field": "bullet", "text": _s(b.get("text")).strip(),
                            "variants": _bullet_variants(b, placeholders), "sec": si, "title": title})
    return out


class _TokenIndex(object):
    """Extracted words, searchable for a contiguous run of words. A second, space-free pass (on word
    boundaries) tolerates extractors that split or join words at line ends ("first-" / "year")."""

    def __init__(self, toks):
        self.spaced = " " + " ".join(toks) + " "
        self.squashed = "".join(toks)
        self.starts, self.ends, pos = set(), set(), 0
        for t in toks:
            self.starts.add(pos)
            pos += len(t)
            self.ends.add(pos)

    def has(self, text):
        toks = words(text)
        if not toks:
            return True
        if (" " + " ".join(toks) + " ") in self.spaced:
            return True
        s = "".join(toks)
        i = self.squashed.find(s)
        while i != -1:
            if i in self.starts and (i + len(s)) in self.ends:
                return True
            i = self.squashed.find(s, i + 1)
        return False


def _section_spans(expected, lines):
    """{section number: (first line, end line)} of each section's body in the extracted lines, found by its
    heading line in order. A section whose heading cannot be found is checked against the whole text."""
    line_words = [words(ln) for ln in lines]
    found, cursor = [], 0
    seen = set()
    for e in expected:
        if e["sec"] in seen:
            continue
        seen.add(e["sec"])
        want = words(e["title"])
        for i in range(cursor, len(lines)):
            if want and line_words[i] == want:
                found.append((e["sec"], i + 1))
                cursor = i + 1
                break
    spans = {}
    for k, (sec, start) in enumerate(found):
        end = found[k + 1][1] - 1 if k + 1 < len(found) else len(lines)
        spans[sec] = (start, end)
    return spans


def missing_content(expected, text):
    """The expected items (see expected_content) that do not come back out of an extracted text. Each item
    is looked for inside its own section (between its heading and the next one), so a certification name
    that also sits in the headline still counts as missing when its entry dropped it."""
    lines = (text or "").split("\n")
    spans = _section_spans(expected, lines)
    whole = _TokenIndex(words(text))
    indexes = {}
    out = []
    for e in expected:
        span = spans.get(e.get("sec"))
        if span is None:
            idx = whole
        else:
            idx = indexes.get(span)
            if idx is None:
                idx = indexes[span] = _TokenIndex(words("\n".join(lines[span[0]:span[1]])))
        if not any(all(idx.has(seg) for seg in v) for v in e["variants"]):
            out.append({"where": e["where"], "field": e["field"], "text": e["text"][:120]})
    return out


def _missing_detail(kind, missing):
    shown = ", ".join("%s '%s' (%s)" % (m["field"], m["text"][:60], m["where"]) for m in missing[:4])
    more = " and %d more" % (len(missing) - 4) if len(missing) > 4 else ""
    return ("%s: resume.json content is missing from the file: %s%s. The renderer dropped it; do not send "
            "this file" % (kind, shown, more))


def _load_resume_near(after_dir):
    """work/rewrite/resume.json next to work/screening/after (when the caller did not pass the resume)."""
    path = os.path.normpath(os.path.join(after_dir, os.pardir, os.pardir, "rewrite", "resume.json"))
    try:
        import json
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _screen_side(doc, jd_text, ctx):
    from hp.screen import run_screening
    return run_screening(doc, jd_text, stage=ctx["stage"], as_of=ctx["as_of"], locale=ctx["locale"],
                         jd_url=ctx.get("jd_url"), jd_title=ctx.get("jd_title"), terms=ctx.get("terms"))


def check_file(kind, path, md_text, jd_text, ctx, out_dir, expected=None):
    """Ingest one generated file, screen it, write the after-screening files, and run every check.
    `expected` (from expected_content) adds the content check: every resume.json entry field and bullet
    must come back out of the file."""
    from hp.ingest import ingest_file, write_ats_view
    from hp.screen import render_screening_md

    doc = ingest_file(path)
    result = _screen_side(doc, jd_text, ctx)
    result["extraction"]["ats_view_file"] = "screening/after/%s/ats_view.txt" % kind
    os.makedirs(out_dir, exist_ok=True)
    write_json(os.path.join(out_dir, "screening.json"), result)
    write_text(os.path.join(out_dir, "screening.md"), render_screening_md(result))
    write_ats_view(doc, os.path.join(out_dir, "ats_view.txt"))

    scores = result.get("scores") or {}
    ps = (scores.get("parse_safety") or {}).get("value")
    blocking = [i.get("id") for i in result.get("issues") or []
                if i.get("category") == "parse" and i.get("severity") in BLOCKING_SEVERITIES]
    src = md_words(md_text)
    out = words(doc_text(doc))
    rec = recovery(src, out)
    order = order_match(src, out)
    merged = merged_tokens(src, out)
    signals = doc.get("signals") or {}
    tab_merged = int(signals.get("tab_merged_tokens") or 0)

    failures = []
    if ps is None or ps < MIN_PARSE_SAFETY:
        failures.append({"code": "parse_safety",
                         "detail": "%s readability is %s (needs %d or more)" % (kind, ps, MIN_PARSE_SAFETY)})
    if blocking:
        failures.append({"code": "parse_issue",
                         "detail": "%s has a serious readability issue: %s" % (kind, ", ".join(blocking))})
    if tab_merged or merged:
        failures.append({"code": "merged_tokens",
                         "detail": "%s: words run together when tabs are dropped (%s)"
                                   % (kind, ", ".join(merged[:5]) or "%d spots" % tab_merged)})
    if rec < MIN_RECOVERY:
        failures.append({"code": "word_recovery",
                         "detail": "%s: only %.1f%% of the words came back out (needs %.0f%%)"
                                   % (kind, rec * 100, MIN_RECOVERY * 100)})
    if order < MIN_ORDER:
        failures.append({"code": "reading_order",
                         "detail": "%s: words come back out of order (%.1f%% in order, needs %.0f%%)"
                                   % (kind, order * 100, MIN_ORDER * 100)})
    missing = missing_content(expected, doc_text(doc)) if expected else []
    if missing:
        failures.append({"code": "content_missing", "detail": _missing_detail(kind, missing)})
    return {
        "checked": True,
        "file": os.path.basename(path),
        "extraction": doc.get("method"),
        "overall": (scores.get("overall") or {}).get("value"),
        "parse_safety": ps,
        "parse_band": (scores.get("parse_safety") or {}).get("band"),
        "keyword_match": (scores.get("keyword_match") or {}).get("value"),
        "blocking_parse_issues": blocking,
        "tab_merged_tokens": tab_merged,
        "merged_tokens": merged,
        "word_recovery": round(rec, 4),
        "order_match": round(order, 4),
        "content_checked": len(expected or []),
        "missing_content": missing,
        "passed": not failures,
        "failures": failures,
    }


def run_gate(files, md_path, jd_text, ctx, after_dir, resume=None):
    """Gate the rendered files. `files` is render_resume's files dict; `ctx` holds stage, as_of, locale,
    jd_url, jd_title and terms for the screening; `after_dir` is work/screening/after; `resume` is the
    resume.json dict the files were rendered from (default: work/rewrite/resume.json next to after_dir).

    Returns {"passed", "checks": {"docx", "pdf", "md"}, "failures": [...], "retryable": bool}."""
    try:
        with open(md_path, "r", encoding="utf-8") as f:
            md_text = f.read()
    except (OSError, TypeError):
        md_text = ""
    if resume is None:
        resume = _load_resume_near(after_dir)
    expected = expected_content(resume)
    checks = {}
    failures = []
    for kind in ("docx", "pdf"):
        path = files.get(kind)
        if not path or not os.path.isfile(path):
            checks[kind] = {"checked": False, "reason": "no %s file was produced" % kind}
            if kind == "docx":
                failures.append({"code": "missing_file", "detail": "the .docx was not produced"})
            continue
        res = check_file(kind, path, md_text, jd_text, ctx, os.path.join(after_dir, kind), expected)
        checks[kind] = res
        failures.extend(res["failures"])
    if md_text and expected:
        md_missing = missing_content(expected, md_text)
        md_fail = [{"code": "content_missing", "detail": _missing_detail("md", md_missing)}] if md_missing else []
        checks["md"] = {"checked": True, "file": os.path.basename(md_path), "content_checked": len(expected),
                        "missing_content": md_missing, "passed": not md_fail, "failures": md_fail}
        failures.extend(md_fail)
    retryable = bool(failures) and all(f["code"] in RETRY_CODES for f in failures)
    return {"passed": not failures, "checks": checks, "failures": failures, "retryable": retryable}


def keyword_note(before, after_check):
    """Informational: the ATS spec's 'KM after >= KM before unless unsupported terms were removed'."""
    b = ((before or {}).get("scores") or {}).get("keyword_match", {}).get("value")
    a = (after_check or {}).get("keyword_match")
    if b is None or a is None:
        return {"before": b, "after": a, "note": "not compared (no keyword match on one side)"}
    if a >= b:
        return {"before": b, "after": a, "note": "keyword match held or improved"}
    return {"before": b, "after": a,
            "note": "keyword match went down; check that only terms the candidate could not back up were removed"}


def gate_record(attempts, final, layout, before_screening):
    """The work/gate.json document."""
    after = final["checks"].get("docx") if final["checks"].get("docx", {}).get("checked") else \
        final["checks"].get("pdf")
    return {
        "schema_version": GATE_VERSION,
        "passed": final["passed"],
        "layout": layout,
        "retried_inline": len(attempts) > 1,
        "thresholds": {"parse_safety": MIN_PARSE_SAFETY, "word_recovery": MIN_RECOVERY, "order_match": MIN_ORDER},
        "attempts": [{"layout": a["layout"], "passed": a["passed"], "failures": a["failures"]} for a in attempts],
        "checks": final["checks"],
        "failures": final["failures"],
        "keyword_match": keyword_note(before_screening, after),
    }
