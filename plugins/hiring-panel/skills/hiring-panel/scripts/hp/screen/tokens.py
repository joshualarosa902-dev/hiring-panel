"""Tokenizer, light stemmer and phrase index used for keyword matching (ATS spec 12).

Matching works on token sequences instead of one regex per skill, so thousands of dictionary entries
cost one pass over the text. Variants are handled by keys:
- exact: the casefolded token tuple ("front end" == "Front End"),
- joined: the tokens glued together ("front-end" == "front end" == "frontend", "A/B" == "AB"),
- stem: the last token reduced by a few suffix rules ("dashboards" ~ "dashboard").
Case-sensitive forms (short acronyms, entries flagged case_sensitive) are compared on original case.
"""
import re

# A token: optional leading dot (".NET"), letters/digits, "&" between letters ("R&D", "AT&T"), and a
# trailing "++", "#" or "+" ("C++", "C#", "A+").
_TOKEN_RE = re.compile(r"\.?[^\W_](?:[^\W_]|&(?=[^\W_]))*(?:\+\+|#|\+(?![\w]))?")
# Characters allowed between two tokens of the same phrase. Anything else (comma, colon, brackets)
# breaks a phrase, so "front, end" never matches "front-end".
_SOFT_GAP_RE = re.compile(r"^[ \t\-/._–]*$")
_UNDOUBLE = set("bdgmnprt")


class Token(object):
    """One token of a line: original text, casefolded text, character span, and whether the gap to
    the next token is a soft separator (space, hyphen, slash, dot)."""
    __slots__ = ("orig", "cf", "start", "end", "soft_after")

    def __init__(self, orig, start, end):
        self.orig = orig
        self.cf = orig.casefold()
        self.start = start
        self.end = end
        self.soft_after = False


def tokenize(text):
    """Split text into Tokens. A leading dot is kept only when it starts a word (".NET"), so
    "Node.js" becomes "Node" + "js" and joins back to "nodejs"."""
    toks = []
    for m in _TOKEN_RE.finditer(text or ""):
        s, e = m.start(), m.end()
        tok = m.group(0)
        if tok.startswith(".") and s > 0 and text[s - 1].isalnum():
            tok = tok[1:]
            s += 1
        if not tok:
            continue
        toks.append(Token(tok, s, e))
    for i in range(len(toks) - 1):
        toks[i].soft_after = bool(_SOFT_GAP_RE.match(text[toks[i].end:toks[i + 1].start]))
    return toks


def _drop_e(t):
    return t[:-1] if len(t) > 4 and t.endswith("e") and not t.endswith("ee") else t


def _undouble(t):
    if len(t) >= 4 and t[-1] == t[-2] and t[-1] in _UNDOUBLE:
        return t[:-1]
    return t


def stem(tok):
    """Reduce a casefolded word with a few suffix rules (no full stemmer).

    Returns (stem, suffix_class) where suffix_class is "plural" (ies/es/s), "verb" (ing/ed) or "none".
    Only alphabetic words of 4+ characters are touched.
    """
    t = tok
    if len(t) < 4 or not t.isalpha():
        return t, "none"
    if t.endswith("ies") and len(t) > 4:
        return t[:-3] + "y", "plural"
    if t.endswith("es") and len(t) > 4 and re.search(r"(?:ss|x|z|ch|sh)es$", t):
        return t[:-2], "plural"
    if t.endswith("s") and not t.endswith(("ss", "us", "is")):
        return _drop_e(t[:-1]), "plural"
    if t.endswith("ing") and len(t) >= 6:
        return _drop_e(_undouble(t[:-3])), "verb"
    if t.endswith("ed") and len(t) >= 5:
        return _drop_e(_undouble(t[:-2])), "verb"
    return _drop_e(t), "none"


# Light derivational matching (resume side only): a noun term also matches the verb forms of the same
# word, so "communicate with customers" is evidence for "communication". Bare forms that are also
# common nouns or adjectives ("present", "document", "documents") are left out on purpose.
DERIVATIONS = {
    "communication": ("communicate", "communicates", "communicated", "communicating"),
    "analysis": ("analyze", "analyzes", "analyzed", "analyzing", "analyse", "analyses", "analysed",
                 "analysing"),
    "analytical": ("analyze", "analyzes", "analyzed", "analyzing", "analyse", "analysed", "analysing"),
    "organization": ("organize", "organizes", "organized", "organizing", "organise", "organises",
                     "organised", "organising"),
    "collaboration": ("collaborate", "collaborates", "collaborated", "collaborating"),
    "presentation": ("presented", "presenting"),
    "management": ("manage", "manages", "managed", "managing"),
    "documentation": ("documented", "documenting"),
}
for _noun in list(DERIVATIONS):
    DERIVATIONS[_noun + "s"] = DERIVATIONS[_noun]
_VERB_TO_NOUNS = {}
for _noun, _verbs in sorted(DERIVATIONS.items()):
    for _v in _verbs:
        _VERB_TO_NOUNS.setdefault(_v, []).append(_noun)


def derived_stems(cfs):
    """Stems of the nouns derived from verbs among the casefolded words `cfs` ("analyzed" -> "analysis")."""
    out = set()
    for w in cfs:
        for noun in _VERB_TO_NOUNS.get(w, ()):
            out.add(stem(noun)[0])
    return out


def suffix_compatible(a, b):
    """Plural and bare forms match each other; -ing/-ed forms only match other -ing/-ed forms.
    This keeps "accounts" from matching "accounting" and "markets" from matching "marketing"."""
    if a == "verb" or b == "verb":
        return a == b
    return True


def joined_key(toks):
    return "".join(t.cf for t in toks)


class FormIndex(object):
    """An index of surface forms ("SEO", "search engine optimization") pointing at term keys.

    add() registers one form; scan() finds forms in a tokenized line. Values are lists so two keys
    may share a form; insertion order keeps results deterministic.
    """

    def __init__(self):
        self.ci = {}       # tuple(casefold tokens) -> [(key, form_kind, form_joined)]
        self.cs = {}       # tuple(original tokens) -> [...]
        self.jci = {}      # joined casefold string -> [...]
        self.jcs = {}      # joined original string -> [...]
        self.stem = {}     # tuple(tokens[:-1] + stem(last)) -> [(key, form_kind, form_joined, cls)]
        self.deriv = {}    # verb form -> [(key, form_kind, form_joined)] for one-word noun forms
        self.maxn = 1

    @staticmethod
    def _put(d, k, v):
        lst = d.get(k)
        if lst is None:
            d[k] = [v]
        elif v not in lst:
            lst.append(v)

    def add(self, form, key, form_kind, case_sensitive=False, allow_stem=True, plural_acronym=False):
        toks = tokenize(form)
        if not toks:
            return
        self.maxn = max(self.maxn, len(toks))
        fj = joined_key(toks)
        val = (key, form_kind, fj)
        if case_sensitive:
            self._put(self.cs, tuple(t.orig for t in toks), val)
            if len(toks) > 1 and len(fj) >= 4:
                self._put(self.jcs, "".join(t.orig for t in toks), val)
            if plural_acronym and len(toks) == 1:
                self._put(self.cs, (toks[0].orig + "s",), (key, form_kind, fj + "s"))
            return
        self._put(self.ci, tuple(t.cf for t in toks), val)
        if len(fj) >= 4:
            self._put(self.jci, fj, val)
        if plural_acronym and len(toks) == 1:
            self._put(self.ci, (toks[0].cf + "s",), (key, form_kind, fj + "s"))
        last = toks[-1].cf
        if allow_stem and last.isalpha() and len(last) >= 4:
            st, cls = stem(last)
            k = tuple(t.cf for t in toks[:-1]) + (st,)
            self._put(self.stem, k, (key, form_kind, fj, cls))
        if allow_stem and len(toks) == 1 and last in DERIVATIONS:
            for v in DERIVATIONS[last]:
                self._put(self.deriv, v, val)

    def lookup(self, toks, i, n, stems, derive=False):
        """All hits for the n-gram starting at i: list of (key, form_kind, form_joined, via).
        derive=True also tries DERIVATIONS (verb form -> noun term) for one-word n-grams."""
        seg = toks[i:i + n]
        hits = []
        seen = set()

        def emit(vals, via):
            for v in vals:
                if v[0] in seen:
                    continue
                seen.add(v[0])
                hits.append((v[0], v[1], v[2], via))
        cf = tuple(t.cf for t in seg)
        emit(self.ci.get(cf, ()), "exact")
        emit(self.cs.get(tuple(t.orig for t in seg), ()), "exact")
        j = "".join(cf)
        if len(j) >= 4:
            emit(self.jci.get(j, ()), "exact")
            emit(self.jcs.get("".join(t.orig for t in seg), ()), "exact")
        last_stem, last_cls = stems[i + n - 1]
        if seg[-1].cf.isalpha() and len(seg[-1].cf) >= 4:
            k = cf[:-1] + (last_stem,)
            for key, fk, fj, cls in self.stem.get(k, ()):
                if key in seen or not suffix_compatible(cls, last_cls):
                    continue
                if cls == "none" and last_cls == "none":
                    continue
                seen.add(key)
                hits.append((key, fk, fj, "inflection"))
        if derive and n == 1:
            emit(self.deriv.get(seg[0].cf, ()), "inflection")
        return hits

    def scan(self, toks, longest_only=True, stems=None, derive=False):
        """Find forms in a token list. Returns [(i, n, key, form_kind, form_joined, via)].

        longest_only=True: greedy, non-overlapping, longest match first (used on the job posting).
        longest_only=False: every match at every position (used on the resume, for recall).
        """
        out = []
        L = len(toks)
        if not L:
            return out
        if stems is None:
            stems = [stem(t.cf) for t in toks]
        i = 0
        while i < L:
            lim = 1
            while lim < self.maxn and i + lim < L and toks[i + lim - 1].soft_after:
                lim += 1
            here = []
            for n in range(lim, 0, -1):
                hits = self.lookup(toks, i, n, stems, derive)
                if hits:
                    here.extend((i, n) + h for h in hits)
                    if longest_only:
                        break
            out.extend(here)
            i += here[0][1] if (longest_only and here) else 1
        return out
