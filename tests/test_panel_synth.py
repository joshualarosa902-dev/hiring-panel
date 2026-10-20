"""Tests for hp.panel.synth (ARCHITECTURE.md section 9) on the fictional run_basic fixture.

Set HP_REGEN_GOLDEN=1 to rewrite tests/fixtures/panel/expected_synthesis.json after an intended change.
"""
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "plugins", "hiring-panel", "skills", "hiring-panel", "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from hp.panel import synth as synth_module  # noqa: E402
from hp.panel.common import PanelError, SourceContext  # noqa: E402
from hp.panel.ledger import build_ledger  # noqa: E402
from hp.panel.synth import LAMBDA, cli_summary, closest_to_reject, keyword_question, scrub_ids, synthesize  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "panel", "run_basic")
GOLDEN = os.path.join(HERE, "fixtures", "panel", "expected_synthesis.json")
TOP_KEYS = ["schema_version", "mode", "panel_size", "missing_reviewers", "reviewers", "panel_vote",
            "verdict_split", "closest_to_reject", "issues", "notes", "top3", "pinned_integrity", "conflicts", "strengths",
            "questions_for_candidate", "interview_prep", "validation_log"]
ISSUE_KEYS = ["id", "rank", "title", "family", "categories", "severity", "priority", "reviewers",
              "reviewer_count", "from_script", "stage", "lane", "has_real_gap", "real_gap_routes", "evidence",
              "detail", "fixes", "jd_anchors", "is_pattern", "instances"]


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _dump(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


class RunCase(unittest.TestCase):
    """Each test gets a private copy of the fixture run folder."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hp-panel-")
        self.run_dir = os.path.join(self.tmp, "run")
        shutil.copytree(FIXTURE, self.run_dir)
        self.reviews = os.path.join(self.run_dir, "work", "reviews")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def review(self, rid):
        return _load(os.path.join(self.reviews, rid + ".json"))

    def put_review(self, rid, data):
        _dump(os.path.join(self.reviews, rid + ".json"), data)

    def issue_with(self, result, anchor):
        for it in result["issues"]:
            if any(e["anchor"] == anchor for e in it["evidence"]) or anchor in it["jd_anchors"]:
                return it
        return None

    def log_actions(self, result, where_prefix):
        return [(e["where"], e["action"]) for e in result["validation_log"] if e["where"].startswith(where_prefix)]


class OutputShapeTest(RunCase):
    def test_fixed_keys_and_written_file(self):
        res = synthesize(self.run_dir, "parallel")
        self.assertEqual(list(res), TOP_KEYS)
        for it in res["issues"]:
            self.assertEqual(list(it), ISSUE_KEYS)
            self.assertIn(it["severity"], ("critical", "major", "moderate", "minor"))
            self.assertIn(it["lane"], ("fixed_by_rewrite", "needs_your_input", "real_gap"))
        self.assertEqual([it["id"] for it in res["issues"]], ["I{}".format(i) for i in range(1, len(res["issues"]) + 1)])
        self.assertEqual([it["rank"] for it in res["issues"]], list(range(1, len(res["issues"]) + 1)))
        self.assertEqual(_load(os.path.join(self.run_dir, "work", "synthesis.json")), res)
        self.assertEqual(res["schema_version"], "1.0")
        self.assertEqual(res["mode"], "parallel")

    def test_reviewers_in_report_order_with_names(self):
        res = synthesize(self.run_dir, "parallel")
        self.assertEqual([r["id"] for r in res["reviewers"]],
                         ["screening", "hiring_manager", "recruiter", "competitor", "ceo", "teammate", "skeptic"])
        self.assertEqual(res["reviewers"][0]["name"], "Automated Screening Check")
        self.assertEqual(res["reviewers"][3]["name"], "Competing Applicant")
        self.assertEqual(res["reviewers"][5]["name"], "Future Teammate")
        for r in res["reviewers"]:
            self.assertEqual(sorted(r), sorted(["id", "name", "verdict", "advance", "confidence",
                                                "one_line_take", "decision_question"]))

    def test_cli_summary(self):
        res = synthesize(self.run_dir, "parallel")
        s = cli_summary(res)
        self.assertEqual(s["panel_vote"], {"advance": 2, "unsure": 3, "no": 2, "total": 7})
        self.assertEqual(len(s["top"]), 5)
        self.assertEqual(s["dropped"], 5)


class VoteTest(RunCase):
    def test_vote_counts_advance_not_verdicts(self):
        res = synthesize(self.run_dir, "parallel")
        self.assertEqual(res["panel_vote"], {"advance": 2, "unsure": 3, "no": 2, "total": 7})
        # Make the skeptic doubt one claim (strong_no) but still say "yes": the vote follows advance.
        sk = self.review("skeptic")
        sk["advance"] = "yes"
        self.put_review("skeptic", sk)
        res = synthesize(self.run_dir, "parallel")
        self.assertEqual(res["panel_vote"]["advance"], 3)
        self.assertEqual([r["verdict"] for r in res["reviewers"] if r["id"] == "skeptic"], ["strong_no"])

    def test_verdict_split(self):
        res = synthesize(self.run_dir, "parallel")
        vs = res["verdict_split"]
        self.assertEqual(vs["spread"], 3)
        self.assertTrue(vs["is_split"])
        self.assertEqual(vs["median"], "borderline")
        self.assertEqual(vs["outliers"], ["skeptic"])
        self.assertTrue(vs["advance_split"])


class ClosestToRejectTest(RunCase):
    """synthesis.closest_to_reject (ARCHITECTURE.md section 17.4): lowest verdict, ties in report order,
    that reviewer's top-ranked issue (else its one-line take)."""

    def test_fixture_run(self):
        res = synthesize(self.run_dir, "parallel")
        c = res["closest_to_reject"]
        self.assertEqual(sorted(c), ["issue_id", "reason", "reviewer", "verdict"])
        self.assertEqual((c["reviewer"], c["verdict"]), ("skeptic", "strong_no"))
        mine = [it for it in res["issues"] if "skeptic" in it["reviewers"]]
        top = min(mine, key=lambda it: it["rank"])
        self.assertEqual(c["issue_id"], top["id"])
        self.assertEqual(c["reason"], top["title"])
        self.assertEqual(top["rank"], min(it["rank"] for it in mine))

    def test_tie_goes_to_report_order(self):
        # competitor is lean_no; make the skeptic and the CEO lean_no too: competitor comes first.
        for rid in ("skeptic", "ceo"):
            r = self.review(rid)
            r["verdict"] = "lean_no"
            self.put_review(rid, r)
        c = synthesize(self.run_dir, "parallel")["closest_to_reject"]
        self.assertEqual((c["reviewer"], c["verdict"]), ("competitor", "lean_no"))
        # Now the screening reviewer ties at lean_no as well and wins (it is first in report order).
        r = self.review("screening")
        r["verdict"] = "lean_no"
        self.put_review("screening", r)
        c = synthesize(self.run_dir, "parallel")["closest_to_reject"]
        self.assertEqual(c["reviewer"], "screening")

    def test_reviewer_without_issues_uses_its_take(self):
        sk = self.review("skeptic")
        sk["findings"] = []
        self.put_review("skeptic", sk)
        res = synthesize(self.run_dir, "parallel")
        c = res["closest_to_reject"]
        self.assertEqual(c["reviewer"], "skeptic")
        self.assertFalse(any("skeptic" in it["reviewers"] for it in res["issues"]))
        self.assertIsNone(c["issue_id"])
        take = [r["one_line_take"] for r in res["reviewers"] if r["id"] == "skeptic"][0]
        self.assertTrue(take)
        self.assertEqual(c["reason"], take)

    def test_missing_reviewer_is_skipped(self):
        os.remove(os.path.join(self.reviews, "skeptic.json"))
        c = synthesize(self.run_dir, "parallel")["closest_to_reject"]
        self.assertEqual((c["reviewer"], c["verdict"]), ("competitor", "lean_no"))

    def test_contact_details_masked(self):
        sk = self.review("skeptic")
        sk["findings"] = []
        sk["one_line_take"] = "Email jordan.example@example.com before you send this."
        self.put_review("skeptic", sk)
        c = synthesize(self.run_dir, "parallel")["closest_to_reject"]
        self.assertIsNone(c["issue_id"])
        self.assertIn("Email", c["reason"])
        self.assertNotIn("jordan.example@example.com", c["reason"])

    def test_function_rules(self):
        reviewers = [{"id": "hiring_manager", "verdict": "borderline", "one_line_take": "HM take"},
                     {"id": "screening", "verdict": "borderline", "one_line_take": "Screening take"},
                     {"id": "skeptic", "verdict": "lean_yes", "one_line_take": "Skeptic take"}]
        issues = [{"id": "I1", "rank": 1, "title": "Top", "reviewers": ["hiring_manager"]},
                  {"id": "I3", "rank": 3, "title": "Third", "reviewers": ["screening", "skeptic"]},
                  {"id": "I2", "rank": 2, "title": "Second", "reviewers": ["screening"]}]
        # Tie at borderline: screening comes first in report order (whatever the list order is), and its
        # top-ranked issue is I2 (rank 2), not I3.
        self.assertEqual(closest_to_reject(reviewers, issues),
                         {"reviewer": "screening", "verdict": "borderline", "issue_id": "I2", "reason": "Second"})
        self.assertEqual(closest_to_reject(list(reversed(reviewers)), list(reversed(issues))),
                         closest_to_reject(reviewers, issues))
        # No issue lists the reviewer: the reason is its one-line take.
        self.assertEqual(closest_to_reject(reviewers, [])["reason"], "Screening take")
        self.assertIsNone(closest_to_reject(reviewers, [])["issue_id"])
        # Empty or unusable panel.
        self.assertIsNone(closest_to_reject([], issues))
        self.assertIsNone(closest_to_reject(None, None))
        self.assertIsNone(closest_to_reject([{"id": "ceo", "verdict": "maybe"}, "x", {"id": "intruder",
                                                                                     "verdict": "strong_no"}], issues))


class EvidenceTest(RunCase):
    def test_made_up_quote_dropped(self):
        res = synthesize(self.run_dir, "parallel")
        self.assertIn(("skeptic:skeptic-3", "finding_dropped"), self.log_actions(res, "skeptic:skeptic-3"))
        quotes = [e["quote"] for it in res["issues"] for e in it["evidence"]]
        self.assertNotIn("Led a team of 12 analysts", quotes)

    def test_anchor_repair_for_findings_and_strengths(self):
        res = synthesize(self.run_dir, "parallel")
        log = res["validation_log"]
        self.assertIn({"where": "recruiter:recruiter-4", "action": "anchor_repaired", "from": "R3", "to": "R1"}, log)
        self.assertIn({"where": "competitor:competitor-s1", "action": "anchor_repaired", "from": "R3", "to": "R12"}, log)
        s2 = [s for s in res["strengths"] if "R12" in s["anchors"]][0]
        self.assertIn("competitor", s2["reviewers"])

    def test_dash_and_bullet_normalization(self):
        # recruiter-1 quotes "Jun 2025 - Aug 2025" with a hyphen; the line has an en dash.
        res = synthesize(self.run_dir, "parallel")
        title_issue = self.issue_with(res, "R7")
        self.assertIsNotNone(title_issue)
        self.assertIn("recruiter", title_issue["reviewers"])

    def test_ellipsis_quote_accepted_but_not_fragments_out_of_order(self):
        sk = self.review("skeptic")
        sk["findings"][0]["evidence"] = [{"anchor": "R9", "quote": "revenue 300% ... Spearheaded"}]
        self.put_review("skeptic", sk)
        res = synthesize(self.run_dir, "parallel")
        self.assertIn(("skeptic:skeptic-1", "finding_dropped"), self.log_actions(res, "skeptic:skeptic-1"))

    def test_a_anchors_checked_against_screening(self):
        res = synthesize(self.run_dir, "parallel")
        self.assertIn({"where": "screening:screening-5", "action": "evidence_dropped", "anchor": "A:PARSE-099",
                       "reason": "no such issue in screening.json"}, res["validation_log"])
        title_issue = self.issue_with(res, "A:KW-004")       # A:KW-004 exists (low issue), so it is kept
        self.assertIsNotNone(title_issue)
        self.assertIn("screening", title_issue["reviewers"])
        self.assertIn("recruiter", title_issue["reviewers"])

    def test_q_anchor_not_allowed_in_reviews(self):
        hm = self.review("hiring_manager")
        hm["findings"][0]["evidence"] = [{"anchor": "Q1", "quote": "yes"}]
        self.put_review("hiring_manager", hm)
        res = synthesize(self.run_dir, "parallel")
        self.assertIn(("hiring_manager:hiring_manager-1", "finding_dropped"),
                      self.log_actions(res, "hiring_manager:hiring_manager-1"))

    def test_contact_details_masked_in_output(self):
        res = synthesize(self.run_dir, "parallel")
        text = json.dumps(res)
        self.assertNotIn("jordan.rivera@example.com", text)
        self.assertNotIn("555-0198", text.replace("***-***-0198", ""))


class KeywordGapTest(RunCase):
    def test_overruled_by_resume_text(self):
        res = synthesize(self.run_dir, "parallel")
        reasons = [e.get("reason", "") for e in res["validation_log"] if e["where"] == "screening:screening-2"]
        self.assertTrue(any("Python" in r for r in reasons))

    def test_overruled_by_screening_truth(self):
        # "data visualization" is not in the resume text, but the screening check found it (implied).
        res = synthesize(self.run_dir, "parallel")
        reasons = [e.get("reason", "") for e in res["validation_log"] if e["where"] == "teammate:teammate-4"]
        self.assertTrue(any("data visualization" in r for r in reasons))

    def test_short_terms_need_exact_case(self):
        sc = self.review("screening")
        sc["findings"][1] = {"id": "screening-2", "category": "KEYWORD_GAP", "severity": "major",
                             "confidence": "high", "title": "R is missing", "detail": "",
                             "evidence": [{"anchor": "J10", "quote": "Experience with Python or R"}],
                             "searched_terms": ["R"], "fix": {"fix_type": "real_gap", "suggestion": "",
                                                              "candidate_question": None},
                             "out_of_lens": False}
        self.put_review("screening", sc)
        res = synthesize(self.run_dir, "parallel")
        # "r" appears inside words all over the resume, but the language R does not: the gap stands.
        self.assertNotIn(("screening:screening-2", "finding_dropped"), self.log_actions(res, "screening:screening-2"))


class LensTest(RunCase):
    def test_out_of_lens_minor_dropped(self):
        res = synthesize(self.run_dir, "parallel")
        self.assertIn(("ceo:ceo-4", "finding_dropped"), self.log_actions(res, "ceo:ceo-4"))

    def test_out_of_lens_cap_of_two(self):
        comp = self.review("competitor")
        extra = [
            ("competitor-4", "TITLE_MISMATCH", "R7", "Marketing Intern"),
            ("competitor-5", "INCONSISTENCY", "R11", "Sep 2023"),
            ("competitor-6", "LAYOUT_SKIM", "R4", "EDUCATION"),
        ]
        for fid, cat, anchor, quote in extra:
            comp["findings"].append({"id": fid, "category": cat, "severity": "major", "confidence": "high",
                                     "title": cat, "detail": "", "evidence": [{"anchor": anchor, "quote": quote}],
                                     "fix": {"fix_type": "rewrite", "suggestion": "", "candidate_question": None},
                                     "out_of_lens": True})
        self.put_review("competitor", comp)
        res = synthesize(self.run_dir, "parallel")
        self.assertNotIn(("competitor:competitor-4", "finding_dropped"), self.log_actions(res, "competitor:competitor-4"))
        self.assertNotIn(("competitor:competitor-5", "finding_dropped"), self.log_actions(res, "competitor:competitor-5"))
        dropped = [e for e in res["validation_log"] if e["where"] == "competitor:competitor-6"]
        self.assertEqual(dropped[0]["action"], "finding_dropped")
        self.assertIn("cap", dropped[0]["reason"])
        # Out-of-lens agreement counts half in the consensus weight.
        title = self.issue_with(res, "A:KW-004")
        self.assertIn("competitor", title["reviewers"])

    def test_automatic_findings_bypass_lens_cap(self):
        res = synthesize(self.run_dir, "parallel")
        autos = [it for it in res["issues"] if it["from_script"]]
        self.assertEqual(len(autos), 3)      # KW-001, PARSE-006, KW-002 (medium and above)


class AutomaticFindingsTest(RunCase):
    def test_screening_issues_imported_with_category_map_and_severity(self):
        res = synthesize(self.run_dir, "parallel")
        sql = self.issue_with(res, "A:KW-001")
        self.assertEqual(sql["id"], "I1")
        self.assertEqual(sql["jd_anchors"], ["J9"])        # attached by matching the term's jd_quote
        self.assertIn("KEYWORD_GAP", sql["categories"])
        self.assertEqual(sql["lane"], "needs_your_input")
        contact = self.issue_with(res, "A:PARSE-006")
        self.assertEqual(contact["severity"], "major")     # high -> major
        self.assertIn("PARSE_FORMAT", contact["categories"])
        self.assertIn("CONTACT_HEADER", contact["categories"])
        self.assertEqual(contact["reviewers"], ["screening", "recruiter"])
        self.assertEqual(contact["lane"], "fixed_by_rewrite")
        skill = self.issue_with(res, "A:KW-002")
        self.assertEqual(skill["severity"], "moderate")    # medium -> moderate
        self.assertEqual(skill["categories"], ["SKILL_UNSUPPORTED"])
        self.assertEqual(skill["reviewers"], ["screening", "teammate", "skeptic"])
        self.assertTrue(skill["from_script"])
        # low items are not imported automatically
        self.assertIsNone(self.issue_with(res, "A:CONTENT-002"))

    def test_info_items_become_notes(self):
        res = synthesize(self.run_dir, "parallel")
        self.assertEqual(res["notes"], [{"id": "CONTENT-008", "title": "Buzzwords with no evidence: teamwork, communication"},
                                        {"id": "KW-005", "title": "Preferred terms missing: healthcare data"}])
        self.assertIsNone(self.issue_with(res, "A:CONTENT-008"))

    def test_finding_citing_info_item_capped_at_minor(self):
        tm = self.review("teammate")
        tm["findings"][1]["evidence"].append({"anchor": "A:CONTENT-008"})
        tm["findings"][1]["severity"] = "moderate"
        self.put_review("teammate", tm)
        res = synthesize(self.run_dir, "parallel")
        capped = [e for e in res["validation_log"] if e["action"] == "severity_capped"]
        self.assertEqual(capped[0]["where"], "teammate:teammate-2")

    def test_hidden_text_pinned(self):
        path = os.path.join(self.run_dir, "work", "screening", "before", "screening.json")
        scr = _load(path)
        scr["issues"].append({"id": "PARSE-016", "rank": 8, "category": "parse", "severity": "high",
                              "title": "Hidden text found", "evidence": ["white text"],
                              "why_it_matters": "Hidden text looks like keyword stuffing.",
                              "fix": "Remove the hidden text.", "honesty_note": None, "confidence": "high",
                              "detected_by": "file_structure"})
        _dump(path, scr)
        res = synthesize(self.run_dir, "parallel")
        hidden = self.issue_with(res, "A:PARSE-016")
        self.assertIsNotNone(hidden)
        self.assertIn(hidden["id"], res["pinned_integrity"])
        self.assertEqual(hidden["fixes"][0]["fix_type"], "remove")

    def test_without_screening_json(self):
        os.remove(os.path.join(self.run_dir, "work", "screening", "before", "screening.json"))
        res = synthesize(self.run_dir, "parallel")
        self.assertFalse(any(it["from_script"] for it in res["issues"]))
        self.assertEqual(res["notes"], [])
        self.assertEqual(res["panel_size"], 7)
        # "Python" is still overruled from the resume text; A: evidence cannot be verified.
        reasons = [e.get("reason", "") for e in res["validation_log"]]
        self.assertIn("screening.json not available", reasons)

    def test_garbage_screening_json(self):
        path = os.path.join(self.run_dir, "work", "screening", "before", "screening.json")
        for garbage in ('{"issues": "nope", "keywords": 7}', '[1, 2]', '{"issues": [null, 5, {"id": 3}, '
                        '{"id": "KW-001", "severity": "high", "evidence": [null, 4]}], "keywords": {"required": "x"}}',
                        "not json at all"):
            with open(path, "w", encoding="utf-8") as f:
                f.write(garbage)
            res = synthesize(self.run_dir, "parallel")
            self.assertEqual(res["panel_size"], 7)


class RankingTest(RunCase):
    def test_parallel_ranking(self):
        res = synthesize(self.run_dir, "parallel")
        top = [(it["title"], it["severity"], it["priority"]) for it in res["issues"][:5]]
        self.assertEqual(top[0], ("SQL, a required skill, never appears", "critical", 22.5))
        self.assertEqual(top[1][0], "Bullets describe duties, not results (pattern across 4 lines)")
        self.assertEqual(top[1][2], 10.0)
        self.assertEqual(top[2], ("Email and phone only in the page header", "major", 9.0))
        self.assertEqual(top[3][2], 8.4)
        self.assertEqual(top[4], ("Company-wide strategy and 300% revenue in a summer internship", "critical", 8.0))
        self.assertEqual(res["top3"], ["I1", "I2", "I3"])
        priorities = [it["priority"] for it in res["issues"]]
        self.assertEqual(priorities, sorted(priorities, reverse=True))

    def test_lambda_per_mode(self):
        self.assertEqual(LAMBDA, {"parallel": 0.5, "sequential": 0.3, "lite": 0.3})
        par = synthesize(self.run_dir, "parallel")
        seq = synthesize(self.run_dir, "sequential")
        lite = synthesize(self.run_dir, "lite")
        self.assertEqual(seq["issues"][0]["priority"], 19.5)          # 8 x (1 + 0.3) x 1.5 x 1.0 x 1.25
        self.assertEqual(par["issues"][0]["priority"], 22.5)          # 8 x (1 + 0.5) x 1.5 x 1.0 x 1.25
        self.assertEqual([i["priority"] for i in seq["issues"]], [i["priority"] for i in lite["issues"]])
        self.assertEqual(lite["mode"], "lite")
        # Weaker consensus weight in sequential mode lets the single-reviewer critical claim climb.
        self.assertEqual([i["title"] for i in seq["issues"][:3]][2],
                         "Company-wide strategy and 300% revenue in a summer internship")
        par_top = [i["title"] for i in par["issues"][:3]]
        seq_top = [i["title"] for i in seq["issues"][:3]]
        self.assertNotEqual(par_top, seq_top)

    def test_rollup_pattern(self):
        res = synthesize(self.run_dir, "parallel")
        pat = [it for it in res["issues"] if it["is_pattern"]]
        self.assertEqual(len(pat), 1)
        pat = pat[0]
        self.assertEqual(pat["family"], "IMPACT")
        self.assertEqual(len(pat["instances"]), 3)
        self.assertEqual([e["anchor"] for e in pat["evidence"]], ["R8", "R10", "R12", "R15"])
        self.assertEqual(pat["reviewers"], ["hiring_manager", "competitor", "ceo"])
        self.assertEqual(pat["severity"], "major")

    def test_pinned_integrity(self):
        res = synthesize(self.run_dir, "parallel")
        pinned = [it for it in res["issues"] if it["id"] in res["pinned_integrity"]]
        self.assertEqual([it["title"] for it in pinned],
                         ["Company-wide strategy and 300% revenue in a summer internship"])

    def test_requirement_merge_on_shared_j_line(self):
        res = synthesize(self.run_dir, "parallel")
        sql = res["issues"][0]
        self.assertEqual(sql["reviewers"], ["screening", "hiring_manager"])
        self.assertEqual(sorted(sql["categories"]), ["KEYWORD_GAP", "REQUIREMENT_UNPROVEN"])


class ConflictsStrengthsTest(RunCase):
    def test_conflicts(self):
        res = synthesize(self.run_dir, "parallel")
        kinds = [(c["type"], c["issue_id"]) for c in res["conflicts"]]
        self.assertEqual(kinds, [("strength_vs_weakness", "I2"), ("severity_split", "I3"),
                                 ("strength_vs_weakness", "I12")])
        c = res["conflicts"][2]
        self.assertEqual(c["anchors"], ["R14"])
        sides = {s["reviewer"]: s["view"] for s in c["sides"]}
        self.assertTrue(sides["skeptic"].startswith("Weakness: "))
        self.assertTrue(sides["hiring_manager"].startswith("Strength: "))
        for conflict in res["conflicts"]:
            self.assertTrue(conflict["which_matters"])
            self.assertGreaterEqual(len(conflict["sides"]), 2)

    def test_strengths_merged_by_line(self):
        res = synthesize(self.run_dir, "parallel")
        self.assertEqual([s["id"] for s in res["strengths"]], ["S1", "S2", "S3"])
        s1 = res["strengths"][0]
        self.assertEqual(s1["anchors"], ["R14"])
        self.assertEqual(s1["reviewers"], ["hiring_manager", "competitor", "ceo", "teammate"])
        self.assertTrue(s1["underused"])

    def test_thin_resume_no_invented_strengths(self):
        for rid in ("screening", "hiring_manager", "recruiter", "competitor", "ceo", "teammate", "skeptic"):
            r = self.review(rid)
            r["strengths"] = []
            if rid == "competitor":
                r["lens_data"]["unfair_advantages"] = []
            self.put_review(rid, r)
        res = synthesize(self.run_dir, "parallel")
        self.assertEqual(res["strengths"], [])
        self.assertFalse(any(c["type"] == "strength_vs_weakness" for c in res["conflicts"]))


class QuestionsPrepTest(RunCase):
    def test_questions(self):
        res = synthesize(self.run_dir, "parallel")
        qs = res["questions_for_candidate"]
        self.assertLessEqual(len(qs), 6)
        self.assertEqual([q["id"] for q in qs], ["RQ{}".format(i) for i in range(1, len(qs) + 1)])
        self.assertEqual(qs[0]["issue_ids"], ["I1"])
        self.assertIn("SQL", qs[0]["question"])
        self.assertEqual(len({q["question"] for q in qs}), len(qs))
        first_issue = [int(q["issue_ids"][0][1:]) for q in qs if q["issue_ids"]]
        self.assertEqual(first_issue, sorted(first_issue))

    def test_questions_capped_at_six(self):
        hm = self.review("hiring_manager")
        hm["questions_for_candidate"] = [{"question": "Unlinked question {}?".format(i), "why": "",
                                          "related_anchors": []} for i in range(5)]
        self.put_review("hiring_manager", hm)
        res = synthesize(self.run_dir, "parallel")
        self.assertEqual(len(res["questions_for_candidate"]), 6)

    def test_interview_prep(self):
        res = synthesize(self.run_dir, "parallel")
        prep = res["interview_prep"]
        self.assertLessEqual(len(prep), 6)
        self.assertEqual([p["from"] for p in prep], ["hiring_manager"] * 3 + ["skeptic"] * 3)
        self.assertEqual([p["anchor"] for p in prep[3:]], ["R9", "R14", "R12"])   # high risk first
        self.assertIsNone(prep[0]["anchor"])

    def test_interview_prep_skips_unverified_claims_and_fills_from_skeptic(self):
        sk = self.review("skeptic")
        sk["lens_data"]["claim_audit"][0]["quote"] = "a claim that is not on the page"
        sk["lens_data"]["claim_audit"].append({"anchor": "R10", "quote": "weekly reports", "claim_type": "scope",
                                               "risk": "low",
                                               "probe_question": "What went into each weekly Excel report?",
                                               "recommended": "keep_prepare_story"})
        self.put_review("skeptic", sk)
        hm = self.review("hiring_manager")
        hm["lens_data"]["interview_questions"] = hm["lens_data"]["interview_questions"][:1]
        self.put_review("hiring_manager", hm)
        res = synthesize(self.run_dir, "parallel")
        prep = res["interview_prep"]
        self.assertEqual([p["from"] for p in prep], ["hiring_manager", "skeptic", "skeptic", "skeptic"])
        self.assertNotIn("R9", [p["anchor"] for p in prep])


class LiveFindingsTest(RunCase):
    """Regressions for the live end-to-end test findings (fictional data only)."""

    def finding(self, fid, cat, sev, anchor, quote, fix_type, suggestion, question=None, title="A finding title",
                ool=False):
        return {"id": fid, "category": cat, "severity": sev, "confidence": "high", "title": title,
                "detail": "Detail text.", "evidence": [{"anchor": anchor, "quote": quote}],
                "fix": {"fix_type": fix_type, "suggestion": suggestion, "candidate_question": question},
                "out_of_lens": ool}

    def by_title(self, res, title):
        return next(it for it in res["issues"] if it["title"] == title)

    def test_vote_has_no_count(self):                                        # 4.1
        v = synthesize(self.run_dir, "parallel")["panel_vote"]
        self.assertEqual(v["advance"] + v["unsure"] + v["no"], v["total"])
        self.assertEqual(list(v), ["advance", "unsure", "no", "total"])

    def test_first_fix_comes_from_the_finding_that_gave_the_title(self):    # A12
        ceo = self.review("ceo")
        ceo["findings"].append(self.finding("ceo-9", "SCOPE_INFLATION", "major", "R9",
                                            "Spearheaded company-wide analytics strategy", "rewrite",
                                            "Describe only the part you did.", title="Strategy claim is too big",
                                            ool=True))
        self.put_review("ceo", ceo)
        res = synthesize(self.run_dir, "parallel")
        lead = self.review("skeptic")["findings"][0]
        it = self.by_title(res, lead["title"])
        self.assertEqual(it["reviewers"], ["ceo", "skeptic"])
        # "rewrite" sorts before "needs_candidate_input", but the title came from the Skeptic's finding.
        self.assertEqual(it["fixes"][0]["reviewer"], "skeptic")
        self.assertEqual(it["fixes"][0]["suggestion"], lead["fix"]["suggestion"])
        self.assertEqual(it["fixes"][1]["reviewer"], "ceo")
        self.assertEqual(it["detail"], lead["detail"])

    def test_real_gap_surfaces_inside_a_needs_input_issue(self):            # 4.3 and 6.12
        tm = self.review("teammate")
        route = "Take a short SQL course or build one small SQL project before you apply."
        tm["findings"].append(self.finding("teammate-5", "REQUIREMENT_UNPROVEN", "major", "J9", "Proficiency in SQL",
                                           "real_gap", route, title="No SQL anywhere"))
        self.put_review("teammate", tm)
        res = synthesize(self.run_dir, "parallel")
        it = next(i for i in res["issues"] if "J9" in i["jd_anchors"])
        self.assertIn("teammate", it["reviewers"])
        self.assertEqual(it["lane"], "needs_your_input")          # lane logic unchanged
        self.assertTrue(it["has_real_gap"])
        self.assertEqual(it["real_gap_routes"], [route])
        for other in res["issues"]:
            types = {f["fix_type"] for f in other["fixes"]}
            if "real_gap" not in types and other["lane"] != "real_gap":
                self.assertFalse(other["has_real_gap"], other["title"])
                self.assertEqual(other["real_gap_routes"], [])

    def test_ids_in_student_text_become_short_quotes(self):                 # A11
        comp = self.review("competitor")
        f = next(x for x in comp["findings"] if x["title"] == "No link to the dashboard")
        f["title"] = "No link to the dashboard in R14"
        f["detail"] = "R14 is your best work, but nothing links to it (R14, R17)."
        f["fix"]["suggestion"] = "Add the link next to R14; compare lines R8-R10."
        f["fix"]["candidate_question"] = "Is the dashboard in R14 public?"
        hm = self.review("hiring_manager")
        hm["one_line_take"] = "Show SQL; the dashboard in R14 already helps."
        self.put_review("competitor", comp)
        self.put_review("hiring_manager", hm)
        res = synthesize(self.run_dir, "parallel")
        texts = [r["one_line_take"] for r in res["reviewers"]]
        for it in res["issues"]:
            texts += [it["title"], it["detail"]] + it["real_gap_routes"] + [x["title"] for x in it["instances"]]
            for fx in it["fixes"]:
                texts += [fx["suggestion"], fx["candidate_question"] or ""]
        texts += [q["question"] for q in res["questions_for_candidate"]] + [q["why"] for q in res["questions_for_candidate"]]
        texts += [p["question"] for p in res["interview_prep"]] + [st["title"] for st in res["strengths"]]
        texts += [sd["view"] for c in res["conflicts"] for sd in c["sides"]]
        bare = re.compile(r"(?<![\w/.-])(A:[A-Z]+-[0-9]{3}|[RJ][0-9]+)(?![\w/-])")
        for t in texts:
            self.assertIsNone(bare.search(t), t)
        joined = " ".join(texts)
        self.assertIn("No link to the dashboard in the line \u2018Built a Python dashboard...\u2019", joined)
        self.assertIn("The line \u2018Built a Python dashboard tracking...\u2019 is your best work, but nothing "
                      "links to it.", joined)
        self.assertIn("Add the link next to the line \u2018Built a Python dashboard tracking...\u2019; compare the "
                      "lines \u2018Responsible for social media...\u2019 to \u2018Helped the team with...\u2019.", joined)
        self.assertIn("Is the dashboard in the line \u2018Built a Python dashboard tracking...\u2019 public?", joined)
        self.assertIn("the dashboard in the line \u2018Built a Python dashboard...\u2019 already helps", joined)
        # evidence quotes stay verbatim
        quotes = [e["quote"] for it in res["issues"] for e in it["evidence"]]
        self.assertIn("Proficiency in SQL", quotes)

    def test_scrub_rules(self):
        ctx = SourceContext(self.ledger(), self.screening())
        self.assertEqual(scrub_ids("Studied at an R1 university; needs a J1 visa.", ctx),
                         "Studied at an R1 university; needs a J1 visa.")
        self.assertEqual(scrub_ids("R99 is not a line", ctx), "R99 is not a line")
        self.assertEqual(scrub_ids("Use the R language", ctx), "Use the R language")
        self.assertEqual(scrub_ids("Fix A:PARSE-006 first (A:PARSE-006).", ctx),
                         "Fix the screening check\u2019s \u2018Email and phone only in the page header\u2019 first.")
        self.assertEqual(scrub_ids("Typo in line R10", ctx),
                         "Typo in the line \u2018Helped the team with weekly...\u2019")

    def ledger(self):
        return _load(os.path.join(self.run_dir, "work", "inputs", "ledger.json"))

    def screening(self):
        return _load(os.path.join(self.run_dir, "work", "screening", "before", "screening.json"))

    def test_keyword_question_reads_naturally(self):                        # A8 and 4.2
        resume = "\n".join(["Avery Park", "avery@example.com", "Education", "Lakeshore State University, B.S. Biology",
                            "Experience", "Lab Aide, Lakeshore Biology Lab", "Cleaned survey data in R for a study",
                            "Skills", "Excel, CPR certified, bilingual (English and Korean)"])
        ctx = SourceContext(build_ledger(resume, [], {}), None)
        rows = [
            {"term": "BLS/CPR", "canonical": "Basic Life Support", "kind": "cert", "found": False,
             "jd_quote": "Requirements: High school diploma or GED. Current BLS/CPR certification."},
            {"term": "High school diploma", "kind": "unknown", "found": False, "jd_quote": "High school diploma or GED."},
            {"term": "GED", "kind": "unknown", "found": False, "jd_quote": "High school diploma or GED."},
            {"term": "economics", "kind": "domain", "found": False,
             "jd_quote": "Currently pursuing a bachelor's degree in statistics, economics or a related field"},
            {"term": "R", "kind": "tool", "found": False, "jd_quote": "Experience with Python or R"},
            {"term": "sql", "canonical": "SQL", "kind": "tool", "found": False, "jd_quote": "Write SQL queries weekly"},
            {"term": "teamwork", "kind": "soft", "found": False, "jd_quote": "Excellent communication and teamwork."},
        ]
        q = keyword_question(ctx, "KW-001", rows)
        self.assertEqual(q, "Do you hold a current BLS/CPR certification? What does the card say? "
                            "Have you used SQL in a class, job, project or activity? "
                            "Where have you shown teamwork: a job, class, club or volunteering?")
        for banned in ("economics", "diploma", "GED", "used R", "Have you used any of these"):
            self.assertNotIn(banned, q)
        # No school on the page: ask about the credential, never "have you used" it.
        ctx2 = SourceContext(build_ledger("Avery Park\nWork\nCashier, Corner Market", [], {}), None)
        q2 = keyword_question(ctx2, "KW-001", rows[1:3])
        self.assertEqual(q2, "Do you have a high school diploma or GED?")
        # Listed only: certifications and languages are listed by nature; a skill a work line shows is skipped.
        listed = [{"term": "Cardiopulmonary Resuscitation", "kind": "cert", "resume_wording": "CPR", "found": True,
                   "jd_quote": "Current BLS/CPR certification."},
                  {"term": "Bilingual", "kind": "hard", "found": True, "jd_quote": "Bilingual."},
                  {"term": "R", "kind": "tool", "found": True, "jd_quote": "Experience with Python or R"}]
        self.assertIsNone(keyword_question(ctx, "KW-002", listed))
        listed.append({"term": "Excel", "kind": "tool", "found": True, "jd_quote": "Advanced Excel skills"})
        self.assertEqual(keyword_question(ctx, "KW-002", listed),
                         "Where have you used Excel? A class, job, project or club counts.")

    def test_no_question_about_what_the_page_already_shows(self):           # A5 / A8 cascade guard
        scr = self.screening()
        for it in scr["issues"]:
            if it["id"] == "KW-002":
                it["evidence"] = ['"Python" appears only in your skills or other lists.']
        scr["issues"].append({"id": "SECT-001", "rank": 9, "category": "sections", "severity": "high",
                              "title": "No Education section found", "evidence": [], "why_it_matters": "x",
                              "fix": "Add an Education heading.", "confidence": "medium"})
        _dump(os.path.join(self.run_dir, "work", "screening", "before", "screening.json"), scr)
        res = synthesize(self.run_dir, "parallel")
        asked = [q["question"] for q in res["questions_for_candidate"]] + \
                [f["candidate_question"] or "" for it in res["issues"] for f in it["fixes"]]
        self.assertFalse(any("Where do you study" in q for q in asked))
        self.assertFalse(any("Where have you used Python" in q for q in asked))
        kw2 = next(it for it in res["issues"] if any(e["anchor"] == "A:KW-002" for e in it["evidence"]))
        auto_fix = next(f for f in kw2["fixes"] if f["reviewer"] == "screening")
        self.assertEqual(auto_fix["fix_type"], "rewrite")

    def test_interview_prep_drops_bare_and_near_duplicate_questions(self):  # 6.15
        hm = self.review("hiring_manager")
        hm["lens_data"]["interview_questions"] = ["Walk me through how you built the food bank dashboard.",
                                                  "Why this job?",
                                                  "What did the weekly Excel reports show, and who used them?"]
        self.put_review("hiring_manager", hm)
        sk = self.review("skeptic")
        audit = sk["lens_data"]["claim_audit"]
        audit.append({"anchor": "R12", "quote": "Trained 6 new baristas", "claim_type": "date", "risk": "high",
                      "probe_question": "What month did you start?", "recommended": "verify_with_candidate"})
        audit.append({"anchor": "R14", "quote": "Built a Python dashboard", "claim_type": "scope", "risk": "high",
                      "probe_question": "How did you build the food bank dashboard, step by step?",
                      "recommended": "keep_prepare_story"})
        self.put_review("skeptic", sk)
        res = synthesize(self.run_dir, "parallel")
        prep = [p["question"] for p in res["interview_prep"]]
        self.assertLessEqual(len(prep), 6)
        self.assertNotIn("Why this job?", prep)
        self.assertNotIn("What month did you start?", prep)
        self.assertNotIn("How did you build the food bank dashboard, step by step?", prep)
        self.assertIn("Walk me through how you built the food bank dashboard.", prep)
        self.assertTrue(all(len(q.split()) >= 6 for q in prep))
        dropped = [e for e in res["validation_log"] if e["action"] == "prep_dropped"]
        self.assertEqual(len(dropped), 3)

    def test_issue_ids_are_documented_as_final_after_merges(self):         # 6.20
        doc = " ".join(synth_module.__doc__.split())
        self.assertIn("assigned AFTER merges", doc)
        self.assertIn("FINAL synthesis.json", doc)


class PanelShrinkTest(RunCase):
    def test_missing_and_corrupt_reviews_shrink_the_panel(self):
        os.remove(os.path.join(self.reviews, "ceo.json"))
        with open(os.path.join(self.reviews, "competitor.json"), "w", encoding="utf-8") as f:
            f.write("{not json")
        rec = self.review("recruiter")
        rec["verdict"] = "maybe"
        self.put_review("recruiter", rec)
        with open(os.path.join(self.reviews, "skeptic.json"), "wb") as f:
            f.write(b"\xff\xfe\x00garbage")
        res = synthesize(self.run_dir, "parallel")
        self.assertEqual(res["panel_size"], 3)
        self.assertEqual(res["missing_reviewers"], ["recruiter", "competitor", "ceo", "skeptic"])
        self.assertEqual(res["panel_vote"]["total"], 3)
        self.assertEqual([r["id"] for r in res["reviewers"]], ["screening", "hiring_manager", "teammate"])
        actions = {e["where"]: e["action"] for e in res["validation_log"] if e["where"] in
                   ("ceo", "competitor", "recruiter", "skeptic")}
        self.assertEqual(actions, {"ceo": "review_missing", "competitor": "review_unreadable",
                                   "recruiter": "review_rejected", "skeptic": "review_unreadable"})
        self.assertEqual(res["pinned_integrity"], [])

    def test_no_reviews_at_all(self):
        shutil.rmtree(self.reviews)
        res = synthesize(self.run_dir, "parallel")
        self.assertEqual(res["panel_size"], 0)
        self.assertEqual(res["panel_vote"], {"advance": 0, "unsure": 0, "no": 0, "total": 0})
        self.assertEqual(len(res["issues"]), 3)              # the script's findings still stand
        self.assertEqual(res["verdict_split"]["median"], None)
        self.assertIsNone(res["closest_to_reject"])

    def test_hostile_review_shapes(self):
        self.put_review("ceo", [1, 2, 3])
        tm = self.review("teammate")
        tm["findings"] = [1, "x", {"category": 5}, {"category": "SKILL_UNSUPPORTED", "severity": "moderate",
                                                    "evidence": "nope"}, None] + tm["findings"]
        tm["strengths"] = "none"
        tm["lens_data"] = ["bad"]
        tm["advance"] = "definitely"
        tm["one_line_take"] = " ".join(["word"] * 40)
        self.put_review("teammate", tm)
        sk = self.review("skeptic")
        sk["reviewer_id"] = "recruiter"
        self.put_review("skeptic", sk)
        with open(os.path.join(self.reviews, "competitor.json"), "w") as f:
            f.write("[" * 50000 + "]" * 50000)
        res = synthesize(self.run_dir, "parallel")
        self.assertNotIn("ceo", [r["id"] for r in res["reviewers"]])
        self.assertNotIn("skeptic", [r["id"] for r in res["reviewers"]])
        self.assertNotIn("competitor", [r["id"] for r in res["reviewers"]])
        team = [r for r in res["reviewers"] if r["id"] == "teammate"][0]
        self.assertEqual(team["advance"], "unsure")
        self.assertLessEqual(len(team["one_line_take"].split()), 20)

    def test_oversized_review_rejected(self):
        with open(os.path.join(self.reviews, "ceo.json"), "w") as f:
            f.write('{"pad": "' + "x" * (3 * 1024 * 1024) + '"}')
        res = synthesize(self.run_dir, "parallel")
        self.assertIn("ceo", res["missing_reviewers"])


class GeneralReviewTest(RunCase):
    def test_keyword_findings_not_allowed(self):
        path = os.path.join(self.run_dir, "work", "inputs", "ledger.json")
        led = _load(path)
        led["jd_items"] = []
        led["target"]["general_review"] = True
        _dump(path, led)
        scr_path = os.path.join(self.run_dir, "work", "screening", "before", "screening.json")
        scr = _load(scr_path)
        scr["issues"] = [i for i in scr["issues"] if not i["id"].startswith("KW")]
        _dump(scr_path, scr)
        res = synthesize(self.run_dir, "parallel")
        cats = {c for it in res["issues"] for c in it["categories"]}
        self.assertNotIn("KEYWORD_GAP", cats)
        self.assertNotIn("REQUIREMENT_UNPROVEN", cats)
        self.assertTrue(all(not it["jd_anchors"] for it in res["issues"]))
        reasons = [e.get("reason", "") for e in res["validation_log"] if e["where"] == "hiring_manager:hiring_manager-1"]
        self.assertTrue(any("general review" in r for r in reasons))


class MergesTest(RunCase):
    def test_merge_by_issue_ids_and_finding_refs(self):
        base = synthesize(self.run_dir, "parallel")
        by_title = {it["title"]: it["id"] for it in base["issues"]}
        diff = by_title["Generic phrases any applicant could write"]
        proof = by_title["No link to the dashboard"]
        merges = os.path.join(self.run_dir, "work", "merges.json")
        _dump(merges, [[diff, proof], [{"reviewer": "teammate", "id": "teammate-2"},
                                       {"reviewer": "recruiter", "id": "recruiter-3"}], ["I999"], "junk"])
        res = synthesize(self.run_dir, "parallel", merges_path=merges)
        self.assertEqual(len(res["issues"]), len(base["issues"]) - 2)
        merged = [it for it in res["issues"] if it["title"] == "Generic phrases any applicant could write"][0]
        self.assertEqual(sorted(merged["categories"]), ["GENERIC_DIFFERENTIATION", "PROOF_LINKS"])
        actions = [e["action"] for e in res["validation_log"] if e["where"].startswith("merges.json")]
        self.assertEqual(actions.count("merged"), 2)
        self.assertIn("merge_ref_unknown", actions)
        self.assertIn("merge_ignored", actions)

    def test_garbage_merges_file(self):
        merges = os.path.join(self.run_dir, "work", "merges.json")
        with open(merges, "w") as f:
            f.write("{oops")
        res = synthesize(self.run_dir, "parallel", merges_path=merges)
        self.assertEqual(len(res["issues"]), 14)
        res2 = synthesize(self.run_dir, "parallel", merges_path=os.path.join(self.run_dir, "nope.json"))
        self.assertEqual(len(res2["issues"]), 14)


class ErrorsTest(RunCase):
    def test_bad_mode(self):
        with self.assertRaises(PanelError):
            synthesize(self.run_dir, "solo")

    def test_missing_or_corrupt_ledger(self):
        path = os.path.join(self.run_dir, "work", "inputs", "ledger.json")
        with open(path, "w") as f:
            f.write('{"resume_lines": "x"}')
        with self.assertRaises(PanelError):
            synthesize(self.run_dir, "parallel")
        os.remove(path)
        with self.assertRaises(PanelError):
            synthesize(self.run_dir, "parallel")

    def test_accepts_work_dir(self):
        res = synthesize(os.path.join(self.run_dir, "work"), "parallel")
        self.assertEqual(res["panel_size"], 7)


class DeterminismTest(RunCase):
    def test_byte_identical_and_golden(self):
        synthesize(self.run_dir, "parallel")
        with open(os.path.join(self.run_dir, "work", "synthesis.json"), "rb") as f:
            first = f.read()
        synthesize(self.run_dir, "parallel")
        with open(os.path.join(self.run_dir, "work", "synthesis.json"), "rb") as f:
            second = f.read()
        self.assertEqual(first, second)
        if os.environ.get("HP_REGEN_GOLDEN") == "1":
            with open(GOLDEN, "wb") as f:
                f.write(first)
        with open(GOLDEN, "rb") as f:
            self.assertEqual(first, f.read(), "synthesis changed; set HP_REGEN_GOLDEN=1 if intended")

    def test_review_file_order_does_not_matter(self):
        a = synthesize(self.run_dir, "parallel", write=False)
        # Rewrite every review with keys in reverse order; the result must not change.
        for rid in ("screening", "hiring_manager", "recruiter", "competitor", "ceo", "teammate", "skeptic"):
            r = self.review(rid)
            self.put_review(rid, dict(reversed(list(r.items()))))
        b = synthesize(self.run_dir, "parallel", write=False)
        self.assertEqual(a, b)


class NoNetworkTest(RunCase):
    def test_synthesis_makes_no_network_calls(self):
        real = socket.socket

        def blocked(*args, **kwargs):
            raise AssertionError("network access attempted")

        socket.socket = blocked
        try:
            res = synthesize(self.run_dir, "parallel")
        finally:
            socket.socket = real
        self.assertEqual(res["panel_size"], 7)


if __name__ == "__main__":
    unittest.main()
