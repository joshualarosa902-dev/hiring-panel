"""Every hp.py command and flag the skill's instructions mention must exist in the CLI contract.

The contract is the code block in ARCHITECTURE.md section 13. This test parses it, then scans
SKILL.md and every Markdown file under references/ (including files other builders write) for:
  * `hp.py <command> ...` mentions inside code (fenced blocks or inline spans): the command
    must exist and each --flag after it must belong to that command, with an allowed value
    when the value is spelled out;
  * command-reference table rows whose first cell is `<command> ...`: same check;
  * any other --flag anywhere: it must be a contract flag (or one of the few non-hp.py flags
    listed in OTHER_TOOL_FLAGS).
"""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SKILL = os.path.join(ROOT, "plugins", "hiring-panel", "skills", "hiring-panel")
sys.path.insert(0, os.path.join(SKILL, "scripts"))

# Double-dash flags of other tools that the docs may legitimately mention.
OTHER_TOOL_FLAGS = {
    "--install",  # `xcode-select --install`, which the student may run themselves (troubleshooting)
}
FLAG_RE = re.compile(r"(?<![\w-])--[a-z][a-z0-9-]*")


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read().replace("\r\n", "\n")


def parse_contract():
    """Return ({command: {flag: allowed values or None}}, set of commands) from section 13."""
    arch = read(os.path.join(ROOT, "ARCHITECTURE.md"))
    m = re.search(r"^## 13\. .*?$(.*?)(?=^## |\Z)", arch, re.M | re.S)
    if not m:
        raise AssertionError("ARCHITECTURE.md has no section 13")
    blocks = re.findall(r"^```\n(.*?)^```", m.group(1), re.M | re.S)
    if not blocks:
        raise AssertionError("section 13 has no code block")
    commands = {}
    current = None
    for line in blocks[0].split("\n"):
        start = re.match(r"^([a-z]+)\b", line)
        if start:
            current = start.group(1)
            commands.setdefault(current, {})
        if current is None:
            continue
        for fm in re.finditer(r"(--[a-z][a-z0-9-]*)(?:\s+([^\s\[\]()]+))?", line):
            flag, value = fm.group(1), fm.group(2)
            allowed = None
            if value and "|" in value and not value.startswith("-"):
                allowed = set(v for v in value.split("|") if v)
            commands[current].setdefault(flag, set())
            if allowed:
                commands[current][flag] = (commands[current][flag] or set()) | allowed
    for cmd, flags in commands.items():
        for flag in flags:
            if not flags[flag]:
                flags[flag] = None
    return commands


def doc_files():
    """SKILL.md plus every Markdown file under references/ (sorted for stable output)."""
    out = [os.path.join(SKILL, "SKILL.md")]
    for here, dirs, files in os.walk(os.path.join(SKILL, "references")):
        dirs.sort()
        out += [os.path.join(here, f) for f in sorted(files) if f.endswith(".md")]
    return out


def value_ok(value, allowed):
    """True if a spelled-out flag value is allowed. Placeholders like <MODE> always pass."""
    if allowed is None or value is None:
        return True
    value = value.strip("`\"',.;:)")
    if not value or "<" in value or value.startswith("-"):
        return True
    if any(a.endswith(":<URL>") and value.startswith(a.split("<")[0]) for a in allowed):
        return True
    return all(part in allowed for part in value.split("|"))


class CliContractParseTest(unittest.TestCase):
    def test_contract_parses(self):
        c = parse_contract()
        self.assertEqual(set(c), {"doctor", "init", "ledger", "screen", "validate", "synthesize",
                                  "truth", "render", "report", "status", "recheck"})
        self.assertIn("--resume-text", c["init"])
        self.assertEqual(c["synthesize"]["--mode"], {"parallel", "sequential", "lite"})
        self.assertEqual(c["render"]["--layout"], {"classic", "inline"})
        self.assertEqual(c["report"], {"--copy-to": None})


class DocsUseOnlyContractCliTest(unittest.TestCase):
    def setUp(self):
        self.contract = parse_contract()
        self.all_flags = set()
        for flags in self.contract.values():
            self.all_flags |= set(flags)

    def check_segment(self, rel, lineno, command, segment, problems):
        if command not in self.contract:
            problems.append("%s:%d unknown hp.py command %r" % (rel, lineno, command))
            return
        allowed_flags = self.contract[command]
        tokens = [t.lstrip("[(") for t in segment.split()]
        for i, tok in enumerate(tokens):
            fm = FLAG_RE.match(tok)
            if not fm:
                continue
            flag = fm.group(0)
            if flag not in allowed_flags:
                problems.append("%s:%d `%s` has no flag %s" % (rel, lineno, command, flag))
                continue
            value = tokens[i + 1] if i + 1 < len(tokens) else None
            if "=" in tok:
                value = tok.split("=", 1)[1]
            if not value_ok(value, allowed_flags[flag]):
                problems.append("%s:%d `%s %s` has a value outside the contract: %s"
                                % (rel, lineno, command, flag, value))

    def code_segments(self, text):
        """Yield (line number, code text) for every fenced code line and every inline code span.

        Only code counts as a command mention, so prose such as "every hp.py command" is ignored.
        """
        in_fence = False
        for lineno, line in enumerate(text.split("\n"), 1):
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                yield lineno, line
            else:
                for span in re.findall(r"`([^`]+)`", line):
                    yield lineno, span

    def test_commands_and_flags(self):
        problems = []
        mentions = 0
        for path in doc_files():
            rel = os.path.relpath(path, ROOT)
            text = read(path)
            for lineno, code in self.code_segments(text):
                for m in re.finditer(r"hp\.py\s+([a-z][a-z-]*)", code):
                    mentions += 1
                    self.check_segment(rel, lineno, m.group(1), code[m.end():], problems)
            for lineno, line in enumerate(text.split("\n"), 1):
                row = re.match(r"^\|\s*`([a-z]+)\b([^`]*)`", line)
                if row and row.group(1) in self.contract:
                    self.check_segment(rel, lineno, row.group(1), row.group(2), problems)
                for flag in FLAG_RE.findall(line):
                    if flag not in self.all_flags and flag not in OTHER_TOOL_FLAGS:
                        problems.append("%s:%d mentions %s, which is not an hp.py flag" % (rel, lineno, flag))
        self.assertGreater(mentions, 10, "expected SKILL.md and references to show hp.py commands")
        self.assertEqual(problems, [], "\n" + "\n".join(problems))

    def test_skill_uses_every_command_it_documents(self):
        skill = read(os.path.join(SKILL, "SKILL.md"))
        for command in self.contract:
            self.assertRegex(skill, r"`%s\b" % command, "SKILL.md command reference lacks %s" % command)

    def test_scanner_catches_a_bad_flag(self):
        problems = []
        self.check_segment("x.md", 1, "render", "<RUN> --fast", problems)
        self.check_segment("x.md", 2, "synthesize", "<RUN> --mode turbo", problems)
        self.check_segment("x.md", 3, "launch", "<RUN>", problems)
        self.assertEqual(len(problems), 3)
        ok = []
        self.check_segment("x.md", 4, "init", '--jd-source url:https://example.com/job --stage student', ok)
        self.check_segment("x.md", 5, "render", "<RUN> --pdf-engine chrome|soffice|builtin", ok)
        self.assertEqual(ok, [])

    def test_only_code_counts_as_a_command_mention(self):
        sample = ("Prose about every hp.py command is ignored.\n"
                  "Run `python3 S/scripts/hp.py launch <RUN>` now.\n"
                  "```\npython3 S/scripts/hp.py render <RUN> --fast\n```\n")
        segments = list(self.code_segments(sample))
        self.assertEqual(segments, [(2, "python3 S/scripts/hp.py launch <RUN>"),
                                    (4, "python3 S/scripts/hp.py render <RUN> --fast")])


if __name__ == "__main__":
    unittest.main()
