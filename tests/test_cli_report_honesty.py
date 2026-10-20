"""Regression tests for the report's honesty rules found in the live end-to-end tests (all data fictional).

    A24, 6.11  weakness statuses are checked against the re-read of the new resume; "improved" is new
    6.9        final-stage keyword gaps come from the re-read (a term the new resume shows is never a gap;
               a certification under Certifications is not "only in skills list"; "X or Y" alternatives)
    4.3, 6.12  real gaps collect every real-gap fix, never "every gap can be fixed with wording"
    A11        internal R#/J#/A: ids never reach the student
    A23        the candidate name is never a headline or role
    6.13       no "underused: move it up" at the final stage
    6.14       changes.numbers_from_you comes from the truth stats
    5.4        a high screening band next to a low vote gets one plain explaining line
    A18        status after the panel stage never tells Claude to ask a second batch

Each test builds a small run folder on disk (fictional candidate Riley Nguyen, Fictional Bio Co) and calls
hp.report_build.build_report on it, the way `hp.py report` does.
"""
import copy
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

from hp import report_build as RB  # noqa: E402
from hp import run as hprun  # noqa: E402
from hp.render.report import build_report_html, build_report_md  # noqa: E402

RESUME_LINES = [
    "Riley Nguyen",
    "Aspiring Lab Assistant",
    "Education",
    "Prairie Valley University, B.S. Biology, expected 2028",
    "Experience",
    "Lab Aide, Campus Biology Lab, 2025 - present",
    "Prepared media and cleaned glassware for three teaching labs",
    "Skills",
    "Python, Excel, CPR",
]
JD_LINES = ["Lab Assistant Intern", "Requirements: High school diploma or GED required.",
            "Experience with SQL and Excel.", "Current CPR certification.", "Preferred: Tableau, lab safety."]


def kw_row(term, found=False, level="none", locs=None, snippets=None, kind="hard", quote=None, importance=None):
    return {"term": term, "canonical": term, "kind": kind, "importance": importance or "required",
            "found": found, "match_type": "exact" if found else "none", "evidence_level": level,
            "resume_wording": term if found else None, "resume_locations": locs or [],
            "snippets": snippets or [], "jd_quote": quote or ("Experience with %s." % term)}


def screening(rows_required, rows_preferred, band="Close, fix the top items", overall=70, name="Riley Nguyen",
              issues=None):
    found = sum(1 for r in rows_required if r["found"])
    return {
        "scores": {"overall": {"value": overall, "band": band},
                   "parse_safety": {"value": 95, "band": "Clean"},
                   "keyword_match": {"value": 50, "band": "Partial"},
                   "content_signals": {"value": 60, "band": "Fair"},
                   "precision_note": "Simulated."},
        "keywords": {"status": "checked",
                     "coverage": {"basis": "required_preferred", "required_found": found,
                                  "required_total": len(rows_required), "required_listed_only": 0},
                     "required": rows_required, "preferred": rows_preferred, "other": []},
        "issues": issues if issues is not None else [
            {"id": "KW-001", "title": "Required job terms are missing from your resume",
             "why_it_matters": "Recruiters search by the posting's terms.", "fix": "Show each term you have."},
            {"id": "PARSE-014", "title": "Section headings are letter-spaced", "why_it_matters": "x", "fix": "y"}],
        "contact": {"name": name},
        "limitations": [], "disclaimer": "A simulation.", "knockout_signals": [],
    }


BEFORE_REQ = [
    kw_row("High school diploma", kind="unknown", quote="Requirements: High school diploma or GED required."),
    kw_row("GED", kind="unknown", quote="Requirements: High school diploma or GED required."),
    kw_row("SQL", kind="tool", quote="Experience with SQL and Excel."),
    kw_row("Excel", True, "listed", ["skills"], ["Python, Excel, CPR"], kind="tool",
           quote="Experience with SQL and Excel."),
    kw_row("CPR", True, "listed", ["skills"], ["Python, Excel, CPR"], kind="cert", quote="Current CPR certification."),
]
BEFORE_PREF = [kw_row("Tableau", kind="tool", importance="preferred", quote="Preferred: Tableau, lab safety."),
               kw_row("lab safety", importance="preferred", quote="Preferred: Tableau, lab safety.")]
AFTER_REQ = [
    kw_row("High school diploma", True, "listed", ["education"], ["Central High School, High school diploma, 2024"],
           kind="unknown", quote="Requirements: High school diploma or GED required."),
    kw_row("GED", kind="unknown", quote="Requirements: High school diploma or GED required."),
    kw_row("SQL", True, "listed", ["coursework"], ["Coursework: Databases (SQL)"], kind="tool",
           quote="Experience with SQL and Excel."),
    kw_row("Excel", True, "demonstrated", ["experience"], ["Tracked media batches in Excel for three labs"],
           kind="tool", quote="Experience with SQL and Excel."),
    kw_row("CPR", True, "listed", ["certifications"], ["CPR | American Red Cross, 2025"], kind="cert",
           quote="Current CPR certification."),
]
AFTER_PREF = [kw_row("Tableau", kind="tool", importance="preferred", quote="Preferred: Tableau, lab safety."),
              kw_row("lab safety", True, "demonstrated", ["experience"], ["Followed lab safety rules in every prep"],
                     importance="preferred", quote="Preferred: Tableau, lab safety.")]


def issue(iid, rank, title, lane="fixed_by_rewrite", categories=("ORDER_PRIORITY",), anchors=("R7",), fixes=None,
          severity="major", **extra):
    d = {"id": iid, "rank": rank, "title": title, "family": "x", "categories": list(categories),
         "severity": severity, "priority": 1.0, "reviewers": ["hiring_manager"], "reviewer_count": 1,
         "from_script": any(a.startswith("A:") for a in anchors), "stage": "student", "lane": lane,
         "evidence": [{"anchor": a, "quote": "Prepared media and cleaned glassware", "reviewer": "hiring_manager"}
                      for a in anchors],
         "detail": "Detail for %s." % title,
         "fixes": fixes or [{"fix_type": "rewrite", "suggestion": "Rewrite it.", "candidate_question": "",
                             "reviewer": "hiring_manager"}],
         "jd_anchors": [], "is_pattern": False, "instances": []}
    d.update(extra)
    return d


def synthesis(issues, vote=(2, 3, 7)):
    reviewers = [{"id": r, "name": r, "verdict": "borderline", "advance": "unsure", "confidence": "medium",
                  "one_line_take": "Solid start; see R7 and fix (R8).", "decision_question": "?"}
                 for r in hprun.REVIEWER_IDS]
    for i in range(vote[0]):
        reviewers[i]["advance"] = "yes"
    return {"schema_version": "1.0", "mode": "parallel", "panel_size": 7, "missing_reviewers": [],
            "reviewers": reviewers,
            "panel_vote": {"advance": vote[0], "unsure": vote[1], "total": vote[2]},
            "issues": issues, "notes": [], "top3": [], "pinned_integrity": [], "conflicts": [],
            "closest_to_reject": None,
            "strengths": [{"id": "S1", "title": "Real lab prep work", "reviewers": ["hiring_manager"],
                           "anchors": ["R7"], "underused": True}],
            "questions_for_candidate": [], "interview_prep": [], "validation_log": []}


def default_issues():
    return [
        issue("I1", 1, "Required job terms are missing from your resume", lane="needs_your_input",
              categories=("KEYWORD_GAP",), anchors=("J3", "A:KW-001"),
              fixes=[{"fix_type": "needs_candidate_input", "suggestion": "Write 'Excel' in R7 and see A:PARSE-014 "
                      "(R9).", "candidate_question": "", "reviewer": "screening"}]),
        issue("I2", 2, "Tableau is never shown", lane="needs_your_input", categories=("KEYWORD_GAP",),
              anchors=("J5",)),
        issue("I3", 3, "Lab safety is only implied", categories=("SKILL_UNSUPPORTED",), anchors=("R7",)),
        issue("I4", 4, "Skills sit above the lab job"),
        issue("I5", 5, "No hands-on cell culture work", lane="needs_your_input", categories=("REQUIREMENT_UNPROVEN",),
              fixes=[{"fix_type": "needs_candidate_input", "suggestion": "Tell us about any lab work.",
                      "candidate_question": "", "reviewer": "hiring_manager"},
                     {"fix_type": "real_gap", "suggestion": "Do not add these. A cell biology lab course would "
                      "close it honestly.", "candidate_question": "", "reviewer": "teammate"}]),
    ]


ADDRESSED = [{"issue_id": "I1", "status": "fixed", "note": "SQL, Excel, diploma and CPR now shown."},
             {"issue_id": "I2", "status": "fixed", "note": "Tableau added."},
             {"issue_id": "I3", "status": "fixed", "note": "Lab safety now in a bullet."},
             {"issue_id": "I4", "status": "fixed", "note": "Experience now comes first."}]


class RunBuilder(object):
    """A fictional run folder at the panel or final stage."""

    def __init__(self, root, final=True, issues=None, addressed=None, before_name="Riley Nguyen", vote=(2, 3, 7),
                 band="Close, fix the top items", resume_name="Riley Nguyen", numbers=3, answers=None):
        self.run = os.path.join(root, "run")
        w = os.path.join(self.run, "work")
        for d in ("inputs", "screening/before", "screening/after/docx", "rewrite", "reviews"):
            os.makedirs(os.path.join(w, d))
        state = hprun.new_state("2026-10-20", "student", "intern", "en-US", "en", "Lab Assistant Intern",
                                "Fictional Bio Co", "pasted", False, {})
        state["steps"] = {"init": "x", "screen": "x", "synthesize": "x"}
        ledger = {"schema_version": "1.0",
                  "resume_lines": [{"id": "R%d" % (i + 1), "section": "other", "text": t}
                                   for i, t in enumerate(RESUME_LINES)],
                  "jd_items": [{"id": "J%d" % (i + 1), "kind": "must", "block": 0, "text": t}
                               for i, t in enumerate(JD_LINES)],
                  "target": {}}
        self.write("work/inputs/ledger.json", ledger)
        self.write("work/screening/before/screening.json",
                   screening(copy.deepcopy(BEFORE_REQ), copy.deepcopy(BEFORE_PREF), band=band, name=before_name))
        self.write("work/synthesis.json", synthesis(issues if issues is not None else default_issues(), vote))
        if final:
            state["steps"].update({"report_panel": "x", "truth": "x", "render": "x"})
            self.write("work/screening/after/docx/screening.json",
                       screening(copy.deepcopy(AFTER_REQ), copy.deepcopy(AFTER_PREF), band=band, overall=75))
            resume = {"basics": {"name": resume_name}, "sections": [
                {"type": "experience", "title": "Experience", "items": [
                    {"id": "e1", "role": "Lab Aide", "org": "Campus Biology Lab",
                     "evidence": [{"src": "orig", "ref": "R6", "quote": "Lab Aide"}],
                     "bullets": [{"id": "e1.b1", "text": "Tracked media batches in Excel for three labs",
                                  "evidence": [{"src": "orig", "ref": "R7", "quote": "Prepared media"}],
                                  "ops": ["REPHRASE"]}]}]}],
                "meta": {"addressed": addressed if addressed is not None else ADDRESSED,
                         "cuts": [{"ref": "R2", "reason": "Headline replaced."}]}}
            self.write("work/rewrite/resume.json", resume)
            self.write("work/rewrite/truth.json", {"passed": True, "errors": [], "warnings": [],
                                                   "stats": {"bullets": 1, "bullets_with_evidence": 1,
                                                             "placeholders_open": 0, "numbers_from_answers": numbers}})
            self.write("work/gate.json", {"passed": True, "files": {"md": "Riley_Nguyen_Resume.md"}})
            with open(os.path.join(self.run, "Riley_Nguyen_Resume.md"), "w", encoding="utf-8") as f:
                f.write("# Riley Nguyen\n\n- Tracked media batches in Excel for three labs\n")
            self.write("work/answers.json", answers or {
                "schema_version": "1.0", "mode": "interactive",
                "answers": [{"id": "Q1", "kind": "keywords", "question": "Which of these have you used?",
                             "answer": "SQL: some, Tableau: no", "status": "answered",
                             "items": [{"term": "SQL", "answer": "some", "detail": "one class"},
                                       {"term": "Tableau", "answer": "no", "detail": ""}]}]})
        self.write("work/state.json", state)

    def write(self, rel, data):
        with open(os.path.join(self.run, rel), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hp-honesty-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def build(self, **kw):
        b = RunBuilder(tempfile.mkdtemp(dir=self.tmp), **kw)
        notes = []
        report = RB.build_report(b.run, notes=notes)
        self.assertEqual(RB.validate_report(report), [])
        return report, notes

    @staticmethod
    def by_id(report):
        return dict((w["issue_id"], w) for w in report["weaknesses"])


class VerifiedStatusTest(Case):
    """A24 and 6.11: a 'fixed' claim is checked against the re-read of the new resume."""

    def test_partial_progress_is_improved_not_fixed(self):
        report, notes = self.build()
        w = self.by_id(report)["I1"]
        self.assertEqual(report["stage"], "final")
        self.assertEqual(w["status"], "improved")
        # SQL is only coursework; GED is covered by the diploma (one alternative is enough).
        self.assertIn("SQL shown as coursework or a class project", w["fix"])
        self.assertIn("High school diploma", w["fix"])
        self.assertNotIn("GED", w["fix"])
        self.assertTrue(w["fix"].startswith("Re-check of the new resume:"))
        self.assertNotIn("SQL, Excel, diploma and CPR now shown", w["fix"])       # the overridden claim
        self.assertTrue(any(n.startswith("I1: the rewrite marked it fixed") and "improved" in n for n in notes),
                        notes)

    def test_still_missing_term_answered_no_is_a_gap(self):
        report, notes = self.build()
        w = self.by_id(report)["I2"]
        self.assertEqual(w["status"], "gap")
        self.assertIn("Tableau still not found", w["fix"])
        self.assertIn("Tableau is never shown", [g["title"] for g in report["real_gaps"]])
        self.assertTrue(any(n.startswith("I2:") for n in notes))

    def test_still_missing_without_an_answer_needs_you(self):
        answers = {"schema_version": "1.0", "mode": "skipped", "answers": []}
        report, _notes = self.build(answers=answers)
        self.assertEqual(self.by_id(report)["I2"]["status"], "needs_you")

    def test_demonstrated_term_keeps_fixed_and_the_note(self):
        report, _notes = self.build()
        w = self.by_id(report)["I3"]
        self.assertEqual(w["status"], "fixed")
        self.assertEqual(w["fix"], "Lab safety now in a bullet.")

    def test_non_keyword_issue_keeps_its_claim(self):
        report, _notes = self.build()
        self.assertEqual(self.by_id(report)["I4"]["status"], "fixed")

    def test_recheck_never_raises_a_claim(self):
        addressed = [dict(a) for a in ADDRESSED]
        addressed[2] = {"issue_id": "I3", "status": "needs_you", "note": "Say where you followed lab safety."}
        report, _notes = self.build(addressed=addressed)
        self.assertEqual(self.by_id(report)["I3"]["status"], "needs_you")

    def test_improved_renders_with_its_own_chip(self):
        report, _notes = self.build()
        for text in (build_report_html(report, onepage=True), build_report_html(report), build_report_md(report)):
            self.assertIn("Improved", text)

    def test_panel_stage_is_always_open(self):
        report, _notes = self.build(final=False)
        self.assertEqual(report["stage"], "panel")
        self.assertTrue(all(w["status"] == "open" for w in report["weaknesses"]))


class FinalKeywordGapsTest(Case):
    """6.9: at the final stage the keyword section describes the NEW resume."""

    def test_final_gaps_come_from_the_recheck(self):
        report, _notes = self.build()
        kws = dict((k["term"], k) for k in report["keyword_gaps"])
        self.assertNotIn("GED", kws)                                   # the diploma covers "diploma or GED"
        self.assertEqual(kws["CPR"]["status"], "added_with_evidence")  # under Certifications now
        self.assertNotIn("skills list", kws["CPR"]["note"])
        self.assertEqual(kws["Excel"]["status"], "added_with_evidence")
        self.assertEqual(kws["SQL"]["status"], "listed_only")
        self.assertIn("coursework", kws["SQL"]["note"])
        self.assertEqual(kws["Tableau"]["status"], "gap")
        self.assertIn("You said you have not used it", kws["Tableau"]["note"])
        for k in report["keyword_gaps"]:
            if k["status"] == "gap":
                self.assertNotIn(k["term"], ("Excel", "CPR", "High school diploma", "lab safety"))

    def test_panel_stage_notes_fit_the_term(self):
        report, _notes = self.build(final=False)
        kws = dict((k["term"], k) for k in report["keyword_gaps"])
        self.assertIn("if you have it", kws["High school diploma"]["note"])     # not "if you have used it"
        self.assertEqual(kws["CPR"]["status"], "listed_only")
        self.assertIn("Only in your skills list", kws["CPR"]["note"])
        self.assertIn("Certifications", kws["CPR"]["note"])
        self.assertIn("if you have used it", kws["SQL"]["note"])

    def test_term_state_rules(self):
        self.assertEqual(RB.term_state(kw_row("CPR", True, "listed", ["certifications"], kind="cert")), "shown")
        self.assertEqual(RB.term_state(kw_row("CPR", True, "listed", ["skills"], kind="cert")), "listed")
        self.assertEqual(RB.term_state(kw_row("R", True, "demonstrated", ["projects"],
                                              ["Class project: survey analysis in R"])), "listed")
        self.assertEqual(RB.term_state(kw_row("R", True, "demonstrated", ["experience"],
                                              ["Cleaned survey data in R for a study"])), "shown")
        self.assertEqual(RB.term_state(kw_row("Go")), "missing")


class RealGapsTest(Case):
    """4.3 and 6.12: every real-gap fix reaches 'Real gaps'; the 'can be fixed with wording' claim is gone."""

    def test_real_gap_fix_inside_a_needs_input_issue_is_listed(self):
        report, _notes = self.build(final=False)
        gaps = dict((g["title"], g["honest_route"]) for g in report["real_gaps"])
        self.assertIn("No hands-on cell culture work", gaps)
        self.assertEqual(gaps["No hands-on cell culture work"], "A cell biology lab course would close it honestly.")

    def test_has_real_gap_flag_wins_when_present(self):
        issues = default_issues()
        issues[3]["has_real_gap"] = True          # flagged by the synthesis, no real_gap fix of its own
        issues[4]["has_real_gap"] = False
        report, _notes = self.build(final=False, issues=issues)
        titles = [g["title"] for g in report["real_gaps"]]
        self.assertIn("Skills sit above the lab job", titles)
        self.assertNotIn("No hands-on cell culture work", titles)

    def test_final_stage_keeps_reviewer_real_gaps_and_addressed_gaps(self):
        addressed = ADDRESSED + [{"issue_id": "I4", "status": "gap", "note": "Needs real lab hours first."}]
        addressed = [a for a in addressed if not (a["issue_id"] == "I4" and a["status"] == "fixed")]
        report, _notes = self.build(addressed=addressed)
        gaps = dict((g["title"], g["honest_route"]) for g in report["real_gaps"])
        self.assertIn("No hands-on cell culture work", gaps)
        self.assertEqual(gaps["Skills sit above the lab job"], "Needs real lab hours first.")

    def test_no_real_gap_message(self):
        issues = [i for i in default_issues() if i["id"] != "I5"]
        report, _notes = self.build(final=False, issues=issues)
        self.assertEqual(report["real_gaps"], [])
        for text in (build_report_html(report, onepage=True), build_report_html(report), build_report_md(report)):
            self.assertIn("The panel didn&#x27;t flag any gap that wording can&#x27;t fix." if "<html" in text
                          else "The panel didn't flag any gap that wording can't fix.", text)
            self.assertNotIn("can be fixed with wording", text)
            self.assertNotIn("None found", text)


class AnchorsTest(Case):
    """A11: internal ids are swapped for short quotes of the line or removed."""

    def test_deanchor(self):
        lines = {"R7": "• Prepared media and cleaned glassware for three teaching labs", "J3": "Experience with SQL."}
        titles = {"PARSE-014": "Section headings are letter-spaced"}
        out = RB.deanchor("Write 'Excel' in R7 and see A:PARSE-014 (R9).", lines, titles)
        self.assertEqual(out, "Write 'Excel' in “Prepared media and cleaned glassware for…” and see "
                              "“Section headings are letter-spaced”.")
        self.assertEqual(RB.deanchor("Matches J3 exactly", lines, titles), "Matches “Experience with SQL.” exactly")
        self.assertEqual(RB.deanchor("Lines R12-R14 repeat (R12, R13 and J3).", {}, {}), "Lines repeat.")
        # Real text that looks like an id stays: a J-1 visa and an R2 score.
        self.assertEqual(RB.deanchor("Needs a J1 visa", lines, titles), "Needs a J1 visa")
        self.assertEqual(RB.deanchor("Model R2 of 0.8", {"R2": "x"}, {}), "Model R2 of 0.8")

    def test_no_ids_in_the_report(self):
        import re
        report, _notes = self.build(final=False)
        text = json.dumps(report, ensure_ascii=False)
        for k in ("weaknesses", "panel", "needs_you", "real_gaps"):
            self.assertIsNone(re.search(r"\b[RJ][0-9]+\b|A:[A-Z]+-[0-9]{3}", json.dumps(report[k])), k)
        self.assertIn("Prepared media and cleaned glassware", text)
        final, _ = self.build()
        rendered = build_report_html(final, onepage=True) + build_report_html(final) + build_report_md(final)
        self.assertNotIn("Cut R2", rendered)
        self.assertIsNone(re.search(r"\bR2\b", re.sub(r"<style>.*?</style>", "", rendered, flags=re.S)))


class CandidateNameTest(Case):
    """A23: resume.json name, else the screening name only when it looks like a name, else none."""

    def test_headline_is_never_the_name(self):
        report, _notes = self.build(final=False, before_name="Aspiring Lab Assistant")
        self.assertEqual(report["candidate"], "")
        self.assertNotIn("Aspiring", build_report_html(report, onepage=True).split("</header>")[0])

    def test_plausible_screening_name(self):
        report, _notes = self.build(final=False, before_name="Riley Nguyen")
        self.assertEqual(report["candidate"], "Riley Nguyen")

    def test_resume_json_name_wins(self):
        report, _notes = self.build(before_name="Aspiring Lab Assistant", resume_name="Riley T. Nguyen")
        self.assertEqual(report["candidate"], "Riley T. Nguyen")

    def test_plausible_name_rules(self):
        for bad in ("Data Analyst", "JORDAN", "Marketing Student", "Resume", "Jane Doe | 555-0100", "Software Engineer II"):
            self.assertEqual(RB.plausible_name(bad), "", bad)
        for good in ("Jordan Alvarez", "Mary-Kate O'Neil", "Nguyen Thi Lan"):
            self.assertEqual(RB.plausible_name(good), good)


class FinalStageDetailsTest(Case):
    def test_no_underused_hint_at_final_stage(self):
        report, _notes = self.build()
        self.assertFalse(any(s["underused"] for s in report["strengths"]))
        self.assertNotIn("Underused", build_report_html(report) + build_report_md(report))
        panel, _ = self.build(final=False)
        self.assertTrue(panel["strengths"][0]["underused"])

    def test_cut_ranges_read_as_whole_lines(self):
        lines = {"R18": "Hardworking statistics student and detail-", "R19": "oriented self-starter.", "R20": "x"}
        self.assertEqual(RB._ref_text("R18-R19", lines), "Hardworking statistics student and detail-oriented "
                                                         "self-starter.")
        self.assertEqual(RB._ref_text("R20", lines), "x")

    def test_numbers_from_you_reads_truth_stats(self):
        report, _notes = self.build(numbers=4)
        self.assertEqual(report["changes"]["numbers_from_you"], 4)
        self.assertIn("4 numbers from your answers", build_report_md(report))


class MixedSignalTest(Case):
    """5.4: a high simulated band next to a low vote gets one plain line, nothing else changes."""

    def test_high_band_low_vote(self):
        report, _notes = self.build(final=False, vote=(2, 3, 7), band="Close, fix the top items")
        self.assertEqual(report["verdict_strip"]["mixed_line"], RB.MIXED_LINE)
        for text in (build_report_html(report, onepage=True), build_report_md(report)):
            self.assertIn("the panel reads the whole story", text)

    def test_no_line_otherwise(self):
        for vote, band in (((4, 2, 7), "Ready to send"), ((1, 3, 7), "Needs work"), ((3, 0, 7), "Not ready")):
            report, _notes = self.build(final=False, vote=vote, band=band)
            self.assertEqual(report["verdict_strip"]["mixed_line"], "", (vote, band))
        report, _notes = self.build(final=False, vote=(3, 2, 7), band="Ready to send")
        self.assertEqual(report["verdict_strip"]["mixed_line"], RB.MIXED_LINE)


class StatusNextTest(unittest.TestCase):
    """A18: after the panel report, status must not send a re-invoked skill to ask a second batch."""

    def test_answers_step_checks_the_chat_first(self):
        tmp = tempfile.mkdtemp(prefix="hp-status-")
        try:
            b = RunBuilder(tmp, final=False)
            state = hprun.load_state(b.run)
            state["steps"]["report_panel"] = "x"
            step, cmd, text = hprun.next_step(b.run, state)
            self.assertEqual((step, cmd), ("answers", ""))
            self.assertIn("If the student already answered the questions, save answers.json and go to Step 6", text)
            self.assertIn("otherwise share the summary and ask the one question batch", text)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
