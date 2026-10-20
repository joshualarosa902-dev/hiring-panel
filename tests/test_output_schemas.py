"""resume/report/answers schemas: well-formed, consistent with the fictional fixtures, and strict where the
contract is strict. Uses a tiny draft-07 subset validator (standard library only)."""
import copy
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SKILL = os.path.join(ROOT, "plugins", "hiring-panel", "skills", "hiring-panel")
SCRIPTS = os.path.join(SKILL, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
FIX = os.path.join(HERE, "fixtures", "output")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


SCHEMAS = {n: load(os.path.join(SKILL, "schemas", "%s.schema.json" % n)) for n in ("resume", "report", "answers")}


def _type_ok(value, t):
    if t == "null":
        return value is None
    if t == "boolean":
        return isinstance(value, bool)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "string":
        return isinstance(value, str)
    if t == "array":
        return isinstance(value, list)
    if t == "object":
        return isinstance(value, dict)
    raise AssertionError("unknown type " + t)


def validate(value, schema, root=None, path="$"):
    """Return a list of error strings (empty when valid). Supports the subset our schemas use."""
    root = root or schema
    errs = []
    if "$ref" in schema:
        node = root
        for part in schema["$ref"].lstrip("#/").split("/"):
            node = node[part]
        return validate(value, node, root, path)
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_type_ok(value, t) for t in types):
            return ["%s: expected %s" % (path, types)]
    if "const" in schema and value != schema["const"]:
        errs.append("%s: expected const %r" % (path, schema["const"]))
    if "enum" in schema and value not in schema["enum"]:
        errs.append("%s: %r not in enum" % (path, value))
    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errs.append("%s: %r does not match %s" % (path, value, schema["pattern"]))
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", 10 ** 9):
            errs.append("%s: bad length" % path)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < schema.get("minimum", -10 ** 18) or value > schema.get("maximum", 10 ** 18):
            errs.append("%s: out of range" % path)
        if "multipleOf" in schema and value % schema["multipleOf"]:
            errs.append("%s: not a multiple of %s" % (path, schema["multipleOf"]))
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", 10 ** 9):
            errs.append("%s: bad item count" % path)
        if "items" in schema:
            for i, v in enumerate(value):
                errs += validate(v, schema["items"], root, "%s[%d]" % (path, i))
    if isinstance(value, dict):
        for req in schema.get("required", []):
            if req not in value:
                errs.append("%s: missing %s" % (path, req))
        props = schema.get("properties", {})
        for k, v in value.items():
            if k in props:
                errs += validate(v, props[k], root, path + "." + k)
            else:
                extra = schema.get("additionalProperties", True)
                if extra is False:
                    errs.append("%s: unexpected key %s" % (path, k))
                elif isinstance(extra, dict):
                    errs += validate(v, extra, root, path + "." + k)
    for sub in schema.get("allOf", []):
        errs += validate(value, sub, root, path)
    if "anyOf" in schema and not any(not validate(value, s, root, path) for s in schema["anyOf"]):
        errs.append("%s: matches no anyOf branch" % path)
    if "oneOf" in schema and sum(1 for s in schema["oneOf"] if not validate(value, s, root, path)) != 1:
        errs.append("%s: must match exactly one oneOf branch" % path)
    if "if" in schema:
        branch = schema.get("then") if not validate(value, schema["if"], root, path) else schema.get("else")
        if branch:
            errs += validate(value, branch, root, path)
    return errs


class TestSchemas(unittest.TestCase):
    def test_schemas_are_draft07_json(self):
        for name, s in SCHEMAS.items():
            self.assertEqual(s["$schema"], "http://json-schema.org/draft-07/schema#", name)
            self.assertIn("title", s)

    def test_fixtures_validate(self):
        cases = [("resume", "sample/resume.json"), ("answers", "sample/answers.json"),
                 ("report", "sample/report.json"), ("report", "sample/report_panel.json")]
        # stress/report_stress.json is deliberately over the contract's length limits (renderer robustness)
        for schema, rel in cases:
            errs = validate(load(os.path.join(FIX, rel)), SCHEMAS[schema])
            self.assertEqual(errs, [], rel)

    def test_resume_schema_rejects_jd_refs_and_missing_fallback(self):
        r = load(os.path.join(FIX, "sample", "resume.json"))
        bad = copy.deepcopy(r)
        bad["sections"][1]["items"][0]["bullets"][1]["evidence"][0]["ref"] = "J12"
        self.assertTrue(validate(bad, SCHEMAS["resume"]))
        bad = copy.deepcopy(r)
        bad["sections"][1]["items"][0]["bullets"][0].pop("textIfUnknown")
        self.assertTrue(validate(bad, SCHEMAS["resume"]))
        bad = copy.deepcopy(r)
        bad["sections"][1]["items"][0]["bullets"][1]["evidence"][0]["src"] = "jd"
        self.assertTrue(validate(bad, SCHEMAS["resume"]))
        bad = copy.deepcopy(r)
        bad["meta"]["addressed"][0]["status"] = "done"
        self.assertTrue(validate(bad, SCHEMAS["resume"]))
        bad = copy.deepcopy(r)
        bad["meta"]["cuts"][0] = {"ref": "R19"}
        self.assertTrue(validate(bad, SCHEMAS["resume"]))

    def test_answers_schema_rules(self):
        a = load(os.path.join(FIX, "sample", "answers.json"))
        bad = copy.deepcopy(a)
        bad["answers"][0]["items"] = None            # keywords need items
        self.assertTrue(validate(bad, SCHEMAS["answers"]))
        bad = copy.deepcopy(a)
        bad["answers"][1]["items"] = []               # other kinds have items null
        self.assertTrue(validate(bad, SCHEMAS["answers"]))
        bad = copy.deepcopy(a)
        bad["answers"] = bad["answers"] * 2           # at most 8 questions
        self.assertTrue(validate(bad, SCHEMAS["answers"]))
        bad = copy.deepcopy(a)
        bad["answers"][0]["items"][0]["answer"] = "maybe"
        self.assertTrue(validate(bad, SCHEMAS["answers"]))

    def test_report_schema_rules(self):
        r = load(os.path.join(FIX, "sample", "report.json"))
        bad = copy.deepcopy(r)
        bad["screening"]["before"]["overall"] = 62    # multiples of 5 only
        self.assertTrue(validate(bad, SCHEMAS["report"]))
        bad = copy.deepcopy(r)
        bad["screening"]["label"] = "ATS score"
        self.assertTrue(validate(bad, SCHEMAS["report"]))
        bad = copy.deepcopy(r)
        bad["panel"][0]["score"] = 7                  # no per-reviewer numbers
        self.assertTrue(validate(bad, SCHEMAS["report"]))
        bad = copy.deepcopy(r)
        bad["weaknesses"][0]["severity"] = "high"     # one severity scale
        self.assertTrue(validate(bad, SCHEMAS["report"]))

    def test_validator_sanity(self):
        self.assertEqual(validate(5, {"type": "integer", "multipleOf": 5}), [])
        self.assertTrue(validate(True, {"type": "integer"}))
        self.assertTrue(validate({"a": 1}, {"type": "object", "additionalProperties": False}))


if __name__ == "__main__":
    unittest.main()
