"""Dates, date ranges, entries and gaps (ATS spec 9).

Dates resolve to the month. A month is stored as an integer `y * 12 + (m - 1)` and printed as
"YYYY-MM". Seasons: Spring = Mar-May, Summer = Jun-Aug, Fall/Autumn = Sep-Nov, Winter = Dec (of the
year before) to Feb. A year-only start becomes January and a year-only end becomes December.
"""
import re

MONTHS = {"jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4,
          "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9,
          "september": 9, "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12}
SEASONS = {"spring": (3, 5, 0), "summer": (6, 8, 0), "fall": (9, 11, 0), "autumn": (9, 11, 0),
           "winter": (12, 2, -1)}  # (start month, end month, start-year offset)

_MONTH = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
          r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
_SEASON = r"(?:spring|summer|fall|autumn|winter)"
_Y4 = r"(?:19[5-9]\d|20[0-4]\d)"
DATE_SRC = (r"(?<![\w/.])(?:"
            r"%(m)s\.?,?\s*(?:%(y)s|['’]\d{2})(?!\d)"                     # Jan 2024, Jan. 2024, Jan '24
            r"|%(s)s\s+%(y)s(?!\d)"                                      # Summer 2024
            r"|(?:0?[1-9]|1[0-2])[/.](?:%(y)s)(?!\d)"                    # 01/2024, 1.2024
            r"|(?:0?[1-9]|1[0-2])-%(y)s(?!\d)"                           # 01-2024
            r"|%(y)s[-/.](?:0[1-9]|1[0-2])(?![\d/.-])"                   # 2024-01
            r"|(?:0?[1-9]|1[0-2])/\d{2}(?![\d/])"                        # 01/24 (two-digit year)
            r"|%(y)s(?![\d])"                                            # 2024
            r")") % {"m": _MONTH, "s": _SEASON, "y": _Y4}
PRESENT_SRC = r"(?:present|current(?:ly)?|now|ongoing|today)"
EXPECTED_SRC = r"(?:expected|anticipated|graduating|est\.|incoming|upcoming|projected|planned)"
_CONNECT = r"\s*(?:–|-|\bto\b|\bthrough\b|\buntil\b|\bthru\b|\btill\b)\s*"
DATE_RE = re.compile(DATE_SRC, re.I)
RANGE_RE = re.compile(r"(?P<a>%s)%s(?:%s\s+)?(?P<b>%s|(?<![\w])%s(?![\w]))"
                      % (DATE_SRC, _CONNECT, EXPECTED_SRC, DATE_SRC, PRESENT_SRC), re.I)
EXPECTED_RE = re.compile(r"(?i)(?<![\w])%s(?![\w])" % EXPECTED_SRC)
PRESENT_RE = re.compile(r"(?i)^%s$" % PRESENT_SRC)
# Split range: a line ending in a date (or "date –") and the next line starting with a connector and
# a date or Present.
SPLIT_END_RE = re.compile(r"(?:%s)\s*(?:–|-|to)?\s*$" % DATE_SRC, re.I)
SPLIT_START_RE = re.compile(r"^\s*(?:–|-|to\b)\s*(?:%s|%s)" % (DATE_SRC, PRESENT_SRC), re.I)

FORMAT_FAMILY = {"month_year_name": "name", "season_year": "name", "month_year_numeric": "numeric",
                 "two_digit_year": "numeric", "year_only": "year", "missing": None}


def month_str(m):
    """Month integer -> "YYYY-MM" (None stays None)."""
    if m is None:
        return None
    return "%04d-%02d" % (m // 12, m % 12 + 1)


def as_of_month(as_of):
    y, mo = int(as_of[0:4]), int(as_of[5:7])
    return y * 12 + mo - 1


def _two_digit_year(yy, as_of_m):
    """'24 -> 2024; values more than 10 years past the as-of year mean 19xx."""
    cur = (as_of_m // 12) % 100
    return (2000 + yy) if yy <= cur + 10 else (1900 + yy)


def parse_date(text, as_of_m):
    """Parse one date token. Returns dict(start, end, fmt) with month integers, or None."""
    t = text.strip().lower().replace("’", "'")
    m = re.match(r"^(%s)\.?,?\s*(?:(\d{4})|'(\d{2}))$" % _MONTH, t)
    if m:
        mo = MONTHS.get(m.group(1).rstrip("."), None)
        if mo is None:
            mo = MONTHS.get(m.group(1)[:3])
        if m.group(2):
            y, fmt = int(m.group(2)), "month_year_name"
        else:
            y, fmt = _two_digit_year(int(m.group(3)), as_of_m), "two_digit_year"
        v = y * 12 + mo - 1
        return {"start": v, "end": v, "fmt": fmt}
    m = re.match(r"^(%s)\s+(\d{4})$" % _SEASON, t)
    if m:
        a, b, off = SEASONS[m.group(1)]
        y = int(m.group(2))
        return {"start": (y + off) * 12 + a - 1, "end": y * 12 + b - 1, "fmt": "season_year"}
    m = re.match(r"^(\d{1,2})[/.-](\d{4})$", t)
    if m:
        v = int(m.group(2)) * 12 + int(m.group(1)) - 1
        return {"start": v, "end": v, "fmt": "month_year_numeric"}
    m = re.match(r"^(\d{4})[/.-](\d{2})$", t)
    if m:
        v = int(m.group(1)) * 12 + int(m.group(2)) - 1
        return {"start": v, "end": v, "fmt": "month_year_numeric"}
    m = re.match(r"^(\d{1,2})/(\d{2})$", t)
    if m:
        y = _two_digit_year(int(m.group(2)), as_of_m)
        v = y * 12 + int(m.group(1)) - 1
        return {"start": v, "end": v, "fmt": "two_digit_year"}
    m = re.match(r"^(\d{4})$", t)
    if m:
        y = int(m.group(1))
        return {"start": y * 12, "end": y * 12 + 11, "fmt": "year_only"}
    return None


def find_dates(text, as_of_m):
    """All ranges and lone dates on a line.

    Returns {"ranges": [range...], "singles": [date...]} where a range is
    dict(start, end, start_fmt, end_fmt, current, text, span, earliest_end) and a lone date is
    dict(start, end, fmt, text, span). Month integers throughout.
    """
    ranges, singles = [], []
    taken = []
    for m in RANGE_RE.finditer(text):
        a = parse_date(m.group("a"), as_of_m)
        if a is None:
            continue
        btxt = m.group("b")
        if PRESENT_RE.match(btxt.strip()):
            b, current = {"start": as_of_m, "end": as_of_m, "fmt": a["fmt"]}, True
        else:
            b, current = parse_date(btxt, as_of_m), False
            if b is None:
                continue
        ranges.append({"start": a["start"], "end": b["end"], "start_fmt": a["fmt"],
                       "end_fmt": None if current else b["fmt"], "current": current,
                       "earliest_end": b["start"], "text": m.group(0).strip(), "span": m.span()})
        taken.append(m.span())
    for m in DATE_RE.finditer(text):
        if any(s <= m.start() < e for s, e in taken):
            continue
        d = parse_date(m.group(0), as_of_m)
        if d is None:
            continue
        d.update({"text": m.group(0).strip(), "span": m.span()})
        singles.append(d)
    return {"ranges": ranges, "singles": singles}


def entry_format(rng=None, single=None):
    """Format label for an entry from its range or its lone date."""
    if rng is not None:
        fmts = [rng["start_fmt"]] + ([rng["end_fmt"]] if rng["end_fmt"] else [])
        if "two_digit_year" in fmts:
            return "two_digit_year"
        return rng["start_fmt"]
    if single is not None:
        return single["fmt"]
    return "missing"


def union_months(periods):
    """Merge [start, end] month intervals (inclusive). Returns a sorted list of merged intervals."""
    ps = sorted((a, b) for a, b in periods if a is not None and b is not None and a <= b)
    merged = []
    for a, b in ps:
        if merged and a <= merged[-1][1] + 1:
            if b > merged[-1][1]:
                merged[-1][1] = b
        else:
            merged.append([a, b])
    return merged


def total_months(merged):
    return sum(b - a + 1 for a, b in merged)
