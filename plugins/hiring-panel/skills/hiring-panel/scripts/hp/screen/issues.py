"""Turn ingest signals and text findings into catalogue issues (ATS spec 6 + PARSE-023).

Ingest records facts only; this module decides issue ids, severities and confidence. Each issue id
appears at most once; repeated findings become evidence lines (at most 5, contact details masked).
"""
import re

from .constants import (CATALOGUE, CATEGORY_BY_PREFIX, ENTRY_SECTIONS, FILE_SIZE_LIMIT, MAX_BULLETS_PER_ENTRY,
                        PAGE_LIMIT, SEVERITY_RANK, TEXTBOX_SHARE_HIGH)
from .content import FIRST_PERSON_RE, abbreviated_titles, rating_graphic_lines
from .dates import FORMAT_FAMILY, month_str
from .entries import DEGREE_WORD_RE, SCHOOL_WORD_RE, verb_start
from .sections import STANDARD_NAME
from .textutil import clip, garbled_share, letter_spaced_runs, mask_all

_CORE_HEADINGS = ("education", "experience", "projects", "skills", "leadership_activities", "volunteer")
_PLACEHOLDER_RE = re.compile(
    r"(?i)\b(?:company|client|employer)\s?[0-9A-C]\b|lorem ipsum|\byour name\b|\[company\]|\b123 main st|"
    r"\byour\.?name@|\bname@email\.com\b|\bemail@example\.com\b|\[(?:insert|add|your)[^\]]{0,40}\]|"
    r"\bcompany name\b|\bjob title here\b|(?-i:\bCity, State\b)")
_PAGE_OF_RE = re.compile(r"(?i)\bpage\s+\d+\s*(?:of|/)\s*\d+\b")
_REFERENCES_RE = re.compile(r"(?i)\breferences\s+(?:are\s+)?(?:available\s+)?(?:up)?on\s+request\b")
_DESIGN_RE = re.compile(r"(?i)canva|indesign|illustrator|photoshop|figma|affinity|sketch|\bpages\b|keynote")
_PRIVATE_USE_RE = re.compile("[\ue000-\uf8ff□]")


def _sig(doc, *path, default=None):
    cur = doc.get("signals") if isinstance(doc.get("signals"), dict) else {}
    for p in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(p)
    if cur is None:
        return default
    return cur


def _num(v):
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, list):
        return len(v)
    return 0


class IssueSet(object):
    def __init__(self, doc_word):
        self.doc_word = doc_word
        self.items = {}
        self.order = []
        self.counts = {}

    def add(self, iid, severity, evidence=(), confidence="high", variant=None, detected_by=None,
            count=None, fmt=None):
        cat = CATALOGUE[iid]
        fields = {k: cat.get(k) for k in ("title", "why", "fix", "honesty", "detected_by", "refs")}
        if variant and variant in cat.get("variants", {}):
            fields.update(cat["variants"][variant])
        subs = {"doc": self.doc_word}
        subs.update(fmt or {})

        def f(s):
            if s is None:
                return None
            for k, v in subs.items():
                s = s.replace("{%s}" % k, str(v))
            return s
        ev = [clip(mask_all(clip(str(e), 400)), 200) for e in evidence if e]
        if iid in self.items:
            it = self.items[iid]
            if SEVERITY_RANK[severity] < SEVERITY_RANK[it["severity"]]:
                it["severity"] = severity
            for e in ev:
                if e not in it["evidence"] and len(it["evidence"]) < 5:
                    it["evidence"].append(e)
            return it
        prefix = iid.split("-")[0]
        it = {
            "id": iid, "rank": 0, "category": CATEGORY_BY_PREFIX[prefix], "severity": severity,
            "title": clip(f(fields["title"]), 90), "evidence": ev[:5], "why_it_matters": f(fields["why"]),
            "fix": f(fields["fix"]), "honesty_note": f(fields.get("honesty")), "confidence": confidence,
            "detected_by": detected_by or fields["detected_by"], "score_impact": {},
            "source_refs": list(fields["refs"] or []),
        }
        self.items[iid] = it
        self.order.append(iid)
        if count is not None:
            self.counts[iid] = count
        return it

    def has(self, iid):
        return iid in self.items

    def get(self, iid):
        return self.items.get(iid)

    def remove(self, iid):
        if iid in self.items:
            del self.items[iid]
            self.order.remove(iid)

    def list(self):
        return [self.items[i] for i in self.order]


_REFUSED = ("xml_dtd_refused", "zip_bomb", "file_too_large", "too_large", "refused")


def _unreadable_reason(codes, fmt, legacy):
    """Plain-language reason a file gave no text, from ingest error codes."""
    if legacy or fmt in ("doc", "pages", "odt", "unknown"):
        return "This file type could not be read here, so its text was not checked."
    if any(c in _REFUSED for c in codes):
        return "The file was refused for safety reasons (for example an unusual internal structure)."
    return "The file looks damaged or incomplete, so its text could not be read."


def detect_parse(iss, doc, lines, hf, ctx):
    """PARSE-* issues from file structure and extracted text."""
    fmt = doc.get("format") if isinstance(doc.get("format"), str) else "unknown"
    has_text = bool(lines)
    text = "\n".join(rl.text for rl in lines)
    text_chars = len(text)
    errors = [e for e in (doc.get("errors") or []) if isinstance(e, dict)]
    err_codes = sorted({str(e.get("code") or "error")[:40] for e in errors})

    encrypted = bool(_sig(doc, "encrypted"))
    image = fmt == "image" or bool(_sig(doc, "image_only")) or _sig(doc, "text_layer") is False
    locked = encrypted and not has_text
    if encrypted:
        if has_text:
            # Encrypted with only an owner password: it opens, but some systems refuse it.
            iss.add("PARSE-002", "high", ["The file is encrypted. It opened here without a password, but "
                                          "some systems refuse encrypted files."], confidence="medium")
        else:
            iss.add("PARSE-002", "critical", ["The file is password-protected, so no text could be read."])
    if image and not locked:
        iss.add("PARSE-001", "critical", ["The file has no text layer (an image or a scan)."
                                          if fmt != "image" else "The file is an image, not a document."])
    gshare, gcount = garbled_share(text)
    repl = max(_num(_sig(doc, "replacement_chars")), text.count("\ufffd"))
    garbled = bool(_sig(doc, "garbled")) or (gcount >= 20 and gshare > 0.15) or \
        (text_chars > 0 and repl / float(text_chars) > 0.01)
    if not locked and not image and (garbled or (not has_text and errors)):
        ev = []
        if garbled:
            ev.append("About %d%% of the extracted words look broken." % int(round(gshare * 100))
                      if gshare > 0.15 else "The extracted text contains broken or replacement characters.")
        if not has_text and errors:
            ev.append(_unreadable_reason(err_codes, fmt, _sig(doc, "legacy_format")))
        iss.add("PARSE-003", "critical", ev, confidence="high" if (not has_text or _sig(doc, "garbled")) else "medium")
    if not has_text and not (iss.has("PARSE-001") or locked or iss.has("PARSE-003")):
        iss.add("PARSE-001", "critical", ["No text could be extracted from the file."])
    type0 = _num(_sig(doc, "fonts", "type0"))
    tounicode = _num(_sig(doc, "fonts", "tounicode"))
    if fmt == "pdf" and type0 > tounicode:
        ev = "%d font(s) lack a text mapping (ToUnicode)." % (type0 - tounicode)
        if iss.has("PARSE-003"):
            iss.add("PARSE-003", "critical", [ev])
        else:
            iss.add("PARSE-004", "high", [ev], confidence="low" if (has_text and text_chars > 200) else "medium")
    if _num(_sig(doc, "fonts", "type3")) > 0:
        iss.add("PARSE-005", "medium", ["%d Type 3 font(s) found." % _num(_sig(doc, "fonts", "type3"))],
                confidence="medium")
    # contact details that live only in the header/footer
    where = ctx["contact_where"]
    hf_only = [k for k in ("email", "phone") if where.get(k) == "header_footer"]
    if hf_only:
        iss.add("PARSE-006", "high", ["Your %s appears only in the header or footer." % k for k in hf_only])
    # text boxes
    tb_lines = [rl for rl in lines if rl.where == "textbox"]
    tb_count = max(_num(_sig(doc, "text_boxes", "count")), 1 if tb_lines else 0)
    if tb_count:
        tb_chars = max(_num(_sig(doc, "text_boxes", "chars")), sum(len(rl.text) for rl in tb_lines))
        share = tb_chars / float(text_chars) if text_chars else 0.0
        has_contact = bool(_sig(doc, "text_boxes", "has_contact")) or any("@" in rl.text for rl in tb_lines)
        has_heading = bool(_sig(doc, "text_boxes", "has_heading")) or any(rl.heading for rl in tb_lines)
        high = has_contact or has_heading or share >= TEXTBOX_SHARE_HIGH
        ev = ["%d text box(es) hold about %d%% of the text." % (tb_count, int(round(share * 100)))]
        if has_contact:
            ev.append("A text box holds contact details.")
        if has_heading:
            ev.append("A text box holds a section heading.")
        iss.add("PARSE-007", "high" if high else "medium", ev)
    # tables
    tbl_lines = [rl for rl in lines if rl.where == "table"]
    tbl_count = max(_num(_sig(doc, "tables", "count")), 1 if tbl_lines else 0)
    if tbl_count:
        holds = bool(_sig(doc, "tables", "holds_experience")) or any(
            rl.dates["ranges"] or rl.heading for rl in tbl_lines)
        ev = ["%d table(s) found%s." % (tbl_count, ", including dated entries or headings" if holds else "")]
        if _num(_sig(doc, "tables", "nested")):
            ev.append("Some tables are nested inside other tables.")
        iss.add("PARSE-008", "high" if holds else "medium", ev, variant=None if holds else "layout")
    # columns
    docx_cols = bool(_sig(doc, "columns", "docx_multi_column"))
    gutters = _sig(doc, "columns", "pdf_gutter_pages", default=[])
    gutters = [p for p in gutters if isinstance(p, int)] if isinstance(gutters, list) else []
    if docx_cols or gutters:
        ev = []
        if docx_cols:
            ev.append("A Word section is set to more than one column.")
        if gutters:
            ev.append("A column gutter was found on page(s) %s." % ", ".join(str(p) for p in list(gutters)[:5]))
        iss.add("PARSE-009", "high", ev, confidence="high" if docx_cols else "medium")
    else:
        ro = reading_order_anomaly(lines)
        if ro:
            iss.add("PARSE-009b", "medium", ro, confidence="low", detected_by="heuristic")
    # images and rating graphics
    large = _num(_sig(doc, "images", "large"))
    charts = _num(_sig(doc, "images", "charts")) + _num(_sig(doc, "images", "smartart"))
    icons = _num(_sig(doc, "images", "small_icons"))
    count = _num(_sig(doc, "images", "count"))
    ratings = rating_graphic_lines(lines)
    if large or charts:
        ev = []
        if large:
            ev.append("%d large image(s) found." % large)
        if charts:
            ev.append("%d chart(s) or SmartArt graphic(s) found." % charts)
        if ctx["norms"].get("photo") == "customary" and large <= 1 and not charts:
            iss.add("PARSE-010", "info", ev, variant="photo_customary")
        else:
            iss.add("PARSE-010", "medium", ev)
    elif count or icons:
        iss.add("PARSE-010", "low", ["%d small image(s) or icon(s) found." % max(count, icons)], variant="icons")
    if ratings:
        iss.add("PARSE-024", "low", ratings[:3], count=len(ratings))
    size = _num(doc.get("bytes"))
    if size > FILE_SIZE_LIMIT or _sig(doc, "too_large"):
        iss.add("PARSE-011", "high", ["The file is about %.1f MB." % (size / 1000000.0)] if size else [])
    legacy = _sig(doc, "legacy_format")
    if fmt in ("doc", "pages", "unknown") or legacy:
        iss.add("PARSE-012", "high", ["File type: %s." % (legacy or fmt)])
    producer = " ".join(str(x) for x in (doc.get("producer"), doc.get("creator"), _sig(doc, "design_tool")) if x)
    if fmt == "pdf" and (_sig(doc, "design_tool") or _DESIGN_RE.search(producer)):
        sev = "medium" if (iss.has("PARSE-003") or iss.has("PARSE-004") or iss.has("PARSE-009")) else "info"
        iss.add("PARSE-013", sev, ["Made with: %s" % clip(producer, 80)])
    spaced = [rl for rl in lines if letter_spaced_runs(rl.text)]
    spaced_heads = [rl.text for rl in spaced if rl.heading and rl.heading["section"] in _CORE_HEADINGS]
    if spaced_heads:
        # The headings only worked here because this check joins the letters back up.
        iss.add("PARSE-014", "high", spaced_heads[:3], confidence="medium", variant="headings")
    elif _num(_sig(doc, "letter_spaced")) or spaced:
        iss.add("PARSE-014", "medium", [rl.text for rl in spaced][:3] or ["Letter-spaced text was found in the file."])
    pua = _num(_sig(doc, "private_use_chars")) + sum(len(_PRIVATE_USE_RE.findall(rl.raw)) for rl in lines)
    if pua:
        iss.add("PARSE-015", "low", ["%d icon or symbol character(s) found." % pua])
    hidden = {k: _num(_sig(doc, "hidden_text", k)) for k in ("vanish", "white", "tiny", "pdf_invisible")}
    if any(hidden.values()):
        conf = "high" if (hidden["vanish"] or hidden["white"]) else ("medium" if hidden["tiny"] else "low")
        labels = {"vanish": "hidden-formatted runs", "white": "white text runs", "tiny": "tiny text runs",
                  "pdf_invisible": "invisible PDF text"}
        iss.add("PARSE-016", "high", ["%d %s" % (hidden[k], labels[k]) for k in sorted(hidden) if hidden[k]],
                confidence=conf)
    if _num(_sig(doc, "caps_formatting")):
        iss.add("PARSE-017", "low", ["%d run(s) use capitals formatting." % _num(_sig(doc, "caps_formatting"))])
    ole = _num(_sig(doc, "fields", "ole"))
    flds = _num(_sig(doc, "fields", "docproperty")) + _num(_sig(doc, "fields", "mergefield"))
    if ole:
        iss.add("PARSE-018", "medium", ["%d embedded object(s) found." % ole], variant="ole")
    elif flds:
        iss.add("PARSE-018", "low", ["%d document field(s) found." % flds])
    tc, cm = _num(_sig(doc, "tracked_changes")), _num(_sig(doc, "comments"))
    if tc or cm:
        iss.add("PARSE-019", "medium", ["%d tracked change(s) and %d comment(s) found." % (tc, cm)])
    ph = [t for t in [rl.text for rl in lines] + [h["text"] for h in hf] if _PLACEHOLDER_RE.search(t)]
    if ph:
        iss.add("PARSE-020", "high", ph[:3])
    leaks = [rl.text for rl in lines if _PAGE_OF_RE.search(rl.text)]
    if _num(_sig(doc, "repeated_footer_lines")) or leaks:
        iss.add("PARSE-021", "low", leaks[:2] or ["Repeated footer lines appear in the text."])
    pages = doc.get("pages")
    limit = PAGE_LIMIT.get(ctx["stage"], 2)
    if isinstance(pages, int) and not isinstance(pages, bool) and pages > limit:
        iss.add("PARSE-022", "info", ["The file has %d pages." % pages], fmt={"pages": limit})
    merged = _num(_sig(doc, "tab_merged_tokens"))
    if merged:
        iss.add("PARSE-023", "medium", ["%d place(s) where a tab is the only gap between two words." % merged])


def reading_order_anomaly(lines):
    """PARSE-009b: 3+ date ranges within 8 consecutive lines of one section with no bullets between
    them, followed (within 3 lines) by a run of 2+ bullets in the same section."""
    idx = [k for k, rl in enumerate(lines) if rl.dates["ranges"]]
    for a in range(len(idx) - 2):
        i0, i2 = idx[a], idx[a + 2]
        if i2 - i0 > 7:
            continue
        seg = lines[i0:i2 + 1]
        if any(rl.bullet for rl in seg) or len({rl.section for rl in seg}) > 1 or any(rl.heading for rl in seg):
            continue
        after = lines[i2 + 1:i2 + 6]
        for s in range(min(3, len(after))):
            run = after[s:s + 2]
            if len(run) == 2 and all(rl.bullet and rl.section == seg[0].section for rl in run) and \
                    not any(rl.heading for rl in after[:s]):
                return ["%d date ranges in a row before any bullets, near: %s" % (
                    sum(1 for rl in seg if rl.dates["ranges"]), seg[0].text)]
    return []


def detect_contact(iss, contact, ctx):
    if not contact["email"]:
        iss.add("CONTACT-001", "high")
    if not contact["phone"]:
        iss.add("CONTACT-002", "medium")
    if not contact["location"] and ctx["english"]:
        iss.add("CONTACT-003", "low", confidence="medium")
    if not contact["linkedin"]:
        iss.add("CONTACT-004", "info")
    if contact["street_address_present"] and ctx["locale"].startswith("en"):
        iss.add("CONTACT-005", "info")
    if contact["found_in"] == "body_elsewhere":
        iss.add("CONTACT-006", "low", ["Your email or phone first appears below the top 12 lines."])
    if contact["emails_found"] > 1:
        iss.add("CONTACT-007", "low", ["%d different email addresses found." % contact["emails_found"]])


def education_evidence(lines):
    """A line (or two neighbouring lines) naming both a degree and a school, or None."""
    for k, rl in enumerate(lines):
        if rl.heading:
            continue
        here = DEGREE_WORD_RE.search(rl.text)
        school = SCHOOL_WORD_RE.search(rl.text)
        if here and school:
            return rl.text
        nxt = lines[k + 1] if k + 1 < len(lines) else None
        if nxt is not None and not nxt.heading and (
                (here and SCHOOL_WORD_RE.search(nxt.text)) or (school and DEGREE_WORD_RE.search(nxt.text))):
            return "%s / %s" % (rl.text, nxt.text)
    return None


def work_evidence(entries, lex):
    """Header of a dated entry outside Education that has a bullet starting with a verb, or None."""
    for e in entries:
        if e.section == "education" or not e.dated or not e.header_lines:
            continue
        if any(verb_start(b.btext, lex) for b in e.bullets):
            return e.header_text()
    return None


def detect_sections(iss, lines, detected, ctx, entries=(), lex=None):
    """SECT-* issues. A missing Education or Experience heading is only reported as missing when the
    text has no such content; otherwise SECT-007 says the heading was not recognized."""
    present = {d["canonical"] for d in detected}
    if ctx["stage"] == "student" and "education" not in present:
        ev = education_evidence(lines)
        if ev:
            iss.add("SECT-007", "medium", ['Education details found ("%s") but no heading named Education.'
                                           % clip(ev, 90)], confidence="medium")
        else:
            iss.add("SECT-001", "high")
    has_exp = "experience" in present
    has_alt = bool(present & {"projects", "leadership_activities", "volunteer"})
    if not has_exp and not has_alt:
        ev = work_evidence(entries, lex) if lex is not None else None
        if ev:
            iss.add("SECT-007", "medium", ['Dated entries with bullets found ("%s") but no Experience, Projects '
                                           'or Leadership heading.' % clip(ev, 90)], confidence="medium")
        else:
            iss.add("SECT-002", "high")
    elif not has_exp:
        iss.add("SECT-002", "medium", variant="no_experience")
    if "skills" not in present:
        iss.add("SECT-003", "medium")
    nonstd = [d for d in detected if not d["standard"] and not d["combined"] and not d["inline"]
              and d["canonical"] not in ("other", "contact")]
    if nonstd:
        iss.add("SECT-004", "low", ['"%s" reads as %s; the usual name is "%s".' % (
            d["heading"], STANDARD_NAME.get(d["canonical"], d["canonical"]),
            STANDARD_NAME.get(d["canonical"], d["canonical"])) for d in nonstd], confidence="medium")
    comb = [d for d in detected if d["combined"]]
    if comb:
        iss.add("SECT-005", "low", ['"%s"' % d["heading"] for d in comb])
    refs = [rl.text for rl in lines if _REFERENCES_RE.search(rl.text)]
    ref_lines = [rl.text for rl in lines if rl.section == "references" and not rl.heading]
    if refs or ref_lines:
        iss.add("SECT-006", "low", (refs + ref_lines)[:2])


def detect_dates(iss, lines, entries, tl, ctx):
    as_of_m = ctx["as_of_m"]
    undated = [e for e in entries if not e.dated and e.header_lines and
               e.section in ("experience", "leadership_activities", "volunteer", "education")]
    if undated:
        iss.add("DATE-001", "medium", [e.header_text() for e in undated], count=len(undated))
    year_only = []
    two_digit = []
    families = set()
    inverted, future = [], []
    for e in entries:
        if not e.dated:
            continue
        fmts = []
        if e.range is not None:
            fmts = [e.range["start_fmt"]] + ([e.range["end_fmt"]] if e.range["end_fmt"] else [])
            if e.range["start"] > e.range["end"] and not e.range["current"]:
                inverted.append(e.range["text"])
            if not e.range["current"] and e.range["earliest_end"] > as_of_m and not e.expected:
                future.append(e.range["text"])
        else:
            fmts = [e.single["fmt"]]
            if e.single["start"] > as_of_m and not e.expected:
                future.append(e.single["text"])
        for f in fmts:
            fam = FORMAT_FAMILY.get(f)
            if fam:
                families.add(fam)
        if "year_only" in fmts and e.section in ENTRY_SECTIONS:
            year_only.append(e.header_text())
        if "two_digit_year" in fmts:
            two_digit.append((e.range or e.single)["text"])
    if year_only:
        iss.add("DATE-002", "low", year_only)
    splits = ctx.get("splits") or []
    if splits:
        iss.add("DATE-003", "medium", splits)
    if "name" in families and "numeric" in families:
        iss.add("DATE-004", "low", ["Both month names and numeric dates are used."])
    if inverted:
        iss.add("DATE-005", "high", inverted)
    if future:
        iss.add("DATE-006", "medium", future)
    if tl["inversions"]:
        iss.add("DATE-007", "low", ['"%s" is listed above the more recent "%s".' % (
            clip(a.header_text(), 70), clip(b.header_text(), 70)) for a, b in tl["inversions"]])
    gap_ev = ["No dated activity from %s to %s (%d months)." % (g["from"], g["to"], g["months"])
              for g in tl["gaps"]]
    since = tl["months_since_last_activity"]
    if since is not None and since > 6:
        gap_ev.append("Your most recent dated activity ended %d months before %s." % (since, month_str(as_of_m)))
    if gap_ev:
        iss.add("DATE-008", "info", gap_ev)
    if two_digit:
        iss.add("DATE-009", "low", two_digit)


def detect_content(iss, lines, entries, bm, details, ctx, lex):
    as_of_m = ctx["as_of_m"]
    if bm["count"] and bm["quantified_ratio"] is not None and bm["quantified_ratio"] < 0.35:
        n_q = sum(1 for d in details if d["quant"])
        iss.add("CONTENT-001", "medium", ["%d of %d bullets show a number (target: 35%% or more)." % (
            n_q, bm["count"])])
    by_line = {rl.idx: rl for rl in lines}
    weak = [d for d in details if d["weak"]]
    if weak:
        iss.add("CONTENT-002", "low", [by_line[d["line"]].btext for d in weak], count=len(weak))
    long_ = [d for d in details if d["words"] > 35]
    if long_:
        iss.add("CONTENT-003", "low", ["%d words: %s" % (d["words"], by_line[d["line"]].btext) for d in long_])
    short = [d for d in details if d["words"] < 5]
    if short:
        iss.add("CONTENT-004", "low", [by_line[d["line"]].btext for d in short])
    if bm["first_person_count"]:
        fp = [rl.btext for rl in lines if FIRST_PERSON_RE.search(rl.text) and (rl.section == "summary" or rl.bullet)]
        iss.add("CONTENT-005", "low", fp[:3] or ["%d first-person word(s)." % bm["first_person_count"]],
                count=bm["first_person_count"])
    if bm["repeated_openers"]:
        iss.add("CONTENT-006", "low", ['"%s" starts %d bullets.' % (k.capitalize(), v)
                                      for k, v in sorted(bm["repeated_openers"].items(), key=lambda kv: (-kv[1], kv[0]))])
    present = []
    for e in entries:
        if e.section not in ENTRY_SECTIONS or not e.dated:
            continue
        start, end, current = e.period(as_of_m)
        if current or e.expected or end is None or end >= as_of_m:
            continue
        for b in e.bullets:
            words = re.findall(r"[A-Za-z][A-Za-z'’-]*", b.btext)
            if words and words[0].lower() in lex.present_forms:
                present.append(b.btext)
    if present:
        iss.add("CONTENT-007", "low", present)
    if bm["buzzwords"]:
        iss.add("CONTENT-008", "info", ['"%s"' % b for b in bm["buzzwords"]])
    bad = []
    for e in entries:
        if not e.header_lines:
            continue
        if e.section == "experience" and not e.bullets:
            bad.append("No bullets: %s" % e.header_text())
        elif e.section in ENTRY_SECTIONS and len(e.bullets) > MAX_BULLETS_PER_ENTRY:
            bad.append("%d bullets: %s" % (len(e.bullets), e.header_text()))
    if bad:
        iss.add("CONTENT-009", "low", bad)
    abbr = abbreviated_titles(entries)
    if abbr:
        iss.add("CONTENT-010", "low", abbr)


def _listed_text(t):
    alt = t.get("matched_alternative")
    if alt and alt != t["term"]:
        return '"%s" (you have "%s") appears only in a list, not in a bullet about your work.' % (
            t["term"], t["resume_wording"])
    return '"%s" appears only in a list, not in a bullet about your work.' % t["term"]


def _wording_text(t):
    alt = t.get("matched_alternative")
    if alt and alt != t["term"]:
        return 'For "%s", the posting says "%s"; you wrote "%s".' % (t["term"], alt, t["resume_wording"])
    return 'Posting says "%s"; you wrote "%s".' % (t["term"], t["resume_wording"])


def detect_keywords(iss, kw, km_value, title_match):
    """KW-* issues; only called when the keyword match has a number."""
    basis = kw["basis_terms"]
    missing = sorted([t for t in basis if not t["found"]], key=lambda t: (-t["weight"], t["pos"]))
    if missing:
        sev = "high" if kw["R"] < 0.5 else "medium"
        ev = []
        for t in missing:
            note = " (only part of it found)" if t["match_type"] in ("partial", "ambiguous") else ""
            ev.append('Not found: "%s"%s' % (t["term"], note))
        if kw["basis"] == "all_terms":
            ev.insert(0, "The posting has no separate requirements list, so every job term counts.")
        iss.add("KW-001", sev, ev, count=len(missing))
    scored = kw["basis_terms"] + kw["pref_terms"]
    listed = [t for t in scored if t["found"] and t["evidence_level"] == "listed"]
    if listed:
        listed.sort(key=lambda t: (-t["weight"], t["pos"]))
        iss.add("KW-002", "medium", [_listed_text(t) for t in listed], count=len(listed))
    # Both sides are quoted as written: the posting's words (never the dictionary's name) and the
    # resume's words.
    alias = [t for t in scored if t["found"] and t["match_type"] in ("alias", "acronym")]
    if alias:
        iss.add("KW-003", "low", [_wording_text(t) for t in alias])
    if title_match.get("match") == "none" and title_match.get("jd_title"):
        iss.add("KW-004", "low", ['Posting title: "%s"' % title_match["jd_title"]])
    pref_missing = [t for t in kw["pref_terms"] if not t["found"]]
    if pref_missing and kw["basis"] == "required_preferred":
        pref_missing.sort(key=lambda t: (-t["weight"], t["pos"]))
        iss.add("KW-005", "info", ['Not found: "%s"' % t["term"] for t in pref_missing], count=len(pref_missing))
