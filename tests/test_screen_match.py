"""hp.screen matching: normalization, credit table, evidence levels, snippets (ATS spec 12)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_screen_support as S  # noqa: E402

from hp.screen.tokens import FormIndex, stem, suffix_compatible, tokenize  # noqa: E402

PAD = "\n" + "This sentence pads the posting so it is long enough to score. " * 6
HEAD = "Jamie Sample\nDenver, CO | jamie.sample@example.com | (555) 010-0177\n"


def resume(experience_bullets, skills="", summary=""):
    text = HEAD
    if summary:
        text += "SUMMARY\n%s\n" % summary
    text += "EXPERIENCE\nAnalyst Intern | Example Co | Jan 2025 – May 2025\n"
    text += "\n".join("• " + b for b in experience_bullets) + "\n"
    text += "EDUCATION\nExample State University, B.S. Economics, May 2026\n"
    if skills:
        text += "SKILLS\n%s\n" % skills
    return text


def jd(required, preferred=()):
    text = "Analyst Intern\nRequirements\n" + "\n".join("- " + r for r in required) + "\n"
    if preferred:
        text += "Preferred Qualifications\n" + "\n".join("- " + p for p in preferred) + "\n"
    return text + PAD


class AliasAcronymTests(unittest.TestCase):
    def test_seo_matches_search_engine_optimization(self):
        r = S.screen(resume(["Wrote 12 blog posts using search engine optimization best practices"]),
                     jd(["SEO", "Excel", "SQL", "Tableau", "Python"]))
        t = S.term(r, "SEO")
        self.assertTrue(t["found"])
        self.assertEqual(t["match_type"], "acronym")
        self.assertEqual(t["credit"], 1.0)
        self.assertEqual(t["resume_wording"].lower(), "search engine optimization")
        self.assertIn("KW-003", S.issue_ids(r))

    def test_search_engine_optimization_matches_seo(self):
        r = S.screen(resume(["Improved SEO for 20 product pages"]),
                     jd(["search engine optimization", "Excel", "SQL", "Tableau", "Python"]))
        t = S.term(r, "search engine optimization")
        self.assertTrue(t["found"])
        self.assertEqual(t["match_type"], "acronym")

    def test_same_wording_is_exact_and_no_kw003(self):
        r = S.screen(resume(["Improved SEO for 20 product pages"]), jd(["SEO", "Excel", "SQL", "Tableau", "Python"]))
        self.assertEqual(S.term(r, "SEO")["match_type"], "exact")
        kw3 = S.issue(r, "KW-003")
        self.assertTrue(kw3 is None or not any("SEO" in e for e in kw3["evidence"]))

    def test_alias(self):
        r = S.screen(resume(["Ran split testing on 4 email subject lines"]),
                     jd(["A/B testing", "Excel", "SQL", "Tableau", "Python"]))
        t = S.term(r, "A/B testing")
        self.assertTrue(t["found"])
        self.assertEqual(t["match_type"], "alias")

    def test_ab_testing_variants_are_exact(self):
        for wording in ("AB testing", "A/B Testing", "a/b testing"):
            r = S.screen(resume(["Ran %s on 4 email subject lines" % wording]),
                         jd(["A/B testing", "Excel", "SQL", "Tableau", "Python"]))
            t = S.term(r, "A/B testing")
            self.assertTrue(t["found"], wording)
            self.assertEqual(t["match_type"], "exact", wording)


class ImpliedTests(unittest.TestCase):
    def test_postgresql_implies_sql(self):
        r = S.screen(resume(["Wrote PostgreSQL queries to join 3 sales tables"]),
                     jd(["SQL", "Excel", "Tableau", "Python", "Power BI"]))
        t = S.term(r, "SQL")
        self.assertTrue(t["found"])
        self.assertEqual(t["match_type"], "implied")
        self.assertEqual(t["credit"], 0.8)
        self.assertEqual(t["resume_wording"], "PostgreSQL")
        self.assertEqual(t["evidence_level"], "demonstrated")

    def test_direct_match_beats_implied(self):
        r = S.screen(resume(["Wrote SQL and PostgreSQL queries for 3 reports"]),
                     jd(["SQL", "Excel", "Tableau", "Python", "Power BI"]))
        self.assertEqual(S.term(r, "SQL")["match_type"], "exact")


class AmbiguousTests(unittest.TestCase):
    def test_r_without_context_is_ambiguous(self):
        r = S.screen(resume(["Built 3 charts for the weekly sales meeting"], skills="Tools: R, Excel"),
                     jd(["R for statistical analysis", "Python", "Excel", "SQL", "Tableau", "Power BI"]))
        t = S.term(r, "R")
        self.assertIsNotNone(t)
        self.assertFalse(t["found"])
        self.assertEqual(t["match_type"], "ambiguous")
        self.assertEqual(t["credit"], 0.5)

    def test_r_with_context_is_found(self):
        r = S.screen(resume(["Ran regression models in R on 2 years of data"]),
                     jd(["R for statistical analysis", "Python", "Excel", "SQL", "Tableau", "Power BI"]))
        t = S.term(r, "R")
        self.assertTrue(t["found"])
        self.assertEqual(t["match_type"], "exact")

    def test_r_in_posting_without_context_is_not_a_term(self):
        r = S.screen(resume(["Built 3 charts"]),
                     jd(["Excel, SQL and R", "Tableau", "Canva", "Power BI", "Word documents"]))
        self.assertIsNone(S.term(r, "R"))

    def test_letter_spaced_name_does_not_count_as_r(self):
        text = "J O R D A N   S A M P L E\n" + resume(["Built 3 charts"])[len("Jamie Sample\n"):]
        r = S.screen(text, jd(["R for statistical analysis", "Python", "Excel", "SQL", "Tableau", "Power BI"]))
        self.assertEqual(S.term(r, "R")["match_type"], "none")

    def test_case_sensitive_go(self):
        r = S.screen(resume(["Go to weekly meetings and take notes for 5 managers"]),
                     jd(["Go (Golang) for backend services", "SQL", "Excel", "Tableau", "Python"]))
        t = S.term(r, "Go")
        self.assertIsNotNone(t)
        self.assertFalse(t["found"])


class VariantTests(unittest.TestCase):
    def test_front_end_variants(self):
        for wording in ("frontend development", "front end development", "Front-End Development",
                        "front-end web development"):
            r = S.screen(resume(["Did %s for 3 student club websites" % wording]),
                         jd(["front-end development", "SQL", "Excel", "Tableau", "Python"]))
            t = S.term(r, "front-end development")
            self.assertTrue(t["found"], wording)
            self.assertIn(t["match_type"], ("exact", "alias"), wording)

    def test_node_js_variants(self):
        for wording in ("Node.js", "NodeJS", "node.js"):
            r = S.screen(resume(["Built an API in %s for 200 users" % wording]),
                         jd(["Node.js", "SQL", "Excel", "Tableau", "Python"]))
            self.assertTrue(S.term(r, "Node.js")["found"], wording)

    def test_plural_inflection_end_to_end(self):
        terms = [{"term": "financial statement", "importance": "required",
                  "jd_quote": "Read a financial statement quickly"}]
        r = S.screen(resume(["Reviewed financial statements for 6 student groups"]),
                     jd(["Read a financial statement quickly", "SQL", "Excel", "Tableau", "Python"]), terms=terms)
        t = S.term(r, "financial statement")
        self.assertTrue(t["found"])
        self.assertEqual(t["match_type"], "inflection")
        self.assertEqual(t["credit"], 0.9)

    def test_stemmer_rules(self):
        self.assertEqual(stem("dashboards"), ("dashboard", "plural"))
        self.assertEqual(stem("analytics")[0], stem("analytic")[0])
        self.assertEqual(stem("processes")[0], stem("process")[0])
        self.assertEqual(stem("strategies")[0], "strategy")
        self.assertEqual(stem("planned")[0], stem("planning")[0])
        self.assertEqual(stem("SQL".casefold()), ("sql", "none"))
        self.assertFalse(suffix_compatible("verb", "plural"))
        self.assertTrue(suffix_compatible("plural", "none"))

    def test_gerund_fields_do_not_match_plain_nouns(self):
        idx = FormIndex()
        idx.add("accounting", "acc", "canonical")
        idx.add("marketing", "mkt", "canonical")
        idx.add("campaign", "cmp", "canonical")
        hits = {h[2]: h[5] for h in idx.scan(tokenize("Managed 30 accounts in 4 markets"), longest_only=False)}
        self.assertNotIn("acc", hits)
        self.assertNotIn("mkt", hits)
        hits = {h[2]: h[5] for h in idx.scan(tokenize("Ran 3 campaigns"), longest_only=False)}
        self.assertEqual(hits.get("cmp"), "inflection")

    def test_comma_breaks_phrases(self):
        idx = FormIndex()
        idx.add("front-end", "fe", "canonical")
        self.assertFalse(idx.scan(tokenize("front, end"), longest_only=False))
        self.assertTrue(idx.scan(tokenize("front end"), longest_only=False))
        self.assertTrue(idx.scan(tokenize("frontend"), longest_only=False))

    def test_partial_match(self):
        terms = [{"term": "customer data platform", "importance": "required",
                  "jd_quote": "Experience with a customer data platform"}]
        r = S.screen(resume(["Cleaned customer records in the CRM platform for 2 teams"]),
                     jd(["Experience with a customer data platform", "SQL", "Excel", "Tableau", "Python"]),
                     terms=terms)
        t = S.term(r, "customer data platform")
        self.assertFalse(t["found"])
        self.assertEqual(t["match_type"], "partial")
        self.assertEqual(t["credit"], 0.5)


class EvidenceTests(unittest.TestCase):
    def test_evidence_levels(self):
        r = S.screen(resume(["Built 4 Tableau dashboards for 12 stores"], skills="Tools: Excel, SQL",
                            summary="Analyst who enjoys Python."),
                     jd(["Tableau", "Excel", "SQL", "Python", "Power BI"]))
        self.assertEqual(S.term(r, "Tableau")["evidence_level"], "demonstrated")
        self.assertEqual(S.term(r, "Excel")["evidence_level"], "listed")
        self.assertEqual(S.term(r, "Python")["evidence_level"], "claimed")
        self.assertEqual(S.term(r, "Power BI")["evidence_level"], "none")
        self.assertIn("Excel", r["keywords"]["coverage"]["listed_only"])
        self.assertIn("KW-002", S.issue_ids(r))

    def test_best_location_wins(self):
        r = S.screen(resume(["Wrote SQL queries for 3 weekly reports"], skills="Tools: SQL"),
                     jd(["SQL", "Excel", "Tableau", "Python", "Power BI"]))
        t = S.term(r, "SQL")
        self.assertEqual(t["evidence_level"], "demonstrated")
        self.assertEqual(t["resume_locations"][0], "experience")
        self.assertIn("skills", t["resume_locations"])

    def test_snippets_are_short_and_at_most_two(self):
        long_bullet = "Used SQL " + "to build a very long set of weekly reports for the team " * 6
        r = S.screen(resume([long_bullet, "Wrote SQL checks", "More SQL work"], skills="Tools: SQL"),
                     jd(["SQL", "Excel", "Tableau", "Python", "Power BI"]))
        t = S.term(r, "SQL")
        self.assertLessEqual(len(t["snippets"]), 2)
        for s in t["snippets"]:
            self.assertLessEqual(len(s), 160)
            self.assertIn("SQL", s)

    def test_coverage_counts_and_required_line(self):
        from hp.screen import required_line
        r = S.screen(resume(["Built Tableau dashboards for 12 stores"], skills="Tools: Excel"),
                     jd(["Tableau", "Excel", "SQL"], ["Python", "Power BI"]))
        cov = r["keywords"]["coverage"]
        self.assertEqual((cov["required_found"], cov["required_total"], cov["required_listed_only"]), (2, 3, 1))
        self.assertEqual(required_line(r), "Required terms: 2 of 3 found (1 only in your skills list).")
        self.assertIn("Required terms: 2 of 3 found (1 only in your skills list).",
                      r["scores"]["keyword_match"]["explanation"])


if __name__ == "__main__":
    unittest.main()
