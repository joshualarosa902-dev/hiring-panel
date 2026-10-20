"""Knockout signals (ATS spec 13): requirements an application form often asks about. Never scored.

Status rules:
- appears_met only with explicit evidence on the resume;
- appears_unmet only with an explicit conflict (GPA below the minimum, graduation outside the window,
  a lower degree level that is not marked in progress);
- work authorization, sponsorship, schedule, age, physical and background-check items are
  not_on_resume_by_design: they are never inferred from a name, school, location or anything else;
- everything else is unclear.
"""
import re

from .constants import KNOCKOUT_BY_DESIGN
from .dates import MONTHS, SEASONS, as_of_month
from .terms import importance_at, verbatim_window
from .textutil import clip

_LANGS = ("English|Spanish|French|German|Mandarin|Chinese|Cantonese|Japanese|Korean|Portuguese|Italian|"
          "Arabic|Hindi|Russian|Vietnamese|Tagalog|ASL|American Sign Language|Dutch|Polish|Turkish|"
          "Hebrew|Urdu|Bengali|Punjabi|Swahili|Haitian Creole|Greek|Swedish|Farsi|Persian|Somali|Hmong")
_MONTH_WORD = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
               r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|spring|summer|fall|autumn|winter)")
_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
              "nine": 9, "ten": 10}

PATTERNS = (
    ("work_authorization", re.compile(r"(?i)authori[sz]ed to work|work authori[sz]ation|eligible to work|"
                                      r"right to work|legally (?:authori[sz]ed|permitted|able) to work")),
    ("sponsorship", re.compile(r"(?i)\b(?:visa|immigration|employment|work)\s+sponsorship\b|"
                               r"\bsponsor(?:ship)?\b[^.]{0,40}\b(?:visas?|immigration|h-?1b|work authori[sz]ation)\b|"
                               r"\brequire[sd]?\s+(?:\w+\s+){0,3}sponsorship\b|\bh-?1b\b|\bvisas?\b|"
                               r"(?-i:\b(?:OPT|CPT)\b)")),
    ("onsite_hybrid", re.compile(r"(?i)\bon-?site\b|\bin[- ]office\b|\bin[- ]person\b|\bhybrid\b|"
                                 r"\b\d+ days (?:a|per) week (?:in|on)")),
    ("location", re.compile(r"(?i)must (?:live|reside|be located|be based)|within \d+ miles|"
                            r"commut(?:able|ing) distance")),
    ("relocation", re.compile(r"(?i)\brelocat\w*")),
    ("years_experience", re.compile(r"(?i)(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s*\+?\s*"
                                    r"(?:(?:-|–|to)\s*(\d+)\s*\+?\s*)?(?:years?|yrs?)\b[^.]{0,40}?experience")),
    ("degree", re.compile(r"(?i)\bbachelor(?:'?s)?\b|\bmaster(?:'s|s)?\s+(?:degree|of)\b|\bmaster's\b|"
                          r"\bdoctorate\b|\bph\.?\s?d\b|\bassociate(?:'s)?\s+degree\b|\bdegree\b|"
                          r"(?-i:\b(?:BS|BA|B\.S\.|B\.A\.|MBA|M\.S\.)(?![\w.])(?!\s+(?:Office|Excel|Word|Teams|Access|Project|SQL|Outlook|PowerPoint)))")),
    ("gpa", re.compile(r"(?i)\bgpa\b|\bgrade point average\b")),
    ("graduation_window", re.compile(r"(?i)graduat\w*\s+(?:date\s+)?(?:between|by|in|from|of|before|after)?\s*"
                                     r"%s\.?\s+\d{4}|class of \d{4}" % _MONTH_WORD)),
    ("license", re.compile(r"(?i)\blicen[sc]e[ds]?\b|\blicensure\b")),
    ("certification", re.compile(r"(?i)\bcertifi(?:ed|cation|cations|cate|cates)\b")),
    ("clearance", re.compile(r"(?i)security clearance|ts/sci|top secret|public trust|secret clearance")),
    ("travel", re.compile(r"(?i)travel (?:up to )?\d+\s?%|\d+\s?% travel|travel (?:is )?required|"
                          r"ability to travel|willing(?:ness)? to travel")),
    ("schedule", re.compile(r"(?i)\bweekends?\b|\bevenings?\b|\bovernights?\b|\bnight shifts?\b|\bshifts?\b|"
                            r"\bon-call\b|\bholidays\b")),
    ("physical", re.compile(r"(?i)lift(?:ing)? (?:up to )?\d+\s?(?:lbs?|pounds|kg)|"
                            r"stand(?:ing)? for (?:long|extended|prolonged) periods")),
    ("age", re.compile(r"(?i)\b(?:18|21) years of age|at least (?:18|21) years old|\bmust be (?:18|21)\b")),
    ("language", re.compile(r"(?i)\b(?:fluent|fluency|bilingual|proficient|proficiency)\b[^.]{0,30}\b(?:%s)\b|"
                            r"\b(?:%s)\b[^.]{0,25}\b(?:fluency|fluent|proficiency|required|preferred|speaking)\b|"
                            r"\bbilingual\b" % (_LANGS, _LANGS))),
    ("background_check", re.compile(r"(?i)background (?:check|screening|investigation)|drug (?:test|screen)")),
)
QUOTE_LIMIT = 120
BY_DESIGN = ("work_authorization", "sponsorship", "schedule", "age", "physical", "background_check")

ADVICE = {
    "onsite_hybrid": "The posting sets where you work. Answer honestly in the application; your resume "
                     "doesn't need to address it.",
    "location": "The posting has a location rule. Your resume's city is the evidence a reader sees. "
                "Answer location questions honestly.",
    "relocation": "The posting mentions relocation. Answer any relocation question honestly.",
    "years_experience": "Your dated experience is counted from the dates on your resume. If you have "
                        "more relevant experience, make sure its dates are written out.",
    "degree": "Make sure your degree and graduation date (or expected date) are written out in your "
              "Education section.",
    "major": "Make sure your major is written out in your Education section.",
    "gpa": "If an application asks for your GPA, answer truthfully. Never change the number.",
    "graduation_window": "Make sure your graduation date (or expected date) is written out with month "
                         "and year.",
    "license": "If you hold this license, list it with its exact name. If you don't, answer honestly.",
    "certification": "If you hold this certification, list it with its exact name. If you don't, "
                     "answer honestly.",
    "clearance": "Only list a clearance you actually hold. Answer clearance questions honestly.",
    "travel": "The posting mentions travel. Answer any travel question honestly.",
    "language": "If you speak this language, list it with an honest level, for example "
                "\"Spanish (conversational)\".",
    "other": "Answer this honestly if the application asks.",
}
_DEGREE_LEVEL = (
    (4, re.compile(r"(?i)\bph\.?\s?d\b|\bdoctor(?:ate|al)\b|\bd\.?phil\b|\bed\.?d\b")),
    # Bare "MA" and "MS" are also state abbreviations ("Boston, MA"), so they need dots or "in"/"of".
    (3, re.compile(r"(?i)\bmaster(?:'s|s)?\b|\bm\.b\.a\b|(?-i:\bMBA\b|\bM\.S\.|\bM\.Sc\b|\bMSc\b|"
                   r"\bM\.A\.|\bM\.Eng\b|\bMEng\b|\bMPH\b|\b(?:MS|MA)\s+(?:in|of)\b)")),
    (2, re.compile(r"(?i)\bbachelor(?:'s|s)?\b|(?-i:\bB\.S\.|\bBS\b|\bB\.Sc\b|\bBSc\b|\bB\.A\.|\bBA\b|"
                   r"\bBBA\b|\bB\.Eng\b|\bBEng\b|\bBFA\b)")),
    (1, re.compile(r"(?i)\bassociate(?:'s)?\b(?:\s+(?:of|degree|in))|(?-i:\bA\.A\.?\b|\bA\.S\.?\b|\bAAS\b)")),
)
_PURSUING_RE = re.compile(r"(?i)pursuing|currently enrolled|working toward|enrolled in|current(?:ly)? (?:a )?student|"
                          r"rising (?:junior|senior)|in progress")
_RESUME_GPA_RE = re.compile(r"(?i)\bGPA\b\s*[:\-]?\s*([0-4]\.\d{1,2})(?:\s*/\s*([0-9]+(?:\.\d+)?))?|"
                            r"\b([0-4]\.\d{1,2})\s*/\s*([0-9]+(?:\.\d+)?)\s*GPA\b")
_JD_GPA_RE = re.compile(r"(?i)(?:gpa|grade point average)[^.\d]{0,25}([0-4]\.\d{1,2})|([0-4]\.\d{1,2})\s*\+?\s*"
                        r"(?:or (?:higher|above|better)\s*)?(?:cumulative\s+)?(?:gpa|grade point average)")
_JD_MAJOR_RE = re.compile(r"(?i)degree in ([A-Za-z&,/ ]{3,90}?)(?=\s+or\s+(?:a\s+)?(?:related|similar|equivalent)|"
                          r"[.;)]|$)")
_GRAD_RE = re.compile(r"(?i)(%s)\.?\s+(\d{4})(?:\s*(?:and|-|–|to|through)\s*(%s)\.?\s+(\d{4}))?" % (_MONTH_WORD, _MONTH_WORD))


_LANG_CONTEXT_RE = re.compile(r"(?i)\b(?:fluent|fluency|native|bilingual|trilingual|multilingual|"
                              r"conversational|proficien\w*|intermediate|advanced|heritage|languages?|speak\w*)\b")


def _speaks_two(t):
    """A resume line that shows two or more spoken languages: "bilingual (English and Mandarin)",
    "Languages: Spanish, English", "Fluent in Spanish"."""
    if re.search(r"(?i)\b(?:bilingual|multilingual|trilingual)\b", t):
        return True
    found = set(x.lower() for x in re.findall(r"(?i)\b(%s)\b" % _LANGS, t))
    if len(found) >= 2 and _LANG_CONTEXT_RE.search(t):
        return True
    return bool(found - {"english"}) and bool(re.search(r"(?i)\b(?:fluent|native|bilingual|conversational|"
                                                          r"proficien\w*|heritage)\b", t))


def _month_value(word, year, end=False):
    w = word.lower()
    if w in SEASONS:
        a, b, off = SEASONS[w]
        return (int(year) * 12 + b - 1) if end else ((int(year) + off) * 12 + a - 1)
    mo = MONTHS.get(w) or MONTHS.get(w[:3])
    return int(year) * 12 + mo - 1


def _degree_level(text):
    for lvl, rx in _DEGREE_LEVEL:
        if rx.search(text):
            return lvl
    return None


def find_knockouts(parsed, ctx):
    """ctx: dict(education_lines, education_entries, total_months, contact_location, resume_texts,
    has_cert(fn), as_of). Returns knockout_signals list (ordered by first appearance, then type)."""
    found = {}
    for li, ln in enumerate(parsed["lines"]):
        if ln["eeo"]:
            continue
        text = ln["scan"]
        for typ, rx in PATTERNS:
            if typ in found:
                continue
            m = rx.search(text)
            if not m:
                continue
            if typ == "gpa" and not _JD_GPA_RE.search(text):
                continue
            if typ == "degree" and ln["kind"] == "boilerplate":
                continue
            found[typ] = (li, m.start(), ln, m)
            if typ == "degree":
                mm = _JD_MAJOR_RE.search(text)
                if mm and "major" not in found:
                    found["major"] = (li, mm.start(), ln, mm)
    out = []
    for typ, (li, pos, ln, m) in sorted(found.items(), key=lambda kv: (kv[1][0], kv[1][1], kv[0])):
        text = ln["scan"]
        imp = "unspecified"
        imp_at = importance_at(ln, pos)
        if imp_at in ("required", "preferred"):
            imp = imp_at
        status, evidence, advice = _judge(typ, text, m, ctx)
        out.append({"type": typ, "importance": imp, "jd_quote": quote_for(text, m.start(), m.end()),
                    "resume_evidence": evidence,
                    "status": status, "advice": advice})
    return out


_SENTENCE_END_RE = re.compile(r"(?<=[.!?;])\s+")


def quote_for(text, start, end, limit=QUOTE_LIMIT):
    """The sentence of `text` that holds the match [start, end), verbatim, cut down around the match
    when longer than `limit` characters, so a quote always shows what the requirement is about
    (and survives the 120-character clip in brief.json)."""
    a = 0
    for m in _SENTENCE_END_RE.finditer(text):
        if m.end() <= start:
            a = m.end()
        else:
            break
    nxt = _SENTENCE_END_RE.search(text, max(end, a))
    b = nxt.start() if nxt else len(text)
    sent = text[a:b]
    if len(sent.strip()) <= limit:
        return sent.strip()
    return verbatim_window(sent, start - a, end - a, limit)


def _judge(typ, text, m, ctx):
    if typ in BY_DESIGN:
        return "not_on_resume_by_design", None, KNOCKOUT_BY_DESIGN
    advice = ADVICE.get(typ, ADVICE["other"])
    edu_text = " ".join(ctx["education_lines"])
    if typ == "years_experience":
        raw = m.group(1).lower()
        need = _NUM_WORDS.get(raw) or (int(raw) if raw.isdigit() else None)
        months = ctx["total_months"]
        if need and months is not None and months >= need * 12:
            return "appears_met", "About %d years of dated experience on your resume" % (months // 12), advice
        return "unclear", None, advice
    if typ == "degree":
        want = _degree_level(text)
        have = _degree_level(edu_text) if edu_text else None
        if have is None:
            return "unclear", None, advice
        ev = clip(next((l for l in ctx["education_lines"] if _degree_level(l) == have), edu_text), 160)
        in_progress = ctx["edu_expected"]
        if _PURSUING_RE.search(text):
            # The posting asks for a current student: an in-progress degree at the asked level fits.
            ok = in_progress and (want is None or have >= want)
            return ("appears_met" if ok else "unclear"), ev, advice
        if in_progress:
            return "unclear", ev, advice
        if want is None or have >= want:
            return "appears_met", ev, advice
        return "appears_unmet", ev, advice
    if typ == "major":
        fields = [f.strip().lower() for f in re.split(r",|/|\bor\b|\band\b", m.group(1)) if len(f.strip()) >= 3]
        low = edu_text.lower()
        for f in fields:
            if f and re.search(r"(?<![\w])%s(?![\w])" % re.escape(f), low):
                return "appears_met", clip(next((l for l in ctx["education_lines"] if f in l.lower()), f), 160), advice
        return "unclear", None, advice
    if typ == "gpa":
        jm = _JD_GPA_RE.search(text)
        need = float(jm.group(1) or jm.group(2)) if jm else None
        rm = _RESUME_GPA_RE.search(edu_text) if edu_text else None
        if not rm or need is None:
            return "unclear", None, advice
        val = float(rm.group(1) or rm.group(3))
        scale = rm.group(2) or rm.group(4)
        if scale and abs(float(scale) - 4.0) > 0.01:
            return "unclear", clip(rm.group(0), 160), advice
        if val >= need:
            return "appears_met", clip(rm.group(0), 160), advice
        return "appears_unmet", clip(rm.group(0), 160), advice
    if typ == "graduation_window":
        grad = ctx["graduation_month"]
        if grad is None:
            return "unclear", None, advice
        tail = text[m.start():]
        gm = _GRAD_RE.search(tail)
        cm = re.search(r"(?i)class of (\d{4})", tail)
        if gm:
            lo = _month_value(gm.group(1), gm.group(2))
            if gm.group(3):
                hi = _month_value(gm.group(3), gm.group(4), end=True)
            else:
                hi = _month_value(gm.group(1), gm.group(2), end=True)
                if re.search(r"(?i)\b(?:by|before)\b", m.group(0)):
                    lo = None
                elif re.search(r"(?i)\bafter\b", m.group(0)):
                    lo, hi = hi, None
        elif cm:
            lo, hi = int(cm.group(1)) * 12, int(cm.group(1)) * 12 + 11
        else:
            return "unclear", None, advice
        ev = ctx["graduation_text"]
        if (lo is None or grad >= lo) and (hi is None or grad <= hi):
            return "appears_met", ev, advice
        return "appears_unmet", ev, advice
    if typ in ("certification", "license"):
        hit = ctx["cert_evidence"](text)
        if hit:
            return "appears_met", clip(hit, 160), advice
        return "unclear", None, advice
    if typ == "clearance":
        for t in ctx["resume_texts"]:
            if re.search(r"(?i)\b(?:clearance|ts/sci|top secret)\b", t):
                return "appears_met", clip(t, 160), advice
        return "unclear", None, advice
    if typ == "language":
        langs = re.findall(r"(?i)\b(%s)\b" % _LANGS, text)
        named = [x for x in langs if x.lower() != "english"]
        for lang in named or langs:
            for t in ctx["resume_texts"]:
                if re.search(r"(?i)\b%s\b" % re.escape(lang), t) and (named or _LANG_CONTEXT_RE.search(t)):
                    return "appears_met", clip(t, 160), advice
        if not named and re.search(r"(?i)\b(?:bilingual|multilingual|trilingual)\b", text):
            # "Bilingual" with no language named: the resume must show two or more languages.
            for t in ctx["resume_texts"]:
                if _speaks_two(t):
                    return "appears_met", clip(t, 160), advice
        return "unclear", None, advice
    if typ == "location":
        loc = ctx["contact_location"]
        if loc:
            places = re.findall(r"\b(?:of|in|near|around)\s+([A-Z][A-Za-z.]+(?:\s[A-Z][A-Za-z.]+)?)", text)
            for p in places:
                if p.split()[0].lower() in loc.lower():
                    return "appears_met", loc, advice
            return "unclear", loc, advice
        return "unclear", None, advice
    return "unclear", None, advice


def graduation_info(entries, as_of):
    """Latest education end month (graduation or expected) and its text."""
    best, text = None, None
    for e in entries:
        if e.section != "education" or not e.dated:
            continue
        _s, end, _c = e.period(as_of_month(as_of))
        if end is not None and (best is None or end > best):
            best = end
            text = (e.range or e.single)["text"]
    return best, text
