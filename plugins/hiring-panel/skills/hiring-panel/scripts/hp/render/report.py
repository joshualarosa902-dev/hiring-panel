"""render_report: report.json -> Hiring_Panel_Report.{pdf,md,html}.

Display order (ARCHITECTURE.md section 12, critic C12), top to bottom:
  1 header + verdict strip (vote, simulated screening check, truth check / next step, mode), then right
    under it the strong-resume line (only when report.json says strong_resume) and the Recruiter's
    7-second first impression
  2 Fix before you send          3 Biggest weaknesses, most serious first (top 5)
  4 What changed / needs you / real gaps (+ next steps)                    5 The panel (7 rows)
  6 Where the panel disagreed     7 Keyword gaps to close honestly          8 What's already working
  9 Interview prep                10 Mode and limitations
The one-page PDF holds 1-5; the .md and .html hold all ten.

Honesty rules enforced here: one number only (the screening Overall, always next to "Simulated
screening check" and the method text); never "ATS score"; no per-reviewer numbers or probabilities;
"0 invented facts" only when truth_check.ran == "script" and passed; sequential/lite/manual runs always
show the approximate-independence disclosure; emails and phone numbers are masked everywhere; the
"Strong resume." line appears only when report.json has strong_resume true (the renderer never decides it).
Clipped text (one-page PDF) prefers whole sentences, then clause and phrase breaks, never half a word.
"""
import html as _html
import os
import re
import shutil
import tempfile

from .. import util
from .. import __version__ as HP_VERSION
from .model import RenderError, clean, as_dict, as_list
from .pdf_builtin import PdfLayout, Unencodable, write_pdf_bytes, wrap_runs, text_width, to_winansi, rgb, pdf_str
from . import pdf_engines

STEM = "Hiring_Panel_Report"
FOOTER = "Hiring Panel v%s · free and open source · not affiliated with Anthropic or any ATS vendor"

REVIEWER_NAMES = {"screening": "Automated Screening Check", "hiring_manager": "Hiring Manager",
                  "recruiter": "Recruiter", "competitor": "Competing Applicant", "ceo": "CEO",
                  "teammate": "Future Teammate", "skeptic": "Skeptic"}
SHORT_NAMES = {"screening": "Screening", "hiring_manager": "Hiring Manager", "recruiter": "Recruiter",
               "competitor": "Competing Applicant", "ceo": "CEO", "teammate": "Teammate", "skeptic": "Skeptic"}
REVIEWER_ORDER = ["screening", "hiring_manager", "recruiter", "competitor", "ceo", "teammate", "skeptic"]

# (label, text color, background)
VERDICTS = {"strong_yes": ("Strong yes", "05603A", "D1FADF"), "lean_yes": ("Lean yes", "067647", "ECFDF3"),
            "borderline": ("Borderline", "93370D", "FEF0C7"), "lean_no": ("Lean no", "B42318", "FEF3F2"),
            "strong_no": ("Strong no", "912018", "FEE4E2")}
ADVANCE = {"yes": ("Yes", "067647"), "unsure": ("Unsure", "B54708"), "no": ("No", "B42318")}
STATUS = {"fixed": ("Fixed", "067647", "ECFDF3"), "improved": ("Improved", "175CD3", "EFF8FF"),
          "needs_you": ("Needs you", "B54708", "FFFAEB"), "gap": ("Real gap", "344054", "F2F4F7"),
          "open": ("Open", "475467", "F2F4F7")}
SEVERITY = {"critical": ("Critical", "B42318"), "major": ("Major", "B54708"), "moderate": ("Moderate", "A15C07"),
            "minor": ("Minor", "667085")}
KW_STATUS = {"gap": ("Gap", "B42318", "FEF3F2"), "listed_only": ("Listed only", "B54708", "FFFAEB"),
             "added_with_evidence": ("Added with evidence", "067647", "ECFDF3")}
PROVENANCE = {"subagent": "A fresh Skeptic reviewer audited the rewrite against your own words.",
              "self": "The audit was done in this same chat, not by a fresh reviewer. Check each line yourself.",
              "unresolved": "The second audit still has open items. Check those lines yourself.",
              "not_run": "No second audit was needed: no bullet used wording beyond its sources."}
INDEPENDENCE_NOTE = {
    "sequential": "One chat played all 7 reviewers in turn, so their views are less independent than 7 "
                  "separate reviewers. Treat the vote as approximate.",
    "lite": "Quick run: one chat played all 7 reviewers in turn using short role cards, so their views are "
            "less independent than 7 separate reviewers. Treat the vote as approximate.",
    "manual": "Python could not run, so Claude did the checks by hand. Treat every result as approximate.",
}

INK, INK2, MUTED, FAINT, LINE, SOFT, ACCENT = "101828", "344054", "667085", "98A2B3", "E4E7EC", "F9FAFB", "1F3A5F"


# ----------------------------------------------------------------------------------------------
# Safe accessors: report.json is trusted to be built by our script, but never trusted to be tidy.
# ----------------------------------------------------------------------------------------------
_ATS_SCORE_RE = re.compile(r"(?i)\bATS\s+score\b")
# Safety net for internal ids (live test A11). report_build already swaps them for short quotes; whatever
# is left here is removed: a screening issue id (A:PARSE-014) anywhere, and a bracketed list of line ids
# like "(R26)" or "(R12-R14, J3)".
_ID = r"(?:A:[A-Z]+-[0-9]{3}b?|[RJ][0-9]{1,4}(?:\s*[-\u2013]\s*[RJ]?[0-9]{1,4})?)"
_ID_PAREN_RE = re.compile(r"\s*[\(\[]\s*(?:(?:see|line|lines|at|in)\s+)?" + _ID +
                          r"(?:\s*(?:,|;|/|&|and|or)\s*" + _ID + r")*\s*[\)\]]")
_ISSUE_ID_RE = re.compile(r"(?<![\w:])A:[A-Z]+-[0-9]{3}b?\b")


def strip_ids(s):
    if "A:" not in s and not re.search(r"[\(\[]\s*(?:\w+\s+)?[RJ][0-9]", s):
        return s
    s = _ID_PAREN_RE.sub("", s)
    s = _ISSUE_ID_RE.sub("", s)
    s = re.sub(r"\s+([,.;:!?])", r"\1", s)
    return re.sub(r"\s{2,}", " ", s).strip()


def txt(x, limit=None):
    """String from any value, contact details masked, internal ids removed, 'ATS score' never printed,
    optionally trimmed."""
    s = clean(x)
    if not s:
        return ""
    s = util.mask_contact(s)
    s = util.PHONE_INTL_RE.sub(lambda m: "***-***-" + re.sub(r"\D", "", m.group(0))[-4:], s)
    s = _ATS_SCORE_RE.sub("simulated screening result", s)
    s = strip_ids(s)
    if limit and len(s) > limit:
        s = fit(s, limit)
    return s


_SENTENCE_END_RE = re.compile("[.!?][\"'”’)]*(?=\\s|$)")
_CLAUSE_BREAK_RE = re.compile("\\s*[;,:]\\s|\\s[-–—]\\s|\\s\\(")
# Words that start a new phrase: cutting just before one leaves a complete phrase ("Increased online sales
# by 300%" rather than "Increased online sales by 300% during the").
_PHRASE_WORDS = frozenset((
    "about", "across", "after", "and", "as", "at", "because", "before", "but", "by", "during", "for", "from",
    "in", "including", "into", "of", "on", "or", "so", "than", "that", "through", "to", "using", "via", "when",
    "where", "which", "while", "who", "with", "without"))


def fit(s, n):
    """Shorten s to at most n characters without cutting a word in half, preferring whole sentences, then
    a clause break (, ; : a spaced dash or an opening parenthesis), then a phrase break (just before a
    linking word), and only then a plain word break. Anything cut short ends with an ellipsis; whole
    sentences end with their own punctuation."""
    s = s or ""
    if len(s) <= n:
        return s
    if n < 12:
        head = s[:max(n - 1, 1)]
        return (head.rsplit(" ", 1)[0] if " " in head else head).rstrip(" ,;:.") + "…"
    keep = max(16, n // 2)          # a cut must keep at least half the room (and 16 characters)
    sentences = ""
    for m in _SENTENCE_END_RE.finditer(s):
        if m.end() > n:
            break
        sentences = s[:m.end()]
    if len(sentences) >= keep:
        return sentences
    head = s[:n - 1]                # room for the ellipsis
    clause = [m.start() for m in _CLAUSE_BREAK_RE.finditer(head) if m.start() >= keep]
    if clause:
        return head[:clause[-1]].rstrip(" ,;:") + "…"
    if len(sentences) >= 16:        # a short complete sentence beats a long fragment
        return sentences
    words = list(re.finditer(r"\S+", head))
    for w in reversed(words[1:]):
        if w.start() < keep:
            break
        if w.group(0).lower() in _PHRASE_WORDS:
            return head[:w.start()].rstrip(" ,;:") + "…"
    cut = head.rsplit(" ", 1)[0] if " " in head and not s[n - 1:n].isspace() else head
    return cut.rstrip(" ,;:.") + "…"


def num(x):
    if isinstance(x, bool) or x is None:
        return None
    if isinstance(x, (int, float)):
        return int(round(x))
    m = re.match(r"^\s*(-?\d+(?:\.\d+)?)\s*$", clean(x))
    return int(round(float(m.group(1)))) if m else None


def reviewer_name(rid, short=False):
    rid = clean(rid)
    table = SHORT_NAMES if short else REVIEWER_NAMES
    return table.get(rid) or txt(rid.replace("_", " ").title())


def panel_total(report):
    """Panel size for "Flagged by N of M": the number of reviewer rows (7 unless a reviewer failed)."""
    return len([p for p in as_list(report.get("panel")) if isinstance(p, dict)]) or 7


def flagged_label(w, total=7):
    ids = [clean(i) for i in as_list(w.get("flagged_by")) if clean(i)]
    count = num(w.get("flagged_count"))
    if count is None:
        count = len(ids)
    if w.get("from_script") and count <= 1 and (not ids or ids == ["screening"]):
        return "Found by the screening script"
    label = "Flagged by %d of %d" % (count, max(total, count)) if count else "Flagged by the panel"
    if w.get("from_script"):
        label += " · includes the screening script"
    return label


def status_of(w, stage):
    st = clean(w.get("status")).lower()
    if stage == "panel":
        return "open"
    return st if st in STATUS else "open"


def truth_view(report):
    """What the truth-check cell says, following the display rules exactly."""
    tc = as_dict(report.get("truth_check"))
    ran = clean(tc.get("ran")) or "not_run"
    passed = tc.get("passed")
    traced, total = num(tc.get("bullets_traced")), num(tc.get("bullets_total"))
    prov_key = clean(tc.get("provenance")) or "not_run"
    prov = PROVENANCE.get(prov_key, PROVENANCE["not_run"])
    if ran == "script" and passed is True:
        big, small = "0", "invented facts"
        line = ("%d of %d bullets trace to your resume or your answers." % (traced, total)) \
            if traced is not None and total else "Every bullet traces to your resume or your answers."
        if prov_key == "self":
            # Live test 6.16: say plainly that the second audit was not independent.
            line = line[:-1] + ". The audit was done in this same chat, not by a fresh reviewer."
            prov = "Check each line yourself."
        tone = "good"
    elif ran == "script":
        big, small = "Did not pass", ""
        line = "The truth check found problems. Do not send this resume until they are fixed."
        tone = "bad"
    elif ran == "model_only":
        big, small = "Model-only", "truth check"
        line = "The truth-check script did not run, so we cannot promise zero invented facts. Check every line yourself."
        tone = "warn"
    else:
        big, small = "Not run", ""
        line = "The truth check has not run on a rewrite yet."
        tone = "muted"
    return {"big": big, "small": small, "line": line, "prov": prov, "tone": tone, "ran": ran}


def mode_note(report):
    mode = clean(report.get("mode")).lower()
    note = txt(report.get("mode_note"))
    if mode in INDEPENDENCE_NOTE and not note:
        note = INDEPENDENCE_NOTE[mode]
    return mode, note


FIRST_IMPRESSION_LABEL = "What a recruiter sees in 7 seconds"
NEXT_STEP_BIG = "Answer a few questions in chat"
NEXT_STEP_LINE = "Or say skip. Then Claude rebuilds your resume from your real experience only."
NO_REAL_GAP = "The panel didn't flag any gap that wording can't fix."
PANEL_LEGEND = ("Verdict: how each reviewer rates the resume through their own lens. "
                "Move forward: whether they would pass it on.")
STRONG_LEAD = "Strong resume."


def strong_view(report):
    """(lead, rest) of the strong-resume line, or None. Shown only when report_build set strong_resume to
    true and wrote the templated line; the renderer never decides a resume is strong on its own."""
    if report.get("strong_resume") is not True:
        return None
    line = txt(as_dict(report.get("verdict_strip")).get("strong_line"))
    if not line:
        return None
    if line.startswith(STRONG_LEAD):
        return STRONG_LEAD, line[len(STRONG_LEAD):].strip()
    return "", line


def mixed_view(report):
    """The plain line explaining a high screening band next to a low panel vote (live test 5.4), or ''.
    Built by report_build (verdict_strip.mixed_line); never shown next to the strong-resume line."""
    if strong_view(report):
        return ""
    return txt(as_dict(report.get("verdict_strip")).get("mixed_line"))


def first_impression_view(report, limit=None):
    """The Recruiter's 7-second takeaway (masked, trimmed), or ''."""
    value = report.get("first_impression")
    return txt(value, limit) if isinstance(value, str) else ""


def screening_view(report):
    sc = as_dict(report.get("screening"))
    before, after = as_dict(sc.get("before")), as_dict(sc.get("after")) if sc.get("after") else {}

    def side(d):
        if not d:
            return None
        req = as_dict(d.get("required"))
        found, total, listed = num(req.get("found")), num(req.get("total")), num(req.get("listed_only"))
        overall = num(d.get("overall"))
        if overall is not None:
            overall = util.round5(overall)   # one number, always a multiple of 5
        return {"overall": overall, "band": txt(d.get("band")),
                "readability": txt(as_dict(d.get("machine_readability")).get("band")),
                "keywords": txt(as_dict(d.get("keyword_match")).get("band")),
                "content": txt(as_dict(d.get("content_signals")).get("band")),
                "found": found, "total": total, "listed": listed,
                "req_label": txt(req.get("label")) or "Required terms"}
    b, a = side(before), side(after)
    return {"label": txt(sc.get("label")) or "Simulated screening check",
            "method": txt(sc.get("method")) or ("Overall = 40% file readability + 40% job-keyword match + 20% "
                                                 "content signals, rounded to steps of 5. Weights are our judgment, "
                                                 "not calibrated to hiring outcomes."),
            "before": b, "after": a, "after_source": txt(sc.get("after_source")),
            "precision": txt(sc.get("precision_note")), "disclaimer": txt(sc.get("disclaimer"))}


def required_line(side, general):
    if general:
        return "No job posting, so no keyword check"
    if not side or side["total"] in (None, 0):
        return "Not enough job description to count required terms"
    s = "%s: %d of %d found" % (side.get("req_label") or "Required terms", side["found"] or 0, side["total"])
    if side["listed"]:
        s += " (%d only in your skills list)" % side["listed"]
    return s


def dot(s):
    """End a label with a period unless it already ends with punctuation or an ellipsis."""
    s = s or ""
    return s if (not s or s[-1] in ".!?:\u2026") else s + "."


def label(s):
    """'Where:' for a lead-in label, but a clipped label keeps just its ellipsis (no '...:')."""
    s = s or ""
    return s if (not s or s.endswith("\u2026")) else s.rstrip(":") + ":"


def first_sentence(s):
    m = re.match(r"^(.+?[.!?])(\s|$)", s or "")
    return m.group(1) if m else (s or "")


def header_bits(report, short=False):
    t = as_dict(report.get("target"))
    role = txt(t.get("role"), 52 if short else None) or "Your target role"
    company = txt(t.get("company"), 34 if short else None)
    general = bool(report.get("general_review"))
    stage = clean(report.get("stage")) or "final"
    kicker = "Hiring Panel Report" + (" · General review" if general else "")
    title = role + ((" at " + company) if company else "")
    if general:
        title += " (no posting provided)"
    stage_label = "Final report" if stage == "final" else "Panel feedback · rewrite not done yet"
    sub = " · ".join(x for x in (txt(report.get("candidate")), txt(report.get("date")), stage_label) if x)
    return kicker, title, sub, stage, general


def panel_rows(report):
    rows = [as_dict(p) for p in as_list(report.get("panel")) if isinstance(p, dict)]
    order = {rid: i for i, rid in enumerate(REVIEWER_ORDER)}
    rows.sort(key=lambda p: order.get(clean(p.get("id")), 99))
    return rows


def vote_dots(rows):
    return [clean(p.get("advance")).lower() for p in rows]


# ----------------------------------------------------------------------------------------------
# HTML
# ----------------------------------------------------------------------------------------------
def e(s):
    return _html.escape(s or "", quote=True)


def chip(label, fg, bg, cls="chip"):
    return '<span class="%s" style="color:#%s;background:#%s">%s</span>' % (cls, fg, bg, e(label))


CSS = """
@page { size: Letter; margin: 0.4in 0.5in 0.36in; }
:root { --ink:#101828; --ink2:#344054; --muted:#667085; --faint:#98A2B3; --line:#E4E7EC; --soft:#F9FAFB;
        --accent:#1F3A5F; --accent-soft:#EEF2F7; }
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { margin: 0; background: #fff; color: var(--ink);
       font: %(base)spt/%(lh)s -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
       -webkit-font-smoothing: antialiased; }
.page { max-width: 7.5in; margin: 0 auto; }
@media screen {
  body { background: #EEF0F3; }
  .page { background: #fff; padding: 0.55in 0.6in; margin: 28px auto; border-radius: 10px;
          box-shadow: 0 1px 3px rgba(16,24,40,.06), 0 12px 32px rgba(16,24,40,.08); }
}
header.top { display: flex; justify-content: space-between; align-items: flex-end; gap: 16pt;
             padding-bottom: 7pt; border-bottom: 1.6pt solid var(--accent); }
.kicker { font-size: 6.8pt; letter-spacing: .07em; text-transform: uppercase; color: var(--accent); font-weight: 700; }
h1 { font-size: 15.5pt; line-height: 1.15; margin: 2pt 0 0; letter-spacing: -.2pt; font-weight: 750; }
.sub { color: var(--muted); font-size: 7.8pt; text-align: right; white-space: nowrap; }
.sub b { display: block; color: var(--ink); font-size: 9.5pt; font-weight: 650; margin-bottom: 1pt; }
.strip { display: grid; grid-template-columns: .9fr 1.72fr 1fr; gap: 7pt; margin: %(gap)spt 0 4pt; }
.cell { border: .75pt solid var(--line); border-radius: 7pt; padding: 5pt 8pt 5.5pt; background: #fff; }
.cell h3 { margin: 0 0 2pt; font-size: 6.4pt; letter-spacing: .07em; text-transform: uppercase; color: var(--muted); font-weight: 700; }
.big { font-size: 18pt; font-weight: 780; line-height: 1.02; letter-spacing: -.4pt; }
.big small { font-size: 8.4pt; font-weight: 600; color: var(--muted); letter-spacing: 0; margin-left: 2pt; }
.big .arrow { color: var(--faint); font-weight: 500; font-size: 13pt; margin: 0 3pt; }
.big .was { color: var(--faint); font-weight: 650; }
.line { color: var(--ink2); margin-top: 2pt; }
.line.tight { margin-top: .5pt; }
.fine { color: var(--muted); font-size: 6pt; line-height: 1.26; margin-top: 2pt; }
.dots { display: flex; gap: 2.5pt; margin: 4pt 0 1pt; }
.dots i { width: 7pt; height: 7pt; border-radius: 50%%; display: inline-block; background: #E4E7EC; }
.dots i.yes { background: #12B76A; } .dots i.unsure { background: #F79009; } .dots i.no { background: #F04438; }
.legend { font-size: 6.5pt; color: var(--muted); }
.good { color: #067647; } .bad { color: #B42318; } .warn { color: #B54708; } .muted { color: var(--muted); }
.modebar { display: flex; gap: 6pt; align-items: baseline; font-size: 7.4pt; color: var(--ink2); margin: 0 0 2pt; }
.modebar b { color: var(--ink); }
.modebar .note { color: #93370D; background: #FFFAEB; border-radius: 4pt; padding: 1pt 5pt; }
.lead { margin: 0; }
.strongline { margin: 2.5pt 0 1.5pt; padding: 2.5pt 8pt; border: .75pt solid #ABEFC6; border-radius: 6pt; background: #ECFDF3;
              color: #05603A; }
.strongline b { color: #054F31; }
.mixed { margin: 2pt 0 0; font-size: 7.6pt; color: var(--ink2); }
.plegend { margin-top: 2.5pt; font-size: 6.6pt; color: var(--muted); }
.first { display: flex; gap: 6pt; align-items: baseline; margin: 1.5pt 0 0; font-size: 7.6pt; color: var(--ink2); }
.first .lbl { flex: none; font-size: 6.4pt; letter-spacing: .07em; text-transform: uppercase; color: var(--muted); font-weight: 700; }
.first .q { font-style: italic; color: var(--ink); }
h2 { font-size: 7.6pt; letter-spacing: .07em; text-transform: uppercase; color: var(--accent); margin: %(h2gap)spt 0 3.5pt;
     font-weight: 750; display: flex; align-items: center; gap: 6pt; }
h2::after { content: ""; flex: 1; border-top: .6pt solid var(--line); }
h2 .n { color: var(--faint); font-weight: 600; letter-spacing: .4pt; }
.pinned { border: 1pt solid #FDA29B; background: #FEF3F2; border-radius: 7pt; padding: 5pt 9pt; }
.pinned li { margin: 1.5pt 0; } .pinned ul { margin: 0; padding-left: 11pt; }
.pinned b { color: #912018; }
ol.weak { list-style: none; margin: 0; padding: 0; }
ol.weak li { display: grid; grid-template-columns: 15pt 1fr; gap: 0 7pt; padding: %(wpad)spt 0; border-top: .6pt solid var(--line); }
ol.weak li:first-child { border-top: 0; padding-top: 1pt; }
.rank { width: 15pt; height: 15pt; border-radius: 50%%; background: var(--accent-soft); color: var(--accent); font-weight: 750;
        font-size: 7.6pt; display: flex; align-items: center; justify-content: center; margin-top: .5pt; }
.wt { display: flex; align-items: baseline; gap: 6pt; }
.wt b { font-size: %(wtitle)spt; }
.sev { font-size: 6.3pt; font-weight: 750; text-transform: uppercase; letter-spacing: .05em; }
.flag { margin-left: auto; font-size: 6.7pt; color: var(--muted); white-space: nowrap; }
.why { color: var(--ink2); margin-top: .3pt; }
.quote { color: var(--muted); font-style: italic; }
.fix { margin-top: 1pt; color: var(--ink2); }
.chip { display: inline-block; font-size: 6.5pt; font-weight: 700; padding: .6pt 5pt; border-radius: 8pt; white-space: nowrap;
        letter-spacing: .2pt; vertical-align: 1pt; margin-right: 3pt; }
.cols { display: grid; grid-template-columns: 1fr 1.08fr 1.08fr; gap: 10pt; }
.col h4 { margin: 0 0 2pt; font-size: 7.6pt; color: var(--ink); }
.col ul { margin: 0; padding-left: 10pt; color: var(--ink2); } .col li { margin: 0 0 1.5pt; }
.col p { margin: 0 0 2pt; color: var(--ink2); }
.next { margin-top: 4pt; padding: 3.5pt 8pt; background: var(--soft); border-radius: 6pt; color: var(--ink2); }
.next span { margin-right: 8pt; }
.next b { color: var(--ink); }
.next ol { margin: 1pt 0 0; padding-left: 12pt; } .next li { margin: 0 0 1pt; }
table.panel { width: 100%%; border-collapse: collapse; }
table.panel td { padding: %(tpad)spt 4pt; border-top: .6pt solid var(--line); vertical-align: middle; }
table.panel tr:first-child td { border-top: 0; }
table.panel td.who { width: 24%%; line-height: 1.18; } td.who b { display: block; font-size: 8pt; } td.who small { display: block; color: var(--muted); font-size: 6.6pt; }
table.panel td.v { width: 11%%; white-space: nowrap; } table.panel td.a { width: 12%%; white-space: nowrap; font-weight: 650; font-size: 7.4pt; }
table.panel td.take { color: var(--ink2); }
table.panel th { white-space: nowrap; text-align: left; font-size: 6.2pt; letter-spacing: .06em; text-transform: uppercase; color: var(--faint);
                 font-weight: 700; padding: 0 4pt 2pt; }
.adot { display: inline-block; width: 5.5pt; height: 5.5pt; border-radius: 50%%; margin-right: 3pt; vertical-align: .5pt; }
.after { margin-top: 3pt; font-size: 7.4pt; color: var(--ink2); }
.card { border: .75pt solid var(--line); border-radius: 7pt; padding: 6pt 9pt; margin: 0 0 5pt; }
.card .side { margin: 2pt 0; } .card .which { color: var(--ink2); margin-top: 2pt; }
table.kw { width: 100%%; border-collapse: collapse; } table.kw td { padding: 3pt 4pt; border-top: .6pt solid var(--line); vertical-align: top; }
table.kw tr:first-child td { border-top: 0; } table.kw td.term { width: 22%%; font-weight: 650; } table.kw td.st { width: 21%%; }
ul.plain { margin: 0; padding-left: 12pt; } ul.plain li { margin: 0 0 2pt; }
ol.prep { margin: 0; padding-left: 14pt; } ol.prep li { margin: 0 0 3pt; } ol.prep small { color: var(--muted); }
.tag { font-size: 6.4pt; font-weight: 700; color: #B54708; background: #FFFAEB; border-radius: 6pt; padding: .5pt 5pt; margin-left: 4pt; }
.small { font-size: 7.2pt; color: var(--ink2); } .small p { margin: 0 0 3pt; }
footer { margin-top: %(fgap)spt; padding-top: 4pt; border-top: .6pt solid var(--line); display: flex; justify-content: space-between;
         gap: 10pt; font-size: 6pt; color: var(--faint); }
footer span:last-child { text-align: right; white-space: nowrap; }
.onepage footer span { white-space: nowrap; }
.onepage .full-only { display: none; }
@media screen and (min-width: 1150px) { .page { zoom: 1.25; } }
@media screen and (max-width: 900px) {
  body { background: #fff; }
  .page { max-width: none; margin: 0; padding: 14px 6px 24px; border-radius: 0; box-shadow: none; zoom: 1.32; }
  header.top { flex-direction: column; align-items: flex-start; gap: 4pt; }
  .sub { text-align: left; white-space: normal; }
  .strip, .cols { grid-template-columns: 1fr; }
  .modebar { flex-wrap: wrap; }
  .first { display: block; } .first .lbl { display: block; margin-bottom: 1pt; }
  .wt { flex-wrap: wrap; } .flag { margin-left: 0; width: 100%%; }
  table.panel thead { display: none; }
  table.panel tr { display: grid; grid-template-columns: auto auto 1fr; gap: 2pt 6pt; padding: 4pt 0;
                   border-top: .6pt solid var(--line); }
  table.panel tr:first-child { border-top: 0; }
  table.panel td { display: block; border: 0; padding: 0; width: auto !important; }
  table.panel td.who, table.panel td.take { grid-column: 1 / -1; }
  table.kw td.term, table.kw td.st { width: auto; }
  footer { flex-direction: column; gap: 3pt; } footer span:last-child { text-align: left; white-space: normal; }
}
"""

DENSITY = [  # base font, line height, strip gap, h2 gap, weakness padding, panel padding, footer gap, weakness title
    {"base": 8.3, "lh": 1.33, "gap": 7, "h2gap": 7.5, "wpad": 2.8, "tpad": 2.3, "fgap": 6, "wtitle": 8.6},
    {"base": 8.0, "lh": 1.32, "gap": 6, "h2gap": 6.5, "wpad": 2.4, "tpad": 2.0, "fgap": 5, "wtitle": 8.3},
    {"base": 7.6, "lh": 1.3, "gap": 5, "h2gap": 5.5, "wpad": 2.0, "tpad": 1.6, "fgap": 4, "wtitle": 8.0},
    {"base": 7.2, "lh": 1.28, "gap": 4, "h2gap": 4.5, "wpad": 1.5, "tpad": 1.2, "fgap": 3, "wtitle": 7.6},
    {"base": 7.0, "lh": 1.25, "gap": 3, "h2gap": 4, "wpad": 1.2, "tpad": 1.0, "fgap": 2, "wtitle": 7.4},
]
# Text budgets for the one-page PDF. "line" is roughly how many characters fit on one full-width line,
# so a weakness stays at three lines: title, why (+ quote when it fits), status + fix.
LIMITS = [
    {"line": 128, "fix": 118, "take": 140, "list": 2, "item": 72, "show_quote": True, "show_why": True, "steps": 3},
    {"line": 132, "fix": 122, "take": 140, "list": 2, "item": 68, "show_quote": True, "show_why": True, "steps": 3},
    {"line": 138, "fix": 128, "take": 130, "list": 2, "item": 64, "show_quote": False, "show_why": True, "steps": 2},
    {"line": 145, "fix": 135, "take": 120, "list": 2, "item": 60, "show_quote": False, "show_why": True, "steps": 2},
    {"line": 150, "fix": 140, "take": 110, "list": 1, "item": 56, "show_quote": False, "show_why": False, "steps": 0},
]
# The panel's "In one line" column holds two lines next to the two-line reviewer cell, so a take up to
# "take" characters costs no height. Real-gap titles and cut lines get room for a whole phrase.
GAP_TITLE, CUT_TEXT = 64, 90
GAP_ROUTE = 150     # one or two real gaps get room for the whole honest route (it is the point of the column)
FULL_LIMITS = {"line": 0, "fix": 400, "take": 300, "list": 12, "item": 300, "show_quote": True, "show_why": True, "steps": 4}


def why_and_quote(w, lim):
    """The 'why' sentence and evidence quote, fitted to one line in the one-page PDF."""
    if not lim["show_why"]:
        return "", ""
    why = txt(w.get("why"))
    quote = txt(w.get("evidence_quote")) if lim["show_quote"] else ""
    line = lim["line"]
    if not line:
        return why, quote
    if len(why) >= line:
        return txt(why, line), ""
    room = line - len(why) - 3
    if quote and len(quote) > room:
        quote = txt(quote, room) if room >= 28 else ""
    return why, quote


def vote_counts(rows):
    adv = vote_dots(rows)
    return sum(1 for a in adv if a == "yes"), sum(1 for a in adv if a == "unsure"), sum(1 for a in adv if a == "no")


def _strip_html(report, sv, tv, rows, general, stage):
    dots = "".join('<i class="%s" title="%s"></i>' % (clean(p.get("advance")).lower() if clean(p.get("advance")).lower() in ADVANCE else "",
                                                     e(txt(p.get("name")) or reviewer_name(p.get("id")))) for p in rows)
    vote_label = txt(as_dict(report.get("verdict_strip")).get("vote_label"))
    yes, unsure, no = vote_counts(rows)
    m = re.match(r"^\s*(\d+)\s+of\s+(\d+)\s*(.*)$", vote_label)
    if m:
        big = '%s<small>of %s</small>' % (e(m.group(1)), e(m.group(2)))
        rest = m.group(3) or "would move you forward"
    else:
        big = '%d<small>of %d</small>' % (yes, len(rows) or 7)
        rest = vote_label or "would move you forward"
    cell1 = ('<div class="cell"><h3>The panel</h3><div class="big">%s</div><div class="line">%s</div>'
             '<div class="dots">%s</div><div class="legend">%d yes \u00b7 %d unsure \u00b7 %d no</div>'
             '<div class="fine">Each reviewer answered: should this resume move to the next step for this job?</div></div>'
             % (big, e(rest), dots, yes, unsure, no))
    b, a = sv["before"], sv["after"]
    if b and b["overall"] is not None:
        if a and a["overall"] is not None:
            score = ('<span class="was">%d</span><span class="arrow">\u2192</span>%d<small>/ 100</small>'
                     % (b["overall"], a["overall"]))
            band = "%s \u2192 %s" % (b["band"], a["band"]) if b["band"] != a["band"] else a["band"]
            read = "Machine readability: %s" % (("%s \u2192 %s" % (b["readability"], a["readability"]))
                                                 if b["readability"] != a["readability"] else a["readability"])
            req = required_line(a, general)
            src = ""
        else:
            score = '%d<small>/ 100</small>' % b["overall"]
            band, read, req, src = b["band"], "Machine readability: %s" % b["readability"], required_line(b, general), ""
        cell2 = ('<div class="cell"><h3>%s</h3><div class="big">%s</div><div class="line"><b>%s</b></div>'
                 '<div class="line tight">%s</div><div class="line tight">%s</div><div class="fine">%s%s</div></div>'
                 % (e(sv["label"]), score, e(band), e(read), e(req), e(src), e(sv["method"])))
    else:
        cell2 = ('<div class="cell"><h3>%s</h3><div class="big muted">Not run</div><div class="fine">%s</div></div>'
                 % (e(sv["label"]), e(sv["method"])))
    if stage == "panel":
        # No count here: the batch Claude asks in chat can differ from this list (live test 4.4).
        cell3 = ('<div class="cell"><h3>Next step</h3><div class="big" style="font-size:12.5pt;margin-top:2pt">%s</div>'
                 '<div class="line">%s</div></div>' % (e(NEXT_STEP_BIG), e(NEXT_STEP_LINE)))
    else:
        big = '%s<small>%s</small>' % (e(tv["big"]), e(tv["small"])) if tv["small"] else e(tv["big"])
        size = "" if tv["big"] == "0" else ' style="font-size:12.5pt;margin-top:2pt"'
        cell3 = ('<div class="cell"><h3>Truth check</h3><div class="big %s"%s>%s</div><div class="line">%s</div>'
                 '<div class="fine">%s</div></div>' % (tv["tone"], size, big, e(tv["line"]),
                                                       e(tv["prov"] if tv["ran"] == "script" else "")))
    return '<section class="strip">%s%s%s</section>' % (cell1, cell2, cell3)

def _weak_html(w, stage, lim, total=7):
    sl, scol = SEVERITY.get(clean(w.get("severity")).lower(), SEVERITY["minor"])
    st = status_of(w, stage)
    stl, stc, stb = STATUS[st]
    why, quote = why_and_quote(w, lim)
    fix = txt(w.get("fix"), lim["fix"])
    rank = num(w.get("rank")) or 0
    body = '<div class="wt"><b>%s</b><span class="sev" style="color:#%s">%s</span><span class="flag">%s</span></div>' % (
        e(txt(w.get("title"), 80)), scol, e(sl), e(flagged_label(w, total)))
    if why or quote:
        body += '<div class="why">%s%s</div>' % (e(why), (' <span class="quote">\u201c%s\u201d</span>' % e(quote)) if quote else "")
    body += '<div class="fix">%s%s</div>' % (chip(stl, stc, stb), e(fix))
    return '<li><span class="rank">%d</span><div>%s</div></li>' % (rank, body)

def cut_text(c, limit=None):
    """The cut line's own words (its R# id stays in report.json; students never see ids, live test A11)."""
    return txt(c.get("text"), limit) or "a line from your original resume"


def changes_line(ch):
    bits = []
    br = num(ch.get("bullets_rewritten"))
    if br is not None:
        bits.append("%d bullet%s rewritten" % (br, "" if br == 1 else "s"))
    if ch.get("reordered"):
        bits.append("sections reordered")
    nf = num(ch.get("numbers_from_you"))
    if nf:
        bits.append("%d number%s from your answers" % (nf, "" if nf == 1 else "s"))
    n = len(as_list(ch.get("cut")))
    bits.append("%d line%s cut" % (n, "" if n == 1 else "s"))
    return ", ".join(bits).capitalize() + "."


def _section4_html(report, stage, lim, onepage=False):
    ch = report.get("changes") if isinstance(report.get("changes"), dict) else None
    n, item = lim["list"], lim["item"]
    if stage == "panel" or ch is None:
        changed = '<p>Nothing yet. After you answer, Claude rewrites your resume from your own lines and answers only.</p>'
    else:
        cuts = [as_dict(c) for c in as_list(ch.get("cut"))]
        changed = "<p>%s</p>" % e(changes_line(ch))
        if cuts:
            if onepage:
                items = "".join('<li>Cut: \u201c%s\u201d</li>' % e(cut_text(c, CUT_TEXT))
                                for c in cuts[:n])
            else:
                items = "".join('<li>Cut: \u201c%s\u201d. %s</li>' % (e(cut_text(c)),
                                                                       e(txt(c.get("reason")))) for c in cuts)
            more = ('<li>+%d more (see the full report)</li>' % (len(cuts) - n)) if onepage and len(cuts) > n else ""
            changed += "<ul>%s%s</ul>" % (items, more)
    needs = [as_dict(x) for x in as_list(report.get("needs_you"))]
    if needs:
        shown = needs[:n] if onepage else needs
        needs_html = "<ul>%s%s</ul>" % ("".join('<li><b>%s</b> %s</li>' % (e(label(txt(x.get("where"), 40))), e(txt(x.get("ask"), item)))
                                                for x in shown),
                                        ('<li>+%d more</li>' % (len(needs) - n)) if onepage and len(needs) > n else "")
    else:
        needs_html = "<p>Nothing. Every open question was answered or skipped.</p>"
    gaps = [as_dict(x) for x in as_list(report.get("real_gaps"))]
    if gaps:
        shown = gaps[:n] if onepage else gaps
        gap_item = max(item, GAP_ROUTE) if onepage and len(gaps) <= 2 else item
        gaps_html = "<ul>%s%s</ul>" % ("".join('<li><b>%s</b> %s</li>' % (e(dot(txt(x.get("title"), GAP_TITLE))), e(txt(x.get("honest_route"), gap_item)))
                                               for x in shown),
                                       ('<li>+%d more</li>' % (len(gaps) - n)) if onepage and len(gaps) > n else "")
    else:
        gaps_html = "<p>%s</p>" % e(NO_REAL_GAP)
    title1 = "What we changed" if stage != "panel" else "What changes next"
    out = ('<div class="cols"><div class="col"><h4>%s</h4>%s</div><div class="col"><h4>Needs you</h4>%s</div>'
           '<div class="col"><h4>Real gaps (not fixable by wording)</h4>%s</div></div>' % (e(title1), changed, needs_html, gaps_html))
    steps = [txt(x) for x in as_list(report.get("next_steps")) if txt(x)][:lim["steps"]]
    if steps:
        if onepage:
            out += '<div class="next"><b>Next steps:</b> %s</div>' % " ".join(
                '<span>%d. %s</span>' % (i + 1, e(txt(x, 78))) for i, x in enumerate(steps))
        else:
            out += '<div class="next"><b>Next steps</b><ol>%s</ol></div>' % "".join("<li>%s</li>" % e(x) for x in steps)
    return out

def _panel_html(report, rows, lim):
    trs = []
    for p in rows:
        vl, vc, vb = VERDICTS.get(clean(p.get("verdict")).lower(), ("Not given", "475467", "F2F4F7"))
        al, ac = ADVANCE.get(clean(p.get("advance")).lower(), ("Unsure", "B54708"))
        name = txt(p.get("name")) or reviewer_name(p.get("id"))
        trs.append('<tr><td class="who"><b>%s</b><small>%s</small></td><td class="v">%s</td>'
                   '<td class="a" style="color:#%s"><span class="adot" style="background:#%s"></span>%s</td><td class="take">%s</td></tr>'
                   % (e(name), e(txt(p.get("lens"), 40)), chip(vl, vc, vb), ac, ac, e(al), e(txt(p.get("take"), lim["take"]))))
    head = '<tr><th>Reviewer</th><th>Verdict</th><th>Move forward?</th><th>In one line</th></tr>'
    out = '<table class="panel"><thead>%s</thead><tbody>%s</tbody></table>' % (head, "".join(trs))
    out += '<div class="plegend">%s</div>' % e(PANEL_LEGEND)
    pa = report.get("panel_after")
    if isinstance(pa, dict) and txt(pa.get("vote_label")):
        out += '<div class="after"><b>After the rewrite:</b> %s. <span class="muted">%s</span></div>' % (
            e(txt(pa.get("vote_label"))), e(txt(pa.get("note")) or "Re-read by fresh reviewers; directional."))
    return out


def _lead_html(report):
    """Right under the verdict strip: the strong-resume line (only when report_build says so) and the
    Recruiter's 7-second first impression."""
    parts = []
    strong = strong_view(report)
    if strong:
        lead, rest = strong
        parts.append('<div class="strongline">%s%s</div>' % (('<b>%s</b> ' % e(lead)) if lead else "", e(rest)))
    mixed = mixed_view(report)
    if mixed:
        parts.append('<div class="mixed">%s</div>' % e(mixed))
    first = first_impression_view(report)
    if first:
        parts.append('<div class="first"><span class="lbl">%s</span><span class="q">\u201c%s\u201d</span></div>'
                     % (e(FIRST_IMPRESSION_LABEL), e(first)))
    return '<section class="lead">%s</section>' % "".join(parts) if parts else ""


def build_report_html(report, onepage=False, density=0):
    if not isinstance(report, dict):
        raise RenderError("report.json must be a JSON object")
    d = DENSITY[min(density, len(DENSITY) - 1)] if onepage else DENSITY[0]
    lim = LIMITS[min(density, len(LIMITS) - 1)] if onepage else FULL_LIMITS
    kicker, title, sub, stage, general = header_bits(report, short=onepage)
    sv = screening_view(report)
    tv = truth_view(report)
    rows = panel_rows(report)
    mode, note = mode_note(report)
    vs = as_dict(report.get("verdict_strip"))
    version = txt(report.get("hp_version")) or HP_VERSION
    out = []
    candidate = txt(report.get("candidate"))
    sub_rest = sub[len(candidate) + 3:] if candidate and sub.startswith(candidate) else sub
    h1_style = ' style="font-size:13pt"' if len(title) > 52 else ""
    # A long "date · stage" line goes on two lines so it does not squeeze the title onto two.
    sub_html = e(sub_rest) if len(sub_rest) <= 32 else "<br>".join(e(x) for x in sub_rest.split(" \u00b7 ", 1))
    out.append('<header class="top"><div><div class="kicker">%s</div><h1%s>%s</h1></div>'
               '<div class="sub"><b>%s</b>%s</div></header>' % (e(kicker), h1_style, e(title), e(candidate), sub_html))
    out.append(_strip_html(report, sv, tv, rows, general, stage))
    mode_label = txt(vs.get("mode_label")) or {"parallel": "7 independent reviewers", "sequential": "One chat, 7 roles in turn",
                                              "lite": "Quick run, 7 roles in turn", "manual": "Manual mode"}.get(mode, "")
    if mode_label or note:
        out.append('<div class="modebar"><span><b>Mode:</b> %s</span>%s</div>' % (
            e(mode_label), ('<span class="note">%s</span>' % e(note)) if note else ""))
    lead = _lead_html(report)
    if lead:
        out.append(lead)
    # 2. Fix before you send
    pinned = [as_dict(p) for p in as_list(report.get("pinned_integrity"))]
    if pinned:
        lst = pinned[:lim["list"]] if onepage else pinned
        out.append('<h2>Fix before you send</h2><div class="pinned"><ul>%s</ul></div>' % "".join(
            '<li><b>%s</b> %s</li>' % (e(dot(txt(p.get("title"), 90))), e(txt(p.get("fix"), lim["fix"]))) for p in lst))
    # 3. Biggest weaknesses
    weak = [as_dict(w) for w in as_list(report.get("weaknesses"))]
    shown = weak[:5] if onepage else weak
    if shown:
        extra = ('<span class="n">top 5 of %d</span>' % len(weak)) if onepage and len(weak) > 5 else ""
        out.append('<h2>Biggest weaknesses, most serious first %s</h2><ol class="weak">%s</ol>' % (
            extra, "".join(_weak_html(w, stage, lim, panel_total(report)) for w in shown)))
    else:
        out.append('<h2>Biggest weaknesses, most serious first</h2><p class="muted">The panel did not agree on any '
                   'weakness strong enough to rank.</p>')
    # 4. What changed / needs you / real gaps
    out.append('<h2>%s</h2>%s' % ("What changed, what needs you, real gaps" if stage != "panel" else
                                  "What needs you, real gaps", _section4_html(report, stage, lim, onepage)))
    # 5. The panel
    out.append('<h2>The panel</h2>%s' % _panel_html(report, rows, lim))
    if not onepage:
        out.append(_sections_6_to_10(report, sv, tv, mode_label, note))
    if onepage:
        foot_left = "A simulation, not a real applicant tracking system \u00b7 full report in the .html and .md"
    else:
        foot_left = first_sentence(sv["disclaimer"]) or "This is a simulation, not a real applicant tracking system."
    out.append('<footer><span>%s</span><span>%s</span></footer>' % (e(foot_left), e(FOOTER % version)))
    css = CSS % d
    doc = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
           '<meta name="viewport" content="width=device-width, initial-scale=1">'
           '<title>Hiring Panel Report</title><style>%s</style></head><body class="%s"><main class="page">%s</main>'
           '</body></html>\n' % (css, "onepage" if onepage else "full", "\n".join(out)))
    return doc


def _sections_6_to_10(report, sv, tv, mode_label, note):
    out = []
    final = clean(report.get("stage")) != "panel"      # "underused: move it up" was advice for the old resume
    dis = [as_dict(x) for x in as_list(report.get("disagreements"))][:2]
    if dis:
        cards = []
        for dd in dis:
            sides = "".join('<div class="side"><b>%s:</b> %s%s</div>' % (
                e(reviewer_name(s.get("reviewer"))), e(txt(s.get("view"))),
                (' <span class="quote">“%s”</span>' % e(txt(s.get("quote"), 160))) if txt(s.get("quote")) else "")
                for s in (as_dict(x) for x in as_list(dd.get("sides"))))
            cards.append('<div class="card"><b>%s</b>%s<div class="which"><b>Which view matters:</b> %s</div></div>' % (
                e(txt(dd.get("claim"))), sides, e(txt(dd.get("which_matters")))))
        out.append('<h2>Where the panel disagreed</h2>%s' % "".join(cards))
    kws = [as_dict(x) for x in as_list(report.get("keyword_gaps"))][:6]
    kos = [as_dict(x) for x in as_list(report.get("knockouts"))][:4]
    if kws or kos:
        body = ""
        if kws:
            body += '<table class="kw">%s</table>' % "".join(
                '<tr><td class="term">%s</td><td class="st">%s</td><td>%s</td></tr>' % (
                    e(txt(k.get("term"))), chip(*KW_STATUS.get(clean(k.get("status")), ("Gap", "B42318", "FEF3F2"))),
                    e(txt(k.get("note")))) for k in kws)
        if kos:
            body += '<p class="small" style="margin-top:5pt"><b>Application questions to expect</b> (no resume edit changes these):</p><ul class="plain">%s</ul>' % "".join(
                '<li><b>%s</b> “%s” %s</li>' % (e(dot(txt(k.get("type")).capitalize())), e(txt(k.get("jd_quote"), 160)),
                                                         e(txt(k.get("advice")))) for k in kos)
        out.append('<h2>Keyword gaps to close honestly</h2>%s' % body)
    strengths = [as_dict(x) for x in as_list(report.get("strengths"))][:4]
    if strengths:
        out.append('<h2>What’s already working</h2><ul class="plain">%s</ul>' % "".join(
            '<li><b>%s</b> <span class="muted">(%s)</span>%s</li>' % (
                e(txt(s.get("title"))), e(", ".join(reviewer_name(r, short=True) for r in as_list(s.get("flagged_by")))),
                '<span class="tag">Underused: move it up</span>' if s.get("underused") and not final else "")
            for s in strengths))
    prep = [as_dict(x) for x in as_list(report.get("interview_prep"))][:6]
    if prep:
        out.append('<h2>Interview prep</h2><ol class="prep">%s</ol>' % "".join(
            '<li>%s <small>(%s)</small></li>' % (e(txt(q.get("question"))), e(reviewer_name(q.get("from"))))
            for q in prep))
    tc = as_dict(report.get("truth_check"))
    lims = [txt(x) for x in as_list(report.get("limitations")) if txt(x)]
    parts = ['<p><b>Mode:</b> %s.%s</p>' % (e(mode_label or "Not recorded"), (" " + e(note)) if note else "")]
    if clean(report.get("stage")) != "panel":
        parts.append('<p><b>Truth check:</b> %s. %s %s</p>' % (e(("%s %s" % (tv["big"], tv["small"])).strip()), e(tv["line"]),
                                                             e(tv["prov"]) if tv["ran"] == "script" else ""))
    parts.append('<p><b>%s:</b> %s %s</p>' % (e(sv["label"]), e(sv["method"]), e(sv["precision"])))
    if sv["disclaimer"]:
        parts.append('<p>%s</p>' % e(sv["disclaimer"]))
    if lims:
        parts.append('<ul class="plain">%s</ul>' % "".join("<li>%s</li>" % e(x) for x in lims))
    files = as_dict(report.get("files"))
    names = [txt(files.get(k)) for k in ("resume_docx", "resume_pdf", "resume_md", "report_pdf", "report_md", "report_html")
             if txt(files.get(k))]
    if names:
        parts.append('<p><b>Your files:</b> %s</p>' % e(", ".join(os.path.basename(n) for n in names)))
    del tc
    out.append('<h2>Mode and limitations</h2><div class="small">%s</div>' % "".join(parts))
    return "\n".join(out)


# ----------------------------------------------------------------------------------------------
# Markdown (all ten sections)
# ----------------------------------------------------------------------------------------------
def md(s):
    return re.sub(r"([\\`*_\[\]<>#|])", r"\\\1", s or "")


def build_report_md(report):
    if not isinstance(report, dict):
        raise RenderError("report.json must be a JSON object")
    kicker, title, sub, stage, general = header_bits(report)
    sv, tv, rows = screening_view(report), truth_view(report), panel_rows(report)
    mode, note = mode_note(report)
    vs = as_dict(report.get("verdict_strip"))
    o = ["# %s" % md(title), "", "_%s_" % md(kicker + " · " + sub), ""]
    vote = txt(vs.get("vote_label")) or "%d of %d would move you forward" % (
        sum(1 for a in vote_dots(rows) if a == "yes"), len(rows) or 7)
    o.append("- **The panel:** %s" % md(vote))
    b, a = sv["before"], sv["after"]
    if b and b["overall"] is not None:
        if a and a["overall"] is not None:
            o.append("- **%s:** %d before, %d after (%s → %s). Machine readability: %s → %s. %s." % (
                md(sv["label"]), b["overall"], a["overall"], md(b["band"]), md(a["band"]), md(b["readability"]),
                md(a["readability"]), md(required_line(a, general))))
        else:
            o.append("- **%s:** %d (%s). Machine readability: %s. %s." % (
                md(sv["label"]), b["overall"], md(b["band"]), md(b["readability"]), md(required_line(b, general))))
        o.append("  _%s_" % md(sv["method"]))
    if stage != "panel":
        o.append("- **Truth check:** %s%s. %s" % (md(tv["big"]), (" " + md(tv["small"])) if tv["small"] else "", md(tv["line"])))
    mode_label = txt(vs.get("mode_label"))
    o.append("- **Mode:** %s%s" % (md(mode_label or mode or "not recorded"), (". " + md(note)) if note else ""))
    strong = strong_view(report)
    if strong:
        o.append("- %s%s" % (("**%s** " % md(strong[0])) if strong[0] else "", md(strong[1])))
    mixed = mixed_view(report)
    if mixed:
        o.append("- %s" % md(mixed))
    first = first_impression_view(report)
    if first:
        o.append("- **%s:** \u201c%s\u201d" % (FIRST_IMPRESSION_LABEL, md(first)))
    pinned = [as_dict(p) for p in as_list(report.get("pinned_integrity"))]
    if pinned:
        o += ["", "## Fix before you send", ""] + ["- **%s** %s" % (md(dot(txt(p.get("title")))), md(txt(p.get("fix")))) for p in pinned]
    o += ["", "## Biggest weaknesses, most serious first", ""]
    weak = [as_dict(w) for w in as_list(report.get("weaknesses"))]
    if not weak:
        o.append("The panel did not agree on any weakness strong enough to rank.")
    for w in weak:
        sl = SEVERITY.get(clean(w.get("severity")).lower(), SEVERITY["minor"])[0]
        st = STATUS[status_of(w, stage)][0]
        line = "%d. **%s** (%s; %s)  " % (num(w.get("rank")) or 0, md(txt(w.get("title"))), sl, md(flagged_label(w, panel_total(report))))
        o.append(line)   # two trailing spaces: a Markdown line break inside the list item
        if txt(w.get("why")) or txt(w.get("evidence_quote")):
            o.append("   %s%s  " % (md(txt(w.get("why"))), (" _“%s”_" % md(txt(w.get("evidence_quote")))) if txt(w.get("evidence_quote")) else ""))
        o.append("   **%s:** %s" % (st, md(txt(w.get("fix")))))
    o += ["", "## What changed, what needs you, real gaps" if stage != "panel" else "## What needs you, real gaps", ""]
    ch = report.get("changes") if isinstance(report.get("changes"), dict) else None
    if stage == "panel" or ch is None:
        o.append("**What changes next:** nothing yet. After you answer, Claude rewrites your resume from your own lines and answers only.")
    else:
        cuts = [as_dict(c) for c in as_list(ch.get("cut"))]
        o.append("**What we changed:** %s" % md(changes_line(ch)))
        for c in cuts:
            o.append("- Cut: “%s”. %s" % (md(cut_text(c)), md(txt(c.get("reason")))))
    needs = [as_dict(x) for x in as_list(report.get("needs_you"))]
    o += ["", "**Needs you:**"] + (["- **%s:** %s" % (md(txt(x.get("where"))), md(txt(x.get("ask")))) for x in needs] or ["- Nothing."])
    gaps = [as_dict(x) for x in as_list(report.get("real_gaps"))]
    o += ["", "**Real gaps (not fixable by wording):**"] + (["- **%s** %s" % (md(dot(txt(x.get("title")))), md(txt(x.get("honest_route")))) for x in gaps] or ["- " + NO_REAL_GAP])
    steps = [txt(s) for s in as_list(report.get("next_steps")) if txt(s)][:4]
    if steps:
        o += ["", "**Next steps:**"] + ["%d. %s" % (i + 1, md(s)) for i, s in enumerate(steps)]
    o += ["", "## The panel", "", "| Reviewer | Lens | Verdict | Move forward? | In one line |", "|---|---|---|---|---|"]
    for p in rows:
        vl = VERDICTS.get(clean(p.get("verdict")).lower(), ("Not given",))[0]
        al = ADVANCE.get(clean(p.get("advance")).lower(), ("Unsure",))[0]
        o.append("| %s | %s | %s | %s | %s |" % (md(txt(p.get("name")) or reviewer_name(p.get("id"))), md(txt(p.get("lens"))),
                                                vl, al, md(txt(p.get("take")))))
    o += ["", "_%s_" % md(PANEL_LEGEND)]
    pa = report.get("panel_after")
    if isinstance(pa, dict) and txt(pa.get("vote_label")):
        o += ["", "**After the rewrite:** %s. _%s_" % (md(txt(pa.get("vote_label"))),
                                                      md(txt(pa.get("note")) or "Re-read by fresh reviewers; directional."))]
        for p in [as_dict(x) for x in as_list(pa.get("rows"))]:
            o.append("- %s: %s, move forward: %s" % (md(txt(p.get("name")) or reviewer_name(p.get("id"))),
                                                     VERDICTS.get(clean(p.get("verdict")).lower(), ("Not given",))[0],
                                                     ADVANCE.get(clean(p.get("advance")).lower(), ("Unsure",))[0]))
    dis = [as_dict(x) for x in as_list(report.get("disagreements"))][:2]
    if dis:
        o += ["", "## Where the panel disagreed", ""]
        for dd in dis:
            o.append("**%s**" % md(txt(dd.get("claim"))))
            for s in (as_dict(x) for x in as_list(dd.get("sides"))):
                o.append("- %s: %s%s" % (md(reviewer_name(s.get("reviewer"))), md(txt(s.get("view"))),
                                         (" _“%s”_" % md(txt(s.get("quote")))) if txt(s.get("quote")) else ""))
            o.append("- Which view matters: %s" % md(txt(dd.get("which_matters"))))
            o.append("")
    kws = [as_dict(x) for x in as_list(report.get("keyword_gaps"))][:6]
    kos = [as_dict(x) for x in as_list(report.get("knockouts"))][:4]
    if kws or kos:
        o += ["", "## Keyword gaps to close honestly", ""]
        o += ["- **%s** (%s): %s" % (md(txt(k.get("term"))), KW_STATUS.get(clean(k.get("status")), ("Gap",))[0],
                                      md(txt(k.get("note")))) for k in kws]
        if kos:
            o += ["", "Application questions to expect (no resume edit changes these):"]
            o += ["- **%s** “%s” %s" % (md(dot(txt(k.get("type")).capitalize())), md(txt(k.get("jd_quote"))),
                                                md(txt(k.get("advice")))) for k in kos]
    strengths = [as_dict(x) for x in as_list(report.get("strengths"))][:4]
    if strengths:
        o += ["", "## What's already working", ""]
        o += ["- **%s** (%s)%s" % (md(txt(s.get("title"))), md(", ".join(reviewer_name(r, short=True) for r in as_list(s.get("flagged_by")))),
                                  ". Underused: move it up." if s.get("underused") and stage == "panel" else "")
              for s in strengths]
    prep = [as_dict(x) for x in as_list(report.get("interview_prep"))][:6]
    if prep:
        o += ["", "## Interview prep", ""]
        o += ["%d. %s _(%s)_" % (i + 1, md(txt(q.get("question"))), md(reviewer_name(q.get("from")))) for i, q in enumerate(prep)]
    o += ["", "## Mode and limitations", "", "- **Mode:** %s%s" % (md(mode_label or mode or "not recorded"), (". " + md(note)) if note else "")]
    if stage != "panel":
        o.append("- **Truth check:** %s%s" % (md(tv["line"]), (" " + md(tv["prov"])) if tv["ran"] == "script" else ""))
    o.append("- **%s:** %s %s" % (md(sv["label"]), md(sv["method"]), md(sv["precision"])))
    if sv["disclaimer"]:
        o.append("- %s" % md(sv["disclaimer"]))
    o += ["- %s" % md(txt(x)) for x in as_list(report.get("limitations")) if txt(x)]
    files = as_dict(report.get("files"))
    names = [os.path.basename(txt(files.get(k))) for k in ("resume_docx", "resume_pdf", "resume_md", "report_pdf", "report_md",
                                                          "report_html") if txt(files.get(k))]
    if names:
        o.append("- **Your files:** %s" % md(", ".join(names)))
    o += ["", "---", "", "_%s_" % md(FOOTER % (txt(report.get("hp_version")) or HP_VERSION))]
    text = "\n".join(o)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


# ----------------------------------------------------------------------------------------------
# Builtin PDF (no browser): the same sections 1-5 in a plainer layout, one Letter page
# ----------------------------------------------------------------------------------------------
class _ReportPdf:
    def __init__(self, density):
        self.lay = PdfLayout(612.0, 792.0, 36.0, 1.3)
        self.base = [8.4, 8.0, 7.6, 7.2, 7.0][density]

    def text(self, runs, size, color=INK2, indent=0.0, width=None, after=0.0, x=None):
        lay = self.lay
        width = (lay.width - indent) if width is None else width
        lines = wrap_runs(runs, size, width)
        x0 = (lay.x0 if x is None else x) + indent
        for segs in lines:
            lay.need(lay.lh(size))
            lay.y -= lay.lh(size)
            lay.draw_segs(segs, size, x0, lay.y + size * 0.24, color)
        lay.y -= after
        return len(lines)

    def heading(self, title):
        lay = self.lay
        size = 7.2
        lay.need(30)
        lay.y -= 9 + lay.lh(size)
        bts = to_winansi(title.upper())
        r, g, b = rgb(ACCENT)
        lay.pages[-1].append("BT /FB %.2f Tf 0.45 Tc %.3f %.3f %.3f rg %.2f %.2f Td %s Tj ET 0 Tc" % (
            size, r, g, b, lay.x0, lay.y + size * 0.24, pdf_str(bts)))
        w = text_width(bts, "B", size) + 0.45 * len(bts) + 6
        lay.hline(lay.x0 + w, lay.x1, lay.y + size * 0.55, 0.6, LINE)
        lay.y -= 3

    def chip(self, label, fg, bg, x, baseline, size):
        bts = to_winansi(label)
        w = text_width(bts, "B", size) + 8
        self.lay.fill_rect(x, baseline - size * 0.35, w, size * 1.45, bg, radius=size * 0.7)
        self.lay.draw_segs([(bts, "B", False, None)], size, x + 4, baseline, fg)
        return w

    def columns(self, cols, size):
        """Lay out several blocks side by side; each block is a list of (runs, size, color, after)."""
        lay = self.lay
        gap = 12.0
        width = (lay.width - gap * (len(cols) - 1)) / len(cols)
        top = lay.y
        bottoms = []
        for ci, block in enumerate(cols):
            lay.y = top
            x = lay.x0 + ci * (width + gap)
            for runs, sz, color, after in block:
                for segs in wrap_runs(runs, sz, width):
                    lay.y -= lay.lh(sz)
                    lay.draw_segs(segs, sz, x, lay.y + sz * 0.24, color)
                lay.y -= after
            bottoms.append(lay.y)
        lay.y = min(bottoms)


def build_report_pdf_builtin(report, density=0):
    if not isinstance(report, dict):
        raise RenderError("report.json must be a JSON object")
    lim = LIMITS[density]
    P = _ReportPdf(density)
    lay, base = P.lay, P.base
    kicker, title, sub, stage, general = header_bits(report, short=True)
    sv, tv, rows = screening_view(report), truth_view(report), panel_rows(report)
    mode, note = mode_note(report)
    vs = as_dict(report.get("verdict_strip"))
    version = txt(report.get("hp_version")) or HP_VERSION
    # 1. header
    P.text([{"t": kicker.upper(), "b": True}], 6.8, ACCENT)
    P.text([{"t": title, "b": True}], 14.5 if len(title) <= 52 else 12.5, INK, after=1)
    P.text([{"t": sub}], 8, MUTED, after=4)
    lay.hline(lay.x0, lay.x1, lay.y, 1.4, ACCENT)
    lay.y -= 6
    vote = txt(vs.get("vote_label")) or "%d of %d would move you forward" % (sum(1 for a in vote_dots(rows) if a == "yes"), len(rows) or 7)
    yes, unsure, no = vote_counts(rows)
    col1 = [([{"t": "THE PANEL", "b": True}], 6.3, MUTED, 1), ([{"t": vote, "b": True}], 11, INK, 2),
            ([{"t": "%d yes \u00b7 %d unsure \u00b7 %d no" % (yes, unsure, no)}], base - 0.4, INK2, 1),
            ([{"t": "Each reviewer answered: should this resume move to the next step for this job?"}], 6.2, MUTED, 0)]
    b, a = sv["before"], sv["after"]
    if b and b["overall"] is not None:
        if a and a["overall"] is not None:
            score = "%d -> %d / 100" % (b["overall"], a["overall"])
            band = "%s -> %s" % (b["band"], a["band"]) if b["band"] != a["band"] else a["band"]
            read = "Machine readability: %s" % a["readability"]
            req = required_line(a, general)
        else:
            score, band, read, req = "%d / 100" % b["overall"], b["band"], "Machine readability: %s" % b["readability"], required_line(b, general)
    else:
        score, band, read, req = "Not run", "", "", ""
    col2 = [([{"t": sv["label"].upper(), "b": True}], 6.3, MUTED, 1), ([{"t": score, "b": True}], 13, INK, 1),
            ([{"t": band, "b": True}], base, INK, 0), ([{"t": read}], base - 0.4, INK2, 0), ([{"t": req}], base - 0.4, INK2, 1),
            ([{"t": sv["method"]}], 6.2, MUTED, 0)]
    if stage == "panel":
        col3 = [([{"t": "NEXT STEP", "b": True}], 6.3, MUTED, 1), ([{"t": NEXT_STEP_BIG, "b": True}], 11, INK, 2),
                ([{"t": NEXT_STEP_LINE}], base - 0.4, INK2, 0)]
    else:
        tone = {"good": "067647", "bad": "B42318", "warn": "B54708"}.get(tv["tone"], MUTED)
        col3 = [([{"t": "TRUTH CHECK", "b": True}], 6.3, MUTED, 1),
                ([{"t": ("%s %s" % (tv["big"], tv["small"])).strip(), "b": True}], 11, tone, 2),
                ([{"t": tv["line"]}], base - 0.4, INK2, 1)]
        if tv["ran"] == "script":
            col3.append(([{"t": tv["prov"]}], 6.4, MUTED, 0))
    P.columns([col1, col2, col3], base)
    lay.y -= 4
    mode_label = txt(vs.get("mode_label"))
    if mode_label or note:
        P.text([{"t": "Mode: ", "b": True, "c": INK}, {"t": mode_label + ((". " + note) if note else "")}], 7.2, INK2 if not note else "93370D")
    strong = strong_view(report)
    if strong:
        lay.y -= 2
        P.text(([{"t": strong[0] + " ", "b": True, "c": "054F31"}] if strong[0] else []) + [{"t": strong[1]}], base - 0.2,
               "05603A", after=1)
    mixed = mixed_view(report)
    if mixed:
        lay.y -= 1
        P.text([{"t": mixed}], base - 0.2, INK2)
    first = first_impression_view(report)
    if first:
        lay.y -= 1
        P.text([{"t": FIRST_IMPRESSION_LABEL.upper() + "  ", "b": True, "c": MUTED}, {"t": "\u201c%s\u201d" % first, "i": True}],
               base - 0.2, INK)
    # 2. pinned
    pinned = [as_dict(p) for p in as_list(report.get("pinned_integrity"))][:lim["list"]]
    if pinned:
        P.heading("Fix before you send")
        for p in pinned:
            P.text([{"t": dot(txt(p.get("title"), 90)) + " ", "b": True, "c": "912018"}, {"t": txt(p.get("fix"), lim["fix"])}], base, INK2, after=1)
    # 3. weaknesses
    P.heading("Biggest weaknesses, most serious first")
    for w in [as_dict(x) for x in as_list(report.get("weaknesses"))][:5]:
        sl, scol = SEVERITY.get(clean(w.get("severity")).lower(), SEVERITY["minor"])
        stl, stc, stb = STATUS[status_of(w, stage)]
        lay.need(4 * lay.lh(base))
        lay.y -= lay.lh(base + 0.6)
        baseline = lay.y + base * 0.24
        rank = to_winansi(str(num(w.get("rank")) or 0))
        lay.fill_rect(lay.x0, baseline - 3.2, 11, 11, "EEF2F7", radius=5.5)
        lay.draw_segs([(rank, "B", False, None)], 7, lay.x0 + 5.5 - text_width(rank, "B", 7) / 2, baseline, ACCENT)
        x = lay.x0 + 17
        title_b = to_winansi(txt(w.get("title"), 90))
        x = lay.draw_segs([(title_b, "B", False, None)], base + 0.6, x, baseline, INK) + 6
        lay.draw_segs([(to_winansi(sl.upper()), "B", False, None)], 6.2, x, baseline, scol)
        fl = to_winansi(flagged_label(w, panel_total(report)))
        lay.draw_segs([(fl, "R", False, None)], 6.6, lay.x1 - text_width(fl, "R", 6.6), baseline, MUTED)
        why, quote = why_and_quote(w, lim)
        if why or quote:
            P.text([{"t": why}] + ([{"t": " “%s”" % quote, "i": True, "c": MUTED}] if quote else []), base, INK2, indent=17)
        lay.y -= lay.lh(base)
        bl = lay.y + base * 0.24
        cw = P.chip(stl, stc, stb, lay.x0 + 17, bl, 6.4)
        fix_lines = wrap_runs([{"t": txt(w.get("fix"), lim["fix"])}], base, lay.width - 17 - cw - 4)
        for i, segs in enumerate(fix_lines):
            if i:
                lay.y -= lay.lh(base)
            lay.draw_segs(segs, base, lay.x0 + 17 + cw + 4, lay.y + base * 0.24, INK2)
        lay.y -= 3
        lay.hline(lay.x0 + 17, lay.x1, lay.y, 0.5, LINE)
    # 4. changed / needs you / gaps
    P.heading("What changed, what needs you, real gaps" if stage != "panel" else "What needs you, real gaps")
    ch = report.get("changes") if isinstance(report.get("changes"), dict) else None
    if stage == "panel" or ch is None:
        changed = [([{"t": "Nothing yet. After you answer, Claude rewrites your resume from your own lines and answers only."}], base, INK2, 0)]
    else:
        cuts = [as_dict(c) for c in as_list(ch.get("cut"))]
        line = changes_line(ch)
        changed = [([{"t": line}], base, INK2, 1)] + [([{"t": "Cut: “%s”" % cut_text(c, CUT_TEXT)}], base - 0.5, MUTED, 1)
                                                      for c in cuts[:lim["list"]]]
    needs = [as_dict(x) for x in as_list(report.get("needs_you"))][:lim["list"]]
    gaps = [as_dict(x) for x in as_list(report.get("real_gaps"))][:lim["list"]]
    col_needs = [([{"t": label(txt(x.get("where"), 50)) + " ", "b": True}, {"t": txt(x.get("ask"), 110)}], base, INK2, 2) for x in needs] or \
        [([{"t": "Nothing. Every open question was answered or skipped."}], base, INK2, 0)]
    col_gaps = [([{"t": dot(txt(x.get("title"), GAP_TITLE)) + " ", "b": True},
                  {"t": txt(x.get("honest_route"), GAP_ROUTE if len(gaps) <= 2 else 110)}], base, INK2, 2) for x in gaps] or \
        [([{"t": NO_REAL_GAP}], base, INK2, 0)]
    title1 = "What we changed" if stage != "panel" else "What changes next"
    P.columns([[([{"t": title1, "b": True}], base, INK, 1)] + changed,
               [([{"t": "Needs you", "b": True}], base, INK, 1)] + col_needs,
               [([{"t": "Real gaps", "b": True}], base, INK, 1)] + col_gaps], base)
    steps = [txt(s, 110) for s in as_list(report.get("next_steps")) if txt(s)][:lim["steps"]]
    if steps:
        lay.y -= 3
        P.text([{"t": "Next steps: ", "b": True, "c": INK}, {"t": "  ".join("%d. %s" % (i + 1, s) for i, s in enumerate(steps))}], base - 0.3, INK2)
    # 5. panel
    P.heading("The panel")
    name_w, chip_w, adv_w = 128.0, 62.0, 40.0
    for p in rows:
        vl, vc, vb = VERDICTS.get(clean(p.get("verdict")).lower(), ("Not given", "475467", "F2F4F7"))
        al, ac = ADVANCE.get(clean(p.get("advance")).lower(), ("Unsure", "B54708"))
        take_lines = wrap_runs([{"t": txt(p.get("take"), lim["take"])}], base, lay.width - name_w - chip_w - adv_w)
        h = max(2, len(take_lines)) * lay.lh(base)
        lay.need(h + 4)
        top = lay.y
        lay.y -= lay.lh(base)
        bl = lay.y + base * 0.24
        lay.draw_segs([(to_winansi(txt(p.get("name")) or reviewer_name(p.get("id"))), "B", False, None)], base, lay.x0, bl, INK)
        P.chip(vl, vc, vb, lay.x0 + name_w, bl, 6.3)
        lay.draw_segs([(to_winansi(al), "B", False, None)], base - 0.4, lay.x0 + name_w + chip_w, bl, ac)
        for i, segs in enumerate(take_lines):
            lay.draw_segs(segs, base, lay.x0 + name_w + chip_w + adv_w, top - (i + 1) * lay.lh(base) + base * 0.24, INK2)
        lay.draw_segs([(to_winansi(txt(p.get("lens"), 40)), "R", False, None)], 6.6, lay.x0, bl - lay.lh(base), MUTED)
        lay.y = top - h - 2
        lay.hline(lay.x0, lay.x1, lay.y + 1, 0.5, LINE)
    P.text([{"t": PANEL_LEGEND}], 6.4, MUTED)
    pa = report.get("panel_after")
    if isinstance(pa, dict) and txt(pa.get("vote_label")):
        P.text([{"t": "After the rewrite: ", "b": True}, {"t": "%s. %s" % (txt(pa.get("vote_label")), txt(pa.get("note")) or "Re-read by fresh reviewers; directional.")}], 7.2, INK2)
    # footer pinned to the bottom margin of the last page
    fy = 26.0
    lay.hline(lay.x0, lay.x1, fy + 9, 0.5, LINE)
    left = to_winansi("A simulation, not a real applicant tracking system \u00b7 full report in the .html and .md")
    right = to_winansi(FOOTER % version)
    lay.draw_segs([(left, "R", False, None)], 5.9, lay.x0, fy, FAINT)
    lay.draw_segs([(right, "R", False, None)], 5.9, lay.x1 - text_width(right, "R", 5.9), fy, FAINT)
    return lay


# ----------------------------------------------------------------------------------------------
# Orchestrator
# ----------------------------------------------------------------------------------------------
def render_report(report, out_dir, pdf_engine="auto"):
    """Write Hiring_Panel_Report.html (all sections), .md (all sections) and .pdf (sections 1-5, one
    Letter page). Returns {files, pdfEngine, pages, warnings, overflow, pdfSkipped, layout, log}."""
    if not isinstance(report, dict):
        raise RenderError("report.json must be a JSON object")
    if pdf_engine not in ("auto", "chrome", "builtin", "soffice", None):
        raise RenderError("unknown pdf engine: %s" % pdf_engine)
    os.makedirs(out_dir, exist_ok=True)
    info = {"files": {}, "pdfEngine": None, "pages": None, "warnings": [], "overflow": None, "pdfSkipped": None,
            "layout": "report", "density": None, "log": []}
    html_path = os.path.join(out_dir, STEM + ".html")
    util.write_text(html_path, build_report_html(report, onepage=False))
    info["files"]["html"] = html_path
    md_path = os.path.join(out_dir, STEM + ".md")
    util.write_text(md_path, build_report_md(report))
    info["files"]["md"] = md_path

    pdf_path = os.path.join(out_dir, STEM + ".pdf")
    order = [pdf_engine] if pdf_engine not in ("auto", None) else ["chrome", "builtin"]
    allowed = pdf_engines.allowed_engines()
    if allowed and pdf_engine in ("auto", None):
        order = [x for x in order if x in allowed]
    engine = None
    for eng in order:
        if eng == "chrome":
            engine = _chrome_report(report, pdf_path, info)
        elif eng == "builtin":
            engine = _builtin_report(report, pdf_path, info)
        elif eng == "soffice":
            info["log"].append("soffice: not used for the report (it cannot lay out the HTML well)")
        if engine:
            break
    if engine:
        info["pdfEngine"] = engine
        info["files"]["pdf"] = pdf_path
        info["pages"] = pdf_engines.pdf_page_count(pdf_path)
        if info["pages"] and info["pages"] > 1:
            info["overflow"] = "The report PDF runs %d pages; the .html and .md hold everything." % info["pages"]
    else:
        if os.path.exists(pdf_path):
            try:
                os.remove(pdf_path)
            except OSError:
                pass
        info["pdfSkipped"] = ("No PDF engine worked on this computer. Open %s.html in a browser and print it to PDF."
                              % STEM)
    return info


def _chrome_report(report, pdf_path, info):
    tmp = tempfile.mkdtemp(prefix="hp-report-")
    try:
        for density in range(len(DENSITY)):
            html_path = os.path.join(tmp, "report_onepage.html")
            util.write_text(html_path, build_report_html(report, onepage=True, density=density))
            engine = pdf_engines.chrome_pdf(html_path, pdf_path, info["log"])
            if not engine:
                return None
            pages = pdf_engines.pdf_page_count(pdf_path)
            info["density"] = density
            if pages == 1:
                break
            info["log"].append("chrome: density %d gave %s pages; tightening" % (density, pages))
        return engine
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _builtin_report(report, pdf_path, info):
    title = "Hiring Panel Report"
    try:
        for density in range(len(DENSITY)):
            lay = build_report_pdf_builtin(report, density)
            info["density"] = density
            if len(lay.pages) == 1:
                break
        data = write_pdf_bytes(lay, title, txt(report.get("candidate")), "en-US")
    except Unencodable as exc:
        info["log"].append("builtin: the character %r is outside Western European text; this engine cannot show it"
                           % str(exc))
        return None
    util._atomic_write_bytes(pdf_path, data)
    return "builtin"
