"""Text normalization and text-level signals shared by every reader (ATS spec 4 and 5).

normalize_line() = hp.util.norm_text (NFKC, ligatures, quotes, dashes, odd spaces) plus:
- bullet glyphs (• ● ▪ ◦ ‣ ∙ · ► ▶ ➢ ➤ ✓ ✔ ■ ◆ ❖) -> "•"; a leading "-", "*", "+", "–" or Word's
  Symbol/Wingdings private-use bullet followed by a space -> "• " (not when the rest is a date,
  so a split date range like "– Present" survives for the screening check);
- other private-use characters (icon fonts, U+E000-U+F8FF and planes 15/16) -> "□", counted;
- U+FFFD replacement characters are kept and counted;
- C0 control characters and zero-width characters are removed; whitespace is collapsed.
Text is never re-ordered and typos are never fixed.
"""
import re
import unicodedata

from hp.util import norm_text, EMAIL_RE, PHONE_US_RE, PHONE_INTL_RE, LINKEDIN_RE, URL_RE

BULLET_GLYPHS = "\u2022\u25cf\u25aa\u25e6\u2023\u2219\u00b7\u25ba\u25b6\u27a2\u27a4\u2713\u2714\u25a0\u25c6\u2756"
_BULLET_TABLE = dict((ord(c), "\u2022") for c in BULLET_GLYPHS)
# Word writes list bullets in the Symbol/Wingdings fonts; PDF extractors return them as private-use
# code points. These are bullets, not icons, when they start a line.
PUA_BULLETS = set([0xF0B7, 0xF0A7, 0xF0D8, 0xF076, 0xF0FC, 0xF06E, 0xF0A8, 0xF071, 0xF06C, 0xF075,
                   0xF077, 0xF0D9, 0xF0E8, 0xF09F, 0xF097, 0xF096])
ICON_PLACEHOLDER = "\u25a1"   # □
ZERO_WIDTH = "\u200b\u200c\u200d\u2060\ufeff\u00ad\u180e"
_ZW_TABLE = dict((ord(c), None) for c in ZERO_WIDTH)
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SURROGATE_RE = re.compile("[\ud800-\udfff]")
_WS_RE = re.compile(r"\s+")

MONTH = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
         r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?")
SEASON = r"(?:spring|summer|fall|autumn|winter)"
YEAR = r"(?:19|20)\d{2}"
DATE = (r"(?:(?:%s|%s)\s*,?\s*(?:%s|'\d{2})|\d{1,2}\s*/\s*(?:%s|\d{2})|%s(?:\s*[-/]\s*\d{1,2}(?!\d))?)"
        % (MONTH, SEASON, YEAR, YEAR, YEAR))
PRESENT = r"(?:present|current|now|ongoing|today)"
DATE_RANGE_RE = re.compile(r"(?i)(?<![\w/])%s\s*(?:\u2013|-|to|through|until|thru)\s*(?:%s|%s)(?![\w/])"
                           % (DATE, DATE, PRESENT))
_LEADING_DATE_RE = re.compile(r"(?i)^(?:%s|%s)(?!\w)" % (DATE, PRESENT))
_LEADING_BULLET_RE = re.compile(r"^[\-\*\+\u2013]\s+(?=\S)")
_LEADING_O_RE = re.compile(r"^o\s+(?=[A-Z])")

LETTER_SPACED_RE = re.compile(r"\b(?:[A-Za-z] ){3,}[A-Za-z]\b")
PAGE_NUMBER_RE = re.compile(r"(?i)^\s*(?:page\s*\d+(?:\s*(?:of|/)\s*\d+)?|\d+\s*(?:of|/)\s*\d+|-\s*\d+\s*-)\s*$")
SECTION_WORDS = (
    "experience", "education", "skills", "projects", "work history", "employment", "leadership",
    "activities", "volunteer", "volunteering", "awards", "honors", "certifications", "certificates",
    "summary", "profile", "objective", "publications", "coursework", "languages", "interests",
    "references", "involvement", "achievements", "contact", "technical skills", "research",
)
_HEADING_WORD_RE = re.compile(r"(?i)\b(?:%s)\b" % "|".join(re.escape(w) for w in SECTION_WORDS))


class TextStats(object):
    """Counters filled while normalizing (private-use and replacement characters)."""

    def __init__(self):
        self.private_use = 0
        self.replacement = 0


def is_private_use(cp):
    return 0xE000 <= cp <= 0xF8FF or 0xF0000 <= cp <= 0xFFFFD or 0x100000 <= cp <= 0x10FFFD


def normalize_line(s, stats=None):
    """Normalize one line of extracted text (see module docstring). Never raises on odd input."""
    if not s:
        return ""
    if not isinstance(s, str):
        s = str(s)
    s = s.replace("\n", " ").replace("\r", " ")
    s = _SURROGATE_RE.sub("\ufffd", s)      # lone surrogates cannot be written as UTF-8
    s = s.translate(_ZW_TABLE)
    s = _CTRL_RE.sub("", s)
    s = s.lstrip(" \t\u00a0\u3000")
    # A Symbol/Wingdings bullet at the start of the line is a bullet, not an icon.
    if s and ord(s[0]) in PUA_BULLETS and (len(s) == 1 or s[1] in " \t\u00a0"):
        s = "\u2022" + s[1:]
    s = norm_text(s)
    s = s.translate(_BULLET_TABLE)
    out = []
    for ch in s:
        cp = ord(ch)
        if is_private_use(cp):
            out.append(ICON_PLACEHOLDER)
            if stats is not None:
                stats.private_use += 1
        else:
            if cp == 0xFFFD and stats is not None:
                stats.replacement += 1
            out.append(ch)
    s = _WS_RE.sub(" ", "".join(out)).strip()
    # Leading ASCII/dash bullets -> "• " unless the rest is a date (keeps "– Present" intact).
    m = _LEADING_BULLET_RE.match(s)
    if m and not _LEADING_DATE_RE.match(s[m.end():]):
        s = "\u2022 " + s[m.end():]
    else:
        m = _LEADING_O_RE.match(s)
        if m:
            s = "\u2022 " + s[m.end():]
    if s.startswith("\u2022") and len(s) > 1 and s[1] != " ":
        s = "\u2022 " + s[1:]
    return s


def word_count(text):
    return len(re.findall(r"[^\W_][\w'+#./@-]*", text or "", re.UNICODE))


def letter_spaced_count(text):
    """Number of letter-spaced words such as 'J O R D A N' (ATS spec 5)."""
    return len(LETTER_SPACED_RE.findall(text or ""))


def has_contact(text):
    t = text or ""
    return bool(EMAIL_RE.search(t) or PHONE_US_RE.search(t) or PHONE_INTL_RE.search(t) or LINKEDIN_RE.search(t))


def has_date_range(text):
    return bool(DATE_RANGE_RE.search(text or ""))


def looks_like_heading(text, style=None, bold=False):
    """A short line that reads like a resume section heading (used for table/text-box facts only;
    the screening module owns real section detection)."""
    t = (text or "").strip().strip("\u2022").strip()
    if not t or len(t) > 45 or "@" in t or t.endswith("."):
        return False
    words = t.split()
    if len(words) > 6:
        return False
    if style and re.match(r"(?i)\s*(heading|title)", style):
        return True
    letters = [c for c in t if c.isalpha()]
    upper = bool(letters) and sum(1 for c in letters if c.isupper()) >= 0.8 * len(letters)
    if _HEADING_WORD_RE.search(t) and (upper or bold or t.endswith(":") or len(words) <= 3):
        return True
    return False


# --- garbled-text detection -------------------------------------------------------------------------
_VOWELS = set("aeiouyAEIOUY\u00e0\u00e1\u00e2\u00e3\u00e4\u00e5\u00e8\u00e9\u00ea\u00eb\u00ec\u00ed\u00ee\u00ef\u00f2\u00f3\u00f4\u00f5\u00f6\u00f9\u00fa\u00fb\u00fc\u00fd\u00ff\u00e6\u0153\u00f8\u00c0\u00c1\u00c2\u00c3\u00c4\u00c5\u00c8\u00c9\u00ca\u00cb\u00cc\u00cd\u00ce\u00cf\u00d2\u00d3\u00d4\u00d5\u00d6\u00d9\u00da\u00db\u00dc\u00dd\u0178\u00c6\u0152\u00d8")
_JUNK = set("!\"#$%&'()*+;<=>?@[\\]^`{}~")
_MOJIBAKE_RE = re.compile("[\u00c2\u00c3][\u0080-\u00bf]|\u00e2\u20ac|\u00ef\u00bf\u00bd")
_EDGE_PUNCT = "\"'()[]{}<>.,;:!?*\u2022|/\u2013-"


def _script(ch):
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return "?"
    return name.split(" ", 1)[0]


def _bad_token(tok):
    if "(cid:" in tok or "\ufffd" in tok:
        return True
    if _MOJIBAKE_RE.search(tok):
        return True
    core = tok.strip(_EDGE_PUNCT)
    if not core:
        return False
    for ch in core:
        cat = unicodedata.category(ch)
        if cat in ("Co", "Cs", "Cn") or (cat == "Cc" and ch not in "\t\n"):
            return True
    if EMAIL_RE.fullmatch(core) or URL_RE.match(core):
        return False
    letters = [c for c in core if c.isalpha()]
    if not letters:
        return False
    scripts = set(_script(c) for c in letters)
    if len(scripts) > 1 and "LATIN" in scripts and not scripts <= set(["LATIN", "GREEK"]):
        return True
    junk_inside = sum(1 for c in core[1:-1] if c in _JUNK)
    if junk_inside >= 2:
        return True
    if scripts == set(["LATIN"]) and len(letters) >= 5 and core.isalpha() and not core.isupper():
        if not any(c in _VOWELS for c in core):
            return True
    return False


def garbled_stats(text):
    """Return (bad_tokens, tokens, replacement_chars, chars) for a block of text."""
    tokens = (text or "").split()
    bad = sum(1 for t in tokens if _bad_token(t))
    chars = len(text or "")
    return bad, len(tokens), (text or "").count("\ufffd"), chars


def is_garbled(text):
    """ATS spec 5: more than 15% of tokens vowelless or symbol-mixed, or U+FFFD above 1% of characters."""
    bad, n, fffd, chars = garbled_stats(text)
    if chars and fffd / float(chars) > 0.01:
        return True
    if n >= 20:
        return bad / float(n) > 0.15
    if n >= 5:
        return bad / float(n) > 0.5
    return False


def page_number_lines(lines):
    """Count lines that are only a page number ('Page 2 of 3', '2 / 3', '- 2 -')."""
    return sum(1 for t in lines if PAGE_NUMBER_RE.match(t or ""))


def repeated_page_lines(pages):
    """Distinct non-trivial lines that sit in the first or last 3 lines of every page of a multi-page
    document (running headers/footers leaking into the text). `pages` is a list of line lists."""
    if len(pages) < 2:
        return 0
    def key(t):
        return re.sub(r"\d+", "#", re.sub(r"\s+", " ", t.strip().lower()))
    edge_sets = []
    for lines in pages:
        nonempty = [t for t in lines if t and t.strip()]
        edges = nonempty[:3] + nonempty[-3:]
        edge_sets.append(set(key(t) for t in edges if len(t.strip()) >= 3))
    common = set.intersection(*edge_sets) if edge_sets else set()
    return len([k for k in common if not PAGE_NUMBER_RE.match(k.replace("#", "1"))])
