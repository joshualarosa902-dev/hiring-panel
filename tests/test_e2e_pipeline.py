"""End-to-end: the full Hiring Panel run, through the real CLI, twice, with the clock pinned.

Fictional candidate (tests/fixtures/e2e/resume.docx, built by make_e2e_fixtures.py) applying to a
fictional posting (jd.txt). The seven reviews in fixtures/e2e/reviews/ were written by hand against
the ledger this run produces (real R#/J#/A: anchors, exact quotes); answers.json, resume.json (an
honest rewrite with evidence) and provenance.json complete the run.

Steps: doctor, init, screen --terms, ledger --override, validate (7 good + 1 bad), synthesize,
report (panel stage), truth, render, report (final, --copy-to), status, recheck + a fresh panel,
report (with the directional re-read).

Run A blocks every socket (sitecustomize on PYTHONPATH); run B is identical without the block. Every
work file except state.json and the PDFs must be byte-identical between them. ARCHITECTURE.md
section 15 invariants are asserted on run A.
"""
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "fixtures", "e2e"))
import support as S  # noqa: E402

sys.path.insert(0, S.SCRIPTS)

TERMS = [
    {"term": "dashboards", "aliases": ["dashboard"], "importance": "preferred",
     "jd_quote": "Build weekly dashboards that track email and social campaign performance"},
    {"term": "Looker", "aliases": [], "importance": "required",
     "jd_quote": "Experience with Looker and BigQuery"},          # not in the posting: must be rejected
]


def pipeline(base, environ, record):
    """Run every step; store each CliResult in `record` under a step name. Returns the run folder."""
    cwd = base
    record["doctor"] = S.hp(["doctor"], cwd, environ)
    r = S.hp(S.init_args(S.fixture("resume.docx"), os.path.join(base, "runs"), jd=S.fixture("jd.txt")), cwd, environ)
    record["init"] = r
    run = r.data["run"]
    terms_path = os.path.join(base, "terms.json")
    with open(terms_path, "w", encoding="utf-8") as f:
        json.dump(TERMS, f)
    record["screen"] = S.hp(["screen", run, "--terms", terms_path], cwd, environ)
    record["ledger"] = S.hp(["ledger", run, "--override", "J2=company"], cwd, environ)
    S.copy_reviews(S.REVIEWS, run)
    record["validate"] = [S.hp(["validate", run, os.path.join(run, "work", "reviews", rid + ".json")], cwd, environ)
                          for rid in S.REVIEWER_IDS]
    record["validate_bad"] = S.hp(["validate", run, os.path.join(S.REVIEWS, "bad_recruiter.json")], cwd, environ)
    record["status_mid"] = S.hp(["status", run], cwd, environ)
    record["synthesize"] = S.hp(["synthesize", run, "--mode", "parallel"], cwd, environ)
    record["report_panel"] = S.hp(["report", run], cwd, environ)
    with open(os.path.join(run, "Hiring_Panel_Report.md"), "r", encoding="utf-8") as f:
        record["panel_md"] = f.read()
    record["panel_report_json"] = S.load(os.path.join(run, "work", "report.json"))
    S.place(S.fixture("answers.json"), run, "answers.json")
    S.place(S.fixture("resume.json"), run, os.path.join("rewrite", "resume.json"))
    record["truth"] = S.hp(["truth", run], cwd, environ)
    S.place(S.fixture("provenance.json"), run, os.path.join("rewrite", "provenance.json"))
    record["render"] = S.hp(["render", run], cwd, environ)
    outputs = os.path.join(base, "outputs")
    record["report_final"] = S.hp(["report", run, "--copy-to", outputs], cwd, environ)
    record["status_end"] = S.hp(["status", run], cwd, environ)
    return run


class FullPipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="hp-e2e-")
        cls.base_a = os.path.join(cls.tmp, "a")
        cls.base_b = os.path.join(cls.tmp, "b")
        os.makedirs(cls.base_a)
        os.makedirs(cls.base_b)
        cls.A, cls.B = {}, {}
        blocked = S.env(block_network_dir=S.network_blocker(cls.tmp))
        cls.run_a = pipeline(cls.base_a, blocked, cls.A)
        cls.run_b = pipeline(cls.base_b, S.env(), cls.B)
        cls.work = os.path.join(cls.run_a, "work")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # ------------------------------------------------------------------ exit codes and outputs
    def test_exit_codes(self):
        expected = {"doctor": 0, "init": 0, "screen": 0, "ledger": 0, "validate_bad": 1, "status_mid": 0,
                    "synthesize": 0, "truth": 0, "status_end": 0}
        for step, code in expected.items():
            self.assertEqual(self.A[step].code, code, "%s: %r" % (step, self.A[step]))
        for v in self.A["validate"]:
            self.assertEqual(v.code, 0, v)
            self.assertTrue(v.data["ok"])
        # render and report exit 0, or 4 when this machine has no PDF engine at all
        for step in ("render", "report_panel", "report_final"):
            self.assertIn(self.A[step].code, (0, 4), "%s: %r" % (step, self.A[step]))

    def test_doctor(self):
        d = self.A["doctor"].data
        for key in ("python", "platform", "surface", "outputs_dir", "pdf_engines", "pdf_text_backends", "git_repo"):
            self.assertIn(key, d)
        self.assertIn(d["surface"], ("claude_code", "claude_ai", "unknown"))
        self.assertIn("builtin", d["pdf_text_backends"])
        self.assertEqual(d["lexicon"], "ok")

    def test_init_output(self):
        d = self.A["init"].data
        self.assertTrue(os.path.isabs(d["run"]))
        self.assertEqual(os.path.basename(d["run"]), "2026-10-20-1430-northwind-foods-marketing-analytics-intern")
        self.assertEqual(d["resume"]["format"], "docx")
        self.assertFalse(d["resume"]["needs_transcription"])
        self.assertFalse(d["jd"]["general_review"])
        self.assertFalse(d["jd"]["too_thin"])
        self.assertEqual(d["flags"], {"thin": False, "long": False, "non_english": False})
        self.assertFalse(d["git_warning"])
        scr = S.load(os.path.join(self.work, "screening", "before", "screening.json"))
        self.assertEqual(d["screening"]["overall"] % 5, 0)
        self.assertEqual(d["ledger"]["resume_lines"], 32)
        self.assertGreater(d["ledger"]["jd_items"], 15)
        for name in ("resume.md", "ats_view.txt", "jd.md", "ledger.json", "original.docx"):
            self.assertTrue(os.path.isfile(os.path.join(self.work, "inputs", name)), name)
        self.assertEqual(S.read(os.path.join(self.work, "inputs", "original.docx"), "rb"),
                         S.read(S.fixture("resume.docx"), "rb"))
        self.assertEqual(S.read(os.path.join(self.work, "inputs", "jd.md")), S.read(S.fixture("jd.txt")))
        self.assertEqual(scr["extraction"]["ats_view_file"], "inputs/ats_view.txt")

    def test_gitignore_everywhere(self):
        base = os.path.dirname(self.run_a)
        for folder in (base, self.run_a):
            text = S.read(os.path.join(folder, ".gitignore"))
            self.assertIn("*", [ln.strip() for ln in text.splitlines()])

    def test_terms_and_override(self):
        d = self.A["screen"].data
        self.assertEqual(d["terms"], {"provided": 2, "accepted": 1, "rejected": 1})
        self.assertTrue(any("Looker" in m or "quote" in m for m in d["term_messages"]), d["term_messages"])
        self.assertTrue(os.path.isfile(os.path.join(self.work, "inputs", "terms.json")))
        state = S.load(os.path.join(self.work, "state.json"))
        self.assertEqual(state["ledger_overrides"], [{"id": "J2", "from": "other", "to": "company"}])
        ledger = S.load(os.path.join(self.work, "inputs", "ledger.json"))
        j2 = [j for j in ledger["jd_items"] if j["id"] == "J2"][0]
        self.assertEqual(j2["kind"], "company")
        # J2 (override) + the two "About" lines + the two EEO lines (EEO statements are kind company).
        self.assertEqual(self.A["ledger"].data["ledger"]["kinds"]["company"], 5)

    def test_bad_review_fails_with_errors(self):
        d = self.A["validate_bad"].data
        self.assertFalse(d["ok"])
        text = " ".join(d["errors"])
        self.assertIn("advance", text)
        self.assertIn("one_line_take", text)
        self.assertIn("quote not found", text)

    def test_status_progression(self):
        self.assertEqual(self.A["status_mid"].data["next_step"], "synthesize")
        self.assertIn("synthesize", self.A["status_mid"].data["next"])
        end = self.A["status_end"].data
        self.assertEqual(end["next_step"], "done")
        for step in ("init", "screen", "synthesize", "report_panel", "answers", "truth", "provenance", "render",
                     "gate", "report_final"):
            self.assertIn(step, end["done"])

    def test_synthesize_output(self):
        d = self.A["synthesize"].data
        vote = dict((k, v) for k, v in d["panel_vote"].items() if k != "no")    # "no" is new (live test 4.1)
        self.assertEqual(vote, {"advance": 4, "unsure": 2, "total": 7})
        self.assertEqual(len(d["reviewers"]), 7)
        self.assertEqual(d["dropped"], 0)
        self.assertLessEqual(len(d["top"]), 5)
        synth = S.load(os.path.join(self.work, "synthesis.json"))
        self.assertEqual(synth["mode"], "parallel")
        self.assertEqual([i["rank"] for i in synth["issues"]], list(range(1, len(synth["issues"]) + 1)))

    # ------------------------------------------------------------------ the gate and the files
    def test_render_and_gate(self):
        d = self.A["render"].data
        gate = S.load(os.path.join(self.work, "gate.json"))
        self.assertTrue(gate["passed"], gate["failures"])
        self.assertEqual(d["gate"]["passed"], True)
        docx = gate["checks"]["docx"]
        self.assertGreaterEqual(docx["parse_safety"], 90)
        self.assertEqual(docx["blocking_parse_issues"], [])
        self.assertEqual(docx["tab_merged_tokens"], 0)
        self.assertGreaterEqual(docx["word_recovery"], 0.98)
        if gate["checks"]["pdf"].get("checked"):
            self.assertGreaterEqual(gate["checks"]["pdf"]["word_recovery"], 0.98)
            self.assertGreaterEqual(gate["checks"]["pdf"]["parse_safety"], 90)
        for kind in ("docx",) + (("pdf",) if gate["checks"]["pdf"].get("checked") else ()):
            for name in ("screening.json", "screening.md", "ats_view.txt"):
                self.assertTrue(os.path.isfile(os.path.join(self.work, "screening", "after", kind, name)))
        self.assertEqual(d["pages"], 1)
        self.assertEqual(d["target_pages"], 1)

    def test_deliverables_exist(self):
        report = S.load(os.path.join(self.work, "report.json"))
        files = report["files"]
        for key in ("resume_docx", "resume_md", "report_md", "report_html"):
            self.assertTrue(os.path.isfile(os.path.join(self.run_a, files[key])), key)
        self.assertEqual(files["resume_docx"], "Riley_Castellano_Resume.docx")
        import zipfile
        with zipfile.ZipFile(os.path.join(self.run_a, files["resume_docx"])) as z:
            self.assertIsNone(z.testzip())
            self.assertIn("word/document.xml", z.namelist())
            self.assertNotIn("docProps/app.xml", z.namelist())
        for key in ("resume_pdf", "report_pdf"):
            if key in files:
                head = S.read(os.path.join(self.run_a, files[key]), "rb")[:5]
                self.assertEqual(head, b"%PDF-", key)
        if "report_pdf" in files:
            self.assertEqual(self.A["report_final"].data["pages"], 1)
            self.assertEqual(self.A["report_panel"].data["pages"], 1)
        from hp.ingest import ingest_file
        back = ingest_file(os.path.join(self.run_a, files["resume_docx"]))
        self.assertEqual(back["errors"], [])
        self.assertEqual(back["method"], "docx-xml")
        for key in ("work/report.json", "work/synthesis.json", "work/gate.json", "work/rewrite/truth.json"):
            json.loads(S.read(os.path.join(self.run_a, key)))
        copied = self.A["report_final"].data["copied"]
        self.assertEqual(sorted(os.path.basename(c) for c in copied), sorted(files.values()))
        for c in copied:
            self.assertTrue(os.path.isfile(c))

    def test_one_json_object_per_command(self):
        for step, res in self.A.items():
            if isinstance(res, list):
                for r in res:
                    self.assertEqual(json.loads(r.stdout), r.data)
            elif hasattr(res, "stdout"):
                self.assertEqual(json.loads(res.stdout), res.data, step)
                self.assertTrue(res.stdout.lstrip().startswith("{"))

    # ------------------------------------------------------------------ determinism
    def test_byte_identical_across_runs(self):
        files_a = S.deterministic_files(self.run_a)
        files_b = S.deterministic_files(self.run_b)
        self.assertEqual(files_a, files_b)
        self.assertGreater(len(files_a), 25)
        for rel in files_a:
            if rel.replace(os.sep, "/") == "work/screening/after/pdf/screening.json":
                # The PDF engine stamps a creation time into the PDF, so its sha256 and size differ;
                # everything read from it must still match.
                a, b = (S.load(os.path.join(r, rel)) for r in (self.run_a, self.run_b))
                for d in (a, b):
                    d["inputs"]["resume"]["sha256"] = d["inputs"]["resume"]["bytes"] = None
                self.assertEqual(a, b, rel)
                continue
            self.assertEqual(S.read(os.path.join(self.run_a, rel), "rb"), S.read(os.path.join(self.run_b, rel), "rb"),
                             "differs between identical runs: %s" % rel)

    def test_no_absolute_paths_or_clock_in_work_json(self):
        for rel in S.deterministic_files(self.run_a):
            if not rel.endswith(".json"):
                continue
            text = S.read(os.path.join(self.run_a, rel))
            self.assertNotIn(self.tmp, text, rel)
            self.assertIsNone(re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", text), rel)

    # ------------------------------------------------------------------ section 15 invariants
    def test_inv1_resume_facts_come_from_sources(self):
        truth = S.load(os.path.join(self.work, "rewrite", "truth.json"))
        self.assertTrue(truth["passed"])
        self.assertEqual(truth["errors"], [])
        md = S.read(os.path.join(self.run_a, "Riley_Castellano_Resume.md"))
        source = S.read(os.path.join(self.work, "inputs", "resume.md")) + "\n" + S.read(S.fixture("answers.json"))
        source_numbers = set(re.findall(r"\d+(?:[.,]\d+)*", source))
        for n in re.findall(r"\d+(?:[.,]\d+)*", md):
            self.assertIn(n, source_numbers, "number %s is not in the resume or the answers" % n)
        self.assertIn("about 600", md)                      # hedge kept
        self.assertIn("about 18 hours", md)
        self.assertIn("Helped with Instagram posts", md)   # ownership not upgraded
        self.assertNotIn("300%", md)                        # the claim the student could not back up is gone
        resume = S.load(S.fixture("resume.json"))
        refs = re.findall(r'"ref":\s*"([^"]+)"', json.dumps(resume))
        self.assertTrue(refs)
        self.assertFalse([r for r in refs if r.startswith("J")], "the posting is never evidence")

    def test_inv2_no_placeholders_in_final_files(self):
        report = S.load(os.path.join(self.work, "report.json"))
        for key, name in report["files"].items():
            path = os.path.join(self.run_a, name)
            if name.endswith(".docx"):
                text = S.docx_text(path)
            elif name.endswith(".pdf"):
                from hp.ingest import ingest_file
                doc = ingest_file(path)
                text = "\n".join(ln["text"] for ln in doc["lines"])
            else:
                text = S.read(path)
            self.assertNotIn("{{", text, key)
            self.assertNotIn("[ADD:", text, key)

    def test_inv3_no_hidden_text_generated(self):
        from hp.ingest import ingest_file
        for ext in ("docx", "pdf"):
            path = os.path.join(self.run_a, "Riley_Castellano_Resume." + ext)
            if not os.path.isfile(path):
                continue
            doc = ingest_file(path)
            hidden = doc["signals"]["hidden_text"]
            self.assertEqual(sum(hidden.values()), 0, (ext, hidden))
            self.assertEqual(doc["signals"]["caps_formatting"], 0)
            self.assertEqual(doc["signals"]["tables"]["count"], 0)
            self.assertEqual(doc["signals"]["text_boxes"]["count"], 0)

    def test_inv4_numbers_from_scripts_one_score(self):
        report = S.load(os.path.join(self.work, "report.json"))
        before = S.load(os.path.join(self.work, "screening", "before", "screening.json"))
        synth = S.load(os.path.join(self.work, "synthesis.json"))
        sb = report["screening"]["before"]
        self.assertEqual(sb["overall"], before["scores"]["overall"]["value"])
        self.assertEqual(sb["overall"] % 5, 0)
        self.assertEqual(sb["machine_readability"], {"value": before["scores"]["parse_safety"]["value"],
                                                     "band": before["scores"]["parse_safety"]["band"]})
        cov = before["keywords"]["coverage"]
        self.assertEqual(sb["required"]["found"], cov["required_found"])
        self.assertEqual(sb["required"]["total"], cov["required_total"])
        self.assertEqual(sb["required"]["listed_only"], cov["required_listed_only"])
        after_src = report["screening"]["after_source"]
        after = S.load(os.path.join(self.work, "screening", "after", after_src, "screening.json"))
        self.assertEqual(report["screening"]["after"]["overall"], after["scores"]["overall"]["value"])
        v = synth["panel_vote"]
        self.assertEqual(report["verdict_strip"]["vote_label"], "%d of %d would move you forward" % (v["advance"], v["total"]))
        self.assertEqual([w["issue_id"] for w in report["weaknesses"]], [i["id"] for i in synth["issues"]])
        for w in report["weaknesses"]:
            self.assertEqual(w["flagged_count"], len(w["flagged_by"]))
        for row in report["panel"]:
            self.assertFalse([k for k, val in row.items() if isinstance(val, (int, float)) and not isinstance(val, bool)])
        self.assertEqual(report["screening"]["label"], "Simulated screening check")
        for name in ("Hiring_Panel_Report.md", "Hiring_Panel_Report.html"):
            text = S.read(os.path.join(self.run_a, name))
            self.assertIsNone(re.search(r"(?i)\bATS\s+score", text), name)
            self.assertIsNone(re.search(r"\b\d{1,2}\s*/\s*10\b", text), name)       # no per-reviewer scores
            self.assertNotIn("interview-ready", text.lower())
            self.assertIn("Simulated screening check", text)
        from hp.report_build import validate_report
        self.assertEqual(validate_report(report), [])
        self.assertEqual(validate_report(self.A["panel_report_json"]), [])

    def test_inv5_parallel_mode_has_no_disclosure_but_label(self):
        report = S.load(os.path.join(self.work, "report.json"))
        self.assertEqual(report["mode"], "parallel")
        self.assertEqual(report["mode_note"], "")
        self.assertIn("independent", report["verdict_strip"]["mode_label"])

    def test_inv7_no_network(self):
        # run A ran every command with sockets blocked; any attempt would have crashed a command
        for step in ("init", "screen", "synthesize", "render", "report_final"):
            self.assertNotIn("NetworkBlocked", self.A[step].stderr, step)

    def test_inv8_no_protected_traits_in_report(self):
        for name in ("Hiring_Panel_Report.md", "Hiring_Panel_Report.html"):
            text = S.read(os.path.join(self.run_a, name)).lower()
            for word in ("religion", "gender", "ethnicity", "pregnan", "marital", "national origin", "sexual orientation"):
                self.assertNotIn(word, text, (name, word))

    def test_inv10_contact_masked_in_report(self):
        report_text = S.read(os.path.join(self.work, "report.json"))
        for name in ("Hiring_Panel_Report.md", "Hiring_Panel_Report.html"):
            text = S.read(os.path.join(self.run_a, name))
            for raw in ("riley.castellano@example.com", "(555) 010-0147", "555-010-0147"):
                self.assertNotIn(raw, text, (name, raw))
                self.assertNotIn(raw, report_text)
        for res in (self.A["synthesize"], self.A["report_final"]):
            self.assertNotIn("riley.castellano@example.com", res.stdout)

    def test_inv11_invented_facts_claim_only_after_script_truth(self):
        panel_md = self.A["panel_md"]
        self.assertNotIn("invented facts", panel_md)
        self.assertEqual(self.A["panel_report_json"]["truth_check"]["ran"], "not_run")
        final = S.load(os.path.join(self.work, "report.json"))
        self.assertEqual(final["truth_check"], {"ran": "script", "passed": True, "invented_facts": 0,
                                                "bullets_traced": 9, "bullets_total": 9, "provenance": "subagent"})
        self.assertIn("0 invented facts", S.read(os.path.join(self.run_a, "Hiring_Panel_Report.md")))

    # ------------------------------------------------------------------ report content
    def test_panel_stage_report(self):
        r = self.A["panel_report_json"]
        self.assertEqual(r["stage"], "panel")
        self.assertIsNone(r["changes"])
        self.assertTrue(all(w["status"] == "open" for w in r["weaknesses"]))
        self.assertEqual(set(r["files"]), {"report_pdf", "report_md", "report_html"} if
                         self.A["report_panel"].code == 0 else {"report_md", "report_html"})
        self.assertTrue(r["needs_you"])
        self.assertLessEqual(len(r["next_steps"]), 4)
        pinned_titles = [p["title"] for p in r["pinned_integrity"]]
        self.assertTrue(any("300%" in t for t in pinned_titles), pinned_titles)

    def test_final_stage_report(self):
        r = S.load(os.path.join(self.work, "report.json"))
        self.assertEqual(r["stage"], "final")
        self.assertEqual(r["candidate"], "Riley Castellano")
        statuses = dict((w["issue_id"], w["status"]) for w in r["weaknesses"])
        self.assertEqual(statuses["I1"], "gap")
        self.assertEqual(statuses["I5"], "fixed")
        self.assertEqual(r["changes"]["cut"][0]["ref"], "R14")
        self.assertTrue(r["changes"]["cut"][0]["text"].startswith("Increased online sales"))
        self.assertTrue(r["changes"]["reordered"])
        # Live tests A24/6.11: resume.json claims I6 (required terms) fixed, but the re-read of the new .docx
        # still cannot find "communication", so the report lowers it to needs_you and asks with the re-check.
        self.assertEqual(statuses["I6"], "needs_you")
        self.assertEqual(r["needs_you"], [{"where": "Experience: Tallgrass Outfitters",
                                           "ask": "Roughly what share of subscribers opened the weekly newsletter?"},
                                          {"where": "Required job terms are missing from your resume",
                                           "ask": "Re-check of the new resume: communication still not found."}])
        notes = self.A["report_final"].data["notes"]
        self.assertTrue(any(n.startswith("I6: the rewrite marked it fixed") for n in notes), notes)
        kw = dict((k["term"], k["status"]) for k in r["keyword_gaps"])
        self.assertEqual(kw.get("VLOOKUP"), "added_with_evidence")
        self.assertLessEqual(len(r["keyword_gaps"]), 6)
        self.assertLessEqual(len(r["disagreements"]), 2)
        self.assertLessEqual(len(r["strengths"]), 4)
        self.assertLessEqual(len(r["interview_prep"]), 6)
        self.assertLessEqual(len(r["knockouts"]), 4)
        self.assertEqual(r["screening"]["after_source"], "docx")
        self.assertIsNone(r["panel_after"])
        # Sections 17.4 and 17.5: 4 of 7 and major issues, so not strong; the Skeptic came closest to no.
        self.assertIs(r["strong_resume"], False)
        self.assertEqual(r["verdict_strip"]["strong_line"], "")
        self.assertEqual((r["closest_to_reject"]["reviewer"], r["closest_to_reject"]["verdict"]), ("skeptic", "lean_no"))
        self.assertEqual(r["closest_to_reject"]["issue_id"], "I5")
        recruiter = S.load(os.path.join(self.work, "reviews", "recruiter.json"))
        self.assertEqual(r["first_impression"], recruiter["lens_data"]["seven_second_takeaway"])
        summary = self.A["report_final"].data["summary"]
        self.assertEqual((summary["strong_resume"], summary["strong_line"], summary["first_impression"]),
                         (False, "", r["first_impression"]))
        self.assertEqual(summary["mixed_line"], r["verdict_strip"]["mixed_line"])
        self.assertEqual(summary["real_gaps"], [g["title"] for g in r["real_gaps"]])
        md = S.read(os.path.join(self.run_a, "Hiring_Panel_Report.md"))
        self.assertIn("What a recruiter sees in 7 seconds:", md)
        self.assertNotIn("Strong resume", md)

    def test_report_md_order_is_weaknesses_first(self):
        md = S.read(os.path.join(self.run_a, "Hiring_Panel_Report.md"))
        order = ["## Fix before you send", "## Biggest weaknesses", "## What changed", "## The panel",
                 "## Keyword gaps", "## What\u2019s already working", "## Interview prep", "## Mode and limitations"]
        order = [h.replace("\u2019", "'") if h.replace("\u2019", "'") in md else h for h in order]
        pos = [md.find(h) for h in order]
        self.assertTrue(all(p >= 0 for p in pos), list(zip(order, pos)))
        self.assertEqual(pos, sorted(pos))


class RecheckTest(unittest.TestCase):
    """recheck builds RUN/recheck from the new .docx; a fresh panel there feeds panel_after."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="hp-e2e-recheck-")
        cls.rec = {}
        cls.run_dir = pipeline(cls.tmp, S.env(pdf_engines="builtin"), cls.rec)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_recheck_flow(self):
        environ = S.env(pdf_engines="builtin")
        r = S.hp(["recheck", self.run_dir], self.tmp, environ)
        self.assertEqual(r.code, 0, r)
        target = r.data["run"]
        self.assertEqual(target, os.path.join(self.run_dir, "recheck"))
        for name in ("resume.md", "ats_view.txt", "jd.md", "ledger.json", "original.docx", "terms.json"):
            self.assertTrue(os.path.isfile(os.path.join(target, "work", "inputs", name)), name)
        self.assertTrue(os.path.isfile(os.path.join(target, "work", "screening", "before", "brief.json")))
        state = S.load(os.path.join(target, "work", "state.json"))
        self.assertEqual(state["recheck_of"], self.run_dir)
        # a fresh "panel" for the recheck: minimal valid reviews with no line findings
        ledger = S.load(os.path.join(target, "work", "inputs", "ledger.json"))
        self.assertGreater(len(ledger["resume_lines"]), 20)
        rdir = os.path.join(target, "work", "reviews")
        os.makedirs(rdir)
        for rid in S.REVIEWER_IDS:
            review = S.load(os.path.join(S.REVIEWS, rid + ".json"))
            review["findings"], review["strengths"], review["questions_for_candidate"] = [], [], []
            for d in review["dimension_scores"]:
                d["evidence_anchors"] = []
            review["advance"] = "yes"
            with open(os.path.join(rdir, rid + ".json"), "w", encoding="utf-8") as f:
                json.dump(review, f)
        s = S.hp(["synthesize", target, "--mode", "parallel"], self.tmp, environ)
        self.assertEqual(s.code, 0, s)
        rep = S.hp(["report", self.run_dir], self.tmp, environ)
        self.assertIn(rep.code, (0, 4), rep)
        report = S.load(os.path.join(self.run_dir, "work", "report.json"))
        self.assertEqual(report["panel_after"]["note"], "Re-read by fresh reviewers; directional.")
        self.assertEqual(report["panel_after"]["vote_label"], "7 of 7 would move you forward")
        self.assertIn("directional", S.read(os.path.join(self.run_dir, "Hiring_Panel_Report.md")))
        # a second recheck keeps the first one (renamed), never deletes it
        r2 = S.hp(["recheck", self.run_dir], self.tmp, environ)
        self.assertEqual(r2.code, 0, r2)
        self.assertTrue(os.path.isdir(os.path.join(self.run_dir, "recheck-prev-1", "work", "reviews")))


if __name__ == "__main__":
    unittest.main()
