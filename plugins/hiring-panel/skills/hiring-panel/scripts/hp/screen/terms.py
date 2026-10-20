"""Job-posting term extraction (ATS spec 11): the union of five sources, deduplicated by canonical and
ordered by first appearance in the posting.

(a) lexicon: skills.json entries (longest match wins, no overlaps)
(b) acronym_definition: "Search Engine Optimization (SEO)" where the letters are the initials
(c) tech_token: C++, C#, .NET, Node.js, CamelCase, 2-6 capital letters (kind unknown)
(d) ngram: 1-3 word phrases from required/preferred lines (at most 20, low confidence)
(e) llm_verified: Claude's terms, accepted only when the quote is in the posting and holds the term
Boilerplate (about us, benefits, EEO) never yields terms.
"""
import re

from ..util import norm_for_match
from .constants import (IMPORTANCE_RANK, MAX_LLM_TERMS, MAX_NGRAM_TERMS, TERM_BASE_WEIGHT,
                        TERM_KIND_FACTOR)
from .tokens import FormIndex, stem, tokenize
from .textutil import clip

# Word lengths are bounded so a long run of letters can't make the search slow.
ACRDEF_RE = re.compile(r"((?:[A-Za-z][a-z]{1,30}|[A-Z]{2,12})(?:[ \t-]{1,3}(?:[A-Za-z][a-z]{1,30}|of|and|&|for|the|to|in|on))"
                       r"{1,7})\s{0,3}\(([A-Z][A-Za-z0-9&/]{1,9})\)")
_SMALL = {"of", "and", "&", "for", "the", "to", "in", "on"}
TECH_RES = (
    re.compile(r"(?<![\w+#.])[A-Za-z]{1,2}(?:\+\+|#)(?![\w+#])"),                  # C++, C#, F#
    re.compile(r"(?<![\w.])[A-Za-z][A-Za-z0-9]*\.(?:js|JS)\b"),                       # Node.js
    re.compile(r"(?<![\w])(?:ASP)?\.NET\b"),                                          # .NET
    re.compile(r"(?<![\w.])(?:[A-Z][a-z]+(?:[A-Z][a-z0-9]*)+|[a-z]{1,4}[A-Z][A-Za-z0-9]+)(?![\w])"),  # HubSpot
    re.compile(r"(?<![\w.&/-])[A-Z][A-Z0-9]{1,5}(?:s)?(?![\w&])"),                     # SQL, ETL, KPIs
)
# Capitalized tokens that are not skills (locations, time zones, degrees, generic job-ad words).
TECH_EXCLUDE = set((
    "us usa u.s eeo llc inc ltd pto faq ada ok id tbd asap fyi n/a am pm est edt pst pdt cst cdt mst mdt "
    "et pt ct mt utc gmt hq ceo cfo coo cto cmo cio vp svp evp avp hr nyc la sf dc uk eu emea apac latam "
    "gpa bs ba ms ma mba phd bsc msc bba beng meng jd md rn dds pharmd edd psyd aa as aas "
    "w2 w-2 1099 k12 k-12 stem dei esg qa fte ote rsu ipo b2b b2c "
    "note must plus new you your our who what why how about job role team work pay and the for with "
    "all any not are we us it is to of in on at or by be an as do if so up no ii iii iv "
    "jan feb mar apr may jun jul aug sep sept oct nov dec mon tue wed thu fri sat sun "
    "linkedin glassdoor indeed handshake").split())
_DEGREE_TOKENS = {"phd", "mba", "bsc", "msc", "bba"}


class Term(object):
    """A job-posting term while it is being built."""
    __slots__ = ("key", "source", "kind", "canonical", "entry_id", "forms", "occ", "llm_importance",
                 "llm_quote", "confidence", "display", "llm_pos", "llm_term", "group", "members")

    def __init__(self, key, source, kind, canonical, entry_id=None, forms=None, confidence="high"):
        self.key = key
        self.source = source
        self.kind = kind
        self.canonical = canonical
        self.entry_id = entry_id
        self.forms = list(forms or [])      # [(form, form_kind)]
        self.occ = []                       # [dict(line, start, end, surface, importance)]
        self.llm_importance = None
        self.llm_quote = None
        self.confidence = confidence
        self.display = None
        self.llm_pos = None
        self.llm_term = None                # Claude's own wording of the term (verified to be in the posting)
        self.group = None                   # "any_of" or "degree_field" for a group of alternatives
        self.members = None                 # group only: [[member key, [posting surfaces]]]


# ---------------------------------------------------------------- alternatives ("Python or R")
# One requirement often names alternatives: "Python or R", "Tableau or Power BI", "BLS/CPR",
# "statistics, economics or a related field". Such a run of terms inside one clause becomes ONE group
# term that any member satisfies, so coverage counts the requirement once. A comma list counts as
# alternatives only when it ends in "or" ("A, B or C"); "A, B and C" stays three terms. Fields listed
# after "degree in" / "major in" form a degree-field group that is matched against Education only.
_OR_GAP_RE = re.compile(r"(?i)^\s*,?\s*(?:or|and/or)\s+(?:an?\s+|the\s+)?$")
_SLASH_GAP_RE = re.compile(r"^\s*/\s*$")
_COMMA_GAP_RE = re.compile(r"^\s*,\s*$")
# "bachelor's degree in", "B.S. in", "degree (BS/BA) in", "major in", "Bachelor of Science in";
# only degree words may stand between the cue and "in", so "degree of autonomy in X" is not a cue.
_DEGREE_FILLER = (r"(?:\s*(?:\([^()]{1,15}\)|/|degrees?|programs?|studies|or|equivalent|of|science|arts|fine|"
                  r"business|administration|engineering|B\.?\s?S\.?|B\.?\s?A\.?))*")
_CUE_IN_RE = re.compile(r"(?i)(?<![\w])(?:degrees?|majors?|majoring|bachelor(?:'?s)?|master(?:'?s)?|"
                        r"associate(?:'?s)?|B\.\s?S\.?|B\.\s?A\.?|BS|BA|MBA|diploma)(?![\w])"
                        + _DEGREE_FILLER + r"\s+in\s+")
_CUE_OF_RE = re.compile(r"(?i)(?<![\w])(?:bachelor|master|associate|doctor)(?:'?s)?\s+of\s+")
_DEGREE_END_RE = re.compile(
    r"(?i)[.;:()]|,?\s+or\s+(?:an?\s+|any\s+|other\s+)?(?:related|similar|equivalent|relevant|comparable|other)\b|"
    r"\s+(?:with|who|that|from|by|plus|preferred|required|is|are|including|and\s+(?:at\s+least|\d|experience|"
    r"an?\s|the\s|have|has|must|strong|excellent|proven))\b")


def _connector(gap):
    if _OR_GAP_RE.match(gap):
        return "or"
    if _SLASH_GAP_RE.match(gap):
        return "slash"
    if _COMMA_GAP_RE.match(gap):
        return "comma"
    return None


def degree_field_spans(text):
    """[(start, end)] of field lists after a degree cue ("bachelor's degree in X, Y or a related field")."""
    out = []
    for rx in (_CUE_IN_RE, _CUE_OF_RE):
        for m in rx.finditer(text):
            a = m.end()
            if any(s <= a < e for s, e in out):
                continue
            if rx is _CUE_OF_RE and re.match(r"(?i)(?:science|arts|business administration|engineering|fine arts)"
                                             r"\s+in\b", text[a:]):
                continue          # "Bachelor of Science in X": the "in" cue covers it
            e = _DEGREE_END_RE.search(text, a)
            b = e.start() if e else len(text)
            if b > a:
                out.append((a, b))
    return out


def _clause_index(ln, pos):
    for k, (a, b, _imp) in enumerate(ln["clauses"]):
        if a <= pos < max(b, a + 1):
            return k
    return -1


def _find_groups(lines, terms, order):
    """[(group kind, line index, [(start, end, key, occ)])] from the occurrences on each line."""
    by_line = {}
    for key in order:
        for o in terms[key].occ:
            by_line.setdefault(o["line"], []).append((o["start"], o["end"], key, o))
    found = []
    for li in sorted(by_line):
        items = sorted(by_line[li], key=lambda x: (x[0], x[1]))
        ln = lines[li]
        text = ln["scan"]
        spans = degree_field_spans(text)
        rest, deg = [], {}
        for it in items:
            sp = next((k for k, (a, b) in enumerate(spans) if a <= it[0] and it[1] <= b), None)
            if sp is None or terms[it[2]].kind in ("cert", "tool", "title"):    # "or CPA eligibility"
                rest.append(it)
            else:
                deg.setdefault(sp, []).append(it)
        for sp in sorted(deg):
            found.append(("degree_field", li, deg[sp]))
        i = 0
        while i < len(rest):
            j, seen_or = i, False
            while j + 1 < len(rest):
                a, b = rest[j], rest[j + 1]
                if a[2] == b[2] or b[0] < a[1] or _clause_index(ln, a[0]) != _clause_index(ln, b[0]):
                    break
                c = _connector(text[a[1]:b[0]])
                if c in ("or", "slash"):
                    seen_or = True
                elif c != "comma" or seen_or:
                    break
                j += 1
            if seen_or and j > i:
                found.append(("any_of", li, rest[i:j + 1]))
                i = j + 1
            else:
                i += 1
    return found


def _kind_rank(kind):
    return TERM_KIND_FACTOR.get(kind, 0.6)


def build_groups(lines, terms, order):
    """Move grouped occurrences from their member terms to group terms (added to `terms`/`order`).
    Group.members holds [member key, posting surfaces, form kinds]. Returns {member key: group key}
    for members whose occurrence went into a group."""
    member_of = {}
    for gkind, li, members in _find_groups(lines, terms, order):
        uk = []
        for _s, _e, k, _o in members:
            if k not in uk:
                uk.append(k)
        if gkind == "any_of" and len(uk) < 2:
            continue
        gkey = ("deg:" if gkind == "degree_field" else "grp:") + "|".join(uk)
        text = lines[li]["scan"]
        a, b = members[0][0], max(m[1] for m in members)
        imp = max((m[3]["importance"] for m in members), key=lambda x: IMPORTANCE_RANK[x])
        g = terms.get(gkey)
        if g is None:
            if gkind == "degree_field":
                kind = "domain"
            else:
                kind = max((terms[k].kind for k in uk), key=_kind_rank)
            conf = "high" if any(terms[k].confidence == "high" for k in uk) else (
                "medium" if any(terms[k].confidence == "medium" for k in uk) else "low")
            g = Term(gkey, terms[uk[0]].source, kind, " or ".join(terms[k].canonical for k in uk), None, [], conf)
            g.group = gkind
            g.members = [[k, [], []] for k in uk]
            terms[gkey] = g
            order.append(gkey)
        g.occ.append({"line": li, "start": a, "end": b, "surface": text[a:b], "importance": imp,
                      "form_kind": "canonical"})
        for _s, _e, k, o in members:
            terms[k].occ = [x for x in terms[k].occ if x is not o]
            slot = next((m for m in g.members if m[0] == k), None)
            if slot is None:
                slot = [k, [], []]
                g.members.append(slot)
            if o["surface"] not in slot[1]:
                slot[1].append(o["surface"])
            slot[2].append(o.get("form_kind"))
            member_of.setdefault(k, gkey)
    return member_of


def _trim_to_form(surface, form):
    """The part of `surface` spelled like `form` ("SQL queries" -> "SQL"), or None."""
    st, ft = tokenize(surface), tokenize(form)
    n = len(ft)
    if not n or n >= len(st):
        return None
    want = [t.cf for t in ft]
    for i in range(len(st) - n + 1):
        if [t.cf for t in st[i:i + n]] == want:
            return surface[st[i].start:st[i + n - 1].end]
    return None


def _line_scan_from(ln):
    """Offset where term scanning starts on a posting line (None = skip the line)."""
    if ln["kind"] == "boilerplate" or ln["eeo"]:
        return None
    if ln["heading"]:
        t = ln["scan"]
        if ln["heading_text"] and ":" in t:
            idx = t.find(":")
            if t[idx + 1:].strip():
                return idx + 1
        return None
    return 0


BLOCK_TO_IMPORTANCE = {"required": "required", "preferred": "preferred", "responsibility": "responsibility",
                       "unspecified": "unspecified"}


def importance_at(ln, pos):
    for a, b, imp in ln["clauses"]:
        if a <= pos < max(b, a + 1) and imp:
            return imp
    return BLOCK_TO_IMPORTANCE.get(ln["kind"], "unspecified")


def _full_cover(lex, text):
    """Dictionary entry id when `text` as a whole is one dictionary form, else None."""
    toks = tokenize(text)
    if not toks:
        return None
    for hit in lex.index.scan(toks, longest_only=True):
        if hit[0] == 0 and hit[1] == len(toks):
            return hit[2]
    return None


def find_acronym_defs(text):
    """[(phrase, acronym, start, end)] where the acronym's capital letters are the phrase's initials
    (small words like "of" skipped), taken from the end of the matched words."""
    out = []
    if not text or "(" not in text:
        return out
    for m in ACRDEF_RE.finditer(text):
        words = re.split(r"[ \t-]+", m.group(1).strip())
        acr = m.group(2)
        letters = re.sub(r"[^A-Z]", "", acr)
        if len(letters) < 2:
            continue
        for j in range(len(words)):
            sub = words[j:]
            if sub[0].lower() in _SMALL:
                continue
            initials = "".join(w[0].upper() for w in sub if w.lower() not in _SMALL)
            if initials == letters:
                out.append((" ".join(sub), acr, m.start(1), m.end()))
                break
    return out


def _excluded_tech(tok, lex):
    """Capitalized tokens that are places, degrees, stopwords or generic job-ad words."""
    base = tok[:-1] if (tok.endswith("s") and tok[:-1].isupper() and len(tok) > 2) else tok
    low = base.lower()
    if low in TECH_EXCLUDE or low in lex.stopwords_en or low in lex.jd_stopwords:
        return True
    if len(base) == 2 and base.upper() in lex.us_states:
        return True
    return low in lex.countries or low in _DEGREE_TOKENS


def _covered(spans, a, b):
    return any(not (b <= s or a >= e) for s, e in spans)


def scan_posting(index, toks):
    """Greedy longest-first dictionary scan of a posting line, except that a stem-only (inflection)
    match gives way to an exact match that starts inside it and reaches further: "record vital signs"
    is "record" + "vital signs", never "record vital" (a stem match of "record vitals").
    Returns [(i, n, key, form_kind, form_joined, via)] without overlaps."""
    every = index.scan(toks, longest_only=False)
    if not every:
        return []
    starts = {}
    for h in every:
        starts.setdefault(h[0], []).append(h)
    exact_reach = {}
    for i, n, _k, _fk, _fj, via in every:
        if via == "exact":
            exact_reach[i] = max(exact_reach.get(i, 0), i + n)
    out = []
    i, L = 0, len(toks)
    while i < L:
        cands = sorted(starts.get(i, ()), key=lambda h: (-h[1], h[5] != "exact"))
        chosen = None
        for h in cands:
            n = h[1]
            if h[5] != "exact" and any(exact_reach.get(j, 0) > i + n for j in range(i + 1, i + n)):
                continue
            chosen = h
            break
        if chosen is None:
            i += 1
            continue
        n = chosen[1]
        out.extend(h for h in cands if h[1] == n)
        i += n
    return out


# Words that never make a phrase term on their own: generic verbs, adverbs and adjectives of job ads
# (merged with jd_stopwords.txt).
_PHRASE_STOP = set(("currently pursuing pursue enrolled enrollment seeking looking comfortable willing eager "
                    "ability abilities able demonstrated proven solid basic advanced working hands hands-on "
                    "excellent outstanding exceptional strong good great effective effectively highly "
                    "self motivated self-motivated motivated driven passion passionate desire interest "
                    "interested minimum maximum least must should will would could may might need needs "
                    "required preferred plus bonus ideal ideally including include such like etc also "
                    "new current previous prior related similar equivalent relevant other various "
                    "applicable appropriate successful successfully candidate candidates applicant "
                    "position role opportunity team member members individual someone person people "
                    "years year months month week weeks hours hour day days time full part").split())


_ADJ_END_RE = re.compile(r"(?:al|ive|ous|ful|ible|able)$")
_NOUNS_LIKE_ADJ = set(("professional proposal approval rental manual portal journal capital hospital signal "
                       "material potential individual terminal arrival referral renewal tutorial editorial "
                       "principal festival survival removal disposal retrieval rehearsal interval criminal "
                       "initiative objective executive representative alternative incentive narrative "
                       "perspective directive collective archive detective native relative motive adhesive "
                       "explosive deliverable receivable payable variable table cable vegetable timetable "
                       "turntable constable").split())


def _adjective_end(word):
    w = word.lower().strip("'’-")
    return len(w) > 4 and bool(_ADJ_END_RE.search(w)) and w not in _NOUNS_LIKE_ADJ


def _is_knockout_line(text):
    from .knockouts import PATTERNS  # imported here: knockouts imports this module
    return any(rx.search(text) for _typ, rx in PATTERNS)


def _phrase_candidates(lines, covered, lex):
    stop = lex.stopwords_en | lex.jd_stopwords | _PHRASE_STOP
    places = lex.countries | lex.us_state_names
    cands = {}
    order = 0
    for li, ln in enumerate(lines):
        start_at = _line_scan_from(ln)
        if start_at is None or _is_knockout_line(ln["scan"]):
            continue
        text = ln["scan"]
        short_line = len(text.split()) <= 15     # bullet-like; long prose lines only feed repeats
        for a, b, imp in ln["clauses"]:
            eff = imp or BLOCK_TO_IMPORTANCE.get(ln["kind"])
            if eff not in ("required", "preferred"):
                continue
            a = max(a, start_at)
            chunk = []
            prev_end = None
            chunks = []
            for m in re.finditer(r"[A-Za-z0-9][A-Za-z0-9'’+#.-]*[A-Za-z0-9+#]|[A-Za-z]", text[a:b]):
                ws, we = a + m.start(), a + m.end()
                w = m.group(0)
                gap = text[prev_end:ws] if prev_end is not None else ""
                # tech-style words (SQL, GraphQL, C++) are terms of their own, never part of a phrase
                techy = any(c.isdigit() for c in w) or (sum(1 for c in w if c.isupper()) >= 2) or \
                    not w.replace("-", "").replace("'", "").replace("’", "").isalpha()
                breaks = (w.lower() in stop or len(w) < 3 or techy or _covered(covered.get(li, ()), ws, we)
                          or w.lower().strip("'’-") in stop)
                if chunk and (breaks or not re.match(r"^[ \t-]*$", gap)):
                    chunks.append(chunk)
                    chunk = []
                if not breaks:
                    chunk.append((w, ws, we))
                prev_end = we
            if chunk:
                chunks.append(chunk)
            # drop leading/trailing verbs and adverbs ("Upload courses" -> "courses")
            trimmed = []
            for ch in chunks:
                while ch and (ch[0][0].lower() in lex.action_forms or ch[0][0].lower().endswith("ly")):
                    ch = ch[1:]
                while ch and (ch[-1][0].lower() in lex.action_forms or ch[-1][0].lower().endswith("ly")):
                    ch = ch[:-1]
                if ch:
                    trimmed.append(ch)
            # A phrase must end on a noun: drop chunks that end on an adjective ("record vital",
            # "highly analytical"); only whole chunks and their tails are kept below.
            chunks = [ch for ch in trimmed if not _adjective_end(ch[-1][0])]
            first_word_at = None
            m0 = re.search(r"[A-Za-z]", text[a:b])
            if m0:
                first_word_at = a + m0.start()
            for ch in chunks:
                L = len(ch)
                for n in range(1, min(3, L) + 1):
                    for s in (L - n,):            # tails only: the head noun of a phrase comes last
                        seg = ch[s:s + n]
                        key = tuple(stem(w.lower())[0] for w, _, _ in seg)
                        c = cands.get(key)
                        if c is None:
                            order += 1
                            c = {"n": n, "count": 0, "req_chunk": False, "first": (li, seg[0][1]),
                                 "surface": text[seg[0][1]:seg[-1][2]], "order": order, "lines": set(),
                                 "proper": False}
                            cands[key] = c
                        if n == 1 and seg[0][0][0].isupper() and seg[0][1] != first_word_at:
                            c["proper"] = True     # capitalized mid-sentence: likely a product name
                        if li not in c["lines"]:
                            c["lines"].add(li)
                            c["count"] += 1
                if 2 <= L <= 3 and eff == "required" and short_line:
                    key = tuple(stem(w.lower())[0] for w, _, _ in ch)
                    cands[key]["req_chunk"] = True
    kept = []
    for key, c in sorted(cands.items(), key=lambda kv: (-kv[1]["n"], kv[1]["order"])):
        ok = c["req_chunk"] or (c["count"] >= 2 and (c["n"] >= 2 or (len(key[0]) >= 4 and c["proper"])))
        if not ok or c["surface"].casefold() in places:
            continue
        inside = [k for k, kc in kept if len(k) > len(key) and any(k[i:i + len(key)] == key
                                                                    for i in range(len(k) - len(key) + 1))]
        if inside and all(cands[k]["count"] >= c["count"] for k in inside):
            continue
        kept.append((key, c))
    kept.sort(key=lambda kv: kv[1]["first"])
    return kept[:MAX_NGRAM_TERMS]


def verify_llm_terms(terms, jd_text, parsed, warnings):
    """Validate Claude-extracted terms. Returns (accepted, stats). Rejections are logged as warnings."""
    stats = {"provided": 0, "accepted": 0, "rejected": 0}
    if terms is None:
        return [], stats
    if not isinstance(terms, list):
        warnings.append("terms: ignored because it is not a list")
        return [], stats
    stats["provided"] = len(terms)
    if len(terms) > MAX_LLM_TERMS:
        warnings.append("terms: only the first %d of %d were checked" % (MAX_LLM_TERMS, len(terms)))
    jd_norm = norm_for_match(jd_text)
    line_norms = [(norm_for_match(ln["scan"]), ln) for ln in parsed["lines"]]
    accepted = []
    for item in terms[:MAX_LLM_TERMS]:
        def reject(why, label="?"):
            stats["rejected"] += 1
            warnings.append("terms: rejected %s: %s" % (label, why))
        if not isinstance(item, dict):
            reject("not an object")
            continue
        term = item.get("term")
        if not isinstance(term, str) or not term.strip() or len(term.strip()) > 80:
            reject("missing or overlong term")
            continue
        term = re.sub(r"\s+", " ", term.strip())
        label = '"%s"' % clip(term, 40)
        quote = item.get("jd_quote")
        if not isinstance(quote, str) or not quote.strip() or len(quote) > 600:
            reject("missing or overlong jd_quote", label)
            continue
        imp = item.get("importance", "unspecified")
        if imp not in ("required", "preferred", "unspecified"):
            reject("importance must be required, preferred or unspecified", label)
            continue
        aliases = item.get("aliases") or []
        if not isinstance(aliases, list):
            aliases = []
        aliases = [re.sub(r"\s+", " ", a.strip()) for a in aliases[:10]
                   if isinstance(a, str) and a.strip() and len(a.strip()) <= 80]
        qn, tn = norm_for_match(quote), norm_for_match(term)
        if not qn or qn not in jd_norm:
            reject("quote not found in the job description", label)
            continue
        if not re.search(r"(?<![\w])%s(?![\w])" % re.escape(tn), qn):
            reject("quote does not contain the term", label)
            continue
        hosts = [ln for n, ln in line_norms if n and (n in qn or qn in n)]
        if hosts and all(ln["kind"] == "boilerplate" or ln["eeo"] for ln in hosts):
            reject("quote is from company, benefits or equal-opportunity text", label)
            continue
        stats["accepted"] += 1
        pos = None
        for i, (n, ln) in enumerate(line_norms):
            if n and (n in qn or qn in n) and re.search(r"(?<![\w])%s(?![\w])" % re.escape(tn), n):
                pos = (i, 0)
                break
        q = re.sub(r"\s+", " ", quote.strip())
        if len(q) > 200:
            k = q.casefold().find(term.casefold())
            q = verbatim_window(q, max(k, 0), max(k, 0) + len(term), 200)
        accepted.append({"term": term, "aliases": aliases, "importance": imp, "jd_quote": q, "pos": pos})
    return accepted, stats


def extract_terms(parsed, lex, resume_defs, llm_terms, warnings, max_lines=2000):
    """Build the posting's term list. Returns (terms, extra_index) where extra_index is a FormIndex
    for every non-dictionary term (used for resume matching)."""
    lines = parsed["lines"][:max_lines]
    if len(parsed["lines"]) > max_lines:
        warnings.append("The job posting is very long; only its first %d lines were used for keywords." % max_lines)
    terms = {}
    order = []

    def get(key, factory):
        t = terms.get(key)
        if t is None:
            t = factory()
            terms[key] = t
            order.append(key)
        return t

    covered = {}
    # (a) dictionary
    for li, ln in enumerate(lines):
        s0 = _line_scan_from(ln)
        if s0 is None:
            continue
        text = ln["scan"]
        toks = [t for t in tokenize(text) if t.start >= s0]
        line_hits = scan_posting(lex.index, toks)
        for i, n, key, fk, fj, via in line_hits:
            e = lex.by_id[key]
            a, b = toks[i].start, toks[i + n - 1].end
            if e["ambiguous"] and key in lex.context_re:
                block_text = " ".join(x["scan"] for x in lines if x.get("block") == ln.get("block"))
                others = any(h[2] != key and h[2] in lex.language_ids for h in line_hits)
                if not lex.ambiguous_ok(key, text, a, b, block_text, others):
                    continue
            t = get("lex:" + key, lambda e=e: Term("lex:" + e["id"], "lexicon", e["kind"], e["canonical"],
                                                   e["id"], lex.entry_forms(e),
                                                   "low" if e["ambiguous"] else "high"))
            t.occ.append({"line": li, "start": a, "end": b, "surface": text[a:b],
                          "importance": importance_at(ln, a), "form_kind": fk})
            covered.setdefault(li, []).append((a, b))
    # (b) acronym definitions in the posting
    for li, ln in enumerate(lines):
        s0 = _line_scan_from(ln)
        if s0 is None:
            continue
        for phrase, acr, a, b in find_acronym_defs(ln["scan"][s0:]):
            if _full_cover(lex, phrase) or _full_cover(lex, acr):
                continue
            key = "acr:" + acr.upper()
            t = get(key, lambda phrase=phrase, acr=acr: Term(
                "acr:" + acr.upper(), "acronym_definition", "unknown", phrase, None,
                [(phrase, "canonical"), (acr, "acronym")], "high"))
            t.display = "%s (%s)" % (t.canonical, acr)
    # (c) tech-style tokens
    for li, ln in enumerate(lines):
        s0 = _line_scan_from(ln)
        if s0 is None:
            continue
        text = ln["scan"]
        caps_line = sum(1 for c in text if c.isupper()) > 0.6 * max(1, sum(1 for c in text if c.isalpha()))
        for rx in TECH_RES:
            for m in rx.finditer(text, s0):
                tok = m.group(0)
                if _covered(covered.get(li, ()), m.start(), m.end()) or _excluded_tech(tok, lex):
                    continue
                if caps_line and tok.isupper():
                    continue
                if _full_cover(lex, tok):
                    continue
                base = tok[:-1] if (tok.endswith("s") and tok[:-1].isupper() and len(tok) > 2) else tok
                if ("acr:" + base.upper()) in terms:
                    continue
                key = "tech:" + base.casefold()
                get(key, lambda base=base: Term("tech:" + base.casefold(), "tech_token", "unknown", base, None,
                                                [(base, "acronym" if base.isupper() else "canonical")], "medium"))
    # (d) phrases from required/preferred lines
    phrase_cover = dict((k, list(v)) for k, v in covered.items())
    for key, c in _phrase_candidates(lines, phrase_cover, lex):
        surface = c["surface"]
        if _full_cover(lex, surface):
            continue
        tkey = "ngram:" + " ".join(key)
        dup = any(terms[k].canonical.casefold() == surface.casefold() for k in order)
        if dup:
            continue
        get(tkey, lambda surface=surface, tkey=tkey: Term(tkey, "ngram", "unknown", surface, None,
                                                         [(surface, "canonical")], "low"))
    # (e) Claude's verified terms
    for item in llm_terms:
        forms = [(item["term"], "canonical")] + [(a, "alias") for a in item["aliases"]]
        eid = _full_cover(lex, item["term"])
        target = None
        if eid and ("lex:" + eid) in terms:
            target = terms["lex:" + eid]
        else:
            for k in order:
                if terms[k].canonical.casefold() == item["term"].casefold():
                    target = terms[k]
                    break
        if target is None and eid:
            e = lex.by_id[eid]
            target = get("lex:" + eid, lambda e=e: Term("lex:" + e["id"], "llm_verified", e["kind"],
                                                         e["canonical"], e["id"], lex.entry_forms(e), "medium"))
        if target is None:
            key = "llm:" + item["term"].casefold()
            target = get(key, lambda item=item, key=key: Term(key, "llm_verified", "unknown", item["term"],
                                                              None, forms, "medium"))
        for f in forms:
            if f not in target.forms:
                target.forms.append(f)
        if item["importance"] != "unspecified":
            prev = target.llm_importance
            if prev is None or IMPORTANCE_RANK[item["importance"]] > IMPORTANCE_RANK[prev]:
                target.llm_importance = item["importance"]
        if target.llm_quote is None:
            target.llm_quote = item["jd_quote"]
            target.llm_pos = item["pos"]
            target.llm_term = item["term"]
    # Forms from the resume's own acronym definitions widen matching ("LMS" <-> "learning management
    # system") for terms that are not in the dictionary.
    for key in order:
        t = terms[key]
        if t.entry_id:
            continue
        for form, _fk in list(t.forms):
            other = resume_defs.get(form.casefold())
            if other and (other, "alias") not in t.forms and (other, "acronym") not in t.forms:
                t.forms.append((other, "acronym" if other.isupper() else "alias"))
    # Occurrences of non-dictionary terms (frequency, importance, first position).
    extra = FormIndex()
    for key in order:
        t = terms[key]
        if t.entry_id:
            continue
        for form, fk in t.forms:
            letters = re.sub(r"[^A-Za-z]", "", form)
            cs = fk == "acronym" and letters.isupper() and len(letters) <= 3
            extra.add(form, key, fk, case_sensitive=cs, allow_stem=(fk != "acronym"),
                      plural_acronym=(fk == "acronym"))
    for li, ln in enumerate(lines):
        s0 = _line_scan_from(ln)
        if s0 is None:
            continue
        text = ln["scan"]
        toks = [t for t in tokenize(text) if t.start >= s0]
        for i, n, key, fk, fj, via in extra.scan(toks, longest_only=True):
            a, b = toks[i].start, toks[i + n - 1].end
            if _covered(covered.get(li, ()), a, b):
                continue
            terms[key].occ.append({"line": li, "start": a, "end": b, "surface": text[a:b],
                                   "importance": importance_at(ln, a), "form_kind": fk})
    # Alternatives inside one requirement become one group term ("Python or R").
    member_of = build_groups(lines, terms, order)
    # Finish: merge adjacent occurrences ("Search Engine Optimization (SEO)" counts once), importance,
    # frequency, quote, weight. Terms with no occurrence and no verified quote are dropped; a member whose
    # every occurrence went into a group lends Claude's importance to that group instead.
    built = {}
    for key in order:
        t = terms[key]
        if key in member_of and not t.occ and t.group is None:
            g = terms[member_of[key]]
            if t.llm_importance and (g.llm_importance is None or
                                     IMPORTANCE_RANK[t.llm_importance] > IMPORTANCE_RANK[g.llm_importance]):
                g.llm_importance = t.llm_importance
            continue
        row = _finish_term(t, lines)
        if row is not None:
            built[key] = row
    out = []
    for key in order:
        row = built.get(key)
        if row is None:
            continue
        t = terms[key]
        if t.group:
            mem = []
            for mk, surfaces, fkinds in t.members:
                own = built.get(mk)
                m = dict(own or _finish_term(terms[mk], lines, force=True))
                m["term"] = surfaces[0] if surfaces else m["term"]
                mine = {_joined(x) for x in surfaces}
                m["jd_surfaces"] = sorted(mine | set(own["jd_surfaces"])) if own else sorted(mine)
                m["jd_surface_tokens"] = _surface_tokens(list(surfaces) + (
                    [" ".join(x) for x in own["jd_surface_tokens"]] if own else []))
                m["jd_acronym"] = bool(fkinds) and fkinds[0] == "acronym"
                mem.append(m)
            row["members"] = mem
            row["group"] = t.group
            row["alternatives"] = [m["term"] for m in mem]
        else:
            row["group"] = None
            row["members"] = []
            row["alternatives"] = []
        out.append(row)
    out.sort(key=lambda d: d["pos"])
    return out, extra


def _finish_term(t, lines, force=False):
    """The output dict for one term (None when it has no occurrence and no verified quote)."""
    occ = sorted(t.occ, key=lambda o: (o["line"], o["start"]))
    merged = []
    for o in occ:
        if merged and merged[-1]["line"] == o["line"] and o["start"] - merged[-1]["end"] <= 3:
            if IMPORTANCE_RANK[o["importance"]] > IMPORTANCE_RANK[merged[-1]["importance"]]:
                merged[-1]["importance"] = o["importance"]
            merged[-1]["end"] = max(merged[-1]["end"], o["end"])
            continue
        merged.append(dict(o))
    if not merged and t.llm_quote is None and not force:
        return None
    surfaces = {_joined(o["surface"]) for o in occ}
    if merged:
        best = max(merged, key=lambda o: (IMPORTANCE_RANK[o["importance"]], -o["line"], -o["start"]))
        importance = best["importance"]
        first = merged[0]
        pos = (first["line"], first["start"])
        quote_line = lines[best["line"]]["scan"]
        quote = _quote_window(quote_line, best["start"], best["end"])
        # The posting's own words where it states the term most strongly ("Experience with SQL", not
        # "Write SQL queries"), narrowed to the dictionary name when the posting wrote it inside.
        surface = next((o["surface"] for o in occ if o["line"] == best["line"] and o["start"] == best["start"]),
                       best["surface"])
        if t.entry_id and not t.group:
            surface = _trim_to_form(surface, t.canonical) or surface
    else:
        importance = "unspecified"
        pos = t.llm_pos or (10 ** 6, 0)
        quote = t.llm_quote or ""
        # Never the dictionary's name: only words that are in the posting (Claude's term was checked
        # against its quote; a forced group member keeps its own surface, set by the caller).
        surface = t.llm_term or t.canonical
    if t.llm_importance and IMPORTANCE_RANK[t.llm_importance] > IMPORTANCE_RANK[importance]:
        importance = t.llm_importance
        if t.llm_quote:
            quote = t.llm_quote
    freq = max(1, len(merged))
    weight = (TERM_BASE_WEIGHT[importance] * TERM_KIND_FACTOR.get(t.kind, 0.6)
              * (1 + 0.25 * min(freq - 1, 3)))
    return {
        "key": t.key, "term": t.display or surface, "canonical": t.canonical, "kind": t.kind,
        "importance": importance, "weight": round(weight, 3), "jd_frequency": freq,
        "jd_quote": quote, "source": t.source, "confidence": t.confidence, "entry_id": t.entry_id,
        "jd_surfaces": sorted(surfaces | ({_joined(t.canonical)} if not merged else set())),
        "jd_surface_tokens": _surface_tokens(o["surface"] for o in occ),
        "jd_acronym": bool(merged) and merged[0].get("form_kind") == "acronym",
        "forms": list(t.forms), "pos": pos,
    }


def _surface_tokens(surfaces):
    out = []
    for s in surfaces:
        cfs = [t.cf for t in tokenize(s)]
        if cfs and cfs not in out:
            out.append(cfs)
    return out


def _joined(s):
    return "".join(t.cf for t in tokenize(s))


def _quote_window(text, a, b, limit=200):
    """A verbatim piece of `text` (no added "...") of at most `limit` characters around [a, b), cut
    at spaces, so the quote is always a substring of the posting line."""
    return verbatim_window(text, a, b, limit)


def verbatim_window(text, a, b, limit):
    if len(text) <= limit:
        return text
    room = max(0, limit - (b - a))
    s = max(0, a - room // 2)
    e = min(len(text), s + limit)
    s = max(0, e - limit)
    if s > 0:
        sp = text.find(" ", s, a) if a > s else -1
        if sp != -1:
            s = sp + 1
    if e < len(text):
        sp = text.rfind(" ", b, e)
        if sp != -1:
            e = sp
    return text[s:e].strip()


def resume_acronym_defs(texts):
    """{casefold(phrase): acronym, casefold(acronym): phrase} from the resume's own definitions."""
    out = {}
    for t in texts:
        for phrase, acr, _a, _b in find_acronym_defs(t):
            out.setdefault(phrase.casefold(), acr)
            out.setdefault(acr.casefold(), phrase)
    return out
