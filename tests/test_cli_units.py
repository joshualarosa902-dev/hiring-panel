"""Unit tests for the integration modules: hp.gate, hp.run, hp.report_build and hp.py's helpers.
Also checks that every integration file parses as Python 3.8 and stays standard-library only."""
import ast
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

from hp import gate, report_build  # noqa: E402
from hp import run as hprun  # noqa: E402

INTEGRATION_FILES = [os.path.join(S.SCRIPTS, "hp.py")] + [
    os.path.join(S.SCRIPTS, "hp", n) for n in ("run.py", "gate.py", "report_build.py")]


class GateMetricsTest(unittest.TestCase):
    def test_words_ignore_markdown_and_bullets(self):
        md = "# Riley Castellano\n\n## Education\n**Lakeshore State University** \\| Columbus, OH  \n- Built *pivot* tables"
        self.assertEqual(gate.md_words(md), ["riley", "castellano", "education", "lakeshore", "state", "university",
                                             "columbus", "oh", "built", "pivot", "tables"])
        self.assertEqual(gate.words("• Jan 2025 – May 2025"), ["jan", "2025", "may", "2025"])

    def test_recovery_counts_repeats(self):
        src = ["a", "b", "b", "c"]
        self.assertEqual(gate.recovery(src, ["a", "b", "c"]), 0.75)
        self.assertEqual(gate.recovery(src, ["c", "b", "a", "b"]), 1.0)
        self.assertEqual(gate.recovery([], ["x"]), 1.0)

    def test_order_match(self):
        src = list("abcdefghij")
        self.assertEqual(gate.order_match(src, src), 1.0)
        moved = list("abcdeghijf")
        self.assertAlmostEqual(gate.order_match(src, moved), 0.9)
        self.assertLess(gate.order_match(src, list(reversed(src))), 0.2)

    def test_merged_tokens(self):
        src = gate.words("Lakeshore State University Columbus OH Statistics Expected May 2027")
        out = gate.words("Lakeshore State UniversityColumbus OH StatisticsExpected May 2027")
        self.assertEqual(gate.merged_tokens(src, out), ["universitycolumbus", "statisticsexpected"])
        self.assertEqual(gate.merged_tokens(src, src), [])

    def test_keyword_note(self):
        before = {"scores": {"keyword_match": {"value": 70}}}
        self.assertIn("held", gate.keyword_note(before, {"keyword_match": 75})["note"])
        self.assertIn("went down", gate.keyword_note(before, {"keyword_match": 60})["note"])
        self.assertIn("not compared", gate.keyword_note({"scores": {}}, {"keyword_match": 60})["note"])


class RunHelpersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hp-run-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_git_detection_walks_up(self):
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(os.path.join(repo, ".git"))
        self.assertTrue(hprun.in_git_repo(os.path.join(repo, "a", "b", "not-yet")))
        self.assertFalse(hprun.in_git_repo(os.path.join(self.tmp, "elsewhere")))

    def test_resolve_run(self):
        run = os.path.join(self.tmp, "r")
        os.makedirs(os.path.join(run, "work"))
        with self.assertRaises(hprun.RunError):
            hprun.resolve_run(run)
        with open(os.path.join(run, "work", "state.json"), "w") as f:
            f.write("{}")
        self.assertEqual(hprun.resolve_run(run), run)
        self.assertEqual(hprun.resolve_run(os.path.join(run, "work")), run)
        self.assertEqual(hprun.resolve_run(os.path.join(run, "work", "state.json")), run)
        for bad in ("", None, os.path.join(self.tmp, "missing")):
            with self.assertRaises(hprun.RunError):
                hprun.resolve_run(bad)

    def test_load_state_rejects_garbage(self):
        run = os.path.join(self.tmp, "r")
        os.makedirs(os.path.join(run, "work"))
        with open(os.path.join(run, "work", "state.json"), "w") as f:
            f.write("[1, 2")
        with self.assertRaises(hprun.RunError):
            hprun.load_state(run)
        with open(os.path.join(run, "work", "state.json"), "w") as f:
            f.write('{"steps": "x", "ledger_overrides": 5}')
        st = hprun.load_state(run)
        self.assertEqual((st["steps"], st["ledger_overrides"]), ({}, []))

    def test_new_run_dir_names(self):
        os.environ["HP_NOW"] = "2026-10-20-0900"
        try:
            a = hprun.new_run_dir(self.tmp, "Northwind Foods, Inc.", "Marketing Analytics Intern (Summer)")
            b = hprun.new_run_dir(self.tmp, None, "Résumé Reviewer")
        finally:
            os.environ.pop("HP_NOW", None)
        self.assertEqual(os.path.basename(a), "2026-10-20-0900-northwind-foods-inc-marketing-analytics-intern-summer")
        self.assertEqual(os.path.basename(b), "2026-10-20-0900-resume-reviewer")
        self.assertTrue(os.path.isfile(os.path.join(a, ".gitignore")))


class ReportHelpersTest(unittest.TestCase):
    def test_clip_and_sentences(self):
        self.assertEqual(report_build.clip("one two three four", 9), "one two…")
        self.assertEqual(report_build.first_sentences("First one. Second one is longer. Third.", 34),
                         "First one. Second one is longer.")

    def test_mask_covers_international_numbers(self):
        out = report_build._mask({"a": ["Call +44 20 7946 0958 or mail sam.lee@example.com"]})
        self.assertNotIn("7946", out["a"][0])
        self.assertNotIn("sam.lee@example.com", out["a"][0])
        self.assertIn("***-***-0958", out["a"][0])

    def test_screening_side_labels(self):
        base = {"scores": {"overall": {"value": 70, "band": "Close, fix the top items"},
                           "parse_safety": {"value": 95, "band": "Clean"},
                           "keyword_match": {"value": 50, "band": "Partial match"},
                           "content_signals": {"value": 80, "band": "Solid"}}}
        req = dict(base, keywords={"status": "checked", "coverage": {
            "basis": "required_preferred", "required_found": 3, "required_total": 5, "required_listed_only": 1,
            "basis_found": 3, "basis_total": 5, "basis_listed_only": 1}})
        allt = dict(base, keywords={"status": "checked", "coverage": {
            "basis": "all_terms", "required_found": 0, "required_total": 0, "required_listed_only": 0,
            "basis_found": 6, "basis_total": 9, "basis_listed_only": 2}})
        nojd = dict(base, keywords={"status": "no_jd", "coverage": {}})
        self.assertEqual(report_build.screening_side(req)["required"],
                         {"found": 3, "total": 5, "listed_only": 1, "label": "Required terms"})
        self.assertEqual(report_build.screening_side(allt)["required"],
                         {"found": 6, "total": 9, "listed_only": 2, "label": "Job terms"})
        self.assertEqual(report_build.screening_side(nojd)["required"]["total"], 0)
        self.assertEqual(report_build.screening_side(req)["overall"], 70)

    def test_question_matching_is_conservative(self):
        answered = {"Q4": {"question": "Which part of the bike share survey did you do yourself?"}}
        self.assertTrue(report_build._question_answered("Which part of the bike share survey was yours?", answered))
        self.assertFalse(report_build._question_answered("What did you do with SQL in your class projects?", answered))

    def test_build_report_needs_synthesis(self):
        tmp = tempfile.mkdtemp(prefix="hp-rb-")
        try:
            run = os.path.join(tmp, "r")
            os.makedirs(os.path.join(run, "work"))
            with open(os.path.join(run, "work", "state.json"), "w") as f:
                json.dump(hprun.new_state("2026-10-20", "student", "intern", "en-US", "en", "Analyst", None, "none",
                                          True, {}), f)
            with self.assertRaises(report_build.ReportError):
                report_build.build_report(run)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class ReportFromPanelFixtureTest(unittest.TestCase):
    """build_report on the panel builder's run (different candidate, a pinned 300% claim, a header-only
    email): panel stage, schema-valid, numbers copied from the scripts, contact masked."""

    def test_panel_stage_report(self):
        from hp.panel.synth import synthesize
        tmp = tempfile.mkdtemp(prefix="hp-rb-panel-")
        try:
            run = os.path.join(tmp, "run")
            shutil.copytree(os.path.join(HERE, "fixtures", "panel", "run_basic"), run)
            state = hprun.new_state("2026-10-20", "student", "intern", "en-US", "en", "Data Analyst Intern",
                                    "Fictional Analytics Co", "pasted", False, {})
            with open(os.path.join(run, "work", "state.json"), "w") as f:
                json.dump(state, f)
            synth = synthesize(run, mode="sequential")
            notes = []
            report = report_build.build_report(run, notes=notes)
            self.assertEqual(report_build.validate_report(report), [])
            self.assertEqual(report["stage"], "panel")
            self.assertEqual(report["mode"], "sequential")
            self.assertIn("less independent", report["mode_note"])
            self.assertEqual([w["issue_id"] for w in report["weaknesses"]], [i["id"] for i in synth["issues"]])
            self.assertTrue(all(w["status"] == "open" for w in report["weaknesses"]))
            self.assertEqual(len(report["pinned_integrity"]), len(synth["pinned_integrity"]))
            v = synth["panel_vote"]
            self.assertEqual(report["verdict_strip"]["vote_label"],
                             "%d of %d would move you forward" % (v["advance"], v["total"]))
            self.assertLessEqual(len(report["disagreements"]), 2)
            self.assertEqual(report["truth_check"]["ran"], "not_run")
            text = json.dumps(report)
            self.assertNotIn("@example.com", text.replace("***@", ""))
            self.assertEqual(report, report_build.build_report(run))        # deterministic
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class StrongResumeAndFirstImpressionTest(unittest.TestCase):
    """report.json strong_resume, closest_to_reject, verdict_strip.strong_line and first_impression
    (ARCHITECTURE.md sections 17.4 and 17.5), built on the panel builder's fictional run."""

    def setUp(self):
        from hp.panel.synth import synthesize
        self.tmp = tempfile.mkdtemp(prefix="hp-rb-strong-")
        self.run = os.path.join(self.tmp, "run")
        shutil.copytree(os.path.join(HERE, "fixtures", "panel", "run_basic"), self.run)
        state = hprun.new_state("2026-10-20", "student", "intern", "en-US", "en", "Data Analyst Intern",
                                "Fictional Analytics Co", "pasted", False, {})
        with open(os.path.join(self.run, "work", "state.json"), "w") as f:
            json.dump(state, f)
        self.synth = synthesize(self.run, mode="parallel")
        self.synth_path = os.path.join(self.run, "work", "synthesis.json")
        self.recruiter_path = os.path.join(self.run, "work", "reviews", "recruiter.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_synth(self, data):
        with open(self.synth_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def strong_synth(self, advance=6, worst="moderate", pinned=False):
        """A copy of the synthesis that a strong resume would get: `advance` yes votes, no issue worse
        than `worst`, the skeptic still at lean_no with a top issue."""
        d = json.loads(json.dumps(self.synth))
        d["panel_vote"] = {"advance": advance, "unsure": 0, "total": 7}
        for it in d["issues"]:
            if it["severity"] in ("critical", "major"):
                it["severity"] = worst
        d["pinned_integrity"] = [d["issues"][0]["id"]] if pinned else []
        return d

    def test_weak_panel_is_not_strong(self):
        report = report_build.build_report(self.run)
        self.assertEqual(report_build.validate_report(report), [])
        self.assertIs(report["strong_resume"], False)
        self.assertEqual(report["verdict_strip"]["strong_line"], "")
        c = report["closest_to_reject"]
        self.assertEqual((c["reviewer"], c["name"], c["verdict"]), ("skeptic", "Skeptic", "strong_no"))
        self.assertEqual(c["issue_id"], self.synth["closest_to_reject"]["issue_id"])
        self.assertEqual(c["severity"], [i["severity"] for i in self.synth["issues"] if i["id"] == c["issue_id"]][0])
        self.assertEqual(c["reason"], self.synth["closest_to_reject"]["reason"])

    def test_strong_resume_line(self):
        d = self.strong_synth(worst="minor")
        cid = d["closest_to_reject"]["issue_id"]
        title = [i["title"] for i in d["issues"] if i["id"] == cid][0]
        self.write_synth(d)
        report = report_build.build_report(self.run)
        self.assertEqual(report_build.validate_report(report), [])
        self.assertIs(report["strong_resume"], True)
        self.assertEqual(report["closest_to_reject"]["severity"], "minor")
        self.assertEqual(report["verdict_strip"]["strong_line"],
                         "Strong resume. The Skeptic came closest to saying no: %s. It still held because that is a "
                         "minor issue, not a critical or major one." % title.rstrip("."))
        self.assertEqual(report, report_build.build_report(self.run))          # deterministic

    def test_strong_without_an_issue_uses_the_take(self):
        d = self.strong_synth()
        d["closest_to_reject"] = {"reviewer": "teammate", "verdict": "lean_yes", "issue_id": None,
                                  "reason": "Ready to help next sprint."}
        self.write_synth(d)
        report = report_build.build_report(self.run)
        self.assertEqual(report["verdict_strip"]["strong_line"],
                         "Strong resume. The Future Teammate came closest to saying no: Ready to help next sprint. "
                         "It still held because no reviewer found a critical or major issue.")

    def test_never_strong_otherwise(self):
        for kwargs in ({"advance": 4}, {"worst": "major"}, {"pinned": True}):
            self.write_synth(self.strong_synth(**kwargs))
            report = report_build.build_report(self.run)
            self.assertIs(report["strong_resume"], False, kwargs)
            self.assertEqual(report["verdict_strip"]["strong_line"], "", kwargs)
        d = self.strong_synth()
        d["panel_vote"] = {"advance": True, "unsure": 0, "total": 7}           # garbage is never strong
        self.write_synth(d)
        self.assertIs(report_build.build_report(self.run)["strong_resume"], False)

    def test_old_synthesis_without_the_field_and_empty_panel(self):
        d = json.loads(json.dumps(self.synth))
        expected = d.pop("closest_to_reject")
        self.write_synth(d)
        c = report_build.build_report(self.run)["closest_to_reject"]
        self.assertEqual((c["reviewer"], c["issue_id"], c["reason"]),
                         (expected["reviewer"], expected["issue_id"], expected["reason"]))
        d["closest_to_reject"] = None
        d["reviewers"], d["panel_vote"] = [], {"advance": 0, "unsure": 0, "total": 0}
        self.write_synth(d)
        report = report_build.build_report(self.run)
        self.assertIsNone(report["closest_to_reject"])
        self.assertIs(report["strong_resume"], False)
        self.assertIsNone(report["first_impression"])         # no accepted recruiter review
        self.assertEqual(report_build.validate_report(report), [])

    def set_takeaway(self, value):
        with open(self.recruiter_path, encoding="utf-8") as f:
            review = json.load(f)
        if value is None:
            review["lens_data"].pop("seven_second_takeaway", None)
        else:
            review["lens_data"]["seven_second_takeaway"] = value
        with open(self.recruiter_path, "w", encoding="utf-8") as f:
            json.dump(review, f)

    def test_first_impression_present(self):
        with open(self.recruiter_path, encoding="utf-8") as f:
            takeaway = json.load(f)["lens_data"]["seven_second_takeaway"]
        report = report_build.build_report(self.run)
        self.assertEqual(report["first_impression"], takeaway)
        self.set_takeaway('"Analytics student,\u200b marketing intern."')
        self.assertEqual(report_build.build_report(self.run)["first_impression"], "Analytics student, marketing intern.")

    def test_first_impression_absent(self):
        for value in (None, "", "   ", 42):
            self.set_takeaway(value)
            report = report_build.build_report(self.run)
            self.assertIsNone(report["first_impression"], value)
            self.assertEqual(report_build.validate_report(report), [])
        os.remove(self.recruiter_path)
        self.assertIsNone(report_build.build_report(self.run)["first_impression"])

    def test_first_impression_masked_and_capped(self):
        self.set_takeaway("Analytics student; email maya.rivera@example.com, phone (512) 555-0142 and +44 20 7946 "
                          "0958 sit in the header.")
        fi = report_build.build_report(self.run)["first_impression"]
        for raw in ("maya.rivera@example.com", "555-0142", "7946 0958"):
            self.assertNotIn(raw, fi)
        self.assertIn("Analytics student", fi)
        words = ["word%d" % i for i in range(40)]
        self.set_takeaway(" ".join(words))
        fi = report_build.build_report(self.run)["first_impression"]
        self.assertEqual(fi, " ".join(words[:30]) + "\u2026")
        self.set_takeaway(" ".join(words[:20]) + ". " + " ".join(words[20:]))
        self.assertEqual(report_build.build_report(self.run)["first_impression"], " ".join(words[:20]) + ".")


class SourceRulesTest(unittest.TestCase):
    def test_python38_syntax_and_stdlib_only(self):
        stdlib = {"argparse", "json", "math", "os", "re", "shutil", "sys", "traceback", "datetime", "collections",
                  "difflib", "importlib", "platform", "hp", "zipfile"}
        for path in INTEGRATION_FILES:
            with open(path, "r", encoding="utf-8") as f:
                src = f.read()
            tree = ast.parse(src, filename=path, feature_version=(3, 8))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        self.assertIn(a.name.split(".")[0], stdlib, (path, a.name))
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    self.assertIn(node.module.split(".")[0], stdlib, (path, node.module))
            for banned in ("removeprefix", "removesuffix", "functools.cache", "zip(strict"):
                self.assertNotIn(banned, src, (path, banned))

    def test_hp_py_finds_itself(self):
        with open(INTEGRATION_FILES[0], "r", encoding="utf-8") as f:
            src = f.read()
        self.assertIn("os.path.abspath(__file__)", src)
        self.assertIn("sys.path.insert(0, HERE)", src)
        self.assertNotIn("CLAUDE_SKILL_DIR", src)


if __name__ == "__main__":
    unittest.main()
