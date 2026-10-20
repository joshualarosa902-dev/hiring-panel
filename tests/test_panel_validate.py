"""Tests for review validation (hp.panel.synth.validate_review / check_review) and the review schema.
Fictional data only."""
import copy
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.join(os.path.dirname(HERE), "plugins", "hiring-panel", "skills", "hiring-panel")
SCRIPTS = os.path.join(SKILL, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from hp.panel import schema_lite  # noqa: E402
from hp.panel.synth import check_review, validate_review  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "panel", "run_basic")
REVIEWERS = ["screening", "hiring_manager", "recruiter", "competitor", "ceo", "teammate", "skeptic"]


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def example_review():
    with open(os.path.join(SKILL, "references", "reviewers", "_output-format.md"), encoding="utf-8") as f:
        doc = f.read()
    blocks = re.findall(r"```json\n(.*?)\n```", doc, re.S)
    return json.loads(blocks[-1])


class SchemaValidityTest(unittest.TestCase):
    """Every fixture review and the documented example are valid against review.schema.json."""

    @classmethod
    def setUpClass(cls):
        cls.schema = _load(os.path.join(SKILL, "schemas", "review.schema.json"))

    def test_schema_uses_only_supported_keywords(self):
        self.assertEqual(schema_lite.unsupported_keywords(self.schema), [])

    def test_fixture_reviews_are_schema_valid(self):
        for rid in REVIEWERS:
            data = _load(os.path.join(FIXTURE, "work", "reviews", rid + ".json"))
            self.assertEqual(schema_lite.validate(data, self.schema), [], rid)

    def test_output_format_example_is_schema_valid(self):
        self.assertEqual(schema_lite.validate(example_review(), self.schema), [])

    def test_schema_rejects_common_mistakes(self):
        good = example_review()
        cases = {
            "missing advance": lambda r: r.pop("advance"),
            "bad advance": lambda r: r.__setitem__("advance", "maybe"),
            "q anchor": lambda r: r["findings"][0]["evidence"].__setitem__(0, {"anchor": "Q1", "quote": "x"}),
            "r anchor without quote": lambda r: r["findings"][0]["evidence"].__setitem__(0, {"anchor": "R3"}),
            "keyword gap without terms": lambda r: r["findings"][0].__setitem__("category", "KEYWORD_GAP"),
            "wrong dimension id": lambda r: r["dimension_scores"][0].__setitem__("dimension_id", "S1_parse_safety"),
            "four dimensions": lambda r: r["dimension_scores"].pop(),
            "extra field": lambda r: r.__setitem__("score", 87),
            "bad lens_data": lambda r: r["lens_data"].pop("biggest_doubt"),
            "eight findings": lambda r: r["findings"].extend([r["findings"][0]] * (8 - len(r["findings"]))),
            "title too long": lambda r: r["findings"][0].__setitem__("title", "x" * 91),
        }
        for name, mutate in cases.items():
            r = copy.deepcopy(good)
            mutate(r)
            self.assertNotEqual(schema_lite.validate(r, self.schema), [], name)

    def test_empty_strengths_and_findings_allowed(self):
        r = example_review()
        r["strengths"] = []
        r["findings"] = []
        self.assertEqual(schema_lite.validate(r, self.schema), [])

    def test_a_anchor_quote_optional(self):
        r = example_review()
        r["findings"][0]["evidence"].append({"anchor": "A:KW-001"})
        r["findings"][0]["evidence"].append({"anchor": "A:PARSE-009b"})
        self.assertEqual(schema_lite.validate(r, self.schema), [])


class CheckReviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hp-panel-")
        self.run_dir = os.path.join(self.tmp, "run")
        shutil.copytree(FIXTURE, self.run_dir)
        self.reviews = os.path.join(self.run_dir, "work", "reviews")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def write(self, name, data):
        path = os.path.join(self.reviews, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(data if isinstance(data, str) else json.dumps(data))
        return path

    def test_example_review_passes(self):
        path = self.write("hiring_manager.json", example_review())
        ok, errors = validate_review(self.run_dir, path)
        self.assertTrue(ok, errors)
        self.assertEqual(errors, [])

    def test_fixture_reviews(self):
        expected_ok = {"screening": False, "hiring_manager": True, "recruiter": True, "competitor": True,
                       "ceo": False, "teammate": False, "skeptic": False}
        for rid, want in expected_ok.items():
            res = check_review(self.run_dir, os.path.join(self.reviews, rid + ".json"))
            self.assertEqual(res["ok"], want, (rid, res["errors"]))
            self.assertTrue(res["usable"], rid)      # semantic problems never make a review unusable

    def test_error_messages_tell_the_reviewer_what_to_fix(self):
        res = check_review(self.run_dir, os.path.join(self.reviews, "skeptic.json"))
        self.assertTrue(any("Led a team of 12 analysts" in e and "word for word" in e for e in res["errors"]))
        res = check_review(self.run_dir, os.path.join(self.reviews, "screening.json"))
        self.assertTrue(any("Python" in e for e in res["errors"]))
        self.assertTrue(any("A:PARSE-099" in e for e in res["errors"]))
        res = check_review(self.run_dir, os.path.join(self.reviews, "recruiter.json"))
        self.assertTrue(any("R1" in w and "R3" in w for w in res["warnings"]))
        self.assertEqual(res["repairs"][0]["to"], "R1")

    def test_relative_path_resolves_inside_reviews(self):
        ok, errors = validate_review(self.run_dir, "hiring_manager.json")
        self.assertTrue(ok, errors)

    def test_reviewer_id_must_match_file(self):
        path = self.write("ceo.json", example_review())      # a hiring_manager review saved as ceo.json
        ok, errors = validate_review(self.run_dir, path)
        self.assertFalse(ok)
        self.assertTrue(any("reviews/ceo.json" in e for e in errors))
        self.assertFalse(check_review(self.run_dir, path)["usable"])

    def test_take_over_twenty_words(self):
        r = example_review()
        r["one_line_take"] = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen " \
                             "fifteen sixteen seventeen eighteen nineteen twenty twentyone"
        ok, errors = validate_review(self.run_dir, self.write("hiring_manager.json", r))
        self.assertFalse(ok)
        self.assertTrue(any("one_line_take" in e for e in errors))

    def test_general_review_bans_keyword_categories(self):
        led_path = os.path.join(self.run_dir, "work", "inputs", "ledger.json")
        led = _load(led_path)
        led["target"]["general_review"] = True
        with open(led_path, "w") as f:
            json.dump(led, f)
        ok, errors = validate_review(self.run_dir, os.path.join(self.reviews, "hiring_manager.json"))
        self.assertFalse(ok)
        self.assertTrue(any("general review" in e for e in errors))

    def test_out_of_lens_flag_warning(self):
        r = example_review()
        r["findings"][0]["out_of_lens"] = True        # REQUIREMENT_UNPROVEN is inside the HM lens
        res = check_review(self.run_dir, self.write("hiring_manager.json", r))
        self.assertTrue(res["ok"])
        self.assertTrue(any("inside your lens" in w for w in res["warnings"]))

    def test_ids_in_student_text_warn_but_do_not_fail(self):
        """A11: ids in text a student reads draw a warning (synthesis cleans leftovers); no retry is spent."""
        r = example_review()
        r["findings"][0]["fix"]["suggestion"] = "Name SQL in R14 if you used it there."
        r["findings"][0]["title"] = "SQL (J9) is required and never shown"
        r["one_line_take"] = "Show SQL; the dashboard in R14 already helps."
        res = check_review(self.run_dir, self.write("hiring_manager.json", r))
        self.assertTrue(res["ok"], res["errors"])
        joined = " ".join(res["warnings"])
        for where in ("one_line_take", "title", "suggestion"):
            self.assertIn(where, joined)
        self.assertIn("quoted words", joined)
        clean = check_review(self.run_dir, self.write("hiring_manager.json", example_review()))
        self.assertFalse(any("quoted words" in w for w in clean["warnings"]))

    def test_screening_keyword_table_must_copy_brief(self):
        sc = _load(os.path.join(self.reviews, "screening.json"))
        sc["lens_data"]["keyword_table"][1]["found"] = False
        sc["lens_data"]["keyword_table"].append({"term": "Kubernetes", "importance": "required", "found": False,
                                                 "match_type": "none", "evidence_level": "none",
                                                 "resume_wording": None, "jd_anchor": None, "resume_anchors": [],
                                                 "truthful_fix": "do_not_add"})
        res = check_review(self.run_dir, self.write("screening.json", sc))
        self.assertTrue(any("copy it, do not recompute" in w for w in res["warnings"]))
        self.assertTrue(any("Kubernetes" in w for w in res["warnings"]))

    def test_hostile_files(self):
        cases = {"garbage.json": "{nope", "list.json": "[1,2]", "deep.json": "[" * 40000 + "]" * 40000,
                 "binary.json": "\udcff"}
        for name, content in cases.items():
            path = os.path.join(self.reviews, name)
            if name == "binary.json":
                with open(path, "wb") as f:
                    f.write(b"\xff\xfe\x00\x01")
            else:
                self.write(name, content)
            ok, errors = validate_review(self.run_dir, path)
            self.assertFalse(ok, name)
            self.assertTrue(errors, name)
        ok, errors = validate_review(self.run_dir, os.path.join(self.reviews, "missing.json"))
        self.assertFalse(ok)

    def test_missing_ledger(self):
        os.remove(os.path.join(self.run_dir, "work", "inputs", "ledger.json"))
        ok, errors = validate_review(self.run_dir, os.path.join(self.reviews, "hiring_manager.json"))
        self.assertFalse(ok)
        self.assertIn("ledger.json", errors[0])


class SchemaLiteTest(unittest.TestCase):
    """The stdlib validator itself."""

    def test_basics(self):
        schema = {"type": "object", "required": ["a"], "additionalProperties": False,
                  "properties": {"a": {"type": "integer", "minimum": 1, "maximum": 3},
                                 "b": {"type": ["string", "null"], "pattern": "^x", "maxLength": 3},
                                 "c": {"type": "array", "items": {"enum": [1, 2]}, "minItems": 1, "uniqueItems": True}}}
        self.assertEqual(schema_lite.validate({"a": 2, "b": None, "c": [1, 2]}, schema), [])
        self.assertTrue(schema_lite.validate({"a": True}, schema))           # booleans are not integers
        self.assertTrue(schema_lite.validate({"a": 4}, schema))
        self.assertTrue(schema_lite.validate({"a": 1, "b": "yxx"}, schema))
        self.assertTrue(schema_lite.validate({"a": 1, "b": "xxxx"}, schema))
        self.assertTrue(schema_lite.validate({"a": 1, "c": [1, 1]}, schema))
        self.assertTrue(schema_lite.validate({"a": 1, "c": []}, schema))
        self.assertTrue(schema_lite.validate({"a": 1, "d": 0}, schema))
        self.assertTrue(schema_lite.validate([], schema))

    def test_refs_conditionals_and_combinators(self):
        schema = {"$defs": {"pos": {"type": "number", "exclusiveMinimum": 0}},
                  "type": "object",
                  "properties": {"kind": {"enum": ["a", "b"]}, "n": {"$ref": "#/$defs/pos"}},
                  "if": {"properties": {"kind": {"const": "a"}}},
                  "then": {"required": ["n"]},
                  "else": {"not": {"required": ["n"]}},
                  "anyOf": [{"required": ["kind"]}, {"required": ["n"]}]}
        self.assertEqual(schema_lite.validate({"kind": "a", "n": 1}, schema), [])
        self.assertTrue(schema_lite.validate({"kind": "a"}, schema))
        self.assertTrue(schema_lite.validate({"kind": "b", "n": 1}, schema))
        self.assertTrue(schema_lite.validate({"kind": "a", "n": 0}, schema))
        self.assertTrue(schema_lite.validate({}, schema))
        self.assertEqual(schema_lite.validate({"kind": "b"}, schema), [])
        one = {"oneOf": [{"type": "string"}, {"maxLength": 2}]}
        self.assertEqual(schema_lite.validate(5, one), [])
        self.assertTrue(schema_lite.validate("ab", one))                       # matches both

    def test_bad_ref_and_unsupported_keywords(self):
        self.assertTrue(schema_lite.validate(1, {"$ref": "#/$defs/missing"}))
        self.assertEqual(schema_lite.unsupported_keywords({"type": "object", "properties": {"format": {"format": "x"}}}),
                         ["format"])
        self.assertEqual(schema_lite.validate("x", {"pattern": "("}),
                         ["$: schema pattern is not a valid regular expression"])

    def test_error_cap(self):
        schema = {"type": "array", "items": {"type": "string"}}
        self.assertEqual(len(schema_lite.validate(list(range(100)), schema, max_errors=10)), 10)


if __name__ == "__main__":
    unittest.main()
