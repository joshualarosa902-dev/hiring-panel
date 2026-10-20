"""Load the screening dictionaries from hp/data (formats in ARCHITECTURE 6.4 and 6.5).

load_lexicon(data_dir=None) returns a Lexicon. Every file listed in REQUIRED_FILES must exist; a
missing or unreadable file raises LexiconError with a clear message. Entries with bad fields are
skipped (counted in Lexicon.warnings), never fatal. Results are cached per directory and file stamp.
"""
import json
import os
import re

from .tokens import FormIndex

REQUIRED_FILES = ("skills.json", "headings.json", "action_verbs.txt", "weak_openers.txt", "buzzwords.txt",
                  "stopwords_en.txt", "jd_stopwords.txt", "us_states.json", "countries.txt",
                  "locale_norms.json", "VERSION")
SKILL_KINDS = ("hard", "tool", "cert", "domain", "soft", "title")
JD_KINDS = ("required", "preferred", "responsibility", "boilerplate")

# Minimal built-in heading phrases. The data file is the main source; these only make sure the
# core names always work. Both lists are merged.
_RESUME_HEADINGS_FALLBACK = {
    "summary": ["summary", "professional summary", "profile", "objective", "career objective",
                "about me"],
    "experience": ["experience", "work experience", "professional experience", "relevant experience",
                   "employment", "employment history", "work history", "internships",
                   "internship experience"],
    "education": ["education", "academic background", "education and training"],
    "skills": ["skills", "technical skills", "skills and tools", "core skills", "key skills"],
    "projects": ["projects", "academic projects", "personal projects", "selected projects"],
    "certifications": ["certifications", "certificates", "licenses and certifications",
                       "certifications and licenses"],
    "leadership_activities": ["leadership", "activities", "leadership and activities",
                              "extracurricular activities", "campus involvement", "involvement"],
    "volunteer": ["volunteer", "volunteer experience", "volunteering", "community service"],
    "awards": ["awards", "honors", "honors and awards", "awards and honors", "achievements"],
    "publications": ["publications", "research publications"],
    "coursework": ["coursework", "relevant coursework"],
    "languages": ["languages"],
    "interests": ["interests", "hobbies", "hobbies and interests"],
    "references": ["references"],
}
_JD_HEADINGS_FALLBACK = {
    "required": ["requirements", "qualifications", "minimum qualifications", "basic qualifications",
                 "required qualifications", "must have", "must haves", "what you'll need",
                 "what you will need", "what we're looking for", "what we are looking for",
                 "who you are", "you have", "you bring", "skills and experience", "about you"],
    "preferred": ["preferred qualifications", "nice to have", "nice to haves", "bonus", "bonus points",
                  "pluses", "desired", "extra credit", "preferred"],
    "responsibility": ["responsibilities", "what you'll do", "what you will do", "the role",
                       "your impact", "day to day", "key duties", "in this role", "duties",
                       "about the role", "about the job", "about the position", "job summary",
                       "position summary", "role overview"],
    "boilerplate": ["about us", "who we are", "benefits", "perks", "compensation", "salary",
                    "pay range", "equal opportunity", "eeo", "accommodation", "privacy",
                    "our values", "why join", "culture", "why join us", "what we offer",
                    "about the company", "our mission"],
}
_STOPWORDS_FALLBACK = set(("a an and are as at be by for from has have he her his i in is it its me my "
                           "of on or our she so that the their them they this to was we were with you "
                           "your").split())

_CACHE = {}

# Programming-language names that are also letters or words (R, C, Go, Swift) count with local context
# too: "in R" / "using Go" on a line about data or code, "R (", or another language on the same line.
_LOCAL_PREFIX_RE = re.compile(r"(?i)(?:^|[\s(])(?:in|using|with|via|and)\s+$")
_TECH_WORDS_RE = re.compile(
    r"(?i)(?<![\w])(?:data|datasets?|surveys?|analy[sz]\w*|clean\w*|statistic\w*|regressions?|models?|"
    r"modeling|modelling|scripts?|scripting|code|coded|coding|programs?|programmed|programming|wrote|written|"
    r"built|develop\w*|implement\w*|apps?|software|packages?|librar\w*|functions?|algorithms?|"
    r"visuali[sz]\w*|plots?|plotted|charts?|simulat\w*|projects?|class|course\w*|homework|assignments?|"
    r"robots?|robotics|firmware|backend|server|api|apis|ios|iphone|mobile)(?![\w])")
_INITIAL_RE = re.compile(r"\.\s+[A-Z]")


class LexiconError(Exception):
    """A required data file is missing or unreadable."""


def default_data_dir():
    """hp/data next to this package."""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def norm_heading(s):
    """Lowercase, "&" -> "and", drop markdown and punctuation, collapse spaces."""
    s = (s or "").replace("’", "'").replace("‘", "'").casefold()
    s = s.replace("&", " and ")
    s = re.sub(r"[^\w' ]+", " ", s)
    s = s.replace("_", " ")
    s = re.sub(r"\s+", " ", s).strip(" '")
    return s


def _read_text(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return f.read()
    except (OSError, UnicodeDecodeError) as e:
        raise LexiconError("Hiring Panel data file can't be read: %s (%s). Reinstall the skill." % (path, e))


def _read_list(path):
    out = []
    for line in _read_text(path).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


def _read_json(path):
    try:
        return json.loads(_read_text(path))
    except ValueError as e:
        raise LexiconError("Hiring Panel data file is not valid JSON: %s (%s). Reinstall the skill."
                           % (path, e))


def _str_list(v, limit=200):
    if not isinstance(v, list):
        return []
    return [x.strip() for x in v[:limit] if isinstance(x, str) and x.strip()]


def _verb_forms(base, past=None):
    """Generate inflected forms of a verb by rule. Over-generation is harmless: the forms are only
    compared with real words. Returns (present_forms, past_forms)."""
    b = base.lower()
    present = {b}
    pasts = set()
    if past:
        pasts.update(p.strip().lower() for p in past.split("/") if p.strip())
    if re.search(r"(?:s|x|z|ch|sh)$", b):
        present.add(b + "es")
    elif re.search(r"[^aeiou]y$", b):
        present.add(b[:-1] + "ies")
    else:
        present.add(b + "s")
    if b.endswith("ie"):
        present.add(b[:-2] + "ying")
    elif b.endswith("e") and not b.endswith("ee"):
        present.add(b[:-1] + "ing")
    else:
        present.add(b + "ing")
    if not past:
        if b.endswith("e"):
            pasts.add(b + "d")
        elif re.search(r"[^aeiou]y$", b):
            pasts.add(b[:-1] + "ied")
        else:
            pasts.add(b + "ed")
    if re.search(r"[^aeiou][aeiou][bdgklmnprt]$", b) and len(b) <= 6:
        pasts.add(b + b[-1] + "ed")
        present.add(b + b[-1] + "ing")
    return present - pasts, pasts


class Lexicon(object):
    """All dictionaries, normalized and indexed. Treat as read-only."""

    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.warnings = []
        missing = [f for f in REQUIRED_FILES if not os.path.isfile(os.path.join(data_dir, f))]
        if missing:
            raise LexiconError("Hiring Panel data file missing: %s (in %s). Reinstall the skill."
                               % (", ".join(missing), data_dir))
        p = lambda name: os.path.join(data_dir, name)  # noqa: E731
        self.version = (_read_text(p("VERSION")).strip().splitlines() or ["unknown"])[0].strip() or "unknown"
        self._load_skills(_read_json(p("skills.json")))
        self._load_headings(_read_json(p("headings.json")))
        self._load_verbs(_read_list(p("action_verbs.txt")))
        self.weak_openers = sorted({w.lower() for w in _read_list(p("weak_openers.txt"))},
                                   key=lambda w: (-len(w), w))
        self.buzzwords = sorted({w.lower() for w in _read_list(p("buzzwords.txt"))},
                                key=lambda w: (-len(w), w))
        sw = {w.lower() for w in _read_list(p("stopwords_en.txt"))}
        self.stopwords_en = sw or set(_STOPWORDS_FALLBACK)
        self.jd_stopwords = {w.lower() for w in _read_list(p("jd_stopwords.txt"))}
        states = _read_json(p("us_states.json"))
        self.us_states = {}
        if isinstance(states, dict):
            for k, v in states.items():
                if isinstance(k, str) and isinstance(v, str):
                    self.us_states[k.strip().upper()] = v.strip()
        else:
            self.warnings.append("us_states.json is not an object; ignored")
        self.us_state_names = {v.casefold() for v in self.us_states.values()}
        self.countries = {c.casefold() for c in _read_list(p("countries.txt"))}
        norms = _read_json(p("locale_norms.json"))
        self.locale_norms = norms if isinstance(norms, dict) else {}
        self._buzz_re = None
        if self.buzzwords:
            self._buzz_re = re.compile(r"(?i)(?<![\w])(?:%s)(?![\w])"
                                       % "|".join(re.escape(b) for b in self.buzzwords))

    # ---------------------------------------------------------------- skills
    def _load_skills(self, data):
        entries = data.get("entries") if isinstance(data, dict) else data
        if not isinstance(entries, list):
            raise LexiconError("skills.json has no entries list (in %s). Reinstall the skill." % self.data_dir)
        self.entries = []
        self.by_id = {}
        by_canon = {}
        skipped = 0
        for raw in entries:
            if not isinstance(raw, dict) or not isinstance(raw.get("canonical"), str) or not raw["canonical"].strip():
                skipped += 1
                continue
            canon = raw["canonical"].strip()
            eid = raw.get("id") if isinstance(raw.get("id"), str) and raw.get("id").strip() else canon.casefold()
            eid = eid.strip()
            if eid in self.by_id:
                skipped += 1
                continue
            kind = raw.get("kind") if raw.get("kind") in SKILL_KINDS else "hard"
            e = {
                "id": eid, "canonical": canon, "kind": kind,
                "aliases": _str_list(raw.get("aliases")), "acronyms": _str_list(raw.get("acronyms")),
                "case_sensitive": bool(raw.get("case_sensitive")), "ambiguous": bool(raw.get("ambiguous")),
                "context": [c.casefold() for c in _str_list(raw.get("context"))],
                "implies_raw": _str_list(raw.get("implies")),
            }
            self.entries.append(e)
            self.by_id[eid] = e
            by_canon.setdefault(canon.casefold(), eid)
        if skipped:
            self.warnings.append("skills.json: %d entries skipped (missing canonical or duplicate id)" % skipped)
        # implies: ids or canonicals, resolved and closed transitively (depth 3, cycle safe)
        direct = {}
        for e in self.entries:
            tgt = []
            for x in e["implies_raw"]:
                t = x if x in self.by_id else by_canon.get(x.casefold())
                if t and t != e["id"] and t not in tgt:
                    tgt.append(t)
            direct[e["id"]] = tgt
        self.implied_by = {}
        for e in self.entries:
            seen = []
            frontier = list(direct[e["id"]])
            depth = 0
            while frontier and depth < 3:
                nxt = []
                for t in frontier:
                    if t not in seen and t != e["id"]:
                        seen.append(t)
                        nxt.extend(direct.get(t, []))
                frontier = nxt
                depth += 1
            for t in seen:
                self.implied_by.setdefault(t, []).append(e["id"])
        self.context_re = {}
        for e in self.entries:
            if e["ambiguous"] and e["context"]:
                self.context_re[e["id"]] = re.compile(
                    r"(?i)(?<![\w])(?:%s)(?![\w+#])" % "|".join(re.escape(c) for c in
                                                                sorted(set(e["context"]), key=len, reverse=True)))
        # programming languages: entries that imply computer programming (ambiguous or not)
        self.language_ids = set(e["id"] for e in self.entries if "computer-programming" in direct.get(e["id"], []))
        self.index = FormIndex()
        for e in self.entries:
            for form, fk in self.entry_forms(e):
                self.index.add(form, e["id"], fk, case_sensitive=self.form_case_sensitive(e, form, fk),
                               allow_stem=(fk != "acronym" and not e["case_sensitive"]),
                               plural_acronym=(fk == "acronym"))

    def ambiguous_ok(self, eid, text, start, end, scope_text="", other_language=False):
        """Does an ambiguous entry's match at text[start:end] have context? A context word on the line
        (or in `scope_text`, the rest of a list section) counts. Programming languages also count after
        "in"/"using"/"with" on a line about data or code, before "(", or next to another language on
        the line (`other_language`). A one-letter match that is an initial ("R. Smith") never counts."""
        rx = self.context_re.get(eid)
        if rx is None:
            return True
        if end - start == 1 and _INITIAL_RE.match(text[end:end + 3]):
            return False
        if rx.search(text) or (scope_text and rx.search(scope_text)):
            return True
        if eid not in self.language_ids:
            return False
        if other_language:
            return True
        if re.match(r"\s*\(", text[end:end + 3]):
            return True
        return bool(_LOCAL_PREFIX_RE.search(text[max(0, start - 12):start]) and _TECH_WORDS_RE.search(text))

    def entry_forms(self, e):
        """(form, form_kind) pairs for an entry: canonical, aliases, acronyms; duplicates removed."""
        out = []
        seen = set()
        for form, fk in [(e["canonical"], "canonical")] + [(a, "alias") for a in e["aliases"]] + \
                [(a, "acronym") for a in e["acronyms"]]:
            k = (form.casefold(), fk == "acronym")
            if k in seen:
                continue
            seen.add(k)
            out.append((form, fk))
        return out

    def form_case_sensitive(self, e, form, fk):
        """Entry flag, or short all-caps forms (acronyms of 3 letters or fewer, and caps forms that
        are also English words like "IT" or "OR")."""
        if e["case_sensitive"]:
            return True
        letters = re.sub(r"[^A-Za-z]", "", form)
        if fk == "acronym" and len(letters) <= 3:
            return True
        if letters and letters.isupper() and len(letters) <= 3 and form.casefold() in _STOPWORDS_FALLBACK | {
                "it", "or", "us", "am", "pm", "as", "ed", "pr", "ui", "go", "do", "me", "hr", "ai"}:
            return True
        return False

    # ---------------------------------------------------------------- headings
    def _load_headings(self, data):
        if not isinstance(data, dict):
            data = {}
        resume = data.get("resume") if isinstance(data.get("resume"), dict) else {}
        jd = data.get("jd") if isinstance(data.get("jd"), dict) else {}
        if not resume:
            self.warnings.append("headings.json has no resume headings; using built-in names")
        if not jd:
            self.warnings.append("headings.json has no jd headings; using built-in names")
        self.resume_headings = {}   # normalized synonym -> section
        for src in (resume, _RESUME_HEADINGS_FALLBACK):
            for section in sorted(src):
                syns = src[section]
                sec = section if section in ("contact", "summary", "experience", "education", "skills", "projects",
                                             "certifications", "leadership_activities", "volunteer",
                                             "awards", "publications", "coursework", "languages",
                                             "interests", "references", "other") else None
                if sec is None:
                    continue
                for syn in _str_list(syns, 500):
                    k = norm_heading(syn)
                    if k and k not in self.resume_headings:
                        self.resume_headings[k] = sec
        self.core_words = {}        # extra core word -> section (headings.json "resume_core_words")
        cw = data.get("resume_core_words")
        if isinstance(cw, dict):
            for w, sec in sorted(cw.items()):
                if isinstance(w, str) and isinstance(sec, str) and sec in self.resume_headings.values():
                    self.core_words[norm_heading(w)] = sec
        self.jd_headings = []       # (normalized phrase, kind), longest first
        seen = set()
        for src in (jd, _JD_HEADINGS_FALLBACK):
            for kind in JD_KINDS:
                for ph in _str_list(src.get(kind), 500):
                    k = norm_heading(ph)
                    if k and k not in seen:
                        seen.add(k)
                        self.jd_headings.append((k, kind))
        self.jd_headings.sort(key=lambda x: (-len(x[0]), x[0]))
        self.jd_heading_exact = dict(self.jd_headings)

    # ---------------------------------------------------------------- verbs
    def _load_verbs(self, lines):
        self.action_forms = {}     # any form -> base
        self.present_forms = set()
        self.past_forms = set()
        for line in lines:
            base, _, past = line.partition("|")
            base = base.strip().lower()
            if not base or not re.match(r"^[a-z][a-z-]*$", base):
                continue
            pres, pasts = _verb_forms(base, past.strip() or None)
            for f in pres | pasts:
                self.action_forms.setdefault(f, base)
            self.present_forms |= pres
            self.past_forms |= pasts
        self.present_forms -= self.past_forms

    # ---------------------------------------------------------------- helpers
    def norms_for(self, locale):
        """locale_norms entry for a locale, falling back to its language, then "default"."""
        n = self.locale_norms
        if locale in n and isinstance(n[locale], dict):
            return n[locale]
        lang = (locale or "").split("-")[0]
        for k in sorted(n):
            if k.split("-")[0] == lang and isinstance(n[k], dict):
                return n[k]
        d = n.get("default")
        return d if isinstance(d, dict) else {}

    def buzzwords_in(self, text):
        if not self._buzz_re or not text:
            return []
        return [m.group(0) for m in self._buzz_re.finditer(text)]


def _stamp(data_dir):
    out = []
    for f in REQUIRED_FILES:
        try:
            st = os.stat(os.path.join(data_dir, f))
            out.append((f, st.st_mtime_ns, st.st_size))
        except OSError:
            out.append((f, None, None))
    return tuple(out)


def load_lexicon(data_dir=None):
    """Load (and cache) the dictionaries from data_dir (default: hp/data). Raises LexiconError when a
    required file is missing or unreadable."""
    d = os.path.abspath(data_dir or default_data_dir())
    if not os.path.isdir(d):
        raise LexiconError("Hiring Panel data folder missing: %s. Reinstall the skill." % d)
    stamp = _stamp(d)
    hit = _CACHE.get(d)
    if hit and hit[0] == stamp:
        return hit[1]
    lex = Lexicon(d)
    _CACHE[d] = (stamp, lex)
    return lex
