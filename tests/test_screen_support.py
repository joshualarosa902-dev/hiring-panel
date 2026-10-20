"""Shared helpers for the hp.screen tests (no test cases here).

- puts the skill's scripts folder first on sys.path,
- builds Document dicts (ARCHITECTURE 5.2) straight from text lines,
- runs the screening with the small fictional dictionary in tests/fixtures/screen/data,
- validates output with a tiny standard-library JSON Schema checker (the subset our schema uses).
All people, schools and companies in the fixtures are fictional.
"""
import copy
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPTS = os.path.join(REPO, "plugins", "hiring-panel", "skills", "hiring-panel", "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
SCHEMA_PATH = os.path.join(REPO, "plugins", "hiring-panel", "skills", "hiring-panel", "schemas",
                           "screening.schema.json")
FIX = os.path.join(HERE, "fixtures", "screen")
DATA = os.path.join(FIX, "data")
AS_OF = "2026-10-20"

from hp.screen import run_screening  # noqa: E402

_SIGNALS = {
    "encrypted": False, "text_layer": None, "image_only": False, "garbled": False,
    "too_large": False, "legacy_format": None,
    "images": {"count": 0, "large": 0, "charts": 0, "smartart": 0, "small_icons": 0},
    "tables": {"count": 0, "nested": 0, "holds_experience": False},
    "text_boxes": {"count": 0, "chars": 0, "has_contact": False, "has_heading": False},
    "columns": {"docx_multi_column": False, "pdf_check": "unavailable", "pdf_gutter_pages": []},
    "header_footer": {"has_text": False, "has_contact": False},
    "hidden_text": {"vanish": 0, "white": 0, "tiny": 0, "pdf_invisible": 0},
    "caps_formatting": 0, "fields": {"docproperty": 0, "mergefield": 0, "ole": 0},
    "tracked_changes": 0, "comments": 0, "symbols": 0,
    "fonts": {"type0": 0, "tounicode": 0, "type3": 0},
    "design_tool": None, "private_use_chars": 0, "replacement_chars": 0,
    "letter_spaced": 0, "repeated_footer_lines": 0, "tab_merged_tokens": 0,
}


def fixture(name):
    with open(os.path.join(FIX, name), "r", encoding="utf-8") as f:
        return f.read()


def deep_update(base, upd):
    for k, v in upd.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_update(base[k], v)
        else:
            base[k] = v
    return base


def make_doc(text, fmt="txt", method="text", header_footer=None, signals=None, where=None, **extra):
    """A Document dict built from text lines. `where` maps 0-based line index -> body|table|textbox."""
    lines = []
    for i, t in enumerate(text.splitlines()):
        lines.append({"text": t, "style": None, "list": False, "bold": False,
                      "where": (where or {}).get(i, "body")})
    doc = {"format": fmt, "sha256": "0" * 64, "bytes": len(text.encode("utf-8")), "pages": None,
           "producer": None, "creator": None, "method": method, "lines": lines,
           "header_footer": [{"where": w, "text": t} for w, t in (header_footer or [])],
           "text_chars": len(text), "words": len(text.split()), "signals": copy.deepcopy(_SIGNALS),
           "warnings": [], "errors": []}
    if signals:
        deep_update(doc["signals"], signals)
    doc.update(extra)
    return doc


def screen(doc_or_text, jd="", **kw):
    doc = make_doc(doc_or_text) if isinstance(doc_or_text, str) else doc_or_text
    kw.setdefault("as_of", AS_OF)
    kw.setdefault("data_dir", DATA)
    return run_screening(doc, jd, **kw)


def issue_ids(result):
    return [i["id"] for i in result["issues"]]


def issue(result, iid):
    for i in result["issues"]:
        if i["id"] == iid:
            return i
    return None


def all_terms(result):
    kw = result["keywords"]
    return kw["required"] + kw["preferred"] + kw["other"]


def term(result, name):
    for t in all_terms(result):
        if t["term"].casefold() == name.casefold() or t["canonical"].casefold() == name.casefold():
            return t
    return None


def load_schema():
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- tiny JSON Schema validator
_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool}


def _is_type(v, t):
    if t == "null":
        return v is None
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    return isinstance(v, _TYPES[t])


def validate(inst, schema, root=None, path="$"):
    """Return a list of error strings. Supports: $ref (#/$defs/...), type, enum, const, required,
    properties, additionalProperties, items, minItems, maxItems, minimum, maximum, multipleOf,
    minLength, maxLength, pattern."""
    root = root if root is not None else schema
    errs = []
    if "$ref" in schema:
        ref = schema["$ref"]
        assert ref.startswith("#/"), ref
        target = root
        for part in ref[2:].split("/"):
            target = target[part]
        return validate(inst, target, root, path)
    if "type" in schema:
        ts = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_is_type(inst, t) for t in ts):
            return ["%s: expected %s, got %r" % (path, ts, type(inst).__name__)]
    if "const" in schema and inst != schema["const"]:
        errs.append("%s: expected const %r" % (path, schema["const"]))
    if "enum" in schema and inst not in schema["enum"]:
        errs.append("%s: %r not in enum" % (path, inst))
    if isinstance(inst, dict):
        for k in schema.get("required", []):
            if k not in inst:
                errs.append("%s: missing %s" % (path, k))
        props = schema.get("properties", {})
        addl = schema.get("additionalProperties", True)
        for k, v in inst.items():
            if k in props:
                errs.extend(validate(v, props[k], root, "%s.%s" % (path, k)))
            elif addl is False:
                errs.append("%s: unexpected key %s" % (path, k))
            elif isinstance(addl, dict):
                errs.extend(validate(v, addl, root, "%s.%s" % (path, k)))
    if isinstance(inst, list):
        if "minItems" in schema and len(inst) < schema["minItems"]:
            errs.append("%s: fewer than %d items" % (path, schema["minItems"]))
        if "maxItems" in schema and len(inst) > schema["maxItems"]:
            errs.append("%s: more than %d items" % (path, schema["maxItems"]))
        if "items" in schema:
            for i, v in enumerate(inst):
                errs.extend(validate(v, schema["items"], root, "%s[%d]" % (path, i)))
    if isinstance(inst, (int, float)) and not isinstance(inst, bool):
        if "minimum" in schema and inst < schema["minimum"]:
            errs.append("%s: below minimum" % path)
        if "maximum" in schema and inst > schema["maximum"]:
            errs.append("%s: above maximum" % path)
        if "multipleOf" in schema and inst % schema["multipleOf"] != 0:
            errs.append("%s: %r not a multiple of %r" % (path, inst, schema["multipleOf"]))
    if isinstance(inst, str):
        if "minLength" in schema and len(inst) < schema["minLength"]:
            errs.append("%s: shorter than %d" % (path, schema["minLength"]))
        if "maxLength" in schema and len(inst) > schema["maxLength"]:
            errs.append("%s: longer than %d (%d)" % (path, schema["maxLength"], len(inst)))
        if "pattern" in schema and not re.search(schema["pattern"], inst):
            errs.append("%s: %r does not match %s" % (path, inst, schema["pattern"]))
    return errs
