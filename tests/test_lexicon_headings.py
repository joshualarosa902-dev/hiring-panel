"""headings.json: every resume section (ATS spec 7) and JD block kind (ATS spec 11) is covered,
synonyms are unambiguous, and every synonym can actually be detected as a heading."""
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
SECTIONS = ["contact", "summary", "experience", "education", "skills", "projects", "certifications",
            "leadership_activities", "volunteer", "awards", "publications", "coursework", "languages",
            "interests", "references", "other"]
JD_KINDS = ["required", "preferred", "responsibility", "boilerplate"]
CORE_WORDS = ["experience", "education", "skills", "projects", "certifications", "leadership", "activities",
              "volunteer", "awards", "honors", "publications", "coursework", "languages", "interests", "summary",
              "profile", "objective"]


def load():
    with open(os.path.join(DATA, "headings.json"), encoding="utf-8") as f:
        return json.load(f)


def norm_drop(s):
    """ATS spec 7 normalization, punctuation dropped: "what you'll need" -> "what youll need"."""
    s = s.casefold().replace("&", " and ")
    s = re.sub(r"[^\w ]+", "", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_space(s):
    """Same, punctuation turned into spaces: "must-have" -> "must have"."""
    s = s.casefold().replace("&", " and ")
    s = re.sub(r"[^\w ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


class HeadingsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.h = load()

    def test_shape(self):
        self.assertEqual(sorted(self.h["resume"]), sorted(SECTIONS))
        self.assertEqual(sorted(self.h["jd"]), sorted(JD_KINDS))

    def test_lists_are_clean(self):
        for ns in ("resume", "jd"):
            for key, lst in self.h[ns].items():
                self.assertGreater(len(lst), 0, key)
                self.assertEqual(len(lst), len(set(lst)), (ns, key))
                for s in lst:
                    self.assertEqual(s, s.strip().lower(), (ns, key, s))
                    self.assertNotIn("  ", s)

    def test_every_synonym_passes_the_heading_rule(self):
        """ATS spec 7: a heading candidate has 1-6 words and at most 45 characters."""
        for ns in ("resume", "jd"):
            for key, lst in self.h[ns].items():
                for s in lst:
                    self.assertLessEqual(len(s.split()), 6, s)
                    self.assertLessEqual(len(s), 45, s)
                    self.assertNotIn("@", s)

    def test_no_synonym_points_at_two_sections(self):
        for ns in ("resume", "jd"):
            for norm in (norm_drop, norm_space):
                owner = {}
                for key, lst in self.h[ns].items():
                    for s in lst:
                        k = norm(s)
                        self.assertTrue(k, s)
                        if k in owner:
                            self.assertEqual(owner[k], key, "%r is in %s and %s" % (s, owner[k], key))
                        owner[k] = key

    def test_resume_standard_names(self):
        r = self.h["resume"]
        expect = {
            "summary": ["summary", "professional summary", "profile", "objective"],
            "experience": ["experience", "work experience", "professional experience", "relevant experience",
                           "employment history", "internships", "research experience", "clinical experience"],
            "education": ["education", "academic background"],
            "skills": ["skills", "technical skills", "core competencies"],
            "projects": ["projects", "academic projects", "capstone project"],
            "certifications": ["certifications", "licenses and certifications"],
            "leadership_activities": ["leadership", "activities", "leadership experience", "campus involvement"],
            "volunteer": ["volunteer experience", "community service"],
            "awards": ["awards", "honors", "honors and awards"],
            "publications": ["publications", "presentations"],
            "coursework": ["relevant coursework", "coursework"],
            "languages": ["languages"],
            "interests": ["interests", "hobbies"],
            "references": ["references", "references available upon request", "referees"],
            "other": ["additional information"],
            "contact": ["contact information"],
        }
        for sec, names in expect.items():
            for n in names:
                self.assertIn(n, r[sec], (sec, n))

    def test_jd_lists_cover_the_ats_spec(self):
        j = self.h["jd"]
        spec = {
            "required": ["requirements", "qualifications", "minimum qualifications", "basic qualifications",
                         "required qualifications", "must have", "what you'll need", "what we're looking for",
                         "who you are", "you have", "you bring", "skills and experience"],
            "preferred": ["preferred qualifications", "nice to have", "bonus", "pluses", "desired", "extra credit"],
            "responsibility": ["responsibilities", "what you'll do", "the role", "your impact", "day to day",
                               "key duties", "in this role"],
            "boilerplate": ["about us", "who we are", "benefits", "perks", "compensation", "salary", "pay range",
                            "equal opportunity", "eeo", "accommodation", "privacy", "our values", "why join",
                            "culture"],
        }
        for kind, names in spec.items():
            for n in names:
                self.assertIn(n, j[kind], (kind, n))

    def test_core_words_map(self):
        cw = self.h["resume_core_words"]
        self.assertEqual(sorted(cw), sorted(CORE_WORDS))
        for word, sec in cw.items():
            self.assertIn(sec, SECTIONS, word)

    def test_screen_loader_accepts_it(self):
        """The screening loader keys headings with its own normalizer; nothing may collide there."""
        try:
            from hp.screen.lexicon import norm_heading
        except ImportError:  # pragma: no cover - screen module not built yet
            self.skipTest("hp.screen not available")
        owner = {}
        for key, lst in self.h["resume"].items():
            for s in lst:
                k = norm_heading(s)
                self.assertEqual(owner.setdefault(k, key), key, s)


if __name__ == "__main__":
    unittest.main()
