"""resume.md and ats_view.txt formats (ARCHITECTURE.md 5.3)."""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "fixtures"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "plugins", "hiring-panel", "skills", "hiring-panel", "scripts"))

import make_fixtures  # noqa: E402
from hp.ingest import ingest_file, ingest_text, doc_to_resume_md, write_ats_view, ats_view_text  # noqa: E402


def handmade_doc():
    doc = ingest_text("placeholder")
    doc["method"] = "docx-xml"
    doc["lines"] = [
        {"text": "Avery Quinn", "style": "Title", "list": False, "bold": True, "where": "body"},
        {"text": "CONTACT", "style": None, "list": False, "bold": False, "where": "textbox"},
        {"text": "Jun 2025 \u2013 Aug 2025 | Social Media Intern", "style": None, "list": False, "bold": False,
         "where": "table"},
        {"text": "\u2022 Planned 24 posts", "style": None, "list": True, "bold": False, "where": "body"},
    ]
    doc["header_footer"] = [{"where": "header", "text": "avery.quinn@example.com"},
                            {"where": "footer", "text": "Page 1"}]
    doc["warnings"] = ['hidden text (white text): "python sql"', "some other warning"]
    return doc


class ResumeMdTest(unittest.TestCase):
    def test_format(self):
        md = doc_to_resume_md(handmade_doc())
        self.assertEqual(md, "[header] avery.quinn@example.com\n[footer] Page 1\n\nAvery Quinn\n"
                             "[text box] CONTACT\nJun 2025 \u2013 Aug 2025 | Social Media Intern\n"
                             "\u2022 Planned 24 posts\n")

    def test_no_header_block(self):
        md = doc_to_resume_md(ingest_text("Avery Quinn\nTeh typo stays"))
        self.assertEqual(md, "Avery Quinn\nTeh typo stays\n")

    def test_empty_document(self):
        self.assertEqual(doc_to_resume_md(ingest_text("")), "\n")

    def test_line_numbering_matches_lines(self):
        """R# ids count the non-empty lines of resume.md: header/footer lines first, then lines[]."""
        doc = ingest_file(make_fixtures.shared_fixtures()["header_contact.docx"])
        nonempty = [l for l in doc_to_resume_md(doc).split("\n") if l.strip()]
        self.assertEqual(len(nonempty), len(doc["header_footer"]) + len(doc["lines"]))
        self.assertTrue(nonempty[0].startswith("[header] "))

    def test_hidden_text_is_not_in_resume_md(self):
        doc = ingest_file(make_fixtures.shared_fixtures()["hidden_text.docx"])
        self.assertNotIn("python sql tableau", doc_to_resume_md(doc))


class AtsViewTest(unittest.TestCase):
    def test_format(self):
        text = ats_view_text(handmade_doc())
        self.assertEqual(text, "# extraction: docx-xml\n# roughly what parsing software reads; order matters\n\n"
                               "Avery Quinn\n[text box] CONTACT\nJun 2025 \u2013 Aug 2025 | Social Media Intern\n"
                               "\u2022 Planned 24 posts\n\n# header/footer (some systems skip this):\n"
                               "[header] avery.quinn@example.com\n[footer] Page 1\n\n"
                               "# hidden text (people can't see it; parsing software still reads it):\n"
                               'hidden text (white text): "python sql"\n')

    def test_no_text_and_no_header(self):
        doc = ingest_file(make_fixtures.shared_fixtures()["image_only.pdf"], pdf_backends=["builtin"])
        text = ats_view_text(doc)
        self.assertEqual(text, "# extraction: none\n# roughly what parsing software reads; order matters\n\n"
                               "# (no text could be extracted)\n\n# header/footer (some systems skip this):\n# (none)\n")

    def test_write(self):
        doc = handmade_doc()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "work", "inputs", "ats_view.txt")
            self.assertEqual(write_ats_view(doc, path), path)
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), ats_view_text(doc))

    def test_every_fixture_renders(self):
        for name, path in sorted(make_fixtures.shared_fixtures().items()):
            doc = ingest_file(path, pdf_backends=["builtin"])
            with self.subTest(fixture=name):
                view = ats_view_text(doc)
                self.assertTrue(view.startswith("# extraction: %s\n" % doc["method"]))
                view.encode("utf-8")
                doc_to_resume_md(doc).encode("utf-8")


if __name__ == "__main__":
    unittest.main()
