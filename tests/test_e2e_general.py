"""End-to-end: a General review (no job posting), from the PDF version of the fictional resume, with the
panel played in one chat ("lite" mode) and the built-in PDF engine.

Checks the no-posting rules (keyword match left empty on purpose, no keyword or requirement findings,
no posting mirrored), the approximate-independence disclosure for single-chat modes, the lane-based
status fallback (no meta.addressed), a skipped question batch, and byte-identical JSON across runs.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "fixtures", "e2e"))
import support as S  # noqa: E402

sys.path.insert(0, S.SCRIPTS)


def general_pipeline(base, environ, rec):
    cwd = base
    rec["init"] = S.hp(S.init_args(S.fixture("resume.pdf"), os.path.join(base, "runs")), cwd, environ)
    run = rec["init"].data["run"]
    S.copy_reviews(S.REVIEWS_GENERAL, run)
    rec["validate"] = [S.hp(["validate", run, os.path.join(run, "work", "reviews", r + ".json")], cwd, environ)
                       for r in S.REVIEWER_IDS]
    rec["validate_posting_review"] = S.hp(["validate", run, os.path.join(S.REVIEWS, "screening.json")], cwd, environ)
    rec["synthesize"] = S.hp(["synthesize", run, "--mode", "lite"], cwd, environ)
    rec["report_panel"] = S.hp(["report", run], cwd, environ)
    rec["panel_report"] = S.load(os.path.join(run, "work", "report.json"))
    S.place(S.fixture("answers_skipped.json"), run, "answers.json")
    S.place(S.fixture("resume_general.json"), run, os.path.join("rewrite", "resume.json"))
    rec["truth"] = S.hp(["truth", run], cwd, environ)
    rec["render"] = S.hp(["render", run], cwd, environ)
    rec["report_final"] = S.hp(["report", run], cwd, environ)
    return run


class GeneralReviewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="hp-e2e-general-")
        cls.A, cls.B = {}, {}
        environ = S.env(pdf_engines="builtin")
        os.makedirs(os.path.join(cls.tmp, "a"))
        os.makedirs(os.path.join(cls.tmp, "b"))
        cls.run_a = general_pipeline(os.path.join(cls.tmp, "a"), environ, cls.A)
        cls.run_b = general_pipeline(os.path.join(cls.tmp, "b"), environ, cls.B)
        cls.work = os.path.join(cls.run_a, "work")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_exit_codes(self):
        for step in ("init", "synthesize", "report_panel", "truth", "render", "report_final"):
            self.assertEqual(self.A[step].code, 0, "%s: %r" % (step, self.A[step]))
        self.assertTrue(all(v.code == 0 for v in self.A["validate"]), self.A["validate"])

    def test_init_general_review(self):
        d = self.A["init"].data
        self.assertTrue(d["jd"]["general_review"])
        self.assertEqual(d["jd"]["chars"], 0)
        self.assertEqual(d["resume"]["format"], "pdf")
        self.assertEqual(d["ledger"]["jd_items"], 0)
        self.assertEqual(d["ledger"]["resume_lines"], 32)
        self.assertIsNone(d["screening"]["keyword_match"]["value"])
        self.assertEqual(d["screening"]["keyword_match"]["band"], "No job description provided")
        self.assertEqual(S.read(os.path.join(self.work, "inputs", "jd.md"), "rb"), b"")
        state = S.load(os.path.join(self.work, "state.json"))
        self.assertTrue(state["general_review"])
        self.assertEqual(state["jd_source"], "none")
        self.assertIsNone(state["company"])
        self.assertEqual(os.path.basename(self.run_a), "2026-10-20-1430-marketing-analytics-intern")

    def test_posting_findings_rejected_in_general_review(self):
        d = self.A["validate_posting_review"]
        self.assertEqual(d.code, 1)
        self.assertTrue(any("KEYWORD_GAP" in e or "J1" in e or "J" in e for e in d.data["errors"]), d.data["errors"])

    def test_lite_mode_discloses_approximate_independence(self):
        for r in (self.A["panel_report"], S.load(os.path.join(self.work, "report.json"))):
            self.assertEqual(r["mode"], "lite")
            self.assertIn("less independent", r["mode_note"])
            self.assertIn("one chat", r["verdict_strip"]["mode_label"].lower())
        for name in ("Hiring_Panel_Report.md", "Hiring_Panel_Report.html"):
            self.assertIn("less independent", S.read(os.path.join(self.run_a, name)))

    def test_report_general_review(self):
        r = S.load(os.path.join(self.work, "report.json"))
        self.assertTrue(r["general_review"])
        self.assertIsNone(r["target"]["company"])
        self.assertEqual(r["keyword_gaps"], [])
        self.assertIsNone(r["screening"]["before"]["keyword_match"]["value"])
        self.assertEqual(r["screening"]["before"]["required"]["total"], 0)
        synth = S.load(os.path.join(self.work, "synthesis.json"))
        cats = set(c for i in synth["issues"] for c in i["categories"])
        self.assertFalse(cats & {"KEYWORD_GAP", "REQUIREMENT_UNPROVEN"}, cats)
        md = S.read(os.path.join(self.run_a, "Hiring_Panel_Report.md"))
        self.assertIn("no posting provided", md.lower())
        self.assertIn("No job posting, so no keyword check", md)
        self.assertTrue(any("No job posting was provided" in x for x in r["limitations"]))
        from hp.report_build import validate_report
        self.assertEqual(validate_report(r), [])
        self.assertEqual(validate_report(self.A["panel_report"]), [])

    def test_lane_statuses_without_meta_addressed(self):
        r = S.load(os.path.join(self.work, "report.json"))
        synth = S.load(os.path.join(self.work, "synthesis.json"))
        lanes = dict((i["id"], i["lane"]) for i in synth["issues"])
        expected = {"fixed_by_rewrite": "fixed", "needs_your_input": "needs_you", "real_gap": "gap"}
        cut_line = [w for w in r["weaknesses"] if "300%" in w["title"]]
        self.assertEqual(len(cut_line), 1)
        for w in r["weaknesses"]:
            if w is cut_line[0]:
                # every line it quotes (R14) was cut and its words are gone from the new resume
                self.assertEqual(w["status"], "fixed")
                self.assertIn("cut", w["fix"])
                continue
            self.assertEqual(w["status"], expected[lanes[w["issue_id"]]], w)
        # "Needs you" lists exactly the weaknesses still waiting on the student
        waiting = [w["title"][:60] for w in r["weaknesses"] if w["status"] == "needs_you"]
        self.assertTrue(waiting)
        self.assertEqual(sorted(n["where"] for n in r["needs_you"]), sorted(waiting))
        pinned = [p for p in r["pinned_integrity"] if "300%" in p["title"]]
        self.assertIn("cut", pinned[0]["fix"])

    def test_truth_and_files(self):
        r = S.load(os.path.join(self.work, "report.json"))
        self.assertEqual(r["stage"], "final")
        self.assertEqual(r["truth_check"]["ran"], "script")
        self.assertTrue(r["truth_check"]["passed"])
        self.assertEqual(r["truth_check"]["provenance"], "not_run")    # nothing was flagged for an audit
        self.assertEqual(self.A["render"].data["pdf_engine"], "builtin")
        md = S.read(os.path.join(self.run_a, "Riley_Castellano_Resume.md"))
        jd_words = ("dashboards", "Tableau", "A/B testing", "Northwind")
        for w in jd_words:
            self.assertNotIn(w, md)
        gate = S.load(os.path.join(self.work, "gate.json"))
        self.assertTrue(gate["passed"], gate["failures"])
        self.assertEqual(gate["keyword_match"]["before"], None)

    def test_byte_identical_across_runs(self):
        files = S.deterministic_files(self.run_a)
        self.assertEqual(files, S.deterministic_files(self.run_b))
        for rel in files:
            self.assertEqual(S.read(os.path.join(self.run_a, rel), "rb"), S.read(os.path.join(self.run_b, rel), "rb"), rel)

    def test_builtin_pdf_is_deterministic_too(self):
        for name in ("Riley_Castellano_Resume.pdf", "Hiring_Panel_Report.pdf"):
            self.assertEqual(S.read(os.path.join(self.run_a, name), "rb"), S.read(os.path.join(self.run_b, name), "rb"), name)


if __name__ == "__main__":
    unittest.main()
