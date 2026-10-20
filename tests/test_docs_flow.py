"""Regression tests for the skill instructions, from the live end-to-end tests (test A: Claude Code, parallel;
test B: claude.ai simulation, Free plan, lite). Each test names the finding it guards.

The skill's behavior lives in prose, so these tests pin the exact rules a model must read: what reviewers read,
the one question-batch rule and closing line, stage inference, the headline and privacy rules, the delivery
template, and a complete resume.json example that must stay valid, pass the truth check and render fully.
All data here is fictional.
"""
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SKILL = os.path.join(ROOT, "plugins", "hiring-panel", "skills", "hiring-panel")
REFS = os.path.join(SKILL, "references")
sys.path.insert(0, os.path.join(SKILL, "scripts"))

CLOSING_LINE = ("Answer any you can. A range or \"not sure\" is fine, or reply skip and I'll rebuild it with "
                "what's already there.")


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read().replace("\r\n", "\n")


def flat(text):
    """Collapse whitespace and blockquote markers so wrapped Markdown phrases match."""
    return " ".join(re.sub(r"(?m)^[ \t]*>[ \t]?", "", text).split())


def skill():
    return read(os.path.join(SKILL, "SKILL.md"))


def ref(name):
    return read(os.path.join(REFS, name))


def md_section(text, heading_start):
    """Body of the Markdown heading that starts with `heading_start`, up to the next heading of that level."""
    level = len(heading_start) - len(heading_start.lstrip("#"))
    m = re.search(r"^%s.*?$(.*?)(?=^#{1,%d} |\Z)" % (re.escape(heading_start), level), text, re.M | re.S)
    if not m:
        raise AssertionError("no heading starting with %r" % heading_start)
    return m.group(1)


# A fictional source resume and answers that the rewrite-rules example (section 14) cites.
EXAMPLE_LINES = [
    "Avery Quinn", "Dayton, OH | (555) 010-0199 | avery.quinn@example.com", "EDUCATION",
    "Riverbend College, Dayton, OH", "B.A. in Communication | Expected May 2027", "EXPERIENCE",
    "Maple Street Cafe, Dayton, OH", "Barista | June 2024 – Present",
    "• Helped train new baristas on the espresso machine", "• Made instagram posts for the cafe 3x a week",
    "PROJECTS", "Campus Food Survey, Research Methods class project | Spring 2025",
    "• Designed a 10 question survey and collected 85 responses", "CERTIFICATIONS",
    "ServSafe Food Handler, National Restaurant Association | 2024", "SKILLS", "Canva, Google Sheets, Instagram",
    "Excel ●●○○○", "INTERESTS", "Hiking, baking",
]
EXAMPLE_LEDGER = {
    "schema_version": "1.0",
    "resume_lines": [{"id": "R%d" % (i + 1), "section": "other", "text": t} for i, t in enumerate(EXAMPLE_LINES)],
    "jd_items": [{"id": "J1", "kind": "must", "block": 0, "text": "Experience with Excel and Google Analytics"}],
    "target": {"role_title": "Marketing Assistant", "role_level": "entry", "company": "Harbor Books",
               "locale": "en-US", "general_review": False},
}
EXAMPLE_ANSWERS = {"schema_version": "1.0", "mode": "interactive", "answers": [
    {"id": "Q1", "kind": "keywords", "question": "For each, reply yes, some or no, and where: Excel, Google Analytics.",
     "answer": "Excel some, made budget sheets in my Intro to Business class. Google Analytics no",
     "status": "answered",
     "items": [{"term": "Excel", "answer": "some", "detail": "made budget sheets in my Intro to Business class"},
               {"term": "Google Analytics", "answer": "no", "detail": ""}]},
    {"id": "Q2", "kind": "number",
     "question": "Roughly how many followers did the cafe account gain since you started posting?",
     "answer": "not sure", "status": "declined", "items": None}]}


class ReviewerInputsTest(unittest.TestCase):
    """Finding A4 (and 3.6): reviewers read the ledger, never resume.md or jd.md; lite reads card + ledger."""

    def test_parallel_template_reads_the_ledger_only(self):
        for text in (skill(), ref("panel-parallel.md")):
            block = re.search(r"^```\n(You are one reviewer.*?)^```", text, re.M | re.S).group(1)
            self.assertIn("4. Your inputs: <RUN>/work/inputs/ledger.json", block)
            self.assertNotIn("resume.md", block)
            self.assertNotIn("jd.md", block)
        # The filled-in example follows the template.
        example = ref("panel-parallel.md").split("Filled-in example", 1)[1].split("```", 2)[1]
        self.assertIn("/work/inputs/ledger.json", example)
        self.assertNotIn("resume.md", example)
        self.assertNotIn("jd.md", example)

    def test_screening_reviewer_also_reads_brief_and_ats_view(self):
        for text in (skill(), ref("panel-parallel.md"), ref("panel-single.md")):
            self.assertIn("<RUN>/work/screening/before/brief.json", text)
            self.assertIn("<RUN>/work/inputs/ats_view.txt", text)

    def test_sequential_protocol_reads_rules_persona_format_and_ledger(self):
        seq = flat(md_section(ref("panel-single.md"), "## 3. Sequential protocol"))
        self.assertIn("Re-read `_shared-rules.md`, that reviewer's persona file and `_output-format.md`", seq)
        self.assertIn("Re-read `<RUN>/work/inputs/ledger.json` from disk", seq)
        self.assertNotIn("resume.md", seq)
        self.assertNotIn("jd.md", seq)

    def test_lite_protocol_reads_card_and_ledger_only(self):
        lite = flat(md_section(ref("panel-single.md"), "## 4. Lite protocol"))
        self.assertIn("Read only `_lite-cards.md` and `<RUN>/work/inputs/ledger.json`", lite)
        self.assertIn("Don't read `_shared-rules.md`, `_output-format.md` or the full persona files", lite)
        self.assertNotIn("resume.md", lite)
        self.assertNotIn("jd.md", lite)

    def test_manual_mode_uses_its_ledger_file(self):
        manual = flat(ref("no-python.md"))
        self.assertIn("every reviewer reads `ledger.md` where that file says `ledger.json`", manual)


class ReviewerOrderTest(unittest.TestCase):
    """Finding 3.1: one order everywhere; the sequential order only in panel-single.md, labeled as the run order."""

    def run_order(self):
        rows = re.findall(r"^\| (\d) \| ([a-z_]+) \| ([^|]+) \|", ref("panel-single.md"), re.M)
        return {name.strip(): int(n) for n, _rid, name in rows}

    def test_progress_examples_match_the_mode_that_prints_them(self):
        order = self.run_order()
        self.assertEqual(len(order), 7)
        # Sequential and lite print one line per reviewer, numbered by run order.
        for rel, text in (("SKILL.md", skill()), ("panel-single.md", ref("panel-single.md"))):
            for n, name in re.findall(r"Reviewer (\d) of 7\s+\(([^)]+)\)", text):
                self.assertEqual(int(n), order[name], "%s: 'Reviewer %s of 7 (%s)'" % (rel, n, name))
        # Parallel prints one line for the whole panel.
        par = flat(ref("panel-parallel.md"))
        self.assertIn("print ONE progress line, not seven", par)
        self.assertNotRegex(par, r"Reviewer \d of 7")

    def test_report_order_is_named_as_such(self):
        self.assertIn("This is the report order", flat(skill()))
        self.assertIn("## 2. Run order (this mode only)", ref("panel-single.md"))


class QuestionBatchTest(unittest.TestCase):
    """Findings 5.1, 5.2, 5.3 and A15: one batch rule, one closing line, one fact per question."""

    def test_one_closing_line_everywhere(self):
        for rel, text in (("SKILL.md", skill()), ("questions.md", ref("questions.md"))):
            self.assertIn(CLOSING_LINE, flat(text), rel)
        # Every line in questions.md that offers "skip" is the canonical closing line (or points to it).
        for line in ref("questions.md").split("\n"):
            if "reply skip" in line or "reply **skip**" in line:
                self.assertIn(CLOSING_LINE, flat(line), line)
        for old in ("skip any you like", "I'll build it with what we have", "Or reply skip.",
                    "reply **skip** and I'll rewrite"):
            for rel, text in (("SKILL.md", skill()), ("questions.md", ref("questions.md"))):
                self.assertNotIn(old, flat(text), rel)

    def test_batch_size_rule_agrees_everywhere(self):
        s, q, e = flat(skill()), flat(ref("questions.md")), flat(ref("edge-cases.md"))
        self.assertIn("**Normal batch, at most 7.**", s)
        self.assertIn("the builder interview, at most 8.** The yes/some/no list counts as one of the 8", s)
        self.assertIn("the yes/some/no keyword list counts as one of the 8", q)
        self.assertIn("the yes/some/no keyword list counts as one of them", e)
        # A15: a resume flagged thin by mistake (unrecognized headings) still gets the normal batch.
        self.assertIn("If `flags.thin` is true but the resume clearly has several dated entries, use the normal "
                      "batch instead", s)
        self.assertIn("If `flags.thin` is true but the resume clearly has several dated entries", q)
        self.assertIn("never ask about jobs that are already on the page", e)

    def test_one_fact_per_question(self):
        s, q = flat(skill()), flat(ref("questions.md"))
        self.assertIn("**One fact per question.** No compound questions", s)
        self.assertIn("**One fact per question.**", q)
        builder = md_section(ref("questions.md"), "## 5. Thin resume")
        items = re.findall(r"^\d\. (\".*?)(?=^\d\. |^\n|\Z)", builder, re.M | re.S)
        self.assertEqual(len(items), 8)
        for item in items:
            self.assertEqual(flat(item).count("?"), 1, item)
            self.assertNotRegex(item, r"(?i)where, when,? and", item)
        templates = md_section(ref("questions.md"), "## 2. Phrasing templates")
        for line in re.findall(r"^- [A-Z][a-z]+: \"(.*?)\"$", templates, re.M):
            self.assertLessEqual(line.count("?"), 1, line)
        self.assertNotIn("and is 300% right?", templates)

    def test_summary_shows_at_most_three_weaknesses(self):
        self.assertIn("(at most 3 here; the report has the rest)", flat(skill()))
        self.assertIn("Keep this message short; many students read it on a phone.", flat(skill()))

    def test_questions_read_compact_files(self):
        q = flat(ref("questions.md"))
        self.assertIn("Read the compact files, not synthesis.json", q)
        self.assertIn("`keyword_gaps`", q)

    def test_answers_json_section_has_no_placeholders(self):
        # Finding 6.1: placeholders live in resume.json, never in answers.json (additionalProperties: false).
        section4 = md_section(ref("questions.md"), "## 4. Writing answers.json")
        self.assertNotIn("placeholders.p#.value", section4)
        self.assertIn("Placeholders are not part of answers.json", flat(section4))
        self.assertIn("copy it into `placeholders.p#.value` verbatim", flat(ref("rewrite-rules.md")))

    def test_answers_example_is_valid(self):
        from hp.panel import schema_lite
        schema = json.loads(read(os.path.join(SKILL, "schemas", "answers.schema.json")))
        blocks = re.findall(r"```json\n(.*?)\n```", ref("questions.md"), re.S)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(schema_lite.validate(json.loads(blocks[0]), schema), [])


class IntakeTest(unittest.TestCase):
    """Finding 1.1: infer the stage from the resume and confirm it instead of guessing silently."""

    def test_stage_is_inferred_and_confirmed(self):
        s = flat(skill())
        self.assertIn("**Stage** (`--stage`): infer it from the resume", s)
        self.assertIn("An expected graduation date", s)
        self.assertIn("Name the stage and what you read it from", s)
        self.assertIn("I'm treating you as a student", s)
        self.assertIn("never ask for them up front", s)


class KeywordTermsTest(unittest.TestCase):
    """Findings 2.10 and 2.11: the optional terms step never adds terms to move the score, and says what it did."""

    def test_terms_guidance(self):
        s = flat(skill())
        for needle in ("Include only terms the posting truly names as skills, tools, certifications or "
                       "qualifications", "Never add a term to raise the score",
                       "One requirement is one term", "with the other wording as an alias",
                       "The screening check now also includes <terms.accepted from the output> terms I read from "
                       "the posting."):
            self.assertIn(needle, s)


class PhaseTwoTest(unittest.TestCase):
    """Finding A18: a re-invoked skill must never ask the batch twice."""

    def test_status_answers_step_goes_to_step_six(self):
        s = flat(skill())
        self.assertIn("If the student already replied to the questions (their reply is in the conversation "
                      "above), save it to answers.json and go to Step 6. Never ask the batch a second time.", s)
        self.assertIn("never ask the batch again", flat(ref("questions.md")))
        self.assertIn("Never ask a second batch", flat(ref("troubleshooting.md")))


class RewriteRulesTest(unittest.TestCase):
    """Findings A20, A21, 6.17, 6.19 and 6.11."""

    def setUp(self):
        self.rules = flat(ref("rewrite-rules.md"))

    def test_issue_ids_come_from_report_json(self):
        self.assertIn("`weaknesses` list in `work/report.json` (each has `issue_id`, `title` and `fix`", self.rules)
        self.assertIn("You don't need the much larger `synthesis.json`", self.rules)
        self.assertIn("`meta.addressed` come from the `weaknesses` in `<RUN>/work/report.json`", flat(skill()))

    def test_skill_ratings_are_dropped(self):
        self.assertIn("Dot, bar or star ratings", self.rules)
        self.assertIn("drop the rating", self.rules)
        self.assertIn("Never write a level", self.rules)

    def test_other_peoples_details_stay_out(self):
        for rel, text in (("rewrite-rules.md", self.rules), ("SKILL.md", flat(skill())),
                          ("edge-cases.md", flat(ref("edge-cases.md")))):
            self.assertIn("Family caregiver", text, rel)
        self.assertIn("Never their health, medications, diagnosis, age or name", self.rules)
        self.assertIn("The report never repeats them either", self.rules)

    def test_one_headline_rule(self):
        self.assertIn("Never write the posting's job title into it on your own", self.rules)
        self.assertIn("(KW-004), that is a suggestion for the candidate", self.rules)
        self.assertIn("Never write the posting's job title into the headline yourself; offer it as the student's "
                      "choice", flat(skill()))
        edge = flat(ref("edge-cases.md"))
        self.assertIn("**The screening check suggests a headline with the job title** (KW-004). That's a "
                      "suggestion for the student", edge)
        self.assertIn("the posting's title goes in only if the student asks for it", edge)

    def test_keyword_fixed_status_is_honest(self):
        self.assertIn("Missing-keyword issues: `fixed` only if every term the issue names is now on the resume",
                      self.rules)


class CompleteExampleTest(unittest.TestCase):
    """Finding 6.2: rewrite-rules.md carries one short but complete resume.json example."""

    def setUp(self):
        section = md_section(ref("rewrite-rules.md"), "## 14. A complete resume.json")
        blocks = re.findall(r"```json\n(.*?)\n```", section, re.S)
        self.assertEqual(len(blocks), 1)
        self.example = json.loads(blocks[0])

    def test_valid_against_the_schema(self):
        from hp.panel import schema_lite
        schema = json.loads(read(os.path.join(SKILL, "schemas", "resume.schema.json")))
        self.assertEqual(schema_lite.validate(self.example, schema), [])

    def test_complete(self):
        ex = self.example
        for key in ("schemaVersion", "basics", "sections", "meta", "placeholders"):
            self.assertIn(key, ex)
        self.assertEqual({s["type"] for s in ex["sections"]}, {"education", "experience", "projects", "custom",
                                                                "skills"})
        self.assertTrue(ex["meta"]["addressed"])
        self.assertEqual({a["status"] for a in ex["meta"]["addressed"]}, {"fixed", "needs_you", "gap"})
        self.assertTrue(ex["meta"]["cuts"])
        bullets = [b for s in ex["sections"] for it in s.get("items") or [] for b in it.get("bullets") or []]
        with_placeholder = [b for b in bullets if "{{p1}}" in b["text"]]
        self.assertEqual(len(with_placeholder), 1)
        self.assertIn("textIfUnknown", with_placeholder[0])
        self.assertIn("p1", ex["placeholders"])
        cert = [it for s in ex["sections"] if s["type"] == "custom" for it in s["items"]][0]
        self.assertTrue(cert.get("name") and cert.get("org"))
        # Finding A21: the rating line is cited, and no level word appears in the skills.
        skills = [i for s in ex["sections"] if s["type"] == "skills" for g in s["groups"] for i in g["items"]]
        self.assertFalse([i for i in skills if re.search(r"(?i)advanced|proficient|expert|strong|●", i)])

    def test_passes_the_truth_check(self):
        from hp.rewrite.truth import check_truth
        truth = check_truth(EXAMPLE_LEDGER, EXAMPLE_ANSWERS, self.example)
        self.assertEqual(truth["errors"], [])
        self.assertTrue(truth["passed"])

    def test_renders_every_entry_and_bullet(self):
        # Step 7's skim and finding 6.6: every entry name, organization and bullet must reach the file.
        from hp.render import render_resume
        out = tempfile.mkdtemp(prefix="hp-docs-example-")
        try:
            info = render_resume(self.example, out, formats=("md",))
            md = read(info["files"]["md"])
        finally:
            shutil.rmtree(out, ignore_errors=True)
        for s in self.example["sections"]:
            for it in s.get("items") or []:
                for field in ("school", "org", "role", "name"):
                    if it.get(field):
                        self.assertIn(it[field], md, "%s %r is missing from the rendered resume" % (field, it[field]))
                for b in it.get("bullets") or []:
                    self.assertIn(b.get("textIfUnknown") or b["text"], md)


class DeliveryTest(unittest.TestCase):
    """Findings 6.18 and 6.6: the delivery names real gaps kindly; Step 7 skims the rendered resume."""

    def test_real_gaps_slot(self):
        step8 = flat(md_section(skill(), "## Step 8."))
        self.assertIn("<For each real_gaps item, said kindly:> One honest gap: <title>. <honest_route>", step8)
        self.assertIn("<its status from report.json", step8)

    def test_skim_after_render(self):
        step7 = flat(md_section(skill(), "## Step 7."))
        self.assertIn("**Skim the result once.** After render exits 0", step7)
        self.assertIn("every entry name, organization and bullet in resume.json appears in it", step7)
        self.assertIn("never hand the files over as if they were complete", step7)


class ReadmeExpectationsTest(unittest.TestCase):
    """README: measured numbers, stated as approximate, without invented token counts."""

    def setUp(self):
        self.raw = read(os.path.join(ROOT, "README.md"))
        self.box = flat(md_section(self.raw, "## What to expect"))

    def test_measured_numbers(self):
        for needle in ("about 15 to 20 minutes", "about 4 minutes", "rough numbers from one test run",
                       "substantial amount of your plan", "quick run", "lighter single-chat panel",
                       "at most 7, or 8 for a very short resume"):
            self.assertIn(needle, self.box)
        self.assertNotRegex(self.box, r"(?i)\btokens?\b")
        self.assertNotRegex(self.box, r"\d+\s?[kK]\b")

    def test_owner_placeholder_kept(self):
        self.assertIn("https://github.com/joshualarosa902-dev/hiring-panel/releases/latest/download/hiring-panel.plugin", self.raw)
        self.assertIn("/plugin marketplace add joshualarosa902-dev/hiring-panel", self.raw)


if __name__ == "__main__":
    unittest.main()
