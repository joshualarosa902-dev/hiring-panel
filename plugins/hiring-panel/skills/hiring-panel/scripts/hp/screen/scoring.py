"""Scoring rubric (ATS spec 14): Parse Safety, Keyword Match, Content Signals and Overall.

Every score is round5 (nearest multiple of 5, halves up, clamped 0-100). Penalties tied to an issue are
multiplied by its confidence (high 1.0, medium 0.7, low 0.4), and each issue id counts once.
"""
from ..util import round5
from .constants import (CATEGORY_ORDER, CONFIDENCE_MULT, CS_BANDS, CS_FEW_BULLETS_CAP, GATE_BAND, KM_BANDS,
                        KM_COVERAGE_FLOOR, KM_WEIGHTS, MIN_BULLETS_TO_JUDGE, OVERALL_LOW_COVERAGE_CAP,
                        OVERALL_LOW_COVERAGE_NOTE,
                        KM_WEIGHTS_SIMPLE, OVERALL_BANDS, OVERALL_GATE_CAP, OVERALL_WEIGHTS,
                        OVERALL_WEIGHTS_NO_KM, PS_BANDS, PS_CRITICAL_CAP, PS_EXTRA_IDS, PS_FAIL_BAND,
                        PS_ONLY_BAND, PS_POINTS, SEVERITY_RANK, TARGET_ACTION_SHARE, TARGET_QUANT_SHARE)


def band(value, bands):
    if value is None:
        return None
    for floor, name in bands:
        if value >= floor:
            return name
    return bands[-1][1]


def counts_for_ps(iid):
    return iid.startswith("PARSE-") or iid in PS_EXTRA_IDS


def parse_penalties(issues):
    """{issue id: penalty points} for Parse Safety."""
    out = {}
    for it in issues:
        if counts_for_ps(it["id"]):
            out[it["id"]] = PS_POINTS[it["severity"]] * CONFIDENCE_MULT[it["confidence"]]
    return out


def content_deductions(issues, bm, counts):
    """{issue id or pseudo id: deduction points} for Content Signals. The action-verb share has no
    issue of its own, so it is reported under the pseudo id "action_verbs"."""
    by_id = {it["id"]: it for it in issues}

    def mult(iid):
        return CONFIDENCE_MULT[by_id[iid]["confidence"]] if iid in by_id else 0.0
    out = {}
    n = bm.get("count") or 0
    if n:
        q = bm["quantified_ratio"] or 0.0
        a = bm["action_verb_ratio"] or 0.0
        d = min(20.0, 20.0 * max(0.0, TARGET_QUANT_SHARE - q) / TARGET_QUANT_SHARE)
        if d and "CONTENT-001" in by_id:
            out["CONTENT-001"] = d * mult("CONTENT-001")
        d = min(15.0, 15.0 * max(0.0, TARGET_ACTION_SHARE - a) / TARGET_ACTION_SHARE)
        if d:
            out["action_verbs"] = d
        share_long = bm["too_long"] / float(n)
        d = min(10.0, 10.0 * share_long / 0.20)
        if d and "CONTENT-003" in by_id:
            out["CONTENT-003"] = d * mult("CONTENT-003")
    if "CONTENT-002" in by_id:
        out["CONTENT-002"] = min(12.0, 3.0 * counts.get("CONTENT-002", 1)) * mult("CONTENT-002")
    if "CONTENT-005" in by_id:
        out["CONTENT-005"] = min(6.0, 2.0 * counts.get("CONTENT-005", 1)) * mult("CONTENT-005")
    if "DATE-001" in by_id:
        out["DATE-001"] = min(15.0, 5.0 * counts.get("DATE-001", 1)) * mult("DATE-001")
    for iid, pts in (("DATE-004", 5.0), ("DATE-005", 10.0), ("DATE-006", 5.0), ("DATE-007", 3.0),
                     ("CONTACT-001", 15.0), ("CONTACT-002", 5.0)):
        if iid in by_id:
            out[iid] = pts * mult(iid)
    sect = [(iid, 10.0 * mult(iid)) for iid in ("SECT-001", "SECT-002") if iid in by_id]
    room = 20.0
    for iid, pts in sect:
        take = min(pts, room)
        out[iid] = take
        room -= take
    return out


def _top(impacts, k=3):
    items = [(v, iid) for iid, v in impacts.items() if v > 0 and not iid.startswith("action")]
    items.sort(key=lambda x: (-round(x[0], 6), x[1]))
    return [iid for _v, iid in items[:k]]


def score_all(issues, bm, counts, km, flags):
    """Compute the four scores and fill each issue's score_impact. Returns the scores dict.

    km: dict(value_raw or None, band_null, explanation, impacts{id: points}).
    flags: dict(has_text, english).
    """
    ps_pen = parse_penalties(issues)
    ps_raw = 100.0 - sum(ps_pen.values())
    if any(it["severity"] == "critical" for it in issues if it["id"] in ps_pen):
        ps_raw = min(ps_raw, PS_CRITICAL_CAP)
    ps = round5(max(0.0, ps_raw))
    ps_band = band(ps, PS_BANDS)
    if not flags["has_text"]:
        ps_band += " (text not checked)"

    cs_ded = {}
    if flags["has_text"] and flags["english"]:
        cs_ded = content_deductions(issues, bm, counts)
        cs = round5(max(0.0, 100.0 - sum(cs_ded.values())))
        if (bm.get("count") or 0) < MIN_BULLETS_TO_JUDGE:
            # Too little writing to call it polished: a 3-bullet resume never scores "Polished".
            cs = min(cs, CS_FEW_BULLETS_CAP)
        cs_band = band(cs, CS_BANDS)
    else:
        cs = None
        cs_band = flags["cs_null_band"]

    km_value = None if km["value_raw"] is None else round5(km["value_raw"])
    km_band = band(km_value, KM_BANDS) if km_value is not None else km["band_null"]

    if km_value is not None:
        w = OVERALL_WEIGHTS
        overall_raw = w["parse_safety"] * ps + w["keyword_match"] * km_value + w["content_signals"] * (cs or 0)
    elif cs is not None:
        w = OVERALL_WEIGHTS_NO_KM
        overall_raw = w["parse_safety"] * ps + w["content_signals"] * cs
    else:
        w = {"parse_safety": 1.0, "keyword_match": 0.0, "content_signals": 0.0}
        overall_raw = float(ps)
    overall = round5(overall_raw)
    explanation = flags["overall_method"]
    found, total = km.get("basis_found"), km.get("basis_total")
    if km_value is not None and total and total >= 2 and found < KM_COVERAGE_FLOOR * total \
            and overall > OVERALL_LOW_COVERAGE_CAP:
        overall = OVERALL_LOW_COVERAGE_CAP
        explanation += OVERALL_LOW_COVERAGE_NOTE
    gated = ps_band.startswith(PS_FAIL_BAND)
    if gated:
        overall = min(overall, OVERALL_GATE_CAP)
        overall_band = GATE_BAND
    elif km_value is None and cs is None:
        # Only file readability could be checked (non-English text): say so instead of a
        # "Ready to send" style band that would claim more than was checked.
        overall_band = PS_ONLY_BAND.replace("{band}", ps_band)
    else:
        overall_band = band(overall, OVERALL_BANDS)

    # per-issue impact on each score, for ranking and drivers
    overall_imp = {}
    for it in issues:
        iid = it["id"]
        p = ps_pen.get(iid, 0.0)
        c = cs_ded.get(iid, 0.0)
        k = km["impacts"].get(iid, 0.0)
        o = w["parse_safety"] * p + w["content_signals"] * c + w["keyword_match"] * k
        it["score_impact"] = {"parse_safety": round(p, 2), "keyword_match": round(k, 2),
                              "content_signals": round(c, 2), "overall": round(o, 2)}
        overall_imp[iid] = o
    scores = {
        "overall": {"value": overall, "band": overall_band, "explanation": explanation,
                    "drivers": _top(overall_imp)},
        "parse_safety": {"value": ps, "band": ps_band, "explanation": _ps_explanation(ps_pen),
                         "drivers": _top(ps_pen)},
        "keyword_match": {"value": km_value, "band": km_band, "explanation": km["explanation"],
                          "drivers": _top(km["impacts"])},
        "content_signals": {"value": cs, "band": cs_band,
                            "explanation": _cs_explanation(bm, cs_ded, flags), "drivers": _top(cs_ded)},
    }
    return scores


def _ps_explanation(ps_pen):
    n = sum(1 for v in ps_pen.values() if v > 0)
    return ("Starts at 100 and loses points for each file-readability risk (critical 45, high 15, "
            "medium 7, low 2), scaled by how sure the check is. Any critical risk caps it at 40. "
            "Risks counted: %d." % n)


def _cs_explanation(bm, cs_ded, flags):
    if not (flags["has_text"] and flags["english"]):
        return "Not checked for this file."
    n = bm.get("count") or 0
    cap = ("There is too little bullet text to judge the writing (fewer than %d bullets), so this score "
           "is capped at %d (Needs work)." % (MIN_BULLETS_TO_JUDGE, CS_FEW_BULLETS_CAP))
    if not n:
        return ("No experience or project bullets were found, so only dates, sections and contact "
                "details were checked. " + cap)
    out = ("%d%% of %d bullets show a number (target 35%% or more). %d%% start with an action verb "
           "(target 70%% or more). Points also come off for weak openers, long bullets, missing dates, "
           "missing sections and missing contact details." % (
               int(round((bm["quantified_ratio"] or 0) * 100)), n,
               int(round((bm["action_verb_ratio"] or 0) * 100))))
    if n < MIN_BULLETS_TO_JUDGE:
        out += " " + cap
    return out


def rank_issues(issues):
    """Biggest weaknesses first: severity, then points removed from Overall, then category, then id."""
    cat = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    issues.sort(key=lambda it: (SEVERITY_RANK[it["severity"]], -round(it["score_impact"].get("overall", 0.0), 6),
                                cat.get(it["category"], 99), it["id"]))
    for i, it in enumerate(issues, 1):
        it["rank"] = i
    return issues


def keyword_score(terms):
    """KM per ATS spec 14B from matched terms. Returns dict with value_raw, R, P, E, basis and sets."""
    req = [t for t in terms if t["importance"] == "required"]
    pref = [t for t in terms if t["importance"] in ("preferred", "responsibility")]
    other = [t for t in terms if t["importance"] == "unspecified"]
    if not req:
        basis, rset, pset = "all_terms", req + pref + other, []
    elif not pref:
        basis, rset, pset = "required_only", req, []
    else:
        basis, rset, pset = "required_preferred", req, pref

    def ratio(ts):
        tw = sum(t["weight"] for t in ts)
        return (sum(t["credit"] * t["weight"] for t in ts) / tw) if tw else 0.0
    R = ratio(rset)
    P = ratio(pset) if pset else None
    matched = [t for t in rset + pset if t["found"]]
    mw = sum(t["weight"] for t in matched)
    E = (sum(t["weight"] for t in matched if t["evidence_level"] == "demonstrated") / mw) if mw else 0.0
    if basis == "required_preferred":
        value = 100.0 * (KM_WEIGHTS["required"] * R + KM_WEIGHTS["preferred"] * P + KM_WEIGHTS["evidence"] * E)
        w_r, w_p, w_e = KM_WEIGHTS["required"], KM_WEIGHTS["preferred"], KM_WEIGHTS["evidence"]
    else:
        value = 100.0 * (KM_WEIGHTS_SIMPLE["required"] * R + KM_WEIGHTS_SIMPLE["evidence"] * E)
        w_r, w_p, w_e = KM_WEIGHTS_SIMPLE["required"], 0.0, KM_WEIGHTS_SIMPLE["evidence"]
    impacts = {"KW-001": 100.0 * w_r * (1.0 - R), "KW-002": 100.0 * w_e * (1.0 - E) if matched else 0.0}
    if P is not None:
        impacts["KW-005"] = 100.0 * w_p * (1.0 - P)
    return {"value_raw": value, "R": R, "P": P, "E": E, "basis": basis, "basis_terms": rset,
            "pref_terms": pset, "other_terms": [t for t in terms if t not in rset and t not in pset],
            "impacts": impacts}
