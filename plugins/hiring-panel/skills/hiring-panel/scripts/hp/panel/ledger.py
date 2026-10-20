"""The evidence ledger: resume.md and the screening JD blocks as numbered lines (ARCHITECTURE.md 7).

    from hp.panel.ledger import build_ledger, apply_overrides
    ledger = build_ledger(resume_md_text, jd_blocks, target={"role_title", "role_level", "company", "locale"})
    ledger, log = apply_overrides(ledger, {"J3": "must"})

- R ids number the NON-EMPTY lines of resume.md in order, `[header]` / `[footer]` lines included.
  Text is kept verbatim (only surrounding whitespace and control characters are removed), so a
  reviewer's verbatim quote and the rewrite's evidence quote can always be found again.
  Section labels: a heading is recognized when it is one of the standard heading names in
  hp/data/headings.json (any case, so "Education" counts), when it is letter-spaced
  ("E D U C A T I O N" is read as EDUCATION; the text itself stays verbatim), or when it is a short
  capitalized / colon-ended line naming a known section. Before any heading, the top lines are contact
  lines, except that a school or degree line is labeled education.
- J ids number the non-empty lines of the JD blocks in order. The blocks come from the ONE job-posting
  classifier in hp.screen (screening.json inputs.job_description.blocks); this module never
  re-classifies the posting, it only maps block kinds to ledger kinds:
  required->must, preferred->nice, responsibility->responsibility, unspecified->other,
  boilerplate->logistics (location, schedule, pay, authorization, travel) or company (everything else,
  including benefits and EEO statements). An EEO statement is `company` in any block: it never says
  anything about the candidate, and reviewers are told to ignore it.
  A posting line that holds two or more sentences ("Requirements: High school diploma or GED. Current
  BLS/CPR certification.") becomes one J item per sentence (a leading "Label:" becomes its own item),
  so a reviewer can point at one requirement. The split is lossless: the texts of a line's J items,
  joined with single spaces, give back that line (whitespace runs between sentences become one space).
- Claude may correct kinds only through apply_overrides (logged in state.json by the CLI).
- The file is written compactly (one line per item, target and posting first) because reviewers read
  ledger.json as their only copy of the resume and the posting.

Pure functions, deterministic, never raise on garbage content (apply_overrides raises ValueError
for an unknown id or kind, by contract).
"""
import copy
import json
import os
import re

from hp.util import write_text
from hp.panel.common import (JD_KINDS, LEDGER_SECTIONS, SCHEMA_VERSION, PanelError, clean_str,
                             load_json_file, run_paths)

ROLE_LEVELS = ("intern", "entry", "mid", "senior", "unknown")

# Resume heading words -> ledger section. Matched on the normalized heading text (lowercase, '&' ->
# 'and', punctuation removed). Order matters: the first table entry with a hit wins.
_SECTION_WORDS = [
    ("summary", r"\b(summary|profile|objective|about me|personal statement|overview|highlights)\b"),
    ("education", r"\b(education|academics?|academic background|coursework|degrees?|schooling|"
                  r"ausbildung|formation|formacion)\b"),
    ("leadership", r"\b(leadership|activities|involvement|extracurriculars?|volunteer(ing)?|"
                   r"community service|clubs?|organizations?)\b"),
    ("projects", r"\b(projects?|portfolio|research|capstone|publications?)\b"),
    ("experience", r"\b(experience|employment|work history|internships?|career history|"
                   r"professional background|jobs?|berufserfahrung|experiences? professionnelles?|"
                   r"experiencia)\b"),
    ("skills", r"\b(skills?|technical|technologies|tools|competencies|languages|certifications?|"
               r"licen[cs]es?|kenntnisse|competences|habilidades)\b"),
    ("other", r"\b(awards?|honou?rs|achievements|interests|hobbies|references|referees|"
              r"additional|other)\b"),
]
_SECTION_RES = [(name, re.compile(rx)) for name, rx in _SECTION_WORDS]

_BULLET_START = re.compile("^\\s*(?:[-*\u2022\u25cf\u25aa\u25e6\u2023\u2219\u25a0\u25ba\u27a2\u2013]|\\d+[.)])\\s+")
_URLISH = re.compile(r"(?i)(https?://|www\.|@|\.com\b|\.org\b|\.edu\b|linkedin|github)")
_CONTACTISH = re.compile(r"(?i)(@|\+?\d[\d\s().-]{7,}\d|linkedin\.com|github\.com)")

# Posting lines. An EEO statement is never about the candidate: kind "company" in any block.
_EEO = re.compile(
    r"(?i)\b(equal (employment )?opportunit(y|ies)|eeo\b|affirmative action|without regard to|"
    r"regardless of (race|colou?r|religion|sex|gender|age|national|disability|veteran)|"
    r"discriminat\w*|protected (class|veteran|status)|gender identity|sexual orientation|"
    r"reasonable accommodations?|accommodations? (is|are) available|request an? accommodation)")
# Benefits and perks inside boilerplate are "company" (what the employer offers), not logistics.
_BENEFITS = re.compile(
    r"(?i)\b(benefits?|perks?|401\s?\(?k\)?|pto|paid time off|vacation|holidays?|insurance|dental|vision|"
    r"medical|health(care)? (plan|coverage)|wellness|tuition (assistance|reimbursement)|parental leave|"
    r"employee discounts?|retirement|pension)\b")
# Boilerplate lines about these topics are "logistics"; the rest of the boilerplate is "company".
_LOGISTICS = re.compile(
    r"(?i)\b(locat(ed|ion)s?|relocat\w*|remote|hybrid|on-?site|in[- ]office|in person|commut\w*|"
    r"schedules?|hours?|shifts?|weekends?|evenings?|full[- ]time|part[- ]time|start date|"
    r"duration|deadline|apply by|salary|salaries|compensation|pay|paid|wages?|stipend|"
    r"hourly|per hour|per year|annual|bonus(es)?|equity|"
    r"authori[sz](ed|ation)|sponsor(ship)?|visa|work permit|right to work|eligible to work|"
    r"citizens?(hip)?|clearance|travel|background check|drug (test|screen)|e-?verify)\b|\$\s?\d")

_KIND_MAP = {"required": "must", "preferred": "nice", "responsibility": "responsibility",
             "unspecified": "other"}


def _clean_line(line):
    """Strip surrounding whitespace and control characters; keep everything else verbatim."""
    line = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", line)
    return line.strip()


def _to_text(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value if isinstance(value, str) else ""


def _heading_key(line):
    """Heading lookup key, normalized like hp.screen's headings: casefold, curly quotes straightened,
    '&' -> 'and', punctuation (except apostrophes) removed, spaces collapsed."""
    s = line.strip().lstrip("#").strip()
    s = s.replace("\u2019", "'").replace("\u2018", "'").casefold()
    s = s.replace("&", " and ")
    s = re.sub(r"[^\w' ]+", " ", s).replace("_", " ")
    return re.sub(r"\s+", " ", s).strip(" '")


def collapse_letter_spacing(text):
    """'E D U C A T I O N' -> 'EDUCATION'; 'W O R K   E X P E R I E N C E' -> 'WORK EXPERIENCE'.
    Returns the text unchanged unless it is mostly single characters separated by spaces. Used only to
    recognize headings; the ledger keeps the verbatim text."""
    s = (text or "").strip()
    tokens = s.split()

    def spaced(toks):
        return sum(1 for t in toks if len(t) == 1 and (t.isalnum() or t == "&")) >= 0.8 * len(toks)

    if len(tokens) < 3 or not spaced(tokens):
        return s
    words = [w for w in re.split(r"\s{2,}", s) if w.strip()]
    if len(words) > 1 and all(spaced(w.split()) for w in words):
        return " ".join("".join(w.split()) for w in words)
    return "".join(tokens)


# headings.json resume section -> ledger section
_HEADING_SECTIONS = {
    "contact": "contact", "summary": "summary", "experience": "experience", "education": "education",
    "coursework": "education", "skills": "skills", "certifications": "skills", "languages": "skills",
    "projects": "projects", "publications": "projects", "leadership_activities": "leadership",
    "volunteer": "leadership", "awards": "other", "interests": "other", "references": "other",
    "other": "other",
}
_FALLBACK_SYNONYMS = {
    "contact": ["contact", "contact information", "contact info", "contact details", "personal information"],
    "summary": ["summary", "professional summary", "profile", "objective", "career objective", "about me"],
    "experience": ["experience", "work experience", "professional experience", "employment", "work history",
                   "relevant experience", "work", "internships", "research experience"],
    "education": ["education", "academic background", "academics", "education and training"],
    "coursework": ["coursework", "relevant coursework", "courses"],
    "skills": ["skills", "technical skills", "core competencies", "competencies", "technologies", "tools",
               "skills and interests"],
    "certifications": ["certifications", "certificates", "licenses", "licenses and certifications"],
    "languages": ["languages"],
    "projects": ["projects", "academic projects", "personal projects", "research projects", "portfolio"],
    "publications": ["publications"],
    "leadership_activities": ["leadership", "activities", "leadership and activities", "involvement",
                              "extracurricular activities", "clubs", "organizations"],
    "volunteer": ["volunteer", "volunteer experience", "volunteering", "community service"],
    "awards": ["awards", "honors", "honors and awards", "achievements"],
    "interests": ["interests", "hobbies"],
    "references": ["references"],
    "other": ["additional information", "other"],
}
_SYNONYMS = None


def _heading_synonyms():
    """{normalized heading: ledger section}, read once from hp/data/headings.json when present (the
    lexicon the screening check uses), else a small built-in list. Never raises."""
    global _SYNONYMS
    if _SYNONYMS is not None:
        return _SYNONYMS
    table = _FALLBACK_SYNONYMS
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "headings.json")
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
        resume = data.get("resume") if isinstance(data, dict) else None
        if isinstance(resume, dict) and resume:
            table = resume
    except (OSError, ValueError):
        pass
    out = {}
    for name, syns in sorted(table.items()):
        sec = _HEADING_SECTIONS.get(name)
        if sec is None or not isinstance(syns, list):
            continue
        for syn in syns:
            if isinstance(syn, str) and _heading_key(syn):
                out.setdefault(_heading_key(syn), sec)
    _SYNONYMS = out
    return out


def _looks_like_heading(line):
    """ATS-spec style heading test: short, no contact/URL, not a bullet, no final period, and either
    mostly capitals, a markdown '#', or a short line ending with ':'."""
    s = line.strip()
    if not s or len(s) > 45 or _URLISH.search(s) or _BULLET_START.match(s) or s.endswith("."):
        return False
    if s.startswith("#"):
        return True
    words = s.rstrip(":").split()
    if not 1 <= len(words) <= 6:
        return False
    letters = [c for c in s if c.isalpha()]
    if letters and sum(1 for c in letters if c.isupper()) / float(len(letters)) >= 0.8:
        return True
    return s.endswith(":") and len(words) <= 4


def _heading_section(line):
    """Return the ledger section for a heading line, or None if the line is not a known heading.
    A standard heading name (headings.json) counts in any case ("Education", "Work"); a letter-spaced
    heading is read with its spacing collapsed; other headings must look like headings (capitals, '#'
    or a trailing ':') and contain a known section word."""
    raw = line.strip()
    if not raw or _BULLET_START.match(raw):
        return None
    collapsed = collapse_letter_spacing(raw.lstrip("#").strip())
    if not collapsed or len(collapsed) > 45 or _URLISH.search(collapsed) or collapsed.endswith("."):
        return None
    key = _heading_key(collapsed.rstrip(":"))
    if not key:
        return None
    synonyms = _heading_synonyms()
    if key in synonyms:
        return synonyms[key]
    if collapsed != raw.lstrip("#").strip():
        squashed = key.replace(" ", "")
        for syn in sorted(synonyms):
            if syn.replace(" ", "") == squashed:
                return synonyms[syn]
    if not _looks_like_heading(("#" if raw.startswith("#") else "") + collapsed):
        return None
    for name, rx in _SECTION_RES:
        if rx.search(key):
            return name
    return None


# A school or degree line in the top block (before any heading) is education, not contact.
_EDU_LINE = re.compile(
    r"(?i)\b(universit(y|ies)|college|institute of|school of|polytechnic|academy|"
    r"bachelor'?s?|master'?s?|associate'?s? degree|ph\.?\s?d|mba|b\.\s?[as]\.|b\.?sc|m\.\s?[as]\.|"
    r"diploma|gpa|expected (graduation|grad|may|june|december|dec|[a-z]+ \d{4})|graduat(ing|ion)|"
    r"class of \d{4}|pre-?(nursing|med|law))\b")


def _resume_lines(resume_md_text):
    out, section, seen_heading, top_lines = [], "contact", False, 0
    text = _to_text(resume_md_text).replace("\r\n", "\n").replace("\r", "\n")
    for raw in text.split("\n"):
        line = _clean_line(raw)
        if not line:
            continue
        low = line.lower()
        if low.startswith("[header]") or low.startswith("[footer]"):
            sec = "header_footer"
        else:
            body = line[len("[text box]"):].strip() if low.startswith("[text box]") else line
            new = _heading_section(body)
            if new:
                section, seen_heading = new, True
                sec = new
            elif not seen_heading:
                # The top block holds the name and contact details; without any headings at all,
                # only the first few lines are treated as the top block. A school or degree line before
                # any heading is education, not contact.
                top_lines += 1
                if _EDU_LINE.search(body) and not _CONTACTISH.search(body):
                    sec = "education"
                else:
                    sec = "contact" if (top_lines <= 5 or _CONTACTISH.search(body)) else "other"
            elif low.startswith("[text box]") and _CONTACTISH.search(body):
                sec = "contact"
            else:
                sec = section
        out.append({"id": "R{}".format(len(out) + 1), "section": sec, "text": line})
    return out


_ABBREVIATIONS = frozenset((
    "inc", "ltd", "co", "corp", "llc", "dr", "mr", "mrs", "ms", "jr", "sr", "st", "no", "vs", "etc",
    "approx", "incl", "dept", "univ", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept",
    "oct", "nov", "dec", "min", "max", "yrs", "hrs", "mo", "est", "fig", "ave", "blvd", "mt", "ft", "pp"))
_CLOSERS = "\"')]\u201d\u2019"
_SENTENCE_START = re.compile("^[\"'(\\[\u201c\u2018]?[A-Z0-9]")
_LABEL = re.compile(r"^([A-Za-z][A-Za-z '&/()-]{0,38}):\s+(?=\S)")


def _is_abbreviation(token):
    t = token.rstrip(_CLOSERS).lower()
    if not t.endswith("."):
        return False
    core = t[:-1]
    if re.match(r"^([a-z]\.)*[a-z]$", core):      # single initials and dotted abbreviations: A. U.S. e.g. B.S.
        return True
    return core.split(".")[-1] in _ABBREVIATIONS


def split_sentences(line):
    """Split one posting line into sentence-sized pieces (a leading "Label:" becomes its own piece).
    Returns [line] when the line holds fewer than two sentences. Pieces are stripped; joined with single
    spaces they give back the line with the whitespace between sentences collapsed to one space."""
    pieces, start = [], 0
    for m in re.finditer(r"\s+", line):
        before = line[start:m.start()]
        after = line[m.end():]
        if not before.strip() or not after:
            continue
        prev = before.rstrip(_CLOSERS)
        if not prev or prev[-1] not in ".!?" or not _SENTENCE_START.match(after):
            continue
        if prev[-1] == "." and _is_abbreviation(before.split()[-1]):
            continue
        pieces.append(line[start:m.start()].strip())
        start = m.end()
    pieces.append(line[start:].strip())
    pieces = [p for p in pieces if p]
    if len(pieces) < 2:
        return [line]
    m = _LABEL.match(pieces[0])
    if m and len(m.group(1).split()) <= 4 and not re.search(r"\d", m.group(1)):
        pieces = [pieces[0][:m.end()].strip(), pieces[0][m.end():].strip()] + pieces[1:]
    return [p for p in pieces if p]


def _jd_kind(kind_in, text):
    if _EEO.search(text):
        return "company"
    if kind_in == "boilerplate":
        if _BENEFITS.search(text):
            return "company"
        return "logistics" if _LOGISTICS.search(text) else "company"
    return _KIND_MAP.get(kind_in, "other") if isinstance(kind_in, str) else "other"


def _jd_items(jd_blocks):
    out = []
    if not isinstance(jd_blocks, list):
        return out
    for b_index, block in enumerate(jd_blocks):
        if not isinstance(block, dict):
            continue
        kind_in = block.get("kind")
        lines = block.get("lines")
        if isinstance(lines, str):
            lines = lines.split("\n")
        if not isinstance(lines, list):
            continue
        for raw in lines:
            if not isinstance(raw, str):
                continue
            for part in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
                line = _clean_line(part)
                if not line:
                    continue
                for piece in split_sentences(line):
                    out.append({"id": "J{}".format(len(out) + 1), "kind": _jd_kind(kind_in, piece),
                                "block": b_index, "text": piece})
    return out


def _target(target, general_review):
    t = target if isinstance(target, dict) else {}
    level = t.get("role_level") if t.get("role_level") in ROLE_LEVELS else "unknown"
    company = clean_str(t.get("company"), 120) or None
    locale = clean_str(t.get("locale"), 20) or "en-US"
    return {"role_title": clean_str(t.get("role_title"), 160), "role_level": level,
            "company": company, "locale": locale, "general_review": general_review}


def build_ledger(resume_md_text, jd_blocks, target=None):
    """Build the ledger dict from resume.md text and the screening JD blocks.

    `target` keys: role_title, role_level (intern|entry|mid|senior|unknown), company, locale and,
    optionally, general_review (bool). When general_review is not given it is True exactly when the
    posting yields no J lines.
    """
    resume_lines = _resume_lines(resume_md_text)
    jd_items = _jd_items(jd_blocks)
    gr = target.get("general_review") if isinstance(target, dict) else None
    general_review = gr if isinstance(gr, bool) else not jd_items
    if general_review:
        jd_items = []     # a general review never cites a posting
    return {"schema_version": SCHEMA_VERSION, "resume_lines": resume_lines, "jd_items": jd_items,
            "target": _target(target, general_review)}


def _parse_overrides(overrides):
    """Accept {"J3": "must"}, [("J3", "must")] or ["J3=must"]; return an ordered list of pairs."""
    pairs = []
    if isinstance(overrides, dict):
        pairs = list(overrides.items())
    elif isinstance(overrides, (list, tuple)):
        for item in overrides:
            if isinstance(item, str) and "=" in item:
                k, _, v = item.partition("=")
                pairs.append((k.strip(), v.strip()))
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                pairs.append((item[0], item[1]))
            else:
                raise ValueError("override must look like J3=must, got {!r}".format(item))
    elif overrides is not None:
        raise ValueError("overrides must be a dict like {'J3': 'must'}")
    return pairs


def apply_overrides(ledger, overrides):
    """Change JD line kinds only. Returns (new_ledger, log) where log is
    [{"id": "J3", "from": "other", "to": "must"}] in the order given. The input ledger is not modified.
    Raises ValueError for an unknown id, a resume (R) id, or a kind outside
    must|nice|responsibility|company|logistics|other."""
    if not isinstance(ledger, dict) or not isinstance(ledger.get("jd_items"), list):
        raise ValueError("not a ledger: jd_items missing")
    new = copy.deepcopy(ledger)
    index = {}
    for item in new["jd_items"]:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            index[item["id"]] = item
    log = []
    for key, kind in _parse_overrides(overrides):
        if not isinstance(key, str) or not re.match(r"^J[0-9]+$", key.strip()):
            raise ValueError("only job-posting lines (J#) have kinds; got {!r}".format(key))
        key = key.strip()
        if key not in index:
            raise ValueError("no job-posting line {} in this ledger".format(key))
        if kind not in JD_KINDS:
            raise ValueError("kind must be one of {}; got {!r}".format(", ".join(JD_KINDS), kind))
        old = index[key].get("kind")
        index[key]["kind"] = kind
        log.append({"id": key, "from": old, "to": kind})
    return new, log


def jd_blocks_from_screening(screening):
    """Return the JD blocks from a screening.json dict ([] when absent or malformed)."""
    try:
        blocks = screening["inputs"]["job_description"]["blocks"]
    except (KeyError, TypeError):
        return []
    return blocks if isinstance(blocks, list) else []


def build_run_ledger(run_dir, target, overrides=None):
    """Convenience for the CLI: read work/inputs/resume.md and the before-screening JD blocks, build
    the ledger, re-apply any overrides (e.g. state.json ledger_overrides), write
    work/inputs/ledger.json and return (ledger, override_log)."""
    paths = run_paths(run_dir)
    try:
        with open(paths["resume_md"], "rb") as f:
            resume_text = f.read(8 * 1024 * 1024).decode("utf-8", "replace")
    except OSError:
        raise PanelError("resume.md not found at {}".format(paths["resume_md"]))
    screening, err = load_json_file(paths["screening"])
    blocks = jd_blocks_from_screening(screening) if not err else []
    ledger = build_ledger(resume_text, blocks, target)
    log = []
    if overrides:
        pairs = []
        for o in overrides if isinstance(overrides, list) else [overrides]:
            if isinstance(o, dict) and "id" in o and "to" in o:
                pairs.append((o["id"], o["to"]))
            elif isinstance(o, dict):
                pairs.extend(o.items())
            else:
                pairs.append(o)
        ledger, log = apply_overrides(ledger, pairs)
    write_text(paths["ledger"], ledger_to_text(ledger))
    return ledger, log


def ledger_to_text(ledger):
    """ledger.json text: one line per R/J item (reviewers read this file as their only copy of the
    resume and the posting, so it stays compact), target and posting first. json.loads gives back the
    same dict as build_ledger. Deterministic."""
    def dump(x):
        return json.dumps(x, ensure_ascii=False)

    def items(key):
        rows = ledger.get(key) if isinstance(ledger.get(key), list) else []
        if not rows:
            return "[]"
        return "[\n" + ",\n".join("  " + dump(r) for r in rows) + "\n ]"

    head = ['"schema_version": ' + dump(ledger.get("schema_version", SCHEMA_VERSION)),
            '"target": ' + dump(ledger.get("target"))]
    rest = ['"jd_items": ' + items("jd_items"), '"resume_lines": ' + items("resume_lines")]
    extra = ['{}: {}'.format(dump(k), dump(v)) for k, v in ledger.items()
             if k not in ("schema_version", "target", "jd_items", "resume_lines")]
    return "{" + ",\n ".join(head + extra + rest) + "}\n"


def kinds_summary(ledger):
    """Counts per JD kind, for the init/ledger CLI output: {"must": 3, "nice": 1, ...}."""
    counts = dict((k, 0) for k in JD_KINDS)
    for item in ledger.get("jd_items") if isinstance(ledger.get("jd_items"), list) else []:
        if isinstance(item, dict) and item.get("kind") in counts:
            counts[item["kind"]] += 1
    return counts


__all__ = ["build_ledger", "apply_overrides", "build_run_ledger", "jd_blocks_from_screening",
           "kinds_summary", "ledger_to_text", "split_sentences", "collapse_letter_spacing",
           "LEDGER_SECTIONS", "ROLE_LEVELS"]
