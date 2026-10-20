"""Every file path the docs point at must exist, or be listed in the ARCHITECTURE.md contract.

Files written by other builders may not exist yet while the repo is being assembled, so a
path also passes when its file name appears in ARCHITECTURE.md (the layout tree in section 2
or anywhere else in the contract). Once the repo is complete, every path should exist.

Checked:
  * SKILL.md and references/**/*.md: skill-relative paths such as `references/x.md`,
    `scripts/hp.py`, `schemas/...`, `assets/...` (with or without a `<SKILL_DIR>/` prefix),
    and reviewer file names such as `01-screening.md`.
  * Repo Markdown (README.md, SECURITY.md, CHANGELOG.md, docs/, the plugin README,
    .github/): relative Markdown links.
"""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SKILL = os.path.join(ROOT, "plugins", "hiring-panel", "skills", "hiring-panel")
sys.path.insert(0, os.path.join(SKILL, "scripts"))

SKILL_PATH_RE = re.compile(
    r"(?:<SKILL_DIR>/)?\b((?:references|scripts|schemas|assets)/[A-Za-z0-9_./-]*[A-Za-z0-9_/-])")
REVIEWER_FILE_RE = re.compile(r"(?<![\w/-])((?:0[1-7]-[a-z-]+|_[a-z-]+)\.md)\b")
LINK_RE = re.compile(r"\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read().replace("\r\n", "\n")


def contract_names():
    """Every file or folder name mentioned in ARCHITECTURE.md."""
    arch = read(os.path.join(ROOT, "ARCHITECTURE.md"))
    names = set()
    for token in re.findall(r"[A-Za-z0-9_.\-]+/?", arch):
        token = token.rstrip("/")
        if token:
            names.add(token)
    return names


def skill_docs():
    out = [os.path.join(SKILL, "SKILL.md")]
    for here, dirs, files in os.walk(os.path.join(SKILL, "references")):
        dirs.sort()
        out += [os.path.join(here, f) for f in sorted(files) if f.endswith(".md")]
    return out


def repo_docs():
    out = []
    for rel in ("README.md", "SECURITY.md", "CHANGELOG.md", "plugins/hiring-panel/README.md"):
        p = os.path.join(ROOT, *rel.split("/"))
        if os.path.exists(p):
            out.append(p)
    for top in ("docs", ".github"):
        for here, dirs, files in os.walk(os.path.join(ROOT, top)):
            dirs.sort()
            out += [os.path.join(here, f) for f in sorted(files) if f.endswith(".md")]
    return out


class PathResolutionTest(unittest.TestCase):
    def setUp(self):
        self.names = contract_names()

    def known(self, path):
        """True if `path` exists or its last component is named in the contract."""
        if os.path.exists(path):
            return True
        return os.path.basename(path.rstrip("/\\")) in self.names

    def test_contract_names_parse(self):
        for name in ("SKILL.md", "panel-parallel.md", "questions.md", "hp.py", "NOTICE",
                     "docx-skeleton", "sample-run", "01-screening.md", "_lite-cards.md"):
            self.assertIn(name, self.names)

    def test_skill_and_reference_paths(self):
        problems = []
        for doc in skill_docs():
            rel_doc = os.path.relpath(doc, ROOT)
            for lineno, line in enumerate(read(doc).split("\n"), 1):
                line = re.sub(r"https?://\S+", " ", line)  # paths inside web links aren't ours
                for m in SKILL_PATH_RE.finditer(line):
                    rel = m.group(1)
                    if "<" in rel or "*" in rel:
                        continue
                    if not self.known(os.path.join(SKILL, *rel.rstrip("/").split("/"))):
                        problems.append("%s:%d %s" % (rel_doc, lineno, rel))
                for m in REVIEWER_FILE_RE.finditer(line):
                    path = os.path.join(SKILL, "references", "reviewers", m.group(1))
                    if not self.known(path):
                        problems.append("%s:%d %s" % (rel_doc, lineno, m.group(1)))
        self.assertEqual(problems, [], "\n" + "\n".join(problems))

    def test_repo_markdown_links(self):
        problems = []
        checked = 0
        for doc in repo_docs():
            rel_doc = os.path.relpath(doc, ROOT)
            for lineno, line in enumerate(read(doc).split("\n"), 1):
                for m in LINK_RE.finditer(line):
                    target = m.group(1)
                    if re.match(r"^(https?:|mailto:|#)", target):
                        continue
                    target = target.split("#", 1)[0]
                    if not target:
                        continue
                    checked += 1
                    path = os.path.normpath(os.path.join(os.path.dirname(doc), *target.split("/")))
                    if not path.startswith(ROOT) or not self.known(path):
                        problems.append("%s:%d %s" % (rel_doc, lineno, target))
        self.assertGreater(checked, 5)
        self.assertEqual(problems, [], "\n" + "\n".join(problems))

    def test_my_routing_files_exist(self):
        # The files SKILL.md routes to that this part of the build owns must really exist.
        for rel in ("panel-parallel.md", "panel-single.md", "edge-cases.md", "no-python.md",
                    "troubleshooting.md", "sources.md"):
            self.assertTrue(os.path.isfile(os.path.join(SKILL, "references", rel)), rel)
        for rel in ("README.md", "LICENSE", "SECURITY.md", "CHANGELOG.md", "docs/how-it-works.md",
                    "docs/privacy.md", "plugins/hiring-panel/README.md", "plugins/hiring-panel/LICENSE",
                    "scripts/release.sh", "scripts/check.sh", ".github/workflows/check.yml", ".gitignore"):
            self.assertTrue(os.path.isfile(os.path.join(ROOT, *rel.split("/"))), rel)


class AnchorLinkTest(unittest.TestCase):
    """In-page links like (#privacy) in README.md must match a heading."""

    @staticmethod
    def slug(heading):
        s = heading.strip().lower()
        s = re.sub(r"[^\w\- ]", "", s)
        return s.replace(" ", "-")

    def test_readme_anchors(self):
        text = read(os.path.join(ROOT, "README.md"))
        slugs = {self.slug(h) for h in re.findall(r"^#{1,6} (.+)$", text, re.M)}
        anchors = re.findall(r"\]\(#([^)]+)\)", text)
        self.assertGreater(len(anchors), 3)
        missing = sorted(a for a in set(anchors) if a not in slugs)
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
