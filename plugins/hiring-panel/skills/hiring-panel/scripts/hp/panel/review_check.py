"""Reading, cleaning and validating one reviewer's JSON (ARCHITECTURE.md sections 8 and 9).

Two consumers with different needs:
- `check_review` / `validate_review` (CLI `validate RUN PATH`) are STRICT: full schema check plus
  every semantic rule, so the reviewer can be re-run once with a precise list of errors.
- `prepare_review` (used by synthesis) is LENIENT: a review is excluded only when it is unusable as a
  whole (not an object, wrong reviewer id, no valid verdict). Individual bad findings, quotes or
  strengths are dropped and logged, never fatal.
"""
import os
import re

from hp.panel import schema_lite
from hp.panel.common import (ADVANCE, CATEGORY_LABEL, CATS, CONFIDENCES, FIX_ORDER, LENS,
                             MAX_REVIEW_BYTES, REPORT_ORDER, REVIEWER_INFO, SEVERITIES, VERDICTS,
                             PanelError, SourceContext, as_list, check_evidence, clean_str, cap_words,
                             load_json_file, load_ledger, load_screening, match_norm, quote_in_line,
                             run_paths, schema_path)

MAX_FINDINGS = 7
MAX_OUT_OF_LENS = 2
GENERAL_REVIEW_BANNED = ("KEYWORD_GAP", "REQUIREMENT_UNPROVEN")
FINDING_ID_RE = re.compile(r"^[a-z_]+-[0-9]+$")


# ----------------------------------------------------------------------------- lenient preparation
def _fix(raw, where, log):
    fx = raw if isinstance(raw, dict) else {}
    ft = fx.get("fix_type")
    if ft not in FIX_ORDER:
        log.append({"where": where, "action": "fix_defaulted", "reason": "missing or unknown fix_type"})
        ft = "rewrite"
    q = clean_str(fx.get("candidate_question"), 200) or None
    return {"fix_type": ft, "suggestion": clean_str(fx.get("suggestion"), 280), "candidate_question": q}


def prepare_finding(rid, raw, index, ctx, log, lens_state):
    """Clean one reviewer finding. Returns the internal finding dict, or None when it is dropped.
    `lens_state` counts out-of-lens findings kept so far for this reviewer."""
    if not isinstance(raw, dict):
        log.append({"where": "{}:#{}".format(rid, index + 1), "action": "finding_dropped",
                    "reason": "finding is not an object"})
        return None
    fid = raw.get("id") if isinstance(raw.get("id"), str) and FINDING_ID_RE.match(raw.get("id")) \
        else "{}-{}".format(rid, index + 1)
    where = "{}:{}".format(rid, fid)
    cat, sev = raw.get("category"), raw.get("severity")
    if not isinstance(cat, str) or cat not in CATS:
        log.append({"where": where, "action": "finding_dropped", "reason": "unknown category"})
        return None
    if sev not in SEVERITIES:
        log.append({"where": where, "action": "finding_dropped", "reason": "unknown severity"})
        return None
    if ctx.general_review and cat in GENERAL_REVIEW_BANNED:
        log.append({"where": where, "action": "finding_dropped",
                    "reason": "{} is not allowed in a general review (no posting)".format(cat)})
        return None
    evidence = check_evidence(raw.get("evidence"), ctx, where, log)
    if not evidence:
        log.append({"where": where, "action": "finding_dropped",
                    "reason": "no verifiable evidence (quote not found on its line, or unknown anchor)"})
        return None
    terms = []
    if cat == "KEYWORD_GAP":
        st = raw.get("searched_terms")
        terms = [clean_str(t, 80) for t in st if isinstance(t, str) and t.strip()][:12] \
            if isinstance(st, list) else []
        if not terms:
            log.append({"where": where, "action": "finding_dropped",
                        "reason": "KEYWORD_GAP without searched_terms"})
            return None
        found = [t for t in terms if ctx.term_found(t)]
        if found:
            log.append({"where": where, "action": "finding_dropped",
                        "reason": "claimed missing but the resume or the screening check has: {}".format(
                            ", ".join(found))})
            return None
    # Gaps and other info-level script items are never ranked as more than polish.
    info_cited = [e["anchor"] for e in evidence if e["anchor"].startswith("A:")
                  and (ctx.issues.get(e["anchor"][2:]) or {}).get("severity") == "info"]
    if info_cited and sev != "minor":
        log.append({"where": where, "action": "severity_capped", "from": sev, "to": "minor",
                    "reason": "cites info-level screening item {}".format(info_cited[0])})
        sev = "minor"
    out_of_lens = cat not in LENS[rid]
    if out_of_lens:
        if SEVERITIES.index(sev) < SEVERITIES.index("major"):
            log.append({"where": where, "action": "finding_dropped",
                        "reason": "outside the {} lens and below major".format(rid)})
            return None
        if lens_state["kept"] >= MAX_OUT_OF_LENS:
            log.append({"where": where, "action": "finding_dropped",
                        "reason": "over the cap of {} out-of-lens findings".format(MAX_OUT_OF_LENS)})
            return None
        lens_state["kept"] += 1
    conf = raw.get("confidence") if raw.get("confidence") in CONFIDENCES else "medium"
    family, stage, key = CATS[cat]
    return {
        "reviewer": rid, "id": fid, "auto": False, "category": cat, "family": family, "stage": stage,
        "merge_key": key, "severity": sev, "confidence": conf,
        "title": clean_str(raw.get("title"), 90) or CATEGORY_LABEL[cat],
        "detail": clean_str(raw.get("detail"), 420),
        "evidence": evidence, "searched_terms": terms, "fix": _fix(raw.get("fix"), where, log),
        "out_of_lens": out_of_lens,
    }


def prepare_strengths(rid, raw_list, ctx, log):
    out = []
    if not isinstance(raw_list, list):
        return out
    for i, raw in enumerate(raw_list[:4]):
        if not isinstance(raw, dict):
            log.append({"where": "{}:s#{}".format(rid, i + 1), "action": "strength_dropped",
                        "reason": "strength is not an object"})
            continue
        sid = clean_str(raw.get("id"), 40) or "{}-s{}".format(rid, i + 1)
        where = "{}:{}".format(rid, sid)
        ev = [e for e in check_evidence(raw.get("evidence"), ctx, where, log) if e["anchor"].startswith("R")]
        if not ev:
            log.append({"where": where, "action": "strength_dropped",
                        "reason": "no verifiable resume quote"})
            continue
        title = clean_str(raw.get("title"), 90)
        if not title:
            log.append({"where": where, "action": "strength_dropped", "reason": "no title"})
            continue
        out.append({"reviewer": rid, "id": sid, "title": title, "evidence": ev,
                    "underused": raw.get("underused") is True})
    return out


def prepare_questions(raw_list):
    out = []
    if not isinstance(raw_list, list):
        return out
    for raw in raw_list[:5]:
        if not isinstance(raw, dict):
            continue
        q = clean_str(raw.get("question"), 200)
        if not q:
            continue
        anchors = [a for a in raw.get("related_anchors") or [] if isinstance(a, str)] \
            if isinstance(raw.get("related_anchors"), list) else []
        out.append({"question": q, "why": clean_str(raw.get("why"), 160), "related_anchors": anchors[:6]})
    return out


def prepare_review(rid, raw, ctx, log):
    """Turn one raw review into the internal form used by synthesis, or None if unusable."""
    where = rid
    if not isinstance(raw, dict):
        log.append({"where": where, "action": "review_rejected", "reason": "not a JSON object"})
        return None
    if raw.get("reviewer_id") != rid:
        log.append({"where": where, "action": "review_rejected",
                    "reason": "reviewer_id {!r} does not match the file name".format(
                        clean_str(raw.get("reviewer_id"), 40))})
        return None
    if raw.get("verdict") not in VERDICTS:
        log.append({"where": where, "action": "review_rejected", "reason": "missing or unknown verdict"})
        return None
    advance = raw.get("advance")
    if advance not in ADVANCE:
        log.append({"where": where, "action": "advance_defaulted", "reason": "missing or unknown advance"})
        advance = "unsure"
    take = clean_str(raw.get("one_line_take"), 200)
    if len(take.split()) > 20:
        take = cap_words(take, 20)
        log.append({"where": where, "action": "take_truncated", "reason": "one_line_take over 20 words"})
    findings_raw = raw.get("findings") if isinstance(raw.get("findings"), list) else []
    if not isinstance(raw.get("findings"), list):
        log.append({"where": where, "action": "findings_missing", "reason": "findings is not a list"})
    if len(findings_raw) > MAX_FINDINGS:
        log.append({"where": where, "action": "findings_capped",
                    "reason": "{} findings; only the first {} are used".format(len(findings_raw), MAX_FINDINGS)})
        findings_raw = findings_raw[:MAX_FINDINGS]
    lens_state = {"kept": 0}
    findings = []
    for i, f in enumerate(findings_raw):
        item = prepare_finding(rid, f, i, ctx, log, lens_state)
        if item is not None:
            findings.append(item)
    lens = raw.get("lens_data") if isinstance(raw.get("lens_data"), dict) else {}
    return {
        "id": rid, "verdict": raw["verdict"], "advance": advance,
        "confidence": raw.get("confidence") if raw.get("confidence") in CONFIDENCES else "medium",
        "one_line_take": take, "findings": findings,
        "strengths": prepare_strengths(rid, raw.get("strengths"), ctx, log),
        "questions": prepare_questions(raw.get("questions_for_candidate")),
        "lens_data": lens,
    }


# ----------------------------------------------------------------------------- strict validation
_schema_cache = {}


def load_review_schema():
    path = schema_path("review.schema.json")
    if path not in _schema_cache:
        data, err = load_json_file(path)
        _schema_cache[path] = data if not err and isinstance(data, dict) else None
    return _schema_cache[path]


def _reviewer_from_path(path):
    stem = os.path.splitext(os.path.basename(path))[0]
    return stem if stem in REVIEWER_INFO else None


def _brief_keywords(brief):
    rows = {}
    if isinstance(brief, dict) and isinstance(brief.get("keywords"), list):
        for row in brief["keywords"]:
            if isinstance(row, dict) and isinstance(row.get("term"), str):
                rows.setdefault(match_norm(row["term"]), row)
    return rows


def check_review(run_dir, review_path):
    """Strict check of one review file. Returns
    {"ok", "usable", "reviewer_id", "errors": [str], "warnings": [str], "repairs": [log entries]}.
    `usable` means synthesis would include the review (possibly dropping some findings)."""
    result = {"ok": False, "usable": False, "reviewer_id": None, "errors": [], "warnings": [], "repairs": []}
    errors, warnings = result["errors"], result["warnings"]
    paths = run_paths(run_dir)
    if not os.path.isabs(review_path) and not os.path.exists(review_path):
        alt = os.path.join(paths["reviews"], review_path)
        review_path = alt if os.path.exists(alt) else review_path
    try:
        ledger = load_ledger(paths["ledger"])
    except PanelError as e:
        errors.append(str(e))
        return result
    log = []
    ctx = SourceContext(ledger, load_screening(paths["screening"], log))
    raw, err = load_json_file(review_path, MAX_REVIEW_BYTES)
    if err:
        errors.append("review file {}: write ONE JSON object and nothing else".format(err))
        return result
    if not isinstance(raw, dict):
        errors.append("the review must be one JSON object, not {}".format(type(raw).__name__))
        return result
    rid = raw.get("reviewer_id") if isinstance(raw.get("reviewer_id"), str) \
        and raw.get("reviewer_id") in REVIEWER_INFO else None
    result["reviewer_id"] = rid
    file_rid = _reviewer_from_path(review_path)
    if file_rid and rid and file_rid != rid:
        errors.append("reviewer_id is {!r} but the file is reviews/{}.json".format(rid, file_rid))

    schema = load_review_schema()
    if schema is None:
        warnings.append("review.schema.json not found next to the scripts; schema checks skipped")
    else:
        for e in schema_lite.validate(raw, schema, max_errors=25):
            errors.append("schema " + e)

    if rid is None:
        if not any("reviewer_id" in e for e in errors):
            errors.append("reviewer_id must be one of " + ", ".join(REPORT_ORDER))
        return result

    take = raw.get("one_line_take")
    if isinstance(take, str) and len(take.split()) > 20:
        errors.append("one_line_take has {} words; keep it to 20 or fewer".format(len(take.split())))

    try:
        prepared = prepare_review(rid, raw, ctx, log)
    except Exception as e:   # hostile content must produce an error message, never a traceback
        errors.append("review could not be read safely ({}); rewrite it to match _output-format.md".format(
            type(e).__name__))
        return result
    result["usable"] = prepared is not None and (file_rid in (None, rid))
    _messages_from_log(log, result)

    # Out-of-lens flag honesty (the script decides lens membership from the category).
    for f in raw.get("findings") if isinstance(raw.get("findings"), list) else []:
        cat = f.get("category") if isinstance(f, dict) else None
        if isinstance(cat, str) and cat in CATS and f.get("out_of_lens") is True and cat in LENS[rid]:
            warnings.append("finding {}: {} is inside your lens; set out_of_lens to false".format(
                clean_str(f.get("id"), 40), f.get("category")))

    _check_student_text(raw, warnings)
    try:
        _check_lens_extras(rid, raw, ctx, paths, warnings)
    except Exception as e:   # lens_data extras are advisory; never let them crash validation
        warnings.append("lens_data could not be compared ({})".format(type(e).__name__))
    result["errors"] = _unique(errors)
    result["warnings"] = _unique(warnings)
    result["ok"] = not result["errors"]
    return result


def _unique(items):
    seen, out = set(), []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _messages_from_log(log, result):
    """Turn the lenient pass's log into reviewer-facing errors (things to fix and re-run) and warnings
    (repairs the script made on its own)."""
    errors, warnings = result["errors"], result["warnings"]
    by_where = {}
    for entry in log:
        by_where.setdefault(entry.get("where"), []).append(entry)
    for entry in log:
        act, where = entry.get("action"), entry.get("where", "")
        label = where.split(":", 1)[1] if ":" in where else where
        siblings = by_where.get(where, [])
        if act == "finding_dropped":
            reason = entry.get("reason", "")
            if "evidence" in reason:
                bad = [e for e in siblings if e.get("action") == "evidence_dropped"]
                hint = ""
                if bad:
                    quote = bad[0].get("quote")
                    hint = " ({} {}{})".format(bad[0].get("anchor", ""), bad[0].get("reason", ""),
                                               ": {!r}".format(quote) if quote else "")
                errors.append("finding {}: {}{}. Copy quotes word for word from the anchored line.".format(
                    label, reason, hint))
            else:
                errors.append("finding {}: {}".format(label, reason))
        elif act == "strength_dropped":
            errors.append("strength {}: {}".format(label, entry.get("reason")))
        elif act in ("review_rejected", "findings_capped"):
            errors.append(entry.get("reason"))
        elif act == "anchor_repaired":
            warnings.append("{}: quote is on {}, not {} (anchor will be repaired)".format(
                label, entry.get("to"), entry.get("from")))
            result["repairs"].append(entry)
        elif act == "evidence_dropped":
            if not any(e.get("action") in ("finding_dropped", "strength_dropped") for e in siblings):
                warnings.append("{}: evidence {} dropped ({})".format(label, entry.get("anchor", "?"),
                                                                     entry.get("reason")))
        elif act == "severity_capped":
            warnings.append("{}: severity lowered to minor ({})".format(label, entry.get("reason")))


STUDENT_TEXT_ID_RE = re.compile(r"(?<![\w/.-])(A:[A-Z]+-[0-9]{3}b?|[RJ][0-9]+)(?![\w/-])")


def _check_student_text(raw, warnings):
    """Students read titles, details, fixes, questions and the one-line take; ids there are noise. A
    warning (synthesis replaces leftovers with a short quote), not an error, so no retry is spent."""
    def check(where, text):
        m = STUDENT_TEXT_ID_RE.search(text) if isinstance(text, str) else None
        if m:
            warnings.append("{}: write a few quoted words instead of the id {} (students read this text)".format(
                where, m.group(1)))

    check("one_line_take", raw.get("one_line_take"))
    for f in as_list(raw.get("findings")):
        if not isinstance(f, dict):
            continue
        label = "finding {}".format(clean_str(f.get("id"), 40))
        for key in ("title", "detail"):
            check("{} {}".format(label, key), f.get(key))
        fx = f.get("fix") if isinstance(f.get("fix"), dict) else {}
        for key in ("suggestion", "candidate_question"):
            check("{} {}".format(label, key), fx.get(key))
    for i, q in enumerate(as_list(raw.get("questions_for_candidate"))):
        if isinstance(q, dict):
            check("questions_for_candidate[{}]".format(i), q.get("question"))


def _check_lens_extras(rid, raw, ctx, paths, warnings):
    lens = raw.get("lens_data") if isinstance(raw.get("lens_data"), dict) else {}
    if rid == "screening":
        brief, err = load_json_file(paths["brief"])
        if err:
            warnings.append("brief.json not available ({}); keyword table not compared".format(err))
            return
        rows = _brief_keywords(brief)
        for row in as_list(lens.get("keyword_table")):
            if not isinstance(row, dict) or not isinstance(row.get("term"), str):
                continue
            b = rows.get(match_norm(row["term"]))
            if b is None:
                warnings.append("keyword_table: {!r} is not in brief.json; list only the brief's terms".format(
                    row["term"][:40]))
                continue
            for k in ("found", "match_type", "evidence_level", "importance"):
                if k in b and k in row and b[k] != row[k]:
                    warnings.append("keyword_table: {!r} {} is {!r} in brief.json; copy it, do not "
                                    "recompute".format(row["term"][:40], k, b[k]))
    elif rid == "skeptic":
        for i, c in enumerate(as_list(lens.get("claim_audit"))):
            if not isinstance(c, dict):
                continue
            entry = ctx.by_id.get(c.get("anchor")) if isinstance(c.get("anchor"), str) else None
            qn = match_norm(c.get("quote") if isinstance(c.get("quote"), str) else "")
            if entry is None or not quote_in_line(qn, entry[2]):
                warnings.append("claim_audit[{}]: quote not found on {}".format(i, c.get("anchor")))


def validate_review(run_dir, review_path):
    """Contract API: (ok, errors). See check_review for warnings and repairs."""
    res = check_review(run_dir, review_path)
    return res["ok"], res["errors"]
