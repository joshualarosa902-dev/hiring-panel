"""Every issue id in the catalogue fires on a minimal case and stays quiet on a clean resume."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_screen_support as S  # noqa: E402

from hp.screen.constants import CATALOGUE  # noqa: E402

CLEAN = S.fixture("resume_clean.txt")
PERFECT = S.fixture("jd_perfect.txt")
CONTACT_LINE = "Austin, TX | avery.quinn@example.com | (555) 010-0142 | linkedin.com/in/avery-quinn-example"
SALES_HDR = "Sales Associate | Bluebird Books | Austin, TX | Sep 2023 – May 2025"
INTERN_HDR = "Marketing Intern | Northwind Foods | Austin, TX | Jun 2025 – Aug 2025"


def edit(old, new, text=CLEAN):
    assert old in text, old
    return text.replace(old, new)


def drop_block(heading, text=CLEAN):
    """Remove a section heading and its lines (up to the next all-caps heading)."""
    out, skip = [], False
    for ln in text.splitlines():
        if ln.strip() == heading:
            skip = True
            continue
        if skip and ln.isupper() and len(ln.split()) <= 3:
            skip = False
        if not skip:
            out.append(ln)
    return "\n".join(out) + "\n"


def doc(text=CLEAN, **kw):
    return S.make_doc(text, **kw)


def run(d, jd=PERFECT, **kw):
    return S.screen(d, jd, **kw)


GAP_RESUME = """Casey Example
Denver, CO | casey.example@example.com | (555) 010-0150 | linkedin.com/in/casey-example
EDUCATION
Example State University, B.S. Accounting, May 2023
EXPERIENCE
Staff Accountant | Example Partners | Jun 2024 – Present
• Reconciled 40 vendor accounts each month in Excel
Audit Intern | Sample & Co | Jun 2023 – Aug 2023
• Tested 25 expense reports for policy errors
SKILLS
Excel, SQL
"""

# id -> (builder returning (doc, jd, kwargs), expected severity)
CASES = {
    "PARSE-001": (lambda: (doc(signals={"image_only": True}, fmt="pdf"), PERFECT, {}), "critical"),
    "PARSE-002": (lambda: (doc("", signals={"encrypted": True}, fmt="pdf"), PERFECT, {}), "critical"),
    "PARSE-003": (lambda: (doc(signals={"garbled": True}, fmt="pdf"), PERFECT, {}), "critical"),
    "PARSE-004": (lambda: (doc(fmt="pdf", signals={"fonts": {"type0": 2, "tounicode": 0}}), PERFECT, {}), "high"),
    "PARSE-005": (lambda: (doc(fmt="pdf", signals={"fonts": {"type3": 1}}), PERFECT, {}), "medium"),
    "PARSE-006": (lambda: (doc(edit(CONTACT_LINE + "\n", ""), header_footer=[("header", CONTACT_LINE)]), PERFECT, {}),
                  "high"),
    "PARSE-007": (lambda: (doc(fmt="docx", where={1: "textbox"}, signals={"text_boxes": {"count": 1}}), PERFECT, {}),
                  "high"),
    "PARSE-008": (lambda: (doc(fmt="docx", where={7: "table"}, signals={"tables": {"count": 1}}), PERFECT, {}),
                  "high"),
    "PARSE-009": (lambda: (doc(fmt="docx", signals={"columns": {"docx_multi_column": True}}), PERFECT, {}), "high"),
    "PARSE-009b": (lambda: (doc(edit(
        INTERN_HDR + "\n", "Jun 2025 – Aug 2025\nSep 2023 – May 2025\nJan 2025 – Apr 2025\nMarketing Intern\n")),
        PERFECT, {}), "medium"),
    "PARSE-010": (lambda: (doc(fmt="docx", signals={"images": {"count": 1, "large": 1}}), PERFECT, {}), "medium"),
    "PARSE-011": (lambda: (doc(bytes=3000000), PERFECT, {}), "high"),
    "PARSE-012": (lambda: (doc(fmt="doc"), PERFECT, {}), "high"),
    "PARSE-013": (lambda: (doc(fmt="pdf", producer="Canva"), PERFECT, {}), "info"),
    "PARSE-014": (lambda: (doc(edit("Avery Quinn\n", "A V E R Y   Q U I N N\n")), PERFECT, {}), "medium"),
    "PARSE-015": (lambda: (doc(signals={"private_use_chars": 3}), PERFECT, {}), "low"),
    "PARSE-016": (lambda: (doc(fmt="docx", signals={"hidden_text": {"white": 2}}), PERFECT, {}), "high"),
    "PARSE-017": (lambda: (doc(fmt="docx", signals={"caps_formatting": 2}), PERFECT, {}), "low"),
    "PARSE-018": (lambda: (doc(fmt="docx", signals={"fields": {"mergefield": 1}}), PERFECT, {}), "low"),
    "PARSE-019": (lambda: (doc(fmt="docx", signals={"tracked_changes": 1}), PERFECT, {}), "medium"),
    "PARSE-020": (lambda: (doc(edit("Bluebird Books", "Company A")), PERFECT, {}), "high"),
    "PARSE-021": (lambda: (doc(CLEAN + "Page 1 of 2\n"), PERFECT, {}), "low"),
    "PARSE-022": (lambda: (doc(fmt="pdf", pages=3), PERFECT, {}), "info"),
    "PARSE-023": (lambda: (doc(fmt="docx", signals={"tab_merged_tokens": 2}), PERFECT, {}), "medium"),
    "PARSE-024": (lambda: (doc(CLEAN + "Python ● ● ● ○ ○\n"), PERFECT, {}), "low"),
    "CONTACT-001": (lambda: (doc(edit("avery.quinn@example.com | ", "")), PERFECT, {}), "high"),
    "CONTACT-002": (lambda: (doc(edit("(555) 010-0142 | ", "")), PERFECT, {}), "medium"),
    "CONTACT-003": (lambda: (doc(edit("Austin, TX | avery", "avery")), PERFECT, {}), "low"),
    "CONTACT-004": (lambda: (doc(edit(" | linkedin.com/in/avery-quinn-example", "")), PERFECT, {}), "info"),
    "CONTACT-005": (lambda: (doc(edit("Austin, TX | avery", "1200 Example Lane, Austin, TX | avery")), PERFECT, {}),
                    "info"),
    "CONTACT-006": (lambda: (doc(edit(CONTACT_LINE + "\n", "") + CONTACT_LINE + "\n"), PERFECT, {}), "low"),
    "CONTACT-007": (lambda: (doc(edit("| (555)", "| avery.q@example.org | (555)")), PERFECT, {}), "low"),
    "SECT-001": (lambda: (doc(drop_block("EDUCATION")), PERFECT, {}), "high"),
    "SECT-002": (lambda: (doc(drop_block("LEADERSHIP", drop_block("PROJECTS", drop_block("EXPERIENCE")))), PERFECT, {}),
                 "high"),
    "SECT-003": (lambda: (doc(drop_block("SKILLS")), PERFECT, {}), "medium"),
    "SECT-004": (lambda: (doc(edit("EXPERIENCE\n", "INDUSTRY EXPERIENCE\n")), PERFECT, {}), "low"),
    "SECT-005": (lambda: (doc(edit("SKILLS\n", "SKILLS & INTERESTS\n")), PERFECT, {}), "low"),
    "SECT-006": (lambda: (doc(CLEAN + "References available upon request\n"), PERFECT, {}), "low"),
    "SECT-007": (lambda: (doc(edit("EDUCATION\n", "WHERE I STUDY\n")), PERFECT, {}), "medium"),
    "DATE-001": (lambda: (doc(edit(SALES_HDR, "Sales Associate | Bluebird Books | Austin, TX")), PERFECT, {}),
                 "medium"),
    "DATE-002": (lambda: (doc(edit("Sep 2023 – May 2025", "2023 – 2025")), PERFECT, {}), "low"),
    "DATE-003": (lambda: (doc(edit(SALES_HDR, "Sales Associate | Bluebird Books | Austin, TX | Sep 2023\n– May 2025")),
                          PERFECT, {}), "medium"),
    "DATE-004": (lambda: (doc(edit("Sep 2023 – May 2025", "09/2023 – 05/2025")), PERFECT, {}), "low"),
    "DATE-005": (lambda: (doc(edit("Sep 2023 – May 2025", "Sep 2023 – May 2022")), PERFECT, {}), "high"),
    "DATE-006": (lambda: (doc(edit("Expected May 2027", "May 2027")), PERFECT, {}), "medium"),
    "DATE-007": (lambda: (doc(edit("Jun 2025 – Aug 2025", "Jun 2022 – Aug 2022")), PERFECT, {}), "low"),
    "DATE-008": (lambda: (doc(GAP_RESUME), PERFECT, {"stage": "early_career"}), "info"),
    "DATE-009": (lambda: (doc(edit("Jun 2025 – Aug 2025", "06/25 – 08/25")), PERFECT, {}), "low"),
    "KW-001": (lambda: (doc(), PERFECT.replace("- Excel pivot tables", "- Excel pivot tables\n- Salesforce"), {}),
               "medium"),
    "KW-002": (lambda: (doc(), PERFECT.replace("- Excel pivot tables", "- Excel pivot tables\n- Canva"), {}), "medium"),
    "KW-003": (lambda: (doc(), PERFECT.replace("- A/B testing", "- split testing"), {}), "low"),
    "KW-004": (lambda: (doc(), PERFECT.replace("Marketing Intern\n", "Data Engineer\n", 1), {}), "low"),
    "KW-005": (lambda: (doc(), PERFECT.replace("- A/B testing", "- A/B testing\n- HubSpot"), {}), "info"),
    "CONTENT-001": (lambda: (doc(_unquantified()), PERFECT, {}), "medium"),
    "CONTENT-002": (lambda: (doc(edit("• Organized a weekly", "• Responsible for a weekly")), PERFECT, {}), "low"),
    "CONTENT-003": (lambda: (doc(edit("• Trained 5 new hires on customer service standards",
                                      "• Trained 5 new hires on customer service standards " + "and more " * 16)),
                             PERFECT, {}), "low"),
    "CONTENT-004": (lambda: (doc(edit("• Trained 5 new hires on customer service standards", "• Did filing")), PERFECT,
                             {}), "low"),
    "CONTENT-005": (lambda: (doc(edit("• Organized a weekly", "• I organized a weekly")), PERFECT, {}), "low"),
    "CONTENT-006": (lambda: (doc(edit("• Wrote 30", "• Built 30").replace("• Analyzed survey", "• Built survey")
                                 .replace("• Planned 3", "• Built 3")), PERFECT, {}), "low"),
    "CONTENT-007": (lambda: (doc(edit("• Organized a weekly", "• Organize a weekly")), PERFECT, {}), "low"),
    "CONTENT-008": (lambda: (doc(edit("EDUCATION\n", "SUMMARY\nHard-working team player.\nEDUCATION\n")), PERFECT, {}),
                    "info"),
    "CONTENT-009": (lambda: (doc(edit("• Served 60 customers per shift and processed returns at the register\n"
                                      "• Organized a weekly inventory count across 2 store locations\n"
                                      "• Trained 5 new hires on customer service standards\n", "")), PERFECT, {}),
                    "low"),
    "CONTENT-010": (lambda: (doc(edit("Sales Associate |", "Sr. Sales Assoc. |")), PERFECT, {}), "low"),
}


def _unquantified():
    t = CLEAN
    for old, new in (("• Built 4 Tableau dashboards that tracked weekly sales for 12 stores",
                      "• Built Tableau dashboards that tracked weekly sales"),
                     ("• Wrote 30 social media posts that reached 18,000 followers on Instagram",
                      "• Wrote social media posts for Instagram"),
                     ("• Analyzed survey data from 450 customers in Excel using pivot tables",
                      "• Analyzed survey data in Excel using pivot tables"),
                     ("• Planned 3 product sampling events with 200 attendees each", "• Planned product sampling events"),
                     ("• Served 60 customers per shift and processed returns at the register",
                      "• Served customers and processed returns at the register"),
                     ("• Organized a weekly inventory count across 2 store locations", "• Organized a weekly inventory count"),
                     ("• Trained 5 new hires on customer service standards", "• Trained new hires on customer service"),
                     ("• Ran A/B testing on menu prices at 2 student cafes and presented results to 15 managers",
                      "• Ran A/B testing on menu prices and presented results"),
                     ("• Used SQL and Python to clean 3,000 transaction records for the pricing model",
                      "• Used SQL and Python to clean transaction records"),
                     ("• Managed a $4,500 annual budget and tracked spending for 40 members",
                      "• Managed the annual budget and tracked spending")):
        t = edit(old, new, t)
    return t


class CatalogueCoverageTests(unittest.TestCase):
    def test_every_catalogue_id_has_a_case(self):
        self.assertEqual(sorted(CASES), sorted(CATALOGUE))

    def test_catalogue_text_rules(self):
        for iid, c in CATALOGUE.items():
            for field in ("title", "why", "fix", "honesty"):
                txt = c.get(field) or ""
                self.assertNotIn("—", txt, iid)
                self.assertNotIn("ATS score", txt, iid)
            self.assertLessEqual(len(c["title"].replace("{doc}", "resume").replace("{pages}", "2")), 90, iid)
            if iid.startswith("KW-"):
                self.assertEqual(c.get("honesty"), "Only add a term you can back up in an interview.")


class FiresAndQuietTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.clean_txt = S.issue_ids(run(doc()))
        cls.clean_docx = S.issue_ids(run(doc(fmt="docx", method="docx-xml")))
        cls.clean_pdf = S.issue_ids(run(doc(fmt="pdf", method="pdfplumber", pages=1,
                                           signals={"columns": {"pdf_check": "performed"}})))

    def test_clean_resume_is_quiet(self):
        self.assertEqual(self.clean_txt, [])
        self.assertEqual(self.clean_docx, [])
        self.assertEqual(self.clean_pdf, [])

    def test_each_issue_fires_on_its_minimal_case(self):
        for iid, (build, severity) in sorted(CASES.items()):
            with self.subTest(iid=iid):
                d, jd, kw = build()
                r = run(d, jd, **kw)
                it = S.issue(r, iid)
                self.assertIsNotNone(it, "%s did not fire; got %s" % (iid, S.issue_ids(r)))
                self.assertEqual(it["severity"], severity)
                self.assertNotIn(iid, self.clean_txt)


class SeverityVariantTests(unittest.TestCase):
    def test_textbox_without_contact_is_medium(self):
        r = run(doc(fmt="docx", where={19: "textbox"}, signals={"text_boxes": {"count": 1}}))
        self.assertEqual(S.issue(r, "PARSE-007")["severity"], "medium")

    def test_layout_table_is_medium(self):
        r = run(doc(fmt="docx", where={25: "table"}, signals={"tables": {"count": 1}}))
        self.assertEqual(S.issue(r, "PARSE-008")["severity"], "medium")

    def test_small_icons_are_low_and_ole_is_medium(self):
        r = run(doc(fmt="docx", signals={"images": {"count": 2, "small_icons": 2},
                                         "fields": {"ole": 1}}))
        self.assertEqual(S.issue(r, "PARSE-010")["severity"], "low")
        self.assertEqual(S.issue(r, "PARSE-018")["severity"], "medium")

    def test_photo_is_info_where_customary(self):
        r = run(doc(fmt="docx", signals={"images": {"count": 1, "large": 1}}), locale="de-DE")
        self.assertEqual(S.issue(r, "PARSE-010")["severity"], "info")

    def test_design_tool_is_medium_with_columns(self):
        r = run(doc(fmt="pdf", producer="Canva", signals={"columns": {"pdf_gutter_pages": [1]}}))
        self.assertEqual(S.issue(r, "PARSE-013")["severity"], "medium")

    def test_type0_becomes_part_of_parse003_when_garbled(self):
        r = run(doc(fmt="pdf", signals={"garbled": True, "fonts": {"type0": 3, "tounicode": 1}}))
        self.assertIn("PARSE-003", S.issue_ids(r))
        self.assertNotIn("PARSE-004", S.issue_ids(r))

    def test_hidden_text_confidence_and_honesty(self):
        r = run(doc(fmt="pdf", signals={"hidden_text": {"pdf_invisible": 1}}))
        it = S.issue(r, "PARSE-016")
        self.assertEqual(it["confidence"], "low")
        self.assertTrue(it["honesty_note"])

    def test_sect002_medium_when_projects_exist(self):
        r = run(doc(drop_block("EXPERIENCE")))
        self.assertEqual(S.issue(r, "SECT-002")["severity"], "medium")

    def test_sect001_only_for_students(self):
        r = run(doc(drop_block("EDUCATION")), stage="experienced")
        self.assertNotIn("SECT-001", S.issue_ids(r))

    def test_kw001_high_when_most_required_missing(self):
        jd = PERFECT.replace("- SQL and Python\n- Tableau dashboards\n- Excel pivot tables",
                             "- Salesforce and HubSpot\n- Power BI\n- QuickBooks\n- SQL")
        r = run(doc(), jd)
        self.assertEqual(S.issue(r, "KW-001")["severity"], "high")

    def test_unreadable_file_errors_become_parse003(self):
        d = doc("", fmt="docx", errors=[{"code": "xml_dtd_refused", "detail": "entity declaration"}])
        r = run(d)
        self.assertIn("PARSE-003", S.issue_ids(r))
        self.assertEqual(r["scores"]["parse_safety"]["value"], 40)

    def test_us_only_advice_not_given_outside_en(self):
        r = run(doc(edit("Austin, TX | avery", "1200 Example Lane, Austin, TX | avery")), locale="de-DE")
        self.assertNotIn("CONTACT-005", S.issue_ids(r))

    def test_cv_word_for_uk_and_fixed_disclaimer(self):
        from hp.screen.constants import DISCLAIMER
        r = run(doc(edit("EXPERIENCE\n", "INDUSTRY EXPERIENCE\n")), locale="en-GB")
        self.assertIn("your CV", S.issue(r, "SECT-004")["why_it_matters"])
        self.assertEqual(r["disclaimer"], DISCLAIMER)

    def test_non_us_contact_formats(self):
        text = edit(CONTACT_LINE, "London, UK | avery.quinn@example.com | +44 7700 900123")
        r = run(doc(text), locale="en-GB")
        self.assertEqual(r["contact"]["location"], "London, UK")
        self.assertEqual(r["contact"]["phone"], "+44 7700 900123")
        for iid in ("CONTACT-002", "CONTACT-003"):
            self.assertNotIn(iid, S.issue_ids(r))
        text = edit(CONTACT_LINE, "Berlin, Germany | avery.quinn@example.com | 030 1234567")
        r = run(doc(text), locale="de-DE")
        self.assertEqual(r["contact"]["phone"], "030 1234567")

    def test_inline_label_inside_education_does_not_split_entries(self):
        text = edit("GPA: 3.7/4.0\n", "Relevant Coursework: Statistics, Consumer Behavior\nGPA: 3.7/4.0\n")
        r = run(doc(text))
        self.assertNotIn("DATE-001", S.issue_ids(r))
        self.assertEqual(len([e for e in r["experience"]["entries"] if e["section"] == "education"]), 1)
        cw = [d for d in r["sections"]["detected"] if d["inline"]]
        self.assertEqual(cw[0]["canonical"], "coursework")

    def test_wrapped_bullet_tail_is_joined(self):
        text = edit("• Organized a weekly inventory count across 2 store locations",
                    "• Organized a weekly inventory count across 2 store\nlocations and fixed 40 shelf labels")
        r = run(doc(text, fmt="pdf"))
        self.assertEqual(S.issue_ids(r), [])
        sales = [e for e in r["experience"]["entries"] if e["header"].startswith("Sales Associate")][0]
        self.assertEqual(sales["bullet_count"], 3)

    def test_encrypted_but_readable_is_high_not_critical(self):
        r = run(doc(fmt="pdf", signals={"encrypted": True}))
        it = S.issue(r, "PARSE-002")
        self.assertEqual((it["severity"], it["confidence"]), ("high", "medium"))

    def test_evidence_is_masked_and_short(self):
        r = run(doc(edit(CONTACT_LINE + "\n", ""), header_footer=[("header", CONTACT_LINE)]))
        for it in r["issues"]:
            for e in it["evidence"]:
                self.assertNotIn("avery.quinn@example.com", e)
                self.assertNotIn("010-0142", e)
                self.assertLessEqual(len(e), 200)


if __name__ == "__main__":
    unittest.main()
