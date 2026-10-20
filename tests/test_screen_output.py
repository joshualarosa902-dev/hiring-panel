"""hp.screen outputs: schema validity, determinism, the student-facing Markdown, the subagent brief,
robustness on garbage, missing data files, no network, sources and performance."""
import json
import os
import shutil
import socket
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_screen_support as S  # noqa: E402

from hp.screen import LexiconError, load_lexicon, make_brief, render_screening_md, run_screening  # noqa: E402
from hp.screen.constants import CATALOGUE, PLATFORM_NOTES  # noqa: E402
from hp.screen.lexicon import REQUIRED_FILES, default_data_dir  # noqa: E402

CLEAN = S.fixture("resume_clean.txt")
MESSY = S.fixture("resume_messy.txt")
JD = S.fixture("jd_marketing.txt")
PERFECT = S.fixture("jd_perfect.txt")
SCHEMA = S.load_schema()
SOURCES = os.path.join(S.SCRIPTS, "hp", "screen", "sources.json")


def variety():
    """A spread of results covering every code path that changes the output shape."""
    es = ("Lucía Ejemplo\nMadrid, España | lucia.ejemplo@example.com\nEXPERIENCIA\n"
          "• Gestioné las redes sociales de la empresa y creé contenido para la página web de la tienda\n"
          "• Analicé los datos de ventas con Excel y preparé informes para el equipo de dirección\n")
    terms = [{"term": "campaign performance", "importance": "required",
              "jd_quote": "Build weekly dashboards in Tableau to track campaign performance"},
             {"term": "Kubernetes", "importance": "required", "jd_quote": "Kubernetes clusters"}]
    return [
        ("clean", S.screen(CLEAN, JD)),
        ("clean-perfect", S.screen(CLEAN, PERFECT, jd_url="https://jobs.lever.co/example/1")),
        ("messy", S.screen(S.make_doc(MESSY, header_footer=[("header", "jordan@example.com | 555-010-0199")]), JD)),
        ("no-jd", S.screen(CLEAN, "")),
        ("thin-jd", S.screen(CLEAN, "Intern. SQL and Excel.")),
        ("spanish", S.screen(es, JD)),
        ("image", S.screen(S.make_doc("", fmt="image", signals={"image_only": True}), JD)),
        ("empty-dict", run_screening({}, JD, as_of=S.AS_OF, data_dir=S.DATA)),
        ("terms", S.screen(CLEAN, JD, terms=terms)),
        ("uk", S.screen(CLEAN, JD, locale="en-GB", stage="experienced")),
        ("docx-hazards", S.screen(S.make_doc(CLEAN, fmt="docx", method="docx-xml", pages=4, bytes=3000000,
                                             signals={"tables": {"count": 2, "nested": 1},
                                                      "hidden_text": {"tiny": 3}, "tab_merged_tokens": 1}), JD)),
    ]


class SchemaTests(unittest.TestCase):
    def test_schema_is_well_formed(self):
        self.assertEqual(SCHEMA["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertIn("blocks", SCHEMA["properties"]["inputs"]["properties"]["job_description"]["properties"])
        for key in ("language", "locale"):
            self.assertIn(key, SCHEMA["required"])

    def test_outputs_validate(self):
        for name, r in variety():
            with self.subTest(case=name):
                errs = S.validate(r, SCHEMA)
                self.assertEqual(errs, [], "\n".join(errs[:10]))

    def test_validator_catches_errors(self):
        r = S.screen(CLEAN, JD)
        r["scores"]["overall"]["value"] = 72
        r["issues"].append({"id": "BAD"})
        r["surprise"] = 1
        errs = S.validate(r, SCHEMA)
        self.assertTrue(any("multiple" in e for e in errs))
        self.assertTrue(any("unexpected key surprise" in e for e in errs))
        self.assertTrue(any("issues[" in e for e in errs))

    def test_source_refs_exist(self):
        with open(SOURCES, encoding="utf-8") as f:
            keys = set(json.load(f)["sources"])
        for iid, c in CATALOGUE.items():
            for ref in c["refs"]:
                self.assertIn(ref, keys, iid)
        for notes in PLATFORM_NOTES.values():
            for _t, refs in notes:
                for ref in refs:
                    self.assertIn(ref, keys)


class DeterminismTests(unittest.TestCase):
    def test_same_inputs_same_bytes(self):
        d1 = json.dumps(S.screen(S.make_doc(MESSY), JD), ensure_ascii=False, indent=2)
        load_lexicon.__globals__["_CACHE"].clear()          # a cold dictionary load gives the same bytes
        d2 = json.dumps(S.screen(S.make_doc(MESSY), JD), ensure_ascii=False, indent=2)
        self.assertEqual(d1, d2)

    def test_same_bytes_across_processes_and_hash_seeds(self):
        import subprocess
        code = ("import json,sys; sys.path.insert(0, %r); import test_screen_support as S; "
                "r = S.screen(S.make_doc(S.fixture('resume_messy.txt')), S.fixture('jd_marketing.txt'), "
                "terms=[{'term': 'campaign performance', 'importance': 'required', "
                "'jd_quote': 'track campaign performance'}]); "
                "sys.stdout.write(json.dumps(r, ensure_ascii=True, indent=2))") % S.HERE
        outs = []
        for seed in ("1", "2", "777"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            outs.append(subprocess.run([sys.executable, "-c", code], env=env, stdout=subprocess.PIPE,
                                       check=True, timeout=60).stdout)
        self.assertTrue(outs[0])
        self.assertEqual(outs[0], outs[1])
        self.assertEqual(outs[0], outs[2])

    def test_generated_at_is_the_as_of_date(self):
        r = S.screen(CLEAN, JD, as_of="2027-01-31")
        self.assertEqual(r["generated_at"], "2027-01-31")
        self.assertEqual(r["as_of"], "2027-01-31")

    def test_input_is_not_mutated(self):
        doc = S.make_doc(MESSY)
        before = json.dumps(doc, sort_keys=True)
        S.screen(doc, JD)
        self.assertEqual(json.dumps(doc, sort_keys=True), before)


class MarkdownTests(unittest.TestCase):
    def test_wording_and_masking(self):
        for name, r in variety():
            with self.subTest(case=name):
                md = render_screening_md(r)
                self.assertTrue(md.startswith("# Simulated screening check"))
                self.assertNotIn("ats score", md.lower())
                self.assertNotIn("—", md)
                for raw in ("avery.quinn@example.com", "010-0142", "jordan@example.com", "010-0199",
                            "lucia.ejemplo@example.com"):
                    self.assertNotIn(raw, md)
                self.assertIn("This is a simulation, not a real applicant tracking system.", md)

    def test_masked_contact_and_counts_shown(self):
        md = render_screening_md(S.screen(CLEAN, JD))
        self.assertIn("a***@e***.com", md)
        self.assertIn("***-***-0142", md)
        self.assertIn("Required terms:", md)
        self.assertIn("Biggest issues first", md)

    def test_untrusted_text_cannot_inject_html_or_break_tables(self):
        jd = PERFECT.replace("- A/B testing", "- A/B testing\n- <script>alert(1)</script> | Excel")
        md = render_screening_md(S.screen(CLEAN.replace("Avery Quinn", "Avery <b>Quinn</b>"), jd))
        self.assertNotIn("<script>", md)
        self.assertNotIn("<b>", md)

    def test_garbage_result_renders(self):
        for bad in (None, {}, {"scores": "x", "issues": [None, 1]}, {"keywords": {"required": [{}]}}):
            self.assertTrue(render_screening_md(bad).startswith("# Simulated screening check"))


class BriefTests(unittest.TestCase):
    def test_shape_and_limits(self):
        r = S.screen(S.make_doc(MESSY, header_footer=[("header", "jordan@example.com | 555-010-0199")]), JD)
        b = make_brief(r)
        self.assertEqual(sorted(b), sorted(["scores", "precision_note", "disclaimer", "top_issues", "keywords",
                                            "coverage", "knockouts", "job_title", "platform_guess", "language"]))
        self.assertEqual(sorted(b["scores"]), sorted(["overall", "parse_safety", "keyword_match", "content_signals"]))
        for v in b["scores"].values():
            self.assertEqual(sorted(v), ["band", "value"])
        self.assertLessEqual(len(b["top_issues"]), 12)
        self.assertLessEqual(len(b["keywords"]), 30)
        for it in b["top_issues"]:
            self.assertEqual(sorted(it), ["evidence", "id", "severity", "title"])
            self.assertLessEqual(len(it["evidence"]), 160)
        for k in b["keywords"]:
            self.assertEqual(sorted(k), sorted(["term", "importance", "found", "match_type", "evidence_level",
                                                "resume_wording"]))
        text = json.dumps(b, ensure_ascii=False, indent=2)
        self.assertNotIn("jordan@example.com", text)
        self.assertLess(len(text), 9500)          # about 2k tokens
        self.assertEqual(b["top_issues"][0]["id"], r["issues"][0]["id"])
        self.assertEqual(b["coverage"]["summary"], "Required terms: 1 of 5 found (1 only in your skills list).")

    def test_brief_on_garbage(self):
        self.assertIn("scores", make_brief(None))
        self.assertIn("scores", make_brief({"issues": "x", "keywords": None}))


class RobustnessTests(unittest.TestCase):
    def test_hostile_documents_never_raise(self):
        huge = "x" * 200000
        cases = [None, 5, "text", [], {"lines": "nope"}, {"lines": [None, 3, {"text": 7}, {"text": "ok"}]},
                 {"signals": "bad", "lines": [{"text": huge}]}, {"lines": [{"text": "a\u0000b�" * 50}]},
                 {"lines": [{"text": "• " * 5000}]}, {"lines": [{"text": "Jan 2020 – " * 2000}]},
                 {"lines": [{"text": "x"} for _ in range(6000)]},
                 {"format": "pdf", "pages": "2", "bytes": "big", "signals": {"fonts": {"type0": "x"},
                                                                          "columns": {"pdf_gutter_pages": None}}},
                 {"header_footer": "no", "errors": ["bad"], "warnings": [None, 5]}]
        for doc in cases:
            r = run_screening(doc, JD, as_of=S.AS_OF, data_dir=S.DATA)
            self.assertEqual(S.validate(r, SCHEMA), [])

    def test_hostile_job_postings_never_raise(self):
        for jd in (None, 7, b"\xff\xfe bytes", "(" * 5000, "Requirements\n" + "- SQL (" * 3000,
                   "\n".join("Requirements:" for _ in range(500)), "R" * 100000):
            r = S.screen(CLEAN, jd)
            self.assertEqual(S.validate(r, SCHEMA), [])

    def test_pathological_character_runs_stay_fast(self):
        import string
        units = list(string.punctuation) + ["a", "A", "1", "a.", "a-", "a@", "1.", "1/", "Jan ", "R ", "(a", "Aa",
                                            "• ", "\u00e9", "\u4e2d", "+1", "C++ ", ".NET ", "www.", "http://a", "I "]
        for u in units:
            line = (u * (2000 // len(u)))[:2000]
            t0 = time.time()
            r = run_screening(S.make_doc(line + "\n" + CLEAN + "\n" + line),
                              JD + "\n" + u * (20000 // len(u)), as_of=S.AS_OF, data_dir=S.DATA)
            render_screening_md(r)
            make_brief(r)
            self.assertLess(time.time() - t0, 2.0, repr(u))

    def test_container_types_are_sanitized(self):
        doc = {"errors": 5, "warnings": "abc", "lines": [{"text": "hello", "where": 5, "list": "yes"}],
               "signals": {"columns": {"pdf_gutter_pages": "abc"}, "fonts": "x", "images": [1]},
               "header_footer": [{"where": 3, "text": None}, "str", {"text": "a@b.co"}]}
        r = run_screening(doc, JD, as_of=S.AS_OF, data_dir=S.DATA)
        self.assertEqual(S.validate(r, SCHEMA), [])
        self.assertNotIn("a", r["extraction"]["warnings"])
        self.assertNotIn("PARSE-009", S.issue_ids(r))

    def test_bad_arguments_fall_back(self):
        r = S.screen(CLEAN, JD, as_of="2026-13-45", stage="phd", locale="english")
        self.assertEqual(r["level"], "student")
        self.assertEqual(r["locale"], "en-US")
        self.assertRegex(r["as_of"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertTrue(r["extraction"]["warnings"])


class DataFileTests(unittest.TestCase):
    def test_missing_data_file_fails_clearly(self):
        tmp = tempfile.mkdtemp()
        try:
            for f in REQUIRED_FILES:
                if f != "skills.json":
                    shutil.copy(os.path.join(S.DATA, f), tmp)
            with self.assertRaises(LexiconError) as cm:
                load_lexicon(tmp)
            self.assertIn("skills.json", str(cm.exception))
            with self.assertRaises(LexiconError):
                load_lexicon(os.path.join(tmp, "nope"))
        finally:
            shutil.rmtree(tmp)

    def test_bad_json_fails_clearly(self):
        tmp = tempfile.mkdtemp()
        try:
            for f in REQUIRED_FILES:
                shutil.copy(os.path.join(S.DATA, f), tmp)
            with open(os.path.join(tmp, "headings.json"), "w") as f:
                f.write("{not json")
            with self.assertRaises(LexiconError) as cm:
                load_lexicon(tmp)
            self.assertIn("headings.json", str(cm.exception))
        finally:
            shutil.rmtree(tmp)

    def test_lexicon_tolerates_odd_entries(self):
        tmp = tempfile.mkdtemp()
        try:
            for f in REQUIRED_FILES:
                shutil.copy(os.path.join(S.DATA, f), tmp)
            with open(os.path.join(tmp, "skills.json"), "w") as f:
                json.dump({"version": "x", "entries": [None, {"canonical": ""}, {"canonical": "Excel", "kind": "?",
                                                                                 "aliases": "bad", "implies": [5]},
                                                       {"id": "excel", "canonical": "Dup"}]}, f)
            lex = load_lexicon(tmp)
            self.assertEqual([e["canonical"] for e in lex.entries], ["Excel"])
            self.assertTrue(lex.warnings)
        finally:
            shutil.rmtree(tmp)

    @unittest.skipUnless(all(os.path.isfile(os.path.join(default_data_dir(), f)) for f in REQUIRED_FILES),
                         "shipped hp/data is not complete yet")
    def test_shipped_data_works(self):
        r = run_screening(S.make_doc(CLEAN), JD, as_of=S.AS_OF)
        self.assertEqual(S.validate(r, SCHEMA), [])
        self.assertTrue(r["keywords"]["required"])
        self.assertIsNotNone(S.term(r, "SQL"))


class NoNetworkTests(unittest.TestCase):
    def test_no_sockets(self):
        real = socket.socket

        def boom(*a, **k):
            raise AssertionError("network access attempted")
        socket.socket = boom
        try:
            r = S.screen(CLEAN, JD, jd_url="https://jobs.lever.co/example/1")
            render_screening_md(r)
            make_brief(r)
        finally:
            socket.socket = real


class PerformanceTests(unittest.TestCase):
    def test_two_page_resume_under_two_seconds(self):
        body = CLEAN.split("SKILLS")[0]
        extra = "\n".join("Role %d | Example Org %d | Austin, TX | Jan 20%02d – Dec 20%02d\n"
                          "• Built %d dashboards in Tableau and SQL for %d stores across the region\n"
                          "• Wrote weekly reports in Excel with pivot tables for %d managers and teams" %
                          (i, i, 10 + i, 10 + i, i, i * 3, i * 2) for i in range(1, 9))
        text = body + extra + "\nSKILLS\nExcel, SQL, Python, Tableau\n"
        jd = JD * 4
        data_dir = default_data_dir() if all(os.path.isfile(os.path.join(default_data_dir(), f))
                                            for f in REQUIRED_FILES) else S.DATA
        load_lexicon(data_dir)       # dictionary load is cached once per process; time the screening
        t0 = time.time()
        r = run_screening(S.make_doc(text), jd, as_of=S.AS_OF, data_dir=data_dir)
        md = render_screening_md(r)
        make_brief(r)
        elapsed = time.time() - t0
        self.assertTrue(md)
        self.assertLess(elapsed, 2.0)

    def test_cold_load_under_two_seconds(self):
        load_lexicon.__globals__["_CACHE"].clear()
        t0 = time.time()
        S.screen(CLEAN, JD)
        self.assertLess(time.time() - t0, 2.0)


if __name__ == "__main__":
    unittest.main()
