"""hp.py command behaviour: argument checks, exit codes, one JSON object on stdout, run folders,
transcription, pasted text, overrides, terms, and the preconditions each command enforces.

Every case runs the real CLI as a subprocess from a working folder outside the repo.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "fixtures", "e2e"))
sys.path.insert(0, os.path.join(HERE, "fixtures"))
import support as S  # noqa: E402

GAP_RESUME = """Casey Morgan
Dayton, OH | casey.morgan@example.com | (555) 010-0163

Education
Riverbend Community College, Dayton, OH
Associate of Science in Business, May 2026

Experience
Barista, Larkspur Cafe, Dayton, OH
June 2021 - August 2022
- Made drinks for about 200 customers a shift
- Trained 2 new baristas
Cashier, Hilltop Grocery, Dayton, OH
September 2024 - Present
- Count the cash drawer at closing
- Restock shelves and help customers find items

Skills
Excel, Google Sheets, Spanish (conversational)
"""


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hp-cli-")
        self.base = os.path.join(self.tmp, "runs")
        self.environ = S.env(pdf_engines="builtin")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def hp(self, args, **kw):
        return S.hp(args, kw.pop("cwd", self.tmp), kw.pop("environ", self.environ), **kw)

    def write(self, name, text):
        p = os.path.join(self.tmp, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p

    def init_ok(self, **kw):
        r = self.hp(S.init_args(S.fixture("resume.docx"), self.base, jd=S.fixture("jd.txt")), **kw)
        self.assertEqual(r.code, 0, r)
        return r


class ArgumentErrorsTest(CliTestCase):
    def assert_error(self, args, needle=None, code=2):
        r = self.hp(args)
        self.assertEqual(r.code, code, r)
        self.assertFalse(r.data["ok"])
        self.assertIn("error", r.data)
        if needle:
            self.assertIn(needle, r.data["error"])
        return r

    def test_no_command_and_unknown_command(self):
        self.assert_error([], "give a command")
        self.assert_error(["launch"], "invalid choice")

    def test_help_is_json(self):
        r = self.hp(["init", "-h"])
        self.assertEqual(r.code, 0)
        self.assertEqual(r.data["command"], "init")
        self.assertIsInstance(r.data["help"], list)
        text = "\n".join(r.data["help"])
        self.assertIn("--resume-text", text)
        self.assertIn("the resume file", text)           # options carry descriptions (live test 2.12)

    def test_help_prints_once(self):
        """Live test 2.12: the help text is printed once (inside the JSON), never again on stderr."""
        for args in (["init", "--help"], ["validate", "-h"], ["-h"]):
            r = self.hp(args)
            self.assertEqual(r.code, 0, args)
            text = "\n".join(r.data["help"])
            self.assertEqual(text.count("usage: hp.py"), 1, args)
            self.assertNotIn("usage:", r.stderr, args)
        r = self.hp(["validate", "-h"])
        self.assertIn("Exit 0", "\n".join(r.data["help"]))

    def test_init_argument_errors_create_nothing(self):
        jd = S.fixture("jd.txt")
        res = S.fixture("resume.docx")
        cases = [
            (["init", "--jd", jd, "--role", "X", "--out", self.base], "--resume"),
            (["init", "--resume", res, "--role", "X", "--out", self.base], "exactly one"),
            (["init", "--resume", res, "--jd", jd, "--no-jd", "--role", "X", "--out", self.base], "exactly one"),
            (["init", "--resume", res, "--no-jd", "--role", "   ", "--out", self.base], "--role"),
            (["init", "--resume", res, "--no-jd", "--role", "X", "--as-of", "2026-13-40", "--out", self.base], "--as-of"),
            (["init", "--resume", res, "--no-jd", "--role", "X", "--as-of", "yesterday", "--out", self.base], "--as-of"),
            (["init", "--resume", res, "--no-jd", "--role", "X", "--locale", "Germany", "--out", self.base], "--locale"),
            (["init", "--resume", res, "--jd", jd, "--role", "X", "--jd-source", "linkedin", "--out", self.base],
             "--jd-source"),
            (["init", "--resume", res, "--no-jd", "--role", "X", "--stage", "senior", "--out", self.base], "invalid choice"),
            (["init", "--resume", os.path.join(self.tmp, "missing.pdf"), "--no-jd", "--role", "X", "--out", self.base],
             "no file"),
            (["init", "--resume", self.tmp, "--no-jd", "--role", "X", "--out", self.base], "folder"),
            (["init", "--resume", res, "--jd", os.path.join(self.tmp, "nope.txt"), "--role", "X", "--out", self.base],
             "no file"),
        ]
        for args, needle in cases:
            self.assert_error(args, needle)
        self.assertFalse(os.path.exists(self.base), "an argument error must not create a run folder")

    def test_empty_and_binary_text_inputs(self):
        empty = self.write("empty.txt", "   \n")
        self.assert_error(["init", "--resume-text", empty, "--no-jd", "--role", "X", "--out", self.base], "empty")
        binary = os.path.join(self.tmp, "blob.txt")
        with open(binary, "wb") as f:
            f.write(b"\x00\x01\x02binary\x00")
        self.assert_error(["init", "--resume-text", binary, "--no-jd", "--role", "X", "--out", self.base], "binary")

    def test_run_commands_need_a_run_folder(self):
        for args in (["status", self.tmp], ["synthesize", self.tmp, "--mode", "parallel"], ["truth", "/nonexistent/x"],
                     ["render", self.tmp], ["report", self.tmp], ["recheck", self.tmp], ["screen", self.tmp],
                     ["validate", self.tmp, "x.json"], ["ledger", self.tmp, "--override", "J1=must"]):
            self.assert_error(args)

    def test_bad_choices(self):
        r = self.init_ok()
        run = r.data["run"]
        self.assert_error(["synthesize", run, "--mode", "turbo"], "invalid choice")
        self.assert_error(["render", run, "--layout", "fancy"], "invalid choice")
        self.assert_error(["render", run, "--pdf-engine", "wkhtml"], "invalid choice")
        self.assert_error(["synthesize", run, "--mode", "parallel", "--merges", os.path.join(self.tmp, "m.json")], "--merges")


class InitTest(CliTestCase):
    def test_default_base_is_cwd_and_gitignored(self):
        work = os.path.join(self.tmp, "student")
        os.makedirs(work)
        args = [a for a in S.init_args(S.fixture("resume.docx"), "", jd=S.fixture("jd.txt")) if a]
        args.remove("--out")
        r = self.hp(args, cwd=work)
        self.assertEqual(r.code, 0, r)
        base = os.path.join(work, "hiring-panel-runs")
        self.assertEqual(os.path.realpath(os.path.dirname(r.data["run"])), os.path.realpath(base))
        self.assertIn("*", S.read(os.path.join(base, ".gitignore")).split())
        self.assertFalse(r.data["git_warning"])

    def test_git_warning_and_existing_gitignore_kept(self):
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(os.path.join(repo, ".git"))
        base = os.path.join(repo, "hiring-panel-runs")
        os.makedirs(base)
        with open(os.path.join(base, ".gitignore"), "w") as f:
            f.write("# mine\n*.tmp\n")
        r = self.hp(S.init_args(S.fixture("resume.docx"), base, jd=S.fixture("jd.txt")))
        self.assertEqual(r.code, 0, r)
        self.assertTrue(r.data["git_warning"])
        self.assertEqual(S.read(os.path.join(base, ".gitignore")), "# mine\n*.tmp\n")      # never clobbered
        self.assertIn("*", S.read(os.path.join(r.data["run"], ".gitignore")).split())      # the run is still covered

    def test_same_minute_runs_get_distinct_folders(self):
        a = self.init_ok().data["run"]
        b = self.init_ok().data["run"]
        self.assertNotEqual(a, b)
        self.assertTrue(b.endswith("-2"))

    def test_pasted_resume_and_posting_on_stdin(self):
        resume = self.write("pasted.txt", GAP_RESUME)
        jd = S.read(S.fixture("jd.txt"))
        r = self.hp(["init", "--resume-text", resume, "--jd", "-", "--role", "Store Associate", "--locale", "en_us",
                     "--out", self.base], stdin=jd)
        self.assertEqual(r.code, 0, r)
        run = r.data["run"]
        self.assertEqual(r.data["resume"]["format"], "txt")
        self.assertEqual(r.data["jd"]["source"], "pasted")
        self.assertEqual(S.read(os.path.join(run, "work", "inputs", "original.txt"), "rb"),
                         S.read(resume, "rb"))
        self.assertEqual(S.read(os.path.join(run, "work", "inputs", "jd.md")), jd)
        state = S.load(os.path.join(run, "work", "state.json"))
        self.assertEqual(state["locale"], "en-US")
        self.assertEqual(state["resume_input"], {"file": None, "text": "inputs/original.txt"})
        # screen re-reads the same text and gives the same screening
        before = S.read(os.path.join(run, "work", "screening", "before", "screening.json"))
        s = self.hp(["screen", run])
        self.assertEqual(s.code, 0, s)
        self.assertEqual(S.read(os.path.join(run, "work", "screening", "before", "screening.json")), before)

    def test_gap_is_info_only(self):
        resume = self.write("gap.txt", GAP_RESUME)
        r = self.hp(["init", "--resume-text", resume, "--no-jd", "--role", "Store Associate", "--out", self.base])
        run = r.data["run"]
        scr = S.load(os.path.join(run, "work", "screening", "before", "screening.json"))
        gaps = [i for i in scr["issues"] if i["id"] == "DATE-008"]
        self.assertTrue(gaps, [i["id"] for i in scr["issues"]])
        self.assertEqual(gaps[0]["severity"], "info")
        s = self.hp(["synthesize", run, "--mode", "parallel"])          # no reviews: script findings only
        self.assertEqual(s.code, 0, s)
        self.assertEqual(s.data["panel_size"], 0)
        self.assertTrue(s.data.get("warnings"))
        synth = S.load(os.path.join(run, "work", "synthesis.json"))
        self.assertIn("DATE-008", [n["id"] for n in synth["notes"]])
        anchors = [e["anchor"] for i in synth["issues"] for e in i["evidence"]]
        self.assertNotIn("A:DATE-008", anchors)

    def test_other_locale_is_accepted(self):
        r = self.hp(["init", "--resume", S.fixture("resume.docx"), "--no-jd", "--role", "Analyst", "--locale", "nl-NL",
                     "--out", self.base])
        self.assertEqual(r.code, 0, r)
        self.assertEqual(S.load(os.path.join(r.data["run"], "work", "state.json"))["locale"], "nl-NL")

    def test_image_only_pdf_needs_transcription_then_rerun(self):
        scan = os.path.join(S.FILES, "image_only.pdf")
        if not os.path.isfile(scan):
            self.skipTest("ingest fixtures not generated")
        r = self.hp(["init", "--resume", scan, "--no-jd", "--role", "Marketing Intern", "--out", self.base])
        self.assertEqual(r.code, 0, r)
        self.assertTrue(r.data["resume"]["needs_transcription"])
        self.assertEqual(r.data["resume"]["transcription_reason"], "image_only")
        self.assertIn("--resume-text", r.data["next"])
        run1 = r.data["run"]
        st = self.hp(["status", run1])
        self.assertEqual(st.data["next_step"], "transcribe")
        transcript = os.path.join(run1, "work", "inputs", "transcript.txt")
        with open(transcript, "w", encoding="utf-8") as f:
            f.write(GAP_RESUME)
        r2 = self.hp(["init", "--resume", scan, "--resume-text", transcript, "--no-jd", "--role", "Marketing Intern",
                      "--out", self.base])
        self.assertEqual(r2.code, 0, r2)
        self.assertFalse(r2.data["resume"]["needs_transcription"])
        run2 = r2.data["run"]
        self.assertNotEqual(run1, run2)
        self.assertEqual(S.read(os.path.join(run2, "work", "inputs", "transcript.txt")), GAP_RESUME)
        self.assertTrue(os.path.isfile(os.path.join(run2, "work", "inputs", "original.pdf")))
        scr = S.load(os.path.join(run2, "work", "screening", "before", "screening.json"))
        p1 = [i for i in scr["issues"] if i["id"] == "PARSE-001"]
        self.assertTrue(p1 and p1[0]["severity"] == "critical", [i["id"] for i in scr["issues"]])
        self.assertIn("Casey Morgan", S.read(os.path.join(run2, "work", "inputs", "resume.md")))
        self.assertEqual(self.hp(["status", run2]).data["next_step"], "panel")

    def test_encrypted_docx_asks_for_another_file(self):
        enc = os.path.join(S.FILES, "encrypted.docx")
        if not os.path.isfile(enc):
            self.skipTest("ingest fixtures not generated")
        r = self.hp(["init", "--resume", enc, "--no-jd", "--role", "Analyst", "--out", self.base])
        self.assertEqual(r.code, 0, r)
        self.assertTrue(r.data["resume"]["needs_transcription"])
        self.assertIn(r.data["resume"]["transcription_reason"], ("encrypted", "refused", "unreadable"))
        self.assertIn("Ask the student", r.data["next"])

    def test_docx_posting_file_is_read(self):
        jd_docx = os.path.join(S.FILES, "clean.docx")
        if not os.path.isfile(jd_docx):
            self.skipTest("ingest fixtures not generated")
        r = self.hp(["init", "--resume", S.fixture("resume.docx"), "--jd", jd_docx, "--role", "Analyst",
                     "--out", self.base])
        self.assertEqual(r.code, 0, r)
        self.assertGreater(r.data["jd"]["chars"], 50)
        self.assertEqual(r.data["jd"]["source"], "file")


class RunCommandsTest(CliTestCase):
    def test_ledger_override(self):
        run = self.init_ok().data["run"]
        r = self.hp(["ledger", run, "--override", "J2=company", "J14=logistics"])
        self.assertEqual(r.code, 0, r)
        self.assertEqual([o["id"] for o in r.data["overrides"]], ["J2", "J14"])
        state = S.load(os.path.join(run, "work", "state.json"))
        self.assertEqual(len(state["ledger_overrides"]), 2)
        for bad, needle in ((["J999=must"], "J999"), (["R3=must"], "J#=kind"), (["J3=essential"], "kind"),
                            (["J3"], "J#=kind")):
            e = self.hp(["ledger", run, "--override"] + bad)
            self.assertEqual(e.code, 2, e)
            self.assertIn(needle, e.data["error"])
        self.assertEqual(len(S.load(os.path.join(run, "work", "state.json"))["ledger_overrides"]), 2)
        # screen keeps the overrides
        self.assertEqual(self.hp(["screen", run]).code, 0)
        ledger = S.load(os.path.join(run, "work", "inputs", "ledger.json"))
        kinds = dict((j["id"], j["kind"]) for j in ledger["jd_items"])
        self.assertEqual((kinds["J2"], kinds["J14"]), ("company", "logistics"))

    def test_screen_terms_errors(self):
        run = self.init_ok().data["run"]
        bad = self.write("terms.json", "{not json")
        self.assertEqual(self.hp(["screen", run, "--terms", bad]).code, 2)
        wrong = self.write("terms2.json", json.dumps({"term": "SQL"}))
        self.assertEqual(self.hp(["screen", run, "--terms", wrong]).code, 2)
        self.assertEqual(self.hp(["screen", run, "--terms", os.path.join(self.tmp, "none.json")]).code, 2)

    def test_preconditions(self):
        run = self.init_ok().data["run"]
        st = self.hp(["status", run])
        self.assertEqual(st.data["next_step"], "panel")
        self.assertEqual(st.data["reviews"], [])
        v = self.hp(["validate", run, os.path.join(run, "work", "reviews", "recruiter.json")])
        self.assertEqual(v.code, 1, v)
        self.assertTrue(v.data["errors"])
        # Live test 3.4: ok alone decides; no confusing "usable"; partial_ok and next explain the rest.
        self.assertIs(v.data["ok"], False)
        self.assertNotIn("usable", v.data)
        self.assertIs(v.data["partial_ok"], False)
        self.assertIn("Redo this reviewer once", v.data["next"])
        self.assertIn("skips this file", v.data["next"])
        for args, needle in ((["report", run], "synthesize"), (["truth", run], "resume.json"),
                             (["render", run], "resume.json"), (["recheck", run], "render")):
            r = self.hp(args)
            self.assertEqual(r.code, 2, r)
            self.assertIn(needle, r.data["error"])

    def test_validate_resolves_relative_names(self):
        run = self.init_ok().data["run"]
        S.copy_reviews(S.REVIEWS, run, ids=("recruiter",))
        r = self.hp(["validate", run, "recruiter.json"])
        self.assertEqual(r.code, 0, r)
        self.assertEqual(r.data["reviewer_id"], "recruiter")
        self.assertIs(r.data["ok"], True)
        self.assertIs(r.data["partial_ok"], False)
        self.assertNotIn("usable", r.data)
        self.assertTrue(r.data["next"].startswith("Valid."))

    def test_validate_partial_review(self):
        """An invalid review that synthesis could still partly use: exit 1, ok false, partial_ok true."""
        run = self.init_ok().data["run"]
        S.copy_reviews(S.REVIEWS, run, ids=("recruiter",))
        path = os.path.join(run, "work", "reviews", "recruiter.json")
        with open(path, encoding="utf-8") as f:
            review = json.load(f)
        review["one_line_take"] = " ".join(["word"] * 40)          # too long: invalid, but the findings are fine
        with open(path, "w", encoding="utf-8") as f:
            json.dump(review, f)
        r = self.hp(["validate", run, path])
        self.assertEqual(r.code, 1, r)
        self.assertIs(r.data["ok"], False)
        self.assertIs(r.data["partial_ok"], True, r.data)
        self.assertIn("keeps the parts of this review it can use", r.data["next"])

    def test_doctor_surfaces(self):
        d = self.hp(["doctor"], environ=S.env(extra={"CLAUDECODE": "1"})).data
        self.assertEqual(d["surface"], "claude_code")
        self.assertEqual(d["outputs_dir"], "")
        d = self.hp(["doctor"]).data
        self.assertIn(d["surface"], ("unknown", "claude_ai"))
        self.assertTrue(os.path.isabs(d["script"]))


if __name__ == "__main__":
    unittest.main()
