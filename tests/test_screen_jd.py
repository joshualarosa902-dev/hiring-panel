"""hp.screen job-posting parsing: lossless block partition, required/preferred split, clause overrides,
EEO exclusion, inline headings, title and platform guesses, term sources and --terms verification."""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_screen_support as S  # noqa: E402

from hp.screen.jd import guess_platform, parse_jd, split_jd_lines  # noqa: E402
from hp.screen.lexicon import load_lexicon  # noqa: E402

LEX = load_lexicon(S.DATA)
CLEAN = S.fixture("resume_clean.txt")
JD = S.fixture("jd_marketing.txt")


def blocks_of(jd):
    return parse_jd(jd, LEX)["blocks"]


def flatten(blocks):
    return [ln for b in blocks for ln in b["lines"]]


class PartitionTests(unittest.TestCase):
    def assertPartition(self, jd):
        blocks = blocks_of(jd)
        self.assertEqual(flatten(blocks), split_jd_lines(jd))
        for b in blocks:
            self.assertTrue(b["lines"], "empty block")
            self.assertIn(b["kind"], ("required", "preferred", "responsibility", "boilerplate", "unspecified"))
            if b["heading"] is not None:
                self.assertIn(b["heading"].casefold(), b["lines"][0].casefold())

    def test_fixture_posting_is_partitioned_losslessly(self):
        self.assertPartition(JD)

    def test_messy_formats_are_partitioned_losslessly(self):
        cases = [
            "",
            "   \n\n\t\n",
            "One line only",
            "## About the role\r\nYou will build things.\r\n\r\n**Requirements:**\r\n* SQL\r\n* Excel\r\n",
            "REQUIREMENTS\n  - SQL  \n\n\nNICE TO HAVE\n- Tableau\nEqual Opportunity Employer: we hire without regard to race.\nMore text",
            "Requirements: SQL, Excel and Tableau\nPreferred: Python\nWe are an equal opportunity employer.\n",
            " odd separator line\nRequirements\n  SQL ",
            "Who you are\nYou have 2+ years of experience with SQL\nWhat you'll do\nBuild dashboards",
        ]
        for jd in cases:
            with self.subTest(jd=jd[:30]):
                self.assertPartition(jd)

    def test_random_text_is_partitioned_losslessly(self):
        rnd = random.Random(7)
        words = ["Requirements", "Preferred", "SQL", "- Excel", "Benefits", "is a plus", "must", "EEO",
                 "About us", "###", "**Bold**", ":", "What you'll do", "\t", "", "equal opportunity"]
        for _ in range(60):
            jd = "\n".join(" ".join(rnd.choice(words) for _ in range(rnd.randint(0, 5)))
                           for _ in range(rnd.randint(0, 25)))
            self.assertPartition(jd)

    def test_headings_start_blocks_and_kinds(self):
        kinds = [(b["kind"], b["heading"]) for b in blocks_of(JD)]
        self.assertEqual(kinds[0], ("unspecified", None))
        self.assertIn(("boilerplate", "About Us"), kinds)
        self.assertIn(("responsibility", "What You'll Do"), kinds)
        self.assertIn(("required", "Requirements"), kinds)
        self.assertIn(("preferred", "Preferred Qualifications"), kinds)
        self.assertIn(("boilerplate", "Benefits"), kinds)

    def test_plain_requirement_sentence_is_not_a_heading(self):
        b = blocks_of("Requirements\nYou have experience with SQL\nWho you are\nCurious")
        self.assertEqual([x["kind"] for x in b], ["required", "required"])
        self.assertEqual(b[0]["lines"], ["Requirements", "You have experience with SQL"])

    def test_inline_label_heading(self):
        b = blocks_of("Marketing Intern\nRequirements: SQL, Excel and Tableau\nBenefits: free snacks")
        self.assertEqual([(x["kind"], x["heading"]) for x in b],
                         [("unspecified", None), ("required", "Requirements"), ("boilerplate", "Benefits")])

    def test_markdown_and_caps_headings(self):
        b = blocks_of("# Data Intern\n## What You'll Do\n- Clean data\n**Nice to have**\n- Python\nQUALIFICATIONS\n- SQL")
        self.assertEqual([x["kind"] for x in b], ["unspecified", "responsibility", "preferred", "required"])


class ClassificationTests(unittest.TestCase):
    def test_required_preferred_split(self):
        r = S.screen(CLEAN, JD)
        self.assertEqual(S.term(r, "SQL")["importance"], "required")
        self.assertEqual(S.term(r, "pivot tables")["importance"], "required")
        self.assertEqual(S.term(r, "Python or R")["importance"], "preferred")   # one requirement, two choices
        self.assertEqual(S.term(r, "Python or R")["alternatives"], ["Python", "R"])
        self.assertEqual(S.term(r, "HubSpot or Salesforce")["importance"], "preferred")
        self.assertEqual(S.term(r, "Tableau")["importance"], "responsibility")

    def test_preferred_clause_inside_requirements_becomes_its_own_block(self):
        b = blocks_of(JD)
        line = "- Familiarity with Google Analytics is a plus"
        owner = [x for x in b if line in x["lines"]][0]
        self.assertEqual(owner["kind"], "preferred")
        self.assertEqual(S.term(S.screen(CLEAN, JD), "Google Analytics")["importance"], "preferred")

    def test_clause_overrides(self):
        jd = ("Data Intern\nWhat you'll do\n- Must be comfortable building dashboards in Tableau\n"
              "- Build reports in Excel, and familiarity with Power BI\n"
              "Requirements\n- SQL required; HubSpot preferred\n- Python, ideally\n"
              "This text pads the posting so it is long enough to be scored fairly by the check. " * 3)
        r = S.screen(CLEAN, jd)
        self.assertEqual(S.term(r, "Tableau")["importance"], "required")       # "must" in a duties line
        self.assertEqual(S.term(r, "Excel")["importance"], "responsibility")   # block kind
        self.assertEqual(S.term(r, "Power BI")["importance"], "preferred")     # "familiarity with" clause
        self.assertEqual(S.term(r, "SQL")["importance"], "required")
        self.assertEqual(S.term(r, "HubSpot")["importance"], "preferred")      # preferred wins in its clause
        self.assertEqual(S.term(r, "Python")["importance"], "preferred")

    def test_eeo_and_boilerplate_never_yield_terms_or_knockouts(self):
        jd = ("Analyst Intern\nRequirements\n- SQL and Excel\n- Tableau dashboards\n- Python scripting\n"
              "- Strong communication\nAbout Us\nWe build Salesforce tools for 40 clients.\n"
              "We are an equal opportunity employer and do not discriminate based on age, disability, "
              "or veteran status. Python lovers welcome.\n" + "Padding sentence for length. " * 8)
        r = S.screen(CLEAN, jd)
        blocks = r["inputs"]["job_description"]["blocks"]
        eeo = [b for b in blocks if any("equal opportunity" in ln for ln in b["lines"])][0]
        self.assertEqual(eeo["kind"], "boilerplate")
        self.assertIsNone(S.term(r, "Salesforce"))
        py = S.term(r, "Python")
        self.assertEqual(py["jd_frequency"], 1)
        self.assertNotIn("age", [k["type"] for k in r["knockout_signals"]])

    def test_eeo_line_inside_requirements_is_split_out(self):
        b = blocks_of("Requirements\n- SQL\n- We are an Equal Opportunity Employer\n- Excel")
        self.assertEqual([x["kind"] for x in b], ["required", "boilerplate", "required"])


class TitleAndPlatformTests(unittest.TestCase):
    def test_title_guess(self):
        r = S.screen(CLEAN, JD)
        self.assertEqual(r["inputs"]["job_description"]["title_guess"], "Marketing Analytics Intern")

    def test_title_override(self):
        r = S.screen(CLEAN, JD, jd_title="Growth Marketing Intern")
        self.assertEqual(r["inputs"]["job_description"]["title_guess"], "Growth Marketing Intern")

    def test_platform_guess(self):
        cases = {"https://acme.wd5.myworkdayjobs.com/en-US/careers/job/123": "workday",
                 "https://boards.greenhouse.io/acme/jobs/1": "greenhouse",
                 "https://jobs.lever.co/acme/abc": "lever",
                 "https://careers-acme.icims.com/jobs/1": "icims",
                 "https://acme.taleo.net/careersection/1": "taleo",
                 "https://jobs.ashbyhq.com/acme": "ashby",
                 "https://example.com/jobs/1": "other"}
        for url, want in cases.items():
            self.assertEqual(guess_platform(url, ""), want)
        self.assertEqual(guess_platform(None, "Apply at https://jobs.lever.co/acme/1"), "lever")
        self.assertEqual(guess_platform(None, "no link"), "unknown")

    def test_platform_notes_present_for_workday(self):
        r = S.screen(CLEAN, JD, jd_url="https://acme.wd1.myworkdayjobs.com/x")
        self.assertEqual(r["platform"]["guess"], "workday")
        self.assertTrue(r["platform"]["notes"])
        self.assertIn("wd_parsing_admin", r["platform"]["notes"][0]["source_refs"])


class TermSourceTests(unittest.TestCase):
    def test_lexicon_terms_ordered_by_first_appearance(self):
        r = S.screen(CLEAN, JD)
        terms = S.all_terms(r)
        self.assertTrue(all(t["source"] in ("lexicon", "acronym_definition", "tech_token", "ngram", "llm_verified")
                            for t in terms))
        names = [t["canonical"] for t in r["keywords"]["required"]]
        self.assertLess(names.index("SQL"), names.index("pivot tables"))

    def test_acronym_definition_term(self):
        jd = ("Training Intern\nRequirements\n- Experience with a Learning Management System (LMS)\n"
              "- Upload courses to the LMS every week\n- Excel and SQL\n" + "Padding for length. " * 15)
        resume = CLEAN.replace("• Trained 5 new hires", "• Managed course uploads in the LMS for 300 learners\n"
                                                        "• Trained 5 new hires")
        r = S.screen(resume, jd)
        t = S.term(r, "Learning Management System")
        self.assertIsNotNone(t)
        self.assertEqual(t["source"], "acronym_definition")
        self.assertEqual(t["jd_frequency"], 2)
        self.assertTrue(t["found"])
        self.assertEqual(t["match_type"], "exact")      # the posting itself also says "LMS"
        self.assertEqual(t["evidence_level"], "demonstrated")

    def test_tech_tokens_and_exclusions(self):
        jd = ("Data Intern - Austin, TX\nRequirements\n- Build ETL jobs and GraphQL APIs\n- SQL\n"
              "- Must live in the USA; EEO and PTO details below\n" + "Padding for length. " * 15)
        r = S.screen(CLEAN, jd)
        names = [t["term"] for t in S.all_terms(r)]
        self.assertIn("ETL", names)
        self.assertIn("GraphQL", names)
        for bad in ("USA", "EEO", "PTO", "TX"):
            self.assertNotIn(bad, names)
        self.assertEqual(S.term(r, "ETL")["source"], "tech_token")

    def test_phrase_mining_keeps_specific_phrases_only(self):
        jd = ("Finance Intern\nRequirements\n- Experience with financial reporting\n"
              "- Comfortable with month-end close and financial reporting\n- Excel\n"
              "- Must be authorized to work in the United States\n" + "Padding for length. " * 15)
        r = S.screen(CLEAN, jd)
        mined = [t for t in S.all_terms(r) if t["source"] == "ngram"]
        names = [t["term"].lower() for t in mined]
        self.assertIn("financial reporting", names)
        self.assertNotIn("united states", names)
        for t in mined:
            self.assertEqual(t["confidence"], "low")
            self.assertEqual(t["kind"], "unknown")
        self.assertLessEqual(len(mined), 20)


class TermsVerificationTests(unittest.TestCase):
    def run_terms(self, terms):
        return S.screen(CLEAN, JD, terms=terms)

    def test_fake_quote_is_rejected(self):
        r = self.run_terms([{"term": "Kubernetes", "aliases": [], "importance": "required",
                             "jd_quote": "Experience running Kubernetes clusters in production"}])
        self.assertIsNone(S.term(r, "Kubernetes"))
        self.assertEqual(r["inputs"]["terms"], {"provided": 1, "accepted": 0, "rejected": 1})
        self.assertTrue(any("Kubernetes" in w and "not found" in w for w in r["extraction"]["warnings"]))

    def test_quote_must_contain_term(self):
        r = self.run_terms([{"term": "Snowflake", "importance": "required",
                             "jd_quote": "Analyze customer data with SQL and Excel"}])
        self.assertIsNone(S.term(r, "Snowflake"))
        self.assertTrue(any("does not contain" in w for w in r["extraction"]["warnings"]))

    def test_boilerplate_quote_is_rejected(self):
        r = self.run_terms([{"term": "outdoor goods", "importance": "required",
                             "jd_quote": "Lumen & Pine is a fictional outdoor goods retailer"}])
        self.assertIsNone(S.term(r, "outdoor goods"))
        self.assertTrue(any("benefits or equal-opportunity" in w for w in r["extraction"]["warnings"]))

    def test_verified_term_is_accepted_with_whitespace_normalized_quote(self):
        r = self.run_terms([{"term": "campaign performance", "aliases": ["campaign results"],
                             "importance": "required",
                             "jd_quote": "Build weekly   dashboards in Tableau\nto track campaign performance"}])
        t = S.term(r, "campaign performance")
        self.assertIsNotNone(t)
        self.assertEqual(t["source"], "llm_verified")
        self.assertEqual(t["importance"], "required")
        self.assertEqual(r["inputs"]["terms"]["accepted"], 1)

    def test_terms_matching_a_dictionary_entry_merge(self):
        r = self.run_terms([{"term": "Tableau", "importance": "required",
                             "jd_quote": "Build weekly dashboards in Tableau"}])
        tabs = [t for t in S.all_terms(r) if t["canonical"] == "Tableau"]
        self.assertEqual(len(tabs), 1)
        self.assertEqual(tabs[0]["importance"], "required")

    def test_garbage_terms_never_crash(self):
        for terms in ({"a": 1}, "nope", 5, [None, 3, "x", {"term": 5}, {"term": "SQL"}, {"term": "x" * 500},
                                            {"term": "SQL", "jd_quote": 7}, {"term": "SQL", "jd_quote": "SQL",
                                                                              "importance": "critical"}]):
            r = self.run_terms(terms)
            self.assertIn("terms", r["inputs"])


if __name__ == "__main__":
    unittest.main()
