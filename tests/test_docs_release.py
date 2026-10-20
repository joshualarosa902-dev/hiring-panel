"""Behavior tests for scripts/release.sh and scripts/check.sh.

Each test works on a throwaway copy of the repo's packaging files, so nothing in the real
tree changes and no dist/ folder appears. If the integration builder's scripts/hp.py doesn't
exist yet, the copy gets a tiny stand-in so the packaging can still be exercised.

Skipped on Windows (the scripts are bash; releases are built on Linux in CI).
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SKILL_REL = os.path.join("plugins", "hiring-panel", "skills", "hiring-panel")
sys.path.insert(0, os.path.join(ROOT, SKILL_REL, "scripts"))

BASH = shutil.which("bash")
CAN_RUN = os.name != "nt" and BASH is not None
COPY_ITEMS = ["scripts", ".claude-plugin", "plugins", "README.md", "SECURITY.md", "CHANGELOG.md",
              "NOTICE", "CITATION.cff", "docs", ".github"]
STUB_HP = '"""Test stand-in for scripts/hp.py (the real CLI is built separately)."""\n' \
          'import json, sys\nprint(json.dumps({"stub": True, "argv": sys.argv[1:]}))\n'


def make_copy(dest):
    """Copy the packaging-relevant parts of the repo into dest and add junk to be excluded."""
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "dist")
    for item in COPY_ITEMS:
        src = os.path.join(ROOT, item)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dest, item), ignore=ignore)
        elif os.path.isfile(src):
            shutil.copy2(src, os.path.join(dest, item))
    skill = os.path.join(dest, SKILL_REL)
    hp_py = os.path.join(skill, "scripts", "hp.py")
    if not os.path.exists(hp_py):
        with open(hp_py, "w", encoding="utf-8") as fh:
            fh.write(STUB_HP)
    # The manual-mode .docx skeleton holds dot-files that must ship (create stand-ins if absent).
    for rel, data in ((("assets", "docx-skeleton", "_rels", ".rels"), b"<Relationships/>"),
                      (("assets", "docx-skeleton", "[Content_Types].xml"), b"<Types/>")):
        path = os.path.join(skill, *rel)
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(data)
    junk = {
        os.path.join(skill, "scripts", "hp", "__pycache__", "util.cpython-39.pyc"): b"\x00junk",
        os.path.join(skill, ".DS_Store"): b"junk",
        os.path.join(dest, "plugins", "hiring-panel", ".DS_Store"): b"junk",
        os.path.join(skill, "references", "._SKILL.md"): b"junk",
        os.path.join(skill, "tests", "test_should_not_ship.py"): b"# excluded\n",
        os.path.join(skill, "scripts", "stray.pyc"): b"junk",
    }
    for path, data in junk.items():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)


def run(copy, script, *args):
    env = dict(os.environ, PYTHON=sys.executable, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([BASH, os.path.join(copy, "scripts", script)] + list(args),
                          cwd=copy, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True, timeout=300)


def sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


@unittest.skipUnless(CAN_RUN, "needs bash on macOS or Linux")
class ReleaseScriptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hp-release-test-")
        self.copy = os.path.join(self.tmp, "repo")
        os.makedirs(self.copy)
        make_copy(self.copy)
        self.put_placeholder_back()
        self.out = os.path.join(self.tmp, "out")

    def put_placeholder_back(self):
        """The real repo has the GitHub owner filled in; these tests start from the pre-release
        state, so swap the owner back to the OWNER placeholder in the copy."""
        for here, dirs, files in os.walk(self.copy):
            for name in files:
                path = os.path.join(here, name)
                try:
                    with open(path, encoding="utf-8") as fh:
                        text = fh.read()
                except (UnicodeDecodeError, OSError):
                    continue
                if "joshualarosa902-dev" in text:
                    with open(path, "w", encoding="utf-8") as fh:
                        fh.write(text.replace("joshualarosa902-dev", "OWNER"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def replace_owner(self):
        for here, dirs, files in os.walk(self.copy):
            dirs[:] = [d for d in dirs if d not in ("scripts",)] if here == self.copy else dirs
            for name in files:
                path = os.path.join(here, name)
                try:
                    with open(path, encoding="utf-8") as fh:
                        text = fh.read()
                except (UnicodeDecodeError, OSError):
                    continue
                if re.search(r"\bOWNER\b", text):
                    with open(path, "w", encoding="utf-8") as fh:
                        fh.write(re.sub(r"\bOWNER\b", "fictional-owner", text))

    def test_refuses_while_owner_placeholder_remains(self):
        r = run(self.copy, "release.sh", "--skip-validate", "--out", self.out)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("OWNER", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.out, "hiring-panel.plugin")))

    def test_builds_both_files_with_the_right_structure(self):
        r = run(self.copy, "release.sh", "--allow-placeholder", "--skip-validate", "--out", self.out)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

        with zipfile.ZipFile(os.path.join(self.out, "hiring-panel.plugin")) as z:
            names = z.namelist()
            self.assertIsNone(z.testzip())
            skill_md = z.read("hiring-panel/skills/hiring-panel/SKILL.md")
        self.assertEqual({n.split("/")[0] for n in names}, {"hiring-panel"})
        for required in ("hiring-panel/.claude-plugin/plugin.json", "hiring-panel/LICENSE",
                         "hiring-panel/README.md", "hiring-panel/skills/hiring-panel/scripts/hp.py",
                         "hiring-panel/skills/hiring-panel/references/panel-parallel.md"):
            self.assertIn(required, names)
        with open(os.path.join(self.copy, SKILL_REL, "SKILL.md"), "rb") as fh:
            self.assertEqual(skill_md, fh.read())

        with zipfile.ZipFile(os.path.join(self.out, "hiring-panel-skill.zip")) as z:
            skill_names = z.namelist()
        self.assertEqual({n.split("/")[0] for n in skill_names}, {"hiring-panel"})
        self.assertIn("hiring-panel/SKILL.md", skill_names)
        self.assertIn("hiring-panel/references/panel-single.md", skill_names)
        self.assertIn("hiring-panel/assets/docx-skeleton/_rels/.rels", skill_names)
        self.assertIn("hiring-panel/assets/docx-skeleton/[Content_Types].xml", skill_names)
        self.assertFalse(any(n.startswith("hiring-panel/skills/") for n in skill_names))

        for n in names + skill_names:
            parts = n.rstrip("/").split("/")
            self.assertNotIn("__pycache__", parts, n)
            self.assertNotIn("tests", parts, n)
            self.assertNotEqual(parts[-1], ".DS_Store", n)
            self.assertFalse(parts[-1].startswith("._"), n)
            self.assertFalse(parts[-1].endswith(".pyc"), n)
        self.assertIn("sha256", r.stdout)

    def test_output_is_deterministic(self):
        out2 = os.path.join(self.tmp, "out2")
        for out in (self.out, out2):
            r = run(self.copy, "release.sh", "--allow-placeholder", "--skip-validate", "--out", out)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for name in ("hiring-panel.plugin", "hiring-panel-skill.zip"):
            self.assertEqual(sha(os.path.join(self.out, name)), sha(os.path.join(out2, name)))

    def test_builds_without_flag_once_owner_is_replaced(self):
        self.replace_owner()
        r = run(self.copy, "release.sh", "--skip-validate", "--out", self.out)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with zipfile.ZipFile(os.path.join(self.out, "hiring-panel.plugin")) as z:
            manifest = json.loads(z.read("hiring-panel/.claude-plugin/plugin.json").decode("utf-8"))
        self.assertIn("fictional-owner", manifest["homepage"])

    def test_version_mismatch_is_refused(self):
        path = os.path.join(self.copy, "plugins", "hiring-panel", ".claude-plugin", "plugin.json")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        data["version"] = "9.9.9"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        r = run(self.copy, "release.sh", "--allow-placeholder", "--skip-validate", "--out", self.out)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("9.9.9", r.stderr)

    def test_owner_left_only_in_citation_is_refused(self):
        self.replace_owner()
        path = os.path.join(self.copy, "CITATION.cff")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("fictional-owner", text)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text.replace("fictional-owner", "OWNER"))
        r = run(self.copy, "release.sh", "--skip-validate", "--out", self.out)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("CITATION.cff", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.out, "hiring-panel.plugin")))

    def test_citation_and_skill_metadata_versions_must_agree(self):
        for rel, old, new in (("CITATION.cff", 'version: "1.0.0"', 'version: "9.9.8"'),
                              (os.path.join(SKILL_REL, "SKILL.md"), '  version: "1.0.0"', '  version: "9.9.7"')):
            path = os.path.join(self.copy, rel)
            with open(path, encoding="utf-8") as fh:
                original = fh.read()
            self.assertEqual(original.count(old), 1, rel)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(original.replace(old, new))
            r = run(self.copy, "release.sh", "--allow-placeholder", "--skip-validate", "--out", self.out)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn(new.split('"')[1], r.stderr)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(original)
        r = run(self.copy, "release.sh", "--allow-placeholder", "--skip-validate", "--out", self.out)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("CITATION.cff", r.stdout)

    def test_unknown_option(self):
        r = run(self.copy, "release.sh", "--frobnicate")
        self.assertEqual(r.returncode, 2)

    @unittest.skipUnless(shutil.which("claude"), "the Claude Code CLI is not installed")
    def test_validates_with_claude_cli(self):
        r = run(self.copy, "release.sh", "--allow-placeholder", "--out", self.out)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


@unittest.skipUnless(CAN_RUN, "needs bash on macOS or Linux")
class CheckScriptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hp-check-test-")
        make_copy(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_clean_tree_passes_the_network_check(self):
        r = run(self.tmp, "check.sh", "--no-tests", "--no-validate")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("PASS  static scan", r.stdout)

    def test_planted_network_import_is_caught(self):
        planted = os.path.join(self.tmp, SKILL_REL, "scripts", "hp", "planted_fetch.py")
        with open(planted, "w", encoding="utf-8") as fh:
            fh.write("import urllib.request\n\ndef fetch(u):\n    return urllib.request.urlopen(u)\n")
        r = run(self.tmp, "check.sh", "--no-tests", "--no-validate")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("planted_fetch.py", r.stdout)

    def test_planted_curl_call_is_caught(self):
        planted = os.path.join(self.tmp, SKILL_REL, "scripts", "hp", "planted_curl.py")
        with open(planted, "w", encoding="utf-8") as fh:
            fh.write("import subprocess\n\ndef fetch(u):\n    return subprocess.run(['curl', u])\n")
        r = run(self.tmp, "check.sh", "--no-tests", "--no-validate")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("planted_curl.py", r.stdout)

    def test_shell_syntax(self):
        for script in ("release.sh", "check.sh"):
            r = subprocess.run([BASH, "-n", os.path.join(ROOT, "scripts", script)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
