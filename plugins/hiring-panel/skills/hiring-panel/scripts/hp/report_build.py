"""Build work/report.json from a run's artifacts (ARCHITECTURE.md section 12).

    from hp.report_build import build_report
    report = build_report(run_dir)                 # stage "panel" or "final", picked from the run
    report = build_report(run_dir, notes=[])       # the same, plus plain-text notes for stderr

This is the ONLY place report numbers come from: every count, score and vote is copied from a script
output (screening.json, synthesis.json, truth.json, gate.json); nothing is estimated here and the model
never writes report.json. All wording added here is a fixed template chosen by rules, so the report
states only facts from the inputs or cited constants.

Two stages:
  panel  after synthesis, before the rewrite (delivered early so a usage limit cannot lose the feedback):
         every weakness is "open", changes is null and the truth check has not run.
  final  after `render`: statuses come from resume.json meta.addressed (else the synthesis lane), the
         screening "after" side comes from the gate's re-read of the new .docx (else the .pdf), and the
         truth check is reported exactly as the script found it.

Statuses are verified, not just claimed (live tests A24, 6.11): for a keyword issue the claim is checked
against the re-read of the new resume and the lower of the two wins (fixed: every term now shown; improved:
some progress, but a term is only listed, marked as coursework or a class project, or still missing;
needs_you / gap: no progress). A lowered claim gets a "Re-check of the new resume: ..." fix text and a note
for the CLI. Final-stage keyword gaps come from the same re-read (6.9). Real gaps list every issue a reviewer
marked as a real gap (synthesis has_real_gap, else a real_gap fix), every meta.addressed gap and every
keyword issue the re-check left as a gap (4.3, 6.12). Internal R#/J#/A: ids in display text become short
quotes of the line or are removed (A11). The candidate name is resume.json's, else the screening's only when
it looks like a name, else omitted (A23).

Right under the verdict strip (ARCHITECTURE.md section 17): `first_impression` is the Recruiter's 7-second
takeaway from its review (at most 30 words), and `strong_resume` is true only when at least 5 reviewers
say yes, no issue is critical or major and nothing is pinned; only then does verdict_strip.strong_line
carry the fixed "Strong resume. The <reviewer> came closest to saying no: ..." template, built from
synthesis.closest_to_reject.

Contact details are masked in every string. Deterministic: same run artifacts, same bytes.
"""
import os
import re

from hp import __version__
from hp import run as hprun
from hp.util import PHONE_INTL_RE, mask_contact, norm_for_match, read_json

REPORT_VERSION = "1.0"
REVIEWER_IDS = hprun.REVIEWER_IDS
SCREENING_LABEL = "Simulated screening check"
METHOD = ("Overall = 40% file readability + 40% job-keyword match + 20% content signals, rounded to steps of "
          "5. Weights are our judgment, not calibrated to hiring outcomes.")
AFTER_NOTE = "Re-read by fresh reviewers; directional."
STRONG_MIN_YES = 5            # "strong resume" needs at least 5 reviewers saying yes (5 of 7)
FIRST_IMPRESSION_WORDS = 30   # the Recruiter's 7-second takeaway, capped
_QUOTE_CHARS = "\"'\u201c\u201d\u2018\u2019"
STEM = "Hiring_Panel_Report"

# Truth-check error codes that mean a fact the candidate never gave (counted as "invented facts").
FACT_CODES = ("ENTITY_NOT_IN_SOURCE", "DATE_NOT_IN_SOURCE", "DATE_PRECISION_ADDED", "NUMBER_NOT_IN_SOURCE",
              "TERM_NOT_IN_SOURCE", "SKILL_NOT_IN_SOURCE", "OWNERSHIP_UPGRADED", "HEDGE_REMOVED",
              "CONTACT_CHANGED", "JD_AS_EVIDENCE", "NO_EVIDENCE", "EVIDENCE_QUOTE_NOT_FOUND")
REWRITE_OPS = ("REPHRASE", "TIGHTEN", "MERGE", "SPLIT", "MIRROR", "QUANTIFY_FROM_SOURCE", "QUANTIFY_FROM_USER",
               "SURFACE", "STANDARDIZE", "RELABEL_SECTION")

MODE_LABEL = {"parallel": "%d independent reviewers (Claude Code)",
              "sequential": "One chat, %d reviewers in turn",
              "lite": "Quick run, %d reviewers in one chat",
              "manual": "Manual mode (no scripts)"}
MODE_NOTE = {
    "sequential": "One chat played all 7 reviewers in turn, so their views are less independent than 7 "
                  "separate reviewers. Treat the vote as approximate.",
    "lite": "One chat played all 7 reviewers in turn from short role cards, so their views are less "
            "independent than 7 separate reviewers. Treat the vote as approximate.",
    "manual": "Python could not run, so Claude did the checks by hand. Treat every result as approximate.",
}
LANE_STATUS = {"fixed_by_rewrite": "fixed", "needs_your_input": "needs_you", "real_gap": "gap"}
GAP_ROUTE = "No wording can fix this honestly. Close it with real experience first, then add it."
CUT_NOTE = "The line was cut from the new resume, so this no longer applies."
REVIEWERS_LIMIT = ("The reviewers are simulated by Claude. They can be wrong, and they never saw the real "
                   "applicant pool.")

KW_NOTES = {
    ("gap", "required", "no"): "Required. You said you have not used it, so it stays off your resume.",
    ("gap", "required", None): "Required by the posting and not on your resume. Add it only if you have used it.",
    ("gap", "other", "no"): "Nice to have. You said you have not used it, so it stays off your resume.",
    ("gap", "other", None): "Nice to have. Add it only if you have used it.",
    ("listed_only", None, None): "Only in your skills list. Show it in a bullet about real work, if you can.",
    ("added_with_evidence", None, None): "Now shown on your resume, backed by your own lines or answers.",
}
# Gap notes that fit what the term is: you hold a certification, have a diploma, speak a language and show a
# soft skill through an example; you "use" a tool or skill (live test 6.9).
KW_GAP_NOTES = {
    ("cert", "required"): "Required by the posting and not on your resume. Add it only if you hold it.",
    ("cert", "other"): "Nice to have. Add it only if you hold it.",
    ("edu", "required"): "Required by the posting and not found on your resume. Add it only if you have it.",
    ("edu", "other"): "Nice to have. Add it only if you have it.",
    ("lang", "required"): "Required by the posting and not on your resume. Add it only if you speak it.",
    ("lang", "other"): "Nice to have. Add it only if you speak it.",
    ("soft", "required"): "Required by the posting and not named on your resume. Show it through a real example, "
                          "if you have one.",
    ("soft", "other"): "Nice to have. Show it through a real example, if you have one.",
}
KW_YES_NOT_FOUND = ("You said you have it, but the re-check cannot find this exact term. Use the posting's wording "
                    "only where it is true.")
KW_SOME = "You said you have some experience with it. Keep the qualifier when you mention it."
KW_QUALIFIED = "Now shown as coursework or a class project. That is honest; keep the qualifier."
# Where a listed-only term sits (screening resume_locations) -> how the report names that place.
LIST_PLACES = (("skills", "Only in your skills list."), ("coursework", "Only in your coursework."),
               ("certifications", "Only under Certifications."), ("education", "Only in your Education section."),
               ("languages", "Only in your Languages list."), ("awards", "Only under Awards."),
               ("summary", "Only in your summary or headline."), ("contact", "Only in your headline."),
               ("header_footer", "Only in the page header or footer."))
LIST_ADVICE = " Show it in a bullet about real work, if you can."
LIST_ADVICE_KIND = {"cert": " A certification reads best on its own line under Certifications.",
                    "edu": " A diploma or degree belongs under Education.",
                    "lang": " List it under Languages, or show it in a bullet where you used it."}

# Weakness statuses from best to worst. A status written in resume.json (meta.addressed) or derived from the
# synthesis lane is a claim; for keyword issues the report checks it against the re-read of the new resume
# and keeps the lower of the two (live tests A24, 6.11).
STATUS_RANK = {"fixed": 3, "improved": 2, "needs_you": 1, "gap": 1, "open": 0}
KW_SCRIPT_IDS = ("KW-001", "KW-002", "KW-005")
KW_CATEGORIES = ("KEYWORD_GAP", "SKILL_UNSUPPORTED")
_QUALIFIER_RE = re.compile(r"(?i)(?:\bcourse ?work\b|\b(?:class|course|school|academic|capstone) projects?\b|"
                           r"\b(?:for|in) (?:a|my|one) (?:class|course)\b|\bintro(?:duction)? to\b|"
                           r"\((?:basic|beginner|some|learning|familiar|class|course)\)|\bcurrently learning\b)")
_EDU_TERM_RE = re.compile(r"(?i)\b(?:diploma|degree|ged|bachelor'?s?|master'?s?|associate'?s?|high school|"
                          r"mba|ph\.?d|b\.?s\.?|b\.?a\.?|m\.?s\.?)\b")
_LANG_TERM_RE = re.compile(r"(?i)\b(?:bilingual|multilingual|fluent|fluency|spanish|french|german|mandarin|"
                           r"cantonese|chinese|arabic|portuguese|japanese|korean|vietnamese|hindi|russian|"
                           r"italian|tagalog|asl|sign language)\b")
NO_REAL_GAP = "The panel didn't flag any gap that wording can't fix."

# Plain line under the verdict strip when the simulated screening band is high but the panel is not
# (live test 5.4).
MIXED_LINE = "The screening check reads the file and keywords; the panel reads the whole story."
HIGH_BANDS = ("Ready to send", "Close")
MIXED_MAX_SHARE = 3.0 / 7.0          # "3 of 7 or lower"

# A name must look like a name: never a headline or a role (live tests A10, A23).
_NOT_A_NAME_RE = re.compile(
    r"(?i)\b(?:aspiring|student|graduate|undergraduate|analyst|intern|internship|engineer|engineering|manager|"
    r"developer|designer|assistant|associate|specialist|coordinator|consultant|candidate|resume|cv|"
    r"curriculum|vitae|scientist|technician|nurse|teacher|officer|director|data|marketing|software|"
    r"professional|seeking|objective|summary|profile|contact|portfolio|experience|education|skills|major|"
    r"university|college|school|inc|llc)\b")

# Internal ids (R#, J#, A:<ISSUE>) must never reach a student (live test A11).
_ANCHOR_TOKEN = r"(?:A:[A-Z]+-[0-9]{3}b?|[RJ][0-9]{1,4}(?:\s*[-\u2013]\s*[RJ]?[0-9]{1,4})?)"
_PAREN_ANCHORS_RE = re.compile(r"\s*[\(\[]\s*(?:(?:see|line|lines|at|in|cf\.?|per)\s+)?" + _ANCHOR_TOKEN +
                               r"(?:\s*(?:,|;|/|&|and|or)\s*" + _ANCHOR_TOKEN + r")*\s*[\)\]]")
_ANCHOR_RE = re.compile(r"(?<![\w:/.\-])(" + _ANCHOR_TOKEN + r")(?![\w\u00b2])(?!\s*(?:=|-?\s*visa\b|squared\b|"
                        r"scores?\b|values?\b|of\s+0?\.\d))")


_LEAD_MARK_RE = re.compile("^\\s*(?:[-*•●▪‣–]|\\[(?:header|footer|text box)\\])\\s+")


class ReportError(Exception):
    """The run is missing what a report needs (the CLI exits 2 with this message)."""


# ----------------------------------------------------------------------------------------------- utils
def _load(path):
    """JSON file or None (missing or unreadable files never stop a report)."""
    if not path or not os.path.isfile(path):
        return None
    try:
        return read_json(path)
    except (OSError, ValueError):
        return None


def _d(x):
    return x if isinstance(x, dict) else {}


def _l(x):
    return x if isinstance(x, list) else []


def _s(x):
    return x.strip() if isinstance(x, str) else ""


def clip(text, n):
    """Trim to n characters at a word boundary, adding an ellipsis when cut."""
    s = re.sub(r"\s+", " ", _s(text))
    if len(s) <= n:
        return s
    cut = s[:n - 1].rsplit(" ", 1)[0].rstrip(" ,;:.")
    return cut + "…"


def first_sentences(text, n):
    """Whole sentences up to n characters (falls back to clip)."""
    s = re.sub(r"\s+", " ", _s(text))
    if len(s) <= n:
        return s
    out = ""
    for sent in re.findall(r"[^.!?]+[.!?]+(?:\s|$)", s):
        if len(out) + len(sent) > n:
            break
        out += sent
    return out.strip() or clip(s, n)


def _mask(node):
    """Mask emails and phone numbers (US and international) in every string."""
    if isinstance(node, dict):
        return dict((k, _mask(v)) for k, v in node.items())
    if isinstance(node, list):
        return [_mask(v) for v in node]
    if isinstance(node, str):
        s = mask_contact(node)
        return PHONE_INTL_RE.sub(lambda m: "***-***-" + re.sub(r"\D", "", m.group(0))[-4:], s)
    return node


def _same_text(a, b):
    na, nb = norm_for_match(a).rstrip(".!"), norm_for_match(b).rstrip(".!")
    return bool(na) and (na == nb or na in nb or nb in na)


def short_quote(text, words=6):
    """A few words of a line for display: lead marks dropped, '…' when cut."""
    s = re.sub(r"\s+", " ", _LEAD_MARK_RE.sub("", _s(text))).strip()
    parts = s.split(" ")
    if len(parts) <= words:
        return s.rstrip(" ,;:")
    return " ".join(parts[:words]).rstrip(" ,;:.") + "…"


def deanchor(text, lines=None, titles=None):
    """Replace internal ids in display text (live test A11): a parenthesized id list is removed; a bare R#
    or J# becomes a short quote of that line (from ledger.json), a bare A:<ISSUE> the screening issue's title
    in quotes; an id with nothing to quote is removed. `lines` maps R#/J# ids to their text and `titles`
    maps screening issue ids to titles."""
    s = _s(text)
    if not s or not re.search(r"[RJ][0-9]|A:[A-Z]", s):
        return s
    lines = lines or {}
    titles = titles or {}
    s = _PAREN_ANCHORS_RE.sub("", s)

    def repl(m):
        tok = m.group(1)
        if tok.startswith("A:"):
            title = _s(titles.get(tok[2:]))
            return "“%s”" % title.rstrip(".") if title else ""
        first = re.match(r"[RJ][0-9]+", tok).group(0)
        line = lines.get(first)
        return "“%s”" % short_quote(line) if _s(line) else ""
    s = _ANCHOR_RE.sub(repl, s)
    s = re.sub(r"\(\s*\)|\[\s*\]", "", s)
    s = re.sub(r"\s+([,.;:!?])", r"\1", s)
    s = re.sub(r"([,;:])\1+", r"\1", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return re.sub(r"^[,;:]\s*", "", s)


def plausible_name(value):
    """The value when it looks like a person's name (2 to 5 words, no digits, no role or headline words),
    else '' so the report omits the name rather than show a wrong one."""
    s = re.sub(r"\s+", " ", _s(value))
    if not s or len(s) > 60 or re.search(r"[0-9@/|:]", s):
        return ""
    words = s.split(" ")
    if not 2 <= len(words) <= 5 or _NOT_A_NAME_RE.search(s):
        return ""
    return s


# ----------------------------------------------------------------------------------------------- inputs
class Inputs(object):
    """Everything the report reads, loaded once."""

    def __init__(self, run):
        self.run = run
        self.p = hprun.paths(run)
        self.state = hprun.load_state(run)
        self.before = _load(self.p["screening"])
        if not isinstance(self.before, dict):
            raise ReportError("work/screening/before/screening.json is missing; run init first")
        self.synthesis = _load(self.p["synthesis"])
        if not isinstance(self.synthesis, dict) or not isinstance(self.synthesis.get("issues"), list):
            raise ReportError("work/synthesis.json is missing; run the panel and synthesize first")
        self.ledger = _d(_load(self.p["ledger"]))
        self.answers = _load(self.p["answers"])
        self.resume = _load(self.p["resume_json"])
        self.truth = _load(self.p["truth"])
        self.provenance = _load(self.p["provenance"])
        self.gate = _load(self.p["gate"])
        self.recheck = _load(os.path.join(self.p["recheck"], "work", "synthesis.json"))
        steps = _d(self.state.get("steps"))
        self.stage = "final" if ("render" in steps and isinstance(self.resume, dict)
                                 and isinstance(self.gate, dict)) else "panel"
        self.issues = [i for i in self.synthesis["issues"] if isinstance(i, dict) and _s(i.get("id"))]
        self.issue_by_id = dict((i["id"], i) for i in self.issues)
        self.script_issues = dict((_s(i.get("id")), i) for i in _l(self.before.get("issues"))
                                  if isinstance(i, dict))
        self.notes = []
        self.line_text = {}
        for key in ("resume_lines", "jd_items"):
            for r in _l(self.ledger.get(key)):
                if isinstance(r, dict) and _s(r.get("id")) and _s(r.get("text")):
                    self.line_text[_s(r["id"])] = _s(r["text"])
        self.script_titles = dict((k, _s(v.get("title"))) for k, v in self.script_issues.items())
        self.addressed = self._addressed()
        self.overridden = set()          # issue ids whose claimed status the re-check lowered

    def da(self, text):
        """Display text with internal R#/J#/A: ids replaced (deanchor)."""
        return deanchor(text, self.line_text, self.script_titles)

    def _addressed(self):
        """resume.json meta.addressed, keyed by issue id; unknown ids are ignored and noted."""
        out = {}
        if self.stage != "final":
            return out
        for a in _l(_d(_d(self.resume).get("meta")).get("addressed")):
            if not isinstance(a, dict):
                continue
            iid = _s(a.get("issue_id"))
            if iid not in self.issue_by_id:
                self.notes.append("meta.addressed names %s, which is not a synthesis issue; ignored" % (iid or "?"))
                continue
            st = _s(a.get("status"))
            if st in ("fixed", "improved", "needs_you", "gap"):      # "improved" if rewrite-rules ever allow it
                out[iid] = {"status": st, "note": clip(self.da(a.get("note")), 140)}
        return out

    def new_resume_text(self):
        """The rendered resume .md (normalized for matching), or '' before render."""
        if not hasattr(self, "_new_text"):
            name = _s(_d(_d(self.gate).get("files")).get("md"))
            text = ""
            if name and os.path.isfile(os.path.join(self.run, name)):
                try:
                    with open(os.path.join(self.run, name), "r", encoding="utf-8") as f:
                        text = f.read()
                except OSError:
                    text = ""
            self._new_text = norm_for_match(re.sub(r"[\\*_#|=]", " ", text))
        return self._new_text

    def answered(self):
        """Answers with status 'answered' (Q id -> answer dict)."""
        out = {}
        for a in _l(_d(self.answers).get("answers")):
            if isinstance(a, dict) and a.get("status") == "answered" and _s(a.get("id")):
                out[a["id"]] = a
        return out

    def keyword_answers(self):
        """term (normalized) -> yes|some|no from the combined keyword question."""
        out = {}
        for a in _l(_d(self.answers).get("answers")):
            if not isinstance(a, dict) or a.get("kind") != "keywords" or a.get("status") != "answered":
                continue
            for it in _l(a.get("items")):
                if isinstance(it, dict) and _s(it.get("term")) and it.get("answer") in ("yes", "some", "no"):
                    out[norm_for_match(it["term"])] = it["answer"]
        return out

    def after_screening(self):
        """(screening dict, 'docx'|'pdf') from the gate's re-read, or (None, None)."""
        if self.stage != "final":
            return None, None
        if not hasattr(self, "_after"):
            self._after = (None, None)
            for kind in ("docx", "pdf"):
                data = _load(os.path.join(self.p["after"], kind, "screening.json"))
                if isinstance(data, dict) and isinstance(data.get("scores"), dict):
                    self._after = (data, kind)
                    break
        return self._after


# ----------------------------------------------------------------------------------------------- pieces
def screening_side(scr):
    """One side of report.screening from a screening.json dict."""
    sc = _d(scr.get("scores"))

    def bv(name):
        v = _d(sc.get(name))
        return {"value": v.get("value") if isinstance(v.get("value"), int) else None, "band": _s(v.get("band"))}
    cov = _d(_d(scr.get("keywords")).get("coverage"))
    status = _d(scr.get("keywords")).get("status")
    if status in ("checked", "thin_jd") and cov.get("basis") == "all_terms":
        req = {"found": int(cov.get("basis_found") or 0), "total": int(cov.get("basis_total") or 0),
               "listed_only": int(cov.get("basis_listed_only") or 0), "label": "Job terms"}
    elif status in ("checked", "thin_jd"):
        req = {"found": int(cov.get("required_found") or 0), "total": int(cov.get("required_total") or 0),
               "listed_only": int(cov.get("required_listed_only") or 0), "label": "Required terms"}
    else:
        req = {"found": 0, "total": 0, "listed_only": 0, "label": "Required terms"}
    overall = bv("overall")
    return {"overall": overall["value"], "band": overall["band"], "machine_readability": bv("parse_safety"),
            "keyword_match": bv("keyword_match"), "content_signals": bv("content_signals"), "required": req}


# ----------------------------------------------------------------------------------------------- keywords
def kw_rows(scr, groups=("required", "preferred", "other")):
    """[(group, row)] from a screening dict's keyword table ([] when the keyword check did not run)."""
    kw = _d(_d(scr).get("keywords"))
    if kw.get("status") not in ("checked", "thin_jd"):
        return []
    return [(g, r) for g in groups for r in _l(kw.get(g)) if isinstance(r, dict) and _s(r.get("term"))]


def _kw_kind(row):
    """cert | edu | lang | soft | other: decides the gap wording (you hold a certification, have a diploma,
    speak a language, show a soft skill through an example, use a tool)."""
    name = "%s %s" % (_s(row.get("term")), _s(row.get("canonical")))
    if row.get("kind") == "cert":
        return "cert"
    if _EDU_TERM_RE.search(name):
        return "edu"
    if _LANG_TERM_RE.search(name):
        return "lang"
    return "soft" if row.get("kind") == "soft" else "other"


def _proper_place(row):
    """A certification under Certifications, a diploma under Education or a language under Languages is
    shown where it belongs: 'listed' there is not a weakness."""
    locs = set(x for x in _l(row.get("resume_locations")) if isinstance(x, str))
    kind = _kw_kind(row)
    return ((kind == "cert" and bool(locs & {"certifications", "education"}))
            or (kind == "edu" and "education" in locs) or (kind == "lang" and "languages" in locs))


def _qualified(row):
    """True when the best place the term appears marks it as coursework or a class project."""
    snips = [_s(x) for x in _l(row.get("snippets")) if _s(x)]
    return bool(_QUALIFIER_RE.search(snips[0] if snips else _s(row.get("resume_wording"))))


def term_state(row):
    """'shown' (in a bullet about real work, or a certification, diploma or language in its own section),
    'listed' (only in a list or headline, or marked as coursework or a class project) or 'missing'."""
    if not isinstance(row, dict) or row.get("found") is not True:
        return "missing"
    if row.get("evidence_level") == "demonstrated" or _proper_place(row):
        return "listed" if _qualified(row) else "shown"
    return "listed"


STATE_RANK = {"missing": 0, "listed": 1, "shown": 2}


def _alternative(row, rows):
    """For a missing term from an "X or Y" requirement (or a "X/Y" pair) in the same posting sentence: the
    found row of its alternative, else None. One alternative is enough ("High school diploma or GED")."""
    if row.get("found") is True:
        return None
    q = norm_for_match(row.get("jd_quote"))
    t = re.escape(norm_for_match(row.get("term")))
    if not q or not t:
        return None
    for other in rows:
        if other is row or other.get("found") is not True:
            continue
        o = re.escape(norm_for_match(other.get("term")))
        if o and re.search(r"(?:^|\W)(?:%s\s*(?:,?\s+or|/)\s*%s|%s\s*(?:,?\s+or|/)\s*%s)(?:\W|$)" % (o, t, t, o), q):
            return other
    return None


def state_with_alternatives(row, rows):
    """term_state, but a missing term whose alternative was found takes the alternative's state."""
    st = term_state(row)
    if st == "missing":
        alt = _alternative(row, rows)
        if alt is not None:
            return term_state(alt)
    return st


def _term_in(text, row):
    """True when the term (or its dictionary name) appears as whole words in text."""
    t = norm_for_match(text)
    for name in (_s(row.get("term")), _s(row.get("canonical"))):
        n = norm_for_match(name)
        if len(n) >= 2 and re.search(r"(?:^|\W)%s(?:\W|$)" % re.escape(n), t):
            return True
    return False


def issue_terms(issue, inp):
    """The posting terms a keyword issue is about (before-screening rows), or [] for any other issue.
    Script issues give their terms by id (KW-001 missing required, KW-002 listed only, KW-005 missing
    preferred); a reviewer's KEYWORD_GAP/SKILL_UNSUPPORTED issue names them in its title (else detail)."""
    rows = kw_rows(inp.before, ("required", "preferred"))
    ids = [i for i in _script_ids(issue) if i in KW_SCRIPT_IDS]
    out = []
    for g, r in rows:
        if ("KW-001" in ids and g == "required" and r.get("found") is not True) \
                or ("KW-005" in ids and g == "preferred" and r.get("found") is not True) \
                or ("KW-002" in ids and r.get("found") is True and term_state(r) == "listed"):
            out.append(r)
    if out or ids or not set(_l(issue.get("categories"))) & set(KW_CATEGORIES):
        return out
    for field in ("title", "detail"):
        out = [r for _g, r in kw_rows(inp.before) if _term_in(issue.get(field), r)]
        if out:
            return out
    return []


def verify_keyword_issue(issue, inp):
    """(status, recheck_text) for a keyword issue from the re-read of the new resume, or (None, '') when
    the issue is not about posting terms or there is no re-read. fixed: every term now shown; improved:
    at least one term moved up (missing -> listed or shown, listed -> shown); otherwise needs_you, or gap
    when every term still missing is one the student said they do not have."""
    after, _kind = inp.after_screening()
    terms = issue_terms(issue, inp)
    if not after or not terms:
        return None, ""
    a_rows = [r for _g, r in kw_rows(after)]
    a_by = dict((norm_for_match(r["term"]), r) for r in a_rows)
    b_rows = [r for _g, r in kw_rows(inp.before)]
    answers = inp.keyword_answers()
    states, seen = [], set()
    for r in terms:
        ar = a_by.get(norm_for_match(r["term"]))
        if ar is None:
            continue                     # the term is not in the re-read's table: nothing to check against
        shown_row = ar
        if term_state(ar) == "missing":
            shown_row = _alternative(ar, a_rows) or ar      # "diploma or GED": name the one that was found
        name = _s(shown_row.get("term"))
        if norm_for_match(name) in seen:
            continue
        seen.add(norm_for_match(name))
        a_state = term_state(shown_row)
        qualified = a_state == "listed" and shown_row.get("found") is True and _qualified(shown_row)
        states.append((name, state_with_alternatives(r, b_rows), a_state, qualified))
    if not states:
        return None, ""
    shown = [t for t, _b, a, _q in states if a == "shown"]
    course = [t for t, _b, a, q in states if a == "listed" and q]
    listed = [t for t, _b, a, q in states if a == "listed" and not q]
    missing = [t for t, _b, a, _q in states if a == "missing"]
    if not listed and not missing and not course:
        return "fixed", ""
    parts = []
    if shown:
        parts.append("%s now shown" % _join_terms(shown))
    if course:
        parts.append("%s shown as coursework or a class project" % _join_terms(course))
    if listed:
        parts.append("%s only listed, not shown in your work" % _join_terms(listed))
    if missing:
        parts.append("%s still not found" % _join_terms(missing))
    text = "Re-check of the new resume: %s." % "; ".join(parts)
    if any(STATE_RANK[a] > STATE_RANK[b] for _t, b, a, _q in states):
        return "improved", text
    if missing and not listed and not course and \
            all(answers.get(norm_for_match(t)) == "no" for t in missing):
        return "gap", text
    return "needs_you", text


def _join_terms(terms, n=3):
    terms = [_s(t) for t in terms if _s(t)]
    head = ", ".join(terms[:n])
    return head + (" and %d more" % (len(terms) - n) if len(terms) > n else "")


def _quote_of(issue):
    """The best evidence quote: a resume line first, then a posting line, then the script's evidence."""
    ev = [e for e in _l(issue.get("evidence")) if isinstance(e, dict) and _s(e.get("quote"))]
    for prefix in ("R", "J", "A:"):
        for e in ev:
            a = _s(e.get("anchor"))
            if a.startswith(prefix) and (prefix == "A:" or a[1:].isdigit()):
                return clip(_LEAD_MARK_RE.sub("", e["quote"]), 160)
    return ""


def _script_ids(issue):
    return [_s(e.get("anchor"))[2:] for e in _l(issue.get("evidence"))
            if isinstance(e, dict) and _s(e.get("anchor")).startswith("A:")]


def _why(issue, inp):
    """Why it matters: the reviewers' detail, or the script's reason when the detail repeats the title."""
    title = _s(issue.get("title"))
    for cand in [issue.get("detail")] + [_d(inp.script_issues.get(i)).get("why_it_matters")
                                          for i in _script_ids(issue)]:
        c = inp.da(cand)
        if c and not _same_text(c, title):
            return first_sentences(c, 200)
    return ""


def _suggestion(issue, inp):
    """The issue's first concrete fix (reviewer suggestion, else the script's fix, else its question)."""
    for f in _l(issue.get("fixes")):
        if isinstance(f, dict) and _s(f.get("suggestion")):
            return first_sentences(inp.da(f["suggestion"]), 200)
    for iid in _script_ids(issue):
        fx = _s(_d(inp.script_issues.get(iid)).get("fix"))
        if fx:
            return first_sentences(fx, 200)
    for f in _l(issue.get("fixes")):
        if isinstance(f, dict) and _s(f.get("candidate_question")):
            return "Tell us in chat: " + clip(inp.da(f["candidate_question"]), 180)
    if issue.get("lane") == "real_gap":
        return GAP_ROUTE
    return ""


def _linked_questions(issue, inp):
    """Questions the synthesis linked to this issue (candidate_question fields and questions_for_candidate)."""
    qs = [_s(f.get("candidate_question")) for f in _l(issue.get("fixes"))
          if isinstance(f, dict) and _s(f.get("candidate_question"))]
    for q in _l(inp.synthesis.get("questions_for_candidate")):
        if isinstance(q, dict) and issue.get("id") in _l(q.get("issue_ids")) and _s(q.get("question")):
            qs.append(_s(q["question"]))
    return qs


def _tokens(s):
    return set(w for w in re.findall(r"[a-z0-9]+", norm_for_match(s)) if len(w) > 2)


def _question_answered(question, answered):
    """True when an answered Q# asks substantially the same thing (most content words shared)."""
    qt = _tokens(question)
    if not qt:
        return False
    for a in answered.values():
        at = _tokens(a.get("question"))
        if at and len(qt & at) >= 0.6 * min(len(qt), len(at)):
            return True
    return False


def _cut_refs(inp):
    """R numbers the rewrite lists in meta.cuts (ranges like R12-R14 expanded)."""
    out = set()
    for c in _l(_d(_d(inp.resume).get("meta")).get("cuts")):
        m = re.match(r"^R(\d+)(?:-R?(\d+))?$", _s(_d(c).get("ref")))
        if m:
            a = int(m.group(1))
            b = int(m.group(2) or a)
            out.update(range(a, min(b, a + 200) + 1))
    return out


def cut_away(issue, inp):
    """True when every resume line the issue quotes was cut from the new resume and none of the quoted
    words survive in it: the flagged wording is gone."""
    if inp.stage != "final":
        return False
    ev = [e for e in _l(issue.get("evidence")) if isinstance(e, dict) and re.match(r"^R\d+$", _s(e.get("anchor")))]
    if not ev:
        return False
    cuts = _cut_refs(inp)
    if not all(int(e["anchor"][1:]) in cuts for e in ev):
        return False
    text = inp.new_resume_text()
    return bool(text) and not any(norm_for_match(_LEAD_MARK_RE.sub("", _s(e.get("quote")))) in text
                                  for e in ev if _s(e.get("quote")))


def claimed_status(issue, inp):
    """The status the rewrite claims: meta.addressed, else 'fixed' when the flagged lines were cut, else the
    synthesis lane (a needs-you issue counts as fixed once every linked question was answered)."""
    if inp.stage != "final":
        return "open"
    if issue["id"] in inp.addressed:
        return inp.addressed[issue["id"]]["status"]
    if cut_away(issue, inp):
        return "fixed"
    st = LANE_STATUS.get(issue.get("lane"), "open")
    if st == "needs_you":
        qs = _linked_questions(issue, inp)
        answered = inp.answered()
        if qs and answered and all(_question_answered(q, answered) for q in qs):
            return "fixed"
    return st


def weakness_status_and_check(issue, inp):
    """(status, recheck_text, overridden). For keyword issues the claim is checked against the re-read of
    the new resume and the lower of the two wins; a claim is never raised by the re-check."""
    claimed = claimed_status(issue, inp)
    if inp.stage != "final":
        return claimed, "", False
    verified, text = verify_keyword_issue(issue, inp)
    if verified is None or STATUS_RANK.get(verified, 0) >= STATUS_RANK.get(claimed, 0):
        return claimed, (text if verified is not None and verified != "fixed" else ""), False
    return verified, text, True


def weakness_status(issue, inp):
    return weakness_status_and_check(issue, inp)[0]


def weaknesses(inp):
    out = []
    for issue in inp.issues:
        flagged = [r for r in _l(issue.get("reviewers")) if r in REVIEWER_IDS]
        status, recheck, overridden = weakness_status_and_check(issue, inp)
        claim = inp.addressed.get(issue["id"], {})
        fix = claim.get("note") if inp.stage == "final" else ""
        if not fix and issue["id"] not in inp.addressed and cut_away(issue, inp):
            fix = CUT_NOTE
        if overridden:
            inp.overridden.add(issue["id"])
            inp.notes.append("%s: the rewrite marked it %s, but %s Shown as %s." % (
                issue["id"], claimed_status(issue, inp).replace("_", " "), recheck[0].lower() + recheck[1:],
                status.replace("_", " ")))
        if recheck and (overridden or status != "fixed"):
            fix = recheck + ((" " + fix) if fix and not overridden else "")
        sev = issue.get("severity") if issue.get("severity") in ("critical", "major", "moderate", "minor") \
            else "minor"
        out.append({
            "rank": issue.get("rank") if isinstance(issue.get("rank"), int) and issue["rank"] >= 1 else len(out) + 1,
            "issue_id": issue["id"],
            "title": clip(inp.da(issue.get("title")), 90),
            "severity": sev,
            "flagged_by": flagged,
            "flagged_count": len(flagged),
            "from_script": bool(issue.get("from_script")),
            "why": _why(issue, inp),
            "evidence_quote": _quote_of(issue),
            "status": status,
            "fix": fix or _suggestion(issue, inp),
        })
    return out


def pinned(inp):
    out = []
    for iid in _l(inp.synthesis.get("pinned_integrity")):
        issue = inp.issue_by_id.get(iid)
        if not issue:
            continue
        fix = ""
        if inp.stage == "final" and iid in inp.addressed:
            fix = inp.addressed[iid]["note"]
        elif cut_away(issue, inp):
            fix = CUT_NOTE
        out.append({"issue_id": iid, "title": clip(inp.da(issue.get("title")), 90),
                    "fix": fix or _suggestion(issue, inp) or "Check this line and keep only what you can explain "
                                                                "in an interview."})
    return out


def _entry_label(resume, bullet_id):
    """'Projects: Campus Coffee Pricing Survey' for a bullet id (or the section title)."""
    for sec in _l(_d(resume).get("sections")):
        if not isinstance(sec, dict):
            continue
        for it in _l(sec.get("items")):
            if not isinstance(it, dict):
                continue
            ids = [_s(b.get("id")) for b in _l(it.get("bullets")) if isinstance(b, dict)]
            if bullet_id in ids or _s(it.get("id")) == bullet_id:
                name = _s(it.get("org")) or _s(it.get("name")) or _s(it.get("school")) or _s(it.get("role"))
                title = _s(sec.get("title")) or _s(sec.get("type")).title()
                return clip("%s: %s" % (title, name) if name else title, 60)
    return "Your resume"


def needs_you(inp, weak):
    out = []
    if inp.stage != "final":
        # The synthesis already turns the screening's keyword issues into yes/some/no questions.
        for q in _l(inp.synthesis.get("questions_for_candidate")):
            if not isinstance(q, dict) or not _s(q.get("question")):
                continue
            ids = [i for i in _l(q.get("issue_ids")) if i in inp.issue_by_id]
            where = clip(inp.da(inp.issue_by_id[ids[0]].get("title")), 60) if ids else "Your resume"
            out.append({"where": where, "ask": clip(inp.da(q["question"]), 200)})
        return out[:7]
    resume = _d(inp.resume)
    for pid, ph in sorted(_d(resume.get("placeholders")).items()):
        if not isinstance(ph, dict) or ph.get("status") == "answered" and _s(ph.get("value")):
            continue
        if _s(ph.get("ask")):
            out.append({"where": _entry_label(resume, _s(ph.get("bullet"))), "ask": clip(inp.da(ph["ask"]), 200)})
    for w in weak:
        if w["status"] != "needs_you":
            continue
        issue = inp.issue_by_id.get(w["issue_id"]) or {}
        a = inp.addressed.get(w["issue_id"])
        ask = a["note"] if a and a["note"] else ""
        if w["issue_id"] in inp.overridden:
            ask = w["fix"]                # the re-check, never the claim it overrode
        if not ask:
            qs = _linked_questions(issue, inp)
            ask = clip(inp.da(qs[0]), 200) if qs else w["fix"]
        if ask:
            out.append({"where": clip(w["title"], 60), "ask": ask})
    seen, uniq = set(), []
    for x in out:
        k = norm_for_match(x["ask"])
        if k not in seen:
            seen.add(k)
            uniq.append(x)
    return uniq


def has_real_gap(issue):
    """synthesis issues[].has_real_gap when the synthesis wrote it, else whether any reviewer's fix for the
    issue is fix_type real_gap (a merged issue keeps its members' real-gap fixes)."""
    flag = issue.get("has_real_gap")
    if isinstance(flag, bool):
        return flag
    return issue.get("lane") == "real_gap" or any(isinstance(f, dict) and f.get("fix_type") == "real_gap"
                                                  for f in _l(issue.get("fixes")))


_BARE_DONT_RE = re.compile(r"(?i)^(?:do not|don't|never|avoid)\b[^.!?]*\b(?:these|them|this|that|it|those)\b[^.!?]*[.!]$")


def _route_text(text):
    """A reviewer's real-gap advice without a leading "Do not add these." whose 'these' points at the
    reviewer's own context: the report's heading already says wording cannot fix it."""
    sents = re.findall(r"[^.!?]+[.!?]+(?:\s+|$)", _s(text)) or [_s(text)]
    while len(sents) > 1 and _BARE_DONT_RE.match(sents[0].strip()):
        sents = sents[1:]
    return "".join(sents).strip()


def real_gaps(inp, weak=None):
    """Every issue a reviewer marked as a real gap (has_real_gap), every issue the rewrite marked gap in
    meta.addressed, and every keyword issue the re-check left as a gap (live tests 4.3, 6.12)."""
    status = dict((w["issue_id"], w["status"]) for w in (weak or []))
    out = []
    for issue in inp.issues:
        a = inp.addressed.get(issue["id"]) if inp.stage == "final" else None
        claimed_gap = bool(a) and a["status"] == "gap"
        if not (has_real_gap(issue) or claimed_gap or status.get(issue["id"]) == "gap"):
            continue
        route = a["note"] if claimed_gap and a["note"] else ""
        if not route:
            for f in _l(issue.get("fixes")):
                if isinstance(f, dict) and f.get("fix_type") == "real_gap" and _s(f.get("suggestion")):
                    route = first_sentences(_route_text(inp.da(f["suggestion"])), 200)
                    break
        out.append({"title": clip(inp.da(issue.get("title")), 90), "honest_route": route or GAP_ROUTE})
    return out


def _listed_note(row, ans=None):
    """Where a listed-only term sits, in plain words (live test 6.9: 'only in skills list' must be true)."""
    if _qualified(row):
        return KW_QUALIFIED
    if ans == "some":
        return KW_SOME
    locs = [x for x in _l(row.get("resume_locations")) if isinstance(x, str)]
    places = dict(LIST_PLACES)
    advice = LIST_ADVICE_KIND.get(_kw_kind(row), LIST_ADVICE)
    for loc in locs:
        if loc in places:
            return places[loc] + advice
    return "Only listed, not shown in a bullet about your work." + advice


def _gap_note(row, group, ans):
    g = "required" if group == "required" else "other"
    if ans == "no":
        return KW_NOTES[("gap", g, "no")]
    if ans == "yes":
        return KW_YES_NOT_FOUND
    if ans == "some":
        return KW_SOME
    return KW_GAP_NOTES.get((_kw_kind(row), g)) or KW_NOTES[("gap", g, None)]


KW_ORDER = {"gap": 0, "listed_only": 1, "added_with_evidence": 2}


def keyword_gaps(inp, after):
    """Up to 6 posting terms with an honest status and a templated note: required terms first, then
    preferred; within each, gaps, then listed-only terms, then terms the rewrite added with evidence.
    At the final stage the statuses come from the re-read of the NEW resume (live test 6.9), so a term
    the new resume shows is never listed as a gap. A missing term whose "X or Y" alternative was found
    is not a gap."""
    if inp.state.get("general_review"):
        return []
    if _d(inp.before.get("keywords")).get("status") != "checked":
        return []
    answers = inp.keyword_answers()
    b_list = kw_rows(inp.before, ("required", "preferred"))
    b_all = [r for _g, r in b_list]
    b_by = dict((norm_for_match(r["term"]), r) for r in b_all)
    final = inp.stage == "final" and isinstance(after, dict) and \
        _d(after.get("keywords")).get("status") == "checked"
    truth_ok = isinstance(inp.truth, dict) and inp.truth.get("passed") is True
    rows = kw_rows(after, ("required", "preferred")) if final else b_list
    all_rows = [r for _g, r in rows]
    out = []
    for group, r in rows:
        key = norm_for_match(r["term"])
        alt = _alternative(r, all_rows)
        if alt is not None:
            continue                                   # "High school diploma or GED": one is enough
        ans = answers.get(key)
        st = term_state(r)
        if final:
            br = b_by.get(key)
            before_st = state_with_alternatives(br, b_all) if br else "missing"
            if st == "shown":
                if before_st == "shown" or not truth_ok:
                    continue
                status, note = "added_with_evidence", KW_NOTES[("added_with_evidence", None, None)]
            elif st == "listed":
                status, note = "listed_only", _listed_note(r, ans)
            else:
                status, note = "gap", _gap_note(r, group, ans)
        else:
            if st == "shown":
                continue
            status = "listed_only" if st == "listed" else "gap"
            note = _listed_note(r, ans) if st == "listed" else _gap_note(r, group, ans)
        out.append((0 if group == "required" else 1, KW_ORDER[status], len(out),
                    {"term": clip(r["term"], 60), "status": status, "note": note}))
    return [x[3] for x in sorted(out)][:6]


def knockouts(inp):
    rank = {"appears_unmet": 0, "unclear": 1, "not_on_resume_by_design": 2}
    rows = [k for k in _l(inp.before.get("knockout_signals"))
            if isinstance(k, dict) and k.get("status") in rank and _s(k.get("jd_quote"))]
    rows = sorted(enumerate(rows), key=lambda t: (rank[t[1]["status"]], t[0]))
    return [{"type": _s(k.get("type")).replace("_", " "), "jd_quote": clip(k.get("jd_quote"), 200),
             "advice": clip(k.get("advice"), 240)} for _, k in rows[:4]]


def panel_rows(synth, da=None):
    from hp.panel.common import REVIEWER_INFO
    da = da or _s
    rows = []
    for r in _l(_d(synth).get("reviewers")):
        if not isinstance(r, dict) or r.get("id") not in REVIEWER_IDS:
            continue
        rid = r["id"]
        rows.append({"id": rid, "name": REVIEWER_INFO[rid]["name"], "lens": clip(REVIEWER_INFO[rid]["lens"], 60),
                     "verdict": r.get("verdict"), "advance": r.get("advance") if r.get("advance") in
                     ("yes", "no", "unsure") else "unsure", "take": clip(da(r.get("one_line_take")), 200)})
    return rows


def vote_label(synth):
    v = _d(_d(synth).get("panel_vote"))
    total = v.get("total") if isinstance(v.get("total"), int) else 0
    yes = v.get("advance") if isinstance(v.get("advance"), int) else 0
    if total <= 0:
        return "No reviewer finished, so there is no vote"
    return "%d of %d would move you forward" % (yes, total)


def closest_to_reject(inp):
    """synthesis.closest_to_reject plus the reviewer's display name and the issue's severity, or None.
    A synthesis.json written before the field existed gets the same rule applied here."""
    from hp.panel.common import REVIEWER_INFO, VERDICTS
    synth = inp.synthesis
    if "closest_to_reject" in synth:
        c = synth.get("closest_to_reject")
    else:
        from hp.panel.synth import closest_to_reject as compute
        c = compute(_l(synth.get("reviewers")), inp.issues)
    if not isinstance(c, dict) or c.get("reviewer") not in REVIEWER_IDS or c.get("verdict") not in VERDICTS:
        return None
    issue = inp.issue_by_id.get(_s(c.get("issue_id")))
    sev = issue.get("severity") if issue and issue.get("severity") in ("critical", "major", "moderate", "minor") \
        else None
    reason = clip(_LEAD_MARK_RE.sub("", inp.da(c.get("reason"))), 120) or (clip(inp.da(issue.get("title")), 120)
                                                                           if issue else "")
    return {"reviewer": c["reviewer"], "name": REVIEWER_INFO[c["reviewer"]]["name"], "verdict": c["verdict"],
            "issue_id": issue["id"] if issue else None, "severity": sev, "reason": reason}


def strong_resume(inp):
    """True only when at least STRONG_MIN_YES reviewers would move the resume forward and the panel found
    no critical or major issue and nothing to fix before sending (ARCHITECTURE.md section 17.4)."""
    v = _d(inp.synthesis.get("panel_vote"))
    yes = v.get("advance") if isinstance(v.get("advance"), int) and not isinstance(v.get("advance"), bool) else 0
    total = v.get("total") if isinstance(v.get("total"), int) and not isinstance(v.get("total"), bool) else 0
    if yes < STRONG_MIN_YES or total < yes:
        return False
    if any(i.get("severity") in ("critical", "major") for i in inp.issues):
        return False
    return not _l(inp.synthesis.get("pinned_integrity"))


def strong_line(strong, closest):
    """The verdict strip's plain strong-resume line (a fixed template), or '' when the resume is not strong."""
    if not strong or not isinstance(closest, dict):
        return ""
    reason = re.sub(r"[\s.,;:]+$", "", _s(closest.get("reason")))
    if reason and reason[-1] not in "?!":
        reason += "."
    sev = closest.get("severity")
    if closest.get("issue_id") and sev in ("moderate", "minor"):
        held = "It still held because that is a %s issue, not a critical or major one." % sev
    else:
        held = "It still held because no reviewer found a critical or major issue."
    who = "The %s came closest to saying no" % closest.get("name")
    return "Strong resume. %s. %s" % (who, held) if not reason else "Strong resume. %s: %s %s" % (who, reason, held)


def _cap_words(s, n, keep=12):
    """At most n words, cut at the last sentence end (else clause break) that keeps at least `keep` words."""
    words = s.split()
    if len(words) <= n:
        return s
    head = words[:n]
    for i in range(n - 1, keep - 2, -1):
        if head[i][-1] in ".!?":
            return " ".join(head[:i + 1])
    for i in range(n - 1, keep - 2, -1):
        if head[i][-1] in ",;:":
            return " ".join(head[:i + 1])[:-1] + "…"
    return " ".join(head).rstrip(",;:") + "…"


def first_impression(inp):
    """The Recruiter's 7-second takeaway (lens_data.seven_second_takeaway), at most 30 words, or None when
    the Recruiter's review is missing, was not accepted by the synthesis, or has no takeaway."""
    from hp.panel.common import MAX_REVIEW_BYTES, clean_str, load_json_file
    if "recruiter" not in [r.get("id") for r in _l(inp.synthesis.get("reviewers")) if isinstance(r, dict)]:
        return None
    raw, err = load_json_file(os.path.join(inp.p["reviews"], "recruiter.json"), MAX_REVIEW_BYTES)
    if err or not isinstance(raw, dict):
        return None
    value = _d(raw.get("lens_data")).get("seven_second_takeaway")
    text = clean_str(value) if isinstance(value, str) else ""
    if len(text) >= 2 and text[0] in _QUOTE_CHARS and text[-1] in _QUOTE_CHARS:
        text = text[1:-1].strip()      # the renderers add their own quotation marks
    return _cap_words(inp.da(text), FIRST_IMPRESSION_WORDS) or None


def disagreements(synth, da=None):
    da = da or _s
    out = []
    for c in _l(_d(synth).get("conflicts"))[:2]:
        if not isinstance(c, dict):
            continue
        sides = []
        for s in _l(c.get("sides")):
            if isinstance(s, dict) and s.get("reviewer") in REVIEWER_IDS:
                side = {"reviewer": s["reviewer"], "view": clip(da(s.get("view")), 200)}
                if _s(s.get("quote")):
                    side["quote"] = clip(_LEAD_MARK_RE.sub("", s["quote"]), 160)
                sides.append(side)
        if sides:
            out.append({"claim": clip(_LEAD_MARK_RE.sub("", da(c.get("claim"))), 200), "sides": sides,
                        "which_matters": clip(da(c.get("which_matters")), 240)})
    return out


def strengths(synth, final=False, da=None):
    """Up to 4 strengths. At the final stage the 'underused: move it up' hint is dropped: it was advice for
    the old resume, and the rewrite already acted on it (live test 6.13)."""
    da = da or _s
    return [{"title": clip(da(s.get("title")), 90),
             "flagged_by": [r for r in _l(s.get("reviewers")) if r in REVIEWER_IDS],
             "underused": bool(s.get("underused")) and not final}
            for s in _l(_d(synth).get("strengths")) if isinstance(s, dict) and _s(s.get("title"))][:4]


def interview_prep(synth, da=None):
    da = da or _s
    return [{"question": clip(da(q.get("question")), 240), "from": q.get("from")}
            for q in _l(_d(synth).get("interview_prep"))
            if isinstance(q, dict) and _s(q.get("question")) and q.get("from") in ("hiring_manager", "skeptic")][:6]


def _bullets(resume):
    for sec in _l(_d(resume).get("sections")):
        if not isinstance(sec, dict):
            continue
        for it in _l(sec.get("items")):
            if not isinstance(it, dict):
                continue
            for b in _l(it.get("bullets")):
                if isinstance(b, dict):
                    yield b


def _first_r(evidence):
    for e in _l(evidence):
        m = re.match(r"^R(\d+)", _s(_d(e).get("ref")))
        if _d(e).get("src") == "orig" and m:
            return int(m.group(1))
    return None


def _ref_text(ref, ledger_text):
    """The words of a cut line or range ("R18-R19" joins both lines; a line ending in a hyphen joins the next
    word, so a wrapped "detail-" / "oriented" reads "detail-oriented")."""
    m = re.match(r"^R(\d+)(?:-R?(\d+))?$", _s(ref))
    if not m:
        return _LEAD_MARK_RE.sub("", ledger_text.get(_s(ref), ""))
    a = int(m.group(1))
    b = min(int(m.group(2) or a), a + 10)
    out = ""
    for n in range(a, b + 1):
        piece = _LEAD_MARK_RE.sub("", ledger_text.get("R%d" % n, "")).strip()
        if not piece:
            continue
        out = (out + piece) if out.endswith("-") or not out else (out + " " + piece)
    return out


def changes(inp):
    """What the rewrite did, counted from resume.json and truth.json (final stage only)."""
    if inp.stage != "final":
        return None
    resume = _d(inp.resume)
    ledger_text = dict((_s(r.get("id")), _s(r.get("text"))) for r in _l(inp.ledger.get("resume_lines"))
                       if isinstance(r, dict))
    rewritten, order = 0, []
    for b in _bullets(resume):
        quotes = [_s(_d(e).get("quote")) for e in _l(b.get("evidence"))]
        quotes += [ledger_text.get(_s(_d(e).get("ref")), "") for e in _l(b.get("evidence"))]
        text = norm_for_match(re.sub(r"\{\{[^}]*\}\}", "", _s(b.get("text")))).lstrip("•-* ")
        same = any(text and text == norm_for_match(q).lstrip("•-* ").rstrip(".") for q in quotes if q)
        if not same or any(op in REWRITE_OPS for op in _l(b.get("ops"))):
            rewritten += 1
    for sec in _l(resume.get("sections")):
        for it in _l(_d(sec).get("items")):
            n = _first_r(_d(it).get("evidence"))
            if n is not None:
                order.append(n)
    reordered = any(b < a for a, b in zip(order, order[1:]))
    stats = _d(_d(inp.truth).get("stats"))
    numbers = stats.get("numbers_from_answers") if isinstance(stats.get("numbers_from_answers"), int) else 0
    cut, seen = [], set()
    for c in _l(_d(resume.get("meta")).get("cuts")):
        if isinstance(c, dict) and _s(c.get("ref")):
            ref = _s(c["ref"])
            seen.add(ref)
            cut.append({"ref": ref, "text": clip(_ref_text(ref, ledger_text), 160),
                        "reason": clip(c.get("reason"), 200) or "Cut to fit the page."})
    for w in _l(_d(inp.truth).get("warnings")):
        if isinstance(w, dict) and w.get("code") == "UNLISTED_CUT" and _s(w.get("bullet_id")) not in seen:
            ref = _s(w["bullet_id"])
            seen.add(ref)
            cut.append({"ref": ref, "text": clip(_LEAD_MARK_RE.sub("", ledger_text.get(ref, "")), 160),
                        "reason": "Left out of the new resume without a stated reason. Add it back if it matters."})
    return {"bullets_rewritten": rewritten, "reordered": reordered, "numbers_from_you": numbers, "cut": cut}


def truth_check(inp, bullets_total):
    if inp.stage != "final" or not isinstance(inp.truth, dict):
        return {"ran": "not_run", "passed": None, "invented_facts": None, "bullets_traced": 0,
                "bullets_total": 0, "provenance": "not_run"}
    from hp.rewrite import check_provenance
    truth = inp.truth
    stats = _d(truth.get("stats"))
    passed = truth.get("passed") is True
    invented = 0 if passed else sum(1 for e in _l(truth.get("errors"))
                                    if isinstance(e, dict) and e.get("code") in FACT_CODES)
    prov = "not_run"
    if isinstance(inp.provenance, dict):
        gate = check_provenance(inp.resume, inp.provenance, truth)
        mode = inp.provenance.get("mode")
        prov = (mode if mode in ("subagent", "self") else "self") if gate.get("passed") else "unresolved"
    total = stats.get("bullets") if isinstance(stats.get("bullets"), int) else bullets_total
    traced = stats.get("bullets_with_evidence") if isinstance(stats.get("bullets_with_evidence"), int) else 0
    return {"ran": "script", "passed": passed, "invented_facts": invented, "bullets_traced": traced,
            "bullets_total": total, "provenance": prov}


def limitations(inp, mode, synth):
    lims = []
    scr_l = [x for x in _l(inp.before.get("limitations")) if _s(x)]
    lims.extend(scr_l)
    lims.append(REVIEWERS_LIMIT)
    missing = [r for r in _l(_d(synth).get("missing_reviewers")) if r in REVIEWER_IDS]
    if missing:
        from hp.panel.common import REVIEWER_INFO
        size = _d(synth).get("panel_size") if isinstance(_d(synth).get("panel_size"), int) else 7 - len(missing)
        lims.append("%s could not finish, so the panel had %d reviewer%s." % (
            ", ".join(REVIEWER_INFO[r]["name"] for r in missing), size, "" if size == 1 else "s"))
    if inp.state.get("general_review"):
        lims.append("No job posting was provided, so job keywords were not checked and reviewers judged "
                    "against the role title only.")
    if _d(inp.state.get("resume_input")).get("text") == "inputs/transcript.txt":
        lims.append("The resume file had no readable text, so its words were transcribed by Claude and confirmed "
                    "by you. Parsing software may read nothing from the original file.")
    if inp.stage == "final" and isinstance(inp.gate, dict) and inp.gate.get("passed") is False:
        fails = [_s(_d(f).get("detail")) for f in _l(inp.gate.get("failures"))][:2]
        lims.append("The quality check on the new files did not fully pass: %s." % "; ".join(f for f in fails if f))
    if mode in ("sequential", "lite"):
        lims.append(MODE_NOTE[mode])
    return lims


def next_steps(inp, report):
    steps = []
    if inp.stage != "final":
        if report["pinned_integrity"]:
            steps.append("Fix what 'Fix before you send' lists before you apply anywhere.")
        steps.append("Answer the questions in chat, or reply skip. Then Claude rebuilds your resume.")
        steps.append("Read the biggest weaknesses first. They are ranked by how much they hurt.")
        return steps[:4]
    steps.append("Read the new resume line by line and fix anything that is not exactly true.")
    if report["needs_you"]:
        steps.append("Fill in what 'Needs you' lists, then save a fresh PDF.")
    if not report["files"].get("resume_pdf"):
        steps.append("Open the .docx in Word, Google Docs or Pages and save it as PDF.")
    if any(k for k in report["knockouts"]):
        steps.append("Expect application questions on the items under 'Application questions to expect', and "
                     "answer them truthfully.")
    if report["interview_prep"]:
        steps.append("Practice the interview questions in the full report out loud before you apply.")
    return steps[:4]


def _files(inp):
    files = {}
    if inp.stage == "final":
        gf = _d(_d(inp.gate).get("files"))
        for key, k in (("resume_docx", "docx"), ("resume_pdf", "pdf"), ("resume_md", "md")):
            name = _s(gf.get(k))
            if name and os.path.isfile(os.path.join(inp.run, name)):
                files[key] = name
    files["report_pdf"] = STEM + ".pdf"
    files["report_md"] = STEM + ".md"
    files["report_html"] = STEM + ".html"
    return files


def _candidate(inp):
    """resume.json basics.name when the rewrite exists; else the screening's name only when it looks like a
    name; else '' (the report omits the name rather than show a headline or role, live tests A10, A23)."""
    name = _s(_d(_d(inp.resume).get("basics")).get("name"))
    if name:
        return clip(name, 80)
    contact = _d(inp.before.get("contact")).get("name")
    if isinstance(contact, dict):
        contact = contact.get("value")
    return clip(plausible_name(contact), 80)


def mixed_line(side, synth):
    """One plain line when the simulated screening band is high (Ready to send / Close) but at most 3 of 7
    reviewers would move the resume forward (live test 5.4); else ''."""
    v = _d(_d(synth).get("panel_vote"))
    yes, total = v.get("advance"), v.get("total")
    if not isinstance(yes, int) or not isinstance(total, int) or isinstance(yes, bool) or total <= 0:
        return ""
    band = _s(_d(side).get("band"))
    if not band.startswith(HIGH_BANDS) or yes > MIXED_MAX_SHARE * total + 1e-9:
        return ""
    return MIXED_LINE


def build_report(run_dir, notes=None):
    """Build and return the report dict for a run (ARCHITECTURE.md section 12). When `notes` is a list,
    plain-text notes about ignored input (for example an unknown meta.addressed issue id) are appended.

    Raises ReportError when the run has no screening or synthesis yet."""
    inp = Inputs(hprun.resolve_run(run_dir))
    synth = inp.synthesis
    mode = synth.get("mode") if synth.get("mode") in hprun.MODES else (inp.state.get("mode") or "parallel")
    size = synth.get("panel_size") if isinstance(synth.get("panel_size"), int) else len(panel_rows(synth))
    after, after_kind = inp.after_screening()
    before_side = screening_side(inp.before)
    after_side = screening_side(after) if after else None
    weak = weaknesses(inp)
    strong, closest = strong_resume(inp), closest_to_reject(inp)
    shown_side = after_side or before_side
    report = {
        "schema_version": REPORT_VERSION,
        "stage": inp.stage,
        "hp_version": __version__,
        "candidate": _candidate(inp),
        "target": {"role": clip(inp.state.get("role"), 120) or "Your target role",
                   "company": clip(inp.state.get("company"), 120) or None},
        "date": inp.state.get("as_of") or "",
        "mode": mode,
        "general_review": bool(inp.state.get("general_review")),
        "mode_note": MODE_NOTE.get(mode, ""),
        "verdict_strip": {
            "vote_label": vote_label(synth),
            "screening_band": shown_side["band"],
            "mode_label": (MODE_LABEL[mode] % size) if "%d" in MODE_LABEL[mode] else MODE_LABEL[mode],
            "strong_line": strong_line(strong, closest),
            "mixed_line": "" if strong else mixed_line(shown_side, synth),
        },
        "strong_resume": strong,
        "closest_to_reject": closest,
        "first_impression": first_impression(inp),
        "pinned_integrity": pinned(inp),
        "weaknesses": weak,
        "changes": changes(inp),
        "needs_you": needs_you(inp, weak),
        "real_gaps": real_gaps(inp, weak),
        "panel": panel_rows(synth, inp.da),
        "panel_after": None,
        "screening": {
            "label": SCREENING_LABEL,
            "method": METHOD,
            "before": before_side,
            "after": after_side,
            "after_source": after_kind,
            "precision_note": _s(_d(inp.before.get("scores")).get("precision_note")),
            "disclaimer": _s(inp.before.get("disclaimer")),
        },
        "disagreements": disagreements(synth, inp.da),
        "keyword_gaps": keyword_gaps(inp, after),
        "strengths": strengths(synth, final=inp.stage == "final", da=inp.da),
        "interview_prep": interview_prep(synth, inp.da),
        "knockouts": knockouts(inp),
        "truth_check": None,
        "limitations": [],
        "next_steps": [],
        "files": _files(inp),
    }
    report["truth_check"] = truth_check(inp, sum(1 for _ in _bullets(inp.resume)))
    if isinstance(inp.recheck, dict) and _l(inp.recheck.get("reviewers")):
        report["panel_after"] = {"vote_label": vote_label(inp.recheck), "rows": panel_rows(inp.recheck),
                                 "note": AFTER_NOTE}
    report["limitations"] = limitations(inp, mode, synth)
    report["next_steps"] = next_steps(inp, report)
    if isinstance(notes, list):
        notes.extend(inp.notes)
    return _mask(report)


def validate_report(report):
    """Check a report against schemas/report.schema.json with the stdlib validator ([] when valid)."""
    from hp.panel.common import schema_path
    from hp.panel.schema_lite import validate
    try:
        schema = read_json(schema_path("report.schema.json"))
    except (OSError, ValueError) as e:
        return ["report.schema.json is unreadable (%s)" % e.__class__.__name__]
    return validate(report, schema)
