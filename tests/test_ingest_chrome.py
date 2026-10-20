"""A realistic PDF printed by headless Chrome, read back through macOS PDFKit (and the built-in reader).

Skipped unless /Applications/Google Chrome.app exists and the platform is macOS. The resume is
fictional. Chrome runs with a throwaway profile, no first-run UI and no header/footer, and only ever
opens the local HTML file written by this test.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "fixtures"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "plugins", "hiring-panel", "skills", "hiring-panel", "scripts"))

from hp.ingest import ingest_file, needs_transcription  # noqa: E402
from hp.ingest.pdf_text import pdfkit_available  # noqa: E402

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

RESUME_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>Resume</title>
<style>
body{font-family:Helvetica,Arial,sans-serif;font-size:11pt;margin:0.6in;line-height:1.3}
h1{font-size:20pt;margin:0} h2{font-size:12pt;text-transform:uppercase;border-bottom:1px solid #333;margin:14pt 0 4pt}
.row{display:flex;justify-content:space-between} ul{margin:2pt 0 6pt 18pt;padding:0}
</style></head><body>
<h1>Avery Quinn</h1>
<p>avery.quinn@example.com | (555) 010-0199 | Columbus, OH</p>
<h2>Education</h2>
<div class="row"><b>Lakeview State University, B.S. Marketing</b><span>Expected May 2027</span></div>
<p>GPA 3.6. Relevant coursework: Consumer Behavior, Marketing Analytics, Statistics</p>
<h2>Experience</h2>
<div class="row"><b>Social Media Intern, Northwind Foods</b><span>Jun 2025 &ndash; Aug 2025</span></div>
<ul><li>Planned 24 Instagram posts and grew followers 18% in 10 weeks</li>
<li>Wrote weekly reports on reach, saves and comments for the brand manager</li>
<li>Filmed and edited 6 short videos for a seasonal product launch</li></ul>
<div class="row"><b>Barista, Harbor Coffee Co.</b><span>Sep 2023 &ndash; Present</span></div>
<ul><li>Trained 6 new baristas on drink recipes and opening checklists</li>
<li>Handled the register during the morning rush for about 150 customers</li></ul>
<h2>Projects</h2>
<div class="row"><b>Campus Food Pantry Campaign</b><span>Jan 2025 &ndash; Mar 2025</span></div>
<ul><li>Led a 4-person team that collected 1,200 pounds of donations</li></ul>
<h2>Skills</h2>
<p>Canva, Excel, Google Analytics, Hootsuite, CapCut, Spanish (conversational)</p>
</body></html>
"""


def words(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def recovery(expected_words, got_text):
    """Share of expected words found in the extracted text (multiset, order-free)."""
    pool = {}
    for w in words(got_text):
        pool[w] = pool.get(w, 0) + 1
    hit = 0
    for w in expected_words:
        if pool.get(w, 0) > 0:
            pool[w] -= 1
            hit += 1
    return hit / float(len(expected_words))


@unittest.skipUnless(sys.platform == "darwin" and os.path.exists(CHROME), "needs macOS and Google Chrome")
class ChromePdfTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="hp-chrome-")
        html_path = os.path.join(cls.tmp, "resume.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(RESUME_HTML)
        cls.pdf = os.path.join(cls.tmp, "resume.pdf")
        profile = os.path.join(cls.tmp, "profile")
        args = [CHROME, "--headless=new", "--disable-gpu", "--no-first-run", "--user-data-dir=" + profile,
                "--no-pdf-header-footer", "--print-to-pdf=" + cls.pdf, "file://" + html_path]
        try:
            subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=90)
        except (OSError, subprocess.TimeoutExpired):
            pass
        body = re.sub(r"(?s)<head>.*?</head>", "", RESUME_HTML)
        body = re.sub(r"<[^>]+>", " ", body).replace("&ndash;", " ")
        cls.expected = words(body)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        if not os.path.exists(self.pdf) or os.path.getsize(self.pdf) < 1000:
            self.skipTest("Chrome did not produce a PDF here")

    def test_pdfkit_extraction_quality(self):
        if not pdfkit_available():
            self.skipTest("macOS PDFKit not available")
        doc = ingest_file(self.pdf, pdf_backends=["pdfkit"])
        self.assertEqual(doc["method"], "pdfkit")
        self.assertEqual(doc["format"], "pdf")
        self.assertEqual(doc["pages"], 1)
        text = "\n".join(l["text"] for l in doc["lines"])
        self.assertGreaterEqual(recovery(self.expected, text), 0.98)
        sig = doc["signals"]
        self.assertTrue(sig["text_layer"])
        self.assertFalse(sig["image_only"])
        self.assertFalse(sig["garbled"])
        self.assertEqual(sig["hidden_text"]["pdf_invisible"], 0)
        self.assertGreater(sig["fonts"]["type0"], 0)
        self.assertEqual(sig["fonts"]["type0"], sig["fonts"]["tounicode"])   # Chrome embeds text maps
        self.assertIsNone(sig["design_tool"])
        self.assertIn("Skia", doc["producer"] or "")
        self.assertFalse(needs_transcription(doc))
        self.assertEqual(doc["lines"][0]["text"], "Avery Quinn")

    def test_builtin_reader_on_chrome_output(self):
        doc = ingest_file(self.pdf, pdf_backends=["builtin"])
        self.assertEqual(doc["method"], "builtin-pdf")
        text = "\n".join(l["text"] for l in doc["lines"])
        self.assertGreaterEqual(recovery(self.expected, text), 0.98)
        # Glyph-by-glyph positioning must not come out letter-spaced.
        self.assertEqual(doc["signals"]["letter_spaced"], 0)
        self.assertIn("Social Media Intern, Northwind Foods Jun 2025 \u2013 Aug 2025",
                      [l["text"] for l in doc["lines"]])


if __name__ == "__main__":
    unittest.main()
