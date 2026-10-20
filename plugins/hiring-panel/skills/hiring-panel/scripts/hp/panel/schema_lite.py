"""A small JSON Schema validator (standard library only) for the subset our schemas use.

Supported keywords: type, enum, const, properties, required, additionalProperties, patternProperties,
items (single schema), minItems, maxItems, uniqueItems, minLength, maxLength, pattern, minimum,
maximum, exclusiveMinimum, exclusiveMaximum, multipleOf, $ref (local "#/..." pointers only), $defs,
definitions, allOf, anyOf, oneOf, not, if/then/else. Annotation keywords ($schema, $id, $comment,
title, description, default, examples) are ignored.

`validate(instance, schema)` returns a list of "path: message" strings (empty when valid). It never
raises on hostile instances; an unsupported keyword in the SCHEMA is reported by
`unsupported_keywords(schema)` so tests can prove nothing is silently skipped.
"""
import json
import re

ANNOTATIONS = {"$schema", "$id", "$comment", "title", "description", "default", "examples", "$defs",
               "definitions"}
SUPPORTED = ANNOTATIONS | {
    "type", "enum", "const", "properties", "required", "additionalProperties", "patternProperties",
    "items", "minItems", "maxItems", "uniqueItems", "minLength", "maxLength", "pattern", "minimum",
    "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "$ref", "allOf", "anyOf", "oneOf",
    "not", "if", "then", "else",
}
_MAX_DEPTH = 64
_regex_cache = {}


def _regex(p):
    r = _regex_cache.get(p)
    if r is None:
        try:
            r = re.compile(p)
        except re.error:
            r = False
        _regex_cache[p] = r
    return r


def _is_type(value, t):
    if t == "object":
        return isinstance(value, dict)
    if t == "array":
        return isinstance(value, list)
    if t == "string":
        return isinstance(value, str)
    if t == "boolean":
        return isinstance(value, bool)
    if t == "null":
        return value is None
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool) or (
            isinstance(value, float) and value.is_integer())
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return False


def _resolve(root, ref):
    if not isinstance(ref, str) or not ref.startswith("#"):
        return None
    node = root
    for part in ref[1:].split("/"):
        if part == "":
            continue
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _canon(v):
    try:
        return json.dumps(v, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        return repr(v)


def _fmt(v, n=60):
    s = _canon(v)
    return s if len(s) <= n else s[: n - 3] + "..."


class _Ctx(object):
    def __init__(self, root, max_errors):
        self.root = root
        self.max_errors = max_errors
        self.errors = []

    def add(self, path, msg):
        if len(self.errors) < self.max_errors:
            self.errors.append("{}: {}".format(path, msg))

    @property
    def full(self):
        return len(self.errors) >= self.max_errors


def _sub_errors(ctx, inst, schema, path, depth):
    """Validate into a scratch context and return its errors (used by anyOf/oneOf/not/if)."""
    sub = _Ctx(ctx.root, 20)
    _validate(sub, inst, schema, path, depth)
    return sub.errors


def _validate(ctx, inst, schema, path, depth):
    if ctx.full:
        return
    if depth > _MAX_DEPTH:
        ctx.add(path, "schema nesting too deep")
        return
    if schema is True or schema == {}:
        return
    if schema is False:
        ctx.add(path, "not allowed here")
        return
    if not isinstance(schema, dict):
        return

    if "$ref" in schema:
        target = _resolve(ctx.root, schema["$ref"])
        if target is None:
            ctx.add(path, "schema reference {} not found".format(schema["$ref"]))
        else:
            _validate(ctx, inst, target, path, depth + 1)

    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_is_type(inst, t) for t in types):
            ctx.add(path, "expected {}, got {}".format(" or ".join(types), _type_name(inst)))
            return
    if "const" in schema and _canon(inst) != _canon(schema["const"]):
        ctx.add(path, "must be {}".format(_fmt(schema["const"])))
    if "enum" in schema and isinstance(schema["enum"], list):
        if _canon(inst) not in {_canon(e) for e in schema["enum"]}:
            ctx.add(path, "must be one of {}".format(", ".join(_fmt(e, 30) for e in schema["enum"][:30])))

    if isinstance(inst, str):
        if "minLength" in schema and len(inst) < schema["minLength"]:
            ctx.add(path, "shorter than {} characters".format(schema["minLength"]))
        if "maxLength" in schema and len(inst) > schema["maxLength"]:
            ctx.add(path, "longer than {} characters ({})".format(schema["maxLength"], len(inst)))
        if "pattern" in schema:
            rx = _regex(schema["pattern"])
            if rx is False:
                ctx.add(path, "schema pattern is not a valid regular expression")
            elif not rx.search(inst):
                ctx.add(path, "{} does not match {}".format(_fmt(inst, 40), schema["pattern"]))

    if isinstance(inst, (int, float)) and not isinstance(inst, bool):
        if "minimum" in schema and inst < schema["minimum"]:
            ctx.add(path, "below minimum {}".format(schema["minimum"]))
        if "maximum" in schema and inst > schema["maximum"]:
            ctx.add(path, "above maximum {}".format(schema["maximum"]))
        if "exclusiveMinimum" in schema and inst <= schema["exclusiveMinimum"]:
            ctx.add(path, "must be greater than {}".format(schema["exclusiveMinimum"]))
        if "exclusiveMaximum" in schema and inst >= schema["exclusiveMaximum"]:
            ctx.add(path, "must be less than {}".format(schema["exclusiveMaximum"]))
        if "multipleOf" in schema and schema["multipleOf"]:
            q = inst / schema["multipleOf"]
            if abs(q - round(q)) > 1e-9:
                ctx.add(path, "must be a multiple of {}".format(schema["multipleOf"]))

    if isinstance(inst, list):
        if "minItems" in schema and len(inst) < schema["minItems"]:
            ctx.add(path, "needs at least {} items (has {})".format(schema["minItems"], len(inst)))
        if "maxItems" in schema and len(inst) > schema["maxItems"]:
            ctx.add(path, "allows at most {} items (has {})".format(schema["maxItems"], len(inst)))
        if schema.get("uniqueItems"):
            seen = set()
            for i, v in enumerate(inst):
                c = _canon(v)
                if c in seen:
                    ctx.add("{}[{}]".format(path, i), "duplicate item")
                    break
                seen.add(c)
        if "items" in schema and isinstance(schema["items"], (dict, bool)):
            for i, v in enumerate(inst[:2000]):
                _validate(ctx, v, schema["items"], "{}[{}]".format(path, i), depth + 1)
                if ctx.full:
                    return

    if isinstance(inst, dict):
        props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        for key in schema.get("required") or []:
            if key not in inst:
                ctx.add(path, "missing required field '{}'".format(key))
        for key, sub in props.items():
            if key in inst:
                _validate(ctx, inst[key], sub, "{}.{}".format(path, key), depth + 1)
        pprops = schema.get("patternProperties") if isinstance(schema.get("patternProperties"), dict) else {}
        extra = sorted(k for k in inst if k not in props)
        for key in extra:
            matched = False
            for pat, sub in pprops.items():
                rx = _regex(pat)
                if rx and rx.search(key):
                    matched = True
                    _validate(ctx, inst[key], sub, "{}.{}".format(path, key), depth + 1)
            if matched:
                continue
            ap = schema.get("additionalProperties", True)
            if ap is False:
                ctx.add(path, "unexpected field '{}'".format(key[:60]))
            elif isinstance(ap, dict):
                _validate(ctx, inst[key], ap, "{}.{}".format(path, key), depth + 1)

    for sub in schema.get("allOf") or []:
        _validate(ctx, inst, sub, path, depth + 1)
    if isinstance(schema.get("anyOf"), list):
        branches = [_sub_errors(ctx, inst, s, path, depth + 1) for s in schema["anyOf"]]
        if not any(len(b) == 0 for b in branches):
            best = min(branches, key=len)
            ctx.add(path, "matches none of the allowed shapes ({})".format(best[0] if best else "?"))
    if isinstance(schema.get("oneOf"), list):
        ok = sum(1 for s in schema["oneOf"] if not _sub_errors(ctx, inst, s, path, depth + 1))
        if ok != 1:
            ctx.add(path, "must match exactly one allowed shape (matched {})".format(ok))
    if "not" in schema and not _sub_errors(ctx, inst, schema["not"], path, depth + 1):
        ctx.add(path, "matches a shape that is not allowed")
    if "if" in schema:
        if not _sub_errors(ctx, inst, schema["if"], path, depth + 1):
            if "then" in schema:
                _validate(ctx, inst, schema["then"], path, depth + 1)
        elif "else" in schema:
            _validate(ctx, inst, schema["else"], path, depth + 1)


def _type_name(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "object"
    return type(v).__name__


def validate(instance, schema, max_errors=50):
    """Validate `instance` against `schema`; return a list of error strings (empty when valid)."""
    ctx = _Ctx(schema, max_errors)
    try:
        _validate(ctx, instance, schema, "$", 0)
    except RecursionError:
        ctx.add("$", "instance nested too deeply")
    return ctx.errors


def unsupported_keywords(schema):
    """Return the sorted set of keywords in `schema` this validator does not implement."""
    found = set()

    def walk(node, in_props=False):
        if isinstance(node, dict):
            for k, v in node.items():
                if in_props:
                    walk(v)          # keys of 'properties' / '$defs' are names, not keywords
                    continue
                if k not in SUPPORTED:
                    found.add(k)
                walk(v, in_props=k in ("properties", "$defs", "definitions", "patternProperties"))
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(schema)
    return sorted(found)
