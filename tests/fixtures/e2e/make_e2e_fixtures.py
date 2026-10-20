#!/usr/bin/env python3
"""Build the end-to-end test inputs (fictional candidate, fictional employer).

    python3 tests/fixtures/e2e/make_e2e_fixtures.py

Writes, next to this file:
  resume.docx   a typical one-page student resume made in Word: bold entry headers, real bullet
                numbering, dates after " | ", and the usual content problems (duty bullets, "helped
                with", a hedge ("about 600"), and an inflated claim ("300%") the panel should question)
  resume.pdf    the same resume as a plain text PDF (Helvetica, one page)
  jd.txt        the job posting as the student would paste it

Everyone and everything here is fictional: example.com email, a 555-01xx phone number, made-up
companies and school. The files are deterministic (fixed zip timestamps and PDF ids).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # tests/fixtures, for make_fixtures

import make_fixtures as mf  # noqa: E402

NAME = "Riley Castellano"
CONTACT = "Columbus, OH | (555) 010-0147 | riley.castellano@example.com | linkedin.com/in/riley-castellano-example"

# (kind, text) in reading order. kind: title | contact | heading | entry (bold org, rest plain) |
# role (italic role, rest plain) | bullet | para
LINES = [
    ("title", NAME),
    ("contact", CONTACT),
    ("heading", "EDUCATION"),
    ("entry", ("Lakeshore State University", ", Columbus, OH")),
    ("role", ("Bachelor of Science in Business Analytics, Minor in Marketing", " | Expected May 2027")),
    ("para", "GPA: 3.6/4.0 | Dean's List (3 semesters)"),
    ("para", "Relevant Coursework: Intro to SQL, Statistics for Business, Marketing Research, Data Visualization"),
    ("heading", "EXPERIENCE"),
    ("entry", ("Tallgrass Outfitters", ", Columbus, OH")),
    ("role", ("Marketing Intern", " | June 2025 – August 2025")),
    ("bullet", "Responsible for the weekly email newsletter to about 600 subscribers"),
    ("bullet", "Helped with Instagram posts 3x a week and tracked likes in a spreadsheet"),
    ("bullet", "Pulled weekly sales numbers into Excel for the Monday team meeting"),
    ("bullet", "Increased online sales by 300% during the summer sale"),
    ("entry", ("Cedar Hollow Market", ", Columbus, OH")),
    ("role", ("Shift Lead", " | September 2023 – Present")),
    ("bullet", "Trained 4 new cashiers on the register and the opening checklist"),
    ("bullet", "Handle closing cash counts and customer questions at the service desk"),
    ("bullet", "Work about 18 hours a week during the semester"),
    ("heading", "PROJECTS"),
    ("entry", ("Campus Bike Share Survey", ", Marketing Research class project")),
    ("role", ("Team of 4", " | January 2025 – May 2025")),
    ("bullet", "Designed a 12 question survey with 3 classmates and collected 140 responses"),
    ("bullet", "Analyzed the results in Excel with pivot tables and presented a pricing recommendation"),
    ("heading", "LEADERSHIP & ACTIVITIES"),
    ("entry", ("Lakeshore Analytics Club", ", Columbus, OH")),
    ("role", ("Member", " | January 2024 – Present")),
    ("bullet", "Helped organize 2 Excel workshops for first-year students"),
    ("heading", "SKILLS"),
    ("para", "Tools: Excel (pivot tables, VLOOKUP), Google Sheets, Canva, Mailchimp"),
    ("para", "Data: SQL (class projects), Python (intro course)"),
    ("para", "Languages: English, Spanish (conversational)"),
]

JD = """Marketing Analytics Intern (Summer 2026)
Northwind Foods – Columbus, OH (Hybrid)

About Northwind Foods
Northwind Foods is a fictional regional grocery brand with 60 stores across Ohio and Indiana.

What You'll Do
- Build weekly dashboards that track email and social campaign performance
- Analyze customer and sales data with SQL and Excel
- Support A/B testing of email subject lines with the CRM team
- Present findings to the marketing team every two weeks

Requirements
- Currently pursuing a bachelor's degree in Business Analytics, Marketing, Statistics or a related field
- Experience with SQL and Microsoft Excel (pivot tables, VLOOKUP)
- Strong written and verbal communication skills
- Able to work 20 hours per week during the summer

Preferred Qualifications
- Experience with Tableau or Power BI
- Familiarity with Google Analytics
- Experience with email marketing tools such as Mailchimp

Pay: $20 per hour. This internship is hybrid, 3 days a week in our Columbus office.
Applicants must be authorized to work in the United States. Northwind Foods does not sponsor visas for this role.
Northwind Foods is an equal opportunity employer. All qualified applicants will receive consideration without regard to race, color, religion, sex, sexual orientation, gender identity, national origin, disability or veteran status.
"""


def docx_body():
    out = []
    for kind, text in LINES:
        if kind == "title":
            out.append(mf.p(text, style="Title"))
        elif kind == "contact":
            out.append(mf.p(text))
        elif kind == "heading":
            out.append(mf.p([mf.r(text, "<w:b/><w:sz w:val=\"24\"/>")]))
        elif kind == "entry":
            out.append(mf.p([mf.r(text[0], "<w:b/>"), mf.r(text[1])]))
        elif kind == "role":
            out.append(mf.p([mf.r(text[0], "<w:i/>"), mf.r(text[1])]))
        elif kind == "bullet":
            out.append(mf.bullet(text))
        else:
            out.append(mf.p(text))
    return "".join(out)


def pdf_lines():
    out = []
    for kind, text in LINES:
        if isinstance(text, tuple):
            text = "".join(text)
        out.append(("• " + text) if kind == "bullet" else text)
    return out


def build(out_dir=HERE):
    mf.docx(os.path.join(out_dir, "resume.docx"), docx_body(), app=mf.app_xml(pages=1))
    content = mf.text_lines_content(pdf_lines(), x=54, y=750, size=10, leading=14)
    with open(os.path.join(out_dir, "resume.pdf"), "wb") as f:
        f.write(mf.single_page_pdf(content, info_dict=b"<< /Producer (Fictional Word Processor PDF export) >>"))
    with open(os.path.join(out_dir, "jd.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(JD)
    return out_dir


if __name__ == "__main__":
    print(build())
