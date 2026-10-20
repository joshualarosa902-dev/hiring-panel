"""Hiring Panel synthesis: the ONLY ranker (ARCHITECTURE.md section 9).

    from hp.panel.synth import validate_review, synthesize
    ok, errors = validate_review(run_dir, review_path)
    result = synthesize(run_dir, mode="parallel|sequential|lite", merges_path=None)  # writes work/synthesis.json

Pipeline:
 1. Load the ledger (required), screening.json (optional) and the 7 reviews. A missing, unreadable or
    unusable review shrinks the panel; it never stops the run.
 2. Check every quote against its numbered line (repair the anchor when the quote sits on another
    line, drop it otherwise), overrule false "missing keyword" claims, enforce lenses.
 3. Read screening issues at medium or above in automatically as screening-lens findings (A: anchors,
    the script's confidence); info items become unranked notes. PARSE-016 (hidden text) is pinned.
 4. Merge duplicates (shared A: anchor; shared line within a line family; shared J line for
    requirements; one family-level group for document-wide problems; optional merges.json), roll up
    repeated line problems into one pattern issue, then score:
        priority = SEV x CONS x STAGE x CONF x REQ, CONS = 1 + lambda(n - 1)
    with lambda 0.5 in parallel mode and 0.3 in sequential and lite modes (agreement inside one
    conversation is partly correlated, so it earns less).
 5. Emit the fixed output keys: vote (advance yes / unsure / no counts), the reviewer closest to
    rejecting the resume (lowest verdict, ties in report order, with its top-ranked issue), issues ranked
    I1.., top3, pinned integrity issues, conflicts, strengths, questions for the candidate, interview
    prep, validation log.

Student-facing text rules applied here:
- An issue's title, detail and fixes[0] come from the same finding (the highest-priority one), so the
  first fix always answers the title. Every issue says whether any contributing finding is a real gap
  (`has_real_gap`) and lists those findings' honest routes (`real_gap_routes`), whatever its lane.
- Reviewers are told never to write R#, J# or A: ids in text a student reads; any that slip through are
  replaced by a short quote of the line (or the screening issue's title), or removed when they are only
  a citation in parentheses.
- Automatic screening questions read naturally: certifications ask "Do you hold X? What does the card
  say?", degree-field alternatives and skills already shown in work lines are never asked about, and
  the posting's own wording is used. Interview prep drops near-duplicates and bare questions.

Issue ids (I1, I2, ...) are assigned AFTER merges and rollups, in rank order. Running synthesize again
with --merges renumbers them, so the rewrite (meta.addressed) must use the ids in the FINAL
synthesis.json, never ids remembered from an earlier run.

All weights are documented design heuristics, not research findings. Output is deterministic: the same
inputs give byte-identical synthesis.json.
"""
import json
import os
import re

from hp.util import mask_contact, write_json
from hp.panel.common import (CATEGORY_ORDER, CATS, CONFIDENCES, FIX_ORDER, GATEKEEPERS, MAX_REVIEW_BYTES,
                             REPORT_ORDER, REVIEWER_INFO, SCHEMA_VERSION, SEVERITIES, STAGE_ORDER,
                             VERDICTS, PanelError, SourceContext, anchor_num, check_evidence,
                             clean_str, load_json_file, load_ledger, load_screening, match_norm,
                             run_paths, term_in_text)
from hp.panel.ledger import split_sentences
from hp.panel.review_check import check_review, prepare_review, validate_review  # noqa: F401 (re-export)

MODES = ("parallel", "sequential", "lite")
LAMBDA = {"parallel": 0.5, "sequential": 0.3, "lite": 0.3}
SEV_W = {"critical": 8.0, "major": 4.0, "moderate": 2.0, "minor": 1.0}
CONF_W = {"high": 1.0, "medium": 0.85, "low": 0.65}
STAGE_W = {"ats": 1.5, "recruiter_skim": 1.4, "hm_review": 1.25, "interview": 1.0}
REQ_W = {"must": 1.25, "nice": 1.1}
MAX_CONSENSUS_N = 5.0

ROLLUP_FAMILIES = ("IMPACT", "MECHANICS", "SKILL_EVIDENCE", "CONTRIBUTION")
PATTERN_TITLES = {
    "IMPACT": "Bullets describe duties, not results",
    "MECHANICS": "Writing slips repeat across the page",
    "SKILL_EVIDENCE": "Skills are listed but not shown in your work",
    "CONTRIBUTION": "Your own part is unclear in several lines",
}
INTEGRITY_FAMILIES = ("CREDIBILITY", "CONSISTENCY")
# Only issues that dispute the quality or credibility of a line can contradict praise of that line
# ("great but buried" agrees with the praise, so ORDER is not a conflict).
CONFLICT_FAMILIES = ("IMPACT", "CREDIBILITY", "CONSISTENCY", "CONTRIBUTION", "NOISE", "SKILL_EVIDENCE")

SCREEN_SEV = {"critical": "critical", "high": "major", "medium": "moderate", "low": "minor"}
AUTO_LEVELS = ("critical", "high", "medium")
PINNED_SCRIPT_IDS = ("PARSE-016",)

MAX_ISSUE_EVIDENCE = 6
MAX_ISSUE_FIXES = 6
MAX_QUESTIONS = 6
MAX_PREP = 6
MAX_STRENGTHS = 8
MAX_CONFLICTS = 8

WHICH_MATTERS = {
    "ats": "This is decided before a person reads the resume, so the screening view matters first.",
    "recruiter_skim": "At the first skim the Recruiter decides; fix it so the skim does not end early.",
    "hm_review": "Before the interview, the Hiring Manager's view carries the most weight here.",
    "interview": "Praise can get you the interview; in the interview the Skeptic's and Hiring "
                 "Manager's questions decide. Keep the line only if you can back it up.",
}


# ============================================================================= helpers
def _report_idx(rid):
    return REPORT_ORDER.index(rid) if rid in REPORT_ORDER else len(REPORT_ORDER)


def _sev_idx(sev):
    return SEVERITIES.index(sev)


class _DSU(object):
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # keep the smaller index as the root so grouping never depends on call order
            if ra < rb:
                self.p[rb] = ra
            else:
                self.p[ra] = rb


def _anchors(f, prefix):
    return sorted({e["anchor"] for e in f["evidence"] if e["anchor"].startswith(prefix)}, key=_anchor_key)


def _anchor_key(a):
    if a.startswith("A:"):
        return (2, 0, a)
    return (0 if a.startswith("R") else 1, anchor_num(a), a)


# ============================================================================= automatic findings
def _auto_category(iid):
    prefix, _, rest = iid.partition("-")
    num = rest[:3]
    if prefix == "PARSE":
        return "PARSE_FORMAT"
    if prefix == "CONTACT":
        return "CONTACT_HEADER"
    if prefix == "KW":
        return {"002": "SKILL_UNSUPPORTED", "004": "TITLE_MISMATCH"}.get(num, "KEYWORD_GAP")
    if prefix == "SECT":
        return "EDUCATION_PRESENTATION" if num == "001" else "LAYOUT_SKIM"
    if prefix == "DATE":
        return "TRAJECTORY_GAP" if num in ("001", "005", "006", "008") else "LAYOUT_SKIM"
    if prefix == "CONTENT":
        return {"001": "METRIC_MISSING", "002": "VAGUE_LANGUAGE", "003": "LENGTH_DENSITY",
                "004": "LENGTH_DENSITY", "009": "LENGTH_DENSITY"}.get(num, "TYPO_GRAMMAR")
    if prefix == "KO":
        return "KNOCKOUT_RISK"
    return None


_AUTO_FIX = {
    "PARSE-016": "remove", "PARSE-019": "remove", "PARSE-020": "remove",
    "CONTACT-001": "needs_candidate_input", "CONTACT-002": "needs_candidate_input",
    "CONTACT-003": "needs_candidate_input",
    "KW-001": "needs_candidate_input", "KW-002": "needs_candidate_input",
    "KW-003": "add_keyword_truthfully", "KW-004": "rewrite", "KW-005": "needs_candidate_input",
    "SECT-001": "needs_candidate_input", "SECT-002": "needs_candidate_input", "SECT-006": "remove",
    "DATE-001": "needs_candidate_input", "DATE-002": "needs_candidate_input",
    "DATE-005": "needs_candidate_input", "DATE-006": "needs_candidate_input", "DATE-007": "reorder",
    "CONTENT-001": "needs_candidate_input",
}
_AUTO_FIX_PREFIX = {"PARSE": "reformat", "CONTACT": "reformat", "SECT": "reformat", "DATE": "reformat",
                    "CONTENT": "rewrite", "KW": "rewrite", "KO": "needs_candidate_input"}
_AUTO_QUESTION = {
    "CONTENT-001": "Which bullets can you add a true number to (people, hours, items, how often)? "
                   "A range or 'not sure' is fine.",
    "CONTACT-001": "What email address should employers use to reach you?",
    "CONTACT-002": "Do you want a phone number on your resume? If yes, which one?",
    "CONTACT-003": "Which city (and state or country) should your resume show?",
    "DATE-001": "What are the start and end months for each entry that has no dates?",
    "DATE-002": "Do you know the start and end months for the year-only dates? 'Not sure' is fine.",
    "DATE-005": "Can you confirm the start and end dates that look out of order?",
    "DATE-006": "Is the future end date an expected date (for example, graduation)?",
    "SECT-001": "Where do you study, what degree, and when do you expect to finish?",
    "SECT-002": "Which jobs, projects, clubs or volunteer work could go on your resume?",
}
KW_QUESTION_IDS = ("KW-001", "KW-002", "KW-005")
WORK_SECTIONS = ("experience", "projects", "leadership")

# Term classes for natural keyword questions.
# "a bachelor's degree in statistics, economics or a related field": the span after "degree in" up to the
# end of the clause lists fields of study (alternatives), not skills to ask about.
_DEGREE_FIELDS = re.compile(r"(?i)\b(?:degree|major|majoring|bachelor'?s?|master'?s?|ph\.?\s?d|diploma|studies|"
                            r"field of study|concentration)\b(?:\s*\([^)]*\))?\s+(?:in|of)\s+"
                            r"(.+?)(?=[.;]|\s+(?:and|with|plus)\s+(?:\w+\s+){0,2}?(?:experience|skills?|knowledge)\b|$)")
_EDU_TERM = re.compile(r"(?i)(\b(diploma|ged|hiset|degree|bachelor'?s?|master'?s?|associate'?s?|ph\.?\s?d|mba|"
                       r"high school|a-levels?)\b|\bb\.\s?[as]\.|\bm\.\s?[as]\.)")
_LANG_TERM = re.compile(r"(?i)\b(bilingual|multilingual|trilingual|fluen(t|cy)|spanish|french|german|mandarin|"
                        r"chinese|cantonese|japanese|korean|arabic|hindi|urdu|bengali|punjabi|portuguese|"
                        r"italian|russian|vietnamese|tagalog|polish|somali|swahili|asl|sign language)\b")
_CERT_TERM = re.compile(r"(?i)\b(certif\w*|licen[cs]\w*|licensure)\b")
_EDU_LINE = re.compile(r"(?i)\b(universit(y|ies)|college|institute of|school of|bachelor'?s?|master'?s?|"
                       r"associate'?s? degree|ph\.?\s?d|mba|b\.\s?[as]\.|diploma|gpa|graduat(e|ing|ion)|"
                       r"pre-?(nursing|med|law))\b")
_VOWEL_SOUND_LETTERS = "AEFHILMNORSX"


_QUOTED_RE = re.compile(r'"([^"]{1,80})"')


def _kw_terms(ctx, iid):
    """The screening keyword rows a KW issue is about.

    The screening script names its terms inside the issue's evidence strings ('Not found: "SQL"',
    '"Tableau" appears only in your skills or other lists.', 'Posting says "X"; you wrote "Y".'), so
    those names come first (the first quoted name per evidence line is the posting's term). When the
    evidence names nothing, fall back to the keyword buckets: KW-001 missing required, KW-002 listed
    only, KW-003 matched through an alias or acronym, KW-005 missing preferred."""
    rows = ctx.keyword_rows
    by_name = {}
    for _, r in rows:
        for k in ("term", "canonical"):
            v = r.get(k)
            if isinstance(v, str) and v.strip():
                by_name.setdefault(match_norm(v), r)
    issue = ctx.issues.get(iid) or {}
    named = []
    for e in issue.get("evidence") if isinstance(issue.get("evidence"), list) else []:
        m = _QUOTED_RE.search(e) if isinstance(e, str) else None
        if m:
            row = by_name.get(match_norm(m.group(1)))
            if row is not None and row not in named:
                named.append(row)
    if named:
        return named
    num = iid[3:6]
    if num == "001":
        return [r for b, r in rows if b == "required" and r.get("found") is False]
    if num == "005":
        return [r for b, r in rows if b == "preferred" and r.get("found") is False]
    if num == "003":
        return [r for b, r in rows if r.get("found") is True and r.get("match_type") in ("alias", "acronym")]
    if num == "002":
        return [r for b, r in rows if r.get("found") is True and r.get("evidence_level") in ("listed", "claimed")]
    return []


def _term_name(row):
    for k in ("term", "canonical"):
        if isinstance(row.get(k), str) and row[k].strip():
            return clean_str(row[k], 60)
    return ""


def _jd_quote(row):
    return clean_str(row.get("jd_quote"), 400) if isinstance(row.get("jd_quote"), str) else ""


def _term_sentence(row):
    """The sentence of the posting quote that holds the term (the whole quote when none matches)."""
    quote = _jd_quote(row)
    names = [clean_str(row.get(k), 80) for k in ("term", "canonical", "resume_wording")
             if isinstance(row.get(k), str) and row.get(k).strip()]
    for piece in split_sentences(quote) if quote else []:
        pn = match_norm(piece)
        if any(term_in_text(n, piece, pn) for n in names):
            return piece
    return quote


def _posting_wording(row):
    """The term as the posting writes it: the first of term / canonical name / resume wording found in
    the posting quote, with the posting's own spelling and case; else the term."""
    quote = _jd_quote(row)
    for k in ("term", "canonical", "resume_wording"):
        v = row.get(k)
        if not isinstance(v, str) or not v.strip() or not quote:
            continue
        m = re.search(r"(?i)(?<![0-9A-Za-z])" + re.escape(v.strip()) + r"(?![0-9A-Za-z])", quote)
        if m:
            return clean_str(m.group(0), 60)
    return _term_name(row)


def _jd_evidence_for_terms(ctx, rows):
    """Attach J anchors by matching each term's jd_quote (else the quote's sentence that holds the term,
    else the term) to the ledger's JD lines."""
    out, seen = [], set()
    for row in rows:
        name = _term_name(row)
        hit = None
        for cand in (_jd_quote(row)[:200], _term_sentence(row)):
            qn = match_norm(cand)
            if hit is None and qn and len(qn) >= 3:
                for lid, text, ln in ctx.j_lines:
                    if qn in ln:
                        hit = (lid, cand)
                        break
        if hit is None and name:
            for lid, text, ln in ctx.j_lines:
                if term_in_text(name, text, ln):
                    hit = (lid, name)
                    break
        if hit and hit[0] not in seen:
            seen.add(hit[0])
            out.append({"anchor": hit[0], "quote": hit[1]})
    return out


def _shown_in_work(ctx, names):
    """True when a work, project or activity line (not a skills list) already contains one of the names."""
    for lid, text, ln in ctx.r_lines:
        if ctx.section.get(lid) in WORK_SECTIONS and any(term_in_text(n, text, ln) for n in names if n):
            return True
    return False


def _resume_has_education(ctx):
    return any(ctx.section.get(lid) == "education" or _EDU_LINE.search(text) for lid, text, _ in ctx.r_lines)


def _resume_has_work(ctx):
    return any(ctx.section.get(lid) in WORK_SECTIONS for lid, _, _ in ctx.r_lines)


def _term_class(row, display):
    """cert | edu | degree_field | language | soft | title | skill."""
    kind = row.get("kind") if isinstance(row.get("kind"), str) else ""
    if kind == "title":
        return "title"
    if kind == "cert" or _CERT_TERM.search(display):
        return "cert"
    if _EDU_TERM.search(display) or kind in ("education", "degree"):
        return "edu"
    if kind != "tool" and _is_degree_field(row, display):
        return "degree_field"
    if _LANG_TERM.search(display):
        return "language"
    if kind == "soft":
        return "soft"
    return "skill"


def _is_degree_field(row, display):
    """True when the term sits in the posting's list of degree fields ("degree in X, Y or a related field")."""
    names = [n for n in (display, _term_name(row)) if n]
    for m in _DEGREE_FIELDS.finditer(_term_sentence(row)):
        span = m.group(1)
        if any(term_in_text(n, span, match_norm(span)) for n in names):
            return True
    return False


def _article(phrase):
    first = phrase.split()[0] if phrase.split() else ""
    if len(first) > 1 and first[:2].isupper():          # an acronym: "an RN", "a BLS"
        return "an" if first[0] in _VOWEL_SOUND_LETTERS else "a"
    return "an" if first[:1].lower() in "aeiou" else "a"


def _or_list(items):
    items = [x for x in items if x]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " or " + items[-1]


def _lower_first(phrase):
    first = phrase.split()[0] if phrase.split() else ""
    if len(first) > 1 and first[:2].isupper():
        return phrase
    return phrase[:1].lower() + phrase[1:]


def keyword_question(ctx, iid, rows):
    """A natural question about the terms behind a KW-001 (missing required), KW-005 (missing preferred)
    or KW-002 (listed only) issue, or None when nothing is worth asking. Rules: the posting's own wording;
    certifications ask whether the student holds one and what the card says; education credentials are
    asked only when the resume shows no school; degree-field alternatives and job titles are never asked;
    languages ask how well; soft skills ask where they were shown; skills ask where (listed only) or
    whether (missing) they were used. A term a work, project or activity line already shows is skipped."""
    listed_only = iid == "KW-002"
    groups = {"cert": [], "edu": [], "skill": [], "language": [], "soft": []}
    seen = set()
    for row in rows:
        display = _posting_wording(row)
        if not display or match_norm(display) in seen:
            continue
        seen.add(match_norm(display))
        cls = _term_class(row, display)
        if cls in ("title", "degree_field"):
            continue
        names = [display, _term_name(row)]
        if cls in ("skill", "soft") and _shown_in_work(ctx, names):
            continue
        if listed_only and cls in ("cert", "language", "edu"):
            continue        # listing a certification, a language or a credential is the normal way to show it
        if cls == "edu" and _resume_has_education(ctx):
            continue
        groups[cls].append((display, row))
    parts = []
    for display, row in groups["cert"][:2]:
        phrase = display if re.search(r"(?i)certif|licen|card", display) else display + " certification"
        if re.search(r"(?i)\bcurrent\b", _term_sentence(row)) and not re.search(r"(?i)\bcurrent\b", phrase):
            phrase = "current " + phrase
        parts.append("Do you hold {} {}? What does the card say?".format(_article(phrase), phrase))
    if groups["edu"]:
        phrase = _or_list([_lower_first(d) for d, _ in groups["edu"][:3]])
        parts.append("Do you have {} {}?".format(_article(phrase), phrase))
    skills = [d for d, _ in groups["skill"][:6]]
    if skills:
        if listed_only:
            parts.append("Where have you used {}? A class, job, project or club counts.".format(_or_list(skills)))
        elif len(skills) == 1:
            parts.append("Have you used {} in a class, job, project or activity?".format(skills[0]))
        else:
            parts.append("Have you used any of these in a class, job, project or activity: {}? Answer yes, "
                         "some or no for each.".format(", ".join(skills)))
    for display, _ in groups["language"][:1]:
        if re.search(r"(?i)lingual", display):
            parts.append("Which languages do you speak, and how well?")
        else:
            parts.append("How well do you speak {}?".format(display))
    soft = [_lower_first(d) for d, _ in groups["soft"][:3]]
    if soft:
        parts.append("Where have you shown {}: a job, class, club or volunteering?".format(_or_list(soft)))
    return " ".join(parts[:3]) or None


def _auto_question(ctx, iid, rows):
    if iid in KW_QUESTION_IDS:
        return keyword_question(ctx, iid, rows)
    if iid == "SECT-001" and _resume_has_education(ctx):
        return None       # the school is on the page; the heading was not recognized
    if iid == "SECT-002" and _resume_has_work(ctx):
        return None
    return _AUTO_QUESTION.get(iid)


def auto_findings(ctx, log):
    """Screening issues at medium or above (plus PARSE-016 at any level) as screening-lens findings."""
    out = []
    for iid in ctx.issue_order:
        it = ctx.issues[iid]
        sev_in = it.get("severity")
        pinned = iid in PINNED_SCRIPT_IDS
        if sev_in not in AUTO_LEVELS and not pinned:
            continue
        cat = _auto_category(iid)
        if cat is None:
            cat = "LAYOUT_SKIM"
            log.append({"where": "A:" + iid, "action": "category_defaulted",
                        "reason": "unknown screening issue prefix; treated as LAYOUT_SKIM"})
        if ctx.general_review and cat in ("KEYWORD_GAP", "REQUIREMENT_UNPROVEN"):
            log.append({"where": "A:" + iid, "action": "finding_dropped",
                        "reason": "keyword issue in a general review"})
            continue
        sev = SCREEN_SEV.get(sev_in, "major" if pinned else "moderate") if isinstance(sev_in, str) \
            else ("major" if pinned else "moderate")
        ev_items = it.get("evidence") if isinstance(it.get("evidence"), list) else []
        first = next((clean_str(e, 160) for e in ev_items if isinstance(e, str) and e.strip()), "")
        evidence = [{"anchor": "A:" + iid, "quote": mask_contact(first) or clean_str(it.get("title"), 160)}]
        terms, rows = [], []
        if iid.startswith("KW-") and iid[3:6] in ("001", "002", "003", "005"):
            rows = _kw_terms(ctx, iid)
            terms = [t for t in (_term_name(r) for r in rows) if t]
            evidence.extend(_jd_evidence_for_terms(ctx, rows[:8]))
        q = _auto_question(ctx, iid, rows)
        prefix = iid.split("-")[0]
        fix_type = _AUTO_FIX.get(iid, _AUTO_FIX_PREFIX.get(prefix, "rewrite"))
        if iid == "KW-002" and not q:
            fix_type = "rewrite"       # nothing to ask: every listed term is already shown or is a credential
        family, stage, key = CATS[cat]
        out.append({
            "reviewer": "screening", "id": "A:" + iid, "auto": True, "category": cat, "family": family,
            "stage": stage, "merge_key": key, "severity": sev,
            "confidence": it.get("confidence") if it.get("confidence") in CONFIDENCES else "medium",
            "title": clean_str(it.get("title"), 90) or iid,
            "detail": clean_str(it.get("why_it_matters"), 420),
            "evidence": evidence, "searched_terms": terms,
            "fix": {"fix_type": fix_type, "suggestion": clean_str(it.get("fix"), 280), "candidate_question": q},
            "out_of_lens": False,
        })
    return out


def screening_notes(ctx):
    notes = []
    for iid in ctx.issue_order:
        it = ctx.issues[iid]
        if it.get("severity") == "info" and iid not in PINNED_SCRIPT_IDS:
            notes.append({"id": iid, "title": clean_str(it.get("title"), 90) or iid})
    return notes


# ============================================================================= grouping
def _group(flat, ctx, merge_pairs):
    """Union-find over findings. Rules (conservative; merges.json handles true semantic duplicates):
    a) findings citing the same A: anchor merge (any family);
    b) requirement findings merge on a shared J line (shared R line if neither cites a J line);
    c) line-family findings merge on a shared R line;
    d) a lone script finding in a line family absorbs reviewer findings of the same category;
    e) document-wide families: reviewer findings without A: anchors form one group, which joins the
       family's single A:-anchored group when there is exactly one;
    f) merges.json pairs.
    Two script findings are never merged directly by rules b to e."""
    n = len(flat)
    dsu = _DSU(n)
    a_sets = [set(_anchors(f, "A:")) for f in flat]
    r_sets = [set(_anchors(f, "R")) for f in flat]
    j_sets = [set(_anchors(f, "J")) for f in flat]
    # a) shared A: anchors
    by_a = {}
    for i in range(n):
        for a in sorted(a_sets[i]):
            by_a.setdefault(a, []).append(i)
    for a in sorted(by_a):
        idx = by_a[a]
        for k in idx[1:]:
            dsu.union(idx[0], k)
    # b) and c)
    for i in range(n):
        for j in range(i + 1, n):
            fi, fj = flat[i], flat[j]
            if fi["family"] != fj["family"] or (fi["auto"] and fj["auto"]):
                continue
            if fi["merge_key"] == "jd":
                if j_sets[i] or j_sets[j]:
                    if j_sets[i] & j_sets[j]:
                        dsu.union(i, j)
                elif r_sets[i] & r_sets[j]:
                    dsu.union(i, j)
            elif fi["merge_key"] == "line" and r_sets[i] & r_sets[j]:
                dsu.union(i, j)
    # d) lone script finding per line-family category
    autos_by_cat = {}
    for i, f in enumerate(flat):
        if f["auto"] and f["merge_key"] == "line":
            autos_by_cat.setdefault(f["category"], []).append(i)
    for cat in sorted(autos_by_cat):
        if len(autos_by_cat[cat]) != 1:
            continue
        a = autos_by_cat[cat][0]
        for i, f in enumerate(flat):
            if not f["auto"] and f["category"] == cat:
                dsu.union(a, i)
    # e) document-wide families
    fams = sorted({f["family"] for f in flat if f["merge_key"] == "doc"})
    for fam in fams:
        members = [i for i, f in enumerate(flat) if f["family"] == fam]
        plain = [i for i in members if not flat[i]["auto"] and not a_sets[i]]
        for k in plain[1:]:
            dsu.union(plain[0], k)
        a_groups = sorted({dsu.find(i) for i in members if a_sets[i]})
        if plain and len(a_groups) == 1:
            dsu.union(plain[0], a_groups[0])
    # f) merges.json
    for a, b in merge_pairs:
        dsu.union(a, b)
    groups = {}
    for i in range(n):
        groups.setdefault(dsu.find(i), []).append(i)
    return [groups[k] for k in sorted(groups)]


def _finding_sort_key(f):
    return (-_sev_idx(f["severity"]), not f["auto"], _report_idx(f["reviewer"]), f["_order"])


def _weights(fs):
    """A reviewer counts once per issue; a reviewer whose only contributions are out of lens counts half."""
    w = {}
    for f in fs:
        w[f["reviewer"]] = max(w.get(f["reviewer"], 0.0), 0.5 if f["out_of_lens"] else 1.0)
    return w


def _lane(fix_types):
    s = set(fix_types)
    writing = s & {"rewrite", "reorder", "reformat", "add_keyword_truthfully", "remove"}
    if "needs_candidate_input" in s or ("real_gap" in s and writing):
        return "needs_your_input"
    if "real_gap" in s:
        return "real_gap"
    return "fixed_by_rewrite"


def _priority(sev, weights, stage, conf_vals, req, mode):
    n = min(sum(weights.values()), MAX_CONSENSUS_N)
    cons = 1.0 + LAMBDA[mode] * max(n - 1.0, 0.0)
    conf = sum(conf_vals) / len(conf_vals) if conf_vals else CONF_W["medium"]
    return round(SEV_W[sev] * cons * STAGE_W[stage] * conf * req, 3)


def _make_issue(fs, ctx, mode):
    fs = sorted(fs, key=_finding_sort_key)
    lead = fs[0]
    sev_levels = [_sev_idx(f["severity"]) for f in fs]
    sev = SEVERITIES[max(sev_levels)]
    stage = min((f["stage"] for f in fs), key=STAGE_ORDER.index)
    weights = _weights(fs)
    j_anchors = sorted({a for f in fs for a in _anchors(f, "J")}, key=_anchor_key)
    kinds = {ctx.jd_kind.get(a) for a in j_anchors}
    req = REQ_W["must"] if "must" in kinds else REQ_W["nice"] if "nice" in kinds else 1.0
    conf_vals = [CONF_W[f["confidence"]] for f in fs]
    r_anchors = sorted({a for f in fs for a in _anchors(f, "R")}, key=_anchor_key)
    # One quote per anchor, taken from the most severe finding that cites it; listed in line order.
    evidence, seen = [], set()
    for f in fs:
        for e in f["evidence"]:
            if e["anchor"] not in seen:
                seen.add(e["anchor"])
                evidence.append({"anchor": e["anchor"], "quote": e["quote"], "reviewer": f["reviewer"]})
    evidence.sort(key=lambda e: _anchor_key(e["anchor"]))
    # fixes[0] is the lead finding's own fix (the finding that supplied the title and detail), so the
    # first fix a student reads answers the title; the other findings' fixes follow in fix order.
    fixes, fseen = [], set()
    rest = sorted(fs[1:], key=lambda x: (FIX_ORDER.index(x["fix"]["fix_type"]), _report_idx(x["reviewer"]),
                                          x["_order"]))
    for f in [lead] + rest:
        k = (f["fix"]["fix_type"], match_norm(f["fix"]["suggestion"]), match_norm(f["fix"]["candidate_question"] or ""))
        if k in fseen:
            continue
        fseen.add(k)
        fixes.append({"fix_type": f["fix"]["fix_type"], "suggestion": f["fix"]["suggestion"],
                      "candidate_question": f["fix"]["candidate_question"], "reviewer": f["reviewer"]})
    # Fixes with no words at all add nothing to the report; keep them only if nothing else is left.
    worded = [x for x in fixes if x["suggestion"] or x["candidate_question"]]
    fixes = worded or fixes[:1]
    fix_types = [f["fix"]["fix_type"] for f in fs]
    # Real gaps surface whatever the lane: every contributing real_gap fix and its honest route.
    routes, rseen = [], set()
    for f in fs:
        if f["fix"]["fix_type"] != "real_gap":
            continue
        route = f["fix"]["suggestion"] or f["fix"]["candidate_question"] or ""
        if route and match_norm(route) not in rseen:
            rseen.add(match_norm(route))
            routes.append(route)
    categories = sorted({f["category"] for f in fs}, key=CATEGORY_ORDER.index)
    first_line = anchor_num(r_anchors[0]) if r_anchors else (
        10 ** 6 + anchor_num(j_anchors[0]) if j_anchors else 2 * 10 ** 6)
    return {
        "_findings": fs, "title": lead["title"], "family": lead["family"], "categories": categories,
        "severity": sev, "_spread": max(sev_levels) - min(sev_levels), "stage": stage,
        "reviewers": sorted(weights, key=_report_idx), "_weights": weights,
        "priority": _priority(sev, weights, stage, conf_vals, req, mode), "_conf": conf_vals,
        "_req": req, "from_script": any(f["auto"] for f in fs), "lane": _lane(fix_types),
        "has_real_gap": "real_gap" in fix_types, "real_gap_routes": routes[:MAX_ISSUE_FIXES],
        "evidence": evidence[:MAX_ISSUE_EVIDENCE], "detail": lead["detail"], "fixes": fixes[:MAX_ISSUE_FIXES],
        "jd_anchors": j_anchors, "_r_anchors": r_anchors, "is_pattern": False, "instances": [],
        "_primary_fix": min(fix_types, key=FIX_ORDER.index), "_first_line": first_line,
    }


def _rollup(issues, ctx, mode):
    """Three or more separate issues in a line-level family become one pattern issue with instances."""
    out, by_fam = [], {}
    for it in issues:
        if it["family"] in ROLLUP_FAMILIES:
            by_fam.setdefault(it["family"], []).append(it)
        else:
            out.append(it)
    for fam in sorted(by_fam):
        its = by_fam[fam]
        if len(its) < 3:
            out.extend(its)
            continue
        its = sorted(its, key=lambda i: (i["_first_line"], i["title"]))
        fs = [f for i in its for f in i["_findings"]]
        pat = _make_issue(fs, ctx, mode)
        sev_i = max(_sev_idx(i["severity"]) for i in its)
        if len(its) >= 5 and sev_i < _sev_idx("major"):
            sev_i += 1    # a pattern across 5+ separate problems is worse than any one, capped at major
        sev = SEVERITIES[sev_i]
        lines = len(pat["_r_anchors"])
        pat.update({
            "title": PATTERN_TITLES[fam] + (" (pattern across {} lines)".format(lines) if lines >= 2 else ""),
            "family": fam, "severity": sev, "_spread": 0,
            "priority": _priority(sev, pat["_weights"], pat["stage"], pat["_conf"], pat["_req"], mode),
            "is_pattern": True,
            "evidence": _spread_evidence(its),
            "instances": [{"title": i["title"], "anchors": (i["_r_anchors"] + i["jd_anchors"]) or
                           [e["anchor"] for e in i["evidence"][:1]], "severity": i["severity"]} for i in its],
        })
        out.append(pat)
    return out


def _spread_evidence(its):
    """Pattern evidence: one quote per resume line across the instances, in line order, so the
    pattern shows its spread rather than one line repeated."""
    ev, seen = [], set()
    for i in its:
        for e in i["evidence"]:
            if e["anchor"] not in seen:
                seen.add(e["anchor"])
                ev.append(e)
    ev.sort(key=lambda e: _anchor_key(e["anchor"]))
    return ev[:MAX_ISSUE_EVIDENCE]


def _rank_key(it):
    return (-it["priority"], STAGE_ORDER.index(it["stage"]), -len(it["reviewers"]),
            FIX_ORDER.index(it["_primary_fix"]), it["_first_line"], match_norm(it["title"]),
            min((_report_idx(f["reviewer"]), f["_order"]) for f in it["_findings"]))


def _build_issues(flat, ctx, mode, merge_pairs):
    groups = _group(flat, ctx, merge_pairs)
    issues = [_make_issue([flat[i] for i in g], ctx, mode) for g in groups]
    issues = _rollup(issues, ctx, mode)
    issues.sort(key=_rank_key)
    for n, it in enumerate(issues, 1):
        it["id"] = "I{}".format(n)
        it["rank"] = n
    return issues


# ============================================================================= merges.json
def _merge_pairs(merges_path, flat, ctx, mode, log):
    """Read merges.json: a list of groups; each group lists finding refs {"reviewer", "id"} (script
    findings use reviewer "screening" and id "A:<ISSUE-ID>") and/or issue ids "I3" from the synthesis
    computed WITHOUT merges. Returns index pairs to union."""
    if not merges_path:
        return []
    data, err = load_json_file(merges_path, MAX_REVIEW_BYTES)
    if err:
        log.append({"where": "merges.json", "action": "merges_ignored", "reason": err})
        return []
    if isinstance(data, dict) and isinstance(data.get("merges"), list):
        data = data["merges"]
    if not isinstance(data, list):
        log.append({"where": "merges.json", "action": "merges_ignored", "reason": "expected a list of groups"})
        return []
    by_ref = {}
    for i, f in enumerate(flat):
        by_ref.setdefault((f["reviewer"], f["id"]), i)
    base = None
    pairs = []
    for g_index, group in enumerate(data[:50]):
        if not isinstance(group, list):
            log.append({"where": "merges.json[{}]".format(g_index), "action": "merge_ignored",
                        "reason": "group is not a list"})
            continue
        idx = []
        for ref in group[:20]:
            if isinstance(ref, str) and re.match(r"^I[0-9]+$", ref):
                if base is None:
                    base = {it["id"]: it for it in _build_issues(flat, ctx, mode, [])}
                it = base.get(ref)
                if it is None:
                    log.append({"where": "merges.json[{}]".format(g_index), "action": "merge_ref_unknown",
                                "ref": ref})
                    continue
                idx.extend(sorted(f["_index"] for f in it["_findings"]))
            elif isinstance(ref, dict) and isinstance(ref.get("reviewer"), str) and isinstance(ref.get("id"), str) \
                    and (ref.get("reviewer"), ref.get("id")) in by_ref:
                idx.append(by_ref[(ref.get("reviewer"), ref.get("id"))])
            else:
                log.append({"where": "merges.json[{}]".format(g_index), "action": "merge_ref_unknown",
                            "ref": clean_str(json.dumps(ref, ensure_ascii=False, sort_keys=True), 80)})
        idx = sorted(set(idx))
        if len(idx) >= 2:
            pairs.extend((idx[0], k) for k in idx[1:])
            log.append({"where": "merges.json[{}]".format(g_index), "action": "merged", "findings": len(idx)})
    return pairs


# ============================================================================= strengths, conflicts
def _strengths(reviews, ctx, log):
    items = []
    for rid in REPORT_ORDER:
        r = reviews.get(rid)
        if not r:
            continue
        for s in r["strengths"]:
            items.append(dict(s))
        if rid == "competitor":
            ua = r["lens_data"].get("unfair_advantages")
            for k, u in enumerate(ua[:4] if isinstance(ua, list) else []):
                if not isinstance(u, dict):
                    continue
                anchor = u.get("anchor")
                entry = ctx.by_id.get(anchor) if isinstance(anchor, str) and anchor.startswith("R") else None
                title = clean_str(u.get("why_it_stands_out"), 90)
                if entry is None or not title:
                    log.append({"where": "competitor:unfair_advantages[{}]".format(k),
                                "action": "strength_dropped", "reason": "unknown anchor or no text"})
                    continue
                items.append({"reviewer": "competitor", "id": "competitor-u{}".format(k + 1), "title": title,
                              "evidence": [{"anchor": anchor, "quote": clean_str(entry[1], 160)}],
                              "underused": u.get("currently_buried") is True})
    dsu = _DSU(len(items))
    anchor_sets = [{e["anchor"] for e in s["evidence"]} for s in items]
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if anchor_sets[i] & anchor_sets[j]:
                dsu.union(i, j)
    groups = {}
    for i in range(len(items)):
        groups.setdefault(dsu.find(i), []).append(items[i])
    out = []
    for key in sorted(groups):
        g = groups[key]
        revs = sorted({x["reviewer"] for x in g}, key=_report_idx)
        anchors = sorted({e["anchor"] for x in g for e in x["evidence"]}, key=_anchor_key)
        out.append({"title": g[0]["title"], "reviewers": revs, "anchors": anchors,
                    "underused": any(x["underused"] for x in g), "_items": g})
    out.sort(key=lambda s: (-len(s["reviewers"]), not s["underused"], _anchor_key(s["anchors"][0]),
                            match_norm(s["title"])))
    for n, s in enumerate(out, 1):
        s["id"] = "S{}".format(n)
    return out


def _line_claim(ctx, anchor):
    entry = ctx.by_id.get(anchor)
    return mask_contact(clean_str(entry[1], 100)) if entry else anchor


def _conflicts(issues, strengths, ctx):
    out = []
    for it in issues:
        if it["family"] not in CONFLICT_FAMILIES or it["severity"] == "minor":
            continue
        for s in strengths:
            shared = sorted(set(s["anchors"]) & set(it["_r_anchors"]), key=_anchor_key)
            if not shared:
                continue
            critics = [f for f in it["_findings"]
                       if f["reviewer"] not in s["reviewers"] and set(_anchors(f, "R")) & set(shared)]
            if not critics:
                continue
            sides, seen = [], set()
            for x in s["_items"]:
                if x["reviewer"] in seen:
                    continue
                seen.add(x["reviewer"])
                q = next((e["quote"] for e in x["evidence"] if e["anchor"] in shared), x["evidence"][0]["quote"])
                sides.append({"reviewer": x["reviewer"], "view": "Strength: " + x["title"], "quote": q})
            for f in sorted(critics, key=_finding_sort_key):
                if f["reviewer"] in seen:
                    continue
                seen.add(f["reviewer"])
                q = next((e["quote"] for e in f["evidence"] if e["anchor"] in shared), f["evidence"][0]["quote"])
                sides.append({"reviewer": f["reviewer"], "view": "Weakness: " + f["title"], "quote": q})
            out.append({"type": "strength_vs_weakness", "issue_id": it["id"], "strength_id": s["id"],
                        "claim": _line_claim(ctx, shared[0]), "anchors": shared, "sides": sides,
                        "which_matters": WHICH_MATTERS[it["stage"]]})
    for it in issues:
        if it["is_pattern"] or it["_spread"] < 2:
            continue
        sides, seen = [], set()
        for f in sorted(it["_findings"], key=_finding_sort_key):
            if f["reviewer"] in seen:
                continue
            seen.add(f["reviewer"])
            sides.append({"reviewer": f["reviewer"], "view": "{}: {}".format(f["severity"].capitalize(), f["title"]),
                          "quote": f["evidence"][0]["quote"]})
        if len(sides) >= 2:
            out.append({"type": "severity_split", "issue_id": it["id"], "strength_id": None,
                        "claim": it["title"], "anchors": it["_r_anchors"] + it["jd_anchors"], "sides": sides,
                        "which_matters": WHICH_MATTERS[it["stage"]]})
    rank = {it["id"]: it["rank"] for it in issues}
    out.sort(key=lambda c: (rank.get(c["issue_id"], 10 ** 6), c["type"] != "strength_vs_weakness",
                            c["strength_id"] or ""))
    return out[:MAX_CONFLICTS]


# ============================================================================= questions, prep
def _questions(reviews, issues):
    """One question per ranked issue (best-ranked first), then unlinked reviewer questions; <= 6."""
    rank_of_finding = {}
    anchor_issues = {}
    for it in issues:
        for f in it["_findings"]:
            rank_of_finding[(f["reviewer"], f["id"])] = it["rank"]
        for a in it["_r_anchors"] + it["jd_anchors"]:
            anchor_issues.setdefault(a, []).append(it["rank"])
    by_rank = {it["rank"]: it for it in issues}
    cands = []
    for it in issues:
        for f in it["_findings"]:
            q = f["fix"]["candidate_question"]
            if q:
                cands.append({"question": q, "why": it["title"], "rank": it["rank"], "reviewer": f["reviewer"],
                              "anchors": _anchors(f, "R") + _anchors(f, "J"), "order": f["_order"]})
    for rid in REPORT_ORDER:
        r = reviews.get(rid)
        if not r:
            continue
        for k, q in enumerate(r["questions"]):
            anchors = [a for a in q["related_anchors"] if re.match(r"^[RJ][0-9]+$", a)]
            ranks = sorted({x for a in anchors for x in anchor_issues.get(a, [])})
            cands.append({"question": q["question"], "why": q["why"] or (by_rank[ranks[0]]["title"] if ranks else ""),
                          "rank": ranks[0] if ranks else 10 ** 6, "reviewer": rid, "anchors": anchors,
                          "order": 10 ** 6 + k})
    cands.sort(key=lambda c: (c["rank"], c["reviewer"] not in GATEKEEPERS, _report_idx(c["reviewer"]),
                              c["order"], match_norm(c["question"])))
    out, used_ranks, seen = [], set(), set()
    for c in cands:
        key = match_norm(c["question"])[:80]
        if key in seen or (c["rank"] < 10 ** 6 and c["rank"] in used_ranks):
            continue
        seen.add(key)
        used_ranks.add(c["rank"])
        # The issue this question unlocks comes first, then other issues on the same lines.
        linked = [c["rank"]] + sorted({x for a in c["anchors"] for x in anchor_issues.get(a, [])} - {c["rank"]}) \
            if c["rank"] < 10 ** 6 else []
        out.append({"id": "RQ{}".format(len(out) + 1), "question": c["question"], "why": clean_str(c["why"], 160),
                    "issue_ids": ["I{}".format(x) for x in linked[:4]],
                    "related_anchors": sorted(set(c["anchors"]), key=_anchor_key)[:6]})
        if len(out) >= MAX_QUESTIONS:
            break
    return out


_RISK_ORDER = {"high": 0, "medium": 1, "low": 2}
MIN_PREP_WORDS = 6
# Words that carry no topic: a question needs at least one other word that also appears on the resume.
_PREP_STOPWORDS = frozenset("""
a about after again all also an and any are as at be been before being both but by can could did do
does doing done during each else ever every for from had has have having how i if in into is it its
just me more most my no not now of on once one only or other our out over own same so some such than
that the their them then there these they this those through to too under until up us very was we
were what when where which while who whom why will with would yes you your yours yourself
tell walk describe explain give example time times kind sort way ways thing things something anything
anyone someone part role main typical usually really actually exactly right first last next new
start started finish finished make made makes get got take took use used using work worked
look looks like happen happened go went say said know knew think thought want wanted need needed
""".split())


def _stem(word):
    return word[:5] if len(word) >= 5 else word


def _topic_words(text):
    words = re.findall(r"[a-z0-9][a-z0-9'+#.-]*[a-z0-9+#]|[a-z0-9]", match_norm(text))
    return {_stem(w) for w in words if len(w) >= 3 and w not in _PREP_STOPWORDS}


def _resume_stems(ctx):
    return {_stem(w) for _, _, ln in ctx.r_lines for w in re.findall(r"[a-z0-9][a-z0-9'+#.-]*[a-z0-9+#]|[a-z0-9]", ln)
            if len(w) >= 3}


def _near_duplicate(a, b):
    """Two prep questions ask the same thing when they share most of their topic words, or at least two
    that make up a good part of the shorter question ("CPR certification" twice). Bare numbers do not
    count: two questions about "2,000 responses" can still ask different things."""
    a = {w for w in a if not re.match(r"^[0-9.,%$]+$", w)}
    b = {w for w in b if not re.match(r"^[0-9.,%$]+$", w)}
    if not a or not b:
        return False
    shared = len(a & b)
    small = float(min(len(a), len(b)))
    return (shared >= 2 and shared / small >= 0.4) or (small >= 2 and shared / small >= 0.6)


def _interview_prep(reviews, ctx, log):
    """Hiring Manager questions first, then the Skeptic's probes (highest risk first); <= 6. A question
    is dropped when it is bare (under 6 words, or no topic word that appears on the resume) or a near
    duplicate of one already kept."""
    cands = []
    hm = reviews.get("hiring_manager")
    if hm:
        qs = hm["lens_data"].get("interview_questions")
        for q in (qs if isinstance(qs, list) else [])[:3]:
            cands.append((clean_str(q, 200), "hiring_manager", None))
    sk = reviews.get("skeptic")
    if sk:
        audit = sk["lens_data"].get("claim_audit")
        rows = []
        for k, c in enumerate(audit if isinstance(audit, list) else []):
            if not isinstance(c, dict):
                continue
            text = clean_str(c.get("probe_question"), 200)
            if not text:
                continue
            ev = check_evidence([{"anchor": c.get("anchor"), "quote": c.get("quote")}], ctx,
                                "skeptic:claim_audit[{}]".format(k), log)
            ev = [e for e in ev if e["anchor"].startswith("R")]
            if not ev:
                continue
            risk = _RISK_ORDER.get(c.get("risk"), 3) if isinstance(c.get("risk"), str) else 3
            rows.append((risk, anchor_num(ev[0]["anchor"]), k, text, ev[0]["anchor"]))
        rows.sort()
        cands.extend((text, "skeptic", anchor) for _, _, _, text, anchor in rows)
    resume = _resume_stems(ctx)
    out, kept = [], []
    for text, src, anchor in cands:
        if len(out) >= MAX_PREP:
            break
        if not text:
            continue
        topics = _topic_words(text)
        if len(text.split()) < MIN_PREP_WORDS or not (topics & resume):
            log.append({"where": "interview_prep", "action": "prep_dropped", "from": src,
                        "reason": "too bare to make sense on its own"})
            continue
        if any(_near_duplicate(topics, k) for k in kept) or match_norm(text) in {match_norm(o["question"]) for o in out}:
            log.append({"where": "interview_prep", "action": "prep_dropped", "from": src,
                        "reason": "near duplicate of a question already kept"})
            continue
        kept.append(topics)
        out.append({"question": text, "from": src, "anchor": anchor})
    return out[:MAX_PREP]


# ============================================================================= student-facing id scrub
# Reviewers must quote words, never cite R#/J#/A: ids in text a student reads. Anything that slips
# through is replaced here by a short quote of that line (or removed when it is only a citation).
_ID = r"(?:A:[A-Z]+-[0-9]{3}b?|[RJ][0-9]+)"
_PAREN_CITE_RE = re.compile(r"\s*\((?:\s*(?:see|lines?|in|on|cf\.?)\s+)?" + _ID +
                            r"(?:\s*(?:[-\u2013]|to)\s*" + _ID + r")?(?:\s*(?:,|;|/|&|and)\s*" + _ID +
                            r"(?:\s*(?:[-\u2013]|to)\s*" + _ID + r")?)*\s*\)")
_RANGE_RE = re.compile(r"(?<![\w:/.-])(?:the\s+)?(?:lines?\s+)?([RJ])([0-9]+)\s*(?:[-\u2013]|to)\s*(?:[RJ])?([0-9]+)(?![\w/-])")
_ONE_RE = re.compile(r"(?<![\w/.-])(?:(the\s+)?(lines?|posting line|bullet)\s+)?(A:[A-Z]+-[0-9]{3}b?|[RJ][0-9]+)"
                     r"(?![\w/-])(?!\s+(?:visas?|universit|institution|research|status|program|classification))")
_LINE_PREFIX_RE = re.compile(r"^\s*(?:\[(?:header|footer|text box)\]\s*)+", re.I)
_LEAD_GLYPH_RE = re.compile("^[\\s\u2022\u25cf\u25aa\u25e6\u2023\u2219\u00b7\u25a0\u25ba\u27a2*-]+")


def _short_quote(text, words):
    t = _LEAD_GLYPH_RE.sub("", _LINE_PREFIX_RE.sub("", text or "")).strip()
    t = re.sub("(\\s*[\u2022\u25cf\u25cb\u25e6\u25aa\u25a0\u25a1\u2605\u2606])+\\s*$", "", t)   # rating dots
    parts = t.split()
    q = " ".join(parts[:words]).rstrip(",;:")
    if len(parts) > words:
        q += "..."
    return mask_contact(q)


def _id_phrase(ctx, anchor, words):
    """'the line ...' for R#, 'the posting line ...' for J#, the screening issue's title for A:, or None."""
    if anchor.startswith("A:"):
        it = ctx.issues.get(anchor[2:])
        title = clean_str(it.get("title"), 80) if isinstance(it, dict) else ""
        return "the screening check\u2019s \u2018{}\u2019".format(title) if title else "the screening check"
    entry = ctx.by_id.get(anchor)
    if entry is None:
        return None
    return "{} \u2018{}\u2019".format("the line" if anchor[0] == "R" else "the posting line",
                                     _short_quote(entry[1], words))


def scrub_ids(text, ctx, words=5):
    """Replace R#/J#/A: ids in student-facing text with a short quote of the line (or remove a citation
    in parentheses). Ids that are not in this run's ledger or screening are left alone."""
    if not isinstance(text, str) or not text or not re.search(_ID, text):
        return text

    def known(a):
        return a.startswith("A:") and a[2:] in ctx.issues or a in ctx.by_id

    def paren(m):
        ids = re.findall(_ID, m.group(0))
        return "" if ids and all(known(a) for a in ids) else m.group(0)

    def rng(m):
        a, b = m.group(1) + m.group(2), m.group(1) + m.group(3)
        if not (known(a) and known(b)):
            return m.group(0)
        qa, qb = _short_quote(ctx.by_id[a][1], 4), _short_quote(ctx.by_id[b][1], 4)
        kind = "lines" if m.group(1) == "R" else "posting lines"
        return "the {} \u2018{}\u2019 to \u2018{}\u2019".format(kind, qa, qb)

    def one(m):
        anchor = m.group(3)
        if not known(anchor):
            return m.group(0)
        return _id_phrase(ctx, anchor, words) or m.group(0)

    out = _PAREN_CITE_RE.sub(paren, text)
    out = _RANGE_RE.sub(rng, out)
    out = _ONE_RE.sub(one, out)
    out = re.sub(r"\s+([,.;:!?])", r"\1", re.sub(r"[ \t]{2,}", " ", out)).strip()
    # A replacement at the start of a sentence starts with a capital.
    out = re.sub(r"(^|[.!?]\s+)the (line|posting line|lines|posting lines|screening check)",
                 lambda m: m.group(1) + "The " + m.group(2), out)
    return out


def _scrub_output(result, ctx):
    """Apply scrub_ids to every student-facing text field of the synthesis (never to quotes)."""
    for r in result["reviewers"]:
        r["one_line_take"] = scrub_ids(r["one_line_take"], ctx, 4)
    for it in result["issues"]:
        it["title"] = scrub_ids(it["title"], ctx, 4)
        it["detail"] = scrub_ids(it["detail"], ctx)
        for f in it["fixes"]:
            f["suggestion"] = scrub_ids(f["suggestion"], ctx)
            if f["candidate_question"]:
                f["candidate_question"] = scrub_ids(f["candidate_question"], ctx)
        it["real_gap_routes"] = [scrub_ids(x, ctx) for x in it["real_gap_routes"]]
        for inst in it["instances"]:
            inst["title"] = scrub_ids(inst["title"], ctx, 4)
    for n in result["notes"]:
        n["title"] = scrub_ids(n["title"], ctx, 4)
    for c in result["conflicts"]:
        c["claim"] = scrub_ids(c["claim"], ctx)
        for side in c["sides"]:
            side["view"] = scrub_ids(side["view"], ctx, 4)
    for st in result["strengths"]:
        st["title"] = scrub_ids(st["title"], ctx, 4)
    for q in result["questions_for_candidate"]:
        q["question"] = scrub_ids(q["question"], ctx)
        q["why"] = scrub_ids(q["why"], ctx, 4)
    for p in result["interview_prep"]:
        p["question"] = scrub_ids(p["question"], ctx)


# ============================================================================= main entry
def _load_reviews(paths, ctx, log):
    reviews, missing = {}, []
    for rid in REPORT_ORDER:
        p = os.path.join(paths["reviews"], rid + ".json")
        raw, err = load_json_file(p, MAX_REVIEW_BYTES)
        if err:
            if err != "missing":
                log.append({"where": rid, "action": "review_unreadable", "reason": err})
            else:
                log.append({"where": rid, "action": "review_missing", "reason": "no reviews/{}.json".format(rid)})
            missing.append(rid)
            continue
        try:
            prepared = prepare_review(rid, raw, ctx, log)
        except Exception as e:   # last-resort guard: hostile content must never stop the panel
            log.append({"where": rid, "action": "review_rejected",
                        "reason": "could not be read safely ({})".format(type(e).__name__)})
            prepared = None
        if prepared is None:
            missing.append(rid)
            continue
        reviews[rid] = prepared
    return reviews, missing


def _verdict_split(reviews):
    ords = {rid: VERDICTS.index(r["verdict"]) for rid, r in reviews.items()}
    if not ords:
        return {"spread": 0, "is_split": False, "median": None, "outliers": [], "advance_split": False}
    vals = sorted(ords.values())
    mid = len(vals) // 2
    med = vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2.0
    spread = vals[-1] - vals[0]
    adv = {r["advance"] for r in reviews.values()}
    return {"spread": spread, "is_split": spread >= 3,
            "median": VERDICTS[int(med + 0.5)],
            "outliers": [rid for rid in REPORT_ORDER if rid in ords and abs(ords[rid] - med) >= 2],
            "advance_split": "yes" in adv and "no" in adv}


def closest_to_reject(reviewers, issues):
    """The reviewer who came closest to rejecting the resume, and why (ARCHITECTURE.md section 17.4).

    `reviewers` and `issues` are the public synthesis shapes (the "reviewers" and "issues" lists). The
    reviewer with the lowest verdict wins; ties go to report order (screening, hiring_manager, recruiter,
    competitor, ceo, teammate, skeptic). Its issue is the top-ranked issue that lists it (lowest rank
    number), else None; the reason is that issue's title, else the reviewer's one_line_take.
    Returns None for an empty panel. Deterministic."""
    rows = [r for r in reviewers or [] if isinstance(r, dict) and r.get("id") in REPORT_ORDER
            and r.get("verdict") in VERDICTS]
    if not rows:
        return None
    low = min(rows, key=lambda r: (VERDICTS.index(r["verdict"]), _report_idx(r["id"])))
    mine = [it for it in issues or [] if isinstance(it, dict) and low["id"] in (it.get("reviewers") or [])
            and isinstance(it.get("rank"), int)]
    top = min(mine, key=lambda it: (it["rank"], str(it.get("id")))) if mine else None
    reason = top.get("title") if top else low.get("one_line_take")
    return {"reviewer": low["id"], "verdict": low["verdict"], "issue_id": top.get("id") if top else None,
            "reason": reason if isinstance(reason, str) else ""}


def _public_issue(it):
    return {"id": it["id"], "rank": it["rank"], "title": it["title"], "family": it["family"],
            "categories": it["categories"], "severity": it["severity"], "priority": it["priority"],
            "reviewers": it["reviewers"], "reviewer_count": len(it["reviewers"]),
            "from_script": it["from_script"], "stage": it["stage"], "lane": it["lane"],
            "has_real_gap": it["has_real_gap"], "real_gap_routes": it["real_gap_routes"],
            "evidence": it["evidence"], "detail": it["detail"], "fixes": it["fixes"],
            "jd_anchors": it["jd_anchors"], "is_pattern": it["is_pattern"], "instances": it["instances"]}


def _is_pinned(it):
    for f in it["_findings"]:
        if f["family"] in INTEGRITY_FAMILIES and _sev_idx(f["severity"]) >= _sev_idx("major"):
            return True
        if any(e["anchor"][2:] in PINNED_SCRIPT_IDS for e in f["evidence"] if e["anchor"].startswith("A:")):
            return True
    return False


def synthesize(run_dir, mode="parallel", merges_path=None, write=True):
    """Combine the panel's reviews into work/synthesis.json and return the result dict.

    Raises PanelError for an unknown mode or a missing/unusable ledger; review content never raises.
    `merges_path` defaults to nothing; pass work/merges.json explicitly to apply it."""
    if mode not in MODES:
        raise PanelError("mode must be one of {}; got {!r}".format(", ".join(MODES), mode))
    paths = run_paths(run_dir)
    ledger = load_ledger(paths["ledger"])
    log = []
    ctx = SourceContext(ledger, load_screening(paths["screening"], log))
    reviews, missing = _load_reviews(paths, ctx, log)

    try:
        flat = auto_findings(ctx, log)
    except Exception as e:   # malformed screening.json must not stop the panel
        log.append({"where": "screening.json", "action": "screening_ignored",
                    "reason": "could not read issues safely ({})".format(type(e).__name__)})
        flat = []
    for rid in REPORT_ORDER:
        if rid in reviews:
            flat.extend(reviews[rid]["findings"])
    for i, f in enumerate(flat):
        f["_order"] = i
        f["_index"] = i
    merge_pairs = _merge_pairs(merges_path, flat, ctx, mode, log)
    issues = _build_issues(flat, ctx, mode, merge_pairs)
    strengths = _strengths(reviews, ctx, log)
    conflicts = _conflicts(issues, strengths, ctx)

    result = {
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "panel_size": len(reviews),
        "missing_reviewers": [rid for rid in REPORT_ORDER if rid in missing],
        "reviewers": [{"id": rid, "name": REVIEWER_INFO[rid]["name"], "verdict": reviews[rid]["verdict"],
                       "advance": reviews[rid]["advance"], "confidence": reviews[rid]["confidence"],
                       "one_line_take": reviews[rid]["one_line_take"],
                       "decision_question": REVIEWER_INFO[rid]["decision_question"]}
                      for rid in REPORT_ORDER if rid in reviews],
        "panel_vote": {"advance": sum(1 for r in reviews.values() if r["advance"] == "yes"),
                       "unsure": sum(1 for r in reviews.values() if r["advance"] == "unsure"),
                       "no": sum(1 for r in reviews.values() if r["advance"] == "no"),
                       "total": len(reviews)},
        "verdict_split": _verdict_split(reviews),
        "closest_to_reject": None,
        "issues": [_public_issue(it) for it in issues],
        "notes": screening_notes(ctx),
        "top3": [it["id"] for it in issues[:3]],
        "pinned_integrity": [it["id"] for it in issues if _is_pinned(it)],
        "conflicts": conflicts,
        "strengths": [{"id": s["id"], "title": s["title"], "reviewers": s["reviewers"], "anchors": s["anchors"],
                       "underused": s["underused"]} for s in strengths[:MAX_STRENGTHS]],
        "questions_for_candidate": _questions(reviews, issues),
        "interview_prep": _interview_prep(reviews, ctx, log),
        "validation_log": log,
    }
    _scrub_output(result, ctx)
    result["closest_to_reject"] = closest_to_reject(result["reviewers"], result["issues"])
    result = _mask_strings(result)
    if write:
        write_json(paths["synthesis"], result)
    return result


def _mask_strings(node):
    """Mask emails and phone numbers in every string of the output (quotes were verified before this
    point; synthesis.json feeds the report and the chat summary, where contact details stay masked)."""
    if isinstance(node, dict):
        return dict((k, _mask_strings(v)) for k, v in node.items())
    if isinstance(node, list):
        return [_mask_strings(v) for v in node]
    if isinstance(node, str):
        return mask_contact(node)
    return node


def cli_summary(result):
    """The compact stdout object for `hp.py synthesize` (ARCHITECTURE.md section 13)."""
    issues = result.get("issues") or []
    return {
        "panel_vote": result.get("panel_vote"),
        "reviewers": [{"id": r["id"], "verdict": r["verdict"], "advance": r["advance"],
                       "one_line_take": r["one_line_take"]} for r in result.get("reviewers") or []],
        "top": [{"id": it["id"], "title": it["title"], "severity": it["severity"], "flagged_by": it["reviewers"]}
                for it in issues[:5]],
        "questions": [q["question"] for q in result.get("questions_for_candidate") or []],
        "dropped": sum(1 for e in result.get("validation_log") or [] if e.get("action") == "finding_dropped"),
    }


__all__ = ["validate_review", "check_review", "synthesize", "cli_summary", "closest_to_reject", "MODES",
           "LAMBDA"]
