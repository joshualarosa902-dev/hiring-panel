"""skills.json: structure, uniqueness, implies, ambiguity and false-match safety.

The matcher in hp.screen compiles every form with the boundary rule from ATS spec section 11
((?<![\\w+#.]) ... (?![\\w+#])). These tests use a small reference matcher with the same rule, so
they check the DATA, not hp.screen's implementation. Fictional text only.
"""
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "plugins", "hiring-panel", "skills", "hiring-panel", "scripts")
sys.path.insert(0, SCRIPTS)

from hp import util  # noqa: E402

DATA = os.path.join(SCRIPTS, "hp", "data")
FIX = os.path.join(HERE, "fixtures", "lexicon")

KINDS = {"hard", "tool", "cert", "domain", "soft", "title"}
KEYS = ["id", "canonical", "kind", "aliases", "acronyms", "case_sensitive", "ambiguous", "context", "implies"]
B0, B1 = r"(?<![\w+#.])", r"(?![\w+#])"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
US_REGIONS = set("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY "
                 "NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC PR GU VI AS MP".split())
CA_REGIONS = set("AB BC MB NB NL NS NT NU ON PE QC SK YT".split())

# Single-word forms whose crude stem (ATS spec 12: strip ies/es/s/ing/ed) equals a common English
# word. Each is a deliberate keep: the skill IS the word's meaning, and hp.screen.tokens only lets
# -ing/-ed forms match other -ing/-ed forms, so "accounts" never matches "Accounting". A new entry
# that lands here must be reviewed and added with a reason, or renamed.
STEM_ALLOWLIST = {
    "accounting": "account; hp.screen keeps verb (-ing) and plural stems apart",
    "budgeting": "budget; a managed budget is budgeting evidence",
    "coaching": "coach; coaching a team is the skill",
    "cooking": "cook; a cook cooks",
    "forecasting": "forecast; same meaning",
    "marketing": "market; hp.screen keeps verb (-ing) and plural stems apart",
    "prospecting": "prospect; hp.screen keeps verb (-ing) and plural stems apart",
    "recruiting": "recruit; recruiting members or staff is the skill",
    "sewing": "sew; same meaning",
    "polling": "poll; running polls is survey research",
    "teaching": "teach; same meaning",
}

# Common English words that are also deliberate single-word skill names (none expected right now:
# common_words.txt leaves field names out). Kept as an explicit, reviewed exception list.
COMMON_WORD_ALLOWLIST = set()

# One-word titles that job posts use for collaborators ("partner with designers") must not exist.
GENERIC_TITLES = {"engineer", "designer", "analyst", "manager", "server", "host", "editor", "teacher", "nurse",
                  "developer", "consultant", "associate", "assistant", "intern", "coordinator", "specialist",
                  "director", "coach", "trainer", "programmer", "architect", "writer", "driver", "technician",
                  "administrator", "representative", "officer", "scientist", "researcher", "volunteer"}


def load_skills():
    with open(os.path.join(DATA, "skills.json"), encoding="utf-8") as f:
        return json.load(f)


def load_common_words():
    out = []
    with open(os.path.join(FIX, "common_words.txt"), encoding="utf-8") as f:
        for line in f:
            w = line.strip()
            if w and not w.startswith("#"):
                out.append(w)
    return out


def forms(e):
    return [e["canonical"]] + list(e["aliases"]) + list(e["acronyms"])


def sep_key(form):
    """hyphen, slash and space variants are equal ("front-end" == "front end" == "frontend")."""
    return re.sub(r"[\s\-/]+", "", form.casefold())


def crude_stem(w):
    """The ATS spec's crude rule (single word, 4+ characters): ies->y, es, s, ing, ed."""
    w = w.casefold()
    if len(w) < 4:
        return w
    for suf, rep in (("ies", "y"), ("es", ""), ("s", ""), ("ing", ""), ("ed", "")):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)] + rep
    return w


def form_regex(form, case_sensitive):
    return re.compile(B0 + re.escape(form) + B1, 0 if case_sensitive else re.IGNORECASE)


class RefMatcher(object):
    """Reference matcher: longest non-overlapping hits per line, with the ambiguity rule."""

    def __init__(self, entries):
        self.items = []
        for e in entries:
            fs = sorted(set(forms(e)), key=len, reverse=True)
            rx = re.compile(B0 + "(?:" + "|".join(re.escape(f) for f in fs) + ")" + B1,
                            0 if e["case_sensitive"] else re.IGNORECASE)
            ctx = None
            if e["ambiguous"]:
                ctx = re.compile(B0 + "(?:" + "|".join(re.escape(c) for c in e["context"]) + ")" + B1,
                                 re.IGNORECASE)
            self.items.append((e, rx, ctx))

    def scan(self, text):
        """Return {id: "full" | "ambiguous"} for every entry found (longest match wins a span)."""
        found = {}
        for line in text.splitlines():
            hits = []
            for e, rx, ctx in self.items:
                for m in rx.finditer(line):
                    hits.append((m.start(), m.end(), e, ctx))
            hits.sort(key=lambda h: (-(h[1] - h[0]), h[0], h[2]["id"]))
            taken = []
            for s, t, e, ctx in hits:
                if any(s < b and a < t for a, b in taken):
                    continue
                taken.append((s, t))
                level = "full" if ctx is None or ctx.search(line) else "ambiguous"
                if found.get(e["id"]) != "full":
                    found[e["id"]] = level
        return found


class SkillsStructureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load_skills()
        cls.entries = cls.data["entries"]
        cls.by_id = {e["id"]: e for e in cls.entries}

    def test_top_level(self):
        self.assertEqual(sorted(self.data), ["entries", "version"])
        self.assertEqual(self.data["version"], "1.0.0")
        self.assertIsInstance(self.entries, list)

    def test_size_in_target_range(self):
        self.assertGreaterEqual(len(self.entries), 900)
        self.assertLessEqual(len(self.entries), 1500)

    def test_every_kind_is_represented(self):
        counts = {}
        for e in self.entries:
            counts[e["kind"]] = counts.get(e["kind"], 0) + 1
        self.assertEqual(set(counts), KINDS)
        self.assertGreaterEqual(counts["title"], 100)
        self.assertGreaterEqual(counts["soft"], 30)
        self.assertGreaterEqual(counts["cert"], 50)

    def test_entry_shape_and_types(self):
        for e in self.entries:
            self.assertEqual(list(e), KEYS, e.get("id"))
            self.assertIn(e["kind"], KINDS, e["id"])
            self.assertRegex(e["id"], ID_RE)
            self.assertIsInstance(e["case_sensitive"], bool)
            self.assertIsInstance(e["ambiguous"], bool)
            for key in ("aliases", "acronyms", "context", "implies"):
                self.assertIsInstance(e[key], list, (e["id"], key))
                for v in e[key]:
                    self.assertIsInstance(v, str, (e["id"], key))

    def test_forms_are_clean_and_pre_normalized(self):
        """Forms must survive util.norm_text unchanged, or they could never match normalized text."""
        for e in self.entries:
            for f in forms(e) + e["context"]:
                self.assertTrue(f, e["id"])
                self.assertEqual(f, f.strip(), (e["id"], f))
                self.assertNotIn("  ", f, (e["id"], f))
                self.assertEqual(util.norm_text(f), f, (e["id"], f))

    def test_sorted_by_id_for_stable_diffs(self):
        ids = [e["id"] for e in self.entries]
        self.assertEqual(ids, sorted(ids))

    def test_ids_unique(self):
        ids = [e["id"] for e in self.entries]
        self.assertEqual(len(ids), len(set(ids)))

    def test_canonical_unique_case_insensitively(self):
        seen = {}
        for e in self.entries:
            k = e["canonical"].casefold()
            self.assertNotIn(k, seen, "%s duplicates %s" % (e["id"], seen.get(k)))
            seen[k] = e["id"]

    def test_no_form_repeated_inside_an_entry(self):
        for e in self.entries:
            fs = forms(e)
            if e["case_sensitive"]:
                self.assertEqual(len(fs), len(set(fs)), e["id"])
            else:
                self.assertEqual(len(fs), len({f.casefold() for f in fs}), e["id"])

    def test_no_form_maps_to_two_entries_unless_both_ambiguous(self):
        owner = {}
        for e in self.entries:
            for f in forms(e):
                k = sep_key(f)
                o = owner.get(k)
                if o is not None and o["id"] != e["id"]:
                    self.assertTrue(o["ambiguous"] and e["ambiguous"],
                                    "form %r is in %s and %s" % (f, o["id"], e["id"]))
                owner.setdefault(k, e)

    def test_no_stem_collision_between_entries_unless_both_ambiguous(self):
        owner = {}
        for e in self.entries:
            for f in forms(e):
                if " " in f or len(f) < 4 or f.isupper():
                    continue
                k = crude_stem(f)
                o = owner.get(k)
                if o is not None and o["id"] != e["id"]:
                    self.assertTrue(o["ambiguous"] and e["ambiguous"],
                                    "stem %r of %r: %s vs %s" % (k, f, o["id"], e["id"]))
                owner.setdefault(k, e)


class ImpliesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries = load_skills()["entries"]
        cls.by_id = {e["id"]: e for e in cls.entries}

    def test_targets_exist_and_are_ids(self):
        for e in self.entries:
            for t in e["implies"]:
                self.assertIn(t, self.by_id, "%s implies missing %r" % (e["id"], t))
                self.assertNotEqual(t, e["id"])

    def test_sorted_unique(self):
        for e in self.entries:
            self.assertEqual(e["implies"], sorted(set(e["implies"])), e["id"])

    def test_transitively_closed_and_acyclic(self):
        for e in self.entries:
            mine = set(e["implies"])
            for t in e["implies"]:
                self.assertTrue(set(self.by_id[t]["implies"]) <= mine,
                                "%s -> %s is not closed" % (e["id"], t))
                self.assertNotIn(e["id"], self.by_id[t]["implies"], "cycle %s <-> %s" % (e["id"], t))

    def test_contract_examples(self):
        self.assertIn("sql", self.by_id["postgresql"]["implies"])
        self.assertIn("ms-excel", self.by_id["pivot-tables"]["implies"])
        self.assertIn("ms-excel", self.by_id["vlookup"]["implies"])
        self.assertIn("python", self.by_id["pandas"]["implies"])
        self.assertIn("javascript", self.by_id["typescript"]["implies"])
        self.assertIn("react", self.by_id["next-js"]["implies"])
        self.assertIn("cardiopulmonary-resuscitation", self.by_id["basic-life-support"]["implies"])


class AmbiguityAndCaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries = load_skills()["entries"]
        cls.by_id = {e["id"]: e for e in cls.entries}
        cls.common = load_common_words()

    def test_ambiguous_entries_have_context(self):
        for e in self.entries:
            if e["ambiguous"]:
                self.assertGreaterEqual(len(e["context"]), 3, e["id"])
            else:
                self.assertEqual(e["context"], [], e["id"])

    def test_long_forms_of_ambiguous_entries_disambiguate_themselves(self):
        """Only the short form should need context: "Google Cloud Platform" must count on its own."""
        for e in self.entries:
            if not e["ambiguous"]:
                continue
            ctx = re.compile(B0 + "(?:" + "|".join(re.escape(c) for c in e["context"]) + ")" + B1, re.I)
            for f in forms(e):
                if " " in f or len(f) > 12:
                    self.assertTrue(ctx.search(f), "%s: %r has no context word" % (e["id"], f))

    def test_known_short_tokens_are_flagged(self):
        for eid in ("r-lang", "c-lang", "go-lang", "swift-lang", "ms-word", "ms-access", "ruby", "rust", "dart",
                    "julia-lang", "unity-engine", "apache-spark", "epic-ehr"):
            e = self.by_id[eid]
            self.assertTrue(e["case_sensitive"] and e["ambiguous"], eid)
        excel = self.by_id["ms-excel"]
        self.assertTrue(excel["case_sensitive"])      # "excel in a fast-paced role" is not the software
        self.assertFalse(excel["ambiguous"])          # but "Excel" alone needs no context

    def test_case_sensitive_forms_are_not_lowercase_common_words(self):
        common = set(self.common)
        for e in self.entries:
            if e["case_sensitive"]:
                for f in forms(e):
                    self.assertNotIn(f, common, "%s: %r is a common word in lowercase" % (e["id"], f))

    def test_no_bare_region_codes(self):
        """'San Juan, PR' and 'Montreal, QC' must not count as skills without context."""
        for e in self.entries:
            if e["ambiguous"]:
                continue
            for f in forms(e):
                self.assertNotIn(f.upper() if len(f) == 2 else None, US_REGIONS | CA_REGIONS, (e["id"], f))


class BoundaryRuleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries = load_skills()["entries"]
        cls.common = load_common_words()

    def test_every_form_compiles_and_matches_itself(self):
        for e in self.entries:
            for f in forms(e):
                rx = form_regex(f, e["case_sensitive"])
                for text in ("%s" % f, "Skills: %s, more" % f, "(%s)" % f, "- Used %s." % f, "%s | Other" % f):
                    self.assertTrue(rx.search(text), "%s: %r does not match in %r" % (e["id"], f, text))

    def test_no_common_word_hits(self):
        """No non-ambiguous, case-insensitive entry may match an ordinary English word."""
        text = "\n".join(self.common)
        bad = []
        for e in self.entries:
            if e["ambiguous"] or e["case_sensitive"]:
                continue
            for f in forms(e):
                m = form_regex(f, False).search(text)
                if m and m.group(0).casefold() not in COMMON_WORD_ALLOWLIST:
                    bad.append("%s: %r matched %r" % (e["id"], f, m.group(0)))
        self.assertEqual(bad, [])

    def test_case_sensitive_entries_do_not_hit_lowercase_common_words(self):
        text = "\n".join(self.common)
        for e in self.entries:
            if e["ambiguous"] or not e["case_sensitive"]:
                continue
            for f in forms(e):
                self.assertIsNone(form_regex(f, True).search(text), (e["id"], f))

    def test_stem_hazards_are_reviewed(self):
        """A single-word form whose crude stem is a common word must be on the reviewed allowlist."""
        common = set(self.common)
        stems = {}
        for w in sorted(common):
            stems.setdefault(crude_stem(w), w)
        found = {}
        for e in self.entries:
            if e["ambiguous"] or e["case_sensitive"]:
                continue
            for f in forms(e):
                if " " in f or len(f) < 4 or f.isupper() or f.casefold() in common:
                    continue      # multi-word, short, acronym, or already covered by test_no_common_word_hits
                if crude_stem(f) in stems:
                    found[f.casefold()] = stems[crude_stem(f)]
        unreviewed = sorted(set(found) - set(STEM_ALLOWLIST))
        self.assertEqual(unreviewed, [], "review these stem hazards: %r" % {k: found[k] for k in unreviewed})
        stale = sorted(set(STEM_ALLOWLIST) - set(found))
        self.assertEqual(stale, [], "allowlist entries no longer needed: %r" % stale)


class TitlesAndKindsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries = load_skills()["entries"]
        cls.index = {}
        for e in cls.entries:
            for f in forms(e):
                cls.index.setdefault(f.casefold(), e)

    def resolve(self, term):
        e = self.index.get(term.casefold())
        self.assertIsNotNone(e, "no entry for %r" % term)
        return e

    def test_no_generic_one_word_titles(self):
        for e in self.entries:
            if e["kind"] != "title":
                continue
            for f in forms(e):
                self.assertNotIn(f.casefold(), GENERIC_TITLES, (e["id"], f))

    def test_titles_have_no_plural_forms(self):
        """Plurals would turn "work with product managers" into a title term."""
        for e in self.entries:
            if e["kind"] != "title":
                continue
            for f in e["aliases"] + [e["canonical"]]:
                last = re.split(r"[\s/]+", f)[-1].casefold()
                plural = last.endswith("s") and not last.endswith(("ss", "us", "is"))
                self.assertFalse(plural, (e["id"], f))

    def test_every_field_is_covered(self):
        with open(os.path.join(FIX, "field_samples.json"), encoding="utf-8") as f:
            samples = json.load(f)
        self.assertEqual(len(samples["fields"]), 14)
        for field, terms in samples["fields"].items():
            self.assertGreaterEqual(len(terms), 8, field)
            for t in terms:
                self.resolve(t)
        for kind, terms in samples["kinds"].items():
            for t in terms:
                self.assertEqual(self.resolve(t)["kind"], kind, t)


class MatchingBehaviourTest(unittest.TestCase):
    """End-to-end examples from the ATS spec (section 19) on the real data, fictional text."""

    @classmethod
    def setUpClass(cls):
        cls.m = RefMatcher(load_skills()["entries"])

    def found(self, text):
        return self.m.scan(text)

    def test_alias_and_acronym_share_an_entry(self):
        self.assertIn("search-engine-optimization", self.found("Improved search engine optimization"))
        self.assertIn("search-engine-optimization", self.found("SEO audits for 3 sites"))

    def test_hyphen_slash_space_variants(self):
        for text in ("front-end work", "front end work", "frontend work"):
            self.assertIn("front-end-development", self.found(text), text)
        for text in ("ran A/B testing", "ran AB testing", "ran an A/B test"):
            self.assertIn("a-b-testing", self.found(text), text)

    def test_short_languages_need_context(self):
        self.assertEqual(self.found("Built models in R and Python")["r-lang"], "full")
        self.assertEqual(self.found("R&D club member")["r-lang"], "ambiguous")
        self.assertNotIn("go-lang", {k for k, v in self.found("Go above and beyond").items() if v == "full"})
        self.assertEqual(self.found("Backend services in Go and Rust")["go-lang"], "full")

    def test_plus_and_hash_boundaries(self):
        f = self.found("Wrote C++ and C# tools")
        self.assertIn("cpp", f)
        self.assertIn("csharp", f)
        self.assertNotIn("c-lang", f)

    def test_dotnet_inside_asp_dotnet(self):
        f = self.found("Built an ASP.NET site")
        self.assertIn("asp-net", f)
        self.assertNotIn("dotnet", f)

    def test_case_sensitive_words(self):
        self.assertNotIn("ms-excel", self.found("You will excel in a fast-paced team"))
        self.assertIn("ms-excel", self.found("Advanced Microsoft Excel and Word"))
        self.assertNotIn("slack", self.found("Picked up the slack during finals"))
        self.assertNotIn("agile", self.found("an agile, curious learner"))
        self.assertIn("agile", self.found("Agile ceremonies and sprint reviews"))

    def test_ordinary_resume_lines_stay_quiet(self):
        text = ("Spring 2025 | Fall 2024\n"
                "Played a vital role in the food bank drive\n"
                "Opened a savings account at the bank\n"
                "Earned an A+ in Calculus\n"
                "Contact: San Juan, PR | Montreal, QC | Pittsburgh, PA\n"
                "Served customers at a busy cafe and kept the office tidy")
        full = {k for k, v in self.found(text).items() if v == "full"}
        self.assertEqual(sorted(full), ["calculus"])

    def test_student_job_titles(self):
        f = self.found("Resident Assistant, 2024 to present\nBarista and Shift Supervisor")
        for eid in ("resident-assistant", "barista", "shift-supervisor"):
            self.assertIn(eid, f)
        self.assertIn("student-programming", self.found("Planned residence hall programming"))
        self.assertNotEqual(self.found("Planned residence hall programming").get("computer-programming"), "full")


if __name__ == "__main__":
    unittest.main()
