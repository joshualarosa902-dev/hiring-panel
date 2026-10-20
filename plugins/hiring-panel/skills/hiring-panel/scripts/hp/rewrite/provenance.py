"""Provenance gate: the Skeptic's audit of the rewrite must cover every flagged bullet and be applied.

    from hp.rewrite.provenance import check_provenance
    gate = check_provenance(resume, provenance, truth)
    # -> {"passed": bool, "unresolved": [bullet ids], "missing": [bullet ids], "errors": [str]}

provenance.json (written by a fresh Skeptic subagent in Claude Code, or by Claude itself, mode "self"):
    {"schema_version": "1.0", "auditor": "skeptic-provenance", "mode": "subagent|self",
     "items": [{"bullet_id", "audited_text", "verdict": "ok|soften|remove", "problem", "suggested_text"}]}

Rules
  * missing:    every bullet that truth.json flags with NEW_WORDING needs an audit item. An "ok" item
                whose audited_text no longer matches the bullet is stale (the bullet changed after the
                audit), so that bullet counts as missing until it is audited again.
  * unresolved: every "soften" or "remove" item must now differ from its audited_text, or the bullet
                must be gone from resume.json.
  * errors:     (deviation from the 3-key contract, additive) plain reasons when an input is unusable.
The gate passes only when all three lists are empty. Never raises.
"""
import re

from .. import util

PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")


def _s(x):
    return x if isinstance(x, str) else ("" if x is None else str(x))


def _same(a, b):
    return util.norm_for_match(_s(a)) == util.norm_for_match(_s(b))


def _bullet_texts(resume):
    """bullet id -> set of texts it can render as (raw, textIfUnknown, placeholders filled)."""
    out = {}
    placeholders = resume.get("placeholders") if isinstance(resume.get("placeholders"), dict) else {}

    def add(bid, item, key="text"):
        raw = _s(item.get(key))
        variants = {raw}
        if item.get("textIfUnknown"):
            variants.add(_s(item.get("textIfUnknown")))
        filled = raw
        for pid in PLACEHOLDER_RE.findall(raw):
            ph = placeholders.get(pid) if isinstance(placeholders.get(pid), dict) else {}
            if ph.get("value"):
                filled = re.sub(r"\{\{\s*%s\s*\}\}" % re.escape(pid), lambda _m, v=_s(ph["value"]): v, filled)
        variants.add(filled)
        out[bid] = {v for v in variants if v}

    sections = resume.get("sections") if isinstance(resume.get("sections"), list) else []
    for si, sec in enumerate(sections):
        if not isinstance(sec, dict):
            continue
        sid = _s(sec.get("id")) or _s(sec.get("type")) or "section%d" % (si + 1)
        if _s(sec.get("text")).strip():
            add(sid, sec)
        if _s(sec.get("title")).strip():
            out[sid + ".title"] = {_s(sec.get("title"))}   # truth flags new title words (non-English) too
        for it in sec.get("items") if isinstance(sec.get("items"), list) else []:
            if not isinstance(it, dict):
                continue
            eid = _s(it.get("id")) or sid
            for bi, b in enumerate(it.get("bullets") if isinstance(it.get("bullets"), list) else []):
                if isinstance(b, str):
                    b = {"text": b}
                if isinstance(b, dict):
                    add(_s(b.get("id")) or "%s.b%d" % (eid, bi + 1), b)
    basics = resume.get("basics") if isinstance(resume.get("basics"), dict) else {}
    if _s(basics.get("headline")).strip():
        out["basics.headline"] = {_s(basics["headline"])}
    return out


def check_provenance(resume, provenance, truth):
    try:
        return _check(resume, provenance, truth)
    except (TypeError, ValueError, AttributeError, KeyError, IndexError) as e:
        return {"passed": False, "unresolved": [], "missing": [],
                "errors": ["could not read the inputs (%s)" % e.__class__.__name__]}


def _check(resume, provenance, truth):
    result = {"passed": False, "unresolved": [], "missing": [], "errors": []}
    if not isinstance(resume, dict):
        result["errors"].append("resume.json is not readable")
        return result
    if not isinstance(truth, dict) or not isinstance(truth.get("warnings"), list):
        result["errors"].append("truth.json is missing or unreadable; run the truth check first")
        return result
    if truth.get("passed") is not True:
        result["errors"].append("the truth check has not passed; fix its errors before the provenance audit")
    flagged = []
    for w in truth.get("warnings") or []:
        if isinstance(w, dict) and w.get("code") == "NEW_WORDING" and _s(w.get("bullet_id")) not in flagged:
            flagged.append(_s(w.get("bullet_id")))
    texts = _bullet_texts(resume)
    items = []
    if isinstance(provenance, dict) and isinstance(provenance.get("items"), list):
        items = [i for i in provenance["items"] if isinstance(i, dict)]
    elif flagged:
        result["errors"].append("provenance.json is missing or has no items list")
    by_id = {}
    for it in items:
        by_id.setdefault(_s(it.get("bullet_id")), []).append(it)

    for bid in flagged:
        current = texts.get(bid)
        if current is None:
            continue   # the bullet was removed after the truth check; nothing left to audit
        audits = by_id.get(bid) or []
        if not audits:
            result["missing"].append(bid)
            continue
        covered = False
        for it in audits:
            verdict = _s(it.get("verdict")).lower()
            if verdict in ("soften", "remove"):
                covered = True   # judged below
            elif verdict == "ok" and any(_same(it.get("audited_text"), t) for t in current):
                covered = True
        if not covered:
            result["missing"].append(bid)   # only stale "ok" verdicts: the bullet changed after the audit

    for it in items:
        verdict = _s(it.get("verdict")).lower()
        bid = _s(it.get("bullet_id"))
        if verdict not in ("ok", "soften", "remove"):
            result["errors"].append("item %s has an unknown verdict '%s'" % (bid or "?", verdict))
            if bid and bid not in result["unresolved"]:
                result["unresolved"].append(bid)
            continue
        if verdict == "ok":
            continue
        current = texts.get(bid)
        if current is None:
            continue   # removed: resolved
        if any(_same(it.get("audited_text"), t) for t in current) and bid not in result["unresolved"]:
            result["unresolved"].append(bid)

    result["passed"] = not (result["missing"] or result["unresolved"] or result["errors"])
    return result
