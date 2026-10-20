"""Report rendering (hp.render.render_report): display order, one-page PDF, honesty display rules,
masking, chips and footer. All data is fictional."""
import copy
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "plugins", "hiring-panel", "skills", "hiring-panel", "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from hp.render import render_report, RenderError  # noqa: E402
from hp.render import pdf_engines  # noqa: E402
from hp.render.report import LIMITS, _section4_html, build_report_html, build_report_md, fit  # noqa: E402

FIX = os.path.join(HERE, "fixtures", "output")
HAS_BROWSER = bool(pdf_engines.browser_candidates())


def load(*parts):
    with open(os.path.join(FIX, *parts), encoding="utf-8") as f:
        return json.load(f)


FINAL, PANEL, STRESS = load("sample", "report.json"), load("sample", "report_panel.json"), load("stress", "report_stress.json")

SECTIONS_ALL = ["The panel", "Biggest weaknesses, most serious first", "What changed, what needs you, real gaps",
                "Where the panel disagreed", "Keyword gaps to close honestly", "already working", "Interview prep",
                "Mode and limitations"]


def pdf_text(path):
    with open(path, "rb") as f:
        data = f.read()
    out = []
    for m in re.finditer(rb"stream\n", data):
        try:
            chunk = zlib.decompressobj().decompress(data[m.end():m.end() + 2000000])
        except zlib.error:
            continue
        for s in re.findall(rb"\(((?:\\.|[^\\)])*)\) Tj", chunk):
            s = re.sub(rb"\\([0-7]{3})", lambda mm: bytes([int(mm.group(1), 8)]), s)
            s = re.sub(rb"\\(.)", rb"\1", s)
            out.append(s.decode("cp1252", "replace"))
    return " ".join(out)


def visible(html):
    """Rough visible text of our HTML (tags and the style block removed)."""
    html = re.sub(r"(?s)<style>.*?</style>", " ", html)
    html = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", html.replace("&amp;", "&").replace("&#x27;", "'").replace("&quot;", '"'))


class ReportCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hp-test-report-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def render(self, report, engine="builtin", sub="r"):
        return render_report(copy.deepcopy(report), os.path.join(self.tmp, sub), pdf_engine=engine)


class TestOrderAndContent(ReportCase):
    def test_md_has_all_ten_sections_in_order(self):
        md = build_report_md(copy.deepcopy(FINAL))
        heads = [h for h in re.findall(r"(?m)^## (.+)$", md)]
        self.assertEqual(heads, ["Biggest weaknesses, most serious first", "What changed, what needs you, real gaps",
                                 "The panel", "Where the panel disagreed", "Keyword gaps to close honestly",
                                 "What's already working", "Interview prep", "Mode and limitations"])
        top = md.split("## Biggest weaknesses")[0]
        for needle in ("- **The panel:** 3 of 7 would move you forward", "- **Simulated screening check:** 60 before, 75 after",
                       "Required terms: 3 of 5 found (1 only in your skills list)", "- **Truth check:** 0 invented facts.",
                       "- **Mode:** 7 independent reviewers"):
            self.assertIn(needle, top)

    def test_fix_before_you_send_comes_before_weaknesses(self):
        r = copy.deepcopy(FINAL)
        r["pinned_integrity"] = [{"issue_id": "I9", "title": "Sales figure looks inflated", "fix": "Confirm the base."}]
        md = build_report_md(r)
        self.assertLess(md.index("## Fix before you send"), md.index("## Biggest weaknesses"))
        html = build_report_html(r)
        order = [html.index(x) for x in ("Fix before you send", "Biggest weaknesses", "What changed, what needs you",
                                         "<h2>The panel", "Where the panel disagreed", "Keyword gaps", "already working",
                                         "Interview prep", "Mode and limitations")]
        self.assertEqual(order, sorted(order))

    def test_onepage_html_holds_only_sections_1_to_5(self):
        html = build_report_html(copy.deepcopy(FINAL), onepage=True)
        for kept in ("Biggest weaknesses", "What changed, what needs you", "<h2>The panel"):
            self.assertIn(kept, html)
        for dropped in ("Where the panel disagreed", "Keyword gaps", "already working", "Interview prep",
                        "Mode and limitations"):
            self.assertNotIn(dropped, html)
        self.assertIn("top 5 of 6", html)

    def test_weaknesses_keep_synthesis_order(self):
        md = build_report_md(copy.deepcopy(FINAL))
        ranks = [int(x) for x in re.findall(r"(?m)^(\d+)\. \*\*", md.split("## What changed")[0])]
        self.assertEqual(ranks, [1, 2, 3, 4, 5, 6])

    def test_chips_and_status_labels(self):
        html = build_report_html(copy.deepcopy(FINAL))
        for label in ("Lean no", "Lean yes", "Borderline", "Fixed", "Real gap", "Needs you", "Unsure"):
            self.assertIn(label, html)
        r = copy.deepcopy(FINAL)
        r["panel"][0]["verdict"], r["panel"][1]["verdict"] = "strong_no", "strong_yes"
        html = build_report_html(r)
        self.assertIn("Strong no", html)
        self.assertIn("Strong yes", html)

    def test_footer(self):
        for text in (build_report_md(copy.deepcopy(FINAL)), visible(build_report_html(copy.deepcopy(FINAL)))):
            self.assertIn("Hiring Panel v1.0.0 · free and open source · not affiliated with Anthropic or any ATS vendor", text)


class TestHonestyRules(ReportCase):
    def all_text(self, report):
        out = self.render(report)
        with open(out["files"]["md"], encoding="utf-8") as f:
            md = f.read()
        with open(out["files"]["html"], encoding="utf-8") as f:
            html = visible(f.read())
        return md + "\n" + html + "\n" + pdf_text(out["files"]["pdf"])

    def test_zero_invented_facts_only_when_script_passed(self):
        self.assertIn("0 invented facts", self.all_text(FINAL))
        for tc in ({"ran": "model_only", "passed": None, "invented_facts": None, "bullets_traced": 0, "bullets_total": 8, "provenance": "self"},
                   {"ran": "script", "passed": False, "invented_facts": 2, "bullets_traced": 6, "bullets_total": 8, "provenance": "not_run"},
                   {"ran": "not_run", "passed": None, "invented_facts": None, "bullets_traced": 0, "bullets_total": 0, "provenance": "not_run"},
                   {"ran": "model_only", "passed": True, "invented_facts": 0, "bullets_traced": 8, "bullets_total": 8, "provenance": "self"}):
            r = copy.deepcopy(FINAL)
            r["truth_check"] = tc
            text = self.all_text(r)
            self.assertNotIn("0 invented facts", text, tc)
            self.assertNotIn("0 invented", text, tc)
        r = copy.deepcopy(FINAL)
        r["truth_check"]["ran"] = "model_only"
        self.assertIn("Model-only", self.all_text(r))

    def test_one_number_only(self):
        text = self.all_text(FINAL)
        self.assertIn("Simulated screening check", text)
        self.assertIn("60", text)
        self.assertIn("75", text)
        self.assertIn("Overall = 40% file readability + 40% job-keyword match + 20% content signals", text)
        # sub-scores (85, 35, 50, 100, 80) are never printed as numbers; only their bands
        for sub in ("85", "35", "80"):
            self.assertIsNone(re.search(r"(?<![\d.])%s(?![\d%%])" % sub, text), sub)
        self.assertNotRegex(text, r"\b\d+\s*/\s*10\b")      # no per-reviewer scores
        for banned in ("ATS score", "probability", "interview-ready", "Interview-ready", "—"):
            self.assertNotIn(banned, text)

    def test_overall_rounded_to_five(self):
        r = copy.deepcopy(FINAL)
        r["screening"]["before"]["overall"] = 62
        md = build_report_md(r)
        self.assertIn("60 before", md)
        self.assertNotIn("62", md)

    def test_ats_score_wording_is_rewritten(self):
        r = copy.deepcopy(FINAL)
        r["panel"][0]["take"] = "Your ATS score would be low."
        self.assertNotIn("ATS score", self.all_text(r))

    def test_contact_masked_everywhere(self):
        r = copy.deepcopy(FINAL)
        r["weaknesses"][0]["evidence_quote"] = "maya.rivera@example.com (512) 555-0142"
        r["needs_you"][0]["ask"] = "Call +44 20 7946 0958 or write maya.rivera@example.com"
        r["panel"][2]["take"] = "Contact line shows maya.rivera@example.com and (512) 555-0142."
        text = self.all_text(r)
        for raw in ("maya.rivera@example.com", "555-0142", "7946 0958"):
            self.assertNotIn(raw, text)
        self.assertIn("m***@e***.com", text)

    def test_sequential_mode_always_discloses(self):
        for mode in ("sequential", "lite", "manual"):
            r = copy.deepcopy(FINAL)
            r["mode"], r["mode_note"] = mode, ""
            text = self.all_text(r)
            self.assertTrue("less independent" in text or "by hand" in text, mode)
            onepage = visible(build_report_html(r, onepage=True))
            self.assertTrue("less independent" in onepage or "by hand" in onepage, mode)

    def test_general_review_label(self):
        r = copy.deepcopy(FINAL)
        r["general_review"] = True
        text = self.all_text(r)
        self.assertIn("General review", text)
        self.assertIn("no posting provided", text)

    def test_panel_stage(self):
        text = self.all_text(PANEL)
        self.assertIn("rewrite not done yet", text)
        self.assertIn("Open", text)
        self.assertNotIn("invented facts", text)
        self.assertNotIn("Fixed", visible(build_report_html(copy.deepcopy(PANEL), onepage=True)))
        # Live test 4.4: no question count in the tile (the batch asked in chat can differ).
        onepage = visible(build_report_html(copy.deepcopy(PANEL), onepage=True))
        self.assertIn("Answer a few questions in chat", onepage)
        self.assertIsNone(re.search(r"Answer \d+ question", onepage))


class TestStrongAndFirstImpression(ReportCase):
    """Right under the verdict strip: the strong-resume line (only when strong_resume is true) and the
    Recruiter's 7-second first impression (ARCHITECTURE.md sections 17.4 and 17.5)."""
    LABEL = "What a recruiter sees in 7 seconds"
    LINE = ("Strong resume. The Skeptic came closest to saying no: Weak openers slow the skim. It still held "
            "because that is a minor issue, not a critical or major one.")

    def strong(self):
        r = copy.deepcopy(FINAL)
        r["strong_resume"] = True
        r["verdict_strip"]["strong_line"] = self.LINE
        return r

    def texts(self, report):
        out = self.render(report)
        with open(out["files"]["md"], encoding="utf-8") as f:
            md = f.read()
        with open(out["files"]["html"], encoding="utf-8") as f:
            html = visible(f.read())
        return {"md": md, "html": html, "onepage": visible(build_report_html(copy.deepcopy(report), onepage=True)),
                "pdf": pdf_text(out["files"]["pdf"])}

    def test_first_impression_right_under_the_strip(self):
        fi = FINAL["first_impression"]
        t = self.texts(FINAL)
        self.assertIn("- **%s:** \u201c%s\u201d" % (self.LABEL, fi), t["md"])
        self.assertLess(t["md"].index(self.LABEL), t["md"].index("## Biggest weaknesses"))
        self.assertLess(t["md"].index("- **Mode:**"), t["md"].index(self.LABEL))
        for key in ("html", "onepage"):
            self.assertIn(self.LABEL, t[key])
            self.assertIn("\u201c%s\u201d" % fi, t[key])
            self.assertLess(t[key].index("Mode:"), t[key].index(self.LABEL))
            self.assertLess(t[key].index(self.LABEL), t[key].index("Biggest weaknesses"))
        self.assertIn(self.LABEL.upper(), t["pdf"])
        self.assertIn("strong on tools", t["pdf"])

    def test_first_impression_absent(self):
        for value in (None, "", 7, ["x"]):
            r = copy.deepcopy(FINAL)
            r["first_impression"] = value
            t = self.texts(r)
            for key in ("md", "html", "onepage"):
                self.assertNotIn(self.LABEL, t[key], (value, key))
            self.assertNotIn(self.LABEL.upper(), t["pdf"], value)
        r = copy.deepcopy(FINAL)
        del r["first_impression"]
        self.assertNotIn(self.LABEL, build_report_md(r))

    def test_first_impression_masked(self):
        r = copy.deepcopy(FINAL)
        r["first_impression"] = "Marketing student; maya.rivera@example.com and (512) 555-0142 in the header."
        t = self.texts(r)
        for key, text in t.items():
            for raw in ("maya.rivera@example.com", "555-0142"):
                self.assertNotIn(raw, text, key)
        self.assertIn("m***@e***.com", t["html"])

    def test_strong_line_only_when_strong(self):
        t = self.texts(self.strong())
        for key in ("md", "html", "onepage", "pdf"):
            self.assertIn("Strong resume.", t[key], key)
            self.assertIn("came closest to saying no: Weak openers slow the skim.", t[key], key)
        for key in ("html", "onepage"):
            self.assertLess(t[key].index("Strong resume."), t[key].index(self.LABEL))
            self.assertLess(t[key].index("Strong resume."), t[key].index("Biggest weaknesses"))
        self.assertIn("- **Strong resume.** The Skeptic came closest", t["md"])
        # Never flatter otherwise: the renderer shows the line only when report_build said strong.
        for strong, line in ((False, self.LINE), ("yes", self.LINE), (1, self.LINE), (True, ""), (True, None)):
            r = self.strong()
            r["strong_resume"], r["verdict_strip"]["strong_line"] = strong, line
            t = self.texts(r)
            for key, text in t.items():
                self.assertNotIn("Strong resume", text, (strong, line, key))
                self.assertNotIn("came closest", text, (strong, line, key))

    def test_strong_line_fits_one_page(self):
        info = self.render(self.strong())
        self.assertEqual(info["pages"], 1)
        info = self.render(STRESS, sub="stress")
        self.assertEqual(info["pages"], 1)
        self.assertIn("Strong resume.", pdf_text(info["files"]["pdf"]))


def _visible_items(html):
    """The text of each <li> in an HTML fragment, tags removed and entities decoded."""
    import html as _h
    return [_h.unescape(re.sub(r"<[^>]+>", "", li)).strip() for li in re.findall(r"(?s)<li>(.*?)</li>", html)]


class TestLiveTestFixes(ReportCase):
    """Display fixes from the live end-to-end tests (A11, A13, 4.4, 5.4, 6.13, 6.16, A24)."""

    def texts(self, report):
        out = self.render(report)
        with open(out["files"]["md"], encoding="utf-8") as f:
            md = f.read()
        with open(out["files"]["html"], encoding="utf-8") as f:
            html = f.read()
        return {"md": md, "html": visible(html), "raw_onepage": build_report_html(copy.deepcopy(report), onepage=True),
                "onepage": visible(build_report_html(copy.deepcopy(report), onepage=True)),
                "pdf": pdf_text(out["files"]["pdf"])}

    def test_panel_legend_everywhere(self):
        t = self.texts(FINAL)
        for k in ("md", "html", "onepage", "pdf"):
            self.assertIn("Verdict: how each reviewer rates the resume through their own lens.", t[k], k)
            self.assertIn("Move forward: whether they would pass it on.", t[k], k)

    def test_no_dot_is_red(self):
        html = build_report_html(copy.deepcopy(FINAL), onepage=True)
        self.assertIn(".dots i.no { background: #F04438; }", html)

    def test_improved_status_chip(self):
        r = copy.deepcopy(FINAL)
        r["weaknesses"][0]["status"] = "improved"
        t = self.texts(r)
        for k in ("md", "html", "onepage", "pdf"):
            self.assertIn("Improved", t[k], k)
        self.assertIn("color:#175CD3;background:#EFF8FF", t["raw_onepage"])

    def test_mixed_line_under_the_strip(self):
        r = copy.deepcopy(FINAL)
        r["verdict_strip"]["mixed_line"] = "The screening check reads the file and keywords; the panel reads the whole story."
        t = self.texts(r)
        for k in ("md", "html", "onepage", "pdf"):
            self.assertIn("the panel reads the whole story", t[k], k)
        r["strong_resume"] = True
        r["verdict_strip"]["strong_line"] = "Strong resume. The Skeptic came closest to saying no."
        self.assertNotIn("whole story", visible(build_report_html(r, onepage=True)))

    def test_self_audit_is_said_in_the_tile(self):
        r = copy.deepcopy(FINAL)
        r["truth_check"]["provenance"] = "self"
        t = self.texts(r)
        for k in ("onepage", "pdf", "md"):
            self.assertIn("same chat, not by a fresh reviewer", t[k], k)
        r["truth_check"]["provenance"] = "subagent"
        self.assertNotIn("same chat", visible(build_report_html(r, onepage=True)))

    def test_underused_hint_only_at_panel_stage(self):
        r = copy.deepcopy(FINAL)
        r["strengths"][0]["underused"] = True       # an old report.json; the renderer still drops it
        self.assertNotIn("Underused", build_report_md(r) + visible(build_report_html(r)))
        p = copy.deepcopy(PANEL)
        p["strengths"] = [{"title": "Real tracking work", "flagged_by": ["ceo"], "underused": True}]
        self.assertIn("Underused", build_report_md(p))

    def test_ids_never_shown(self):
        r = copy.deepcopy(FINAL)
        r["weaknesses"][0]["fix"] = "Write the full name in R26 (R26) and see A:PARSE-014."
        r["changes"]["cut"] = [{"ref": "R19", "text": "opening shift some weekends", "reason": "Space."}]
        t = self.texts(r)
        for k in ("md", "html", "onepage", "pdf"):
            self.assertNotIn("(R26)", t[k], k)
            self.assertNotIn("A:PARSE-014", t[k], k)
            self.assertNotIn("Cut R19", t[k], k)
            self.assertIsNone(re.search(r"\bR19\b", t[k]), k)

    def test_panel_tile_has_no_count(self):
        t = visible(build_report_html(copy.deepcopy(PANEL), onepage=True))
        self.assertIn("Answer a few questions in chat", t)
        from hp.render.report import build_report_pdf_builtin
        lay = build_report_pdf_builtin(copy.deepcopy(PANEL), 0)
        self.assertEqual(len(lay.pages), 1)


class TestClipping(unittest.TestCase):
    """Clipped text prefers whole sentences, then clause and phrase breaks, and never cuts a word."""

    def assertCleanCut(self, shown, source):
        source = re.sub(r"\s+", " ", source).strip()
        body = shown[:-1] if shown.endswith("\u2026") else shown
        self.assertTrue(source.startswith(body), (shown, source))
        nxt = source[len(body):len(body) + 1]
        self.assertFalse(nxt.isalnum() and body[-1:].isalnum(), "cut inside a word: %r" % shown)

    def test_fit_prefers_sentences_then_clauses_then_phrases(self):
        route = "SQL stays labeled as class projects. A small project of your own that uses SQL would close this."
        self.assertEqual(fit(route, 64), "SQL stays labeled as class projects.")
        why = ("The posting asks for SQL experience. I see it in your coursework and skills list, but no line shows "
               "you using it, so I cannot tell how far you got.")
        self.assertEqual(fit(why, 128), "The posting asks for SQL experience. I see it in your coursework and skills "
                                        "list, but no line shows you using it\u2026")
        self.assertEqual(fit("Increased online sales by 300% during the summer sale", 48),
                         "Increased online sales by 300%\u2026")
        self.assertEqual(fit("Short enough.", 40), "Short enough.")
        for text in (route, why, "Increased online sales by 300% during the summer sale",
                     "Supercalifragilisticexpialidocious words without any breaks at all in them ever",
                     "One. Two. Three. Four. Five. Six. Seven. Eight. Nine. Ten. Eleven. Twelve."):
            for n in range(8, len(text) + 2):
                out = fit(text, n)
                self.assertLessEqual(len(out), n, (text, n))
                if n >= 12 and len(text.split()[0]) < n - 1:   # a word longer than the room must be cut
                    self.assertCleanCut(out, text)

    def test_onepage_real_gaps_and_cut_lines_end_cleanly(self):
        for report in (FINAL, STRESS):
            gaps = {x["title"]: x["honest_route"] for x in report["real_gaps"]}
            cuts = {x["ref"]: x["text"] for x in report["changes"]["cut"]}
            for lim in LIMITS:
                html = _section4_html(copy.deepcopy(report), "final", lim, onepage=True)
                checked = 0
                for item in _visible_items(html):
                    m = re.match(r"^Cut (R\d+(?:-R?\d+)?): \u201c(.*)\u201d$", item)
                    if m:
                        self.assertCleanCut(m.group(2), cuts[m.group(1)])
                        checked += 1
                        continue
                    for title, route in gaps.items():
                        head = title if len(title) <= 64 else None
                        if head and item.startswith(head):
                            rest = item[len(head):].lstrip(". ").strip()
                            self.assertCleanCut(rest, route)
                            checked += 1
                self.assertGreater(checked, 0)

    def test_full_report_keeps_whole_text(self):
        md = build_report_md(copy.deepcopy(FINAL))
        for x in FINAL["real_gaps"]:
            self.assertIn(x["honest_route"], md)


class TestPdf(ReportCase):
    def test_builtin_one_page(self):
        for name, report in (("final", FINAL), ("panel", PANEL), ("stress", STRESS)):
            info = self.render(report, sub=name)
            self.assertEqual(info["pdfEngine"], "builtin")
            with open(info["files"]["pdf"], "rb") as f:
                self.assertTrue(f.read(5) == b"%PDF-")
            self.assertEqual(info["pages"], 1, name)
            self.assertIsNone(info["overflow"])
            self.assertEqual(sorted(info["files"]), ["html", "md", "pdf"])
            self.assertTrue(info["files"]["pdf"].endswith("Hiring_Panel_Report.pdf"))

    def test_builtin_pdf_holds_sections_1_to_5(self):
        info = self.render(FINAL)
        text = pdf_text(info["files"]["pdf"])
        for kept in ("BIGGEST WEAKNESSES", "THE PANEL", "SIMULATED SCREENING CHECK", "TRUTH CHECK", "Needs you",
                     "Real gaps", "Automated Screening Check", "Skeptic"):
            self.assertIn(kept, text)
        for dropped in ("Interview prep", "INTERVIEW PREP", "Where the panel disagreed", "WHERE THE PANEL"):
            self.assertNotIn(dropped, text)

    def test_non_latin_candidate_skips_builtin_cleanly(self):
        r = copy.deepcopy(FINAL)
        r["candidate"] = "李明"
        info = self.render(r)
        self.assertIsNone(info["pdfEngine"])
        self.assertTrue(info["pdfSkipped"])
        self.assertTrue(os.path.exists(info["files"]["md"]))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "r", "Hiring_Panel_Report.pdf")))

    @unittest.skipUnless(HAS_BROWSER, "no Chrome/Edge/Brave on this machine")
    def test_chrome_one_page(self):
        for name, report in (("final", FINAL), ("panel", PANEL), ("stress", STRESS)):
            info = self.render(report, engine="chrome", sub=name)
            self.assertTrue(info["pdfEngine"].startswith("chrome:"))
            self.assertEqual(info["pages"], 1, (name, info["log"]))
        info = self.render(FINAL, engine="chrome", sub="final2")
        # The first-impression row under the verdict strip costs a line, so the roomiest density that
        # fits is now 0 or 1 (both keep every weakness's why line and evidence quote).
        self.assertLessEqual(info["density"], 1, "the sample should fit at one of the two roomiest densities")

    def test_garbage(self):
        with self.assertRaises(RenderError):
            render_report(None, self.tmp)
        with self.assertRaises(RenderError):
            render_report([], self.tmp)
        info = render_report({"weaknesses": "x", "panel": [None, 5], "screening": 3, "truth_check": [],
                              "changes": "x", "target": None, "stage": 7}, os.path.join(self.tmp, "g"),
                             pdf_engine="builtin")
        self.assertEqual(info["pages"], 1)
        info = render_report({}, os.path.join(self.tmp, "empty"), pdf_engine="builtin")
        self.assertTrue(os.path.exists(info["files"]["md"]))


if __name__ == "__main__":
    unittest.main()
