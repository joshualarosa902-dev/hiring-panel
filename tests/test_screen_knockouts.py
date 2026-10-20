"""hp.screen knockout signals (ATS spec 13): listed, never scored, never inferred."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_screen_support as S  # noqa: E402

CLEAN = S.fixture("resume_clean.txt")
PAD = "\n" + "This sentence pads the posting so it is long enough to score fairly. " * 5


def ko(result, typ):
    for k in result["knockout_signals"]:
        if k["type"] == typ:
            return k
    return None


def run(jd_lines, resume=CLEAN, **kw):
    return S.screen(resume, "Analyst Intern\nRequirements\n" + "\n".join(jd_lines) + PAD, **kw)


class ByDesignTests(unittest.TestCase):
    def test_work_authorization_is_never_inferred(self):
        resume = CLEAN.replace("Languages: English (native)", "US Citizen. Languages: English (native)")
        r = run(["- Must be legally authorized to work in the United States", "- SQL and Excel"], resume)
        k = ko(r, "work_authorization")
        self.assertEqual(k["status"], "not_on_resume_by_design")
        self.assertIsNone(k["resume_evidence"])
        self.assertIn("Answer truthfully", k["advice"])
        self.assertEqual(k["importance"], "required")

    def test_sponsorship_schedule_age_physical_background(self):
        r = run(["- We cannot provide visa sponsorship now or in the future",
                 "- Some weekends and evenings during busy season",
                 "- Must be at least 18 years old", "- Able to lift 25 lbs",
                 "- Offer depends on a background check"])
        for typ in ("sponsorship", "schedule", "age", "physical", "background_check"):
            self.assertEqual(ko(r, typ)["status"], "not_on_resume_by_design", typ)

    def test_false_friends_do_not_fire(self):
        r = run(["- Opt in to our newsletter", "- Help sponsor student events and plan 3 campus fairs",
                 "- SQL and Excel"])
        self.assertIsNone(ko(r, "sponsorship"))

    def test_eeo_lines_are_ignored(self):
        r = run(["- SQL", "We do not discriminate on the basis of age, disability or veteran status."])
        self.assertEqual(r["knockout_signals"], [])

    def test_no_jd_no_knockouts(self):
        self.assertEqual(S.screen(CLEAN, "")["knockout_signals"], [])


class EducationTests(unittest.TestCase):
    def test_gpa_met_unmet_unclear(self):
        self.assertEqual(ko(run(["- Minimum GPA of 3.5"]), "gpa")["status"], "appears_met")
        self.assertEqual(ko(run(["- 3.8 GPA or higher"]), "gpa")["status"], "appears_unmet")
        no_gpa = CLEAN.replace("GPA: 3.7/4.0\n", "")
        self.assertEqual(ko(run(["- Minimum GPA of 3.0"], no_gpa), "gpa")["status"], "unclear")
        other_scale = CLEAN.replace("GPA: 3.7/4.0", "GPA: 4.5/5.0")
        self.assertEqual(ko(run(["- Minimum GPA of 3.0"], other_scale), "gpa")["status"], "unclear")
        k = ko(run(["- Minimum GPA of 3.8"]), "gpa")
        self.assertIn("Never change the number", k["advice"])

    def test_graduation_window(self):
        self.assertEqual(ko(run(["- Graduating between December 2026 and June 2027"]), "graduation_window")["status"],
                         "appears_met")
        self.assertEqual(ko(run(["- Graduating between December 2027 and June 2028"]), "graduation_window")["status"],
                         "appears_unmet")
        self.assertEqual(ko(run(["- Expected graduation by May 2028"]), "graduation_window")["status"], "appears_met")
        self.assertEqual(ko(run(["- Class of 2027"]), "graduation_window")["status"], "appears_met")

    def test_degree(self):
        k = ko(run(["- Currently pursuing a Bachelor's degree in Marketing or Business"]), "degree")
        self.assertEqual(k["status"], "appears_met")
        self.assertIn("Bachelor of Business Administration", k["resume_evidence"])
        self.assertEqual(ko(run(["- Bachelor's degree in Marketing or Business"]), "degree")["status"], "unclear")
        assoc = CLEAN.replace("Bachelor of Business Administration in Marketing, Minor in Statistics, Expected May 2027",
                              "Associate of Arts in Business, May 2024")
        self.assertEqual(ko(run(["- Bachelor's degree required"], assoc), "degree")["status"], "appears_unmet")
        self.assertEqual(ko(run(["- Currently pursuing a Bachelor's degree in Marketing or Business"]), "major")["status"],
                         "appears_met")

    def test_state_abbreviation_is_not_a_degree(self):
        text = CLEAN.replace("University of Texas at Austin, Austin, TX\n"
                             "Bachelor of Business Administration in Marketing, Minor in Statistics, Expected May 2027",
                             "Example College, Boston, MA\nCoursework in marketing, Expected May 2027")
        self.assertEqual(ko(run(["- Master's degree preferred"], text), "degree")["status"], "unclear")


class ExperienceAndSkillTests(unittest.TestCase):
    def test_years_of_experience(self):
        self.assertEqual(ko(run(["- 1+ years of experience in retail or marketing"]), "years_experience")["status"],
                         "appears_met")
        self.assertEqual(ko(run(["- 3-5 years of relevant work experience"]), "years_experience")["status"], "unclear")
        self.assertEqual(ko(run(["- Two years of customer-facing experience"]), "years_experience")["status"],
                         "appears_met")

    def test_language(self):
        self.assertEqual(ko(run(["- Bilingual in English and Spanish"]), "language")["status"], "appears_met")
        self.assertEqual(ko(run(["- Fluent in Mandarin"]), "language")["status"], "unclear")

    def test_certification(self):
        r = run(["- BLS certification required"], CLEAN + "CERTIFICATIONS\nBasic Life Support (BLS), American Example Association\n")
        self.assertEqual(ko(r, "certification")["status"], "appears_met")
        self.assertEqual(ko(run(["- BLS certification required"]), "certification")["status"], "unclear")

    def test_location_and_onsite(self):
        r = run(["- Must live within 30 miles of Austin, TX", "- Hybrid, 3 days per week in office"])
        self.assertEqual(ko(r, "location")["status"], "appears_met")
        self.assertEqual(ko(r, "onsite_hybrid")["status"], "unclear")

    def test_fields_and_order(self):
        r = run(["- Must be authorized to work in the US", "- Minimum GPA of 3.0", "- Travel up to 25%"])
        types = [k["type"] for k in r["knockout_signals"]]
        self.assertEqual(types, ["work_authorization", "gpa", "travel"])
        for k in r["knockout_signals"]:
            self.assertLessEqual(len(k["jd_quote"]), 240)
            self.assertIn(k["jd_quote"], "\n".join(b for blk in r["inputs"]["job_description"]["blocks"]
                                                   for b in blk["lines"]))

    def test_knockouts_never_change_scores(self):
        base = run(["- SQL and Excel"])
        more = run(["- SQL and Excel", "- Must be authorized to work in the US", "- Minimum GPA of 3.9"])
        self.assertEqual(base["scores"]["parse_safety"], more["scores"]["parse_safety"])
        self.assertEqual(base["scores"]["content_signals"], more["scores"]["content_signals"])
        self.assertFalse([i for i in S.issue_ids(more) if i.startswith("KO")])


if __name__ == "__main__":
    unittest.main()
