"""Resume rendering (hp.render.render_resume): valid .docx, the tab-space fix, layouts, paper, PDF ladder,
determinism, Unicode, placeholders and final-file hygiene. All data is fictional."""
import copy
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import unittest
import zipfile
import zlib
from xml.dom import minidom
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "plugins", "hiring-panel", "skills", "hiring-panel", "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from hp.render import render_resume, RenderError, doctor  # noqa: E402
from hp.render import pdf_engines  # noqa: E402
from hp.render.model import page_setup, compile_resume, file_stem  # noqa: E402

SAMPLE = os.path.join(HERE, "fixtures", "output", "sample")
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
HAS_BROWSER = bool(pdf_engines.browser_candidates())

with open(os.path.join(SAMPLE, "resume.json"), encoding="utf-8") as _f:
    RESUME = json.load(_f)


def tab_dropping_lines(docx_bytes_or_path):
    """What a naive extractor reads: w:t text joined per paragraph, w:tab ignored (like the research probe)."""
    with zipfile.ZipFile(docx_bytes_or_path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    lines = []
    for p in root.iter(W + "p"):
        t = "".join(x.text or "" for x in p.iter(W + "t"))
        if t.strip():
            lines.append(t)
    return lines


def tab_dropping_lines_from_xml(document_xml):
    root = ET.fromstring(document_xml)
    return ["".join(x.text or "" for x in p.iter(W + "t")) for p in root.iter(W + "p")]


def merged_tokens(document_xml):
    """Paragraphs where a w:tab sits between two text runs with no space on either side."""
    root = ET.fromstring(document_xml)
    bad = []
    for p in root.iter(W + "p"):
        seq = []
        for el in p.iter():
            if el.tag == W + "t":
                seq.append(("t", el.text or ""))
            elif el.tag == W + "tab" and el.get(W + "val") is None:
                seq.append(("tab", ""))
        for i, (kind, _v) in enumerate(seq):
            if kind != "tab":
                continue
            before = "".join(v for k, v in seq[:i] if k == "t")
            after = "".join(v for k, v in seq[i + 1:] if k == "t")
            if before and after and not before[-1].isspace() and not after[0].isspace():
                bad.append(before[-20:] + "|" + after[:20])
    return bad


def pdf_text_builtin(path):
    """Text drawn by our builtin writer: inflate content streams and read the (..) Tj strings."""
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


class RenderCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hp-test-out-")
        self.env = dict(os.environ)
        os.environ["HP_AS_OF"] = "2026-10-20"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        os.environ.clear()
        os.environ.update(self.env)

    def render(self, resume=None, sub="out", **kw):
        kw.setdefault("pdf_engine", "builtin")
        return render_resume(copy.deepcopy(resume or RESUME), os.path.join(self.tmp, sub), **kw)


class TestDocx(RenderCase):
    def test_docx_is_valid_and_clean(self):
        info = self.render(formats=("docx",))
        path = info["files"]["docx"]
        self.assertTrue(path.endswith("Maya_Rivera_Resume.docx"))
        with zipfile.ZipFile(path) as z:
            self.assertIsNone(z.testzip())
            names = z.namelist()
            self.assertEqual(names[0], "[Content_Types].xml")
            self.assertNotIn("docProps/app.xml", names)          # no tool branding
            for n in names:
                minidom.parseString(z.read(n))                    # every part is well-formed XML
            doc = z.read("word/document.xml").decode("utf-8")
            core = z.read("docProps/core.xml").decode("utf-8")
            styles = z.read("word/styles.xml").decode("utf-8")
        self.assertIn("<dc:creator>Maya Rivera</dc:creator>", core)
        self.assertNotIn("Hiring Panel", core + doc)
        for hazard in ("<w:tbl", "<w:txbxContent", "<w:drawing", "<w:pict", "<w:vanish", "w:caps", "smallCaps",
                       "<w:hdr", "<w:ftr", 'w:val="FFFFFF"'):
            self.assertNotIn(hazard, doc + styles)
        self.assertNotRegex(doc, r'<w:sz w:val="([0-9]|1[01])"/>')   # nothing under 6 pt
        self.assertIn("EDUCATION", doc)                                # real capitals, not caps formatting
        self.assertIn('w:hanging="216"', doc)                          # real bullets
        self.assertIn('<w:numId w:val="1"/>', doc)

    def test_space_before_every_tab_and_no_merged_tokens(self):
        info = self.render(formats=("docx",))
        with zipfile.ZipFile(info["files"]["docx"]) as z:
            doc = z.read("word/document.xml").decode("utf-8")
        tabs = doc.count("<w:tab/>")
        self.assertGreater(tabs, 5)
        self.assertEqual(doc.count('<w:t xml:space="preserve"> </w:t><w:tab/>'), tabs)
        self.assertEqual(merged_tokens(doc), [])
        lines = tab_dropping_lines(info["files"]["docx"])
        self.assertIn("Hill Country University Austin, TX", lines)
        self.assertIn("Bachelor of Business Administration, Marketing; Minor in Statistics Expected May 2027", lines)
        self.assertIn("Social Media Marketing Intern Summer 2025", lines)
        joined = "\n".join(lines)
        for glued in ("UniversityAustin", "StatisticsExpected", "InternSummer", "Co.Austin", "AssociateSep"):
            self.assertNotIn(glued, joined)

    def test_extractor_catches_the_old_bare_tab(self):
        old = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p>'
               '<w:r><w:t>Hill Country University</w:t></w:r><w:r><w:tab/></w:r><w:r><w:t>Austin, TX</w:t></w:r>'
               '</w:p></w:body></w:document>')
        self.assertEqual(merged_tokens(old), ["l Country University|Austin, TX"])
        self.assertEqual(tab_dropping_lines_from_xml(old), ["Hill Country UniversityAustin, TX"])

    def test_inline_layout_has_no_tabs(self):
        info = self.render(formats=("docx", "md"), layout="inline")
        self.assertEqual(info["layout"], "inline")
        with zipfile.ZipFile(info["files"]["docx"]) as z:
            doc = z.read("word/document.xml").decode("utf-8")
        self.assertNotIn("<w:tab/>", doc)
        self.assertIn("Hill Country University | Austin, TX", tab_dropping_lines(info["files"]["docx"]))

    def test_layout_from_meta(self):
        r = copy.deepcopy(RESUME)
        r["meta"]["layout"] = "inline"
        self.assertEqual(self.render(r, formats=("md",))["layout"], "inline")

    def test_paper_from_locale(self):
        def page_w(resume):
            info = self.render(resume, sub=str(id(resume)), formats=("docx",))
            with zipfile.ZipFile(info["files"]["docx"]) as z:
                return re.search(r'<w:pgSz w:w="(\d+)"', z.read("word/document.xml").decode()).group(1), info
        r = copy.deepcopy(RESUME)
        self.assertEqual(page_w(r)[0], "12240")                   # en-US -> Letter
        for loc in ("en-GB", "de-DE", "fr_FR", "en-AU"):
            r = copy.deepcopy(RESUME)
            r["meta"]["locale"] = loc
            w, info = page_w(r)
            self.assertEqual((loc, w, info["paper"]), (loc, "11906", "a4"))
        r = copy.deepcopy(RESUME)
        r["meta"]["locale"] = "en-CA"
        self.assertEqual(page_w(r)[0], "12240")
        r = copy.deepcopy(RESUME)
        r["meta"]["locale"] = "en-GB"
        r["meta"]["pageSize"] = "letter"                              # explicit wins
        self.assertEqual(page_w(r)[0], "12240")

    def test_page_target_rules(self):
        self.assertEqual(page_setup({"meta": {"locale": "en-US"}})["target_pages"], 1)
        self.assertEqual(page_setup({"meta": {"locale": "en-US", "stage": "experienced"}})["target_pages"], 2)
        self.assertIsNone(page_setup({"meta": {"targetPages": None}})["target_pages"])
        self.assertEqual(page_setup({"meta": {"targetPages": 2}})["target_pages"], 2)
        self.assertEqual(page_setup({})["paper"], "letter")
        self.assertEqual(page_setup({"meta": {"locale": "garbage!!"}})["paper"], "letter")

    def test_deterministic_bytes(self):
        a = self.render(sub="a", formats=("docx", "md", "pdf"))
        b = self.render(sub="b", formats=("docx", "md", "pdf"))
        for kind in ("docx", "md", "pdf"):
            with open(a["files"][kind], "rb") as fa, open(b["files"][kind], "rb") as fb:
                self.assertEqual(fa.read(), fb.read(), kind)

    def test_xml_hostile_text(self):
        r = copy.deepcopy(RESUME)
        r["basics"]["name"] = 'Ana <Script> & "Co"'
        r["sections"][1]["items"][0]["bullets"][1]["text"] = "Built R&D tracker for <team> \x0c\x00 with **C++** and 5% > 3%"
        info = self.render(r, formats=("docx", "md", "html"))
        with zipfile.ZipFile(info["files"]["docx"]) as z:
            doc = z.read("word/document.xml").decode("utf-8")
            minidom.parseString(doc)
        self.assertIn("R&amp;D", doc)
        self.assertNotIn("\x0c", doc)
        with open(info["files"]["html"], encoding="utf-8") as f:
            self.assertNotIn("<Script>", f.read())


class TestMarkdownAndHygiene(RenderCase):
    def test_markdown_content(self):
        info = self.render(formats=("md",))
        with open(info["files"]["md"], encoding="utf-8") as f:
            md = f.read()
        self.assertTrue(md.startswith("# Maya Rivera\n"))
        for needle in ("## Education", "## Experience", "## Projects", "## Leadership & Activities", "## Skills",
                       "**Bluebonnet Coffee Co.** | Austin, TX", "*Social Media Marketing Intern* | Summer 2025",
                       "- Created and posted Instagram content 4x a week", "growing the account by about 600 followers",
                       "**Analytics:** Excel (pivot tables, charts), SQL (coursework), Survey design",
                       "linkedin.com/in/maya-rivera-example", "Sep 2023 – Present"):
            self.assertIn(needle, md)
        self.assertNotIn("](", md)          # links are plain text
        self.assertNotIn("—", md)      # no em dashes

    def test_declined_placeholder_uses_honest_text(self):
        info = self.render(formats=("md",))
        with open(info["files"]["md"], encoding="utf-8") as f:
            md = f.read()
        self.assertIn("Designed a 15-question survey and analyzed the responses with pivot tables", md)
        self.assertNotIn("collected", md)

    def test_open_placeholder_warns_and_falls_back(self):
        r = copy.deepcopy(RESUME)
        r["placeholders"]["p2"]["status"] = "open"
        info = self.render(r, formats=("md",))
        self.assertTrue(any("p2" in w for w in info["warnings"]))

    def test_open_placeholder_without_fallback_refuses(self):
        r = copy.deepcopy(RESUME)
        r["placeholders"]["p1"]["status"] = "open"
        r["sections"][1]["items"][0]["bullets"][0].pop("textIfUnknown")
        with self.assertRaises(RenderError):
            self.render(r, formats=("md",))
        draft = self.render(r, sub="draft", formats=("md", "docx"), draft=True)
        self.assertTrue(draft["files"]["md"].endswith("_DRAFT.md"))
        with open(draft["files"]["md"], encoding="utf-8") as f:
            self.assertIn("==\\[ADD: followers gained\\]==", f.read())
        with zipfile.ZipFile(draft["files"]["docx"]) as z:
            self.assertIn('w:highlight w:val="yellow"', z.read("word/document.xml").decode())

    def test_no_braces_or_add_markers_in_final_files(self):
        info = self.render(formats=("docx", "md", "pdf", "html"))
        for kind, path in info["files"].items():
            with open(path, "rb") as f:
                data = f.read()
            if kind == "docx":
                with zipfile.ZipFile(path) as z:
                    data = b"".join(z.read(n) for n in z.namelist())
            if kind == "pdf":
                data = pdf_text_builtin(path).encode("utf-8")
            self.assertNotIn(b"{{", data, kind)
            self.assertNotIn(b"[ADD:", data, kind)

    def test_braces_anywhere_refuse_final_render(self):
        r = copy.deepcopy(RESUME)
        r["basics"]["headline"] = "Student {{oops}}"
        with self.assertRaises(RenderError):
            self.render(r, formats=("md",))

    def test_bad_input_raises_render_error(self):
        for bad in (None, [], {"basics": {}}, {"basics": {"name": "  "}, "sections": []},
                    {"basics": "x", "sections": []}, {"basics": {"name": "A"}, "sections": "x"}):
            with self.assertRaises(RenderError):
                render_resume(bad, os.path.join(self.tmp, "bad"))
        with self.assertRaises(RenderError):
            self.render(formats=("docx", "exe"))
        with self.assertRaises(RenderError):
            self.render(pdf_engine="reportlab")

    def test_messy_but_renderable_input(self):
        r = {"schemaVersion": "1.0", "basics": {"name": "Sam Lee", "links": ["github.com/samlee-example", {"url": ""}, 7]},
             "sections": [None, {"type": "experience", "title": "Experience",
                                 "items": [None, {"id": "x", "org": "Cafe", "bullets": ["Made coffee", None, {"text": None}]}]},
                          {"type": "skills", "groups": [{"items": ["Excel", None, ""]}, 3]},
                          {"type": "custom", "title": "Empty", "items": []}]}
        info = self.render(r, formats=("docx", "md", "pdf"))
        self.assertTrue(info["warnings"])
        with open(info["files"]["md"], encoding="utf-8") as f:
            md = f.read()
        self.assertIn("- Made coffee", md)
        self.assertNotIn("Empty", md)

    def test_emoji_warns(self):
        r = copy.deepcopy(RESUME)
        r["sections"][1]["items"][0]["bullets"][1]["text"] = "Grew engagement \U0001F680 and kept spreadsheets → weekly"
        info = self.render(r, formats=("pdf",))
        self.assertTrue(any("emoji" in w for w in info["warnings"]))
        self.assertEqual(info["pdfEngine"], "builtin")

    def test_file_stem(self):
        self.assertEqual(file_stem({"basics": {"name": "Zoë Gonçalves-Müller"}}), "Zoe_Goncalves-Muller_Resume")
        self.assertEqual(file_stem({"basics": {"name": "李明"}}), "My_Resume")
        self.assertEqual(file_stem({"basics": {"name": "A B"}}, draft=True), "A_B_Resume_DRAFT")
        self.assertEqual(file_stem({"basics": {"name": "A"}, "meta": {"fileStem": "../../etc"}}), "A_Resume")


class TestPdf(RenderCase):
    def test_builtin_pdf(self):
        info = self.render(formats=("pdf",))
        self.assertEqual(info["pdfEngine"], "builtin")
        path = info["files"]["pdf"]
        with open(path, "rb") as f:
            data = f.read()
        self.assertTrue(data.startswith(b"%PDF-"))
        self.assertEqual(pdf_engines.pdf_page_count(path), 1)
        self.assertEqual(info["pages"], 1)
        self.assertIsNone(info["overflow"])
        sx = int(re.search(rb"startxref\s+(\d+)", data).group(1))
        self.assertEqual(data[sx:sx + 4], b"xref")
        for off in re.findall(rb"(\d{10}) 00000 n", data):
            self.assertRegex(data[int(off):int(off) + 12], rb"^\d+ 0 obj")
        text = pdf_text_builtin(path)
        self.assertIn("Hill Country University ", text)
        self.assertNotIn("1 1 1 rg", zlib.decompress(re.search(rb"stream\n(.*?)\nendstream", data, re.S).group(1)).decode("latin-1"))

    def test_overflow_reported(self):
        r = copy.deepcopy(RESUME)
        r["sections"][1]["items"][0]["bullets"] += [
            {"id": "x%d" % i, "text": "Extra bullet number %d that takes most of a line on the page, more or less" % i,
             "evidence": [{"src": "orig", "ref": "R11"}]} for i in range(40)]
        info = self.render(r, formats=("pdf",))
        self.assertGreaterEqual(info["pages"], 2)
        self.assertIn("target is 1", info["overflow"])

    def test_no_page_target(self):
        r = copy.deepcopy(RESUME)
        r["meta"]["targetPages"] = None
        r["sections"][1]["items"][0]["bullets"] *= 20
        info = self.render(r, formats=("pdf",))
        self.assertGreaterEqual(info["pages"], 2)
        self.assertIsNone(info["overflow"])

    def test_latin1_name_builtin(self):
        r = copy.deepcopy(RESUME)
        r["basics"]["name"] = "Zoë Gonçalves-Müller"
        info = self.render(r, formats=("pdf",))
        self.assertEqual(info["pdfEngine"], "builtin")

    def test_non_latin1_name_builtin_refuses_cleanly(self):
        r = copy.deepcopy(RESUME)
        r["basics"]["name"] = "Nguyễn Thị Minh 李明"
        info = self.render(r, formats=("docx", "md", "pdf"))
        self.assertIsNone(info["pdfEngine"])
        self.assertIn("Save As", info["pdfSkipped"])
        self.assertNotIn("pdf", info["files"])
        self.assertTrue(os.path.exists(info["files"]["docx"]))
        self.assertTrue(info["files"]["docx"].endswith("Nguyen_Thi_Minh_Resume.docx"))
        self.assertFalse(any(f.endswith(".pdf") for f in os.listdir(os.path.dirname(info["files"]["docx"]))))
        with open(info["files"]["md"], encoding="utf-8") as f:
            self.assertIn("Nguyễn", f.read())

    def test_engine_env_restriction(self):
        os.environ["HP_PDF_ENGINES"] = "builtin"
        info = self.render(formats=("pdf",), pdf_engine="auto")
        self.assertEqual(info["pdfEngine"], "builtin")

    def test_network_is_never_used(self):
        real = socket.socket
        def boom(*a, **k):
            raise AssertionError("network access attempted")
        socket.socket = boom
        try:
            info = self.render(formats=("docx", "md", "pdf"))
            self.assertEqual(info["pdfEngine"], "builtin")
        finally:
            socket.socket = real

    def test_doctor(self):
        env = doctor()
        self.assertIn("builtin", env["pdf_engines"])
        json.dumps(env)

    @unittest.skipUnless(HAS_BROWSER, "no Chrome/Edge/Brave on this machine")
    def test_chrome_pdf_one_page_and_scrubbed(self):
        info = self.render(formats=("pdf",), pdf_engine="chrome")
        self.assertTrue(info["pdfEngine"].startswith("chrome:"))
        self.assertEqual(info["pages"], 1)
        with open(info["files"]["pdf"], "rb") as f:
            data = f.read()
        self.assertTrue(data.startswith(b"%PDF-"))
        m = re.search(rb"/Creator\s*\(((?:\\.|[^\\)])*)\)", data)
        if m:
            self.assertEqual(m.group(1).strip(), b"")

    @unittest.skipUnless(HAS_BROWSER, "no Chrome/Edge/Brave on this machine")
    def test_chrome_handles_non_latin_names(self):
        r = copy.deepcopy(RESUME)
        r["basics"]["name"] = "Nguyễn Thị Minh"
        info = self.render(r, formats=("pdf",), pdf_engine="auto")
        self.assertTrue(info["pdfEngine"].startswith("chrome:"))

    def test_compile_blocks_shape(self):
        blocks, warnings, setup = compile_resume(copy.deepcopy(RESUME))
        kinds = [b["k"] for b in blocks]
        self.assertEqual(kinds[:3], ["name", "headline", "contact"])
        self.assertEqual(kinds.count("h"), 5)
        self.assertEqual(setup["layout"], "classic")
        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
