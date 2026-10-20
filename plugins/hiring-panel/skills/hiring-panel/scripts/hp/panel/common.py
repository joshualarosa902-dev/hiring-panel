"""Shared constants and helpers for the panel: reviewer ids, lenses, categories, run-folder paths,
safe file loading, quote matching and the evidence checker used by both validation and synthesis.

Everything here is deterministic and never raises on hostile content: bad input is reported through
return values or the caller's log list.
"""
import json
import os
import re

from hp.util import norm_for_match

SCHEMA_VERSION = "1.0"

# ----------------------------------------------------------------------------- reviewers
# Report order (Reel order) is the canonical order everywhere in synthesis output.
REPORT_ORDER = ["screening", "hiring_manager", "recruiter", "competitor", "ceo", "teammate", "skeptic"]
SEQUENTIAL_ORDER = ["screening", "recruiter", "hiring_manager", "teammate", "ceo", "competitor", "skeptic"]
GATEKEEPERS = ("screening", "recruiter", "hiring_manager")

REVIEWER_INFO = {
    "screening": {
        "name": "Automated Screening Check",
        "lens": "Machine readability and job keywords",
        "file": "01-screening.md",
        "dimension_prefix": "S",
        "decision_question": "Would this file parse cleanly, and would it come up when a recruiter "
                             "searches or filters the applicant pool for this job?",
    },
    "hiring_manager": {
        "name": "Hiring Manager",
        "lens": "Proof you can do this job",
        "file": "02-hiring-manager.md",
        "dimension_prefix": "H",
        "decision_question": "Based on this resume alone, would I spend 45 minutes interviewing this "
                             "person for this role?",
    },
    "recruiter": {
        "name": "Recruiter",
        "lens": "The fast first skim",
        "file": "03-recruiter.md",
        "dimension_prefix": "C",
        "decision_question": "In my first fast pass, does this resume go in the 'send to the hiring "
                             "manager' pile?",
    },
    "competitor": {
        "name": "Competing Applicant",
        "lens": "Side by side with a strong applicant",
        "file": "04-competitor.md",
        "dimension_prefix": "P",
        "decision_question": "If this resume sat next to a typical strong applicant's for this job, "
                             "would it win the interview slot?",
    },
    "ceo": {
        "name": "CEO",
        "lens": "Business outcomes and ownership",
        "file": "05-ceo.md",
        "dimension_prefix": "E",
        "decision_question": "Would this person move something the business cares about, and in a "
                             "year would I fight to keep them?",
    },
    "teammate": {
        "name": "Future Teammate",
        "lens": "Day-one usefulness on the team",
        "file": "06-teammate.md",
        "dimension_prefix": "T",
        "decision_question": "Would I want this person on my team for next week's work, and could "
                             "they contribute without a lot of hand-holding?",
    },
    "skeptic": {
        "name": "Skeptic",
        "lens": "Claims that must survive a probe",
        "file": "07-skeptic.md",
        "dimension_prefix": "K",
        "decision_question": "Which lines would not survive a five-minute probe in an interview or a "
                             "reference check, and does anything read as inflated even if it is true?",
    },
}

DIMENSIONS = {
    "screening": ["S1_parse_safety", "S2_required_coverage", "S3_title_alignment",
                  "S4_knockout_exposure", "S5_keyword_context"],
    "hiring_manager": ["H1_requirement_match", "H2_proof_of_work", "H3_results",
                       "H4_problem_solving", "H5_trajectory"],
    "recruiter": ["C1_top_third", "C2_skimmability", "C3_basic_qualifiers", "C4_red_flags",
                  "C5_instant_fit"],
    "competitor": ["P1_table_stakes", "P2_differentiation", "P3_specificity", "P4_proof_density",
                   "P5_positioning"],
    "ceo": ["E1_business_outcomes", "E2_ownership", "E3_judgment", "E4_alignment", "E5_ceiling"],
    "teammate": ["T1_day_one_toolkit", "T2_collaboration", "T3_dependability",
                 "T4_individual_contribution", "T5_ramp_up"],
    "skeptic": ["K1_verifiability", "K2_scope_plausibility", "K3_attribution",
                "K4_internal_consistency", "K5_inflation_density"],
}

LENS = {
    "screening": ("PARSE_FORMAT", "CONTACT_HEADER", "KEYWORD_GAP", "TITLE_MISMATCH", "KNOCKOUT_RISK"),
    "hiring_manager": ("REQUIREMENT_UNPROVEN", "SKILL_UNSUPPORTED", "IMPACT_MISSING", "METRIC_MISSING",
                       "ORDER_PRIORITY", "RELEVANCE_NOISE", "PROOF_LINKS"),
    "recruiter": ("CONTACT_HEADER", "TITLE_MISMATCH", "KNOCKOUT_RISK", "LAYOUT_SKIM", "LENGTH_DENSITY",
                  "TYPO_GRAMMAR", "EDUCATION_PRESENTATION", "TRAJECTORY_GAP", "ORDER_PRIORITY"),
    "competitor": ("GENERIC_DIFFERENTIATION", "VAGUE_LANGUAGE", "PROOF_LINKS", "METRIC_MISSING",
                   "ORDER_PRIORITY"),
    "ceo": ("IMPACT_MISSING", "OWNERSHIP_EVIDENCE", "MISSION_ALIGNMENT", "RELEVANCE_NOISE"),
    "teammate": ("COLLABORATION_EVIDENCE", "ATTRIBUTION_UNCLEAR", "SKILL_UNSUPPORTED",
                 "REQUIREMENT_UNPROVEN"),
    "skeptic": ("SCOPE_INFLATION", "UNVERIFIABLE_CLAIM", "ATTRIBUTION_UNCLEAR", "INCONSISTENCY",
                "SKILL_UNSUPPORTED", "VAGUE_LANGUAGE"),
}

VERDICTS = ["strong_no", "lean_no", "borderline", "lean_yes", "strong_yes"]   # ordinal 0..4
ADVANCE = ("yes", "no", "unsure")
SEVERITIES = ["minor", "moderate", "major", "critical"]                       # ordinal 0..3
CONFIDENCES = ("high", "medium", "low")
FIX_ORDER = ["rewrite", "reorder", "reformat", "add_keyword_truthfully", "remove",
             "needs_candidate_input", "real_gap"]

# category -> (family, funnel stage, merge key: "doc" | "line" | "jd")
CATS = {
    "PARSE_FORMAT": ("PARSE", "ats", "doc"),
    "CONTACT_HEADER": ("CONTACT", "ats", "doc"),
    "KEYWORD_GAP": ("REQUIREMENT", "ats", "jd"),
    "KNOCKOUT_RISK": ("REQUIREMENT", "ats", "jd"),
    "REQUIREMENT_UNPROVEN": ("REQUIREMENT", "hm_review", "jd"),
    "TITLE_MISMATCH": ("TITLE", "recruiter_skim", "doc"),
    "LAYOUT_SKIM": ("SKIM", "recruiter_skim", "doc"),
    "LENGTH_DENSITY": ("SKIM", "recruiter_skim", "doc"),
    "TYPO_GRAMMAR": ("MECHANICS", "recruiter_skim", "line"),
    "EDUCATION_PRESENTATION": ("EDUCATION", "recruiter_skim", "doc"),
    "TRAJECTORY_GAP": ("HISTORY", "recruiter_skim", "doc"),
    "ORDER_PRIORITY": ("ORDER", "recruiter_skim", "doc"),
    "RELEVANCE_NOISE": ("NOISE", "hm_review", "line"),
    "SKILL_UNSUPPORTED": ("SKILL_EVIDENCE", "hm_review", "line"),
    "IMPACT_MISSING": ("IMPACT", "hm_review", "line"),
    "METRIC_MISSING": ("IMPACT", "hm_review", "line"),
    "VAGUE_LANGUAGE": ("IMPACT", "hm_review", "line"),
    "GENERIC_DIFFERENTIATION": ("DIFFERENTIATION", "hm_review", "doc"),
    "PROOF_LINKS": ("PROOF", "hm_review", "doc"),
    "MISSION_ALIGNMENT": ("FIT", "hm_review", "doc"),
    "OWNERSHIP_EVIDENCE": ("CONTRIBUTION", "interview", "line"),
    "ATTRIBUTION_UNCLEAR": ("CONTRIBUTION", "interview", "line"),
    "COLLABORATION_EVIDENCE": ("TEAMWORK", "interview", "doc"),
    "SCOPE_INFLATION": ("CREDIBILITY", "interview", "line"),
    "UNVERIFIABLE_CLAIM": ("CREDIBILITY", "interview", "line"),
    "INCONSISTENCY": ("CONSISTENCY", "interview", "line"),
}
CATEGORY_ORDER = list(CATS)

# Plain-language fallback titles when a finding arrives without a usable title.
CATEGORY_LABEL = {
    "PARSE_FORMAT": "File may not parse cleanly",
    "CONTACT_HEADER": "Contact details are hard to find",
    "KEYWORD_GAP": "Job keywords are missing",
    "TITLE_MISMATCH": "Target job title is not visible",
    "KNOCKOUT_RISK": "A hard requirement may screen you out",
    "LAYOUT_SKIM": "Hard to skim",
    "LENGTH_DENSITY": "Length or density gets in the way",
    "TYPO_GRAMMAR": "Writing slips",
    "EDUCATION_PRESENTATION": "Education is hard to read",
    "TRAJECTORY_GAP": "Timeline raises questions",
    "ORDER_PRIORITY": "Best evidence is buried",
    "RELEVANCE_NOISE": "Content that does not help for this job",
    "REQUIREMENT_UNPROVEN": "A requirement is not shown",
    "SKILL_UNSUPPORTED": "Skills listed but not shown in your work",
    "IMPACT_MISSING": "Duties instead of results",
    "METRIC_MISSING": "No numbers to show scale",
    "VAGUE_LANGUAGE": "Vague wording",
    "GENERIC_DIFFERENTIATION": "Nothing stands out yet",
    "PROOF_LINKS": "No proof or links to your work",
    "OWNERSHIP_EVIDENCE": "Ownership is unclear",
    "MISSION_ALIGNMENT": "No link to what the company does",
    "COLLABORATION_EVIDENCE": "Teamwork is claimed, not shown",
    "ATTRIBUTION_UNCLEAR": "Your own part is unclear",
    "SCOPE_INFLATION": "A claim reads as bigger than the role",
    "UNVERIFIABLE_CLAIM": "A claim is hard to verify",
    "INCONSISTENCY": "Details do not line up",
}

STAGE_ORDER = ["ats", "recruiter_skim", "hm_review", "interview"]

LEDGER_SECTIONS = ("header_footer", "contact", "summary", "education", "experience", "projects",
                   "skills", "leadership", "other")
JD_KINDS = ("must", "nice", "responsibility", "company", "logistics", "other")

# Anchor grammar (ARCHITECTURE.md section 8). Reviews may use R/J/A; Q is for the provenance audit.
ANCHOR_RE = re.compile(r"^([RJ][0-9]+|A:[A-Z]+-[0-9]{3}b?|Q[0-9]+)$")
REVIEW_ANCHOR_RE = re.compile(r"^([RJ][0-9]+|A:[A-Z]+-[0-9]{3}b?)$")
ISSUE_ID_RE = re.compile(r"^[A-Z]+-[0-9]{3}b?$")

# Size limits for files we read (hostile or runaway input never exhausts memory).
MAX_REVIEW_BYTES = 2 * 1024 * 1024
MAX_INPUT_BYTES = 32 * 1024 * 1024


def as_list(value):
    """The value if it is a list, else an empty list (hostile JSON often puts a scalar where a list goes)."""
    return value if isinstance(value, list) else []


class PanelError(Exception):
    """Raised for problems the caller must fix (missing ledger, bad mode). Never for review content."""


# ----------------------------------------------------------------------------- run-folder paths
def work_dir(run_dir):
    """Return the run's work/ folder. Accepts the run folder or the work folder itself."""
    run_dir = os.fspath(run_dir)
    w = os.path.join(run_dir, "work")
    if os.path.isdir(w):
        return w
    if os.path.isdir(os.path.join(run_dir, "inputs")) or os.path.isdir(os.path.join(run_dir, "reviews")):
        return run_dir
    return w


def run_paths(run_dir):
    w = work_dir(run_dir)
    return {
        "work": w,
        "resume_md": os.path.join(w, "inputs", "resume.md"),
        "jd_md": os.path.join(w, "inputs", "jd.md"),
        "ats_view": os.path.join(w, "inputs", "ats_view.txt"),
        "ledger": os.path.join(w, "inputs", "ledger.json"),
        "screening": os.path.join(w, "screening", "before", "screening.json"),
        "brief": os.path.join(w, "screening", "before", "brief.json"),
        "reviews": os.path.join(w, "reviews"),
        "merges": os.path.join(w, "merges.json"),
        "synthesis": os.path.join(w, "synthesis.json"),
    }


def skill_dir():
    """The skill folder (contains SKILL.md, schemas/, references/), found from this file."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def schema_path(name):
    return os.path.join(skill_dir(), "schemas", name)


# ----------------------------------------------------------------------------- safe loading
def load_json_file(path, max_bytes=MAX_INPUT_BYTES):
    """Return (data, error). Never raises for missing, oversized, undecodable or invalid JSON files."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return None, "missing"
    if size > max_bytes:
        return None, "too large ({} bytes)".format(size)
    try:
        with open(path, "rb") as f:
            raw = f.read(max_bytes + 1)
        text = raw.decode("utf-8-sig")
    except (OSError, UnicodeDecodeError) as e:
        return None, "unreadable: {}".format(type(e).__name__)
    try:
        return json.loads(text), None
    except (ValueError, RecursionError) as e:
        return None, "invalid JSON: {}".format(str(e)[:120])


# ----------------------------------------------------------------------------- text helpers
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_INVISIBLE_RE = re.compile("[\u00ad\u200b\u200c\u200d\u2060\ufeff]")
_BULLET_GLYPHS_RE = re.compile("[\u2022\u25cf\u25aa\u25e6\u2023\u2219\u00b7\u25a0\u25a1\u25ba\u25b8\u27a2\u2043*]")


def clean_str(value, max_len=None):
    """Coerce to a single-line-safe string: drop control and zero-width characters, trim, cap length."""
    if value is None:
        return ""
    if not isinstance(value, str):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value = str(value)
        else:
            return ""
    s = _INVISIBLE_RE.sub("", _CTRL_RE.sub(" ", value))
    s = re.sub(r"\s+", " ", s).strip()
    if max_len is not None and len(s) > max_len:
        s = s[: max_len - 1].rstrip() + "\u2026"
    return s


def cap_words(s, n):
    words = s.split()
    if len(words) <= n:
        return s
    return " ".join(words[:n]).rstrip(",;:") + "\u2026"


def match_norm(s):
    """Normalization for verbatim-quote checks: util.norm_for_match plus dash, bullet-glyph and
    zero-width folding, so smart quotes, en dashes and bullet markers never break a true quote."""
    if not isinstance(s, str):
        return ""
    s = _INVISIBLE_RE.sub("", s)
    s = norm_for_match(s)
    s = s.replace("\u2013", "-")
    s = _BULLET_GLYPHS_RE.sub(" ", s)
    s = s.replace("\u2026", "...")
    return re.sub(r"\s+", " ", s).strip()


def quote_in_line(quote_norm, line_norm):
    """True when the (normalized) quote occurs in the (normalized) line. A quote may be shortened with
    '...' between exact fragments; each fragment must then appear in order."""
    if not quote_norm or not line_norm:
        return False
    if quote_norm in line_norm:
        return True
    if "..." not in quote_norm:
        return False
    parts = [p.strip() for p in quote_norm.split("...") if p.strip()]
    if not parts or any(len(p) < 3 for p in parts):
        return False
    pos = 0
    for p in parts:
        k = line_norm.find(p, pos)
        if k < 0:
            return False
        pos = k + len(p)
    return True


def quote_is_usable(quote_norm):
    """A quote must be long enough to mean something (a one-letter 'quote' matches anything)."""
    return len(quote_norm.replace(".", "").strip()) >= 3 and re.search(r"[0-9a-z\u00c0-\uffff]", quote_norm) is not None


def anchor_num(anchor):
    """Numeric part of R12 / J3 / Q2 for sorting; large for anything else."""
    m = re.match(r"^[RJQ]([0-9]+)$", anchor or "")
    return int(m.group(1)) if m else 10 ** 9


def term_in_text(term, text, text_norm):
    """Word-boundary search for a searched term. Short terms (<= 2 chars, like R or Go) are matched
    case-sensitively in the original text so 'R&D' or 'go' in prose do not count as the skill."""
    t = (term or "").strip()
    if not t:
        return False
    if len(t) <= 2:
        return re.search(r"(?<![\w+#&/.])" + re.escape(t) + r"(?![\w+#&/])", text) is not None
    tn = match_norm(t)
    if not tn:
        return False
    return re.search(r"(?<![0-9a-z])" + re.escape(tn) + r"(?![0-9a-z])", text_norm) is not None


# ----------------------------------------------------------------------------- source context
class SourceContext(object):
    """The facts every check needs: numbered resume and JD lines, screening issue ids and keywords."""

    def __init__(self, ledger, screening=None):
        self.ledger = ledger
        self.r_lines = []   # [(id, raw text, normalized text)] in ledger order
        self.j_lines = []
        self.by_id = {}
        self.section = {}   # R id -> ledger section label
        for key, store in (("resume_lines", self.r_lines), ("jd_items", self.j_lines)):
            for item in as_list(ledger.get(key)):
                if not isinstance(item, dict):
                    continue
                lid, text = item.get("id"), item.get("text")
                if not isinstance(lid, str) or not isinstance(text, str):
                    continue
                entry = (lid, text, match_norm(text))
                store.append(entry)
                self.by_id[lid] = entry
                if key == "resume_lines" and isinstance(item.get("section"), str):
                    self.section[lid] = item["section"]
        self.jd_kind = {}
        for item in as_list(ledger.get("jd_items")):
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                self.jd_kind[item["id"]] = item.get("kind") if item.get("kind") in JD_KINDS else "other"
        target = ledger.get("target") if isinstance(ledger.get("target"), dict) else {}
        gr = target.get("general_review")
        self.general_review = bool(gr) if isinstance(gr, bool) else not self.j_lines
        self.resume_text = "\n".join(t for _, t, _ in self.r_lines)
        self.resume_norm = " \n ".join(n for _, _, n in self.r_lines)
        # screening facts
        self.screening = screening if isinstance(screening, dict) else None
        self.issues = {}            # id -> issue dict (first occurrence wins)
        self.issue_order = []
        if self.screening:
            for it in as_list(self.screening.get("issues")):
                if isinstance(it, dict) and isinstance(it.get("id"), str) and ISSUE_ID_RE.match(it["id"]):
                    if it["id"] not in self.issues:
                        self.issues[it["id"]] = it
                        self.issue_order.append(it["id"])
        self.found_terms = set()    # normalized names of keywords the screening check found
        self.keyword_rows = []
        if self.screening:
            kw = self.screening.get("keywords")
            if isinstance(kw, dict):
                for bucket in ("required", "preferred", "other"):
                    for row in as_list(kw.get(bucket)):
                        if not isinstance(row, dict):
                            continue
                        self.keyword_rows.append((bucket, row))
                        if row.get("found") is True:
                            for k in ("term", "canonical", "resume_wording"):
                                v = row.get(k)
                                if isinstance(v, str) and v.strip():
                                    self.found_terms.add(match_norm(v))

    def lines_for(self, prefix):
        return self.r_lines if prefix == "R" else self.j_lines

    def term_found(self, term):
        """True if the resume contains the term, or the screening check says it found it."""
        if term_in_text(term, self.resume_text, self.resume_norm):
            return True
        return match_norm(term) in self.found_terms if isinstance(term, str) else False


def check_evidence(evidence, ctx, where, log, allow_q=False):
    """Verify evidence items against the sources. Returns the surviving items as
    [{"anchor", "quote"}] with repaired anchors. Every repair or drop is appended to `log`."""
    good, seen = [], set()
    if not isinstance(evidence, list):
        log.append({"where": where, "action": "evidence_dropped", "reason": "evidence is not a list"})
        return good
    for ev in evidence[:8]:
        if not isinstance(ev, dict) or not isinstance(ev.get("anchor"), str):
            log.append({"where": where, "action": "evidence_dropped", "reason": "malformed evidence item"})
            continue
        anchor = ev["anchor"].strip()
        raw_quote = ev.get("quote") if isinstance(ev.get("quote"), str) else ""
        quote = clean_str(raw_quote, 220)
        if not ANCHOR_RE.match(anchor):
            log.append({"where": where, "action": "evidence_dropped", "anchor": clean_str(anchor, 40),
                        "reason": "not an anchor (use R#, J# or A:<ISSUE-ID>)"})
            continue
        if anchor.startswith("Q"):
            if allow_q:
                key = (anchor, match_norm(quote))
                if key not in seen:
                    seen.add(key)
                    good.append({"anchor": anchor, "quote": quote})
            else:
                log.append({"where": where, "action": "evidence_dropped", "anchor": anchor,
                            "reason": "Q anchors are only for the provenance audit"})
            continue
        if anchor.startswith("A:"):
            iid = anchor[2:]
            if iid in ctx.issues:
                if not quote:
                    quote = clean_str(ctx.issues[iid].get("title"), 160)
                key = (anchor, "")
                if key not in seen:
                    seen.add(key)
                    good.append({"anchor": anchor, "quote": quote})
            else:
                log.append({"where": where, "action": "evidence_dropped", "anchor": anchor,
                            "reason": "no such issue in screening.json" if ctx.screening
                            else "screening.json not available"})
            continue
        qn = match_norm(quote)
        if not quote_is_usable(qn):
            log.append({"where": where, "action": "evidence_dropped", "anchor": anchor,
                        "reason": "quote missing or too short to verify"})
            continue
        entry = ctx.by_id.get(anchor)
        if entry is not None and quote_in_line(qn, entry[2]):
            final = anchor
        else:
            final = None
            for lid, _, ln in ctx.lines_for(anchor[0]):
                if quote_in_line(qn, ln):
                    final = lid
                    break
            if final is None:
                log.append({"where": where, "action": "evidence_dropped", "anchor": anchor,
                            "quote": quote[:80], "reason": "quote not found on that line or any other"})
                continue
            log.append({"where": where, "action": "anchor_repaired", "from": anchor, "to": final})
        key = (final, qn)
        if key in seen:
            continue
        seen.add(key)
        good.append({"anchor": final, "quote": quote})
    return good


def load_ledger(path):
    """Load and sanity-check ledger.json. Raises PanelError with a plain message when unusable."""
    data, err = load_json_file(path)
    if err:
        raise PanelError("ledger.json {} ({}); run init (or build_ledger) first".format(err, path))
    problems = ledger_problems(data)
    if problems:
        raise PanelError("ledger.json is not usable: " + "; ".join(problems[:5]))
    return data


def ledger_problems(ledger):
    """Return a list of structural problems with a ledger dict (empty when usable)."""
    if not isinstance(ledger, dict):
        return ["not a JSON object"]
    out = []
    for key, prefix in (("resume_lines", "R"), ("jd_items", "J")):
        items = ledger.get(key)
        if not isinstance(items, list):
            out.append("{} is not a list".format(key))
            continue
        for i, item in enumerate(items):
            if not isinstance(item, dict) or not isinstance(item.get("text"), str):
                out.append("{}[{}] is malformed".format(key, i))
                break
            if item.get("id") != "{}{}".format(prefix, i + 1):
                out.append("{}[{}] has id {!r}, expected {}{}".format(key, i, item.get("id"), prefix, i + 1))
                break
    if "target" in ledger and not isinstance(ledger.get("target"), dict):
        out.append("target is not an object")
    return out


def load_screening(path, log):
    """screening.json is optional for the panel; problems are logged, never raised."""
    data, err = load_json_file(path)
    if err:
        if err != "missing":
            log.append({"where": "screening.json", "action": "screening_ignored", "reason": err})
        return None
    if not isinstance(data, dict):
        log.append({"where": "screening.json", "action": "screening_ignored", "reason": "not a JSON object"})
        return None
    return data
