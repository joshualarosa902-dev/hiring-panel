"""Regression tests for problems found in live end-to-end runs (fictional people and companies only).

Each class names the finding it guards. Most cases use the real dictionary in hp/data, because the
problems came from real dictionary entries (R, BLS, CPR, Communication, Vital Signs).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_screen_support as S  # noqa: E402

from hp.screen import make_brief, render_screening_md  # noqa: E402
from hp.screen.lexicon import load_lexicon  # noqa: E402
from hp.screen.sections import RLine, heading_view  # noqa: E402
from hp.screen.textutil import collapse_letter_spacing, letter_spaced_runs, strip_rating  # noqa: E402

PAD = "\n" + "This sentence pads the posting so it is long enough to score. " * 6
REAL = None          # data_dir=None: the shipped dictionary


def real(text, jd="", **kw):
    kw.setdefault("data_dir", REAL)
    return S.screen(text, jd, **kw)


def posting(required, preferred=(), title="Data Intern"):
    text = "%s\nRequirements\n" % title + "\n".join("- " + r for r in required) + "\n"
    if preferred:
        text += "Preferred Qualifications\n" + "\n".join("- " + p for p in preferred) + "\n"
    return text + PAD


CONTACT = "Fairview, NE | sam.example@example.com | (555) 010-0123\n"


def resume(bullets=(), skills="", education="Example State University, B.S. Statistics, Expected May 2027",
           head="Sam Example\n"):
    text = head + CONTACT + "EDUCATION\n%s\n" % education
    text += "EXPERIENCE\nResearch Assistant | Example Lab | Sep 2025 – Present\n"
    text += "".join("• %s\n" % b for b in bullets)
    if skills:
        text += "SKILLS\n%s\n" % skills
    return text


SPACED = """MORGAN
ELLISON
Aspiring Data Analyst
C O N T A C T
morgan.ellison@example.com
(555) 010-0144
Fairview, NE
S K I L L S
Python • • • •
R • • •
I N T E R E S T S
Chess, trail running
E D U C AT I O N
Prairie Example University
B.S. Statistics, minor in Economics • GPA 3.5 • Expected May 2027
W O R K E X P E R I E N C E
Research Assistant, Example Behavior Lab
Prairie Example University • Sep 2025 – Present
Cleaned survey data in R for a study with 200 participants
Responsible for making charts for the weekly lab meeting
Barista
Example Grind Coffee • Jun 2024 – Aug 2025
Trained 3 new hires on the espresso machine and opening checklist
Handled cash and customer orders during the morning rush
P R O J E C T S
Shot Chart Analysis
Personal project • Mar 2025 – May 2025
Used Python (pandas, matplotlib) to analyze 8,000 shots from public game data
and plot shooting percentage by distance
"""


class LetterSpacingTests(unittest.TestCase):
    """A1, A5, A22: letter-spaced headings are headings; PARSE-014 says so; no false SECT-001/002."""

    def test_runs_and_collapse(self):
        self.assertEqual(collapse_letter_spacing("E D U C A T I O N")[0], "EDUCATION")
        self.assertEqual(collapse_letter_spacing("E D U C AT I O N")[0], "EDUCATION")     # kerned pair kept
        text = "Skills: P Y T H O N, Excel"
        out, idx = collapse_letter_spacing(text)
        self.assertEqual(out, "Skills: PYTHON, Excel")
        self.assertEqual(text[idx[out.index("PYTHON")]:idx[out.index("PYTHON") + 5] + 1], "P Y T H O N")
        for normal in ("I am a U S citizen", "Plan A or B", "A B C", "Grade: A in 3 courses"):
            self.assertEqual(letter_spaced_runs(normal), [], normal)

    def test_multiword_heading_is_split_back_into_words(self):
        rl = RLine(1, "W O R K E X P E R I E N C E")
        self.assertEqual(heading_view(rl, load_lexicon()), "WORK EXPERIENCE")

    def test_spaced_headings_are_sections(self):
        r = real(SPACED)
        canon = [d["canonical"] for d in r["sections"]["detected"]]
        for want in ("contact", "skills", "interests", "education", "experience", "projects"):
            self.assertIn(want, canon)
        heads = [d["heading"] for d in r["sections"]["detected"]]
        self.assertIn("E D U C AT I O N", heads)        # quoted as written, not as joined up
        ids = S.issue_ids(r)
        for wrong in ("SECT-001", "SECT-002", "SECT-003", "SECT-007"):
            self.assertNotIn(wrong, ids)
        it = S.issue(r, "PARSE-014")
        self.assertEqual(it["severity"], "high")
        self.assertIn("headings are letter-spaced", it["title"])
        self.assertIn("E D U C AT I O N", it["evidence"])

    def test_spaced_name_is_not_a_heading_issue(self):
        r = real("S A M   E X A M P L E\n" + resume(["Built 3 charts for the weekly lab meeting"])[len("Sam Example\n"):])
        it = S.issue(r, "PARSE-014")
        self.assertEqual(it["severity"], "medium")
        self.assertNotIn("headings", it["title"])


class SectionFallbackTests(unittest.TestCase):
    """A5, A15: content that is clearly there is never reported missing, and entries still count."""

    def test_unrecognized_education_heading(self):
        text = resume(["Cleaned survey data for 3 studies"]).replace("EDUCATION\n", "WHERE I STUDY\n")
        r = real(text)
        ids = S.issue_ids(r)
        self.assertNotIn("SECT-001", ids)
        it = S.issue(r, "SECT-007")
        self.assertEqual(it["severity"], "medium")
        self.assertIn("Education details found", it["evidence"][0])

    def test_no_recognized_headings_still_gives_entries(self):
        text = ("Sam Example\n" + CONTACT + "My Story So Far\n"
                "Barista | Example Coffee | Jun 2024 – Aug 2025\n"
                "• Trained 3 new hires on the opening checklist\n"
                "Cashier | Example Market | Jan 2023 – May 2024\n"
                "• Handled the register for about 80 customers a shift\n"
                "Learning\nExample State University, B.S. Statistics, Expected May 2027\n")
        r = real(text)
        ids = S.issue_ids(r)
        self.assertNotIn("SECT-001", ids)
        self.assertNotIn("SECT-002", ids)
        self.assertIn("SECT-007", ids)
        work = [e for e in r["experience"]["entries"] if e["section"] != "education"]
        self.assertGreaterEqual(len(work), 2)                 # hp.py's thin flag needs 2 entries
        self.assertTrue(all(e["date_text"] for e in work))

    def test_job_under_an_unread_heading_after_education(self):
        text = ("Sam Example\n" + CONTACT + "EDUCATION\nExample State University, B.S. Statistics, Expected May 2027\n"
                "Where I Have Worked\nBarista | Example Coffee | Jun 2024 – Aug 2025\n"
                "• Trained 3 new hires on the opening checklist\n• Handled the register for 80 customers a shift\n"
                "Cashier | Example Market | Jan 2023 – May 2024\n• Counted the drawer at close\n")
        r = real(text)
        self.assertNotIn("SECT-002", S.issue_ids(r))
        self.assertIn("SECT-007", S.issue_ids(r))
        self.assertEqual([e["section"] for e in r["experience"]["entries"]], ["education", "other", "other"])
        self.assertEqual(r["bullets"]["count"], 3)

    def test_degree_cues(self):
        from hp.screen.terms import degree_field_spans
        cases = {"Bachelor of Science in Nursing required": ["Nursing"],
                 "Degree (BS/BA) in Marketing, Communications, or Business": ["Marketing, Communications, or Business"],
                 "High degree of autonomy in Excel reporting": [],
                 "High school diploma or GED": []}
        for text, want in cases.items():
            self.assertEqual([text[a:b] for a, b in degree_field_spans(text)], want, text)

    def test_truly_missing_sections_still_reported(self):
        r = real("Sam Example\n" + CONTACT + "SKILLS\nExcel, Python\n")
        self.assertIn("SECT-001", S.issue_ids(r))
        self.assertIn("SECT-002", S.issue_ids(r))


class NameTests(unittest.TestCase):
    """A10: stacked names are joined; a headline is never a name; unsure means None."""

    def test_stacked_name(self):
        self.assertEqual(real(SPACED)["contact"]["name"], "MORGAN ELLISON")

    def test_headline_is_never_the_name(self):
        for headline in ("Aspiring Data Analyst", "Marketing Student", "Software Engineering Intern",
                         "Patient Care Technician"):
            r = real(headline + "\n" + resume()[len("Sam Example\n"):])
            self.assertIsNone(r["contact"]["name"], headline)

    def test_normal_name_still_found(self):
        self.assertEqual(real(resume())["contact"]["name"], "Sam Example")

    def test_single_word_top_line_gives_none(self):
        r = real("SAM\nAspiring Analyst\n" + resume()[len("Sam Example\n"):])
        self.assertIsNone(r["contact"]["name"])


class LostBulletTests(unittest.TestCase):
    """A2, B 2.2, 2.3, 6.7: bullets without glyphs are still bullets; tails join; content is not
    called polished on a tiny resume."""

    THIN = ("Riley Example\nFairview, SD • riley.example@example.com • 555-010-0181\nEducation\n"
            "Example Valley University, Pre-Nursing, first year\nExpected graduation: May 2029\nWork\n"
            "Cashier, Example Grocery, 2024 - present\nWorked the register\nStocked shelves\nVolunteer\n"
            "Volunteer, Example Food Pantry, 2023\nHelped sort donations\nSkills\n"
            "Microsoft Word, CPR certified, bilingual (English and Mandarin)\n")

    def test_lines_under_a_dated_header_are_bullets(self):
        r = real(self.THIN, posting(["Customer service", "Communication", "Teamwork", "CPR", "Excel"],
                                    title="Patient Care Technician"))
        ents = {e["header"].split(",")[0]: e for e in r["experience"]["entries"]}
        self.assertEqual(ents["Cashier"]["bullet_count"], 2)
        self.assertEqual(ents["Volunteer"]["bullet_count"], 1)
        self.assertNotIn("CONTENT-009", S.issue_ids(r))                 # no "No bullets" claim
        self.assertNotIn("Worked the register", r["keywords"]["job_title"]["resume_titles"])
        self.assertIn("helped", r["bullets"]["weak_openers"])

    def test_few_bullets_cap_content_signals(self):
        r = real(self.THIN)
        cs = r["scores"]["content_signals"]
        self.assertLessEqual(cs["value"], 65)
        self.assertEqual(cs["band"], "Needs work")
        self.assertIn("too little bullet text", cs["explanation"])

    def test_wrapped_tail_joins_the_bullet(self):
        r = real(SPACED)
        proj = [e for e in r["experience"]["entries"] if e["section"] == "projects"]
        self.assertEqual(len(proj), 1)
        self.assertEqual(proj[0]["bullet_count"], 1)
        self.assertGreaterEqual(r["bullets"]["count"], 5)

    def test_title_like_lines_are_not_bullets(self):
        text = ("Sam Example\n" + CONTACT + "EXPERIENCE\nLead Organizer, Example Food Drive\n"
                "Jan 2024 – Mar 2024\nCollected 400 cans with a team of 6\nData Entry Clerk, Example County Office\n"
                "Jun 2023 – Aug 2023\nEntered 300 forms a week into the records system\n")
        r = real(text)
        ents = [e for e in r["experience"]["entries"] if e["section"] == "experience"]
        self.assertEqual(len(ents), 2)
        self.assertEqual([e["bullet_count"] for e in ents], [1, 1])

    def test_glyph_resume_is_unchanged(self):
        r = real(resume(["Cleaned survey data for 3 studies", "Built 2 dashboards in Excel",
                         "Wrote weekly summaries for the lab lead", "Trained 4 new volunteers"]))
        self.assertEqual(r["bullets"]["count"], 4)
        self.assertNotIn("too little", r["scores"]["content_signals"]["explanation"])


class RatingTests(unittest.TestCase):
    """A3: rating dots are flagged and stripped from the skill."""

    def test_strip_rating(self):
        self.assertEqual(strip_rating("Python • • • • ○"), ("Python", True))
        self.assertEqual(strip_rating("Excel ▮▮▮▯▯ | SQL ●●○○○"), ("Excel | SQL", True))
        self.assertEqual(strip_rating("Example University • Sep 2025 – Present")[1], False)
        self.assertEqual(strip_rating("• • • ")[1], False)

    def test_parse_024_and_clean_wording(self):
        r = real(resume(skills="Python • • • • ○\nExcel • • • ○ ○"), posting(["Python", "Excel", "SQL", "Tableau", "R"]))
        it = S.issue(r, "PARSE-024")
        self.assertEqual(it["severity"], "low")
        self.assertIn("Python • • • • ○", it["evidence"])
        self.assertNotIn("PARSE-010", S.issue_ids(r))
        self.assertEqual(S.term(r, "Python")["resume_wording"], "Python")


class OrGroupTests(unittest.TestCase):
    """A6, B 2.4, 2.5: alternatives in one requirement are one term satisfied by any member."""

    def test_python_or_r(self):
        r = real(resume(["Cleaned survey data in R for a study with 200 participants"]),
                 posting(["Experience with Python or R for data analysis", "SQL", "Excel", "Tableau"]))
        t = S.term(r, "Python or R")
        self.assertIsNotNone(t)
        self.assertEqual(t["group"], "any_of")
        self.assertEqual(t["alternatives"], ["Python", "R"])
        self.assertTrue(t["found"])
        self.assertEqual(t["matched_alternative"], "R")
        self.assertIsNone(S.term(r, "Python"))       # not counted a second time
        self.assertEqual(sum(1 for x in r["keywords"]["required"] if "Python" in x["term"]), 1)

    def test_comma_list_ending_in_or_and_slash(self):
        r = real(resume(skills="Power BI"), posting(["Tableau, Looker or Power BI", "Excel/Google Sheets", "SQL"]))
        self.assertEqual(S.term(r, "Tableau, Looker or Power BI")["alternatives"], ["Tableau", "Looker", "Power BI"])
        self.assertTrue(S.term(r, "Tableau, Looker or Power BI")["found"])
        self.assertEqual(S.term(r, "Excel/Google Sheets")["group"], "any_of")

    def test_and_list_stays_separate(self):
        r = real(resume(), posting(["Experience with SQL, Python, and Tableau", "Excel"]))
        for name in ("SQL", "Python", "Tableau"):
            self.assertIsNotNone(S.term(r, name), name)
            self.assertIsNone(S.term(r, name)["group"], name)

    def test_bls_cpr_satisfied_by_cpr(self):
        jd = posting(["High school diploma or GED", "Current BLS/CPR certification", "Communication", "Teamwork"],
                     title="Patient Care Technician")
        r = real(resume(skills="Microsoft Word, CPR certified"), jd)
        t = [x for x in r["keywords"]["required"] if x["term"].startswith("BLS/CPR")][0]
        self.assertTrue(t["found"])
        self.assertEqual(t["alternatives"][0], "BLS")
        self.assertTrue(t["matched_alternative"].startswith("CPR"))
        hs = S.term(r, "High school diploma or GED")
        self.assertEqual(hs["alternatives"], ["High school diploma", "GED"])
        self.assertFalse(hs["found"])
        req = r["keywords"]["coverage"]
        self.assertEqual(req["required_total"], 4)          # one requirement each, not six terms

    def test_ged_satisfies_the_group(self):
        r = real(resume(education="GED, Example County Adult Learning Center, 2023"),
                 posting(["High school diploma or GED", "Excel", "Communication", "Teamwork", "SQL"]))
        self.assertTrue(S.term(r, "High school diploma or GED")["found"])

    def test_degree_fields_match_education_only(self):
        jd = posting(["Currently pursuing a bachelor's degree in statistics, data science, economics, "
                      "computer science or a related field", "SQL", "Excel", "Tableau"])
        r = real(resume(), jd)
        t = S.term(r, "statistics, data science, economics, computer science")
        self.assertEqual(t["group"], "degree_field")
        self.assertTrue(t["found"])
        self.assertEqual(t["matched_alternative"], "statistics")
        self.assertEqual(t["evidence_level"], "demonstrated")
        self.assertIsNone(S.term(r, "economics"))
        self.assertNotIn(t["term"], r["keywords"]["coverage"]["listed_only"])
        # Economics in a skills list is not a degree in economics
        r2 = real(resume(education="Example State University, B.A. Marketing, Expected May 2027",
                         skills="Economics, Excel"), jd)
        t2 = S.term(r2, "statistics, data science, economics, computer science")
        self.assertFalse(t2["found"])


class AmbiguousLanguageTests(unittest.TestCase):
    """A7: R, C, Go and Swift count with local context; initials never count."""

    JD = posting(["R for statistical work", "SQL", "Excel", "Tableau", "Python"])

    def found(self, line, jd=None, skills=""):
        r = real(resume([line], skills=skills), jd or self.JD)
        t = S.term(r, "R")
        return bool(t and t["found"])

    def test_r_context_patterns(self):
        self.assertTrue(self.found("Cleaned survey data in R for a study with 200 participants"))
        self.assertTrue(self.found("Built charts with R (tidyverse) for the lab"))
        self.assertTrue(self.found("Wrote weekly lab notes", skills="Python, R, SQL"))
        self.assertTrue(self.found("Wrote weekly lab notes", skills="Python\nR"))     # same skills section

    def test_r_initial_is_not_r(self):
        self.assertFalse(self.found("Assisted Dr. R. Smith with data entry for 2 studies"))
        self.assertFalse(self.found("Filed reports for the R. Example Foundation"))

    def test_go_and_swift(self):
        jd = posting(["Go for backend services", "Swift for iOS apps", "SQL", "Excel", "Python"])
        r = real(resume(["Built a REST API in Go for a class project", "Coded a quiz app in Swift"]), jd)
        self.assertTrue(S.term(r, "Go")["found"])
        self.assertTrue(S.term(r, "Swift")["found"])
        r2 = real(resume(["Go to weekly meetings and take notes", "Swift response to customer emails"]), jd)
        self.assertFalse(S.term(r2, "Go")["found"])
        self.assertFalse(S.term(r2, "Swift")["found"])

    def test_c_needs_code_context(self):
        jd = posting(["C programming", "Python", "SQL", "Excel", "MATLAB"])
        self.assertTrue(S.term(real(resume(["Programmed a line-following robot in C"]), jd), "C")["found"])
        self.assertFalse(S.term(real(resume(["Performed in C major at the spring recital"]), jd), "C")["found"])


class HonestyTests(unittest.TestCase):
    """B 2.6, 6.10, and 'SQL queries': issue text quotes the posting's and the resume's own words."""

    def test_term_is_the_posting_words_where_it_is_required(self):
        jd = ("Data Intern\nWhat you'll do\n- Write SQL queries to pull data from the warehouse\n"
              "Requirements\n- Experience with SQL\n- Excel\n- Python\n- Tableau\n" + PAD)
        r = real(resume(), jd)
        t = S.term(r, "SQL")
        self.assertEqual(t["term"], "SQL")
        self.assertEqual(t["importance"], "required")
        self.assertIn("SQL", t["jd_quote"])
        self.assertIsNone(S.term(r, "SQL queries"))

    def test_claude_term_without_occurrence_keeps_its_own_words(self):
        jd = posting(["Current BLS/CPR certification", "Excel", "Communication", "Teamwork", "SQL"])
        terms = [{"term": "CPR", "aliases": ["CPR certified"], "importance": "required",
                  "jd_quote": "Current BLS/CPR certification"}]
        r = real(resume(skills="CPR certified"), jd, terms=terms)
        names = [x["term"] for x in r["keywords"]["required"] + r["keywords"]["preferred"] + r["keywords"]["other"]]
        self.assertNotIn("Cardiopulmonary Resuscitation", names)
        for it in r["issues"]:
            for e in it["evidence"]:
                self.assertNotIn("Cardiopulmonary Resuscitation", e)
        self.assertNotIn("Cardiopulmonary Resuscitation", render_screening_md(r))

    def test_kw003_quotes_both_sides(self):
        r = real(resume(["Ran split testing on 4 email subject lines"]),
                 posting(["A/B testing", "Excel", "SQL", "Tableau", "Python"]))
        ev = S.issue(r, "KW-003")["evidence"]
        self.assertIn('Posting says "A/B testing"; you wrote "split testing".', ev)

    def test_same_words_are_not_a_wording_difference(self):
        r = real(resume(skills="CPR certified, Excel"), posting(["CPR certification", "Excel", "SQL", "Python", "Tableau"]))
        self.assertTrue(S.term(r, "CPR certification")["found"])
        self.assertIsNone(S.issue(r, "KW-003"))

    def test_listed_certification_is_not_only_listed(self):
        jd = posting(["Current BLS/CPR certification", "Excel", "Communication", "Teamwork", "SQL"])
        r = real(resume(skills="CPR certified, Excel"), jd)
        t = [x for x in r["keywords"]["required"] if x["term"].startswith("BLS/CPR")][0]
        self.assertEqual(t["evidence_level"], "demonstrated")
        self.assertNotIn(t["term"], r["keywords"]["coverage"]["listed_only"])
        kw2 = S.issue(r, "KW-002")
        self.assertTrue(kw2 is None or not any("BLS" in e for e in kw2["evidence"]))
        self.assertEqual(S.term(r, "Excel")["evidence_level"], "listed")     # a tool still needs a bullet

    def test_school_name_is_not_a_diploma(self):
        jd = posting(["High school diploma", "Excel", "Communication", "Teamwork", "SQL"])
        r = real(resume(education="Lincoln Example High School, Sioux Falls, SD"), jd)
        self.assertFalse(S.term(r, "High school diploma")["found"])
        r2 = real(resume(education="High school diploma, Lincoln Example High School, 2025"), jd)
        t = S.term(r2, "High school diploma")
        self.assertTrue(t["found"])
        self.assertEqual(t["match_type"], "exact")


class DerivationTests(unittest.TestCase):
    """B 6.8: verbs count for their nouns, conservatively."""

    def test_communicate_counts_for_communication(self):
        r = real(resume(["Communicate with customers at the register every shift"]),
                 posting(["Excellent communication skills", "Excel", "SQL", "Python", "Tableau"]))
        t = S.term(r, "communication")
        self.assertTrue(t["found"])
        self.assertEqual(t["match_type"], "inflection")
        self.assertEqual(t["evidence_level"], "demonstrated")

    def test_collaborated_counts_for_collaboration(self):
        r = real(resume(["Collaborated with 3 researchers on a survey"]),
                 posting(["Collaboration", "Excel", "SQL", "Python", "Tableau"]))
        self.assertTrue(S.term(r, "Collaboration")["found"])

    def test_reworded_phrase_with_a_verb(self):
        jd = posting(["Data analysis", "Project management", "Machine learning", "Excel", "SQL"])
        r = real(resume(["Analyzed reaction-time data for 2 studies", "Managed 3 class projects end to end",
                         "Cleaned the espresso machine while learning the menu"]), jd)
        t = S.term(r, "Data analysis")
        self.assertTrue(t["found"])
        self.assertEqual(t["match_type"], "inflection")
        self.assertEqual(t["resume_wording"], "Analyzed reaction-time data")
        self.assertTrue(S.term(r, "Project management")["found"])
        self.assertFalse(S.term(r, "Machine learning")["found"])        # no derived word: not reworded
        far = real(resume(["Used Python to analyze 8,000 shots from public game data"]), jd)
        self.assertFalse(S.term(far, "Data analysis")["found"])       # words too far apart

    def test_no_false_matches(self):
        r = real(resume(["Answered phones and filed reports"]),
                 posting(["Communication", "Collaboration", "Excel", "SQL", "Python"]))
        self.assertFalse(S.term(r, "Communication")["found"])
        self.assertFalse(S.term(r, "Collaboration")["found"])
        # "Present" in a date range is not a presentation; "documents" (a noun) is not documentation
        from hp.screen.tokens import FormIndex, tokenize
        idx = FormIndex()
        idx.add("presentation", "k1", "canonical")
        idx.add("documentation", "k2", "canonical")
        for text in ("Sep 2025 – Present", "Filed documents for 3 teams", "a present for a friend"):
            self.assertEqual(idx.scan(tokenize(text), longest_only=False, derive=True), [], text)
        self.assertTrue(idx.scan(tokenize("Presented results to 15 managers"), longest_only=False, derive=True))
        # the posting side never derives
        self.assertEqual(idx.scan(tokenize("Presented results"), longest_only=False), [])


class PostingPhraseTests(unittest.TestCase):
    """B 2.7: no broken fragments like "record vital"; whole noun phrases only."""

    def test_vital_signs(self):
        jd = ("Patient Care Technician\nResponsibilities: Take and record vital signs. Assist patients with "
              "bathing and mobility.\nRequirements: High school diploma or GED. Current BLS/CPR certification. "
              "Excellent communication and teamwork.\n" + PAD)
        r = real(resume(), jd)
        names = [t["term"] for g in ("required", "preferred", "other") for t in r["keywords"][g]]
        self.assertIn("vital signs", names)
        self.assertNotIn("record vital", names)

    def test_ngrams_end_on_a_noun(self):
        jd = posting(["Strong customer onboarding experience", "Excel", "SQL"],
                     preferred=["Highly analytical", "Clinic scheduling software"])
        r = S.screen(resume(), jd)
        names = [t["term"].lower() for g in ("required", "preferred", "other") for t in r["keywords"][g]]
        for bad in ("customer onboarding experience", "analytical", "highly analytical"):
            self.assertNotIn(bad, names)


class CoverageFloorTests(unittest.TestCase):
    """B 2.11: a clean file can't lift a resume that misses most required terms above "Needs work"."""

    def test_low_required_coverage_caps_overall(self):
        jd = posting(["SQL", "Tableau", "Power BI", "Python", "Excel"])
        r = real(resume(["Cleaned survey data for 3 studies", "Built 2 charts for the weekly meeting",
                         "Wrote weekly summaries for the lab lead", "Trained 4 new volunteers"], skills="Excel"), jd)
        self.assertEqual(r["keywords"]["coverage"]["required_found"], 1)
        self.assertLessEqual(r["scores"]["overall"]["value"], 60)
        self.assertEqual(r["scores"]["overall"]["band"], "Needs work")
        self.assertIn("fewer than half of the required", r["scores"]["overall"]["explanation"])

    def test_half_or_more_is_not_capped(self):
        jd = posting(["SQL", "Python", "Excel", "Tableau"])
        r = real(resume(["Used SQL and Python to clean 3,000 records", "Built 2 Tableau dashboards for 3 teams",
                         "Wrote weekly summaries for the lab lead", "Trained 4 new volunteers"], skills="Excel"), jd)
        self.assertNotIn("fewer than half", r["scores"]["overall"]["explanation"])


class KnockoutTests(unittest.TestCase):
    """B 2.8, 2.9: knockout quotes hold the matched words; "bilingual" is met by two languages."""

    JD = ("Patient Care Technician\nRequirements: High school diploma or GED. Current BLS/CPR certification. "
          "Ability to lift 50 lbs and stand for long periods. Excellent communication and teamwork. Able to work "
          "night shifts and every other weekend.\nPreferred: CNA certification. Previous experience in healthcare "
          "or customer service. Bilingual.\n" + PAD)

    def ko(self, r, typ):
        return [k for k in r["knockout_signals"] if k["type"] == typ][0]

    def test_quote_is_the_sentence_with_the_match(self):
        r = real(resume(skills="bilingual (English and Mandarin)"), self.JD)
        self.assertEqual(self.ko(r, "schedule")["jd_quote"], "Able to work night shifts and every other weekend.")
        self.assertEqual(self.ko(r, "physical")["jd_quote"], "Ability to lift 50 lbs and stand for long periods.")
        for k in make_brief(r)["knockouts"]:
            self.assertLessEqual(len(k["jd_quote"]), 120)
        long_line = "Requirements: " + "pad words here " * 12 + "must be able to work weekends " + "and more " * 12
        r2 = real(resume(), long_line + PAD)
        q = self.ko(r2, "schedule")["jd_quote"]
        self.assertIn("weekends", q)
        self.assertLessEqual(len(q), 120)
        self.assertIn(q, long_line)

    def test_bilingual(self):
        r = real(resume(skills="bilingual (English and Mandarin)"), self.JD)
        k = self.ko(r, "language")
        self.assertEqual(k["status"], "appears_met")
        self.assertIn("Mandarin", k["resume_evidence"])
        r2 = real(resume(skills="Languages: English, Spanish (conversational)"), self.JD)
        self.assertEqual(self.ko(r2, "language")["status"], "appears_met")
        r3 = real(resume(skills="Excel, Word"), self.JD)
        self.assertEqual(self.ko(r3, "language")["status"], "unclear")

    def test_named_language_still_required(self):
        jd = posting(["Bilingual in English and Spanish", "Excel", "SQL"])
        r = real(resume(skills="Languages: English (native), French (conversational)"), jd)
        self.assertEqual(self.ko(r, "language")["status"], "unclear")
        r2 = real(resume(skills="Languages: English (native), Spanish (conversational)"), jd)
        self.assertEqual(self.ko(r2, "language")["status"], "appears_met")


if __name__ == "__main__":
    unittest.main()
