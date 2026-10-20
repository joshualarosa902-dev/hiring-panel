"""Small text helpers shared by the screening modules: bullets, words, language guess, masking."""
import re
import unicodedata

from ..util import PHONE_INTL_RE, mask_contact, norm_text

# A leading bullet marker. Real glyphs may touch the text ("•Built"); ASCII-like markers ("-", "*",
# "1.") need whitespace after them so "-5%" or "4.0 GPA" never count as bullets. "□" is what ingest
# leaves for icon-font glyphs.
BULLET_RE = re.compile(
    r"^\s*(?:[•●▪◦‣∙·►▶➢➤✓✔■◆❖○◉➔→□▫◾◽⁃]\s*|[*>\-–]\s+|\(?\d{1,2}[.)]\s+)(?=\S)")

# Words for counting and openers: a letter or digit, then word characters and a few joiners.
WORD_RE = re.compile(r"[^\W_][\w'’+#./&-]*")
ALPHA_WORD_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?")

# National phone formats seen outside the US: 0 + 9 to 12 digits in groups ("07700 900123",
# "030 1234567", "06 12 34 56 78"). Only used on contact lines.
PHONE_NATIONAL_RE = re.compile(r"(?<![\w/.])0\d{1,4}(?:[\s./-]?\d{2,4}){2,4}(?![\w/])")

_LATIN_LIMIT = 0x250
_DOMAIN_RE = re.compile(r"(?i)\.(?:com|org|net|edu|io|dev|co|me)\b")

# Common function words of a few languages, used only to guess that a resume is NOT in English.
_FUNCTION_WORDS = {
    "es": "de la el en y los las del con por para una un que se su al como más sus o",
    "fr": "le la les des du et en pour avec une un dans sur au aux par est que qui ou",
    "de": "der die das und mit für von zu im bei auf ein eine den dem des ist sich als oder",
    "pt": "de da do e em com para os as um uma no na dos das pelo pela ou",
    "it": "il di e la per con una un del della nel che le gli dei",
    "nl": "de het en van een met voor op aan bij door als zijn",
}
# Tokens that also occur in English text often enough to be useless as a signal.
_ENGLISH_OVERLAP = {"a", "in", "on", "as", "do", "no", "by", "be", "is", "it", "to", "of", "at", "an",
                    "or", "so", "us", "me", "we", "he", "she", "die", "den", "con", "pro", "per", "e",
                    "y", "o", "un", "la", "le", "les", "op", "dem", "das"}

_SCRIPT_CODES = (("CJK", "zh"), ("HIRAGANA", "ja"), ("KATAKANA", "ja"), ("HANGUL", "ko"),
                 ("CYRILLIC", "ru"), ("ARABIC", "ar"), ("DEVANAGARI", "hi"), ("GREEK", "el"),
                 ("HEBREW", "he"), ("THAI", "th"), ("BENGALI", "bn"), ("TAMIL", "ta"))


def clean_line(s):
    """Normalize one line for analysis: ingest's normalization plus trimming."""
    if not isinstance(s, str):
        return ""
    return norm_text(s).strip()


def bullet_split(text):
    """Return (is_bullet, text_without_marker)."""
    m = BULLET_RE.match(text)
    if not m:
        return False, text
    return True, text[m.end():].strip()


def words(text):
    """Word tokens with trailing punctuation removed."""
    out = []
    for w in WORD_RE.findall(text or ""):
        w = w.rstrip(".,/-&'’")
        if w:
            out.append(w)
    return out


def clip(s, n):
    """Trim to n characters, ending with "..." when cut."""
    s = re.sub(r"\s+", " ", s or "").strip()
    if len(s) <= n:
        return s
    return s[: max(0, n - 3)].rstrip() + "..."


def snippet(text, start, end, side=60, limit=160):
    """A short window of text around [start, end) with "..." where it was cut."""
    a = max(0, start - side)
    b = min(len(text), end + side)
    s = text[a:b].strip()
    if a > 0:
        s = "..." + s
    if b < len(text):
        s = s + "..."
    return clip(s, limit)


def mask_all(s):
    """Mask emails and phone numbers (US, international and national formats) for display."""
    s = mask_contact(s or "")

    def _tail(m):
        digits = re.sub(r"\D", "", m.group(0))
        if len(digits) < 7:
            return m.group(0)
        return "***-***-" + digits[-4:]
    s = PHONE_INTL_RE.sub(_tail, s)
    return PHONE_NATIONAL_RE.sub(_tail, s)


# ---------------------------------------------------------------- letter spacing ("E D U C A T I O N")
# Two-letter groups appear when a PDF reader keeps a kerned pair together ("E D U C AT I O N"). Common
# two-letter words never belong to a spaced run, so "I am a U S citizen" is left alone.
_COMMON_PAIRS = set("am an as at be by do go he if in is it me my no of on or so to up us we".split())


def _spaced_run_ok(run):
    """True when a run of 1-2 letter groups is letter spacing, not ordinary short words."""
    if len(run) < 4:
        return False
    singles = sum(1 for s in run if len(s) == 1)
    if singles < 3 or singles * 4 < len(run) * 3:
        return False
    for a, b in zip(run, run[1:]):
        if len(a) == 2 and len(b) == 2:
            return False
    for s in run:
        if len(s) == 2 and s.lower() == s and s in _COMMON_PAIRS:
            return False
    letters = "".join(run)
    if letters.isupper() or letters.islower():
        return True
    # "E d u c a t i o n": capitals only at the start of a word, and only a few of them
    return letters[0].isupper() and sum(1 for c in letters if c.isupper()) <= 3


_SPACED_TOK_RE = re.compile(r"(\(?)([^\W\d_]{1,2})([,.;:)!?]*)$")


def letter_spaced_runs(text):
    """Character spans [(start, end)] of letter-spaced runs such as "S K I L L S" (punctuation around
    the run, as in "P Y T H O N,", stays outside the span)."""
    toks = []
    for m in re.finditer(r"\S+", text or ""):
        t = _SPACED_TOK_RE.match(m.group(0))
        toks.append((m.start(), m.end(), t))
    out = []
    i, n = 0, len(toks)
    while i < n:
        t = toks[i][2]
        if t is None or t.group(3):
            i += 1
            continue
        j = i
        while j + 1 < n and toks[j + 1][2] is not None and not toks[j + 1][2].group(1) and \
                toks[j + 1][0] == toks[j][1] + 1 and not toks[j][2].group(3):
            j += 1
        run = [x[2].group(2) for x in toks[i:j + 1]]
        if _spaced_run_ok(run):
            a = toks[i][0] + len(toks[i][2].group(1))
            b = toks[j][1] - len(toks[j][2].group(3))
            out.append((a, b))
        i = j + 1
    return out


def collapse_letter_spacing(text):
    """Remove the spaces inside letter-spaced runs: "S K I L L S" -> "SKILLS".

    Returns (collapsed_text, index_map) where index_map[k] is the position in `text` of character k of
    the collapsed text, so a match found in the collapsed text can be quoted from the original."""
    text = text or ""
    runs = letter_spaced_runs(text)
    if not runs:
        return text, None
    out, idx = [], []
    pos = 0
    for a, b in runs:
        for k in range(pos, a):
            out.append(text[k])
            idx.append(k)
        for k in range(a, b):
            if text[k] != " ":
                out.append(text[k])
                idx.append(k)
        pos = b
    for k in range(pos, len(text)):
        out.append(text[k])
        idx.append(k)
    return "".join(out), idx


# ---------------------------------------------------------------- rating graphics ("Python ● ● ● ○ ○")
# Three or more rating symbols in a row (single spaces allowed), after some text. A lone "•" between two
# words is a separator, not a rating.
RATING_GLYPHS = "●○◉◯★☆•▪■□◆◇◐◑⬤⚫⚪✦✧▮▯█░▒▓"
RATING_RUN_RE = re.compile(r"[ ]?(?:[%s] ?){2,}[%s]" % (re.escape(RATING_GLYPHS), re.escape(RATING_GLYPHS)))


def strip_rating(text):
    """Remove rating-symbol runs that follow some words ("Python • • • • ○" -> "Python").

    Returns (text, True if anything was removed). A run at the very start of a line is left alone."""
    text = text or ""
    out, pos, hit = [], 0, False
    for m in RATING_RUN_RE.finditer(text):
        if not re.search(r"[^\W_]", text[:m.start()]):
            continue
        out.append(text[pos:m.start()])
        pos = m.end()
        hit = True
    if not hit:
        return text, False
    out.append(text[pos:])
    return re.sub(r"\s+", " ", "".join(out)).strip(" |,;"), True


def caps_ratio(text):
    """Share of letters that are uppercase (0.0 when there are fewer than 3 letters)."""
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 3:
        return 0.0
    return sum(1 for c in letters if c.isupper()) / float(len(letters))


def _script_of(ch):
    if ord(ch) < _LATIN_LIMIT:
        return "LATIN"
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return "OTHER"
    if name.startswith("LATIN"):
        return "LATIN"
    for prefix, _code in _SCRIPT_CODES:
        if name.startswith(prefix):
            return prefix
    return "OTHER"


def detect_language(text, stopwords_en):
    """Guess whether `text` is English.

    Rule (ARCHITECTURE 6): non-English when under 30% of tokens are English stopwords AND either most
    letters are in a non-Latin script or common non-English function words are frequent. Returns
    (code, details) where code is "en", a two-letter guess, or "und" when the language is unclear.
    """
    # emails and links ("example.com") say nothing about the language (token by token: linear time)
    text = " ".join(t for t in (text or "").split() if "@" not in t and "://" not in t
                    and not t.lower().startswith("www.") and not _DOMAIN_RE.search(t))
    letters = [c for c in text if c.isalpha()]
    details = {"tokens": 0, "en_share": None, "other_share": None, "non_latin_share": 0.0}
    if letters:
        scripts = {}
        for c in letters:
            sc = _script_of(c)
            scripts[sc] = scripts.get(sc, 0) + 1
        non_latin = 1.0 - scripts.get("LATIN", 0) / float(len(letters))
        details["non_latin_share"] = round(non_latin, 3)
    else:
        non_latin = 0.0
        scripts = {}
    toks = [t.lower() for t in ALPHA_WORD_RE.findall(text) if len(t) >= 2]
    details["tokens"] = len(toks)
    if non_latin > 0.30:
        top = sorted(((n, sc) for sc, n in scripts.items() if sc != "LATIN"), reverse=True)
        code = "und"
        if top:
            for prefix, c in _SCRIPT_CODES:
                if prefix == top[0][1]:
                    code = c
                    break
        return code, details
    if len(toks) < 30:
        return "en", details
    en_share = sum(1 for t in toks if t in stopwords_en) / float(len(toks))
    best_code, best_share = None, 0.0
    for code in sorted(_FUNCTION_WORDS):
        fw = set(_FUNCTION_WORDS[code].split()) - _ENGLISH_OVERLAP - set(stopwords_en)
        hits = [t for t in toks if t in fw]
        if len(hits) < 4 or len(set(hits)) < 2:
            continue
        share = len(hits) / float(len(toks))
        if share > best_share:
            best_code, best_share = code, share
    details["en_share"] = round(en_share, 3)
    details["other_share"] = round(best_share, 3)
    if en_share < 0.30 and best_share >= 0.06 and best_share > en_share * 0.6:
        return best_code or "und", details
    return "en", details


def garbled_share(text):
    """Share of 3+ character tokens that look broken: lowercase with no vowel, or mixed with odd
    symbols. Returns (share, token_count)."""
    toks = [t for t in re.split(r"\s+", text or "") if len(t) >= 3]
    if not toks:
        return 0.0, 0
    bad = 0
    for t in toks:
        core = t.strip(".,;:()[]{}\"'!?")
        if not core:
            continue
        has_alpha = any(c.isalpha() for c in core)
        odd = sum(1 for c in core if not (c.isalnum() or c in ".,'’-+#/&@%$():;|•–_"))
        if odd and has_alpha and odd >= len(core) / 3.0:
            bad += 1
            continue
        if (has_alpha and core.isalpha() and not core.isupper() and len(core) >= 4
                and all(ord(c) < 128 for c in core) and not re.search(r"[aeiouyAEIOUY]", core)):
            bad += 1
    return bad / float(len(toks)), len(toks)
