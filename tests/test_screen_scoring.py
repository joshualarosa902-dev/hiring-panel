"""hp.screen scoring: rounding, bands, gates, null keyword-match rules, confidence multipliers, drivers,
issue ranking, and gaps staying info-level (ATS spec 14)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_screen_support as S  # noqa: E402

from hp.screen import constants as C  # noqa: E402
from hp.screen.scoring import band, keyword_score  # noqa: E402
from hp.util import round5  # noqa: E402

CLEAN = S.fixture("resume_clean.txt")
MESSY = S.fixture("resume_messy.txt")
JD = S.fixture("jd_marketing.txt")
PERFECT = S.fixture("jd_perfect.txt")
SCORE_KEYS = ("overall", "parse_safety", "keyword_match", "content_signals")


def values(r):
    return {k: r["scores"][k]["value"] for k in SCORE_KEYS}


class RoundingAndBandTests(unittest.TestCase):
    def test_round5(self):
        self.assertEqual([round5(x) for x in (0, 2.4, 2.5, 7.49, 7.5, 97.5, 101, -3)], [0, 0, 5, 5, 10, 100, 100, 0])
        self.assertIsNone(round5(None))

    def test_bands(self):
        self.assertEqual(band(90, C.PS_BANDS), "Clean")
        self.assertEqual(band(85, C.PS_BANDS), "Minor risks")
        self.assertEqual(band(50, C.PS_BANDS), "Risky")
        self.assertEqual(band(45, C.PS_BANDS), "Likely to mis-parse")
        self.assertEqual(band(80, C.KM_BANDS), "Strong match")
        self.assertEqual(band(55, C.KM_BANDS), "Partial match")
        self.assertEqual(band(35, C.KM_BANDS), "Weak match")
        self.assertEqual(band(85, C.CS_BANDS), "Polished")
        self.assertEqual(band(65, C.CS_BANDS), "Needs work")
        self.assertEqual(band(80, C.OVERALL_BANDS), "Ready to send")
        self.assertEqual(band(65, C.OVERALL_BANDS), "Close, fix the top items")
        self.assertEqual(band(40, C.OVERALL_BANDS), "Not ready")

    def test_all_values_are_multiples_of_5(self):
        for text, jd in ((CLEAN, JD), (MESSY, JD), (CLEAN, ""), (MESSY, PERFECT)):
            r = S.screen(text, jd)
            for k, v in values(r).items():
                if v is not None:
                    self.assertEqual(v % 5, 0, k)
                    self.assertTrue(0 <= v <= 100)


class FormulaTests(unittest.TestCase):
    def test_overall_formula_with_keywords(self):
        for text in (CLEAN, MESSY):
            r = S.screen(S.make_doc(text, header_footer=[]), JD)
            v = values(r)
            if r["scores"]["overall"]["band"] == C.GATE_BAND:
                continue
            self.assertEqual(v["overall"], round5(0.4 * v["parse_safety"] + 0.4 * v["keyword_match"]
                                                  + 0.2 * v["content_signals"]))
            self.assertEqual(r["scores"]["overall"]["explanation"], C.OVERALL_METHOD)

    def test_overall_formula_without_keywords(self):
        r = S.screen(CLEAN.replace("• Built 4 Tableau", "• Responsible for 4 Tableau"), "")
        v = values(r)
        self.assertIsNone(v["keyword_match"])
        self.assertEqual(v["overall"], round5(0.65 * v["parse_safety"] + 0.35 * v["content_signals"]))
        self.assertEqual(r["scores"]["overall"]["explanation"], C.OVERALL_METHOD_NO_KM)

    def test_keyword_formula(self):
        rows = [
            {"importance": "required", "weight": 3.0, "credit": 1.0, "found": True, "evidence_level": "demonstrated"},
            {"importance": "required", "weight": 3.0, "credit": 0.0, "found": False, "evidence_level": "none"},
            {"importance": "preferred", "weight": 1.0, "credit": 1.0, "found": True, "evidence_level": "listed"},
            {"importance": "responsibility", "weight": 1.5, "credit": 0.5, "found": False, "evidence_level": "listed"},
        ]
        k = keyword_score(rows)
        self.assertAlmostEqual(k["R"], 0.5)
        self.assertAlmostEqual(k["P"], (1.0 + 0.75) / 2.5)
        self.assertAlmostEqual(k["E"], 3.0 / 4.0)
        self.assertAlmostEqual(k["value_raw"], 100 * (0.7 * 0.5 + 0.2 * 0.7 + 0.1 * 0.75))
        self.assertEqual(k["basis"], "required_preferred")

    def test_no_required_block_counts_every_term(self):
        rows = [{"importance": "responsibility", "weight": 1.5, "credit": 1.0, "found": True,
                 "evidence_level": "demonstrated"},
                {"importance": "unspecified", "weight": 1.0, "credit": 0.0, "found": False, "evidence_level": "none"}]
        k = keyword_score(rows)
        self.assertEqual(k["basis"], "all_terms")
        self.assertAlmostEqual(k["value_raw"], 100 * (0.9 * 0.6 + 0.1 * 1.0))
        jd = ("Marketing Intern\nWhat you'll do\n- Build Tableau dashboards\n- Analyze data in Excel and SQL\n"
              "- Write social media posts with Canva\n- Support HubSpot email campaigns\n" + "Padding line. " * 20)
        r = S.screen(CLEAN, jd)
        self.assertEqual(r["keywords"]["coverage"]["basis"], "all_terms")
        self.assertIn("no separate requirements list", r["scores"]["keyword_match"]["explanation"])
        self.assertIsNotNone(r["scores"]["keyword_match"]["value"])


class GateTests(unittest.TestCase):
    def test_critical_issue_caps_parse_safety_and_gates_overall(self):
        r = S.screen(S.make_doc(CLEAN, fmt="pdf", signals={"garbled": True}), PERFECT)
        self.assertLessEqual(r["scores"]["parse_safety"]["value"], 40)
        self.assertEqual(r["scores"]["parse_safety"]["band"], "Likely to mis-parse")
        self.assertLessEqual(r["scores"]["overall"]["value"], 40)
        self.assertEqual(r["scores"]["overall"]["band"], "Fix the file first")

    def test_many_high_issues_gate_without_critical(self):
        r = S.screen(S.make_doc(CLEAN, fmt="docx", signals={"columns": {"docx_multi_column": True},
                                                            "hidden_text": {"white": 1},
                                                            "tables": {"count": 1, "holds_experience": True},
                                                            "text_boxes": {"count": 1, "has_contact": True}}),
                     PERFECT)
        self.assertEqual(r["scores"]["parse_safety"]["value"], 40)
        self.assertEqual(r["scores"]["overall"]["band"], "Fix the file first")
        self.assertLessEqual(r["scores"]["overall"]["value"], 40)

    def test_no_text_is_scored_from_structure_only(self):
        r = S.screen(S.make_doc("", fmt="pdf", signals={"image_only": True, "text_layer": False}), JD)
        self.assertTrue(r["scores"]["parse_safety"]["band"].endswith("(text not checked)"))
        self.assertIsNone(r["scores"]["keyword_match"]["value"])
        self.assertIsNone(r["scores"]["content_signals"]["value"])
        self.assertEqual(r["scores"]["overall"]["band"], "Fix the file first")
        self.assertEqual([i for i in S.issue_ids(r) if i.startswith(("CONTACT", "SECT", "KW"))], [])


class NullKeywordTests(unittest.TestCase):
    def test_no_jd(self):
        r = S.screen(CLEAN, "")
        km = r["scores"]["keyword_match"]
        self.assertIsNone(km["value"])
        self.assertEqual(km["band"], "No job description provided")
        self.assertEqual(r["knockout_signals"], [])
        self.assertFalse([i for i in S.issue_ids(r) if i.startswith("KW")])
        self.assertEqual(r["keywords"]["status"], "no_jd")
        self.assertEqual(r["inputs"]["job_description"]["blocks"], [])

    def test_whitespace_only_jd_counts_as_none(self):
        self.assertEqual(S.screen(CLEAN, "  \n\t ")["keywords"]["status"], "no_jd")

    def test_short_jd(self):
        r = S.screen(CLEAN, "Marketing intern. Requirements: SQL, Excel, Tableau, Python and Canva.")
        km = r["scores"]["keyword_match"]
        self.assertIsNone(km["value"])
        self.assertEqual(km["band"], "Not enough job description to judge")
        self.assertFalse([i for i in S.issue_ids(r) if i.startswith("KW")])
        self.assertTrue(r["keywords"]["required"] or r["keywords"]["other"])

    def test_long_jd_with_few_terms(self):
        jd = "Office Helper\nRequirements\n- Excel\n- Be friendly and on time every single day\n" + \
             "We are a small family business that values kindness and good humor above all. " * 5
        r = S.screen(CLEAN, jd)
        self.assertGreaterEqual(r["inputs"]["job_description"]["chars"], 300)
        self.assertEqual(r["scores"]["keyword_match"]["band"], "Not enough job description to judge")

    def test_non_english_resume(self):
        es = ("Lucía Ejemplo\nMadrid, España | lucia.ejemplo@example.com | +34 600 000 000\nEXPERIENCIA\n"
              "Asistente de marketing en una empresa de ejemplo de la ciudad\n"
              "• Gestioné las redes sociales de la empresa y creé contenido para la página web\n"
              "• Analicé los datos de ventas con Excel y preparé informes para el equipo de dirección\n"
              "• Organicé eventos para los clientes de la tienda y coordiné a los voluntarios\n"
              "EDUCACIÓN\nGrado en Administración y Dirección de Empresas, Universidad de Ejemplo\n")
        r = S.screen(es, JD)
        self.assertEqual(r["language"], "es")
        km = r["scores"]["keyword_match"]
        self.assertIsNone(km["value"])
        self.assertIn("keyword dictionary is English-only", km["band"] + km["explanation"])
        self.assertEqual(r["keywords"]["note"], "keyword dictionary is English-only")
        self.assertIsNone(r["scores"]["content_signals"]["value"])
        self.assertTrue(r["scores"]["overall"]["band"].startswith("File readability only"))
        self.assertFalse([i for i in S.issue_ids(r) if i.startswith(("KW", "SECT", "CONTENT", "DATE"))])
        self.assertTrue(any("English-only" in x for x in r["limitations"]))

    def test_english_resume_with_foreign_names_stays_english(self):
        text = CLEAN.replace("University of Texas at Austin", "Universidad de la Rioja y del Mar")
        self.assertEqual(S.screen(text, JD)["language"], "en")


class ConfidenceAndDriversTests(unittest.TestCase):
    def test_confidence_multiplies_penalty(self):
        r = S.screen(S.make_doc(CLEAN, fmt="pdf", signals={"fonts": {"type0": 2, "tounicode": 0}}), PERFECT)
        it = S.issue(r, "PARSE-004")
        self.assertEqual(it["confidence"], "low")
        self.assertAlmostEqual(it["score_impact"]["parse_safety"], 15 * 0.4)
        self.assertEqual(r["scores"]["parse_safety"]["value"], round5(100 - 6))

    def test_drivers_are_real_issue_ids(self):
        r = S.screen(MESSY, JD)
        ids = set(S.issue_ids(r))
        for k in SCORE_KEYS:
            d = r["scores"][k]["drivers"]
            self.assertLessEqual(len(d), 3)
            self.assertTrue(set(d) <= ids, (k, d))

    def test_issue_ranking_order(self):
        r = S.screen(MESSY, JD)
        issues = r["issues"]
        self.assertEqual([i["rank"] for i in issues], list(range(1, len(issues) + 1)))
        sev = [C.SEVERITY_RANK[i["severity"]] for i in issues]
        self.assertEqual(sev, sorted(sev))
        for a, b in zip(issues, issues[1:]):
            if a["severity"] == b["severity"]:
                self.assertGreaterEqual(a["score_impact"]["overall"], b["score_impact"]["overall"])

    def test_each_issue_id_once(self):
        r = S.screen(MESSY, JD)
        ids = S.issue_ids(r)
        self.assertEqual(len(ids), len(set(ids)))


class GapTests(unittest.TestCase):
    GAP = ("Casey Example\nDenver, CO | casey.example@example.com | (555) 010-0150 | linkedin.com/in/casey-example\n"
           "EDUCATION\nExample State University, B.S. Accounting, May 2023\nEXPERIENCE\n"
           "Staff Accountant | Example Partners | Jun 2024 – Present\n• Reconciled 40 vendor accounts each month in Excel\n"
           "Audit Intern | Sample & Co | Jun 2023 – Aug 2023\n• Tested 25 expense reports for policy errors\n"
           "SKILLS\nExcel, SQL\n")

    def test_gap_is_info_and_does_not_move_scores(self):
        with_gap = S.screen(self.GAP, PERFECT, stage="early_career")
        no_gap = S.screen(self.GAP.replace("Jun 2024 – Present", "Sep 2023 – Present"), PERFECT, stage="early_career")
        it = S.issue(with_gap, "DATE-008")
        self.assertEqual(it["severity"], "info")
        self.assertEqual(it["score_impact"], {"parse_safety": 0, "keyword_match": 0, "content_signals": 0, "overall": 0})
        self.assertIsNone(S.issue(no_gap, "DATE-008"))
        self.assertEqual(values(with_gap), values(no_gap))
        self.assertEqual(with_gap["experience"]["gaps"], [{"from": "2023-09", "to": "2024-05", "months": 9}])
        self.assertIn("honest", it["fix"])
        self.assertIn("Never invent", it["honesty_note"])

    def test_recent_pause_is_info(self):
        r = S.screen(self.GAP.replace("Jun 2024 – Present", "Jun 2024 – Dec 2025"), PERFECT, stage="early_career")
        self.assertEqual(r["experience"]["months_since_last_activity"], 10)
        self.assertEqual(S.issue(r, "DATE-008")["severity"], "info")

    def test_total_months_and_current_student(self):
        r = S.screen(CLEAN, PERFECT)
        self.assertEqual(r["experience"]["total_months_experience"], 24)
        self.assertEqual(r["experience"]["months_since_last_activity"], 0)
        self.assertEqual(r["experience"]["gaps"], [])


if __name__ == "__main__":
    unittest.main()
