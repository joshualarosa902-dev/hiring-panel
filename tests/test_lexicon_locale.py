"""locale_norms.json (ARCHITECTURE.md 6.5): every locale, every required key, valid values, sources."""
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "plugins", "hiring-panel", "skills", "hiring-panel", "scripts")
sys.path.insert(0, SCRIPTS)

DATA = os.path.join(SCRIPTS, "hp", "data")
LOCALES = ["en-US", "en-CA", "en-GB", "en-IE", "en-AU", "en-NZ", "en-IN", "de-DE", "de-AT", "de-CH", "fr-FR",
           "es-ES", "default"]
REQUIRED = ["paper", "pages_student", "pages_experienced", "word", "photo", "dob", "gpa", "notes"]
EXTRA = ["name", "local_word", "personal_details", "gpa_note", "confidence", "uncertain", "sources"]
PRESENCE = ("omit", "optional", "customary")
GPA = ("optional_3.0_plus", "optional_if_strong", "degree_classification", "cgpa_or_percentage",
       "local_grade_scale")


def load():
    with open(os.path.join(DATA, "locale_norms.json"), encoding="utf-8") as f:
        return json.load(f)


def all_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            for s in all_strings(v):
                yield s
    elif isinstance(obj, list):
        for v in obj:
            for s in all_strings(v):
                yield s


class LocaleNormsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.n = load()

    def test_locales_present(self):
        self.assertEqual(sorted(k for k in self.n if not k.startswith("_")), sorted(LOCALES))
        self.assertIn("_sources", self.n)
        self.assertIn("_meta", self.n)

    def test_required_keys_and_types(self):
        for loc in LOCALES:
            e = self.n[loc]
            self.assertEqual(sorted(e), sorted(REQUIRED + EXTRA), loc)
            self.assertIn(e["paper"], ("letter", "a4"), loc)
            for k in ("pages_student", "pages_experienced"):
                self.assertIsInstance(e[k], int, (loc, k))
                self.assertTrue(1 <= e[k] <= 3, (loc, k))
            self.assertLessEqual(e["pages_student"], e["pages_experienced"], loc)
            self.assertIn(e["word"], ("resume", "CV"), loc)
            for k in ("photo", "dob", "personal_details"):
                self.assertIn(e[k], PRESENCE, (loc, k))
            self.assertIn(e["gpa"], GPA, loc)
            self.assertIn(e["confidence"], ("high", "medium", "low"), loc)
            self.assertTrue(e["notes"] and all(isinstance(s, str) and s for s in e["notes"]), loc)
            for k in e["uncertain"]:
                self.assertIn(k, REQUIRED + EXTRA, (loc, k))

    def test_contract_values(self):
        us = self.n["en-US"]
        self.assertEqual((us["paper"], us["pages_student"], us["pages_experienced"], us["word"], us["photo"],
                          us["dob"], us["gpa"]), ("letter", 1, 2, "resume", "omit", "omit", "optional_3.0_plus"))
        gb = self.n["en-GB"]
        self.assertEqual((gb["paper"], gb["word"], gb["gpa"]), ("a4", "CV", "degree_classification"))
        for loc in ("de-DE", "de-AT", "de-CH"):
            self.assertEqual((self.n[loc]["photo"], self.n[loc]["dob"]), ("customary", "customary"), loc)

    def test_letter_only_in_north_america(self):
        for loc in LOCALES:
            expect = "letter" if loc in ("en-US", "en-CA") else "a4"
            self.assertEqual(self.n[loc]["paper"], expect, loc)

    def test_sources_resolve(self):
        src = self.n["_sources"]
        for loc in LOCALES:
            for key in self.n[loc]["sources"]:
                self.assertIn(key, src, (loc, key))
        for key, s in src.items():
            if key.startswith("_"):
                continue
            self.assertTrue(s["title"] and s["supports"] and s["seen_via"], key)
            self.assertTrue(s["url"].startswith("https://"), key)
        self.assertTrue(src["_unverified"])

    def test_every_locale_but_default_cites_something(self):
        for loc in LOCALES:
            if loc != "default":
                self.assertTrue(self.n[loc]["sources"], loc)

    def test_house_voice(self):
        """No em dashes, no 'ATS score', no promises (ARCHITECTURE.md 16)."""
        for s in all_strings(self.n):
            self.assertNotIn("—", s)
            self.assertNotRegex(s.lower(), r"ats score|guarantee")

    def test_renderer_and_screen_can_read_it(self):
        """Both consumers key on paper and pages_*; locale fallback must land on a real entry."""
        try:
            from hp.screen.lexicon import load_lexicon
        except ImportError:  # pragma: no cover
            self.skipTest("hp.screen not available")
        lex = load_lexicon()
        self.assertEqual(lex.norms_for("en-US")["paper"], "letter")
        self.assertEqual(lex.norms_for("de-DE")["photo"], "customary")
        self.assertIn(lex.norms_for("pt-BR")["paper"], ("letter", "a4"))


class OtherDataVoiceTest(unittest.TestCase):
    def test_no_em_dashes_in_data(self):
        for name in os.listdir(DATA):
            if name.startswith("."):
                continue
            with open(os.path.join(DATA, name), encoding="utf-8") as f:
                text = f.read()
            self.assertNotIn("—", text, name)
            self.assertIsNone(re.search(r"(?i)ats score", text), name)


if __name__ == "__main__":
    unittest.main()
