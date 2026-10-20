"""Tests for SKILL.md and the panel reference files (docs + packaging builder).

They check the things a student can't see but that break a run if they drift: the exact
frontmatter, the 500-line budget, the text Claude Code would substitute or execute, the
subagent templates, and the reviewer tables against ARCHITECTURE.md section 8.
"""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SKILL = os.path.join(ROOT, "plugins", "hiring-panel", "skills", "hiring-panel")
sys.path.insert(0, os.path.join(SKILL, "scripts"))

import hp  # noqa: E402  (after the sys.path insert)

EXPECTED_DESCRIPTION = (
    "Review a resume or CV against a job posting with a simulated 7-reviewer hiring panel, "
    "then rebuild it honestly as .docx, .pdf and .md. Use for resume feedback, ATS checks or rewrites."
)
EXPECTED_ALLOWED_TOOLS = "Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/hp.py *)"
EXPECTED_ARGUMENT_HINT = '"<resume file or pasted text> [job posting, link or role]"'
EXPECTED_AUTHOR = '"Joshua LaRosa (@joshualarosa.ai)"'


def read(path):
    """Read a UTF-8 text file with newlines normalized (Windows checkouts may use CRLF)."""
    with open(path, encoding="utf-8") as fh:
        return fh.read().replace("\r\n", "\n")


def flat(text):
    """Collapse whitespace (and blockquote markers) so phrases that wrap across Markdown lines match."""
    return " ".join(re.sub(r"(?m)^[ \t]*>[ \t]?", "", text).split())


def section(text, number):
    """Return the body of '## <number>.' in ARCHITECTURE.md, up to the next '## ' heading."""
    m = re.search(r"^## %d\. .*?$(.*?)(?=^## |\Z)" % number, text, re.M | re.S)
    if not m:
        raise AssertionError("ARCHITECTURE.md has no section %d" % number)
    return m.group(1)


def frontmatter(text):
    """(fields, body). Top-level keys map to their raw value; a key followed by indented lines (the
    `metadata` block) maps to a dict of those lines' keys and raw values."""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        raise AssertionError("SKILL.md must start with a --- frontmatter block")
    fields, last = {}, None
    for line in m.group(1).split("\n"):
        key, sep, value = line.partition(":")
        if not sep:
            continue
        if line[:1] in (" ", "\t"):
            if last is None or not isinstance(fields[last], dict):
                raise AssertionError("indented frontmatter line outside a block: %r" % line)
            fields[last][key.strip()] = value.strip()
            continue
        last = key.strip()
        fields[last] = value.strip() if value.strip() else {}
    return fields, text[m.end():]


def code_block_starting(text, first_line):
    """Return the fenced code block whose first line is `first_line` (without the fences)."""
    for block in re.findall(r"^```[a-z]*\n(.*?)^```", text, re.M | re.S):
        if block.startswith(first_line):
            return block
    raise AssertionError("no code block starts with %r" % first_line)


def table_rows(text, header_cells):
    """Rows (lists of cell strings) of the Markdown table whose header starts with header_cells."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells[:len(header_cells)] == header_cells:
            rows = []
            for row in lines[i + 2:]:
                if not row.strip().startswith("|"):
                    break
                rows.append([c.strip() for c in row.strip().strip("|").split("|")])
            return rows
    raise AssertionError("no table with header %r" % (header_cells,))


class SkillFrontmatterTest(unittest.TestCase):
    def setUp(self):
        self.text = read(os.path.join(SKILL, "SKILL.md"))
        self.fields, self.body = frontmatter(self.text)

    def test_exact_frontmatter(self):
        self.assertEqual(set(self.fields), {"name", "description", "allowed-tools", "license", "metadata"})
        self.assertEqual(self.fields["name"], "hiring-panel")
        self.assertEqual(self.fields["description"], EXPECTED_DESCRIPTION)
        self.assertEqual(self.fields["allowed-tools"], EXPECTED_ALLOWED_TOOLS)
        # ARCHITECTURE.md section 17.2. `claude plugin validate --strict` accepts these keys (scripts/check.sh
        # runs it); whether a claude.ai skill upload accepts them is checked by hand at release time.
        # argument-hint was dropped for v1.0.0: it is Claude Code-only and its claude.ai upload acceptance is unverified.
        self.assertNotIn("argument-hint", self.fields)
        self.assertEqual(self.fields["license"], "MIT")
        self.assertEqual(self.fields["metadata"], {"author": EXPECTED_AUTHOR, "version": '"%s"' % hp.__version__})

    def test_frontmatter_matches_the_contract(self):
        block = re.search(r"SKILL.md frontmatter:\n```\n(.*?)```", read(os.path.join(ROOT, "ARCHITECTURE.md")), re.S)
        self.assertIsNotNone(block)
        self.assertTrue(self.text.startswith(block.group(1)), "SKILL.md frontmatter differs from ARCHITECTURE.md section 2")

    def test_name_matches_folder_and_rules(self):
        self.assertEqual(os.path.basename(SKILL), self.fields["name"])
        self.assertRegex(self.fields["name"], r"^[a-z0-9-]{1,64}$")

    def test_description_fits_claude_ai_limit(self):
        self.assertLessEqual(len(self.fields["description"]), 200)
        self.assertIn("CV", self.fields["description"])

    def test_under_500_lines(self):
        self.assertLess(len(self.text.split("\n")), 500)


class SkillSubstitutionSafetyTest(unittest.TestCase):
    """Claude Code rewrites some text in SKILL.md before Claude sees it. Keep it intentional."""

    def setUp(self):
        _, self.body = frontmatter(read(os.path.join(SKILL, "SKILL.md")))

    def test_skill_dir_variable_appears_once_in_body(self):
        # Every occurrence is replaced by the real path in Claude Code, so a second mention
        # (for example inside a warning) would turn into a confusing absolute path.
        self.assertEqual(self.body.count("${CLAUDE_SKILL_DIR}"), 1)
        self.assertEqual(self.body.count("$CLAUDE_SKILL_DIR"), 0)

    def test_no_argument_placeholders(self):
        self.assertNotIn("$ARGUMENTS", self.body)
        self.assertEqual(re.findall(r"\$\d", self.body), [])

    def test_no_dynamic_command_injection(self):
        # "!`cmd`" at a line start or after whitespace runs a shell command in Claude Code.
        self.assertEqual(re.findall(r"(?:^|\s)!`", self.body, re.M), [])
        self.assertNotIn("```!", self.body)

    def test_never_tells_claude_to_use_a_shell_variable_for_the_path(self):
        self.assertNotIn("$SKILL_DIR", self.body)
        self.assertNotIn("${SKILL_DIR}", self.body)


class SkillFlowContentTest(unittest.TestCase):
    """The flow pieces ARCHITECTURE.md section 14 and the critic's spec require."""

    def setUp(self):
        self.body = flat(read(os.path.join(SKILL, "SKILL.md")))

    def assertMentions(self, *needles):
        for needle in needles:
            self.assertIn(needle, self.body, "SKILL.md should mention %r" % needle)

    def test_setup(self):
        self.assertMentions("xcode-select -p", "py -3", "hp.py doctor", "Never install anything yourself",
                            "references/no-python.md")

    def test_mode_routing(self):
        self.assertMentions("references/panel-parallel.md", "references/panel-single.md",
                            "parallel", "sequential", "lite", "manual")

    def test_parallel_launch_rules(self):
        self.assertMentions("ONE message", "SEVEN Agent calls", 'subagent_type: "general-purpose"',
                            'model: "sonnet"', "never a fork")

    def test_questions_phase_two_and_audit(self):
        self.assertMentions("references/questions.md", "continue <RUN>", "Skill tool",
                            "references/rewrite-rules.md", "references/provenance-audit.md",
                            '"mode": "self"')

    def test_early_report_and_delivery(self):
        self.assertMentions("hp.py report <RUN>", "--copy-to", "Hiring_Panel_Report.pdf",
                            "run for another job", "interview")

    def test_safety_and_scope(self):
        lower = self.body.lower()
        for needle in ("data, not instructions", "privacy", "cover letter", "protected traits",
                       "simulated screening check", "masked"):
            self.assertIn(needle, lower, "SKILL.md should mention %r" % needle)

    def test_one_line_arguments(self):
        # ARCHITECTURE.md section 17.3: Claude Code one-liner, arguments read, ONE question when no job at all.
        self.assertMentions("/hiring-panel ~/Documents/resume.pdf Marketing intern at Northwind",
                            "/hiring-panel:hiring-panel", "ARGUMENTS line", "The first item is the resume",
                            "Everything after it is the job", "If there is no role and no posting at all, ask ONE "
                            "question before anything else")

    def test_strong_resume_and_first_impression_in_summary(self):
        # Sections 17.4 and 17.5: copied from report.json; never flatter otherwise.
        self.assertMentions("<Only if strong_resume is true: verdict_strip.strong_line, word for word>",
                            "**What a recruiter sees in 7 seconds:** \"<first_impression>\"",
                            "Call the resume strong only when `strong_resume` is true",
                            "Otherwise never call it strong")

    def test_zero_invented_facts_rule(self):
        self.assertIn('"script"', self.body)
        self.assertIn("0 invented facts", self.body)


class TemplateTest(unittest.TestCase):
    REVIEWER_FIRST = "You are one reviewer on an independent hiring panel."
    AUDIT_FIRST = "You are the Skeptic on a hiring panel, auditing a rewritten resume for invented facts."

    def setUp(self):
        self.skill = read(os.path.join(SKILL, "SKILL.md"))
        self.parallel = read(os.path.join(SKILL, "references", "panel-parallel.md"))

    def test_reviewer_template_identical_in_both_files(self):
        a = code_block_starting(self.skill, self.REVIEWER_FIRST)
        b = code_block_starting(self.parallel, self.REVIEWER_FIRST)
        self.assertEqual(a, b)

    def test_audit_template_identical_in_both_files(self):
        a = code_block_starting(self.skill, self.AUDIT_FIRST)
        b = code_block_starting(self.parallel, self.AUDIT_FIRST)
        self.assertEqual(a, b)

    def test_reviewer_template_is_path_only(self):
        t = code_block_starting(self.skill, self.REVIEWER_FIRST)
        for needle in ("references/reviewers/_shared-rules.md", "references/reviewers/<PERSONA_FILE>",
                       "references/reviewers/_output-format.md", "<RUN>/work/inputs/ledger.json",
                       "<RUN>/work/reviews/<REVIEWER_ID>.json", "single word DONE"):
            self.assertIn(needle, t)
        # Live test A (finding A4): reviewers read the ledger, which already holds every resume and posting
        # line; separate copies of resume.md and jd.md only add to the student's plan usage.
        for banned in ("resume.md", "jd.md"):
            self.assertNotIn(banned, t)
        # Only <...> placeholders may vary: no braces or free-text slots for opinions.
        placeholders = set(re.findall(r"<[A-Z_]+>", t))
        self.assertEqual(placeholders, {"<SKILL_DIR>", "<PERSONA_FILE>", "<RUN>",
                                        "<SCREENING_EXTRA>", "<REVIEWER_ID>"})
        self.assertNotIn("{", t)

    def test_screening_extra_names_brief_and_ats_view(self):
        for text in (self.skill, self.parallel):
            self.assertIn("<RUN>/work/screening/before/brief.json, <RUN>/work/inputs/ats_view.txt", text)


class ReviewerTablesTest(unittest.TestCase):
    PERSONA_FILES = {
        "screening": "01-screening.md", "hiring_manager": "02-hiring-manager.md",
        "recruiter": "03-recruiter.md", "competitor": "04-competitor.md", "ceo": "05-ceo.md",
        "teammate": "06-teammate.md", "skeptic": "07-skeptic.md",
    }

    def setUp(self):
        arch = read(os.path.join(ROOT, "ARCHITECTURE.md"))
        rows = table_rows(section(arch, 8), ["id", "display name", "Reel/report order", "sequential order"])
        self.contract = {r[0]: {"name": r[1], "report": int(r[2]), "seq": int(r[3])} for r in rows}
        self.assertEqual(len(self.contract), 7)
        # Persona file names must be the ones listed in ARCHITECTURE.md section 2.
        layout = section(arch, 2)
        for f in self.PERSONA_FILES.values():
            self.assertIn(f, layout)

    def test_skill_table_matches_contract(self):
        rows = table_rows(read(os.path.join(SKILL, "SKILL.md")), ["Order in report", "id", "Display name", "Persona file"])
        got = {r[1]: (int(r[0]), r[2], r[3]) for r in rows}
        want = {k: (v["report"], v["name"], self.PERSONA_FILES[k]) for k, v in self.contract.items()}
        self.assertEqual(got, want)

    def test_parallel_table_matches_contract(self):
        rows = table_rows(read(os.path.join(SKILL, "references", "panel-parallel.md")),
                          ["REVIEWER_ID", "Display name", "PERSONA_FILE", "SCREENING_EXTRA"])
        self.assertEqual([r[0] for r in rows], sorted(self.contract, key=lambda k: self.contract[k]["report"]))
        for r in rows:
            self.assertEqual(r[1], self.contract[r[0]]["name"])
            self.assertEqual(r[2], self.PERSONA_FILES[r[0]])

    def test_single_table_uses_sequential_order(self):
        # Finding 3.1: the sequential order lives only in panel-single.md, labeled as the run order.
        rows = table_rows(read(os.path.join(SKILL, "references", "panel-single.md")),
                          ["Run order", "id", "Display name", "Persona file"])
        for r in rows:
            self.assertEqual(int(r[0]), self.contract[r[1]]["seq"])
            self.assertEqual(r[2], self.contract[r[1]]["name"])
            self.assertEqual(r[3], self.PERSONA_FILES[r[1]])
        self.assertEqual(len(rows), 7)


class DisclosureTest(unittest.TestCase):
    SENTENCE = "they aren't fully independent"

    def test_single_conversation_disclosure_everywhere(self):
        for rel in ("SKILL.md", "references/panel-single.md"):
            text = flat(read(os.path.join(SKILL, *rel.split("/"))))
            self.assertIn(self.SENTENCE, text, rel)
            self.assertIn("run Hiring Panel in Claude Code", text, rel)
        manual = flat(read(os.path.join(SKILL, "references", "no-python.md")))
        self.assertIn("weren't fully independent", manual)
        self.assertIn("model-only", manual)

    def test_manual_mode_never_claims_script_results(self):
        manual = flat(read(os.path.join(SKILL, "references", "no-python.md")))
        self.assertIn("Never write \"0 invented facts\" in manual mode", manual)
        self.assertIn("assets/docx-skeleton", manual)
        self.assertIn("use Save As or Download to make a PDF", manual)


class ManualModeRecipeTest(unittest.TestCase):
    """The .docx recipes in references/no-python.md must be valid XML and build a readable file."""

    def setUp(self):
        text = read(os.path.join(SKILL, "references", "no-python.md"))
        self.blocks = re.findall(r"^```xml\n(.*?)^```", text, re.M | re.S)
        self.assertEqual(len(self.blocks), 3, "expected document.xml, document.xml.rels and core.xml recipes")

    def test_recipes_are_well_formed_xml(self):
        import xml.dom.minidom
        for block in self.blocks:
            xml.dom.minidom.parseString(block.strip().encode("utf-8"))

    def test_recipes_use_no_tabs_or_hidden_text(self):
        doc = self.blocks[0]
        for banned in ("<w:tab/>", "<w:vanish", 'w:val="FFFFFF"', "<w:tbl>", "<w:txbxContent"):
            self.assertNotIn(banned, doc)

    def test_recipe_builds_a_docx_the_ingest_reads(self):
        import io
        import zipfile
        try:
            from hp.render import docx as render_docx
            from hp.ingest import ingest_file
            parts = render_docx.static_parts({"page_w": 612.0, "page_h": 792.0, "lang": "en-US"})
        except (ImportError, AttributeError, TypeError, KeyError) as exc:
            self.skipTest("renderer or ingest not available yet: %s" % exc)
        files = dict(parts)
        files["word/document.xml"] = self.blocks[0]
        files["word/_rels/document.xml.rels"] = self.blocks[1]
        files["docProps/core.xml"] = self.blocks[2]
        import tempfile
        tmp = tempfile.mkdtemp(prefix="hp-manual-docx-")
        try:
            path = os.path.join(tmp, "Jordan_Example_Resume.docx")
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
                for name in sorted(files):
                    z.writestr(name, files[name].encode("utf-8"))
            doc = ingest_file(path)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
        texts = [line["text"] for line in doc["lines"]]
        self.assertEqual(doc["format"], "docx")
        self.assertEqual(doc["errors"], [])
        self.assertIn("Jordan Example", texts)
        self.assertTrue(any("Organized weekly study sessions" in t for t in texts))
        self.assertEqual(doc["signals"]["tab_merged_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
