"""Resume lines and section detection (ATS spec 7).

A heading must look like a heading (short, no "@", no URL, no final period, not a bullet) and map to a
known section: an exact synonym from headings.json, or a core word ("experience", "skills", ...) whose
other words are generic fillers ("Relevant", "Technical", "Research"...) or whose last word is the
core word and the line is formatted like a heading. Unknown lines never start a section, so an
all-caps employer name cannot cut an Experience section in half.
"""
import re

from ..util import URL_RE
from .constants import SECTIONS
from .dates import RANGE_RE, SPLIT_END_RE, SPLIT_START_RE, find_dates
from .lexicon import norm_heading
from .textutil import bullet_split, caps_ratio, clean_line, letter_spaced_runs, strip_rating, words

CORE_WORDS = {
    "experience": "experience", "experiences": "experience", "employment": "experience",
    "internships": "experience", "work": "experience",
    "education": "education",
    "skills": "skills", "skill": "skills",
    "projects": "projects", "project": "projects",
    "certifications": "certifications", "certification": "certifications",
    "certificates": "certifications", "licenses": "certifications", "licences": "certifications",
    "leadership": "leadership_activities", "activities": "leadership_activities",
    "involvement": "leadership_activities", "extracurriculars": "leadership_activities",
    "volunteer": "volunteer", "volunteering": "volunteer",
    "awards": "awards", "honors": "awards", "honours": "awards", "achievements": "awards",
    "publications": "publications",
    "coursework": "coursework",
    "languages": "languages",
    "interests": "interests", "hobbies": "interests",
    "summary": "summary", "profile": "summary", "objective": "summary",
    "references": "references",
}
FILLER = set(("relevant professional work technical academic related additional selected key other "
              "research teaching industry internship campus community extracurricular career personal "
              "core select recent prior previous notable university college school and of the my in "
              "highlights history background information competencies expertise overview details "
              "service programming computer software tools achievements accomplishments recognition "
              "training credentials qualifications positions roles organizations affiliations "
              "memberships collegiate student honors awards leadership volunteer work experience "
              "activities involvement skills projects summary profile").split())
STANDARD_NAME = {"experience": "Experience", "education": "Education", "skills": "Skills",
                 "projects": "Projects", "certifications": "Certifications",
                 "leadership_activities": "Leadership", "volunteer": "Volunteer Experience",
                 "awards": "Awards", "publications": "Publications", "coursework": "Relevant Coursework",
                 "languages": "Languages", "interests": "Interests", "summary": "Summary",
                 "references": "References", "other": "Additional Information"}
_INLINE_LABEL_RE = re.compile(r"^([^:]{2,30}):\s*\S")
_INLINE_SECTIONS = ("skills", "languages", "certifications", "interests", "coursework")
_SMALL = {"and", "of", "&", "the", "in", "for", "to", "a"}


class RLine(object):
    """One analyzed body line of the resume."""
    __slots__ = ("idx", "text", "style", "list", "bold", "where", "section", "block", "heading", "bullet",
                 "btext", "dates", "is_sentence", "words", "raw", "rated", "htext", "spaced", "implied")

    def __init__(self, idx, text, style=None, is_list=False, bold=False, where="body"):
        self.idx = idx
        self.raw = text              # the line as read (rating symbols included)
        text, self.rated = strip_rating(text)
        self.text = text
        self.htext = None            # heading view of the text (letter spacing collapsed), set lazily
        self.spaced = bool(letter_spaced_runs(text))   # the line holds letter-spaced text ("S K I L L S")
        self.implied = False         # a bullet recognized by its shape (the PDF lost the glyph)
        self.style = style
        self.list = is_list
        self.bold = bold
        self.where = where
        self.section = "contact"     # section for evidence ("Skills: ..." inline labels count as skills)
        self.block = "contact"       # section of the heading above this line (used to group entries)
        self.heading = None          # dict when this line is a section heading
        self.bullet, self.btext = bullet_split(text)
        if not self.bullet and is_list:
            self.bullet = True
        self.dates = None            # filled by build_lines
        self.words = words(self.btext)
        self.is_sentence = False


_ABBREV_END_RE = re.compile(r"(?i)\b(?:inc|co|ltd|corp|llc|jr|sr|st|dept|univ)\.$")


def _continues(prev, rl, lex):
    """True when `rl` is the wrapped tail of the bullet `prev` (a PDF line break, or a manual line
    break inside a Word list item). Conservative: a new entry header must never be swallowed."""
    t = rl.text
    if rl.bullet or rl.where != prev.where or RANGE_RE.search(t) or not t:
        return False
    if lex is not None and classify_heading(rl, lex):
        return False
    ends = prev.text.rstrip()[-1:] in ".!?;:"
    if t[0].islower():
        return True
    if (t[0].isdigit() or t[0] in "(&%$") and not ends:
        return True
    return (not ends and len(rl.words) < 8 and t.endswith(".") and not _ABBREV_END_RE.search(t)
            and not find_dates(t, 0)["singles"])


def build_lines(doc, as_of_m, warnings, lex=None, max_lines=4000, max_chars=2000):
    """Flatten Document lines into RLines (splitting embedded newlines) and header/footer lines.

    Lines prefixed "[header] ", "[footer] " or "[text box] " (resume.md style) are recognized so a
    Document rebuilt from resume.md still screens correctly. Wrapped bullet tails are joined to their
    bullet (ATS spec 10), keeping the first line's number. A date range split over two lines
    ("Jun 2024" then "- Aug 2024") is recorded for DATE-003 and then read as one line.
    Returns (body lines, header/footer lines, split-range evidence strings).
    """
    body, hf = [], []
    raw_lines = doc.get("lines") if isinstance(doc.get("lines"), list) else []
    for h in (doc.get("header_footer") if isinstance(doc.get("header_footer"), list) else []):
        if isinstance(h, dict) and isinstance(h.get("text"), str):
            for part in h["text"].split("\n"):
                t = clean_line(part)
                if t:
                    hf.append({"where": h.get("where") if h.get("where") in ("header", "footer") else "header",
                               "text": t[:max_chars]})
    truncated = False
    for raw in raw_lines:
        if isinstance(raw, str):
            raw = {"text": raw}
        if not isinstance(raw, dict) or not isinstance(raw.get("text"), str):
            continue
        where = raw.get("where") if raw.get("where") in ("body", "table", "textbox") else "body"
        style = raw.get("style") if isinstance(raw.get("style"), str) else None
        for part in raw["text"].split("\n"):
            t = clean_line(part)
            if not t:
                continue
            w = where
            low = t.lower()
            if low.startswith("[header] ") or low.startswith("[footer] "):
                hf.append({"where": low[1:7], "text": t[9:].strip()[:max_chars]})
                continue
            if low.startswith("[text box] "):
                t, w = t[11:].strip(), "textbox"
                if not t:
                    continue
            if len(body) >= max_lines:
                truncated = True
                break
            if len(t) > max_chars:
                t = t[:max_chars]
                warnings.append("A very long line was shortened for checking.")
            body.append(RLine(len(body) + 1, t, style, bool(raw.get("list")), bool(raw.get("bold")), w))
    if truncated:
        warnings.append("The resume has more than %d lines; only the first %d were checked." % (max_lines, max_lines))
    joined = []
    for rl in body:
        prev = joined[-1] if joined else None
        if prev is not None and prev.bullet and _continues(prev, rl, lex):
            prev.text = prev.text + " " + rl.text
            prev.btext = prev.btext + " " + rl.text
            prev.words = words(prev.btext)
            continue
        joined.append(rl)
    body = joined
    splits = []
    merged = []
    for rl in body:
        prev = merged[-1] if merged else None
        if prev is not None and rl.where == prev.where and SPLIT_END_RE.search(prev.text) and \
                SPLIT_START_RE.match(rl.text) and not RANGE_RE.search(prev.text) and len(rl.text) <= 40:
            splits.append("%s / %s" % (prev.text, rl.text))
            prev.text = prev.text + " " + rl.text
            prev.bullet, prev.btext = False, prev.text
            prev.words = words(prev.btext)
            continue
        merged.append(rl)
    body = merged
    for rl in body:
        rl.dates = find_dates(rl.text, as_of_m)
        n = len(rl.words)
        rl.is_sentence = (not rl.bullet and not rl.dates["ranges"] and n >= 8
                          and (rl.text.rstrip().endswith((".", "!", ";")) or n >= 14))
    # "– Present" or "- May 2024" continuation lines are dates, not bullets.
    for rl in body:
        if rl.bullet and rl.text.lstrip()[:1] in "-–" and len(rl.words) <= 4 and (
                rl.dates["singles"] or re.search(r"(?i)\b(present|current|now)\b", rl.btext)):
            rl.bullet = False
            rl.btext = rl.text
    return body, hf, splits


def _fmt_signal(rl, core, n_words):
    style = (rl.style or "").lower().replace(" ", "")
    return (caps_ratio(core) >= 0.8 or style.startswith("heading") or style == "title" or rl.bold
            or (rl.text.rstrip().endswith(":") and n_words <= 4))


def _title_case(core):
    ws = [w for w in re.split(r"\s+", core) if w]
    return bool(ws) and all(w[0].isupper() or w.lower() in _SMALL or not w[0].isalpha() for w in ws)


def _core_map(lex):
    m = dict(CORE_WORDS)
    m.update(getattr(lex, "core_words", {}) or {})
    return m


def _core_section(norm, core):
    """Section for a normalized phrase made only of core and filler words, else None."""
    ws = norm.split()
    if not ws:
        return None
    cores = [core[w] for w in ws if w in core]
    if not cores or not all(w in core or w in FILLER for w in ws):
        return None
    return _choose(cores)


def _choose(cores):
    """Pick the section among core words: modifiers like "Leadership" or "Volunteer" beat the generic
    "experience", and anything beats summary words."""
    distinct = []
    for c in cores:
        if c not in distinct:
            distinct.append(c)
    if len(distinct) == 1:
        return distinct[0]
    strong = [c for c in distinct if c not in ("experience", "summary")]
    if strong:
        return strong[-1] if len(strong) > 1 else strong[0]
    return "experience" if "experience" in distinct else distinct[-1]


_VOCAB_CACHE = {}


def _heading_vocab(lex):
    """Words that make up section headings (for splitting "WORKEXPERIENCE" back into words)."""
    key = id(lex)
    hit = _VOCAB_CACHE.get(key)
    if hit is not None and hit[0] is lex:
        return hit[1]
    vocab = set(CORE_WORDS) | FILLER | set(getattr(lex, "core_words", {}) or {})
    for phrase in getattr(lex, "resume_headings", {}) or {}:
        vocab.update(w for w in phrase.split() if len(w) >= 2 and w.isalpha())
    _VOCAB_CACHE[key] = (lex, vocab)
    return vocab


def _segment(word, vocab):
    """Split a run of letters into heading words ("WORKEXPERIENCE" -> "WORK EXPERIENCE") when every
    piece is a known heading word; otherwise return it unchanged. Fewest pieces wins."""
    low = word.lower()
    if low in vocab or len(low) > 60:
        return word
    n = len(low)
    best = [None] * (n + 1)
    best[0] = []
    for i in range(n):
        if best[i] is None:
            continue
        for j in range(i + 2, n + 1):
            if low[i:j] in vocab and (best[j] is None or len(best[i]) + 1 < len(best[j])):
                best[j] = best[i] + [(i, j)]
    if not best[n] or len(best[n]) < 2:
        return word
    return " ".join(word[a:b] for a, b in best[n])


def heading_view(rl, lex):
    """The line as a heading reader should see it: letter-spaced runs closed up and split into words
    ("E D U C A T I O N" -> "EDUCATION", "W O R K E X P E R I E N C E" -> "WORK EXPERIENCE")."""
    if rl.htext is None:
        runs = letter_spaced_runs(rl.text) if rl.spaced else []
        if not runs:
            rl.htext = rl.text
        else:
            vocab = _heading_vocab(lex) if lex is not None else set(CORE_WORDS)
            parts, pos = [], 0
            for a, b in runs:
                parts.append(rl.text[pos:a])
                parts.append(_segment(rl.text[a:b].replace(" ", ""), vocab))
                pos = b
            parts.append(rl.text[pos:])
            rl.htext = "".join(parts)
    return rl.htext


def classify_heading(rl, lex):
    """Return heading info dict(section, standard, combined, text) or None. Letter-spaced headings are
    read with their spacing closed up; "text" keeps the line as written."""
    if rl.bullet:
        return None
    h = _classify(rl, lex, heading_view(rl, lex))
    if h is not None and rl.spaced:
        h["text"] = rl.text.strip().rstrip(":").strip().strip("*#_ ").strip() or h["text"]
    return h


def _classify(rl, lex, text):
    core = text.strip().rstrip(":").strip().strip("*#_ ").strip()
    if not core or len(core) > 45 or "@" in text or URL_RE.search(text) or core.endswith("."):
        return None
    ws = core.split()
    if not (1 <= len(ws) <= 6) or RANGE_RE.search(text):
        return None
    norm = norm_heading(core)
    if not norm:
        return None
    fmt = _fmt_signal(rl, core, len(ws))
    cmap = _core_map(lex)
    if norm in lex.resume_headings:
        return {"section": lex.resume_headings[norm], "standard": True, "combined": False, "text": core}
    if any(ch.isdigit() for ch in norm):
        return None
    raw_parts = [p for p in re.split(r"(?i)\s*(?:[,/|+;&]|\band\b)\s*", core) if p.strip()]
    if len(raw_parts) >= 2:
        mapped, unmapped = [], 0
        for p in raw_parts:
            pn = norm_heading(p)
            sec = lex.resume_headings.get(pn) or _core_section(pn, cmap)
            if sec:
                if sec not in mapped:
                    mapped.append(sec)
            elif not all(w in FILLER for w in pn.split()):
                unmapped += 1
        if mapped:
            all_mapped = unmapped == 0
            if len(mapped) >= 2 and (fmt or (all_mapped and _title_case(core))):
                return {"section": mapped[0], "standard": False, "combined": True, "text": core}
            if len(mapped) == 1 and unmapped and fmt:
                return {"section": mapped[0], "standard": False, "combined": True, "text": core}
            if len(mapped) == 1 and all_mapped and (fmt or _title_case(core)):
                return {"section": mapped[0], "standard": False, "combined": False, "text": core}
        return None
    nws = norm.split()
    cores = [cmap[w] for w in nws if w in cmap]
    if not cores:
        style = (rl.style or "").lower().replace(" ", "")
        if style in ("heading1", "heading01") and fmt:
            return {"section": "other", "standard": False, "combined": False, "text": core}
        return None
    others = [w for w in nws if w not in cmap]
    if all(w in FILLER for w in others) and len(nws) <= 4:
        ok = True
    else:
        ok = nws[-1] in cmap and (fmt or (len(nws) <= 3 and _title_case(core)))
    if not ok:
        return None
    return {"section": _choose(cores), "standard": False, "combined": False, "text": core}


def _inline_label(rl, lex):
    """"Skills: Python, SQL" style lines: the label names a section for this line only."""
    if rl.bullet:
        return None
    m = _INLINE_LABEL_RE.match(rl.text)
    if not m:
        return None
    sec = lex.resume_headings.get(norm_heading(m.group(1)))
    return sec if sec in _INLINE_SECTIONS else None


def assign_sections(lines, lex):
    """Set RLine.section/heading. Returns (detected, order)."""
    current = "contact"
    detected = []
    for rl in lines:
        h = classify_heading(rl, lex)
        if h:
            rl.heading = h
            rl.section = rl.block = h["section"]
            current = h["section"]
            detected.append({"heading": h["text"], "canonical": h["section"], "line": rl.idx,
                             "standard": h["standard"], "combined": h["combined"], "inline": False})
            continue
        rl.block = current
        sec = _inline_label(rl, lex)
        if sec and current != sec:
            rl.section = sec
            detected.append({"heading": rl.text.split(":", 1)[0].strip(), "canonical": sec, "line": rl.idx,
                             "standard": True, "combined": False, "inline": True})
            continue
        rl.section = current
    order = []
    for d in detected:
        if not d["inline"] and (not order or order[-1] != d["canonical"]):
            order.append(d["canonical"])
    return detected, order


def present_sections(detected):
    return sorted({d["canonical"] for d in detected if d["canonical"] in SECTIONS})
