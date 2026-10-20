"""Tests for hp.panel.ledger (ARCHITECTURE.md section 7). Fictional data only."""
import copy
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

from hp.panel.common import PanelError, ledger_problems  # noqa: E402
from hp.panel.ledger import (apply_overrides, build_ledger, build_run_ledger,  # noqa: E402
                             collapse_letter_spacing, jd_blocks_from_screening, kinds_summary,
                             ledger_to_text, split_sentences)

FIXTURE = os.path.join(HERE, "fixtures", "panel", "run_basic")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


TARGET = {"role_title": "Data Analyst Intern", "role_level": "intern", "company": "Northwind Health",
          "locale": "en-US"}


class FixtureLedgerTest(unittest.TestCase):
    def setUp(self):
        self.resume = _read(os.path.join(FIXTURE, "work", "inputs", "resume.md"))
        self.screening = _json(os.path.join(FIXTURE, "work", "screening", "before", "screening.json"))
        self.blocks = jd_blocks_from_screening(self.screening)

    def test_reproduces_committed_ledger(self):
        built = build_ledger(self.resume, self.blocks, TARGET)
        self.assertEqual(built, _json(os.path.join(FIXTURE, "work", "inputs", "ledger.json")))

    def test_r_ids_number_non_empty_lines_including_header(self):
        led = build_ledger(self.resume, self.blocks, TARGET)
        non_empty = [ln.strip() for ln in self.resume.splitlines() if ln.strip()]
        self.assertEqual([r["text"] for r in led["resume_lines"]], non_empty)
        self.assertEqual([r["id"] for r in led["resume_lines"]],
                         ["R{}".format(i) for i in range(1, len(non_empty) + 1)])
        self.assertEqual(led["resume_lines"][0]["section"], "header_footer")
        self.assertTrue(led["resume_lines"][0]["text"].startswith("[header] "))

    def test_sections(self):
        led = build_ledger(self.resume, self.blocks, TARGET)
        sec = {r["id"]: r["section"] for r in led["resume_lines"]}
        self.assertEqual(sec["R2"], "contact")
        self.assertEqual(sec["R5"], "education")
        self.assertEqual(sec["R9"], "experience")
        self.assertEqual(sec["R14"], "projects")
        self.assertEqual(sec["R17"], "skills")

    def test_j_ids_partition_blocks_with_kind_map(self):
        led = build_ledger(self.resume, self.blocks, TARGET)
        all_lines = [ln for b in self.blocks for ln in b["lines"] if ln.strip()]
        self.assertEqual([j["text"] for j in led["jd_items"]], all_lines)
        kinds = {j["id"]: j["kind"] for j in led["jd_items"]}
        self.assertEqual(kinds["J1"], "other")             # unspecified
        self.assertEqual(kinds["J3"], "company")           # boilerplate, about the company
        self.assertEqual(kinds["J5"], "responsibility")
        self.assertEqual(kinds["J9"], "must")              # required
        self.assertEqual(kinds["J13"], "nice")             # preferred
        self.assertEqual(kinds["J14"], "logistics")        # boilerplate: location / hybrid
        self.assertEqual(kinds["J15"], "company")          # boilerplate: EEO statement (reviewers ignore it)
        self.assertEqual([j["block"] for j in led["jd_items"]][:3], [0, 1, 1])
        self.assertEqual(led["target"]["general_review"], False)
        self.assertEqual(ledger_problems(led), [])

    def test_kinds_summary(self):
        led = build_ledger(self.resume, self.blocks, TARGET)
        self.assertEqual(kinds_summary(led), {"must": 4, "nice": 2, "responsibility": 4, "company": 3,
                                              "logistics": 1, "other": 1})


class KindMapTest(unittest.TestCase):
    def test_boilerplate_logistics_vs_company(self):
        blocks = [{"kind": "boilerplate", "heading": "Benefits", "lines": [
            "Benefits", "Competitive pay of $22 per hour", "We sponsor visas for this role",
            "Travel up to 10%", "We love building great products together",
            "Our mission is to make clinics faster"]}]
        led = build_ledger("x", blocks, {})
        kinds = [j["kind"] for j in led["jd_items"]]
        # Benefits are what the employer offers (company); pay, visas and travel are logistics.
        self.assertEqual(kinds, ["company", "logistics", "logistics", "logistics", "company", "company"])

    def test_eeo_and_benefits_are_company(self):
        blocks = [{"kind": "boilerplate", "heading": None, "lines": [
                      "Health, dental and vision insurance plus 401(k) matching",
                      "Westbrook Clinic is an equal opportunity employer.",
                      "We provide reasonable accommodations to applicants with disabilities.",
                      "Must be authorized to work in the US; no visa sponsorship.",
                      "Pay: $19 to $21 per hour"]},
                  {"kind": "required", "heading": None, "lines": [
                      "Valid CPR card",
                      "All qualified applicants will receive consideration without regard to race or religion."]}]
        kinds = [j["kind"] for j in build_ledger("x", blocks, {})["jd_items"]]
        self.assertEqual(kinds, ["company", "company", "company", "logistics", "logistics", "must", "company"])

    def test_unknown_block_kind_is_other(self):
        led = build_ledger("x", [{"kind": "weird", "lines": ["A line"]}], {})
        self.assertEqual(led["jd_items"][0]["kind"], "other")


class SectionLabelTest(unittest.TestCase):
    """Finding 2.1: section labels follow the headings a person sees (fictional resumes)."""

    def sections(self, text):
        return [(r["text"], r["section"]) for r in build_ledger(text, [], {})["resume_lines"]]

    def test_letter_spaced_headings(self):
        text = "\n".join([
            "MORGAN", "FIELDS", "Aspiring Analyst", "C O N T A C T", "morgan@example.com", "Dayton, OH",
            "S K I L L S", "Python \u2022 \u2022 \u2022 \u25cb", "E D U C A T I O N", "Riverbend College",
            "B.A. Economics, Expected May 2028", "W O R K   E X P E R I E N C E", "Tutor, Learning Center",
            "Tutored 5 students in algebra", "P R O J E C T S", "Budget tracker in Excel",
            "L E A D E R S H I P", "Secretary, Chess Club"])
        sec = dict(self.sections(text))
        self.assertEqual(sec["C O N T A C T"], "contact")
        self.assertEqual(sec["Dayton, OH"], "contact")
        self.assertEqual(sec["Python \u2022 \u2022 \u2022 \u25cb"], "skills")
        self.assertEqual(sec["Riverbend College"], "education")
        self.assertEqual(sec["B.A. Economics, Expected May 2028"], "education")
        self.assertEqual(sec["Tutored 5 students in algebra"], "experience")
        self.assertEqual(sec["Budget tracker in Excel"], "projects")
        self.assertEqual(sec["Secretary, Chess Club"], "leadership")
        # the ledger keeps the verbatim text
        self.assertIn("E D U C A T I O N", [t for t, _ in self.sections(text)])

    def test_collapse_letter_spacing(self):
        self.assertEqual(collapse_letter_spacing("E D U C A T I O N"), "EDUCATION")
        self.assertEqual(collapse_letter_spacing("W O R K   E X P E R I E N C E"), "WORK EXPERIENCE")
        self.assertEqual(collapse_letter_spacing("Python \u2022 \u2022 \u2022 \u2022 \u25cb"),
                         "Python \u2022 \u2022 \u2022 \u2022 \u25cb")
        self.assertEqual(collapse_letter_spacing("Led a team of 4"), "Led a team of 4")

    def test_mixed_case_standard_headings(self):
        text = "\n".join(["Riley Chen", "Fargo, ND | riley@example.com", "Education",
                          "Prairie State University, Pre-Nursing, first year", "Expected graduation: May 2029",
                          "Work", "Cashier, Corner Market, 2024 - present", "Bagged groceries",
                          "Volunteer", "Volunteer, Fargo Food Shelf, 2023", "Skills", "CPR certified"])
        sec = dict(self.sections(text))
        self.assertEqual(sec["Education"], "education")
        self.assertEqual(sec["Prairie State University, Pre-Nursing, first year"], "education")
        self.assertEqual(sec["Expected graduation: May 2029"], "education")
        self.assertEqual(sec["Cashier, Corner Market, 2024 - present"], "experience")
        self.assertEqual(sec["Volunteer, Fargo Food Shelf, 2023"], "leadership")
        self.assertEqual(sec["CPR certified"], "skills")

    def test_education_in_top_block_without_headings(self):
        text = "Riley Chen\nriley@example.com\nPrairie State University, B.S. Biology\nGPA 3.5"
        self.assertEqual([s for _, s in self.sections(text)], ["contact", "contact", "education", "education"])

    def test_builtin_headings_when_lexicon_missing(self):
        from unittest import mock
        import hp.panel.ledger as ledger_mod
        ledger_mod._SYNONYMS = None
        try:
            with mock.patch("hp.panel.ledger.open", side_effect=OSError("missing"), create=True):
                sec = dict(self.sections("Sam Lee\nEducation\nRiverbend College\nWork\nCashier"))
            self.assertEqual((sec["Riverbend College"], sec["Cashier"]), ("education", "experience"))
        finally:
            ledger_mod._SYNONYMS = None

    def test_job_title_lines_are_not_headings(self):
        text = "EXPERIENCE\nResearch Assistant, Biology Lab\nResearch\nMapped bird nests"
        self.assertEqual([s for _, s in self.sections(text)], ["experience", "experience", "experience",
                                                                 "experience"])


class SentenceSplitTest(unittest.TestCase):
    """Finding 2.14: one J item per sentence; the split is lossless."""

    LINE = ("Requirements: High school diploma or GED. Current BLS/CPR certification. Ability to lift 50 lbs "
            "and stand for long periods. Excellent communication and teamwork.")

    def test_label_and_sentences(self):
        self.assertEqual(split_sentences(self.LINE), [
            "Requirements:", "High school diploma or GED.", "Current BLS/CPR certification.",
            "Ability to lift 50 lbs and stand for long periods.", "Excellent communication and teamwork."])

    def test_lossless_partition(self):
        blocks = [{"kind": "required", "lines": [self.LINE, "- Experience with Excel (pivot tables, lookups)"]},
                  {"kind": "boilerplate", "lines": [
                      "Must be authorized to work in the US.  Lakeview Labs is an equal opportunity employer."]}]
        led = build_ledger("x", blocks, {})
        texts = [j["text"] for j in led["jd_items"]]
        source = [ln for b in blocks for ln in b["lines"]]
        self.assertEqual(" ".join(texts), " ".join(" ".join(ln.split()) for ln in source))
        self.assertEqual([j["id"] for j in led["jd_items"]], ["J{}".format(i) for i in range(1, len(texts) + 1)])
        self.assertEqual([j["kind"] for j in led["jd_items"]][-2:], ["logistics", "company"])
        self.assertTrue(all(j["kind"] == "must" for j in led["jd_items"][:6]))
        self.assertEqual(ledger_problems(led), [])

    def test_abbreviations_and_single_sentences_stay_whole(self):
        for line in ("Bachelor's degree (B.S. or B.A.) in a U.S. accredited program",
                     "Experience with Excel, Word, etc. preferred",
                     "Location: Austin, TX (hybrid, 3 days a week)",
                     "Dr. Patel leads the St. Louis clinic"):
            self.assertEqual(split_sentences(line), [line], line)
        self.assertEqual(split_sentences("Must hold a B.S. Degree. Travel up to 10%."),
                         ["Must hold a B.S. Degree.", "Travel up to 10%."])


class CompactFileTest(unittest.TestCase):
    """Finding A4: the ledger file is compact (one line per item) and round-trips exactly."""

    def test_round_trip_and_one_line_per_item(self):
        resume = _read(os.path.join(FIXTURE, "work", "inputs", "resume.md"))
        blocks = jd_blocks_from_screening(_json(os.path.join(FIXTURE, "work", "screening", "before",
                                                             "screening.json")))
        led = build_ledger(resume, blocks, TARGET)
        text = ledger_to_text(led)
        self.assertEqual(json.loads(text), led)
        self.assertEqual(ledger_to_text(led), text)
        lines = text.splitlines()
        self.assertEqual(sum(1 for ln in lines if '"id": "R' in ln), len(led["resume_lines"]))
        self.assertEqual(sum(1 for ln in lines if '"id": "J' in ln), len(led["jd_items"]))
        self.assertLess(text.index('"jd_items"'), text.index('"resume_lines"'))
        self.assertLess(len(text), len(json.dumps(led, indent=2, ensure_ascii=False)) * 0.8)
        empty = build_ledger("", [], {})
        self.assertEqual(json.loads(ledger_to_text(empty)), empty)


class GeneralReviewTest(unittest.TestCase):
    def test_no_blocks_means_general_review(self):
        led = build_ledger("Jordan Rivera\nEXPERIENCE\nBarista", [], {"role_title": "Analyst"})
        self.assertEqual(led["jd_items"], [])
        self.assertTrue(led["target"]["general_review"])
        self.assertEqual(led["target"]["role_level"], "unknown")
        self.assertEqual(led["target"]["locale"], "en-US")

    def test_explicit_general_review_drops_posting(self):
        led = build_ledger("x", [{"kind": "required", "lines": ["SQL"]}], {"general_review": True})
        self.assertEqual(led["jd_items"], [])
        self.assertTrue(led["target"]["general_review"])


class GarbageInputTest(unittest.TestCase):
    def test_garbage_never_raises(self):
        for resume in (None, b"\xff\xfe bytes", 12, "", "\x00\x01\n\n  \n", "line\r\nline2\rline3"):
            for blocks in (None, "nope", [None, 3, {"kind": "required"}, {"lines": "a\nb"},
                                          {"kind": "required", "lines": [None, 5, "ok"]}]):
                led = build_ledger(resume, blocks, "not a dict")
                self.assertIn("resume_lines", led)
                self.assertEqual(ledger_problems(led), [])

    def test_control_characters_removed(self):
        led = build_ledger("Jordan\x07 Rivera\n\x00\n", [], {})
        self.assertEqual(led["resume_lines"], [{"id": "R1", "section": "contact", "text": "Jordan  Rivera"}])

    def test_all_caps_employer_does_not_change_section(self):
        led = build_ledger("EXPERIENCE\nBRIGHTPATH CO\nDid things", [], {})
        self.assertEqual([r["section"] for r in led["resume_lines"]], ["experience"] * 3)

    def test_no_headings_only_top_lines_are_contact(self):
        text = "\n".join("line {}".format(i) for i in range(8))
        led = build_ledger(text, [], {})
        self.assertEqual([r["section"] for r in led["resume_lines"]], ["contact"] * 5 + ["other"] * 3)


class OverrideTest(unittest.TestCase):
    def setUp(self):
        blocks = [{"kind": "unspecified", "lines": ["Title"]}, {"kind": "required", "lines": ["Needs SQL"]}]
        self.led = build_ledger("Jordan", blocks, {})

    def test_apply_and_log(self):
        before = copy.deepcopy(self.led)
        new, log = apply_overrides(self.led, {"J1": "must", "J2": "nice"})
        self.assertEqual([j["kind"] for j in new["jd_items"]], ["must", "nice"])
        self.assertEqual(log, [{"id": "J1", "from": "other", "to": "must"},
                               {"id": "J2", "from": "must", "to": "nice"}])
        self.assertEqual(self.led, before, "input ledger must not be modified")

    def test_cli_style_pairs(self):
        new, log = apply_overrides(self.led, ["J1=company"])
        self.assertEqual(new["jd_items"][0]["kind"], "company")
        self.assertEqual(len(log), 1)

    def test_errors(self):
        with self.assertRaises(ValueError):
            apply_overrides(self.led, {"J9": "must"})        # unknown id
        with self.assertRaises(ValueError):
            apply_overrides(self.led, {"R1": "must"})        # resume lines have no kind
        with self.assertRaises(ValueError):
            apply_overrides(self.led, {"J1": "critical"})    # unknown kind
        with self.assertRaises(ValueError):
            apply_overrides(self.led, ["J1"])                # malformed pair
        with self.assertRaises(ValueError):
            apply_overrides({"nope": 1}, {"J1": "must"})


class RunLedgerTest(unittest.TestCase):
    def test_build_run_ledger_writes_file_and_reapplies_overrides(self):
        tmp = tempfile.mkdtemp(prefix="hp-panel-")
        try:
            run = os.path.join(tmp, "run")
            shutil.copytree(FIXTURE, run)
            os.remove(os.path.join(run, "work", "inputs", "ledger.json"))
            led, log = build_run_ledger(run, TARGET, overrides=[{"id": "J1", "from": "other", "to": "company"}])
            self.assertEqual(led["jd_items"][0]["kind"], "company")
            self.assertEqual(log, [{"id": "J1", "from": "other", "to": "company"}])
            self.assertEqual(_json(os.path.join(run, "work", "inputs", "ledger.json")), led)
            self.assertEqual(_read(os.path.join(run, "work", "inputs", "ledger.json")), ledger_to_text(led))
            with self.assertRaises(PanelError):
                build_run_ledger(os.path.join(tmp, "missing"), TARGET)
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
