"""resume.json -> neutral layout blocks that every backend (docx, html, markdown, builtin PDF) renders.

One theme, one page setup and one block list keep Word, Chrome and the builtin PDF writer in step:
all of them use Arial (or its metric twins Helvetica / Liberation Sans) at the same sizes, so line
breaks and the page estimate agree across formats.

Block kinds (plain dicts, JSON-serializable):
  {"k": "name", "text"}                              candidate name
  {"k": "headline", "text"}                          optional one-liner under the name
  {"k": "contact", "parts": [{"t", "url"}]}          location | phone | email | links
  {"k": "h", "text"}                                 section heading
  {"k": "row", "left": [run], "right": str, "first": bool}
                                                     entry line; "right" is right-aligned (classic)
  {"k": "bullet", "runs": [run]}                     list item
  {"k": "para", "runs": [run]}                       plain paragraph (summary, skills line, extras)
A run is {"t": str, "b": bool?, "i": bool?, "hl": bool?}; hl marks a draft placeholder.
"""
import json
import os
import re
import unicodedata


# ----------------------------------------------------------------------------------------------
# Theme: the single place for sizes and colors. Every backend reads it.
# ----------------------------------------------------------------------------------------------
THEME = {
    "font": "Arial",            # on Windows, macOS and Google Docs; Liberation Sans on Linux
    "body_pt": 10.5,
    "name_pt": 21,
    "headline_pt": 10.5,
    "contact_pt": 9.5,
    "heading_pt": 10.5,
    "line": 1.2,                # line height multiple used by HTML and the builtin PDF
    "accent": "1F3A5F",         # deep navy: name, headings, rules
    "ink": "1A1A1A",
    "muted": "4A4A4A",
    "rule": "1F3A5F",
    "margin_in": 0.7,
    "heading_before_pt": 9,
    "heading_after_pt": 4,
    "entry_before_pt": 4.5,
    "bullet_after_pt": 1,
    "bullet_indent_pt": 14.4,   # 0.2 in
    "bullet_hanging_pt": 10.8,  # 0.15 in
}
PAGES = {"letter": (612.0, 792.0), "a4": (595.28, 841.89)}

# Fallback when hp/data/locale_norms.json is absent: en-US/en-CA use Letter, everyone else A4.
_FALLBACK_NORMS = {
    "en-US": {"paper": "letter", "pages_student": 1, "pages_experienced": 2, "word": "resume"},
    "en-CA": {"paper": "letter", "pages_student": 1, "pages_experienced": 2, "word": "resume"},
    "en-GB": {"paper": "a4", "pages_student": 1, "pages_experienced": 2, "word": "CV"},
    "en-IE": {"paper": "a4", "pages_student": 1, "pages_experienced": 2, "word": "CV"},
    "en-NZ": {"paper": "a4", "pages_student": 1, "pages_experienced": 2, "word": "CV"},
    "default": {"paper": "a4", "pages_student": 1, "pages_experienced": 2, "word": "resume"},
}

DEFAULT_LABELS = {
    "present": "Present",
    "coursework": "Relevant coursework",
    "gpa": "GPA",
    "minor": "Minor in",
    "months": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
}

PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
CONTROL_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f￾￿]")
# Arrows, dingbats, emoji and other pictographs: parsers drop or garble them.
SYMBOL_RE = re.compile("[←-⇿⌀-⏿─-➿⬀-⯿-\U0001F000-\U0001FAFF]")
FILE_STEM_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
HL_START, HL_END = "", ""   # private-use markers for draft highlights (never rendered)


class RenderError(ValueError):
    """resume.json or report.json cannot be rendered (bad input). The CLI maps it to exit code 2."""


# ----------------------------------------------------------------------------------------------
# Small text helpers
# ----------------------------------------------------------------------------------------------
def clean(s):
    """Text pasted from PDFs/Word -> NFC, no control characters, single spaces, trimmed."""
    if s is None:
        return ""
    if not isinstance(s, str):
        s = str(s)
    s = unicodedata.normalize("NFC", s)
    s = CONTROL_RE.sub("", s)
    s = s.replace("\t", " ").replace("\r", " ").replace("\n", " ")
    s = re.sub(r"[    ]{2,}", " ", s)
    return s.strip()


def as_dict(x):
    return x if isinstance(x, dict) else {}


def as_list(x):
    return x if isinstance(x, list) else []


def norm_locale(loc):
    """'en_us' / 'EN-us' -> 'en-US'. Anything odd -> 'en-US'."""
    loc = clean(loc).replace("_", "-")
    m = re.match(r"^([A-Za-z]{2,3})(?:-([A-Za-z]{2}|\d{3}))?$", loc)
    if not m:
        return "en-US"
    lang = m.group(1).lower()
    region = (m.group(2) or "").upper()
    return lang + ("-" + region if region else "")


_NORMS_CACHE = {}


def load_locale_norms():
    """Read hp/data/locale_norms.json when another module has shipped it; else the built-in table."""
    if "v" in _NORMS_CACHE:
        return _NORMS_CACHE["v"]
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "locale_norms.json")
    norms = None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data:
            norms = {k: v for k, v in data.items() if isinstance(v, dict)}
    except (OSError, ValueError):
        norms = None
    if not norms:
        norms = dict(_FALLBACK_NORMS)
    _NORMS_CACHE["v"] = norms
    return norms


def locale_norm(locale):
    norms = load_locale_norms()
    loc = norm_locale(locale)
    entry = norms.get(loc) or norms.get("default") or _FALLBACK_NORMS["default"]
    merged = dict(_FALLBACK_NORMS["en-US"] if loc in ("en-US", "en-CA") else _FALLBACK_NORMS["default"])
    merged.update(entry)
    return loc, merged


def page_setup(resume, layout=None):
    """Paper size, page target, layout and language for a resume.

    Precedence: explicit meta.pageSize > locale norms (en-US/en-CA Letter, else A4).
    Page target: explicit meta.targetPages (null = no target, e.g. academic CVs) > locale norms by
    meta.stage (student/early_career -> pages_student, experienced -> pages_experienced).
    """
    meta = as_dict(as_dict(resume).get("meta"))
    loc, norm = locale_norm(meta.get("locale") or "en-US")
    size = clean(meta.get("pageSize")).lower()
    if size not in PAGES:
        size = "letter" if clean(norm.get("paper")).lower() == "letter" else "a4"
    if "targetPages" in meta and meta.get("targetPages") is None:
        target = None
    else:
        try:
            target = int(meta.get("targetPages"))
            if target < 1 or target > 5:
                raise ValueError
        except (TypeError, ValueError):
            stage = clean(meta.get("stage")).lower()
            key = "pages_experienced" if stage == "experienced" else "pages_student"
            try:
                target = int(norm.get(key) or 1)
            except (TypeError, ValueError):
                target = 1
    lay = clean(layout or meta.get("layout") or "classic").lower()
    if lay not in ("classic", "inline"):
        lay = "classic"
    pw, ph = PAGES[size]
    return {"paper": size, "page_w": pw, "page_h": ph, "target_pages": target, "layout": lay,
            "locale": loc, "lang": loc, "word": clean(norm.get("word")) or "resume"}


def labels_for(resume):
    meta = as_dict(as_dict(resume).get("meta"))
    out = dict(DEFAULT_LABELS)
    custom = as_dict(meta.get("labels"))
    for k in ("present", "coursework", "gpa", "minor"):
        if clean(custom.get(k)):
            out[k] = clean(custom[k])
    months = custom.get("months")
    if isinstance(months, list) and len(months) == 12 and all(clean(m) for m in months):
        out["months"] = [clean(m) for m in months]
    return out


def fmt_date(d, labels):
    """'2027-05' -> 'May 2027'; '2027' stays; 'present' -> labels['present']; anything else verbatim
    (we never add precision the source did not have)."""
    d = clean(d)
    if not d:
        return ""
    if d.lower() in ("present", "current", "now"):
        return labels["present"]
    m = re.match(r"^(\d{4})-(\d{2})$", d)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            return "%s %d" % (labels["months"][mo - 1], y)
    return d


def date_range(item, labels):
    if clean(item.get("dateText")):
        return clean(item.get("dateText"))
    start, end = fmt_date(item.get("start"), labels), fmt_date(item.get("end"), labels)
    label = clean(item.get("endLabel"))
    if label and end:
        end = label + " " + end
    if start and end:
        return "%s – %s" % (start, end)
    return start or end


def runs_from_text(text):
    """'**bold** text' -> [{'t': .., 'b': True}, {'t': ..}]; draft markers become hl runs."""
    out = []
    pos = 0
    for m in BOLD_RE.finditer(text):
        if m.start() > pos:
            out.append({"t": text[pos:m.start()]})
        out.append({"t": m.group(1), "b": True})
        pos = m.end()
    if pos < len(text):
        out.append({"t": text[pos:]})
    final = []
    for r in out:
        for part in re.split("(%s[^%s]*%s)" % (HL_START, HL_END, HL_END), r["t"]):
            if not part:
                continue
            if part.startswith(HL_START):
                final.append(dict(r, t=part[1:-1], hl=True))
            else:
                final.append(dict(r, t=part))
    return [r for r in final if r["t"]]


def resolve_placeholders(text, item, placeholders, draft, warnings, where):
    """Fill {{p}} tokens in a bullet or summary.

    Final mode never prints a bracket: answered -> the student's value (hedging kept verbatim);
    declined or open -> the item's textIfUnknown (open ones add a warning); no fallback -> RenderError.
    Draft mode shows a highlighted [ADD: label] instead.
    """
    text = clean(text)
    ids = PLACEHOLDER_RE.findall(text)
    if not ids:
        return text
    unresolved = []
    for pid in ids:
        ph = placeholders.get(pid)
        if not isinstance(ph, dict):
            if draft:
                unresolved.append((pid, {}))
                continue
            raise RenderError("%s uses {{%s}} but placeholders has no '%s'" % (where, pid, pid))
        value = clean(ph.get("value"))
        if ph.get("status") == "answered" and value:
            text = re.sub(r"\{\{\s*%s\s*\}\}" % re.escape(pid), lambda _m, v=value: v, text)
        else:
            unresolved.append((pid, ph))
    if not unresolved:
        return clean(text)
    if draft:
        for pid, ph in unresolved:
            hint = clean(ph.get("label") or ph.get("kind") or "number")
            text = re.sub(r"\{\{\s*%s\s*\}\}" % re.escape(pid),
                          lambda _m, h=hint: "%s[ADD: %s]%s" % (HL_START, h, HL_END), text)
        return clean(text)
    fallback = clean(item.get("textIfUnknown"))
    if fallback and not PLACEHOLDER_RE.search(fallback):
        for pid, ph in unresolved:
            if ph.get("status") != "declined":
                warnings.append("placeholder %s is still open; used the honest no-number version of %s"
                                % (pid, where))
        return fallback
    raise RenderError("%s has unanswered placeholder(s) %s and no textIfUnknown"
                      % (where, ", ".join(p for p, _ in unresolved)))


def display_url(url):
    return re.sub(r"^(?:https?://)?(?:www\.)?", "", url, flags=re.I).rstrip("/")


def href_for(url):
    if re.match(r"^(?:https?|mailto):", url, re.I):
        return url
    return "https://" + url


def file_stem(resume, draft=False):
    """First_Last_Resume from basics.name (ASCII-folded); meta.fileStem wins when it is safe."""
    meta = as_dict(as_dict(resume).get("meta"))
    stem = clean(meta.get("fileStem"))
    if not FILE_STEM_RE.match(stem or ""):
        name = clean(as_dict(as_dict(resume).get("basics")).get("name"))
        folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
        folded = re.sub(r"[^A-Za-z0-9 _-]+", "", folded)
        folded = re.sub(r"\s+", "_", folded.strip()).strip("_-")
        stem = (folded + "_Resume") if folded else "My_Resume"
    if draft:
        stem += "_DRAFT"
    return stem


# ----------------------------------------------------------------------------------------------
# resume.json -> blocks
# ----------------------------------------------------------------------------------------------
def _row(left, right, first):
    return {"k": "row", "left": [r for r in left if r.get("t")], "right": clean(right), "first": bool(first)}


def _uniq(values):
    """Non-empty values without repeats (case-insensitive), first one wins."""
    out, seen = [], set()
    for v in values:
        key = v.casefold()
        if v and key not in seen:
            seen.add(key)
            out.append(v)
    return out


def _join_runs(parts, first_bold, rest_italic):
    """['BLS Provider', 'American Heart Association'] -> **BLS Provider** | *American Heart Association*."""
    runs = []
    for i, p in enumerate(parts):
        if i:
            runs.append({"t": " | "})
        if i == 0 and first_bold:
            runs.append({"t": p, "b": True})
        elif rest_italic:
            runs.append({"t": p, "i": True})
        else:
            runs.append({"t": p})
    return runs


def _entry_rows(item, stype, labels):
    """One or two header rows per entry (classic layout). Every identity field the entry has (name, org,
    school, role, degree/field/minor, context) is shown in every section type; nothing is dropped.

      education          **School** | Org | Name            location
                         *Degree, Field; Minor* | *Role*   dates
      name-led (projects, certifications, activities, any non-experience entry with a name)
                         **Name** | *Context* | *Org*      dates (or location)
                         *Role* | *Degree*                 location (when there are dates)
      org-led (experience, or no name)
                         **Org** | Name                    location
                         *Role* | *Context*                dates
    """
    f = dict((k, clean(item.get(k))) for k in ("org", "role", "school", "degree", "field", "minor", "name",
                                                "context"))
    dates = date_range(item, labels)
    loc = clean(item.get("location"))
    degree = ", ".join(x for x in (f["degree"], f["field"]) if x)
    if f["minor"]:
        degree = (degree + "; " if degree else "") + "%s %s" % (labels["minor"], f["minor"])
    if stype == "education" or (f["school"] and not f["org"]):
        top = _uniq([f["school"], f["org"], f["name"]])
        sub = _uniq([degree, f["role"], f["context"]])
        return _pair(top, loc, sub, dates)
    if stype == "projects" or (f["name"] and (stype != "experience" or not f["org"])):
        lead = _uniq([f["name"] or f["org"] or f["school"]])
        rest = _uniq([f["context"], f["org"], f["school"]])
        top = lead + [p for p in rest if p.casefold() not in {x.casefold() for x in lead}]
        sub = _uniq([f["role"], degree])
        if not top:
            return _pair([], loc, sub, dates)
        if sub:
            return [_row(_join_runs(top, True, True), dates or loc, True),
                    _row(_join_runs(sub, False, True), loc if dates else "", False)]
        return [_row(_join_runs(top, True, True), " | ".join(x for x in (loc, dates) if x), True)]
    top = _uniq([f["org"] or f["name"] or f["school"], f["name"], f["school"]])
    sub = _uniq([f["role"], degree, f["context"]])
    return _pair(top, loc, sub, dates)


def _pair(top, top_right, sub, sub_right):
    """Lists of parts -> rows. The first top part is bold (others follow after ' | '); sub parts are italic."""
    if not top and sub:
        top, sub = sub, []
        top_right = " | ".join(x for x in (top_right, sub_right) if x)
        sub_right = ""
    if not top:
        return []
    if not sub:
        right = " | ".join(x for x in (top_right, sub_right) if x)
        return [_row(_join_runs(top, True, False), right, True)]
    return [_row(_join_runs(top, True, False), top_right, True), _row(_join_runs(sub, False, True), sub_right, False)]


def _inline(rows):
    """'inline' layout: no right-aligned column; the right text follows the left after ' | '."""
    for r in rows:
        if r.get("right"):
            r["left"] = r["left"] + [{"t": " | " + r["right"]}]
            r["right"] = ""
    return rows


def compile_resume(resume, draft=False, layout=None):
    """Validate resume.json and turn it into (blocks, warnings, setup). Raises RenderError."""
    if not isinstance(resume, dict):
        raise RenderError("resume.json must be a JSON object")
    basics = resume.get("basics")
    sections = resume.get("sections")
    if not isinstance(basics, dict) or not isinstance(sections, list):
        raise RenderError("resume.json needs 'basics' (object) and 'sections' (list)")
    name = clean(basics.get("name"))
    if not name:
        raise RenderError("basics.name is required")
    setup = page_setup(resume, layout)
    labels = labels_for(resume)
    inline = setup["layout"] == "inline"
    placeholders = as_dict(resume.get("placeholders"))
    warnings = []

    blocks = [{"k": "name", "text": name}]
    if clean(basics.get("headline")):
        blocks.append({"k": "headline", "text": clean(basics["headline"])})
    parts = []
    for key in ("location", "phone", "email"):
        v = clean(basics.get(key))
        if v:
            parts.append({"t": v, "url": ("mailto:" + v) if key == "email" else None})
    for ln in as_list(basics.get("links"))[:3]:
        url = clean(as_dict(ln).get("url")) if isinstance(ln, dict) else clean(ln)
        if url:
            parts.append({"t": display_url(url), "url": href_for(url)})
    if parts:
        blocks.append({"k": "contact", "parts": parts})

    for si, sec in enumerate(sections):
        if not isinstance(sec, dict):
            warnings.append("section %d is not an object; skipped" % (si + 1))
            continue
        stype = clean(sec.get("type")).lower() or "custom"
        title = clean(sec.get("title")) or stype.title()
        body = []
        if stype == "summary" or (clean(sec.get("text")) and not sec.get("items") and not sec.get("groups")):
            text = resolve_placeholders(sec.get("text"), sec, placeholders, draft, warnings,
                                        "section %s" % (clean(sec.get("id")) or title))
            if text:
                body.append({"k": "para", "runs": runs_from_text(text)})
        if stype == "skills" or sec.get("groups"):
            for g in as_list(sec.get("groups")):
                g = as_dict(g)
                items = ", ".join(clean(i) for i in as_list(g.get("items")) if clean(i))
                if not items:
                    continue
                label = clean(g.get("label"))
                runs = ([{"t": label + ": ", "b": True}] if label else []) + [{"t": items}]
                body.append({"k": "para", "runs": runs})
        for ii, item in enumerate(as_list(sec.get("items"))):
            if not isinstance(item, dict):
                warnings.append("%s item %d is not an object; skipped" % (title, ii + 1))
                continue
            rows = _entry_rows(item, stype, labels)
            body.extend(_inline(rows) if inline else rows)
            extras = []
            if clean(item.get("gpa")):
                extras.append("%s: %s" % (labels["gpa"], clean(item["gpa"])))
            extras.extend(clean(h) for h in as_list(item.get("honors")) if clean(h))
            if extras:
                body.append({"k": "para", "runs": [{"t": " · ".join(extras)}]})
            courses = [clean(c) for c in as_list(item.get("coursework")) if clean(c)]
            if courses:
                body.append({"k": "para", "runs": [{"t": labels["coursework"] + ": ", "b": True},
                                                   {"t": ", ".join(courses)}]})
            for bi, b in enumerate(as_list(item.get("bullets"))):
                if isinstance(b, str):
                    b = {"id": "%s.%d" % (clean(item.get("id")) or title, bi + 1), "text": b}
                if not isinstance(b, dict):
                    continue
                where = "bullet %s" % (clean(b.get("id")) or "%s #%d" % (title, bi + 1))
                text = resolve_placeholders(b.get("text"), b, placeholders, draft, warnings, where)
                if text:
                    body.append({"k": "bullet", "runs": runs_from_text(text)})
        if body:
            blocks.append({"k": "h", "text": title})
            blocks.extend(body)
        else:
            warnings.append("section '%s' has no content; left out" % title)

    _lint(blocks, warnings, draft)
    return blocks, warnings, setup


def block_texts(blocks):
    """Every visible string in the block list (used by linting and tests)."""
    for b in blocks:
        if b.get("text"):
            yield b["text"]
        for key in ("runs", "left", "parts"):
            for r in b.get(key) or []:
                yield r.get("t", "")
        if b.get("right"):
            yield b["right"]


def _lint(blocks, warnings, draft):
    seen = set()
    for t in block_texts(blocks):
        if SYMBOL_RE.search(t) and t not in seen:
            seen.add(t)
            warnings.append("symbol or emoji in '%s': parsing software may drop or garble it; use plain words"
                            % t[:40])
        if not draft and ("{{" in t or "[ADD:" in t):
            raise RenderError("unresolved placeholder text in '%s'; final files never contain '{{' or '[ADD:'"
                              % t[:60])
