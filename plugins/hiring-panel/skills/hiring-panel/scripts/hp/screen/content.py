"""Bullets and content signals (ATS spec 10). Thresholds live in constants.py and are heuristics."""
import re

from .constants import (BULLET_TOO_LONG, BULLET_TOO_SHORT, ENTRY_SECTIONS, READABILITY_NOTE,
                        REPEATED_OPENER_LIMIT)
from .dates import RANGE_RE

LIST_SECTIONS = ("skills", "coursework", "languages", "interests", "certifications", "references", "education",
                 "awards")

_UNITS = (r"users?|customers?|clients?|students?|members?|people|persons?|employees?|staff|interns?|"
          r"hours?|hrs|weeks?|days?|months?|years?|projects?|events?|accounts?|leads?|orders?|tickets?|"
          r"stores?|locations?|sites?|participants?|volunteers?|followers?|subscribers?|downloads?|views?|"
          r"impressions?|attendees?|guests?|patients?|residents?|families|children|kids|reports?|records?|"
          r"pages?|articles?|posts?|videos?|campaigns?|teams?|classes|courses?|lessons?|sessions?|"
          r"workshops?|shifts?|tables?|calls?|emails?|meetings?|interviews?|surveys?|responses?|"
          r"applications?|cases?|transactions?|invoices?|shipments?|units?|items?|products?|skus?|"
          r"vendors?|partners?|sponsors?|donors?|donations?|dollars|miles|schools?|chapters?|cities|"
          r"countries|states|languages|dashboards?|models?|scripts?|queries|tests?|experiments?|"
          r"samples?|features?|apps?|games?|bugs?|tutees|mentees|athletes|readers|visitors|"
          r"properties|meals|books|pounds|lbs|kg|tons|gallons|signups|sign-ups|registrations|"
          r"members|stakeholders|departments|branches|routes|deliveries|tasks|files|documents")
_NUMWORDS = (r"two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty|"
             r"forty|fifty|sixty|seventy|eighty|ninety|hundred|hundreds|thousand|thousands|dozen|dozens")
QUANT_RE = re.compile(
    r"\d+(?:\.\d+)?\s?%%"
    r"|[$€£¥]\s?\d[\d,]*(?:\.\d+)?\s?(?:k|m|b|million|billion|thousand)?\b"
    r"|\b\d+(?:\.\d+)?\s?x\b"
    r"|\b\d{1,3}(?:,\d{3})+\b"
    r"|\b\d+(?:\.\d+)?\s?[kKmM]\+?(?![\w])"
    r"|\b\d+\+?\s+(?:[a-z-]+\s+)?(?:%s)\b"
    r"|\btop\s\d+%%?"
    r"|#\d+\b"
    r"|\b(?:%s)\s+(?:[a-z-]+\s+)?(?:%s)\b" % (_UNITS, _NUMWORDS, _UNITS), re.I)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_GPA_RE = re.compile(r"(?i)\bGPA\b[:\s]*\d\.\d+(?:\s*/\s*\d(?:\.\d+)?)?|\b\d\.\d+\s*/\s*4(?:\.0+)?\b")
FIRST_PERSON_RE = re.compile(r"(?<![\w'])(?:I(?![\w'.])|(?i:me|my|mine|myself)(?![\w']))")
_ABBREV_TITLE_RE = re.compile(r"(?<![\w])(?:Sr|Mgr|Mngr|Asst|Coord|Assoc|Supv|Admin|Exec|Rep)\b\.?(?=[\s,|/)]|$)")


def is_quantified(text):
    """True when the text shows a number of scale or scope after years, date ranges and GPA are
    removed (ATS spec 10 QUANT)."""
    t = RANGE_RE.sub(" ", text)
    t = _GPA_RE.sub(" ", t)
    t = _YEAR_RE.sub(" ", t)
    return bool(QUANT_RE.search(t))


def _syllables(word):
    w = word.lower()
    groups = re.findall(r"[aeiouy]+", w)
    n = len(groups)
    if w.endswith("e") and not w.endswith(("le", "ee")) and n > 1:
        n -= 1
    return max(1, n)


def readability(texts):
    """Flesch Reading Ease and Flesch-Kincaid grade over bullets (each bullet is one sentence).
    Tokens with digits or all capitals are skipped. Information only."""
    sentences = 0
    n_words = 0
    syl = 0
    for t in texts:
        ws = [w for w in re.findall(r"[A-Za-z][A-Za-z'’-]*", t) if not w.isupper()]
        if not ws:
            continue
        sentences += 1
        n_words += len(ws)
        syl += sum(_syllables(w) for w in ws)
    if not sentences or not n_words:
        return {"flesch_reading_ease": None, "fk_grade": None, "note": READABILITY_NOTE}
    wps = n_words / float(sentences)
    spw = syl / float(n_words)
    fre = 206.835 - 1.015 * wps - 84.6 * spw
    fk = 0.39 * wps + 11.8 * spw - 15.59
    return {"flesch_reading_ease": round(fre, 1), "fk_grade": round(fk, 1), "note": READABILITY_NOTE}


def _opener(text):
    for w in re.findall(r"[A-Za-z][A-Za-z'’-]*", text):
        return w.lower().strip("'’-")
    return ""


def analyze_bullets(lines, entries, lex, has_headings):
    """Content metrics over experience-type bullets. Returns (metrics dict, per-bullet details)."""
    entry_bullets = []
    seen = set()
    for e in entries:
        if e.section in ENTRY_SECTIONS or e.section == "other":     # "other": work under an unread heading
            for b in e.bullets:
                if b.idx not in seen:
                    seen.add(b.idx)
                    entry_bullets.append(b)
    if not has_headings:
        entry_bullets = [rl for rl in lines if rl.bullet]
    elif not entry_bullets:
        # No Experience/Projects-type section was recognized: fall back to bullets outside list-like
        # sections, so a resume with an unusual heading still gets its bullets checked.
        entry_bullets = [rl for rl in lines if rl.bullet and rl.section not in LIST_SECTIONS]
    entry_bullets.sort(key=lambda rl: rl.idx)
    details = []
    openers = {}
    for rl in entry_bullets:
        text = rl.btext
        n = len(rl.words)
        op = _opener(text)
        low = text.lower()
        weak = None
        for w in lex.weak_openers:
            if low.startswith(w) and (len(low) == len(w) or not low[len(w)].isalnum()):
                weak = w
                break
        d = {"line": rl.idx, "words": n, "opener": op, "action": op in lex.action_forms,
             "present": op in lex.present_forms, "weak": weak, "quant": is_quantified(text),
             "first_person": len(FIRST_PERSON_RE.findall(text))}
        details.append(d)
        if op:
            openers[op] = openers.get(op, 0) + 1
    count = len(details)
    word_counts = sorted(d["words"] for d in details)
    if word_counts:
        mid = len(word_counts) // 2
        median = float(word_counts[mid]) if len(word_counts) % 2 else (word_counts[mid - 1] + word_counts[mid]) / 2.0
    else:
        median = None
    # first person also counts in the summary and top block
    fp_extra = sum(len(FIRST_PERSON_RE.findall(rl.text)) for rl in lines
                   if rl.section == "summary" and not rl.heading)
    buzz = []
    for rl in lines:
        if rl.heading or rl.section in ("references",):
            continue
        for b in lex.buzzwords_in(rl.text):
            if b.lower() not in [x.lower() for x in buzz]:
                buzz.append(b)
    metrics = {
        "count": count,
        "words_median": median,
        "too_long": sum(1 for d in details if d["words"] > BULLET_TOO_LONG),
        "too_short": sum(1 for d in details if d["words"] < BULLET_TOO_SHORT),
        "action_verb_ratio": round(sum(1 for d in details if d["action"]) / float(count), 2) if count else None,
        "quantified_ratio": round(sum(1 for d in details if d["quant"]) / float(count), 2) if count else None,
        "weak_openers": sorted({d["weak"] for d in details if d["weak"]}),
        "repeated_openers": {k: openers[k] for k in sorted(openers) if openers[k] > REPEATED_OPENER_LIMIT},
        "first_person_count": sum(d["first_person"] for d in details) + fp_extra,
        "buzzwords": buzz[:10],
        "total_words": sum(len(rl.words) for rl in lines),
    }
    return metrics, details, entry_bullets


def abbreviated_titles(entries):
    out = []
    for e in entries:
        if e.section not in ENTRY_SECTIONS:
            continue
        for rl in e.header_lines:
            m = _ABBREV_TITLE_RE.search(rl.text)
            if m:
                out.append(rl.text)
                break
    return out


def rating_graphic_lines(lines):
    """Lines that carried rating symbols ("Python • • • • ○"), as read (the symbols are stripped from
    the text used for matching)."""
    return [rl.raw for rl in lines if rl.rated]
