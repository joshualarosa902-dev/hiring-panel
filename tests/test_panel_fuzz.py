"""Deterministic fuzzing: random type swaps anywhere in the reviews, screening.json and merges.json must
never produce a traceback from synthesis or validation. Fictional fixture data only."""
import copy
import json
import os
import random
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "plugins", "hiring-panel", "skills", "hiring-panel", "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from hp.panel.common import PanelError  # noqa: E402
from hp.panel.ledger import apply_overrides, build_ledger  # noqa: E402
from hp.panel.synth import check_review, synthesize  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "panel", "run_basic")
REVIEWERS = ["screening", "hiring_manager", "recruiter", "competitor", "ceo", "teammate", "skeptic"]
JUNK = [None, True, 0, -1, 3.5, "", "x" * 300, "R1", "A:KW-001", "Q1", [], [None], ["R1"], {}, {"a": [1]},
        [[["deep"]]], {"anchor": ["R1"], "quote": {"q": 1}}, "\u0000\u202e", 10 ** 30]


def _paths(node, prefix=()):
    """Every path (tuple of keys/indexes) inside a JSON value."""
    out = [prefix]
    if isinstance(node, dict):
        for k in node:
            out.extend(_paths(node[k], prefix + (k,)))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out.extend(_paths(v, prefix + (i,)))
    return out


def _set(node, path, value):
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value


def _mutate(data, rng, n):
    data = copy.deepcopy(data)
    for _ in range(n):
        paths = [p for p in _paths(data) if p]
        if not paths:
            break
        _set(data, rng.choice(paths), copy.deepcopy(rng.choice(JUNK)))
    return data


class FuzzTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hp-panel-fuzz-")
        self.run_dir = os.path.join(self.tmp, "run")
        shutil.copytree(FIXTURE, self.run_dir)
        self.reviews = {}
        for rid in REVIEWERS:
            with open(os.path.join(self.run_dir, "work", "reviews", rid + ".json"), encoding="utf-8") as f:
                self.reviews[rid] = json.load(f)
        with open(os.path.join(self.run_dir, "work", "screening", "before", "screening.json"), encoding="utf-8") as f:
            self.screening = json.load(f)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _write(self, rel, data):
        with open(os.path.join(self.run_dir, "work", rel), "w", encoding="utf-8") as f:
            json.dump(data, f)

    def test_random_type_swaps_never_crash(self):
        rng = random.Random(20261020)
        for round_ in range(60):
            for rid in REVIEWERS:
                self._write(os.path.join("reviews", rid + ".json"), _mutate(self.reviews[rid], rng, rng.randint(1, 6)))
            self._write(os.path.join("screening", "before", "screening.json"),
                        _mutate(self.screening, rng, rng.randint(0, 4)))
            merges = rng.choice([[["I1", "I2"]], [[{"reviewer": ["x"], "id": {}}]], {"merges": 5}, [["I3", 7]]])
            self._write("merges.json", merges)
            for mode in ("parallel", "lite"):
                res = synthesize(self.run_dir, mode, merges_path=os.path.join(self.run_dir, "work", "merges.json"))
                self.assertLessEqual(len(res["questions_for_candidate"]), 6)
                self.assertLessEqual(len(res["interview_prep"]), 6)
                json.dumps(res)
            for rid in REVIEWERS:
                out = check_review(self.run_dir, os.path.join(self.run_dir, "work", "reviews", rid + ".json"))
                self.assertIn("ok", out, (round_, rid))

    def test_ledger_fuzz(self):
        rng = random.Random(7)
        with open(os.path.join(self.run_dir, "work", "inputs", "ledger.json"), encoding="utf-8") as f:
            ledger = json.load(f)
        for _ in range(80):
            self._write(os.path.join("inputs", "ledger.json"), _mutate(ledger, rng, rng.randint(1, 4)))
            try:
                synthesize(self.run_dir, "parallel")
            except PanelError:
                pass    # an unusable ledger is a clear, catchable error by contract

    def test_build_ledger_and_overrides_fuzz(self):
        rng = random.Random(11)
        blocks = self.screening["inputs"]["job_description"]["blocks"]
        for _ in range(80):
            led = build_ledger(rng.choice(JUNK + ["a\nb"]), _mutate({"b": blocks}, rng, 3)["b"], rng.choice(JUNK))
            self.assertIn("jd_items", led)
            try:
                apply_overrides(led, rng.choice([{"J1": "must"}, {"J1": ["x"]}, ["J1"], 5, {5: "nice"}, None]))
            except ValueError:
                pass


    def test_student_text_helpers_on_hostile_strings(self):
        """Id scrubbing, sentence splitting and heading collapse stay fast and never raise."""
        import time
        from hp.panel.common import SourceContext
        from hp.panel.ledger import collapse_letter_spacing, split_sentences
        from hp.panel.synth import keyword_question, scrub_ids
        with open(os.path.join(self.run_dir, "work", "inputs", "ledger.json"), encoding="utf-8") as f:
            ctx = SourceContext(json.load(f), self.screening)
        hostile = ["(" + ", ".join("R%d" % (i % 17 + 1) for i in range(200)), "R1 " * 300, "(R1" + " ," * 300,
                   "A:PARSE-006" * 50, "degree in " + "x, " * 200, ". " * 400, "a. " * 400, "E " * 400,
                   "Requirements: " + "A. " * 300, "\u0000R1\u202e(J2)"]
        for h in hostile:
            start = time.time()
            self.assertIsInstance(scrub_ids(h[:420], ctx), str)
            self.assertEqual(" ".join(split_sentences(h)).split(), h.split())
            collapse_letter_spacing(h)
            keyword_question(ctx, "KW-001", [{"term": h[:60], "jd_quote": h[:400], "kind": "hard"}])
            self.assertLess(time.time() - start, 1.0, h[:30])
        for junk in JUNK:
            self.assertEqual(scrub_ids(junk, ctx), junk) if not isinstance(junk, str) else scrub_ids(junk, ctx)
        self.assertIsNone(keyword_question(ctx, "KW-001", [{"term": None}, {}, {"kind": 5}]))


if __name__ == "__main__":
    unittest.main()
