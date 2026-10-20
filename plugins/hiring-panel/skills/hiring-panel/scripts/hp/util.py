"""Shared helpers for Hiring Panel. Python 3.8+ standard library only.

Other modules may ADD functions here but must not change existing signatures (see ARCHITECTURE.md).
"""
import hashlib
import json
import math
import os
import re
import tempfile
import unicodedata
from datetime import date

LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}
QUOTES = {"‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
          "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"'}
DASHES = "‐‑‒–—―−"
SPACES = "             　"

EMAIL_RE = re.compile(r"(?i)\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b")
PHONE_US_RE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)")
PHONE_INTL_RE = re.compile(r"\+\d{1,3}[\s.-]?(?:\(?\d{1,4}\)?[\s.-]?){2,5}\d{2,4}")
LINKEDIN_RE = re.compile(r"(?i)(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/(?:in|pub)/[\w%-]+/?")
GITHUB_RE = re.compile(r"(?i)(?:https?://)?github\.com/[\w-]+")
URL_RE = re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>\"')]+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|org|net|io|dev|me|co|edu|ai|app|site|xyz)(?:/[^\s<>\"')]*)?")


def norm_text(s):
    """NFKC, ligatures expanded, curly quotes straightened, dash family -> en dash, odd spaces -> space,
    runs of spaces/tabs collapsed. Newlines are kept."""
    if not s:
        return ""
    for k, v in LIGATURES.items():
        s = s.replace(k, v)
    s = unicodedata.normalize("NFKC", s)
    for k, v in QUOTES.items():
        s = s.replace(k, v)
    for d in DASHES:
        s = s.replace(d, "–")
    for sp in SPACES:
        s = s.replace(sp, " ")
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t]+", " ", s)
    return s


def norm_for_match(s):
    """norm_text + casefold + all whitespace collapsed to single spaces; used for verbatim-quote checks."""
    return re.sub(r"\s+", " ", norm_text(s).casefold()).strip()


def round5(x):
    """Round to the nearest multiple of 5 (halves up) and clamp to 0..100."""
    if x is None:
        return None
    v = 5 * int(math.floor(x / 5.0 + 0.5))
    return max(0, min(100, v))


def slugify(s, maxlen=60):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode("ascii").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    s = s[:maxlen].rstrip("-")
    return s or "run"


def today_iso():
    """The only clock read in the package. Tests pin it with the HP_AS_OF environment variable."""
    pinned = os.environ.get("HP_AS_OF")
    if pinned:
        return pinned
    return date.today().isoformat()


def now_stamp():
    """Local time as YYYY-MM-DD-HHMM for run-folder names. Tests pin it with HP_NOW."""
    pinned = os.environ.get("HP_NOW")
    if pinned:
        return pinned
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d-%H%M")


def mask_contact(s):
    """Mask emails and phone numbers for screenshots: j***@g***.com, (***) ***-0142."""
    def _email(m):
        user, _, dom = m.group(0).partition("@")
        host, _, tld = dom.rpartition(".")
        return (user[:1] + "***@" + host[:1] + "***." + tld) if host else "***"
    def _phone(m):
        digits = re.sub(r"\D", "", m.group(0))
        return "***-***-" + digits[-4:]
    s = EMAIL_RE.sub(_email, s or "")
    return PHONE_US_RE.sub(_phone, s)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _atomic_write_bytes(path, data):
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=d)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def write_text(path, s):
    if not s.endswith("\n"):
        s += "\n"
    _atomic_write_bytes(path, s.replace("\r\n", "\n").encode("utf-8"))


def write_json(path, obj):
    write_text(path, json.dumps(obj, ensure_ascii=False, indent=2))


def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
