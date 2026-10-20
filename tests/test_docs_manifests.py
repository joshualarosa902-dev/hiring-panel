"""Packaging checks: the plugin and marketplace manifests, licenses and version strings.

Names and versions must agree everywhere a student or Claude Code reads them, because the
plugin name is permanent after release and the version drives updates.
"""
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PLUGIN = os.path.join(ROOT, "plugins", "hiring-panel")
SKILL = os.path.join(PLUGIN, "skills", "hiring-panel")
sys.path.insert(0, os.path.join(SKILL, "scripts"))

import hp  # noqa: E402  (after the sys.path insert)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read().replace("\r\n", "\n")


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class ManifestTest(unittest.TestCase):
    def setUp(self):
        self.plugin = load(os.path.join(PLUGIN, ".claude-plugin", "plugin.json"))
        self.market = load(os.path.join(ROOT, ".claude-plugin", "marketplace.json"))
        entries = [p for p in self.market["plugins"] if p["name"] == "hiring-panel"]
        self.assertEqual(len(entries), 1)
        self.entry = entries[0]

    def test_plugin_json(self):
        p = self.plugin
        self.assertEqual(p["name"], "hiring-panel")
        self.assertRegex(p["version"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(p["license"], "MIT")
        self.assertEqual(p["author"]["name"], "Joshua LaRosa")
        self.assertRegex(p["homepage"], r"^https://github\.com/[^/]+/hiring-panel$")
        self.assertEqual(p["repository"], p["homepage"])
        self.assertTrue({"resume", "cv", "job-search"} <= set(p["keywords"]))
        self.assertLessEqual(len(p["description"]), 200)

    def test_marketplace_json(self):
        m = self.market
        self.assertEqual(m["name"], "hiring-panel")
        self.assertEqual(m["owner"]["name"], "Joshua LaRosa")
        self.assertEqual(self.entry["source"], "./plugins/hiring-panel")
        source = os.path.normpath(os.path.join(ROOT, self.entry["source"]))
        self.assertTrue(os.path.isfile(os.path.join(source, ".claude-plugin", "plugin.json")))
        self.assertEqual(self.entry["description"], self.plugin["description"])

    def test_versions_agree(self):
        v = self.plugin["version"]
        self.assertEqual(v, hp.__version__)
        self.assertEqual(self.entry.get("version", v), v)
        self.assertEqual(self.market.get("metadata", {}).get("version", v), v)
        self.assertIn("## [%s]" % v, read(os.path.join(ROOT, "CHANGELOG.md")))
        self.assertIn("Version %s" % v, read(os.path.join(ROOT, "README.md")))

    def test_names_agree(self):
        fm = re.match(r"^---\n(.*?)\n---\n", read(os.path.join(SKILL, "SKILL.md")), re.S).group(1)
        self.assertIn("name: hiring-panel", fm.split("\n"))
        self.assertEqual(os.path.basename(SKILL), self.plugin["name"])
        self.assertEqual(os.path.basename(PLUGIN), self.plugin["name"])

    def test_install_commands_match_names(self):
        readme = read(os.path.join(ROOT, "README.md"))
        self.assertIn("/plugin install %s@%s" % (self.plugin["name"], self.market["name"]), readme)


class LicenseTest(unittest.TestCase):
    def test_mit_in_both_places(self):
        root = read(os.path.join(ROOT, "LICENSE"))
        plugin = read(os.path.join(PLUGIN, "LICENSE"))
        self.assertEqual(root, plugin)
        self.assertTrue(root.startswith("MIT License"))
        self.assertIn("Joshua LaRosa", root)


class CitationTest(unittest.TestCase):
    """CITATION.cff (ARCHITECTURE.md section 17.1). No YAML parser in the standard library, so this checks
    the fixed lines a CFF 1.2.0 file needs and the reference to the original skill."""

    def setUp(self):
        self.text = read(os.path.join(ROOT, "CITATION.cff"))
        self.top = dict((m.group(1), m.group(2).strip().strip('"'))
                        for m in re.finditer(r"^([a-z-]+):[ \t]*(.*)$", self.text, re.M))

    def test_required_fields(self):
        self.assertEqual(self.top["cff-version"], "1.2.0")
        self.assertEqual(self.top["type"], "software")
        self.assertEqual(self.top["title"], "Hiring Panel")
        self.assertEqual(self.top["license"], "MIT")
        self.assertEqual(self.top["version"], hp.__version__)
        self.assertEqual(self.top["date-released"], "2026-10-20")
        self.assertEqual(self.top["repository-code"], "https://github.com/joshualarosa902-dev/hiring-panel")
        self.assertTrue(self.top["message"])
        self.assertNotIn("\t", self.text)

    def test_author_and_reference(self):
        authors, _, refs = self.text.partition("\nreferences:\n")
        self.assertIn("  - given-names: Joshua\n    family-names: LaRosa\n    alias: joshualarosa.ai\n",
                      authors.split("\nauthors:\n", 1)[1])
        self.assertIn("  - type: software\n", refs)
        for line in ("given-names: Alex", "family-names: Chen", "alias: nocodealex",
                     'repository-code: "https://github.com/alexyc9381/hiring-panel-skill"', "license: MIT"):
            self.assertIn(line, refs)

    def test_mentioned_in_readme_footer(self):
        footer = read(os.path.join(ROOT, "README.md")).rsplit("\n---\n", 1)[-1]
        self.assertIn("[CITATION.cff](CITATION.cff)", footer)


class GitignoreTest(unittest.TestCase):
    def test_entries(self):
        lines = set(read(os.path.join(ROOT, ".gitignore")).split("\n"))
        for entry in ("dist/", "__pycache__/", "hiring-panel-runs/", ".DS_Store"):
            self.assertIn(entry, lines)


class WorkflowTest(unittest.TestCase):
    """A light structural check of the CI workflow (no YAML parser in the standard library)."""

    def setUp(self):
        self.text = read(os.path.join(ROOT, ".github", "workflows", "check.yml"))

    def test_matrix(self):
        self.assertIn("os: [ubuntu-latest, macos-latest, windows-latest]", self.text)
        self.assertIn('python: ["3.8", "3.9", "3.12"]', self.text)
        self.assertIn("python -m unittest discover -s tests", self.text)

    def test_release_job(self):
        self.assertIn("startsWith(github.ref, 'refs/tags/v')", self.text)
        self.assertIn("bash scripts/release.sh", self.text)
        self.assertIn("dist/hiring-panel.plugin dist/hiring-panel-skill.zip", self.text)
        self.assertIn("contents: write", self.text)

    def test_no_tabs_in_yaml(self):
        self.assertNotIn("\t", self.text)

    def test_issue_templates_ask_for_fictional_text(self):
        folder = os.path.join(ROOT, ".github", "ISSUE_TEMPLATE")
        templates = [f for f in os.listdir(folder) if f.endswith(".md")]
        self.assertGreaterEqual(len(templates), 2)
        for name in templates:
            text = read(os.path.join(folder, name)).lower()
            self.assertTrue(text.startswith("---\nname: "), name)
            self.assertTrue("made-up" in text or "fictional" in text, name)
            self.assertIn("personal details", text, name)


if __name__ == "__main__":
    unittest.main()
