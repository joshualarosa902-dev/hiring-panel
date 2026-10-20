"""Matching posting terms against the resume (ATS spec 12).

Credit per match: exact, alias or acronym 1.0; inflection 0.9; implied (a more specific skill on the
resume, e.g. PostgreSQL for SQL) 0.8; partial (2/3 of a multiword term's content words on one line)
0.5; ambiguous (R, C, Go with no context word on the same line) 0.5; none 0.
Evidence level from where the term appears: demonstrated (experience, projects, leadership, volunteer),
listed (skills, certifications, coursework, education...), claimed (summary or top block only).
"""
import math

from .constants import EVIDENCE_BY_SECTION, EVIDENCE_RANK, FOUND_TYPES, MATCH_CREDIT
from .entries import DEGREE_WORD_RE
from .textutil import collapse_letter_spacing, snippet
from .tokens import derived_stems, stem, tokenize

# A match ending in one of these words right after a capitalized word is part of an institution's
# name ("Lincoln High School"), not a credential or a skill.
_INSTITUTION_WORDS = {"school", "college", "university", "academy", "institute"}
_LIST_SECTIONS = ("skills", "languages", "coursework", "certifications", "interests", "other")

_TYPE_PREF = {"exact": 6, "acronym": 5, "alias": 4, "inflection": 3, "implied": 2, "partial": 1,
              "ambiguous": 0}


def _lone_letter_run(toks, i):
    """A one-letter token next to other one-letter tokens ("J O R D A N") is spacing, not the skill
    "R" or "C"."""
    if len(toks[i].cf) != 1:
        return False
    left = i > 0 and len(toks[i - 1].cf) == 1 and toks[i - 1].soft_after
    right = i + 1 < len(toks) and len(toks[i + 1].cf) == 1 and toks[i].soft_after
    return left or right


def _tokens(text):
    """Tokens of a resume line with letter-spaced runs closed up ("P Y T H O N" reads as "PYTHON");
    spans still point into the original text so quotes stay verbatim."""
    ctext, cmap = collapse_letter_spacing(text)
    toks = tokenize(ctext)
    if cmap:
        for t in toks:
            t.start, t.end = cmap[t.start], cmap[t.end - 1] + 1
    return toks


def _in_institution_name(toks, i, n):
    last = toks[i + n - 1].cf
    if last not in _INSTITUTION_WORDS or i == 0:
        return False
    prev = toks[i - 1]
    return prev.orig[:1].isupper() and prev.cf not in ("a", "an", "the", "from", "at", "in", "of")


class ResumeText(object):
    """Tokenized resume lines with their evidence level, plus every dictionary/extra-term hit."""

    def __init__(self, lines, hf, lex, extra_index, has_headings):
        self.lex = lex
        self.rows = []
        for rl in lines:
            if rl.heading is not None:
                continue
            if has_headings:
                level = EVIDENCE_BY_SECTION.get(rl.section, "listed")
            else:
                level = "demonstrated" if rl.bullet else "listed"
            self.rows.append({"pos": len(self.rows), "line": rl.idx, "text": rl.text,
                              "section": rl.section, "level": level})
        for h in hf:
            self.rows.append({"pos": len(self.rows), "line": None, "text": h["text"],
                              "section": "header_footer", "level": "claimed"})
        self.hits = {}   # key -> [occurrence]
        parts = {}
        for row in self.rows:
            if row["section"] in _LIST_SECTIONS:
                parts.setdefault(row["section"], []).append(row["text"][:300])
        self.section_text = dict((k, " | ".join(v)[:20000]) for k, v in parts.items())
        for row in self.rows:
            toks = _tokens(row["text"])
            row["toks"] = toks
            stems = [stem(t.cf) for t in toks]
            row["stems"] = set(s for s, _c in stems) | derived_stems(t.cf for t in toks)
            row["ids"] = set()
            for idx in (lex.index, extra_index):
                if idx is None:
                    continue
                for i, n, key, fk, fj, via in idx.scan(toks, longest_only=False, stems=stems, derive=True):
                    if n == 1 and _lone_letter_run(toks, i):
                        continue
                    if _in_institution_name(toks, i, n):
                        continue
                    a, b = toks[i].start, toks[i + n - 1].end
                    row["ids"].add(key)
                    self.hits.setdefault(key, []).append({
                        "row": row, "start": a, "end": b, "surface": row["text"][a:b],
                        "form_kind": fk, "form_joined": fj, "via": via, "cfs": [t.cf for t in toks[i:i + n]]})

    def context_ok(self, eid, occ):
        """An ambiguous entry (R, C, Go, Epic...) counts only with context: a context word on the line or,
        for a list section, anywhere in that section; for programming languages also "in R", "R (" or
        another language on the same line (lexicon.ambiguous_ok)."""
        row = occ["row"]
        lex = self.lex
        if eid not in lex.context_re:
            return True
        others = any(k != eid and k in lex.language_ids for k in row["ids"])
        return lex.ambiguous_ok(eid, row["text"], occ["start"], occ["end"],
                                self.section_text.get(row["section"], ""), others)


def _runs(cfs):
    """Every joined run of consecutive tokens, plain and stemmed."""
    out = set()
    st = [stem(c)[0] for c in cfs]
    for a in range(len(cfs)):
        acc, sacc = "", ""
        for b in range(a, len(cfs)):
            acc += cfs[b]
            sacc += st[b]
            out.add(acc)
            out.add("~" + sacc)
    return out


def _same_words(cfs, term):
    """True when the resume wrote the posting's own words: one side's words appear in a row inside
    the other's, plurals aside ("CPR certified" holds the posting's "CPR"; "SQL" sits inside the
    posting's "SQL queries"; "dashboard" for "dashboards")."""
    if not cfs:
        return False
    mine = _runs(cfs)
    whole = "".join(cfs)
    swhole = "~" + "".join(stem(c)[0] for c in cfs)
    for surf in term.get("jd_surface_tokens") or []:
        if not surf:
            continue
        theirs = _runs(surf)
        if "".join(surf) in mine or ("~" + "".join(stem(c)[0] for c in surf)) in mine:
            return True
        if whole in theirs or swhole in theirs:
            return True
    return False


def _kind_of(occ, term):
    if occ["via"] == "inflection":
        return "inflection"
    if occ["form_joined"] in term["jd_surfaces"] or _same_words(occ.get("cfs"), term):
        return "exact"
    if (occ["form_kind"] == "acronym") != bool(term["jd_acronym"]):
        return "acronym"
    return "alias"


_NEAR = 4      # tokens: how close the words of a reworded phrase must be ("Analyzed reaction-time data")


def _token_stems(tok):
    """(direct stem, derived noun stems) of one resume token."""
    return stem(tok.cf)[0], derived_stems([tok.cf])


def _partial(term, rt, stopwords, row_ok=None):
    """Rows where at least 2/3 (and at least 2) of a multiword form's content words appear ("partial").

    When every content word is there, one of them only as its verb ("analyzed" for "analysis"), and the
    words sit within a few tokens of each other, the phrase was reworded, not half-missing: that counts
    as an inflection ("Analyzed reaction-time data" shows "data analysis"; "learning the espresso
    machine" never shows "machine learning", since no word was derived)."""
    out = []
    for form, fk in term["forms"]:
        if fk == "acronym":
            continue
        content = []
        for t in tokenize(form):
            if t.cf in stopwords or len(t.cf) < 2:
                continue
            s = stem(t.cf)[0]
            if s not in content:
                content.append(s)
        k = len(content)
        if k < 2:
            continue
        need = max(2, int(math.ceil(2.0 * k / 3.0)))
        for row in rt.rows:
            if row_ok is not None and not row_ok(row):
                continue
            got = [s for s in content if s in row["stems"]]
            if len(got) < need:
                continue
            where = {}         # content stem -> [(token index, derived?)]
            for i, tok in enumerate(row["toks"]):
                direct, derived = _token_stems(tok)
                for s in got:
                    if s == direct:
                        where.setdefault(s, []).append((i, False))
                    elif s in derived:
                        where.setdefault(s, []).append((i, True))
            hit = sorted(i for s in got for i, _d in where.get(s, []))
            if not hit:
                continue
            typ = "partial"
            if len(got) == k and len(where) == k and any(d for s in got for _i, d in where[s]):
                firsts = [min(i for i, _d in where[s]) for s in got]
                if max(firsts) - min(firsts) <= _NEAR:
                    typ = "inflection"
                    hit = sorted(firsts)
            toks = row["toks"]
            a, b = toks[hit[0]].start, toks[hit[-1]].end
            out.append({"row": row, "start": a, "end": b, "surface": row["text"][a:b], "type": typ})
    return out


def education_row(row):
    """A resume row that can show a degree field: the Education section, or a line naming a degree."""
    return row["section"] == "education" or bool(DEGREE_WORD_RE.search(row["text"]))


def match_row(term, rt, lex):
    """match_term for a posting term, or for a group of alternatives ("Python or R"): the best member
    wins. A degree-field group is matched against Education lines only, and a match there is full
    evidence for a degree requirement. Adds "matched_alternative" (the posting's word for the member
    that was found, or None)."""
    if not term.get("group"):
        out = match_term(term, rt, lex)
        out["matched_alternative"] = None
        return _held_credential(out, term.get("kind"))
    row_ok = education_row if term["group"] == "degree_field" else None
    best = None
    for m in term.get("members") or []:
        r = match_term(m, rt, lex, row_ok)
        k = (r["found"], r["credit"], EVIDENCE_RANK[r["evidence_level"]])
        if best is None or k > best[0]:
            best = (k, m, r)
    if best is None:
        out = {"found": False, "match_type": "none", "credit": 0.0, "resume_wording": None,
               "evidence_level": "none", "resume_locations": [], "snippets": []}
        out["matched_alternative"] = None
        return out
    _k, m, r = best
    out = dict(r)
    out["matched_alternative"] = m["term"] if r["found"] else None
    if term["group"] == "degree_field" and r["found"]:
        out["evidence_level"] = "demonstrated"
    return _held_credential(out, m.get("kind"))


def _held_credential(out, kind):
    """A certification or diploma is shown by listing it (Certifications, Education or Skills); there is
    no bullet that would show it better, so a listed one counts as full evidence, never "only listed"."""
    if kind == "cert" and out["found"] and out["evidence_level"] == "listed":
        out = dict(out)
        out["evidence_level"] = "demonstrated"
    return out


def match_term(term, rt, lex, row_ok=None):
    """Score one posting term against the resume. Returns the public fields for screening.json.
    row_ok(row) -> bool limits which resume rows count."""
    cands = []
    keys = [term["entry_id"]] if term["entry_id"] else [term["key"]]
    for key in keys:
        for o in rt.hits.get(key, ()):
            if row_ok is not None and not row_ok(o["row"]):
                continue
            typ = _kind_of(o, term)
            if term["entry_id"] and not rt.context_ok(term["entry_id"], o):
                typ = "ambiguous"
            cands.append(dict(o, type=typ))
    if term["entry_id"]:
        for src in lex.implied_by.get(term["entry_id"], ()):
            for o in rt.hits.get(src, ()):
                if row_ok is not None and not row_ok(o["row"]):
                    continue
                if not rt.context_ok(src, o):
                    continue
                cands.append(dict(o, type="implied"))
    if not any(c["type"] in FOUND_TYPES for c in cands):
        cands.extend(_partial(term, rt, lex.stopwords_en, row_ok))
    if not cands:
        return {"found": False, "match_type": "none", "credit": 0.0, "resume_wording": None,
                "evidence_level": "none", "resume_locations": [], "snippets": []}

    def rank(c):
        return (MATCH_CREDIT[c["type"]], EVIDENCE_RANK[c["row"]["level"]], _TYPE_PREF[c["type"]],
                -c["row"]["pos"], -c["start"])
    best = max(cands, key=rank)
    found = best["type"] in FOUND_TYPES
    pool = [c for c in cands if (c["type"] in FOUND_TYPES) == found]
    level = max((c["row"]["level"] for c in pool), key=lambda lv: EVIDENCE_RANK[lv])
    locs = []
    for c in sorted(pool, key=lambda c: (-EVIDENCE_RANK[c["row"]["level"]], c["row"]["section"])):
        if c["row"]["section"] not in locs:
            locs.append(c["row"]["section"])
    snips, used = [], set()
    for c in sorted(pool, key=lambda c: (-EVIDENCE_RANK[c["row"]["level"]], -MATCH_CREDIT[c["type"]],
                                         c["row"]["pos"], c["start"])):
        if c["row"]["pos"] in used:
            continue
        used.add(c["row"]["pos"])
        snips.append(snippet(c["row"]["text"], c["start"], c["end"]))
        if len(snips) == 2:
            break
    return {"found": found, "match_type": best["type"], "credit": MATCH_CREDIT[best["type"]],
            "resume_wording": best["surface"][:120], "evidence_level": level,
            "resume_locations": locs, "snippets": snips}
