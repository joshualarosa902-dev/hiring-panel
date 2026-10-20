"""Deterministic truth check: does every fact in the rewritten resume come from the candidate?

    from hp.rewrite.truth import check_truth
    truth = check_truth(ledger, answers, resume)     # -> work/rewrite/truth.json

Sources of truth (and nothing else):
  * ledger["resume_lines"]  R1..Rn, the verbatim text of the uploaded resume
  * answers["answers"]      Q1..Qn, but only answers the student actually gave (status "answered");
                            for kind "keywords" items answered "yes" or "some" count (term + detail), and the
                            free text (including a "no" item's detail) can back OTHER facts: every term
                            answered "no" is masked out, so it can never be cited
The job posting (ledger["jd_items"], J#) is NEVER evidence: it only supplies wording for things the
candidate already showed.

What it checks (error codes):
  ENTITY_NOT_IN_SOURCE    employer, school, title, degree, location, project name, honor or course is new
  DATE_NOT_IN_SOURCE      a year (or "present") the source does not have
  DATE_PRECISION_ADDED    a month where the source only had a season or a year
  NUMBER_NOT_IN_SOURCE    a number (or a %/$ amount) absent from the bullet's own evidence
  TERM_NOT_IN_SOURCE      a tool, brand or proper noun absent from the bullet's evidence
  SKILL_NOT_IN_SOURCE     a skills-list item (or a proficiency word) the candidate never showed
  OWNERSHIP_UPGRADED      a stronger ownership verb than the source ("helped" -> "led")
  HEDGE_REMOVED           "about 600" -> "600", "about 20 to about 60" -> "20 to 60", "around 3 or 4" -> "4"
                          (hedges and ranges from resume lines AND answers), "3" -> "3+", "some weekends" ->
                          "every weekend", "SQL (class)" -> "SQL", or a keyword answered "some" without a qualifier
  HEADING_CLAIM           a section title word that is neither a standard heading word nor in the lines the
                          section cites ("Clinical Experience" over a grocery job); honest labels such as
                          "Family Caregiving" pass when the cited answer shows them (references/edge-cases.md)
  BAD_ANSWERS             answers.json does not match schemas/answers.schema.json (where = the JSON path)
  BAD_RESUME_SCHEMA       resume.json does not match schemas/resume.schema.json (where = the JSON path)
  EVIDENCE_QUOTE_NOT_FOUND  a quote that is not in the cited line or answer
  NO_EVIDENCE             a bullet (or summary) with no usable evidence
  PLACEHOLDER_LEFT        {{p}} / [ADD: ...] left, or a placeholder without textIfUnknown
  CONTACT_CHANGED         name, email, phone, location or link differs from the source
  JD_AS_EVIDENCE          evidence that cites or quotes the job posting
  BAD_REF                 a malformed, unknown or mismatched R#/Q# reference (or a declined answer)
  INVALID_INPUT           (deviation) input that is not the expected JSON shape
Warnings (the model audit and the provenance audit read these):
  NEW_WORDING             content words that are not in the bullet's evidence
  HEADLINE_NEW_WORD       headline words that are not anywhere in the source
  UNLISTED_CUT            (deviation) a source line that is neither used nor listed in meta.cuts

Deterministic: same inputs give the same dict (errors in document order). Never raises.
"""
import functools
import json
import os
import re

from .. import util

# ----------------------------------------------------------------------------------------------
# Vocabulary
# ----------------------------------------------------------------------------------------------
STOP = set("""a an the and or but nor of to in on at for with by from as into onto over under about
across per via is are was were be been being am this that these those it its their our my your his her
them they we i you he she while during through within without after before ahead than then so such
more most less least very each every some any all other new using used use also both either which
who whom whose what when where how why not no yes can could will would should may might must has have
had do does did done up down out off again further once here there just only own same too s t""".split())

NUM_WORDS_SOURCE = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
                    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
                    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
                    "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100, "thousand": 1000,
                    "both": 2, "twice": 2, "pair": 2, "couple": 2, "dozen": 12, "first": 1, "second": 2,
                    "third": 3, "half": 50, "single": 1, "once": 1, "solo": 1}
# In a rewritten bullet only clear cardinals count as numbers ("first-year" or "one of" are not claims).
NUM_WORDS_BULLET = {k: v for k, v in NUM_WORDS_SOURCE.items()
                    if k not in ("zero", "one", "first", "second", "third", "half", "single", "once",
                                 "solo", "both", "pair", "couple")}

ABBREV = {"sr": "senior", "jr": "junior", "mgr": "manager", "asst": "assistant", "assoc": "associate",
          "coord": "coordinator", "eng": "engineer", "engr": "engineer", "dev": "developer",
          "rep": "representative", "dept": "department", "univ": "university", "co": "company",
          "corp": "corporation", "inc": "incorporated", "intl": "international", "mktg": "marketing",
          "admin": "administrative", "tech": "technician", "bba": "bachelor of business administration",
          "bs": "bachelor of science", "bsc": "bachelor of science", "ba": "bachelor of arts",
          "ms": "master of science", "msc": "master of science", "ma": "master of arts",
          "mba": "master of business administration", "bfa": "bachelor of fine arts",
          "bsn": "bachelor of science in nursing", "beng": "bachelor of engineering",
          "cs": "computer science", "st": "street", "ave": "avenue", "&": "and"}
US_STATES = {"AL": "alabama", "AK": "alaska", "AZ": "arizona", "AR": "arkansas", "CA": "california",
             "CO": "colorado", "CT": "connecticut", "DE": "delaware", "DC": "district of columbia",
             "FL": "florida", "GA": "georgia", "HI": "hawaii", "ID": "idaho", "IL": "illinois",
             "IN": "indiana", "IA": "iowa", "KS": "kansas", "KY": "kentucky", "LA": "louisiana",
             "ME": "maine", "MD": "maryland", "MA": "massachusetts", "MI": "michigan", "MN": "minnesota",
             "MS": "mississippi", "MO": "missouri", "MT": "montana", "NE": "nebraska", "NV": "nevada",
             "NH": "new hampshire", "NJ": "new jersey", "NM": "new mexico", "NY": "new york",
             "NC": "north carolina", "ND": "north dakota", "OH": "ohio", "OK": "oklahoma", "OR": "oregon",
             "PA": "pennsylvania", "RI": "rhode island", "SC": "south carolina", "SD": "south dakota",
             "TN": "tennessee", "TX": "texas", "UT": "utah", "VT": "vermont", "VA": "virginia",
             "WA": "washington", "WV": "west virginia", "WI": "wisconsin", "WY": "wyoming"}
MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep",
                                          "oct", "nov", "dec"])}

# Ownership ladder (sideways moves only). Tier 1 < 2 < 3 < 4.
TIER = {}
for _w in ("participated participate participating assisted assist assisting helped help helping supported "
           "support supporting shadowed shadow observed attended joined volunteered").split():
    TIER[_w] = 1
for _w in ("contributed contribute created create built build analyzed analysed analyze designed design trained "
           "train developed develop wrote write made make produced produce prepared prepare implemented "
           "implement conducted conduct researched research presented present planned plan tracked track "
           "drafted draft edited edit tested test ran run taught teach tutored tutor mentored mentor").split():
    TIER[_w] = 2
for _w in ("coordinated coordinate coordinating organized organised organize organizing launched launch "
           "initiated initiate drove drive championed champion facilitated facilitate").split():
    TIER[_w] = 3
for _w in ("led lead leading managed manage managing directed direct directing supervised supervise "
           "supervising oversaw oversee overseeing headed head spearheaded spearhead founded found "
           "established establish owned own chaired chair captained captain presided preside").split():
    TIER[_w] = 4
# Verbs that are also common nouns or adjectives: only judged in a bullet's opening words.
AMBIGUOUS_TOP = {"lead", "leading", "head", "found", "own", "direct", "chair", "captain", "present", "design",
                 "research", "test", "draft", "plan", "track", "run", "support", "help", "edit", "launch",
                 "drive", "champion", "establish"}
TITLE_TIER = {"president": 4, "captain": 4, "chair": 4, "chairperson": 4, "chairman": 4, "chairwoman": 4,
              "head": 4, "lead": 4, "leader": 4, "manager": 4, "founder": 4, "cofounder": 3, "director": 4,
              "supervisor": 4, "owner": 4, "coordinator": 3, "officer": 3, "treasurer": 3, "secretary": 3,
              "vice": 3, "organizer": 3}
HELPERS = {"helped", "help", "helping", "assisted", "assist", "assisting", "supported", "supporting",
           "participated", "participating", "contributed", "contributing"}
HELPER_MARKERS = HELPERS | {"collaborated", "collaborating", "partnered", "jointly", "alongside", "team",
                            "teams", "member", "members", "together", "group", "assist", "support", "contribute",
                            "participate"}
VERB_HINTS = set(TIER) | set("""plan organize run create build design develop launch manage lead write
coordinate analyze research prepare host market promote recruit train implement conduct edit produce test
set raise grow increase improve reduce deliver execute draft review make sell open close update maintain
track monitor collect gather compile clean process handle answer schedule book order stock count serve
teach tutor mentor coach present pitch survey interview evaluate assess audit file enter record code
program debug deploy configure install repair fix plant design shoot photograph film edit post""".split())
ABSOLUTES = {"every", "all", "always", "each", "entire", "whole", "sole", "solely", "fully", "daily", "every-day",
             "independently", "single-handedly", "singlehandedly", "alone"}
QUALIFIERS = {"some", "sometimes", "occasionally", "occasional", "few", "several", "partly", "partially",
              "part", "helped", "assisted", "as-needed", "needed", "times", "on-call", "rotating", "most"}
SKILL_QUALIFIERS = {"class", "classes", "course", "courses", "coursework", "basic", "basics", "beginner",
                    "learning", "familiar", "familiarity", "academic", "school", "some", "exposure",
                    "introductory", "intro"}
PROFICIENCY = {"advanced", "expert", "proficient", "proficiency", "fluent", "fluency", "native", "bilingual",
               "intermediate", "strong", "extensive", "mastery", "certified", "senior", "professional"}
NON_ANSWERS = {"", "not sure", "unsure", "skip", "skipped", "no", "n/a", "na", "none", "idk", "i don't know",
               "dont know", "don't know", "pass", "-", "?"}

# Tools and platforms that must never appear without evidence, even in lowercase. hp/data/skills.json
# (hard/tool/cert entries) extends this list when present.
BUILTIN_TOOLS = {
    "sql", "mysql", "postgresql", "python", "java", "javascript", "typescript", "tableau", "power bi", "powerbi",
    "looker", "salesforce", "hubspot", "marketo", "kubernetes", "docker", "terraform", "aws", "azure", "gcp",
    "figma", "photoshop", "illustrator", "indesign", "premiere pro", "after effects", "jira", "confluence",
    "github", "gitlab", "django", "pandas", "numpy", "hadoop", "snowflake",
    "dbt", "stata", "spss", "sas", "matlab", "autocad", "solidworks", "revit", "quickbooks",
    "netsuite", "google analytics", "google ads", "semrush", "mailchimp", "hootsuite", "sprout social",
    "asana", "trello", "zapier", "wordpress", "shopify", "linux", "kotlin", "golang", "scala", "c++",
    "c#", "vba", "a/b testing", "seo", "sem", "crm", "erp", "cpa", "cfa", "pmp", "lean six sigma", "six sigma",
    "cerner", "hipaa", "osha", "gaap", "ifrs"}
# Words that look like proper nouns because of capitals but are dates or common context labels.
CALENDAR_WORDS = {"january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
                  "november", "december", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct",
                  "nov", "dec", "spring", "summer", "fall", "autumn", "winter", "monday", "tuesday", "wednesday",
                  "thursday", "friday", "saturday", "sunday", "present", "expected"}
CONTEXT_WORDS = {"course", "class", "project", "team", "group", "personal", "academic", "capstone", "independent",
                 "senior", "junior", "hackathon", "research", "thesis", "club", "volunteer", "internship", "part-time",
                 "full-time", "contract", "freelance", "school", "university", "college", "program", "coursework",
                 "assignment", "competition", "lab", "studio", "seminar", "honors", "final", "side", "solo"}

HEDGE_APPROX = re.compile(r"(?<![a-z])(?:about|around|approximately|approx\.?|roughly|circa|ca\.|~|an estimated|"
                          r"estimated|est\.|some|maybe|perhaps|probably|almost exactly)\s*$")
HEDGE_LOWER = re.compile(r"(?<![a-z])(?:over|more than|at least|upwards of|in excess of|north of|above|beyond)\s*$")
HEDGE_UPPER = re.compile(r"(?<![a-z])(?:nearly|almost|up to|under|less than|fewer than|close to|just under|below|"
                         r"not quite|shy of)\s*$")
NUM_RE = re.compile(r"(?<![\w.])(\$|£|€)?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?"
                    r"(?:\s?(k|m|bn|million|billion|thousand|%|percent|x)(?![a-z]))?(\+)?", re.I)
# What may sit between the two ends of a range or an alternative: "50-100", "20 to 60", "3 or 4",
# "between 20 and 60" (the second end's own hedge word, as in "about 20 to about 60", is skipped first).
GROUP_MID_RE = re.compile(r"^\s*(?:-|to|or|through|thru)\s*$")
GROUP_AND_RE = re.compile(r"^\s*and\s*$")
BETWEEN_RE = re.compile(r"(?<![a-z])between\s*$")
FROM_RE = re.compile(r"(?<![a-z])from\s*$")
# "over 10 weeks" usually means "during", not "more than": never read as a hedge in either direction.
TIME_UNIT_RE = re.compile(r"^\s*(?:days?|weeks?|months?|years?|semesters?|quarters?|terms?|summers?|weekends?|"
                          r"sessions?)\b")
NEXT_SKIP = {"a", "an", "the", "of", "or", "so", "ish", "to", "and", "more", "plus", "per", "new", "x", "k",
             "percent", "about", "around", "than", "up", "over", "nearly", "almost", "roughly"}

# Honest labels (references/edge-cases.md): allowed as a role, org or name, or in a section title, only when
# the lines the entry or section cites show them. label -> (what must be shown, [patterns that must all match]).
_CARE = re.compile(r"\b(?:take|takes|taking|took|taken) care of\b|\bcar(?:e|es|ed|ing) for\b|\bcaregiv|"
                   r"\blook(?:s|ed|ing)? after\b|\bhelp(?:s|ed|ing)? (?:to )?care\b")
_FAMILY = re.compile(r"\b(?:family|grandma|grandmother|grandpa|grandfather|grandparents?|granny|nana|abuela|abuelo|"
                     r"mom|mother|dad|father|parents?|brothers?|sisters?|siblings?|aunt|uncle|cousins?|sons?|"
                     r"daughters?|husband|wife|relatives?|stepmom|stepdad|stepmother|stepfather)\b")
_VOLUNTEER = re.compile(r"\bvolunteer|\bunpaid\b|\bcommunity service\b")
_STUDENT = re.compile(r"\bstudents?\b|\buniversity\b|\bcollege\b|\bschool\b|\bfirst[- ]year\b|\bfreshman\b|"
                      r"\bsophomore\b|\bgraduat|\bmajor\b|\bstudying\b|\benrolled\b|\bdegree\b|\bclass(?:es)?\b")
_FREELANCE = re.compile(r"\bfreelanc|\bclients?\b|\bcommissions?\b|\bgigs?\b|\bcontract work\b")
_SELF = re.compile(r"\bself[- ]employed\b|\bmy own (?:business|company|shop|store|brand)\b|\bfor myself\b|"
                   r"\b(?:ran|run|started|start|own|owned) my own\b|\bmy business\b|\bfreelanc|\bclients?\b")
_PERSONAL = re.compile(r"\bpersonal\b|\bon my own\b|\bby myself\b|\bfor fun\b|\bside project|\bmy own\b|\bhobby\b")
HONEST_LABELS = {
    "family caregiver": ("an answer or line saying you care for a family member", [_CARE, _FAMILY]),
    "family caregiving": ("an answer or line saying you care for a family member", [_CARE, _FAMILY]),
    "caregiver": ("an answer or line saying you care for someone", [_CARE]),
    "caregiving": ("an answer or line saying you care for someone", [_CARE]),
    "volunteer": ("an answer or line saying you volunteered", [_VOLUNTEER]),
    "volunteering": ("an answer or line saying you volunteered", [_VOLUNTEER]),
    "volunteer work": ("an answer or line saying you volunteered", [_VOLUNTEER]),
    "student": ("a school line or answer", [_STUDENT]),
    "full-time student": ("a school line or answer", [_STUDENT]),
    "part-time student": ("a school line or answer", [_STUDENT]),
    "freelancer": ("an answer or line saying you did freelance or client work", [_FREELANCE]),
    "freelance": ("an answer or line saying you did freelance or client work", [_FREELANCE]),
    "freelance work": ("an answer or line saying you did freelance or client work", [_FREELANCE]),
    "self-employed": ("an answer or line saying you worked for yourself", [_SELF]),
    "personal project": ("an answer or line saying it was your own project", [_PERSONAL]),
    "personal projects": ("an answer or line saying it was your own project", [_PERSONAL]),
}
# Words any section title may use. Words that claim a kind of work (clinical, research, teaching, internship,
# athletics...) are NOT here: they must come from the lines the section cites or from the resume's own headings.
STANDARD_HEADING_WORDS = set("""education experience work employment history professional relevant related additional
other selected key core notable academic projects project skills skill technical tools technologies software computer
activities activity leadership involvement campus extracurricular extracurriculars community service volunteer
volunteering summary profile objective certifications certification certificates certificate licenses license
licensure credentials awards award honors honours achievements scholarships languages language interests
publications presentations coursework courses information references training organizations clubs memberships
affiliations development hobbies qualifications highlights accomplishments recognition competencies portfolio
part full time and of the in for""".split())


def honest_label(value):
    key = re.sub(r"\s+", " ", re.sub(r"[-‐–]", "-", _s(value).casefold())).strip(" .,:;")
    key = key.replace("self employed", "self-employed").replace("full time", "full-time").replace("part time",
                                                                                                    "part-time")
    return key if key in HONEST_LABELS else None


def label_supported(label, cited_text):
    text = _norm(cited_text)
    return bool(text) and all(rx.search(text) for rx in HONEST_LABELS[label][1])
REF_RE = re.compile(r"^(?:R(\d+)(?:\s*-\s*R?(\d+))?|Q(\d+))$")
JD_REF_RE = re.compile(r"^J\d+(?:\s*-\s*J?\d+)?$")
PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")
LEFTOVER_RE = re.compile(r"\{\{|\}\}|\[ADD\b|\[X\]|\bXX+\b|\bTBD\b|\bTODO\b", re.I)
LINE_PREFIX_RE = re.compile(r"^\[(?:header|footer|text box)\]\s*", re.I)
CAP_TERM_RE = re.compile(r"(?<![\w'])([A-Z][A-Za-z0-9+#]*(?:[./-][A-Za-z0-9+#]+)*\+*|[a-z]+[A-Z][A-Za-z0-9]*|"
                         r"[A-Za-z]*\d[A-Za-z0-9]*[A-Za-z][A-Za-z0-9]*)")


# ----------------------------------------------------------------------------------------------
# Text helpers
# ----------------------------------------------------------------------------------------------
def _s(x):
    if x is None:
        return ""
    return x if isinstance(x, str) else str(x)


def _norm(s):
    """NFKC, straight quotes, dash family -> '-', casefolded, single spaces."""
    s = util.norm_text(_s(s)).replace("–", "-")
    return re.sub(r"\s+", " ", s.casefold()).strip()


def _expand_states(s):
    return re.sub(r"\b([A-Z]{2})\b", lambda m: US_STATES.get(m.group(1), m.group(1)), _s(s))


def tokens(s):
    """Lowercased word tokens; hyphens and slashes split words; 'co-led' stays one token; B.S. -> bs."""
    s = _expand_states(util.norm_text(_s(s)))
    s = re.sub(r"(?i)\bco-(?=[a-z])", "co", s)
    s = re.sub(r"[-–/_|]", " ", s.casefold())
    out = []
    for t in re.findall(r"[a-z0-9À-￿][a-z0-9À-￿+#'.]*[a-z0-9À-￿+#]|[a-z0-9À-￿]", s):
        t = t.strip(".'")
        if re.match(r"^(?:[a-z]\.)+[a-z]$", t):
            t = t.replace(".", "")
        if t.endswith("'s"):
            t = t[:-2]
        if t:
            out.append(t)
    return out


def expand(toks):
    out = []
    for t in toks:
        out.extend(ABBREV.get(t, t).split())
    return out


def phrase_str(s):
    return " " + " ".join(expand(tokens(s))) + " "


@functools.lru_cache(maxsize=4096)
def _needle(needle):
    toks = expand(tokens(needle))
    return (" " + " ".join(toks) + " ") if toks else ""


def contains_phrase(hay, needle):
    """hay is a phrase_str; True when every token of needle appears there as one contiguous run."""
    n = _needle(_s(needle))
    return (not n) or n in hay


def stem(w):
    """Very light stemmer for 'is this word already in the source?': plan/planned/planning -> plan,
    store/stores -> store, analyze/analyzed -> analy. Keeps at most 5 characters."""
    base = w
    if len(w) > 5 and w.endswith("ing"):
        base = w[:-3]
    elif len(w) > 4 and w.endswith("ed"):
        base = w[:-2]
    elif len(w) > 4 and w.endswith(("ches", "shes", "sses", "xes", "zes")):
        base = w[:-2]
    elif len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        base = w[:-1]
    if base is not w and len(base) >= 3 and base[-1] == base[-2] and base[-1] not in "lsz":
        base = base[:-1]          # planned -> plann -> plan
    return base[:5]


def _is_year(v):
    return bool(re.match(r"^(19|20)\d\d$", v))


def _own_hedge(low, start, end, plus):
    """The hedge written right next to one number: (kind, word, start of the hedge word) or (None, None, None).
    kind is approx ("about 600", "600 or so"), lower ("over 60", "40+", "60 or more") or upper ("nearly 300")."""
    before = low[max(0, start - 24):start]
    after = low[end:end + 14]
    if plus:
        return "lower", "+", None
    m = re.match(r"\s*(or more|plus)\b", after)
    if m:
        return "lower", m.group(1), None
    hm = HEDGE_APPROX.search(before)
    if hm:
        return "approx", hm.group(0).strip(), start - len(before) + hm.start()
    m = re.match(r"\s*(or so|ish)\b", after)
    if m:
        return "approx", m.group(1), None
    hm = HEDGE_LOWER.search(before)
    if hm:
        if hm.group(0).strip() == "over" and TIME_UNIT_RE.match(after):
            return None, None, None          # "over 10 weeks": during, not "more than"
        return "lower", hm.group(0).strip(), start - len(before) + hm.start()
    hm = HEDGE_UPPER.search(before)
    if hm:
        return "upper", hm.group(0).strip(), start - len(before) + hm.start()
    return None, None, None


def _next_word(low, end):
    for w in re.findall(r"[a-z]+", low[end:end + 40]):
        if w not in NEXT_SKIP:
            return stem(w)
    return ""


def numbers_in(text, bullet=False):
    """Every number with its unit, hedge and range partner.

    [{'v': '600', 'alt': [...], 'unit': ''|'%'|'$',
      'hedge': None|'approx'|'lower'|'upper'|'range'     (legacy summary: 'range' wins),
      'h': None|'approx'|'lower'|'upper', 'word': the hedge word ('about', '+', ...),
      'grp': the other end of a range or alternative ('3 or 4' -> 4 has grp '3') or None,
      'grp_h'/'grp_word': the hedge in front of the whole group ('around 3 or 4' -> approx/'around'),
      'raw': the source wording, 'next': stem of the word after it ('hires', 'week')}]
    Digits and number words both count; years never form ranges; "from 20 to 60" is a change over time,
    not a range, so each end keeps only its own hedge."""
    t = util.norm_text(_s(text)).replace("–", "-")
    low = t.casefold()
    occ = []
    for m in NUM_RE.finditer(low):
        raw = m.group(2).replace(",", "") + ("." + m.group(3) if m.group(3) else "")
        try:
            v = float(raw)
        except ValueError:
            continue
        unit_word = (m.group(4) or "").lower()
        unit = "%" if unit_word in ("%", "percent") else ("$" if m.group(1) else "")
        mult = {"k": 1000, "thousand": 1000, "m": 1000000, "million": 1000000, "bn": 1e9, "billion": 1e9}.get(unit_word, 1)
        end = m.end()
        if m.group(5):
            end -= 1
        occ.append({"start": m.start(), "end": m.end(), "tok_end": end, "plus": bool(m.group(5)),
                    "v": _fmt(v * mult), "alt": sorted({_fmt(v), _fmt(v * mult)}), "unit": unit,
                    "text": m.group(0).strip()})
    words = NUM_WORDS_BULLET if bullet else NUM_WORDS_SOURCE
    for m in re.finditer(r"[a-z]+", low):
        w = m.group(0)
        if w in words:
            occ.append({"start": m.start(), "end": m.end(), "tok_end": m.end(), "plus": False,
                        "v": _fmt(words[w]), "alt": [_fmt(words[w])], "unit": "", "text": w})
    occ.sort(key=lambda o: o["start"])
    for o in occ:
        o["h"], o["word"], o["hstart"] = _own_hedge(low, o["start"], o["tok_end"], o["plus"])
        o["grp"] = o["grp_h"] = o["grp_word"] = None
        o["gstart"], o["gend"] = (o["hstart"] if o["hstart"] is not None else o["start"]), o["end"]
    for a, b in zip(occ, occ[1:]):
        if a["grp"] is not None or _is_year(a["v"]) and _is_year(b["v"]):
            continue
        try:
            if not float(a["v"]) < float(b["v"]):
                continue
        except ValueError:
            continue
        mid = low[a["end"]:(b["hstart"] if b["hstart"] is not None else b["start"])]
        a_from = a["hstart"] if a["hstart"] is not None else a["start"]
        before_a = low[max(0, a_from - 12):a_from]
        g_from = a_from
        if GROUP_MID_RE.match(mid):
            if FROM_RE.search(before_a):
                continue                    # "from about 20 to about 60": a change, not a range
        else:
            bm = BETWEEN_RE.search(before_a)
            if not (GROUP_AND_RE.match(mid) and bm):
                continue
            g_from = a_from - len(before_a) + bm.start()
        a["grp"], b["grp"] = b["v"], a["v"]
        for o in (a, b):
            o["grp_h"], o["grp_word"] = a["h"], a["word"]
            o["gstart"], o["gend"] = g_from, b["end"]
    out = []
    for o in occ:
        if o["grp"] is not None:
            raw, hedge = low[o["gstart"]:o["gend"]].strip(), "range"
        else:
            raw, hedge = o["text"], o["h"]
            if o["hstart"] is not None:
                raw = low[o["hstart"]:o["end"]].strip()
            elif o["h"] == "approx" and o["word"] in ("or so", "ish") or o["word"] in ("or more", "plus"):
                raw = (o["text"] + " " + o["word"]).strip()
        out.append({"v": o["v"], "alt": o["alt"], "unit": o["unit"], "hedge": hedge, "raw": raw,
                    "h": o["h"], "word": o["word"], "grp": o["grp"], "grp_h": o["grp_h"],
                    "grp_word": o["grp_word"], "next": _next_word(low, o["gend"])})
    return out


def _need_hedge(c):
    """The hedge a source number carries: (kind, word) from its own hedge or from its group's."""
    if c.get("h"):
        return c["h"], c.get("word")
    if c.get("grp") is not None and c.get("grp_h"):
        return c["grp_h"], c.get("grp_word")
    return None, None


def _hedge_compatible(n, c):
    """Can bullet number n honestly come from source number c (same value)?"""
    need, _w = _need_hedge(c)
    have, _hw = _need_hedge(n)
    if c.get("grp") is not None and n.get("grp") != c["grp"]:
        return False                        # "3 or 4" -> "4", "50-100" -> "up to 100": keep the range
    if need:
        return have == need                 # "about 600" -> "600" or -> "over 600": keep the hedge
    return have != "lower"                  # "3" -> "3+" / "more than 3" claims more than the source


def _fmt(v):
    return ("%d" % v) if float(v).is_integer() else ("%g" % v)


def _snippet(text, word, span=3):
    """A few words of `text` around the first `word` ('handle returns sometimes'), for messages."""
    toks = re.findall(r"\S+", util.norm_text(_s(text)))
    for i, t in enumerate(toks):
        if word in tokens(t):
            return " ".join(toks[max(0, i - span):i + span + 1]).strip(" ,.;")
    return word


FILLER_WORDS = {"no", "yes", "some", "none", "not", "but", "and", "n/a", "na", "nope", "never"}


def _term_patterns(term):
    return _term_patterns_cached(_s(term))


@functools.lru_cache(maxsize=1024)
def _term_patterns_cached(term):
    """Regexes for a keyword term and its parts ('healthcare data or HIPAA' -> the whole, 'healthcare data',
    'HIPAA'); 'Power BI' also matches 'PowerBI' and 'power-bi'."""
    term = re.sub(r"\(.*?\)", " ", _s(term)).strip()
    parts = [term] + [p.strip() for p in re.split(r"\s+or\s+|\s+and\s+|/|,|;", term) if p.strip()]
    out, seen = [], set()
    for p in parts:
        toks = re.findall(r"[^\W_]+|[+#]+", util.norm_text(p))
        if not toks or p.casefold() in seen or len("".join(toks)) < 2:
            continue
        seen.add(p.casefold())
        body = r"[\s\-/.]*".join(re.escape(t) for t in toks)
        flags = re.I if len("".join(toks)) >= 3 else 0
        out.append((p, re.compile(r"(?<![^\W_])%s(?![^\W_])" % body, flags)))
    return tuple(out)


def _mask_terms(text, no_terms, keep_terms):
    """Replace every 'no' keyword term (and its parts) in text with ' | ' so it can never be quoted."""
    keep = {_norm(k) for k in keep_terms}
    out = util.norm_text(_s(text))
    for term in no_terms:
        for part, rx in _term_patterns(term):
            if _norm(part) in keep:
                continue
            out = rx.sub(" | ", out)
    return out


# A month name or its 3-letter form ("Sept" too), never a longer word ("Marketing" is not March).
MONTH_NAME = (r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
              r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b\.?")


def month_years(text):
    t = _norm(text)
    pairs, years = set(), set(re.findall(r"\b(?:19|20)\d{2}\b", t))
    for m in re.finditer(r"\b%s,?\s+((?:19|20)\d{2})\b" % MONTH_NAME, t):
        pairs.add((MONTHS[m.group(1)[:3]], m.group(2)))
    # "from March to August 2023", "Mar-Aug 2023", "between June and July 2024": both months share the year.
    # (A season such as "last summer" never becomes a month.)
    for m in re.finditer(r"\b%s\s*(?:-|to|through|thru|until|till|and)\s*%s,?\s+((?:19|20)\d{2})\b"
                         % (MONTH_NAME, MONTH_NAME), t):
        m1, m2 = MONTHS[m.group(1)[:3]], MONTHS[m.group(2)[:3]]
        if m1 <= m2:
            pairs.add((m1, m.group(3)))
            pairs.add((m2, m.group(3)))
    for m in re.finditer(r"\b(0?[1-9]|1[0-2])\s*[/.]\s*((?:19|20)\d{2})\b", t):
        pairs.add((int(m.group(1)), m.group(2)))
    for m in re.finditer(r"\b((?:19|20)\d{2})-(0[1-9]|1[0-2])\b", t):
        pairs.add((int(m.group(2)), m.group(1)))
    return pairs, years


# ----------------------------------------------------------------------------------------------
# Sources
# ----------------------------------------------------------------------------------------------
class Sources:
    """Everything the candidate gave us, indexed for the checks."""

    def __init__(self, ledger, answers):
        self.lines = {}          # "R3" -> text (prefixes like "[header] " removed)
        self.order = []
        self.sections = {}
        for ln in ledger.get("resume_lines") or []:
            if not isinstance(ln, dict):
                continue
            rid = _s(ln.get("id")).strip()
            if re.match(r"^R\d+$", rid):
                self.lines[rid] = LINE_PREFIX_RE.sub("", _s(ln.get("text")))
                self.order.append(rid)
                self.sections[rid] = _s(ln.get("section"))
        self.jd = {}
        for it in ledger.get("jd_items") or []:
            if isinstance(it, dict) and re.match(r"^J\d+$", _s(it.get("id"))):
                self.jd[_s(it.get("id"))] = _s(it.get("text"))
        self.answers = {}        # "Q2" -> {"kind", "status", "text" (evidence text), "some": [terms]}
        self.no_terms = []       # [(qid, term)] keyword items answered "no": never usable anywhere
        raw_answers = answers.get("answers") if isinstance(answers, dict) else None
        for a in raw_answers if isinstance(raw_answers, list) else []:
            if not isinstance(a, dict) or not re.match(r"^Q\d+$", _s(a.get("id"))):
                continue
            qid = _s(a.get("id"))
            kind, status = _s(a.get("kind")), _s(a.get("status")) or "answered"
            text, some, yes, raw, nos, details = "", [], [], "", [], {}
            if status == "answered":
                items = a.get("items")
                if isinstance(items, list):
                    parts, extra = [], []
                    for it in items:
                        if not isinstance(it, dict):
                            continue
                        ans = _s(it.get("answer")).strip().lower()
                        if ans in ("yes", "some"):
                            parts.append("%s %s" % (_s(it.get("term")), _s(it.get("detail"))))
                            (some if ans == "some" else yes).append(_s(it.get("term")))
                            details[_norm(it.get("term"))] = _s(it.get("detail"))
                        elif _s(it.get("term")).strip():
                            nos.append(_s(it.get("term")).strip())
                            extra.append(_s(it.get("detail")))
                    # A "no" item's own words ("no, but I did the CITI human subjects training") and the
                    # free-text reply can back OTHER facts; the "no" term itself is masked out of both.
                    extra.append(_s(a.get("answer")))
                    keep = [_s(t) for t in yes + some]
                    masked = [_mask_terms(x, nos, keep) for x in extra if _s(x).strip()]
                    masked = [m for m in masked if set(tokens(m)) - FILLER_WORDS]
                    text = " . ".join(parts + masked)
                    raw = " . ".join(parts + [_s(x) for x in extra if _s(x).strip()])
                    self.no_terms.extend((qid, t) for t in nos)
                elif kind != "keywords":
                    ans = _s(a.get("answer")).strip()
                    if _norm(ans) not in NON_ANSWERS:
                        text = ans
            self.answers[qid] = {"kind": kind, "status": status, "text": text, "some": some, "yes": yes,
                                 "raw": raw or text, "nos": nos, "details": details}
        self.resume_text = "\n".join(self.lines[r] for r in self.order)
        self.answer_text = "\n".join(v["text"] for v in self.answers.values() if v["text"])
        self.all_text = self.resume_text + "\n" + self.answer_text
        self.all_phrase = phrase_str(self.all_text)
        self.resume_norm = _norm(self.resume_text)
        self.all_norm = _norm(self.all_text)
        self.all_stems = {stem(w) for w in expand(tokens(self.all_text))}
        self.all_numbers = numbers_in(self.all_text)
        self.resume_numbers = numbers_in(self.resume_text)
        self.pairs, self.years = month_years(self.resume_text + "\n" + self.answer_text)
        self.jd_text = "\n".join(self.jd.values())
        self.jd_norm = _norm(self.jd_text)
        self.jd_phrase = phrase_str(self.jd_text)

    def jd_ids_with(self, phrase):
        return [jid for jid, txt in sorted(self.jd.items(), key=lambda kv: int(kv[0][1:]))
                if contains_phrase(phrase_str(txt), phrase)]

    def lines_with_quote(self, qn):
        return [rid for rid in self.order if qn and qn in _norm(self.lines[rid])]


def parse_ref(ref):
    """'R12' -> ('R', [12]); 'R12-R14' -> ('R', [12, 13, 14]); 'Q2' -> ('Q', [2]); else (None, None)."""
    m = REF_RE.match(_s(ref).strip())
    if not m:
        return None, None
    if m.group(3):
        return "Q", [int(m.group(3))]
    a = int(m.group(1))
    b = int(m.group(2)) if m.group(2) else a
    if b < a or b - a > 40:
        return None, None
    return "R", list(range(a, b + 1))


# ----------------------------------------------------------------------------------------------
# The check
# ----------------------------------------------------------------------------------------------
class _Checker:
    def __init__(self, ledger, answers, resume):
        self.src = Sources(ledger, answers)
        self.resume = resume
        self.errors, self.warnings = [], []
        self.stats = {"bullets": 0, "bullets_with_evidence": 0, "placeholders_open": 0, "numbers_from_answers": 0}
        self.placeholders = resume.get("placeholders") if isinstance(resume.get("placeholders"), dict) else {}
        self.cited = set()        # R ids referenced anywhere (evidence refs and meta.cuts)
        self.quotes = []          # normalized evidence quotes (for UNLISTED_CUT)
        self._tools = None

    def err(self, code, where, detail):
        e = {"code": code, "where": where, "detail": detail}
        if e not in self.errors:
            self.errors.append(e)

    def has_err(self, code, where):
        return any(e["code"] == code and e["where"] == where for e in self.errors)

    def warn(self, code, bid, detail):
        w = {"code": code, "bullet_id": bid, "detail": detail}
        if w not in self.warnings:
            self.warnings.append(w)

    # -- evidence ---------------------------------------------------------------------------------
    def evidence_context(self, evidence, where):
        """Validate evidence items. Returns (resume-line text, answer text, number of usable items)."""
        resume_ctx, answer_ctx, valid = [], [], 0
        if evidence is None:
            evidence = []
        if not isinstance(evidence, list):
            self.err("BAD_REF", where, "evidence must be a list of {src, ref, quote}")
            evidence = []
        for ev in evidence:
            if not isinstance(ev, dict):
                self.err("BAD_REF", where, "evidence items must be objects like {src, ref, quote}")
                continue
            src, ref, quote = _s(ev.get("src")).strip().lower(), _s(ev.get("ref")).strip(), _s(ev.get("quote"))
            qn = _norm(quote)
            if src in ("jd", "job", "posting", "job_posting", "job description") or JD_REF_RE.match(ref):
                self.err("JD_AS_EVIDENCE", where, "evidence cites the job posting (%s); the posting is never "
                         "evidence, only your resume lines and your answers are" % (ref or src))
                continue
            kind, nums = parse_ref(ref)
            if src not in ("orig", "user"):
                self.err("BAD_REF", where, "evidence src must be 'orig' (a resume line) or 'user' (an answer), "
                         "not '%s'" % src)
                continue
            if kind is None:
                if qn and qn in self.src.jd_norm and qn not in self.src.all_norm:
                    self.err("JD_AS_EVIDENCE", where, "the quote '%s' comes from the job posting" % quote[:80])
                else:
                    self.err("BAD_REF", where, "'%s' is not a valid reference (use R12, R12-R14 or Q2)" % ref)
                continue
            if (src == "orig") != (kind == "R"):
                self.err("BAD_REF", where, "src '%s' does not match ref '%s' (orig uses R#, user uses Q#)" % (src, ref))
                continue
            if kind == "R":
                ids = ["R%d" % n for n in nums]
                missing = [i for i in ids if i not in self.src.lines]
                if missing:
                    self.err("BAD_REF", where, "%s is not a line of your resume" % ", ".join(missing))
                    continue
                self.cited.update(ids)
                line_text = " ".join(self.src.lines[i] for i in ids)
                if qn:
                    self.quotes.append(qn)
                    if qn not in _norm(line_text):
                        others = self.src.lines_with_quote(qn)
                        if others:
                            self.err("BAD_REF", where, "the quote is on %s, not %s; fix the ref" % (others[0], ref))
                            self.cited.update(others)
                        elif qn in self.src.jd_norm:
                            self.err("JD_AS_EVIDENCE", where, "the quote '%s' comes from the job posting, not your "
                                     "resume" % quote[:80])
                        else:
                            self.err("EVIDENCE_QUOTE_NOT_FOUND", where, "'%s' is not in %s" % (quote[:80], ref))
                        continue
                resume_ctx.append(line_text)
                valid += 1
            else:
                qid = "Q%d" % nums[0]
                a = self.src.answers.get(qid)
                if a is None:
                    self.err("BAD_REF", where, "%s is not in answers.json" % qid)
                    continue
                if a["status"] != "answered" or not a["text"]:
                    why = ("was %s" % (a["status"] or "not answered")) if a["status"] != "answered" else \
                        "has no usable answer (only real answers and yes/some keyword items count)"
                    self.err("BAD_REF", where, "%s %s, so it cannot be evidence" % (qid, why))
                    continue
                if qn and qn not in _norm(a["text"]):
                    if qn in _norm(a.get("raw") or ""):
                        no_hit = [t for t in a.get("nos") or []
                                  if any(rx.search(util.norm_text(quote)) for _p, rx in _term_patterns(t))]
                        self.err("BAD_REF", where, "the quote '%s' is in your answer %s, but it sits inside a 'no' "
                                 "item%s; a term answered 'no' can never be used. Quote only the other words of "
                                 "that answer (they can back other facts)" % (
                                     quote[:80], qid, (" (%s)" % ", ".join("'%s'" % t for t in no_hit)) if no_hit else ""))
                    elif qn in self.src.jd_norm:
                        self.err("JD_AS_EVIDENCE", where, "the quote '%s' comes from the job posting" % quote[:80])
                    else:
                        self.err("EVIDENCE_QUOTE_NOT_FOUND", where, "'%s' is not in your answer %s" % (quote[:80], qid))
                    continue
                answer_ctx.append(a["text"])
                valid += 1
        return "\n".join(resume_ctx), "\n".join(answer_ctx), valid

    def evidence_texts(self, evidence):
        """The text of every valid R#/Q# an evidence list cites (no errors logged; used for labels and titles)."""
        out = []
        for ev in evidence if isinstance(evidence, list) else []:
            if not isinstance(ev, dict):
                continue
            kind, nums = parse_ref(_s(ev.get("ref")).strip())
            if kind == "R":
                out.extend(self.src.lines["R%d" % n] for n in nums if ("R%d" % n) in self.src.lines)
            elif kind == "Q":
                a = self.src.answers.get("Q%d" % nums[0])
                if a and a["status"] == "answered" and a["text"]:
                    out.append(a["text"])
        return out

    def cited_text(self, items, extra=None):
        """Everything the given entries (and their bullets) cite, plus `extra` evidence lists."""
        out = []
        for ev in extra or []:
            out.extend(self.evidence_texts(ev))
        for it in items:
            if not isinstance(it, dict):
                continue
            out.extend(self.evidence_texts(it.get("evidence")))
            for b in it.get("bullets") or []:
                if isinstance(b, dict):
                    out.extend(self.evidence_texts(b.get("evidence")))
        return "\n".join(out)

    def source_heading_words(self):
        """Words of the uploaded resume's own heading lines ('WORK', 'E X P E R I E N C E', 'Berufserfahrung')."""
        words = set()
        for rid in self.src.order:
            line = self.src.lines[rid].strip()
            if re.search(r"\d|@", line):
                continue
            parts = line.rstrip(":").split()
            if parts and all(len(p) == 1 for p in parts):
                line = "".join(parts)            # letter-spaced heading
            toks = tokens(line)
            if not toks or len(toks) > 4:
                continue
            letters = re.sub(r"[^A-Za-zÀ-ÿ]", "", line)
            if line.endswith(":") or (letters and letters.isupper()) or _looks_like_heading(line):
                words.update(expand(toks))
        return words

    def check_section_title(self, sec, sid):
        """HEADING_CLAIM: a section title may only use standard heading words, words the section's own
        evidence (or entry names) contains, words of the original resume's headings, or an honest label the
        evidence shows. 'Clinical Experience' over a grocery job fails."""
        title = _s(sec.get("title")).strip()
        if not title:
            return
        items = [it for it in sec.get("items") or [] if isinstance(it, dict)]
        groups = [g for g in sec.get("groups") or [] if isinstance(g, dict)]
        cited = self.cited_text(items, [sec.get("evidence")] + [g.get("evidence") for g in groups])
        fields = []
        for it in items:
            fields += [_s(it.get(f)) for f in ("org", "role", "school", "degree", "field", "minor", "name", "context")]
            fields += [_s(x) for x in (it.get("honors") or []) + (it.get("coursework") or []) if isinstance(x, str)]
        for g in groups:
            fields.append(_s(g.get("label")))
            fields += [_s(x) for x in g.get("items") or [] if isinstance(x, str)]
        known = {stem(w) for w in expand(tokens(cited + "\n" + "\n".join(fields)))}
        known |= {stem(w) for w in self.source_heading_words()}
        words = [w for w in expand(tokens(title)) if w not in STANDARD_HEADING_WORDS and w not in STOP]
        left = [w for w in words if stem(w) not in known]
        if not left:
            return
        label = honest_label(title) or honest_label(" ".join(left)) or \
            honest_label(" ".join(w for w in expand(tokens(title)) if w not in ("experience", "work")))
        if label and label_supported(label, cited):
            return
        lang = _s((self.resume.get("meta") or {}).get("locale") if isinstance(self.resume.get("meta"), dict) else "")
        detail = ("section title '%s' uses %s, which is not a standard heading word and not in the lines this "
                  "section cites; use a plain heading (Experience, Projects, Volunteer Experience, Activities) or "
                  "words from your own lines" % (title, ", ".join("'%s'" % w for w in left)))
        if lang and not lang.lower().startswith("en"):
            self.warn("NEW_WORDING", "%s.title" % sid, detail)   # headings in other languages: auditor checks
        else:
            self.err("HEADING_CLAIM", "%s.title" % sid, detail)

    # -- placeholders ------------------------------------------------------------------------------
    def resolve(self, item, text_key, where):
        """Return (the text that will be rendered, answer text backing answered placeholders)."""
        text = _s(item.get(text_key))
        ids = PLACEHOLDER_RE.findall(text)
        if not ids:
            return text, ""
        fallback = _s(item.get("textIfUnknown"))
        if not fallback.strip():
            self.err("PLACEHOLDER_LEFT", where, "the text has a placeholder but no textIfUnknown (the honest "
                     "version without the missing fact)")
        extra, unresolved = [], False
        for pid in ids:
            ph = self.placeholders.get(pid)
            if not isinstance(ph, dict):
                self.err("PLACEHOLDER_LEFT", where, "{{%s}} has no entry in placeholders" % pid)
                unresolved = True
                continue
            value = _s(ph.get("value")).strip()
            if ph.get("status") == "answered" and value:
                found = self._answer_holding(value, ph.get("question"))
                if found is None:
                    self.err("EVIDENCE_QUOTE_NOT_FOUND", "placeholders.%s" % pid,
                             "the value '%s' is not in any answer you gave" % value[:60])
                else:
                    extra.append(found)
                text = re.sub(r"\{\{\s*%s\s*\}\}" % re.escape(pid), lambda _m, v=value: v, text)
            else:
                unresolved = True
        if unresolved:
            return (fallback if fallback.strip() else text), ""
        return text, "\n".join(extra)

    def _answer_holding(self, value, qid):
        vn = _norm(value)
        order = []
        if isinstance(qid, str) and qid in self.src.answers:
            order.append(qid)
        order += [q for q in sorted(self.src.answers, key=lambda q: int(q[1:])) if q not in order]
        for q in order:
            a = self.src.answers[q]
            if a["status"] == "answered" and a["text"] and vn and vn in _norm(a["text"]):
                return a["text"]
        return None

    # -- claim checks ------------------------------------------------------------------------------
    def check_numbers(self, text, resume_ctx, answer_ctx, where):
        resume_vals = numbers_in(resume_ctx)
        answer_vals = numbers_in(answer_ctx)
        ctx_nums = resume_vals + answer_vals
        for n in numbers_in(text, bullet=True):
            is_year = n["unit"] == "" and _is_year(n["v"])
            pool = self.src.all_numbers if is_year else ctx_nums
            cands = [c for c in pool if (n["v"] in c["alt"] or c["v"] in n["alt"]) and
                     (n["unit"] == "" or c["unit"] == n["unit"])]
            if not cands:
                same_value = [c for c in pool if n["v"] in c["alt"]]
                elsewhere = [c for c in self.src.all_numbers if n["v"] in c["alt"] and
                             (n["unit"] == "" or c["unit"] == n["unit"])]
                if same_value and n["unit"]:
                    detail = "'%s' is a %s here, but the source has %s without that unit" % (
                        n["raw"], "percentage" if n["unit"] == "%" else "money amount", same_value[0]["raw"])
                elif elsewhere:
                    detail = ("'%s' appears elsewhere in your materials but not in the lines this text cites; "
                              "cite where it comes from or remove it" % n["raw"])
                else:
                    detail = "'%s' is not in your resume or your answers" % n["raw"]
                self.err("NUMBER_NOT_IN_SOURCE", where, detail)
                continue
            if not is_year:
                problem = self._hedge_problem(n, cands)
                if problem:
                    self.err("HEDGE_REMOVED", where, problem)
            if not is_year and any(n["v"] in c["alt"] for c in answer_vals) and \
                    not any(n["v"] in c["alt"] for c in resume_vals):
                self.stats["numbers_from_answers"] += 1

    @staticmethod
    def _hedge_problem(n, cands):
        """None when the bullet keeps the hedge or range of at least one matching source occurrence; else a
        message that names the hedge word (or the range) the bullet dropped or changed."""
        same_next = [c for c in cands if n.get("next") and c.get("next") == n["next"]]
        if same_next:
            cands = same_next               # "about 20 hours" vs "20 people": compare like with like
        if any(_hedge_compatible(n, c) for c in cands):
            return None
        c = cands[0]
        need, word = _need_hedge(c)
        have, _hw = _need_hedge(n)
        shown = n["raw"]
        if c.get("grp") is not None and n.get("grp") != c["grp"]:
            return ("the source gives a range or choice ('%s'); keep the whole range instead of '%s'"
                    % (c["raw"], shown))
        if need and not have:
            return "the source says '%s'; keep '%s' next to %s" % (c["raw"], word, n["v"])
        if need:
            return "the source says '%s', but '%s' changes it; keep '%s'" % (c["raw"], shown, word)
        return "'%s' claims more than the source ('%s'); keep the number as the source has it" % (shown, c["raw"])

    def tool_terms(self):
        """Tool and skill names (lowercase phrases) that must never appear without evidence."""
        if self._tools is None:
            terms = set(BUILTIN_TOOLS)
            path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "skills.json")
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for e in data.get("entries") or []:
                    if not isinstance(e, dict) or e.get("kind") not in ("hard", "tool", "cert"):
                        continue
                    if e.get("ambiguous") or e.get("case_sensitive"):
                        continue
                    for t in [e.get("canonical")] + list(e.get("aliases") or []):
                        t = _s(t).strip().lower()
                        if len(t) >= 3 and t not in STOP:
                            terms.add(t)
            except (OSError, ValueError, AttributeError, TypeError):
                pass
            self._tools = sorted(terms)
        return self._tools

    def check_terms(self, text, ctx_phrase, where, capitalized=True):
        """Tools, brands and proper nouns must be in this text's own evidence."""
        body = re.sub(r"\[ADD:[^\]]*\]", " ", util.norm_text(_s(text)))
        flagged = set()
        if capitalized:
            for m in CAP_TERM_RE.finditer(body):
                tok = m.group(1)
                prev = body[:m.start(1)].rstrip()
                if not prev or prev[-1] in ".;:!?":
                    continue   # sentence-initial capital
                low = tok.lower()
                if len(tok) < 2 or low in STOP or low in CALENDAR_WORDS or re.match(r"^\d+[a-z]{0,2}$", low):
                    continue
                if contains_phrase(ctx_phrase, tok):
                    continue
                flagged.add(" ".join(expand(tokens(tok))))
                self._term_error(tok, where)
        bullet_phrase = phrase_str(text)
        for term in self.tool_terms():
            if term in flagged or not contains_phrase(bullet_phrase, term) or contains_phrase(ctx_phrase, term):
                continue
            if any(term in f or f in term for f in flagged):
                continue
            flagged.add(term)
            self._term_error(term, where)

    def _term_error(self, tok, where):
        jd_ids = self.src.jd_ids_with(tok)
        said_no = [(q, t) for q, t in self.src.no_terms
                   if any(rx.search(util.norm_text(tok)) for _p, rx in _term_patterns(t))]
        if contains_phrase(self.src.all_phrase, tok):
            self.err("TERM_NOT_IN_SOURCE", where, "'%s' is in your materials but not in the lines this text cites; "
                     "cite where you used it or leave it out" % tok)
        elif said_no:
            self.err("TERM_NOT_IN_SOURCE", where, "you answered 'no' for '%s' (%s), so it cannot appear on the "
                     "resume%s" % (said_no[0][1], said_no[0][0],
                                   " (it comes only from the job posting, %s, which is never evidence)" % jd_ids[0]
                                   if jd_ids else ""))
        elif jd_ids:
            self.err("TERM_NOT_IN_SOURCE", where, "'%s' comes only from the job posting (%s); the posting is never "
                     "evidence" % (tok, jd_ids[0]))
        else:
            self.err("TERM_NOT_IN_SOURCE", where, "'%s' is not in your resume or your answers" % tok)

    @staticmethod
    def _tier(t):
        tier = TIER.get(t, 0)
        if t.startswith("co") and len(t) > 4 and TIER.get(t[2:], 0) >= 2:
            tier = 3        # co-led, co-founded, co-managed: shared ownership
        return tier

    def check_ownership(self, text, ctx, where, role_text=""):
        toks = tokens(text)
        if not toks:
            return
        b_tier, b_word = 0, None
        for i, t in enumerate(toks):
            if t in AMBIGUOUS_TOP and i > 2:
                continue
            tier = self._tier(t)
            if tier > b_tier:
                b_tier, b_word = tier, t
        role_toks = tokens(role_text)
        e_tier = 0
        for t in tokens(ctx) + role_toks:
            e_tier = max(e_tier, self._tier(t), TITLE_TIER.get(t, 0))
        if b_tier >= 3 and b_tier > max(e_tier, 1):
            self.err("OWNERSHIP_UPGRADED", where, "'%s' claims more ownership than the source shows; use a verb at "
                     "the same level as the source (for example keep 'helped' or 'supported')" % b_word)
            return
        # Helper constructions in the source ("helped plan", "assisted with") keep a helper in the rewrite.
        b_set = set(toks)
        if b_set & HELPER_MARKERS or any(self._tier(t) and t.startswith("co") and len(t) > 4 for t in b_set):
            return
        etoks = tokens(ctx)
        b_stems = {stem(t) for t in toks}
        for i, t in enumerate(etoks):
            if t not in HELPERS:
                continue
            nxt = [w for w in etoks[i + 1:i + 4] if w not in ("to", "the", "a", "an")]
            if not nxt:
                continue
            verb = nxt[0] if nxt[0] in VERB_HINTS else None
            if nxt[0] in ("with", "in", "on") and len(nxt) > 1:
                verb = nxt[1] if nxt[1] in VERB_HINTS else None
            if verb and stem(verb) in b_stems:
                self.err("OWNERSHIP_UPGRADED", where, "the source says '%s %s'; keep the helper wording "
                         "('Helped %s...', 'Co-%s...' or 'with the team')" % (t, verb, verb, verb))
                return

    def check_qualifiers(self, text, ctx, where):
        b = set(tokens(text))
        c = set(tokens(ctx))
        new_abs = [w for w in tokens(text) if w in ABSOLUTES and w not in c]
        quals = sorted(c & QUALIFIERS)
        if not (new_abs and quals):
            return
        dropped = [q for q in quals if q not in b]
        if dropped:
            self.err("HEDGE_REMOVED", where, "the source says '%s' and this drops it; '%s' is stronger than the "
                     "source. Keep '%s'" % (_snippet(ctx, dropped[0]), new_abs[0], dropped[0]))
        else:
            self.err("HEDGE_REMOVED", where, "'%s' is not in the source, which hedges ('%s'); use the source's own "
                     "frequency words instead of '%s'" % (new_abs[0], _snippet(ctx, quals[0]), new_abs[0]))

    def check_new_wording(self, text, ctx, bid):
        toks = expand(tokens(text))
        ctx_stems = {stem(w) for w in expand(tokens(ctx))}
        novel = []
        for i, w in enumerate(toks):
            if len(w) <= 3 or w in STOP or re.match(r"^[\d.,%$+]+$", w) or stem(w) in ctx_stems:
                continue
            if i == 0 and (w in VERB_HINTS or w.endswith("ed")) and self._tier(w) <= 2:
                continue   # an ordinary action verb up front; ownership is checked separately
            from_jd = (" %s " % w) in self.src.jd_phrase and stem(w) not in self.src.all_stems
            tag = w + (" (job posting)" if from_jd else "")
            if tag not in novel:
                novel.append(tag)
        if novel:
            self.warn("NEW_WORDING", bid, "re-check these words against the evidence: " + ", ".join(novel))

    # -- sections ----------------------------------------------------------------------------------
    def run(self):
        r = self.resume
        basics = r.get("basics") if isinstance(r.get("basics"), dict) else {}
        self.check_contact(basics)
        headline = _s(basics.get("headline"))
        if headline:
            if LEFTOVER_RE.search(headline):
                self.err("PLACEHOLDER_LEFT", "basics.headline", "the headline has placeholder text")
            for n in numbers_in(headline, bullet=True):
                if not any(n["v"] in c["alt"] for c in self.src.all_numbers):
                    self.err("NUMBER_NOT_IN_SOURCE", "basics.headline", "'%s' is not in your resume or answers" % n["raw"])
            # Headlines are Title Case, so only tool names are errors; other new words are warnings.
            self.check_terms(headline, self.src.all_phrase, "basics.headline", capitalized=False)
            novel = []
            for w in expand(tokens(headline)):
                if w not in STOP and len(w) > 2 and stem(w) not in self.src.all_stems and w not in novel:
                    novel.append(w)
            if novel:
                self.warn("HEADLINE_NEW_WORD", "basics.headline", "not in your resume or answers; confirm it is "
                          "true: " + ", ".join(novel))
        sections = r.get("sections") if isinstance(r.get("sections"), list) else []
        for si, sec in enumerate(sections):
            if not isinstance(sec, dict):
                continue
            stype = _s(sec.get("type")).lower()
            sid = _s(sec.get("id")) or stype or "section%d" % (si + 1)
            self.check_section_title(sec, sid)
            if stype == "summary" or (_s(sec.get("text")).strip() and not sec.get("items") and not sec.get("groups")):
                self.check_text_item(sec, "text", sid, entry_ctx="", role="", is_bullet=False)
            if stype == "skills" or sec.get("groups"):
                for g in sec.get("groups") or []:
                    if isinstance(g, dict):
                        self.check_skill_group(g, sid)
            for it in sec.get("items") or []:
                if isinstance(it, dict):
                    self.check_entry(it, stype, sid)
        self.check_meta()
        self.check_leftovers()
        self.check_unlisted_cuts()
        self.stats["placeholders_open"] = sum(
            1 for p in self.placeholders.values()
            if isinstance(p, dict) and (p.get("status") not in ("answered", "declined") or
                                        (p.get("status") == "answered" and not _s(p.get("value")).strip())))

    def check_contact(self, basics):
        src = self.src
        name = _s(basics.get("name")).strip()
        if name and not contains_phrase(src.all_phrase, name):
            self.err("CONTACT_CHANGED", "basics.name", "'%s' differs from the name in your resume" % name)
        email = _s(basics.get("email")).strip()
        if email and _norm(email) not in src.all_norm:
            self.err("CONTACT_CHANGED", "basics.email", "'%s' is not the email in your resume" % email)
        phone = re.sub(r"\D", "", _s(basics.get("phone")))
        if phone:
            digits = [re.sub(r"\D", "", f) for f in re.findall(r"\+?\d[\d\s().-]{5,}\d", src.all_text)]
            ok = any(len(phone) >= 7 and len(d) >= 7 and (d == phone or d.endswith(phone) or phone.endswith(d))
                     for d in digits)
            if not ok:
                self.err("CONTACT_CHANGED", "basics.phone", "'%s' is not the phone number in your resume"
                         % _s(basics.get("phone")))
        loc = _s(basics.get("location")).strip()
        if loc and not contains_phrase(src.all_phrase, loc):
            parts = [p for p in re.split(r"[,|]", loc) if p.strip()]
            if not all(contains_phrase(src.all_phrase, p) for p in parts):
                self.err("CONTACT_CHANGED", "basics.location", "'%s' is not the location in your resume" % loc)
        links = basics.get("links") if isinstance(basics.get("links"), list) else []

        def nurl(u):
            return re.sub(r"^(?:https?://)?(?:www\.)?", "", _s(u).strip().casefold()).rstrip("/")
        flat = re.sub(r"(?:https?://)?(?:www\.)?", "", src.all_text.casefold())
        for i, ln in enumerate(links):
            url = ln.get("url") if isinstance(ln, dict) else ln
            if _s(url).strip() and nurl(url) not in flat:
                self.err("CONTACT_CHANGED", "basics.links[%d]" % i, "'%s' is not a link in your resume" % _s(url)[:80])

    def check_entry(self, it, stype, sid):
        eid = _s(it.get("id")) or sid
        e_resume, e_answers, _valid = self.evidence_context(it.get("evidence"), eid)
        cited = None
        for f in ("org", "role", "school", "degree", "field", "minor", "location", "name"):
            v = _s(it.get(f)).strip()
            if v and not contains_phrase(self.src.all_phrase, v):
                if f == "location" and all(contains_phrase(self.src.all_phrase, p)
                                           for p in re.split(r"[,|]", v) if p.strip()):
                    continue
                label = honest_label(v)
                if label and f in ("org", "role", "name"):
                    if cited is None:
                        cited = self.cited_text([it])
                    if label_supported(label, cited):
                        continue        # "Family Caregiver" when an answer says they care for a relative
                    self.err("ENTITY_NOT_IN_SOURCE", eid, "%s '%s' is an honest label only when the lines this "
                             "entry cites show it (%s)" % (f, v, HONEST_LABELS[label][0]))
                    continue
                in_jd = bool(self.src.jd_ids_with(v))
                self.err("ENTITY_NOT_IN_SOURCE", eid, "%s '%s' is not in your resume%s" % (
                    f, v, " (it is in the job posting, which is never evidence)" if in_jd else ""))
        context = _s(it.get("context"))
        if context:
            kept = " ".join(w for w in re.findall(r"\S+", context) if w.strip(",.;()").lower() not in CONTEXT_WORDS)
            self.check_terms(kept, self.src.all_phrase, eid + ".context")
        self.check_dates(it, eid, e_resume + "\n" + e_answers)
        gpa = _s(it.get("gpa"))
        for n in numbers_in(gpa, bullet=True):
            if not any(n["v"] in c["alt"] for c in self.src.all_numbers):
                self.err("NUMBER_NOT_IN_SOURCE", eid + ".gpa", "GPA '%s' is not in your resume" % gpa)
        for hn in it.get("honors") or []:
            hn = _s(hn)
            for n in numbers_in(hn, bullet=True):
                if not any(n["v"] in c["alt"] for c in self.src.all_numbers):
                    self.err("NUMBER_NOT_IN_SOURCE", eid + ".honors", "'%s' is not in your resume" % n["raw"])
            core = re.sub(r"\(.*?\)", " ", hn)
            if core.strip() and not contains_phrase(self.src.all_phrase, core):
                self.err("ENTITY_NOT_IN_SOURCE", eid, "honor '%s' is not in your resume" % hn)
        for c in it.get("coursework") or []:
            if _s(c).strip() and not contains_phrase(self.src.all_phrase, _s(c)):
                self.err("ENTITY_NOT_IN_SOURCE", eid, "course '%s' is not in your resume" % _s(c))
        entry_fields = " ".join([_s(it.get(f)) for f in ("org", "role", "school", "degree", "field", "minor",
                                                          "location", "name", "context")] +
                                [_s(x) for x in (it.get("honors") or []) + (it.get("coursework") or [])
                                 if isinstance(x, (str, int, float))])
        # Entry-level answers stay answers: a number a bullet takes from them counts as "from your answers".
        entry_ctx = "\n".join(x for x in (e_resume, entry_fields) if x.strip())
        for bi, b in enumerate(it.get("bullets") or []):
            if isinstance(b, str):
                b = {"id": "%s.b%d" % (eid, bi + 1), "text": b}
            if not isinstance(b, dict):
                continue
            self.check_text_item(b, "text", _s(b.get("id")) or "%s.b%d" % (eid, bi + 1),
                                 entry_ctx=entry_ctx, role=_s(it.get("role")), is_bullet=True,
                                 entry_answers=e_answers)

    def check_text_item(self, item, key, bid, entry_ctx, role, is_bullet, entry_answers=""):
        if is_bullet:
            self.stats["bullets"] += 1
        text, ph_answers = self.resolve(item, key, bid)
        if LEFTOVER_RE.search(text) and not self.has_err("PLACEHOLDER_LEFT", bid):
            self.err("PLACEHOLDER_LEFT", bid, "unresolved placeholder text in the final wording")
        evidence = item.get("evidence")
        r_ctx, a_ctx, valid = self.evidence_context(evidence, bid)
        if not valid:
            already = any(e["where"] == bid and e["code"] in ("BAD_REF", "EVIDENCE_QUOTE_NOT_FOUND", "JD_AS_EVIDENCE")
                          for e in self.errors)
            if not already:
                self.err("NO_EVIDENCE", bid, "no evidence: cite the resume line (R#) or the answer (Q#) it comes from")
        elif is_bullet:
            self.stats["bullets_with_evidence"] += 1
        answers_ctx = "\n".join(x for x in (a_ctx, ph_answers) if x)
        resume_ctx = "\n".join(x for x in (r_ctx, entry_ctx) if x)
        all_answers = "\n".join(x for x in (answers_ctx, entry_answers) if x)
        full_ctx = resume_ctx + "\n" + all_answers
        self.check_numbers(text, resume_ctx, all_answers, bid)
        self.check_terms(text, phrase_str(full_ctx), bid)
        self.check_ownership(text, "\n".join(x for x in (r_ctx, answers_ctx) if x), bid, role_text=role)
        self.check_qualifiers(text, r_ctx + "\n" + answers_ctx, bid)
        self.check_new_wording(text, full_ctx, bid)

    def check_skill_group(self, g, sid):
        label = _s(g.get("label"))
        where = "skills/" + (label or sid)
        self.evidence_context(g.get("evidence"), where)
        some_terms = []
        for a in self.src.answers.values():
            some_terms += a["some"]
        resume_phrase = phrase_str(self.src.resume_text)
        for raw in g.get("items") or []:
            item = _s(raw).strip()
            if not item:
                continue
            core = re.sub(r"\(.*?\)", " ", item).strip()
            paren = " ".join(re.findall(r"\((.*?)\)", item))
            if core and not contains_phrase(self.src.all_phrase, core):
                in_jd = bool(self.src.jd_ids_with(core))
                said_no = [(q, t) for q, t in self.src.no_terms
                           if any(rx.search(util.norm_text(core)) for _p, rx in _term_patterns(t))]
                if said_no:
                    self.err("SKILL_NOT_IN_SOURCE", where, "you answered 'no' for '%s' (%s), so it cannot be listed%s"
                             % (said_no[0][1], said_no[0][0], " (only the job posting has it)" if in_jd else ""))
                else:
                    self.err("SKILL_NOT_IN_SOURCE", where, "'%s' is not in your resume or your answers%s" % (
                        core, " (only the job posting has it)" if in_jd else ""))
                continue
            for w in tokens(paren):
                if w in PROFICIENCY and stem(w) not in self.src.all_stems:
                    self.err("SKILL_NOT_IN_SOURCE", where, "'%s' adds a proficiency level ('%s') the source does "
                             "not state" % (item, w))
            src_quals = self._source_qualifiers(core)
            if src_quals and not paren.strip():
                self.err("HEDGE_REMOVED", where, "the source says '%s (%s)'; keep a qualifier such as '(%s)'" % (
                    core, src_quals[0], src_quals[0]))
                continue
            only_some = core and any(_norm(core) == _norm(t) for t in some_terms) and \
                not contains_phrase(resume_phrase, core) and \
                not any(contains_phrase(phrase_str(a["text"]), core) for a in self.src.answers.values()
                        if a["kind"] != "keywords" and a["text"]) and \
                not any(_norm(core) == _norm(t) for a in self.src.answers.values() for t in a["yes"])
            if only_some and not paren.strip():
                qual = self._some_qualifier(core)
                self.err("HEDGE_REMOVED", where, "you answered 'some' for %s; list it with a qualifier taken from "
                         "your answer, %s" % (core, ("such as '%s (%s)'" % (core, qual)) if qual else
                                              "for example where you used it"))

    def _some_qualifier(self, core):
        """'coursework' / 'class project' / 'project' from the student's own 'some' detail, else None
        (never a proficiency word like 'basic' the student did not say)."""
        detail = " ".join(a["details"].get(_norm(core), "") for a in self.src.answers.values())
        toks = set(tokens(detail))
        school = toks & {"class", "classes", "course", "courses", "coursework", "homework", "lecture", "school",
                         "semester", "lab"}
        if toks & {"project", "projects"}:
            return "class project" if school else "project"
        if school:
            return "coursework"
        return None

    def _source_qualifiers(self, core):
        """Qualifiers in parentheses right after the skill in the resume, e.g. 'SQL (class)'; [] if the
        resume also shows the skill without one."""
        found = []
        key = re.escape(_norm(core))
        pat = re.compile(r"(?<![\w])%s\s*\(([^)]{1,40})\)" % key)
        bare = re.compile(r"(?<![\w(])%s(?![\w])(?!\s*\()" % key)
        for rid in self.src.order:
            line = _norm(self.src.lines[rid])
            for m in pat.finditer(line):
                found += [w for w in tokens(m.group(1)) if w in SKILL_QUALIFIERS]
        if not found:
            return []
        for rid in self.src.order:
            if bare.search(_norm(self.src.lines[rid])):
                return []
        return found

    def check_dates(self, it, eid, ectx):
        src = self.src
        dt = _s(it.get("dateText")).strip()
        scope = ectx if ectx.strip() else src.all_text
        present_re = r"(?i)\b(present|current|currently|now|ongoing|today)\b"
        if dt:
            for y in re.findall(r"\b(?:19|20)\d{2}\b", dt):
                if y not in src.years:
                    self.err("DATE_NOT_IN_SOURCE", eid, "year %s is not in your resume" % y)
            pairs, _yrs = month_years(dt)
            for mo, y in sorted(pairs):
                if y in src.years and (mo, y) not in src.pairs:
                    self.err("DATE_PRECISION_ADDED", eid, "the month %02d/%s is not in your resume; keep the source "
                             "wording (for example 'Summer %s')" % (mo, y, y))
            if re.search(r"(?i)\b(present|current|now)\b", dt) and not re.search(present_re, scope):
                self.err("DATE_NOT_IN_SOURCE", eid, "'present' is not supported by the cited lines")
            return
        for key in ("start", "end"):
            v = _s(it.get(key)).strip()
            if not v:
                continue
            if v.lower() in ("present", "current", "now"):
                if not re.search(present_re, scope):
                    self.err("DATE_NOT_IN_SOURCE", eid, "'%s: present' is not supported by the cited lines" % key)
                continue
            m = re.match(r"^((?:19|20)\d{2})(?:-(\d{2}))?$", v)
            if not m:
                self.err("DATE_NOT_IN_SOURCE", eid, "%s '%s' is not a YYYY or YYYY-MM date; use dateText for the "
                         "source wording" % (key, v))
                continue
            y, mo = m.group(1), m.group(2)
            if y not in src.years:
                self.err("DATE_NOT_IN_SOURCE", eid, "%s year %s is not in your resume" % (key, y))
            elif mo and (int(mo), y) not in src.pairs:
                self.err("DATE_PRECISION_ADDED", eid, "%s month %s/%s is not in your resume; keep the source "
                         "precision (use dateText, for example 'Summer %s', or just '%s')" % (key, mo, y, y, y))

    def check_meta(self):
        meta = self.resume.get("meta") if isinstance(self.resume.get("meta"), dict) else {}
        cuts = meta.get("cuts")
        if cuts is None:
            return
        if not isinstance(cuts, list):
            self.err("BAD_REF", "meta.cuts", "meta.cuts must be a list of {ref, reason}")
            return
        for c in cuts:
            ref = _s(c.get("ref")) if isinstance(c, dict) else ""
            kind, nums = parse_ref(ref)
            if kind != "R" or any(("R%d" % n) not in self.src.lines for n in nums):
                self.err("BAD_REF", "meta.cuts", "'%s' is not a line of your resume" % ref)
                continue
            for n in nums:
                self.cited.add("R%d" % n)

    def check_leftovers(self):
        """'{{' or '[ADD:' anywhere outside bullet/summary text (those are resolved and checked above)."""
        def walk(obj, path):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k in ("evidence", "placeholders", "originalText", "textIfUnknown", "ops", "jdTerms"):
                        continue
                    if k == "text":
                        continue    # bullet and summary text is resolved and checked in check_text_item
                    walk(v, path + "." + _s(k))
            elif isinstance(obj, list):
                for i, v in enumerate(obj):
                    walk(v, "%s[%d]" % (path, i))
            elif isinstance(obj, str) and ("{{" in obj or "[ADD:" in obj):
                self.err("PLACEHOLDER_LEFT", path.lstrip("."), "placeholder text left in '%s'" % obj[:60])
        walk({k: v for k, v in self.resume.items() if k != "meta"}, "")

    def check_unlisted_cuts(self):
        final_toks = set(expand(tokens(" ".join(_collect_strings(self.resume)))))
        for rid in self.src.order:
            if rid in self.cited or self.src.sections.get(rid) in ("header_footer", "contact"):
                continue
            text = self.src.lines[rid]
            if _looks_like_heading(text):
                continue
            tn = _norm(text)
            if any(q and q in tn for q in self.quotes):
                continue
            content = [w for w in expand(tokens(text)) if w not in STOP and len(w) > 2]
            if not content:
                continue
            used = sum(1 for w in content if w in final_toks)
            if used / float(len(content)) >= 0.6:
                continue
            self.warn("UNLISTED_CUT", rid, "'%s' is not in the new resume and not listed in meta.cuts; keep it or "
                      "list it as a cut with a reason" % text.strip()[:80])


def _collect_strings(obj):
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("evidence", "placeholders", "originalText", "ops", "jdTerms", "meta"):
                continue
            out.extend(_collect_strings(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_collect_strings(v))
    elif isinstance(obj, str):
        out.append(obj)
    return out


HEADING_WORDS = {"education", "experience", "work", "employment", "history", "projects", "project", "skills",
                 "skill", "activities", "leadership", "summary", "objective", "profile", "certifications",
                 "certificates", "awards", "honors", "volunteer", "volunteering", "interests", "languages",
                 "publications", "coursework", "relevant", "professional", "technical", "additional",
                 "information", "references", "and", "involvement", "campus", "extracurricular", "other"}


def _looks_like_heading(text):
    t = text.strip().rstrip(":")
    words = tokens(t)
    if not words or len(words) > 4 or re.search(r"\d", t):
        return False
    return all(w in HEADING_WORDS for w in words) or (t.isupper() and len(words) <= 3)


def check_truth(ledger, answers, resume):
    """Run every check. Returns {"passed", "errors", "warnings", "stats"}; never raises on bad input."""
    empty_stats = {"bullets": 0, "bullets_with_evidence": 0, "placeholders_open": 0, "numbers_from_answers": 0}
    problems = []
    if not isinstance(ledger, dict) or not isinstance(ledger.get("resume_lines"), list):
        problems.append({"code": "INVALID_INPUT", "where": "ledger", "detail": "ledger.json must have resume_lines"})
    if not isinstance(resume, dict) or not isinstance(resume.get("basics"), dict) or \
            not isinstance(resume.get("sections"), list):
        problems.append({"code": "INVALID_INPUT", "where": "resume",
                         "detail": "resume.json must be an object with basics and sections"})
    if answers is not None and not isinstance(answers, dict):
        problems.append({"code": "INVALID_INPUT", "where": "answers", "detail": "answers.json must be an object"})
    if problems:
        return {"passed": False, "errors": problems, "warnings": [], "stats": empty_stats}
    # Shape first (A19): a wrong kind, an unknown field or a bad ops value is reported with its path.
    shape = []
    if isinstance(answers, dict):
        shape += schema_errors(answers, "answers.schema.json", "BAD_ANSWERS", "answers.json")
    shape += schema_errors(resume, "resume.schema.json", "BAD_RESUME_SCHEMA", "resume.json")
    try:
        c = _Checker(ledger, answers if isinstance(answers, dict) else {}, resume)
        c.run()
    except (TypeError, ValueError, AttributeError, KeyError, IndexError, RecursionError) as e:
        return {"passed": False, "errors": shape + [{"code": "INVALID_INPUT", "where": "resume",
                                                     "detail": "could not read the input (%s)" % e.__class__.__name__}],
                "warnings": [], "stats": empty_stats}
    errors = shape + c.errors
    return {"passed": not errors, "errors": errors, "warnings": c.warnings, "stats": c.stats}


SCHEMA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))), "schemas")
_SCHEMAS = {}
MAX_SCHEMA_ERRORS = 20


def _load_schema(name):
    if name not in _SCHEMAS:
        try:
            with open(os.path.join(SCHEMA_DIR, name), "r", encoding="utf-8") as f:
                _SCHEMAS[name] = json.load(f)
        except (OSError, ValueError):
            _SCHEMAS[name] = None
    return _SCHEMAS[name]


def schema_errors(instance, schema_name, code, label):
    """Validate against SKILL/schemas/<schema_name> with the bundled stdlib validator (the subset our schemas
    use). Returns [{"code", "where": "<path>", "detail": "<file>: <message>"}]; [] when the schema or the
    validator is unavailable."""
    schema = _load_schema(schema_name)
    if schema is None:
        return []
    try:
        from ..panel import schema_lite
    except ImportError:          # pragma: no cover - the validator ships with the skill
        return []
    out = []
    for e in schema_lite.validate(instance, schema, max_errors=MAX_SCHEMA_ERRORS):
        path, _sep, msg = e.partition(": ")
        path = re.sub(r"^\$\.?", "", path) or "(top level)"
        item = {"code": code, "where": path, "detail": "%s: %s %s" % (label, path, msg)}
        if item not in out:
            out.append(item)
    return out


def check_truth_files(ledger_path, answers_path, resume_path):
    """Convenience wrapper for the CLI: read the three JSON files (answers may be missing)."""
    def load(p):
        if not p or not os.path.exists(p):
            return None
        try:
            return util.read_json(p)
        except (OSError, ValueError):
            return "__unreadable__"
    ledger, answers, resume = load(ledger_path), load(answers_path), load(resume_path)
    if answers == "__unreadable__":
        answers = []
    return check_truth(ledger, answers, resume)


if __name__ == "__main__":   # pragma: no cover - manual use: python3 -m hp.rewrite.truth L A R
    import sys
    print(json.dumps(check_truth_files(*sys.argv[1:4]), indent=2, ensure_ascii=False))
