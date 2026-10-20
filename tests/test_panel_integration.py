"""Integration: the REAL ingest and screening modules feed the panel's ledger and synthesis.

Uses a tiny stand-in lexicon (tests/fixtures/panel/lexicon) so the test does not depend on the shipped
dictionaries, and the fictional run_basic resume, posting and reviews. Assertions are structural:
whatever the screening check scores, its JD blocks must number cleanly into J lines, every automatic
finding must point at a real screening issue, KW-001 terms must land on the posting lines that ask for
them, and the screening reviewer's keyword table must line up with the real brief.json.
Skips only when hp.ingest or hp.screen cannot be imported.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "plugins", "hiring-panel", "skills", "hiring-panel", "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from hp.panel.ledger import build_ledger, jd_blocks_from_screening  # noqa: E402
from hp.panel.synth import synthesize  # noqa: E402

try:
    from hp.ingest import doc_to_resume_md, ingest_text
    from hp.screen import make_brief, run_screening
    HAVE_PIPELINE = True
except ImportError:      # another builder's module not present yet
    HAVE_PIPELINE = False

FIXTURE = os.path.join(HERE, "fixtures", "panel", "run_basic")
LEXICON = os.path.join(HERE, "fixtures", "panel", "lexicon")
TARGET = {"role_title": "Data Analyst Intern", "role_level": "intern", "company": "Northwind Health",
          "locale": "en-US"}


@unittest.skipUnless(HAVE_PIPELINE, "hp.ingest / hp.screen not available")
class RealScreeningTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="hp-panel-int-")
        cls.run_dir = os.path.join(cls.tmp, "run")
        shutil.copytree(FIXTURE, cls.run_dir)
        work = os.path.join(cls.run_dir, "work")
        with open(os.path.join(work, "inputs", "resume.md"), encoding="utf-8") as f:
            resume = f.read()
        with open(os.path.join(work, "inputs", "jd.md"), encoding="utf-8") as f:
            cls.jd = f.read()
        doc = ingest_text(resume)
        cls.resume_md = doc_to_resume_md(doc)
        cls.screening = run_screening(doc, cls.jd, stage="student", as_of="2026-10-20", locale="en-US",
                                      data_dir=LEXICON)
        cls.brief = make_brief(cls.screening)
        with open(os.path.join(work, "screening", "before", "screening.json"), "w", encoding="utf-8") as f:
            json.dump(cls.screening, f)
        with open(os.path.join(work, "screening", "before", "brief.json"), "w", encoding="utf-8") as f:
            json.dump(cls.brief, f)
        cls.ledger = build_ledger(cls.resume_md, jd_blocks_from_screening(cls.screening), TARGET)
        with open(os.path.join(work, "inputs", "ledger.json"), "w", encoding="utf-8") as f:
            json.dump(cls.ledger, f)
        cls.result = synthesize(cls.run_dir, "parallel")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_ledger_numbers_the_real_blocks(self):
        blocks = jd_blocks_from_screening(self.screening)
        self.assertTrue(blocks)
        lines = [ln for b in blocks for ln in b["lines"] if ln.strip()]

        def joined(texts):
            return " ".join(" ".join(t.split()) for t in texts)

        # J items may be sentence-sized spans of a line; joined, they give back the lines (lossless).
        self.assertEqual(joined(j["text"] for j in self.ledger["jd_items"]), joined(lines))
        posting = [ln.strip() for ln in self.jd.splitlines() if ln.strip()]
        self.assertEqual(joined(j["text"] for j in self.ledger["jd_items"]), joined(posting),
                         "blocks must partition the posting")
        self.assertEqual([r["text"] for r in self.ledger["resume_lines"]],
                         [ln.strip() for ln in self.resume_md.splitlines() if ln.strip()])

    def test_automatic_findings_point_at_real_issues(self):
        ids = {i["id"]: i["severity"] for i in self.screening["issues"]}
        autos = [it for it in self.result["issues"] if it["from_script"]]
        self.assertTrue(autos)
        for it in self.result["issues"]:
            for e in it["evidence"]:
                if e["anchor"].startswith("A:"):
                    self.assertIn(e["anchor"][2:], ids)
        imported = {e["anchor"][2:] for it in autos for e in it["evidence"] if e["anchor"].startswith("A:")}
        for iid, sev in ids.items():
            if sev in ("critical", "high", "medium"):
                self.assertIn(iid, imported, iid)
        self.assertEqual([n["id"] for n in self.result["notes"]], [i for i, s in ids.items() if s == "info"])

    def test_missing_required_terms_land_on_their_posting_lines(self):
        kw001 = [it for it in self.result["issues"] if any(e["anchor"] == "A:KW-001" for e in it["evidence"])]
        if not any(i["id"] == "KW-001" for i in self.screening["issues"]):
            self.skipTest("this lexicon found every required term")
        self.assertEqual(len(kw001), 1)
        text = {j["id"]: j["text"].lower() for j in self.ledger["jd_items"]}
        missing = [t["term"].lower() for t in self.screening["keywords"]["required"] if not t["found"]]
        self.assertTrue(kw001[0]["jd_anchors"])
        for anchor in kw001[0]["jd_anchors"]:
            self.assertTrue(any(term in text[anchor] for term in missing), anchor)

    def test_screening_review_matches_real_brief(self):
        from hp.panel.synth import check_review
        res = check_review(self.run_dir, os.path.join(self.run_dir, "work", "reviews", "screening.json"))
        recompute = [w for w in res["warnings"] if "do not recompute" in w]
        self.assertEqual(recompute, [], "fixture keyword table drifted from the real brief.json shape")
        self.assertEqual(sorted(self.brief["keywords"][0]), sorted(["term", "importance", "found", "match_type",
                                                                      "evidence_level", "resume_wording"]))

    def test_panel_runs(self):
        self.assertEqual(self.result["panel_size"], 7)
        self.assertLessEqual(len(self.result["questions_for_candidate"]), 6)
        self.assertLessEqual(len(self.result["interview_prep"]), 6)


if __name__ == "__main__":
    unittest.main()
