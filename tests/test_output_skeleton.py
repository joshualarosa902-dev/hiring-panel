"""assets/docx-skeleton (manual mode) matches what the renderer writes and zips into a valid .docx."""
import io
import os
import re
import sys
import unittest
import zipfile
from xml.dom import minidom

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SKILL = os.path.join(ROOT, "plugins", "hiring-panel", "skills", "hiring-panel")
SCRIPTS = os.path.join(SKILL, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from hp.render.docx import static_parts, document_rels_xml  # noqa: E402
from hp.render.model import page_setup  # noqa: E402

SK = os.path.join(SKILL, "assets", "docx-skeleton")
PARTS = ["[Content_Types].xml", "_rels/.rels", "docProps/core.xml", "word/_rels/document.xml.rels",
         "word/numbering.xml", "word/settings.xml", "word/styles.xml"]


def read(rel):
    with open(os.path.join(SK, rel), encoding="utf-8") as f:
        return f.read()


class TestSkeleton(unittest.TestCase):
    def test_all_parts_present_and_well_formed(self):
        for rel in PARTS:
            minidom.parseString(read(rel).encode("utf-8"))
        self.assertFalse(os.path.exists(os.path.join(SK, "word", "document.xml")),
                         "document.xml is written by Claude in manual mode; never ship a sample one")
        self.assertFalse(os.path.exists(os.path.join(SK, "docProps", "app.xml")))

    def test_matches_renderer(self):
        setup = page_setup({"meta": {"locale": "en-US"}})
        for arc, content in static_parts(setup) + [("word/_rels/document.xml.rels", document_rels_xml([]))]:
            self.assertEqual(read(arc), content, arc + " drifted from hp/render/docx.py; regenerate the skeleton")

    def test_core_has_no_branding(self):
        core = read("docProps/core.xml")
        self.assertNotIn("Hiring Panel", core)
        self.assertIn("<dc:creator></dc:creator>", core)

    def test_recipes_zip_into_valid_docx(self):
        recipes = read("RECIPES.md")
        self.assertIn("A space before every tab", recipes)
        self.assertNotIn("—", recipes)
        rpr = re.search(r"```xml\n(<w:rPr>.*?</w:rPr>)\n```", recipes, re.S).group(1)
        wrapper = re.search(r"```xml\n(<\?xml.*?</w:document>)\n```", recipes, re.S).group(1)
        blocks = re.findall(r"```xml\n(<w:p>.*?</w:p>)\n```", recipes, re.S)
        self.assertGreaterEqual(len(blocks), 7)
        bold = rpr.replace("<w:color", "<w:b/><w:bCs/><w:color")
        ital = rpr.replace("<w:color", "<w:i/><w:iCs/><w:color")
        body = "".join(b.replace("RPR-BOLD", bold).replace("RPR-ITALIC", ital).replace("RPR", rpr) for b in blocks)
        document = wrapper.replace("  ... paragraphs ...", body)
        self.assertNotIn("RPR", document)
        minidom.parseString(document.encode("utf-8"))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", read("[Content_Types].xml"))
            for rel in PARTS[1:]:
                z.writestr(rel, read(rel))
            z.writestr("word/document.xml", document)
        with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as z:
            self.assertIsNone(z.testzip())
            self.assertEqual(z.namelist()[0], "[Content_Types].xml")
            doc = z.read("word/document.xml").decode("utf-8")
        self.assertEqual(doc.count("<w:tab/>"), doc.count('<w:t xml:space="preserve"> </w:t><w:tab/>'))


if __name__ == "__main__":
    unittest.main()
