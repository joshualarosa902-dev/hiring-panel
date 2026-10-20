"""hp/data: every file exists, parses, and follows its documented format (ARCHITECTURE.md 6.4)."""
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "plugins", "hiring-panel", "skills", "hiring-panel", "scripts")
sys.path.insert(0, SCRIPTS)

import hp  # noqa: E402
from hp import util  # noqa: E402

DATA = os.path.join(SCRIPTS, "hp", "data")
EXPECTED = ["VERSION", "action_verbs.txt", "buzzwords.txt", "countries.txt", "headings.json", "jd_stopwords.txt",
            "locale_norms.json", "skills.json", "stopwords_en.txt", "us_states.json", "weak_openers.txt"]


def raw(name):
    with open(os.path.join(DATA, name), "rb") as f:
        return f.read()


def items(name):
    """Non-comment, non-blank lines of a .txt list, stripped."""
    out = []
    for line in raw(name).decode("utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            out.append(s)
    return out


def regular_past(base):
    """The rule documented at the top of action_verbs.txt (no doubling)."""
    if base.endswith("e"):
        return base + "d"
    if re.search(r"[^aeiou]y$", base):
        return base[:-1] + "ied"
    return base + "ed"


class FilesTest(unittest.TestCase):
    def test_expected_files_and_nothing_stray(self):
        present = sorted(f for f in os.listdir(DATA) if not f.startswith("."))
        for name in EXPECTED:
            self.assertIn(name, present)
        stray = [f for f in present if f not in EXPECTED and f != "README.md"]
        self.assertEqual(stray, [], "unexpected files in hp/data")

    def test_utf8_no_bom_lf_trailing_newline(self):
        for name in EXPECTED:
            b = raw(name)
            self.assertFalse(b.startswith(b"\xef\xbb\xbf"), name)
            self.assertNotIn(b"\r", b, name)
            self.assertTrue(b.endswith(b"\n"), name)
            b.decode("utf-8")

    def test_json_files_parse(self):
        for name in EXPECTED:
            if name.endswith(".json"):
                self.assertIsInstance(util.read_json(os.path.join(DATA, name)), dict, name)

    def test_versions_agree(self):
        self.assertEqual(raw("VERSION").decode("utf-8"), "1.0.0\n")
        self.assertEqual(json.loads(raw("skills.json"))["version"], "1.0.0")
        self.assertEqual(json.loads(raw("headings.json"))["version"], "1.0.0")
        self.assertEqual(json.loads(raw("locale_norms.json"))["_meta"]["version"], "1.0.0")
        self.assertEqual(hp.__version__, "1.0.0")

    def test_lists_are_clean(self):
        for name in ("action_verbs.txt", "weak_openers.txt", "buzzwords.txt", "stopwords_en.txt",
                     "jd_stopwords.txt", "countries.txt"):
            lst = items(name)
            self.assertEqual(len(lst), len(set(lst)), "%s has duplicates" % name)
            for s in lst:
                self.assertNotIn("  ", s, (name, s))
                self.assertEqual(util.norm_text(s), s, (name, s))
                if name != "countries.txt":
                    self.assertEqual(s, s.lower(), (name, s))


class ActionVerbsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lines = items("action_verbs.txt")
        cls.verbs = {}
        for line in cls.lines:
            base, _, past = line.partition("|")
            cls.verbs[base] = past or None

    def test_format_and_size(self):
        for line in self.lines:
            self.assertRegex(line, r"^[a-z][a-z-]*(\|[a-z][a-z-]*)?$")
        self.assertGreaterEqual(len(self.verbs), 300)
        self.assertEqual(len(self.verbs), len(self.lines), "a base verb is listed twice")

    def test_irregular_and_doubling_pasts_are_spelled_out(self):
        for base, past in (("lead", "led"), ("build", "built"), ("write", "wrote"), ("teach", "taught"),
                           ("run", "ran"), ("oversee", "oversaw"), ("plan", "planned"), ("ship", "shipped"),
                           ("submit", "submitted"), ("debug", "debugged"), ("co-lead", "co-led")):
            self.assertEqual(self.verbs.get(base), past, base)

    def test_regular_rule_gives_real_words(self):
        for base, past in (("manage", "managed"), ("identify", "identified"), ("survey", "surveyed"),
                           ("analyze", "analyzed"), ("deploy", "deployed")):
            self.assertIsNone(self.verbs[base], base)
            self.assertEqual(regular_past(base), past)

    def test_no_weak_openers(self):
        for weak in ("help", "assist", "work", "participate", "handle", "attend", "use"):
            self.assertNotIn(weak, self.verbs)


class WordListsTest(unittest.TestCase):
    def test_weak_openers_cover_the_spec(self):
        lst = set(items("weak_openers.txt"))
        for phrase in ("responsible for", "duties included", "helped", "helped with", "assisted", "assisted with",
                       "assisted in", "worked on", "participated in", "involved in", "tasked with", "in charge of",
                       "handled"):
            self.assertIn(phrase, lst)

    def test_buzzwords(self):
        lst = items("buzzwords.txt")
        self.assertGreaterEqual(len(lst), 70)
        self.assertLessEqual(len(lst), 120)
        for b in ("results-driven", "team player", "synergy", "think outside the box", "detail-oriented"):
            self.assertIn(b, lst)

    def test_buzzwords_never_flag_action_verbs(self):
        """'Leveraged Python to ...' is a fine bullet; a buzzword list must not flag verb openers."""
        verbs = set()
        for line in items("action_verbs.txt"):
            base, _, past = line.partition("|")
            verbs.update([base, past or regular_past(base)])
        for b in items("buzzwords.txt"):
            self.assertNotIn(b, verbs, b)

    def test_stopwords(self):
        sw = set(items("stopwords_en.txt"))
        self.assertGreaterEqual(len(sw), 250)
        for w in ("the", "and", "of", "to", "a", "in", "is", "for", "with", "you", "don't"):
            self.assertIn(w, sw)

    def test_stopword_share_separates_english(self):
        """ARCHITECTURE 6: < 30% of tokens in stopwords_en suggests a non-English resume."""
        sw = set(items("stopwords_en.txt"))

        def share(text):
            toks = re.findall(r"[a-zà-ÿ']+", text.lower())
            return sum(t in sw for t in toks) / float(len(toks))
        english = ("I am a third-year student who is looking for an internship where I can use what I have "
                   "learned in my classes and in the lab to help a team that is building something new.")
        spanish = ("Soy estudiante de tercer año y busco unas prácticas donde pueda aplicar lo que he aprendido "
                   "en mis clases y en el laboratorio para ayudar a un equipo que construye algo nuevo.")
        self.assertGreater(share(english), 0.30)
        self.assertLess(share(spanish), 0.30)

    def test_jd_stopwords(self):
        lst = set(items("jd_stopwords.txt"))
        for w in ("ability", "strong", "excellent", "candidate", "preferred", "required", "experience", "skills"):
            self.assertIn(w, lst)

    def test_jd_stopwords_are_never_skill_names(self):
        skills = json.loads(raw("skills.json"))["entries"]
        names = set()
        for e in skills:
            for f in [e["canonical"]] + e["aliases"] + e["acronyms"]:
                names.add(f.casefold())
        clash = sorted(w for w in items("jd_stopwords.txt") if w in names)
        self.assertEqual(clash, [])


class GeoTest(unittest.TestCase):
    def test_us_states(self):
        st = json.loads(raw("us_states.json"))
        self.assertEqual(len(st), 56)                      # 50 states + DC + 5 inhabited territories
        for code, name in st.items():
            self.assertRegex(code, r"^[A-Z]{2}$")
            self.assertTrue(name and name == name.strip())
        self.assertEqual(st["TX"], "Texas")
        self.assertEqual(st["DC"], "District of Columbia")
        for t in ("PR", "GU", "VI", "AS", "MP"):
            self.assertIn(t, st)
        self.assertEqual(len(set(st.values())), 56)

    def test_countries(self):
        c = items("countries.txt")
        self.assertGreaterEqual(len(c), 190)
        for name in ("United States", "USA", "United Kingdom", "UK", "Canada", "Germany", "India", "Australia",
                     "New Zealand", "Ireland", "France", "Spain", "Switzerland", "Austria", "Mexico", "Nigeria",
                     "Côte d'Ivoire", "Türkiye"):
            self.assertIn(name, c)
        self.assertNotIn("Jersey", c)                      # would fire on "New Jersey"


if __name__ == "__main__":
    unittest.main()
