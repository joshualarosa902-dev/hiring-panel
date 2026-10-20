"""Job posting parsing (ARCHITECTURE 6.1, ATS spec 11): the ONE job-posting classifier.

parse_jd() splits the posting into blocks that PARTITION every non-empty line in order. A line is
"non-empty" when line.strip() != "" after CRLF/CR are turned into LF and the text is split on LF;
block lines hold line.strip() (original characters, nothing else changed). Headings are the first line
of their block. Equal-opportunity sentences always form boilerplate blocks, and a line inside a
required block that is marked preferred ("... is a plus") becomes its own preferred block.
"""
import re

from ..util import norm_text
from .lexicon import norm_heading
from .textutil import bullet_split, caps_ratio

BLOCK_KINDS = ("required", "preferred", "responsibility", "boilerplate", "unspecified")
MAX_SCAN_CHARS = 3000   # analysis reads at most this much of one posting line (blocks keep it all)

EEO_RE = re.compile(
    r"(?i)equal (?:employment )?opportunit|\beeo\b|affirmative action|without regard to|"
    r"regardless of (?:race|color|religion|sex|gender|age|national origin|disability|veteran)|"
    r"protected veteran|race, colou?r, religion|reasonable accommodation|e-verify|"
    r"discriminat\w+ (?:on the basis|based on|against)")
REQUIRED_MARK_RE = re.compile(r"(?i)\b(?:required|requires|requirement|must|minimum|at least|need to have|"
                              r"essential|mandatory)\b")
PREFERRED_MARK_RE = re.compile(r"(?i)\b(?:preferred|preferably|a plus|big plus|huge plus|pluses|"
                               r"nice[- ]to[- ]have|bonus|ideally|desired|desirable|advantageous|"
                               r"familiarity with|exposure to)\b")
_CLAUSE_SPLIT_RE = re.compile(r";|,\s+and\s+|(?<=[.!?])\s+(?=[A-Z(\"'])")
_HEADING_FILLER = set(("key main core primary our the your job role position minimum basic additional "
                       "other essential desired general a an of and to in for this internship intern "
                       "summer what who you we will you'll we're are is").split())
_TITLE_WORDS = set(("intern internship analyst engineer manager assistant associate coordinator specialist "
                    "developer designer nurse teacher representative consultant technician scientist "
                    "administrator officer director lead fellow apprentice trainee clerk cashier server "
                    "accountant writer editor researcher strategist planner advisor counselor therapist "
                    "pharmacist auditor architect producer marketer recruiter generalist programmer "
                    "tutor instructor supervisor operator agent bookkeeper paralegal co-op").split())
_TITLE_PREFIX_RE = re.compile(r"(?i)^(?:job title|position title|position|role|title|job)\s*:\s*")

PLATFORM_PATTERNS = (
    ("workday", re.compile(r"(?i)myworkdayjobs\.com|myworkdaysite\.com|\.wd\d+\.myworkday")),
    ("greenhouse", re.compile(r"(?i)greenhouse\.io")),
    ("lever", re.compile(r"(?i)jobs\.lever\.co")),
    ("icims", re.compile(r"(?i)icims\.com")),
    ("taleo", re.compile(r"(?i)taleo\.net")),
    ("oracle_recruiting", re.compile(r"(?i)oraclecloud\.com/hcmUI")),
    ("smartrecruiters", re.compile(r"(?i)smartrecruiters\.com")),
    ("ashby", re.compile(r"(?i)ashbyhq\.com")),
)


def split_jd_lines(jd_text):
    """Non-empty lines of the posting, stripped, in order (the ledger numbers J# from these)."""
    t = (jd_text or "").replace("\r\n", "\n").replace("\r", "\n")
    return [ln.strip() for ln in t.split("\n") if ln.strip()]


def _strip_md(s):
    s = s.strip()
    s = re.sub(r"^#{1,6}\s*", "", s)
    m = re.match(r"^(\*\*|__)(.+?)(\*\*|__)\s*(:?)\s*$", s)
    if m:
        s = m.group(2).strip() + m.group(4)
    return s.strip()


def _match_phrase(norm, lex, plain):
    """Kind for a normalized heading text. Formatted headings may contain a known phrase; plain lines
    must equal one, apart from generic filler words ("Key Responsibilities")."""
    if norm in lex.jd_heading_exact:
        return lex.jd_heading_exact[norm]
    padded = " " + norm + " "
    for phrase, kind in lex.jd_headings:
        if (" " + phrase + " ") in padded:
            if not plain:
                return kind
            rest = padded.replace(" " + phrase + " ", " ", 1).split()
            if len(norm.split()) <= 5 and all(w in _HEADING_FILLER for w in rest):
                return kind
    return None


def classify_jd_line(raw, lex):
    """Heading detection for one posting line.

    Returns (kind_or_None, heading_text_or_None, is_heading). kind None with is_heading True means a
    sub-heading that keeps the current kind. Inline labels ("Requirements: Excel, SQL") return the
    label's kind with is_heading True and heading = the label.
    """
    md = raw.lstrip().startswith("#")
    is_bullet, _ = bullet_split(norm_text(raw))
    if is_bullet and not md:
        return None, None, False
    s = _strip_md(raw)
    bold = s != raw.strip() and not md
    core = s.rstrip(":").strip()
    colon = s.endswith(":")
    words = core.split()
    if not core:
        return None, None, False
    if 1 <= len(words) <= 8 and len(core) <= 70 and not core.endswith(".") and not re.search(r"\.\s", core):
        norm = norm_heading(core)
        caps = caps_ratio(core) >= 0.8
        formatted = md or bold or colon or caps
        kind = _match_phrase(norm, lex, plain=not formatted)
        if kind is None and norm.startswith("about ") and len(words) <= 6 and (formatted or len(words) <= 4):
            kind = "boilerplate"
        if kind is not None:
            return kind, core, True
        if md or bold or (colon and len(words) <= 4) or (caps and len(words) >= 2):
            return None, core, True
    # inline label: "Requirements: Bachelor's degree in ..."
    m = re.match(r"^\s*(?:\*\*)?([^:]{2,40}?)(?:\*\*)?\s*:\s*\S", raw)
    if m and len(m.group(1).split()) <= 5:
        label = m.group(1).strip().strip("*_# ")
        kind = _match_phrase(norm_heading(label), lex, plain=True)
        if kind is not None:
            return kind, label, True
    return None, None, False


def clauses(text):
    """Split a line into clauses; return [(start, end, importance_or_None)]. Preferred wins inside
    its clause."""
    out = []
    pos = 0
    for m in list(_CLAUSE_SPLIT_RE.finditer(text)) + [None]:
        end = m.start() if m else len(text)
        seg = text[pos:end]
        imp = None
        if PREFERRED_MARK_RE.search(seg):
            imp = "preferred"
        elif REQUIRED_MARK_RE.search(seg):
            imp = "required"
        out.append((pos, end, imp))
        if m:
            pos = m.end()
    return out


def parse_jd(jd_text, lex):
    """Return dict(lines=[...], blocks=[...]) where each line is
    dict(text, kind, block, heading(bool), eeo(bool), clauses) and blocks follow ARCHITECTURE 6.1."""
    raw_lines = split_jd_lines(jd_text)
    lines = []
    kind = "unspecified"
    seen_heading = False
    for raw in raw_lines:
        hk, htext, is_heading = classify_jd_line(raw, lex)
        eeo = bool(EEO_RE.search(raw))
        if is_heading:
            if hk is not None:
                kind = hk
            seen_heading = True
            line_kind = "boilerplate" if eeo else kind
            lines.append({"text": raw, "kind": line_kind, "heading": True, "heading_text": htext,
                          "eeo": eeo, "new_block": True})
            continue
        line_kind = kind
        if eeo:
            line_kind = "boilerplate"
        elif kind == "required" and PREFERRED_MARK_RE.search(raw) and not REQUIRED_MARK_RE.search(raw):
            line_kind = "preferred"
        lines.append({"text": raw, "kind": line_kind, "heading": False, "heading_text": None, "eeo": eeo,
                      "new_block": False})
    blocks = []
    for i, ln in enumerate(lines):
        if not blocks or ln["new_block"] or ln["kind"] != blocks[-1]["kind"]:
            blocks.append({"kind": ln["kind"], "heading": ln["heading_text"] if ln["heading"] else None,
                           "lines": []})
        blocks[-1]["lines"].append(ln["text"])
        ln["block"] = len(blocks) - 1
        ln["scan"] = ln["text"][:MAX_SCAN_CHARS]
        ln["clauses"] = clauses(ln["scan"])
    return {"lines": lines, "blocks": blocks, "has_heading": seen_heading}


def guess_title(parsed, lex, jd_title=None):
    """The posting's job title: --jd-title, else the first short line before the first heading
    (preferring a line with a job-title word)."""
    if isinstance(jd_title, str) and jd_title.strip():
        return clean_title(jd_title)
    pre = []
    for ln in parsed["lines"]:
        if ln["heading"]:
            break
        pre.append(ln["text"])
        if len(pre) >= 4:
            break
    cands = [t for t in pre if len(t) <= 150 and 0 < len(_strip_md(t).split()) <= 10 and not t.rstrip().endswith(".")]
    for t in cands:
        ct = clean_title(t)
        if ct and any(w.lower().strip(",.()") in _TITLE_WORDS for w in ct.split()):
            return ct
    for t in cands:
        if ":" in t and not _TITLE_PREFIX_RE.match(_strip_md(t)):
            continue
        ct = clean_title(t)
        if ct:
            return ct
    return None


def clean_title(t):
    s = _strip_md(norm_text(t[:300]))
    s = _TITLE_PREFIX_RE.sub("", s)
    s = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", s)
    s = re.split(r"\s+[-–|]\s+|\s+at\s+|,\s+", s)[0]
    s = re.sub(r"\s+", " ", s).strip(" -–|,:*#")
    return s[:80] or None


def guess_platform(jd_url, jd_text):
    """Platform from the posting URL, else from links inside the posting text."""
    for src in (jd_url or "", jd_text or ""):
        if not src:
            continue
        for name, rx in PLATFORM_PATTERNS:
            if rx.search(src):
                return name
    return "other" if jd_url else "unknown"
