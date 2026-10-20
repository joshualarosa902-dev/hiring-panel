"""Render and gate regressions from the live end-to-end tests (B 6.6, 6.7, 6.21). All data is fictional."""
import copy
import os
import re
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "plugins", "hiring-panel", "skills", "hiring-panel", "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from hp import gate  # noqa: E402
from hp.ingest import ingest_file  # noqa: E402
from hp.render import model, pdf_engines, render_resume  # noqa: E402
from hp.render.html import build_resume_html  # noqa: E402

HAS_BROWSER = bool(pdf_engines.browser_candidates())


def entry(eid, **fields):
    out = {"id": eid}
    out.update(fields)
    return out


def b(bid, text, **extra):
    out = {"id": bid, "text": text, "evidence": [{"src": "orig", "ref": "R1"}]}
    out.update(extra)
    return out


# Every section type, and entries that carry name AND org (the B 6.6 shape) everywhere.
RESUME = {
    "schemaVersion": "1.0",
    "meta": {"locale": "en-US", "layout": "classic", "stage": "student"},
    "basics": {"name": "Rowan Ellery", "headline": "Nursing Student | BLS Provider",
               "location": "Portland, ME", "email": "rowan.ellery@example.com"},
    "sections": [
        {"id": "sum", "type": "summary", "title": "Summary", "text": "Nursing student who works nights."},
        {"id": "edu", "type": "education", "title": "Education", "items": [
            entry("edu1", school="Harbor Point College", name="Presidential Scholars Program",
                  degree="Bachelor of Science", field="Nursing", minor="Spanish", role="Teaching Assistant",
                  context="Anatomy lab", location="Portland, ME", end="2028-05", endLabel="Expected")]},
        {"id": "exp", "type": "experience", "title": "Experience", "items": [
            entry("exp1", org="Juniper Bakery", name="Summer Kitchen Program", role="Prep Cook",
                  context="Part-time", location="Biddeford, ME", start="2024-06", end="present",
                  bullets=[b("exp1.b1", "Prepared dough for about 200 loaves each morning before the shop "
                                        "opened, working with two bakers to keep the ovens on schedule"),
                           b("exp1.b2", "Trained 3 new hires on food safety")]),
            entry("exp2", role="Family Caregiver", dateText="2023 - present",
                  bullets=[b("exp2.b1", "Help a family member get around the house")])]},
        {"id": "proj", "type": "projects", "title": "Projects", "items": [
            entry("proj1", name="Tide Tracker App", org="Harbor Point College", role="Lead developer",
                  context="Class project", location="Portland, ME", dateText="Spring 2025",
                  bullets=[b("proj1.b1", "Built a tide chart page for {{p1}} classmates",
                             textIfUnknown="Built a tide chart page for classmates")])]},
        {"id": "cert", "type": "custom", "title": "Certifications", "items": [
            entry("cert1", name="BLS Provider", org="American Heart Association", start="2025-08", end="2027-08",
                  endLabel="Expires")]},
        {"id": "act", "type": "custom", "title": "Activities", "items": [
            entry("act1", name="Volleyball team", org="Lincoln High School", dateText="3 years")]},
        {"id": "vol", "type": "custom", "title": "Volunteer Experience", "items": [
            entry("vol1", org="Coastal Food Bank", role="Volunteer", dateText="2023",
                  bullets=[b("vol1.b1", "Packed food boxes about twice a month")])]},
        {"id": "skills", "type": "skills", "title": "Skills", "groups": [
            {"label": "Languages", "items": ["English", "Spanish"]}]},
    ],
    "placeholders": {"p1": {"bullet": "proj1.b1", "ask": "How many?", "status": "answered", "value": "about 30"}},
}

FIELDS = ("org", "role", "name", "school", "degree", "field", "minor", "context", "location")


def all_strings(resume):
    out = []
    for sec in resume["sections"]:
        for it in sec.get("items") or []:
            out += [it[f] for f in FIELDS if it.get(f)]
    return out


def old_entry_rows(item, stype, labels):
    """The pre-fix renderer: outside Projects, org won and the entry name was dropped."""
    dates = model.date_range(item, labels)
    loc = model.clean(item.get("location"))
    if stype == "education" or (model.clean(item.get("school")) and not model.clean(item.get("org"))):
        deg = ", ".join(x for x in (model.clean(item.get("degree")), model.clean(item.get("field"))) if x)
        top = model.clean(item.get("school")) or model.clean(item.get("name")) or model.clean(item.get("org"))
        return model._pair([top], loc, [deg] if deg else [], dates)
    if stype == "projects" or (model.clean(item.get("name")) and not model.clean(item.get("org"))):
        return [model._row([{"t": model.clean(item.get("name")) or model.clean(item.get("org")), "b": True}],
                           dates, True)]
    top = model.clean(item.get("org")) or model.clean(item.get("name"))
    role = model.clean(item.get("role"))
    return model._pair([top], loc, [role] if role else [], dates)


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hp-test-live-")
        self.env = dict(os.environ)
        os.environ["HP_AS_OF"] = "2026-10-20"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        os.environ.clear()
        os.environ.update(self.env)

    def render(self, resume=None, sub="out", **kw):
        kw.setdefault("pdf_engine", "builtin")
        return render_resume(copy.deepcopy(resume or RESUME), os.path.join(self.tmp, sub), **kw)

    def texts(self, info):
        with open(info["files"]["md"], encoding="utf-8") as f:
            md = f.read()
        out = {"md": md, "docx": gate.doc_text(ingest_file(info["files"]["docx"]))}
        if info["files"].get("pdf"):
            out["pdf"] = gate.doc_text(ingest_file(info["files"]["pdf"]))
        return out


class TestEveryFieldRendered(Case):
    """B 6.6: name AND org (and role, school, degree, context, location) show up for every section type."""

    def test_blocks_hold_every_field(self):
        blocks, _warnings, _setup = model.compile_resume(copy.deepcopy(RESUME))
        joined = " ".join(model.block_texts(blocks))
        for s in all_strings(RESUME):
            self.assertIn(s, joined)

    def test_files_hold_every_field_and_bullet(self):
        info = self.render(formats=("docx", "pdf", "md"))
        expected = gate.expected_content(RESUME)
        self.assertEqual(len([e for e in expected if e["field"] == "bullet"]), 5)
        for kind, text in self.texts(info).items():
            self.assertEqual(gate.missing_content(expected, text), [], kind)
            for needle in ("BLS Provider", "American Heart Association", "Volleyball team", "Lincoln High School",
                           "Presidential Scholars Program", "Summer Kitchen Program", "Lead developer"):
                self.assertIn(needle, text, (kind, needle))

    def test_certification_row_reads_name_then_issuer(self):
        info = self.render(formats=("md",))
        with open(info["files"]["md"], encoding="utf-8") as f:
            md = f.read()
        self.assertIn("**BLS Provider** | *American Heart Association* | Aug 2025 – Expires Aug 2027", md)
        self.assertIn("**Volleyball team** | *Lincoln High School* | 3 years", md)
        self.assertIn("**Juniper Bakery** | Summer Kitchen Program | Biddeford, ME", md)
        self.assertIn("*Prep Cook* | *Part-time* | Jun 2024 – Present", md)

    def test_inline_layout_keeps_every_field(self):
        info = self.render(formats=("docx", "md"), layout="inline")
        expected = gate.expected_content(RESUME)
        for kind, text in self.texts(info).items():
            self.assertEqual(gate.missing_content(expected, text), [], kind)


class TestGateContentCheck(Case):
    def test_gate_fails_when_the_renderer_drops_a_name(self):
        with mock.patch.object(model, "_entry_rows", old_entry_rows):
            info = self.render(formats=("docx", "pdf", "md"))
        expected = gate.expected_content(RESUME)
        for kind, text in self.texts(info).items():
            missing = {(m["where"], m["field"], m["text"]) for m in gate.missing_content(expected, text)}
            # "BLS Provider" is also in the headline; the check is scoped to its section, so it still counts
            self.assertIn(("cert1", "name", "BLS Provider"), missing, kind)
            self.assertIn(("act1", "name", "Volleyball team"), missing, kind)
            self.assertIn(("exp1", "name", "Summer Kitchen Program"), missing, kind)

    def test_run_gate_reports_content_missing(self):
        with mock.patch.object(model, "_entry_rows", old_entry_rows):
            info = self.render(formats=("docx", "pdf", "md"))
        ctx = {"stage": "student", "as_of": "2026-10-20", "locale": "en-US"}
        res = gate.run_gate(info["files"], info["files"]["md"], "", ctx, os.path.join(self.tmp, "after"),
                            resume=copy.deepcopy(RESUME))
        self.assertFalse(res["passed"])
        self.assertFalse(res["retryable"])          # never "fixed" by the inline retry
        missing = [f for f in res["failures"] if f["code"] == "content_missing"]
        self.assertEqual({f["detail"].split(":")[0] for f in missing}, {"docx", "pdf", "md"})
        self.assertIn("do not send this file", missing[0]["detail"])
        for kind in ("docx", "pdf", "md"):
            got = {(m["where"], m["field"]) for m in res["checks"][kind]["missing_content"]}
            self.assertTrue({("cert1", "name"), ("act1", "name"), ("edu1", "name"), ("proj1", "org")} <= got,
                            (kind, got))

    def test_run_gate_passes_the_fixed_renderer(self):
        info = self.render(formats=("docx", "pdf", "md"))
        ctx = {"stage": "student", "as_of": "2026-10-20", "locale": "en-US"}
        res = gate.run_gate(info["files"], info["files"]["md"], "", ctx, os.path.join(self.tmp, "after"),
                            resume=copy.deepcopy(RESUME))
        self.assertEqual([f for f in res["failures"] if f["code"] == "content_missing"], [])
        for kind in ("docx", "pdf", "md"):
            self.assertEqual(res["checks"][kind]["missing_content"], [], kind)
            self.assertEqual(res["checks"][kind]["content_checked"], len(gate.expected_content(RESUME)))

    def test_run_gate_finds_resume_json_next_to_after_dir(self):
        run = os.path.join(self.tmp, "run")
        os.makedirs(os.path.join(run, "work", "rewrite"))
        with open(os.path.join(run, "work", "rewrite", "resume.json"), "w", encoding="utf-8") as f:
            import json
            json.dump(RESUME, f)
        self.assertEqual(gate._load_resume_near(os.path.join(run, "work", "screening", "after"))["basics"]["name"],
                         "Rowan Ellery")

    def test_placeholder_variants(self):
        r = copy.deepcopy(RESUME)
        exp = [e for e in gate.expected_content(r) if e["where"] == "proj1.b1"][0]
        text = "\n".join(["PROJECTS", "Tide Tracker App", "Built a tide chart page for about 30 classmates"])
        self.assertEqual([m for m in gate.missing_content([exp], text)], [])
        r["placeholders"]["p1"]["status"] = "open"
        exp = [e for e in gate.expected_content(r) if e["where"] == "proj1.b1"][0]
        self.assertEqual(gate.missing_content([exp], "PROJECTS\nBuilt a tide chart page for classmates"), [])
        self.assertEqual(gate.missing_content([exp], "PROJECTS\nBuilt a tide chart page for [ADD: count] "
                                                     "classmates"), [])
        self.assertTrue(gate.missing_content([exp], "PROJECTS\nBuilt a page"))

    def test_line_end_hyphenation_tolerated(self):
        exp = [{"where": "x", "field": "bullet", "text": "first-year volunteer", "variants": [["first-year volunteer"]],
                "sec": 0, "title": "Volunteer"}]
        self.assertEqual(gate.missing_content(exp, "VOLUNTEER\nfirstyear volunteer"), [])
        self.assertTrue(gate.missing_content(exp, "VOLUNTEER\nsome other year volunteer"))


class TestBulletGlyphs67(Case):
    def test_html_uses_literal_bullets(self):
        blocks, _w, setup = model.compile_resume(copy.deepcopy(RESUME))
        html = build_resume_html(blocks, setup)
        self.assertEqual(html.count('<span class="bm">•</span>'), 5)
        self.assertIn("list-style: none", html)
        self.assertNotIn("::marker", html)

    @unittest.skipUnless(HAS_BROWSER, "no Chrome/Edge/Brave on this machine")
    def test_chrome_pdf_bullets_survive_extraction(self):
        info = self.render(formats=("pdf", "md"), pdf_engine="chrome")
        self.assertTrue(str(info["pdfEngine"]).startswith("chrome"), info)
        doc = ingest_file(info["files"]["pdf"])
        lines = [ln["text"] for ln in doc["lines"]]
        bullets = [t for t in lines if t.startswith("•")]
        self.assertEqual(len(bullets), 5, lines)
        self.assertTrue(bullets[0].startswith("• Prepared dough"), bullets[0])
        # the long first bullet wraps; the continuation is not a bullet and not a new entry
        self.assertTrue(any(t.startswith("opened") or "opened" in t for t in lines))
        from hp.screen import run_screening
        result = run_screening(doc, "", stage="student", as_of="2026-10-20", locale="en-US")
        headers = [e.get("header") or "" for e in (result.get("experience") or {}).get("entries") or []]
        self.assertFalse([h for h in headers if "ovens on schedule" in h or h.startswith("opened")], headers)


class TestDocxTabStop621(Case):
    """B 6.21: the right tab stop sits exactly on the right margin (text width in twips) on Letter and A4.
    Verified by hand in Pages (export to PDF): dates are flush right. macOS Quick Look ignores every
    paragraph tab stop (the Cocoa importer drops them), so it shows dates mid-line; that is a viewer limit."""

    def check(self, locale, page_w, text_w):
        r = copy.deepcopy(RESUME)
        r["meta"]["locale"] = locale
        info = self.render(r, sub=locale, formats=("docx",))
        with zipfile.ZipFile(info["files"]["docx"]) as z:
            doc = z.read("word/document.xml").decode("utf-8")
            styles = z.read("word/styles.xml").decode("utf-8")
        self.assertIn('<w:pgSz w:w="%d"' % page_w, doc)
        self.assertIn('w:right="1008"', doc)
        self.assertIn('w:left="1008"', doc)
        self.assertEqual(page_w - 2 * 1008, text_w)
        tabs = re.findall(r'<w:tab w:val="(\w+)" w:pos="(\d+)"/>', doc + styles)
        self.assertTrue(tabs)
        self.assertEqual(set(tabs), {("right", str(text_w))})
        # every right-aligned date run follows a space and a tab
        self.assertEqual(doc.count("<w:tab/>"), doc.count('<w:t xml:space="preserve"> </w:t><w:tab/>'))

    def test_letter(self):
        self.check("en-US", 12240, 10224)

    def test_a4(self):
        self.check("en-GB", 11906, 9890)


if __name__ == "__main__":
    unittest.main()
