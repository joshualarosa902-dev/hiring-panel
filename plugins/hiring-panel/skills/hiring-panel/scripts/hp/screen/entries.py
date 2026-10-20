"""Entries (a role, project or school with its dates and bullets), gaps and order (ATS spec 9).

Inside each entry-type section, consecutive non-bullet lines form a header group and the bullets after
it belong to the group's last entry. A group with several dated lines is split into several entries:
when the group starts with a dated line, each dated line opens an entry ("Company  Jun 2024 - Aug 2024"
then "Title"); otherwise each dated line closes one ("Title", "Company", "Jun 2024 - Aug 2024").
"""
import re

from .constants import CHRONO_SECTIONS, DATED_SECTIONS, ENTRY_SECTIONS, GAP_MONTHS
from .dates import EXPECTED_RE, entry_format, month_str, total_months, union_months
from .textutil import clip, words

SEGMENT_SECTIONS = ENTRY_SECTIONS + ("education",)
# When no Experience/Projects-type heading was recognized, dated groups in these blocks still count as
# entries (a heading the check could not read must not make a 5-job resume look empty).
FALLBACK_BLOCKS = ("contact", "other", "summary")
_SMALL_WORDS = {"and", "of", "the", "in", "for", "to", "a", "an", "at", "with", "on", "by", "or", "from", "&"}
DEGREE_WORD_RE = re.compile(
    r"(?<![\w])(?:B\.?\s?S\.?|B\.?\s?A\.?|B\.?Sc|BBA|BFA|M\.?\s?S\.?|M\.?\s?A\.?|MBA|MPH|Ph\.?\s?D|"
    r"A\.?A\.?S?|Associate(?:'s)? (?:of|in|degree)|Bachelor(?:'?s)?|Master(?:'?s)?|Doctorate|"
    r"(?i:major(?:ing)? in|minor in|degree|diploma|GED|coursework|GPA))(?![\w])")
SCHOOL_WORD_RE = re.compile(r"(?i)(?<![\w])(?:university|college|institute|school|academy|polytechnic|"
                            r"universidad|universit[eé]|hochschule|community college)(?![\w])")


def _title_like(rl):
    """Most words capitalized, as in a job title or organization line ("Research Assistant, Lab")."""
    ws = [w for w in re.findall(r"[^\W\d_][\w'’-]*", rl.btext) if w.lower() not in _SMALL_WORDS]
    if not ws:
        return True
    return sum(1 for w in ws if w[0].isupper()) >= 0.7 * len(ws)


# Everyday verbs that open bullets but are not in action_verbs.txt (weak or plain on purpose).
_BASIC_VERBS = set(("help helps helping assist assists assisting work works working handle handles handling "
                    "use uses using make makes making do does doing take takes taking keep keeps keeping "
                    "answer answers answering clean cleans cleaning sort sorts sorting stock stocks stocking "
                    "greet greets greeting cover covers covering run runs running open opens opening close "
                    "closes closing count counts counting pack packs packing file files filing ring rings "
                    "serve serves serving watch watches watching care cares caring drive drives driving deliver "
                    "delivers delivering check checks checking cook cooks cooking babysit babysits babysat "
                    "tutor tutors tutoring").split())


def verb_start(text, lex):
    """True when the text opens with a verb: a listed action verb, a weak opener ("Helped ..."), an
    everyday verb ("Help customers ...") or a past-tense looking word ("Stocked", "Worked")."""
    t = (text or "").strip()
    m = re.match(r"([A-Za-z][A-Za-z'’-]*)", t)
    if not m:
        return False
    w = m.group(1).lower()
    if w in lex.action_forms or w in _BASIC_VERBS:
        return True
    low = t.lower()
    for p in lex.weak_openers:
        if low.startswith(p) and (len(low) == len(p) or not low[len(p)].isalnum()):
            return True
    return len(w) >= 5 and w.endswith("ed")


def _bullet_shape(rl, lex, next_rl, after_dated):
    """Does an unmarked line read like a bullet of the entry above it? (The PDF lost the glyph.)"""
    if rl.heading is not None or rl.bullet or rl.dates["ranges"]:
        return False
    t = rl.btext.strip()
    if not t or t.endswith(":") or len(rl.words) < 2 or _title_like(rl):
        return False
    if verb_start(t, lex):
        return True
    if rl.dates["singles"] or not after_dated or len(rl.words) < 5:
        return False
    # A long line just above a dated line is that next entry's title line, not a bullet.
    if next_rl is not None and next_rl.dates["ranges"] and not next_rl.bullet:
        return False
    return True


def mark_implied_bullets(lines, lex, fallback):
    """Mark bullets whose glyph was lost (PDFs that draw bullets as shapes or CSS list markers) and join
    their wrapped tails. Works inside Experience/Projects/Leadership/Volunteer blocks, and in the
    FALLBACK_BLOCKS when `fallback` is True (no entry-type heading was recognized). Inside an entry,
    after its header lines, a line that starts with a verb, or a 5+ word line once the entry has a date,
    counts as a bullet; title-like lines never do. Returns the new line list."""
    from .sections import _continues  # imported here: sections imports this module's users
    eligible = set(ENTRY_SECTIONS) | (set(FALLBACK_BLOCKS) if fallback else set())
    out = []
    has_header = after_dated = in_bullets = False
    last_bullet = None
    cur_block = None
    for k, rl in enumerate(lines):
        if rl.heading is not None or rl.block != cur_block:
            cur_block = None if rl.heading is not None else rl.block
            has_header = after_dated = in_bullets = False
            last_bullet = None
            if rl.heading is not None:
                out.append(rl)
                continue
        if rl.where == "textbox" or rl.block not in eligible:
            out.append(rl)
            continue
        if rl.bullet:
            in_bullets = True
            last_bullet = rl
            out.append(rl)
            continue
        # A wrapped tail starts in lowercase or is a short end of sentence; a line that starts with a
        # digit may be the next entry ("2025 Hackathon"), so it is never joined here.
        tail_like = rl.text[:1].islower() or (rl.text.endswith(".") and len(rl.words) < 8
                                              and not rl.text[:1].isdigit())
        if last_bullet is not None and last_bullet.implied and tail_like and _continues(last_bullet, rl, lex):
            last_bullet.text = last_bullet.text + " " + rl.text
            last_bullet.btext = last_bullet.btext + " " + rl.text
            last_bullet.words = words(last_bullet.btext)
            continue
        nxt = lines[k + 1] if k + 1 < len(lines) else None
        strict = rl.block in FALLBACK_BLOCKS      # no entry heading: only after a dated header line
        if (has_header or in_bullets) and (after_dated or not strict) and \
                _bullet_shape(rl, lex, nxt, after_dated):
            rl.bullet = True
            rl.implied = True
            rl.btext = rl.text
            rl.is_sentence = False
            in_bullets = True
            last_bullet = rl
            out.append(rl)
            continue
        if in_bullets:
            has_header = after_dated = in_bullets = False
            last_bullet = None
        has_header = True
        if rl.dates["ranges"] or rl.dates["singles"]:
            after_dated = True
        out.append(rl)
    return out


class Entry(object):
    __slots__ = ("section", "header_lines", "bullets", "range", "single", "expected", "first_line")

    def __init__(self, section, header_lines):
        self.section = section
        self.header_lines = list(header_lines)
        self.bullets = []
        self.range = None
        self.single = None
        self.expected = False
        self.first_line = header_lines[0].idx if header_lines else None

    def finish(self):
        for rl in self.header_lines:
            if rl.dates["ranges"] and self.range is None:
                self.range = rl.dates["ranges"][0]
            if EXPECTED_RE.search(rl.text):
                self.expected = True
        if self.range is None:
            # the most precise lone date wins ("Team of 4 • Oct 2025" over "HackNebraska 2025")
            precise = [d for rl in self.header_lines for d in rl.dates["singles"] if d["fmt"] != "year_only"]
            for rl in self.header_lines:
                if rl.dates["singles"]:
                    self.single = rl.dates["singles"][-1]
                    break
            if precise:
                self.single = precise[0]
        return self

    @property
    def dated(self):
        return self.range is not None or self.single is not None

    def header_text(self):
        return clip(" | ".join(rl.text for rl in self.header_lines), 160)

    def period(self, as_of_m):
        """(start, end, is_current) month integers, ends capped at the as-of month for unions."""
        if self.range is not None:
            return self.range["start"], self.range["end"], self.range["current"]
        if self.single is not None:
            if self.section == "education":
                return None, self.single["end"], False
            return self.single["start"], self.single["end"], False
        return None, None, False


def _split_group(section, group):
    dated = [k for k, rl in enumerate(group) if rl.dates["ranges"] or rl.dates["singles"]]
    # A year inside a name ("HackNebraska 2025") does not open an entry of its own when another
    # header line carries a real date range or a month.
    precise = [k for k in dated if group[k].dates["ranges"] or
               any(d["fmt"] != "year_only" for d in group[k].dates["singles"])]
    if precise and len(precise) < len(dated):
        dated = precise
    if not dated:
        return [Entry(section, group).finish()]
    out = []
    if dated[0] == 0:
        bounds = dated + [len(group)]
        for a, b in zip(bounds, bounds[1:]):
            out.append(Entry(section, group[a:b]).finish())
    else:
        prev = 0
        for k in dated:
            out.append(Entry(section, group[prev:k + 1]).finish())
            prev = k + 1
        if prev < len(group):
            out[-1].header_lines.extend(group[prev:])
            out[-1].finish()
    return out


def segment_entries(lines, fallback=False, lex=None):
    """Split entry-type sections and Education into Entries, in document order.

    fallback=True (no entry-type heading was recognized): dated groups in FALLBACK_BLOCKS also become
    entries, labeled "education" when their header names a degree or school, else "other"."""
    entries = []
    by_section = []
    cur_sec, cur = None, []
    for rl in lines:
        if rl.where == "textbox":
            continue        # text-box content floats outside the reading order (PARSE-007 covers it)
        if rl.heading is not None:
            if cur:
                by_section.append((cur_sec, cur))
            cur_sec, cur = rl.block, []
            continue
        if rl.block != cur_sec:
            if cur:
                by_section.append((cur_sec, cur))
            cur_sec, cur = rl.block, []
        cur.append(rl)
    if cur:
        by_section.append((cur_sec, cur))
    for sec, sl in by_section:
        if sec not in SEGMENT_SECTIONS:
            if fallback and sec in FALLBACK_BLOCKS:
                entries.extend(_fallback_entries(sl))
            continue
        group, last = [], None
        for rl in sl:
            if rl.bullet or (rl.is_sentence and (group or last is not None)):
                if group:
                    made = _split_group(sec, group)
                    entries.extend(made)
                    last = made[-1]
                    group = []
                if last is None:
                    last = Entry(sec, []).finish()
                    entries.append(last)
                last.bullets.append(rl)
            else:
                if last is not None and last.bullets:
                    last = None
                group.append(rl)
        if group:
            entries.extend(_split_group(sec, group))
    if lex is not None:
        for e in entries:
            if e.section == "education" and _job_like(e, lex):
                e.section = "other"
    return entries


def _job_like(e, lex):
    """An "education" entry that is really a job under a heading the check could not read: a date range,
    no school or degree word in its header, and most bullets start with a verb."""
    if e.range is None or not e.bullets or not e.header_lines:
        return False
    head = " ".join(rl.text for rl in e.header_lines)
    if DEGREE_WORD_RE.search(head) or SCHOOL_WORD_RE.search(head):
        return False
    return sum(1 for b in e.bullets if verb_start(b.btext, lex)) * 2 > len(e.bullets)


def _fallback_entries(sl):
    """Dated entries from a block with no recognized entry heading (see segment_entries)."""
    tmp = []
    group, last = [], None
    for rl in sl:
        if rl.bullet:
            if group:
                made = _split_group("other", group)
                tmp.extend(made)
                last = made[-1]
                group = []
            if last is not None:
                last.bullets.append(rl)
        else:
            if last is not None and last.bullets:
                last = None
            group.append(rl)
    if group:
        tmp.extend(_split_group("other", group))
    out = []
    for e in tmp:
        if not e.dated or e.range is None and not e.bullets:
            continue
        head = " ".join(rl.text for rl in e.header_lines)
        if DEGREE_WORD_RE.search(head) or SCHOOL_WORD_RE.search(head):
            e.section = "education"
        out.append(e)
    return out


def entry_record(e, as_of_m):
    start, end, current = e.period(as_of_m)
    if e.range is not None:
        date_text = e.range["text"]
    elif e.single is not None:
        date_text = e.single["text"]
    else:
        date_text = None
    return {
        "section": e.section,
        "header": e.header_text() or "(no header line)",
        "date_text": date_text,
        "start": month_str(start),
        "end": month_str(min(end, as_of_m) if (current and end is not None) else end),
        "is_current": bool(current),
        "expected": bool(e.expected),
        "date_format": entry_format(e.range, e.single),
        "bullet_count": len(e.bullets),
        "line": e.first_line,
    }


def timeline(entries, as_of_m):
    """Gaps, months since last activity, total experience months and reverse-chronology checks."""
    cover = []
    exp_periods = []
    latest_end = None
    any_current = False
    first_start = None
    enrolled_open = False
    for e in entries:
        if e.section not in DATED_SECTIONS:
            continue
        start, end, current = e.period(as_of_m)
        if end is None:
            continue
        if current or (e.section == "education" and (e.expected or end >= as_of_m)):
            any_current = True
        if e.section == "education" and start is None:
            # A school listed with only a graduation date: if it is still ahead, the student is
            # enrolled now. Its start is unknown, so it only covers time up to today (see below).
            if end >= as_of_m:
                enrolled_open = True
            latest_end = end if latest_end is None else max(latest_end, end)
            continue
        if start is None:
            start = end
        first_start = start if first_start is None else min(first_start, start)
        cover.append((start, min(end, as_of_m)))
        latest_end = end if latest_end is None else max(latest_end, end)
        if e.section == "experience":
            exp_periods.append((start, min(end, as_of_m)))
    if enrolled_open and first_start is not None:
        cover.append((first_start, as_of_m))
    merged = union_months(cover)
    gaps = []
    for (a1, b1), (a2, b2) in zip(merged, merged[1:]):
        months = a2 - b1 - 1
        if months > GAP_MONTHS:
            gaps.append({"from": month_str(b1 + 1), "to": month_str(a2 - 1), "months": months})
    if latest_end is None:
        since = None
    elif any_current or latest_end >= as_of_m:
        since = 0
    else:
        since = as_of_m - latest_end
    exp_merged = union_months(exp_periods)
    total = total_months(exp_merged) if exp_merged else None
    # reverse-chronological order inside each section: current first, then end date descending
    inversions = []
    for sec in CHRONO_SECTIONS:
        dated = []
        for e in entries:
            if e.section != sec or not e.dated:
                continue
            start, end, current = e.period(as_of_m)
            end_key = as_of_m if current else (end if end is not None else -1)
            start_key = start if start is not None else end_key
            dated.append((start_key, end_key, e))
        # An inversion needs the later-listed entry to be more recent at BOTH ends; a current
        # part-time job listed under a newer internship is a normal order, not a mistake.
        for (s1, e1k, e1), (s2, e2k, e2) in zip(dated, dated[1:]):
            if s2 > s1 and e2k > e1k:
                inversions.append((e1, e2))
    return {"gaps": gaps, "months_since_last_activity": since, "total_months_experience": total,
            "inversions": inversions, "dated_count": sum(1 for e in entries if e.dated)}
