"""Voice and promise checks on the user-facing docs (ARCHITECTURE.md section 16, critic spec 4).

* No em dashes in README.md or SKILL.md (or any other doc this part of the build owns).
* Never the words "ATS score": the only number is the "simulated screening check".
* The README carries what the critic's spec requires: the top box with plan honesty, step 0,
  install paths A/B/C with the exact links, the Safari note, Claude Code commands, the first
  message, expectations, privacy, troubleshooting, the honesty promise, FAQ and the footer.
* The README never points students at GitHub's repository download button.
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

# The docs this part of the build writes. Files owned by other builders are not voice-checked here.
OWNED_DOCS = [
    "README.md", "SECURITY.md", "CHANGELOG.md",
    "docs/how-it-works.md", "docs/privacy.md", "docs/releasing.md", "docs/img/README.md",
    "plugins/hiring-panel/README.md",
    "plugins/hiring-panel/skills/hiring-panel/SKILL.md",
    "plugins/hiring-panel/skills/hiring-panel/references/panel-parallel.md",
    "plugins/hiring-panel/skills/hiring-panel/references/panel-single.md",
    "plugins/hiring-panel/skills/hiring-panel/references/questions.md",
    "plugins/hiring-panel/skills/hiring-panel/references/rewrite-rules.md",
    "plugins/hiring-panel/skills/hiring-panel/references/edge-cases.md",
    "plugins/hiring-panel/skills/hiring-panel/references/no-python.md",
    "plugins/hiring-panel/skills/hiring-panel/references/troubleshooting.md",
    "plugins/hiring-panel/skills/hiring-panel/references/sources.md",
    ".github/ISSUE_TEMPLATE/bug_report.md", ".github/ISSUE_TEMPLATE/feature_request.md",
    ".github/ISSUE_TEMPLATE/setup_help.md", ".github/PULL_REQUEST_TEMPLATE.md",
]
EM_DASH = "—"


def read(rel):
    with open(os.path.join(ROOT, *rel.split("/")), encoding="utf-8") as fh:
        return fh.read().replace("\r\n", "\n")


def flat(text):
    return " ".join(re.sub(r"(?m)^[ \t]*>[ \t]?", "", text).split())


class VoiceTest(unittest.TestCase):
    def test_no_em_dashes(self):
        offenders = []
        for rel in OWNED_DOCS:
            for lineno, line in enumerate(read(rel).split("\n"), 1):
                if EM_DASH in line:
                    offenders.append("%s:%d" % (rel, lineno))
        self.assertEqual(offenders, [])

    def test_never_ats_score(self):
        pattern = re.compile(r"(?i)\bATS[\s-]+scor")
        offenders = [rel for rel in OWNED_DOCS if pattern.search(flat(read(rel)))]
        self.assertEqual(offenders, [])

    def test_no_interview_promises(self):
        pattern = re.compile(r"(?i)guarantee(?:s|d)? (?:an |you )?interview|interview-ready|land the job")
        for rel in ("README.md", "plugins/hiring-panel/README.md", "docs/how-it-works.md"):
            text = flat(read(rel))
            for m in pattern.finditer(text):
                window = text[max(0, m.start() - 40):m.start()].lower()
                self.assertTrue("n't" in window or "not" in window or "no " in window,
                                "%s promises outcomes: %r" % (rel, text[m.start() - 40:m.end()]))

    def test_plugin_readme_is_long_enough(self):
        words = re.findall(r"\w+", read("plugins/hiring-panel/README.md"))
        self.assertGreaterEqual(len(words), 40)


class ReadmeContentTest(unittest.TestCase):
    def setUp(self):
        self.raw = read("README.md")
        self.text = flat(self.raw)

    def assertSays(self, *needles):
        for needle in needles:
            self.assertIn(needle, self.text, "README.md should say %r" % needle)

    def test_top_box_plan_honesty(self):
        self.assertSays("Free and open source.",
                        "Works on Claude's Free plan as a single-chat panel.",
                        "The fully parallel 7-reviewer panel runs in Claude Code (Pro or Max plan).",
                        "Do the setup on a computer.")
        top = self.raw.split("## ", 1)[0]
        self.assertIn("Free plan", top, "the plan note belongs in the top box")

    def test_reel_promises_mapped(self):
        for name in ("Automated Screening Check", "Hiring Manager", "Recruiter", "Competing Applicant",
                     "CEO", "Future Teammate", "Skeptic"):
            self.assertIn(name, self.text)
        self.assertSays("biggest weaknesses first", "actual experience", ".docx, .pdf and .md")

    def test_step_zero(self):
        self.assertSays("Settings > Capabilities", "Code execution and file creation", "Last checked")

    def test_install_paths(self):
        self.assertSays("joshualarosa902-dev/hiring-panel", "Add marketplace", "Upload plugin", "Customize > Skills",
                        "Upload a skill", "Sync automatically", "pick ONE")
        self.assertIn("https://github.com/joshualarosa902-dev/hiring-panel/releases/latest/download/hiring-panel.plugin", self.raw)
        self.assertIn("https://github.com/joshualarosa902-dev/hiring-panel/releases/latest/download/hiring-panel-skill.zip", self.raw)
        self.assertIn("Safari", self.text)
        self.assertIn("Compress", self.text)

    def test_claude_code_commands(self):
        self.assertIn("/plugin marketplace add joshualarosa902-dev/hiring-panel", self.raw)
        self.assertIn("/plugin install hiring-panel@hiring-panel", self.raw)
        self.assertSays("Enable auto-update", "/hiring-panel:hiring-panel")

    def test_first_message(self):
        self.assertSays("Use Hiring Panel to review my resume for this job.")

    def test_expectations_privacy_troubleshooting(self):
        for heading in ("## What to expect", "## Privacy", "## Troubleshooting", "## My honesty promise",
                        "## FAQ", "## What you get"):
            self.assertIn(heading, self.raw)
        self.assertSays("simulated screening check", "No telemetry", "Help improve Claude", "30 days",
                        "Never post your real resume in a GitHub issue", "40% file readability")
        # The troubleshooting table covers the critic's list.
        lower = self.text.lower()
        for topic in ("doesn't use hiring panel", "code execution", "upload fails", "developer tools",
                      "usage limit", "pdf is missing", "where are my files"):
            self.assertIn(topic, lower)

    def test_no_todo_placeholders_left(self):
        # The README is about to be read by students: written steps replace the screenshot placeholders, and
        # the screenshots still to take are a checklist in docs/img/README.md instead.
        self.assertNotIn("TODO", self.raw)
        self.assertNotIn("<!--", self.raw)
        listing = read("docs/img/README.md")
        for name in ("step0-code-execution.png", "install-a-add-marketplace.png", "install-b-upload-plugin.png",
                     "install-c-upload-skill.png"):
            self.assertIn(name, listing)
        self.assertIn("[ ]", listing)
        # Every image the README shows exists and is listed as done.
        for path in re.findall(r"!\[[^\]]*\]\((docs/img/[\w.-]+)\)", self.raw):
            self.assertTrue(os.path.isfile(os.path.join(ROOT, *path.split("/"))), path)
            self.assertIn(os.path.basename(path), listing)

    def test_footer(self):
        footer = flat(self.raw.rsplit("\n---\n", 1)[-1])
        for needle in ("MIT License", "Not affiliated with Anthropic or any ATS vendor",
                       "For Claude users 18+", "NOTICE", "Version %s" % hp.__version__):
            self.assertIn(needle, footer)

    def test_never_mentions_repo_download_button(self):
        lower = self.text.lower()
        for banned in ("download zip", "green code button", "green button", "code > download"):
            self.assertNotIn(banned, lower)

    def test_speaks_as_joshua(self):
        self.assertSays("I'm Joshua", "@joshualarosa.ai")

    def test_credits(self):
        # ARCHITECTURE.md section 17.1, word for word.
        self.assertIn("## Credits", self.raw)
        credits = flat(self.raw.split("## Credits", 1)[1].split("\n---\n", 1)[0])
        self.assertIn("Inspired by the original hiring-panel skill by Alex Chen (@nocodealex), MIT licensed: "
                      "[github.com/alexyc9381/hiring-panel-skill](https://github.com/alexyc9381/hiring-panel-skill). "
                      "This version is a from-scratch rebuild with a deterministic screening check, evidence-checked "
                      "rewrites, Word/PDF output and claude.ai support.", credits)
        self.assertIn("[Credits](#credits)", self.raw)

    def test_claude_code_paste_install(self):
        # Section 17.6: next to the /plugin commands, the exact text to paste (two spaces after the URL).
        cc = self.raw.split("### Claude Code", 1)[1].split("\n## ", 1)[0]
        self.assertIn("/plugin install hiring-panel@hiring-panel", cc)
        self.assertIn("\nhttps://github.com/joshualarosa902-dev/hiring-panel  Install this skill, then confirm /hiring-panel works.\n",
                      cc)

    def test_one_line_use(self):
        # Section 17.3.
        first = self.raw.split("## Your first message", 1)[1].split("\n## ", 1)[0]
        self.assertIn("\n/hiring-panel ~/Documents/resume.pdf Marketing intern at Northwind\n", first)
        self.assertIn("/hiring-panel:hiring-panel", first)

    def test_name_collision_troubleshooting(self):
        # Section 17.7: users with both skills keep one, since the command names collide.
        trouble = flat(self.raw.split("## Troubleshooting", 1)[1].split("\n## ", 1)[0])
        ref = flat(read("plugins/hiring-panel/skills/hiring-panel/references/troubleshooting.md"))
        for text in (trouble, ref):
            self.assertIn("Alex Chen's original hiring-panel skill", text)
            self.assertIn("keep only one", text)
            self.assertIn("/plugin uninstall hiring-panel-skill@hiring-panel-skill", text)
            self.assertIn("/hiring-panel:hiring-panel", text)


if __name__ == "__main__":
    unittest.main()
