"""PDFs shaped like the two live-test resumes (fictional people), read end to end: ingest, then screening.

- sidebar_spaced.pdf: a browser-printed two-column template: name stacked one word per line, a
  headline, CSS letter-spaced headings, skill-rating dots, list bullets drawn as shapes (no bullet
  character in the text) and one wrapped bullet.
- shape_bullets.pdf: a thin resume whose bullets are small drawn squares.
Both are rebuilt by tests/fixtures/make_fixtures.py. The built-in reader runs everywhere; macOS PDFKit
runs too when it is available.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "fixtures"))
sys.path.insert(0, HERE)
import make_fixtures  # noqa: E402
import test_screen_support as S  # noqa: E402

from hp.ingest import doc_to_resume_md, ingest_file  # noqa: E402
from hp.ingest.pdf_text import pdfkit_available  # noqa: E402
from hp.screen import run_screening  # noqa: E402

JD = """Data Analyst Intern
Requirements
- Currently pursuing a bachelor's degree in statistics, data science, economics or a related field
- Experience with SQL
- Experience with Python or R for data analysis
- Experience with Excel (pivot tables, lookups)
- Strong written and verbal communication skills
Preferred Qualifications
- Experience with Tableau or Power BI
This sentence pads the posting so it is long enough to be scored fairly by the screening check.
This second sentence also pads the posting so the character count is high enough to score.
"""


def backends():
    out = ["builtin"]
    if pdfkit_available():
        out.append("pdfkit")
    return out


class SidebarSpacedPdfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = make_fixtures.shared_fixtures()["sidebar_spaced.pdf"]

    def screen(self, backend):
        doc = ingest_file(self.path, pdf_backends=[backend])
        return doc, run_screening(doc, JD, stage="student", as_of=S.AS_OF)

    def test_ingest_keeps_text_verbatim(self):
        for b in backends():
            with self.subTest(backend=b):
                doc = ingest_file(self.path, pdf_backends=[b])
                md = doc_to_resume_md(doc)
                self.assertIn("E D U C A T I O N", md)            # resume.md is never "fixed"
                self.assertIn("Python • • • •", md)
                self.assertGreater(doc["signals"]["letter_spaced"], 0)

    def test_screening(self):
        for b in backends():
            with self.subTest(backend=b):
                doc, r = self.screen(b)
                canon = [d["canonical"] for d in r["sections"]["detected"]]
                for want in ("education", "experience", "projects", "leadership_activities", "skills"):
                    self.assertIn(want, canon)
                ids = S.issue_ids(r)
                for wrong in ("SECT-001", "SECT-002", "SECT-003"):
                    self.assertNotIn(wrong, ids)
                self.assertEqual(S.issue(r, "PARSE-014")["severity"], "high")
                self.assertIn("PARSE-024", ids)
                self.assertEqual(r["contact"]["name"], "MORGAN ELLISON")
                work = [e for e in r["experience"]["entries"] if e["section"] != "education"]
                self.assertEqual(len(work), 4)                        # not a thin resume
                self.assertGreaterEqual(doc["words"], 150)
                self.assertEqual(sum(e["bullet_count"] for e in work), 8)
                self.assertEqual(r["bullets"]["count"], 8)
                cov = r["keywords"]["coverage"]
                self.assertEqual([t["term"] for t in r["keywords"]["required"]],
                                 ["statistics, data science, economics", "SQL", "Python or R", "data analysis",
                                  "Excel", "pivot tables", "communication"])
                self.assertEqual(cov["required_total"], 7)
                py = S.term(r, "Python or R")
                self.assertTrue(py["found"])
                self.assertEqual(py["evidence_level"], "demonstrated")
                deg = [t for t in r["keywords"]["required"] if t["group"] == "degree_field"][0]
                self.assertTrue(deg["found"])
                self.assertEqual(deg["matched_alternative"], "statistics")


class ShapeBulletsPdfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = make_fixtures.shared_fixtures()["shape_bullets.pdf"]

    def test_screening(self):
        jd = ("Patient Care Technician\nResponsibilities: Take and record vital signs.\n"
              "Requirements: High school diploma or GED. Current BLS/CPR certification. Excellent communication "
              "and teamwork. Able to work night shifts and every other weekend.\n"
              "Preferred: CNA certification. Previous experience in healthcare or customer service. Bilingual.\n"
              "This sentence pads the posting so it is long enough to be scored fairly by the screening check.\n")
        for b in backends():
            with self.subTest(backend=b):
                doc = ingest_file(self.path, pdf_backends=[b])
                r = run_screening(doc, jd, stage="student", as_of=S.AS_OF)
                ents = {e["header"].split(",")[0]: e for e in r["experience"]["entries"]}
                self.assertEqual(ents["Cashier"]["bullet_count"], 2)
                self.assertEqual(ents["Volunteer"]["bullet_count"], 1)
                self.assertNotIn("CONTENT-009", S.issue_ids(r))
                self.assertNotIn("Worked the register", r["keywords"]["job_title"]["resume_titles"])
                self.assertEqual(r["scores"]["content_signals"]["band"], "Needs work")
                self.assertEqual(r["contact"]["name"], "Riley Example")
                bls = [t for t in r["keywords"]["required"] if t["term"].startswith("BLS/CPR")][0]
                self.assertTrue(bls["found"])
                for it in r["issues"]:
                    for e in it["evidence"]:
                        self.assertNotIn("Cardiopulmonary", e)
                lang = [k for k in r["knockout_signals"] if k["type"] == "language"][0]
                self.assertEqual(lang["status"], "appears_met")


if __name__ == "__main__":
    unittest.main()
