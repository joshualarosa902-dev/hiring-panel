"""hp.ingest sniffing, plain text/Markdown/HTML, RTF, legacy and image files, and normalization."""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "fixtures"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "plugins", "hiring-panel", "skills", "hiring-panel", "scripts"))

import make_fixtures  # noqa: E402
from hp.ingest import ingest_file, ingest_text, transcription_reason  # noqa: E402
from hp.ingest.sniff import sniff  # noqa: E402
from hp.ingest.normalize import (normalize_line, TextStats, is_garbled, letter_spaced_count,  # noqa: E402
                                 has_date_range, looks_like_heading, repeated_page_lines,
                                 page_number_lines, word_count)
from hp.ingest.plain import decode_bytes  # noqa: E402


def texts(doc):
    return [l["text"] for l in doc["lines"]]


class SniffTest(unittest.TestCase):
    def test_magic_bytes_win_over_extensions(self):
        paths = make_fixtures.shared_fixtures()
        cases = {"clean.docx": "docx", "text.pdf": "pdf", "resume.rtf": "rtf", "legacy.doc": "doc",
                 "photo.png": "image", "utf16.txt": "txt", "resume.md": "md", "encrypted.docx": "docx"}
        for name, fmt in cases.items():
            with open(paths[name], "rb") as f:
                data = f.read()
            with self.subTest(fixture=name):
                self.assertEqual(sniff(data, name)[0], fmt)
                # a wrong extension does not fool the sniffer (except md vs txt, which bytes cannot tell)
                if fmt not in ("txt", "md"):
                    self.assertEqual(sniff(data, "resume.txt")[0], fmt)

    def test_other_signatures(self):
        self.assertEqual(sniff(b"\xff\xd8\xff\xe0" + b"\x00" * 20, "a.jpg")[0], "image")
        self.assertEqual(sniff(b"\x00\x00\x00\x18ftypheic" + b"\x00" * 20, "a.heic")[0], "image")
        self.assertEqual(sniff(b"GIF89a" + b"\x00" * 10, "")[0], "image")
        self.assertEqual(sniff(b"junk before %PDF-1.7 rest", "")[0], "pdf")
        self.assertEqual(sniff(b"\xffWPC" + b"\x00" * 20, "")[:2], ("unknown", "wpd"))
        self.assertEqual(sniff(b"BM not a bitmap but text", "")[0], "txt")
        self.assertEqual(sniff(b"", "x.md")[0], "md")
        self.assertEqual(sniff(b"PK\x03\x04 broken zip", "")[0], "unknown")

    def test_odt_and_pages_containers(self):
        with tempfile.TemporaryDirectory() as tmp:
            odt = os.path.join(tmp, "a.odt")
            make_fixtures.write_zip(odt, [("mimetype", "application/vnd.oasis.opendocument.text"),
                                          ("content.xml", "<x/>")])
            pages = os.path.join(tmp, "a.pages")
            make_fixtures.write_zip(pages, [("Index/Document.iwa", b"\x00\x01")])
            for path, fmt in ((odt, "odt"), (pages, "pages")):
                doc = ingest_file(path)
                self.assertEqual(doc["format"], fmt)
                self.assertEqual(doc["signals"]["legacy_format"], fmt)
                self.assertEqual(transcription_reason(doc), "legacy_format")


class PlainTextTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.paths = make_fixtures.shared_fixtures()

    def test_utf16_with_bom(self):
        doc = ingest_file(self.paths["utf16.txt"])
        self.assertEqual(doc["format"], "txt")
        self.assertEqual(doc["method"], "text")
        self.assertEqual(texts(doc)[0], "Avery Quinn")
        self.assertIn("Caf\u00e9 r\u00e9sum\u00e9 na\u00efve", texts(doc))
        self.assertIn("\u2022 Barista, Harbor Coffee Co. (Sep 2023 \u2013 Present)", texts(doc))

    def test_bomless_utf16_and_cp1252(self):
        self.assertEqual(decode_bytes("Avery Quinn r\u00e9sum\u00e9".encode("utf-16-le"))[0], "Avery Quinn r\u00e9sum\u00e9")
        self.assertEqual(decode_bytes("caf\u00e9 \u2013 ok".encode("cp1252"))[:2], ("caf\u00e9 \u2013 ok", "cp1252"))
        self.assertTrue(decode_bytes(bytes(range(256)) * 4)[2])     # binary

    def test_letter_spaced(self):
        doc = ingest_file(self.paths["letter_spaced.txt"])
        self.assertEqual(doc["signals"]["letter_spaced"], 2)
        self.assertEqual(texts(doc)[0], "A V E R Y Q U I N N")       # read as is; never "fixed"

    def test_placeholder_text_is_read_verbatim(self):
        doc = ingest_file(self.paths["placeholder.txt"])
        self.assertEqual(texts(doc)[:2], ["Your Name", "123 Main St, Anytown"])
        self.assertIn("\u2022 Lorem ipsum dolor sit amet, consectetur.", texts(doc))

    def test_markdown_file(self):
        doc = ingest_file(self.paths["resume.md"])
        self.assertEqual(doc["format"], "md")
        self.assertEqual(texts(doc), ["Avery Quinn", make_fixtures.CONTACT, "Experience",
                                      "Barista, Harbor Coffee Co. | Sep 2023 \u2013 Present",
                                      "\u2022 Trained 6 new baristas on drink recipes", "\u2022 Opened the store on weekends",
                                      "Skills", "Excel, Canva"])
        self.assertEqual(doc["lines"][2]["style"], "Heading 2")

    def test_mojibake_is_garbled_but_still_text(self):
        doc = ingest_file(self.paths["mojibake.txt"])
        self.assertTrue(doc["signals"]["garbled"])
        self.assertIn("garbled_text", [e["code"] for e in doc["errors"]])
        self.assertIsNone(transcription_reason(doc))                 # plain text: nothing else to read

    def test_html_is_read_as_text(self):
        doc = ingest_file(self.paths["resume.html"])
        self.assertEqual(texts(doc), ["Avery Quinn", make_fixtures.CONTACT, "Experience",
                                      "\u2022 Trained 6 new baristas & opened the store", "Skills | Excel"])
        self.assertNotIn("var x", "\n".join(texts(doc)))

    def test_binary_junk_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "x.txt")
            with open(path, "wb") as f:
                f.write(bytes(range(256)) * 20)
            doc = ingest_file(path)
        self.assertEqual(doc["format"], "unknown")
        self.assertEqual(doc["errors"][0]["code"], "unsupported_format")
        self.assertEqual(transcription_reason(doc), "unreadable")

    def test_empty_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "empty.pdf")
            open(path, "wb").close()
            doc = ingest_file(path)
        self.assertEqual(doc["errors"][0]["code"], "empty_file")
        self.assertIsNone(transcription_reason(doc))


class RtfTest(unittest.TestCase):
    def setUp(self):
        self.doc = ingest_file(make_fixtures.shared_fixtures()["resume.rtf"])

    def test_text_and_order(self):
        self.assertEqual(self.doc["format"], "rtf")
        self.assertEqual(self.doc["method"], "rtf")
        self.assertEqual(texts(self.doc), [
            "EXPERIENCE",
            "Barista, Harbor Coffee Co. \u2013 Columbus, OH Sep 2023 \u2013 Present",
            "\u2022 Trained 6 new baristas on drink recipes",
            "Skills | Excel, Canva",
            "Visible after hidden",
            "Caf\u00e9 r\u00e9sum\u00e9 Avery",
        ])
        self.assertEqual(self.doc["lines"][3]["where"], "table")
        self.assertTrue(self.doc["lines"][2]["list"])
        self.assertNotIn("Fictional Author", "\n".join(texts(self.doc)))     # \info is skipped

    def test_header_and_signals(self):
        self.assertEqual(self.doc["header_footer"],
                         [{"where": "header", "text": "Avery Quinn | avery.quinn@example.com | (555) 010-0199"}])
        sig = self.doc["signals"]
        self.assertTrue(sig["header_footer"]["has_contact"])
        self.assertEqual(sig["hidden_text"]["vanish"], 1)
        self.assertEqual(sig["hidden_text"]["white"], 1)
        self.assertEqual(sig["tables"]["count"], 1)
        self.assertEqual(sig["fields"]["mergefield"], 1)
        self.assertEqual(sig["images"]["count"], 1)
        self.assertEqual(sig["tab_merged_tokens"], 1)           # "OH\tSep"; the bullet tab is not counted
        self.assertNotIn("secret hidden keywords", "\n".join(texts(self.doc)))

    def test_unbalanced_and_deep_rtf(self):
        for blob in (b"{\\rtf1 unclosed {{{ text", b"{\\rtf1 " + b"{" * 5000 + b"deep" + b"}" * 10,
                     b"{\\rtf1 \\u-10240? \\'zz \\bin5 abc}", b"{\\rtf1{\\*\\unknowndest secret}shown\\par}"):
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "x.rtf")
                with open(path, "wb") as f:
                    f.write(blob)
                doc = ingest_file(path)
                self.assertNotIn("internal_error", [e["code"] for e in doc["errors"]], blob[:30])
        doc = ingest_text("x")  # sanity: module still importable after the odd inputs
        self.assertEqual(texts(doc), ["x"])


class LegacyAndImageTest(unittest.TestCase):
    def test_legacy_doc(self):
        doc = ingest_file(make_fixtures.shared_fixtures()["legacy.doc"])
        self.assertEqual(doc["format"], "doc")
        self.assertEqual(doc["signals"]["legacy_format"], "doc")
        self.assertEqual(doc["errors"][0]["code"], "legacy_format")
        self.assertIn(".docx", doc["errors"][0]["detail"])

    def test_png(self):
        doc = ingest_file(make_fixtures.shared_fixtures()["photo.png"])
        self.assertEqual(doc["format"], "image")
        self.assertTrue(doc["signals"]["image_only"])
        self.assertFalse(doc["signals"]["text_layer"])
        self.assertEqual(transcription_reason(doc), "image_only")


class NormalizeTest(unittest.TestCase):
    def norm(self, s):
        return normalize_line(s, TextStats())

    def test_spec_normalization(self):
        self.assertEqual(self.norm("\ufb01nance \ufb02ow"), "finance flow")
        self.assertEqual(self.norm("\u201cquoted\u201d \u2018it\u2019s\u2019"), "\"quoted\" 'it's'")
        self.assertEqual(self.norm("2019\u20142023 \u2212 x"), "2019\u20132023 \u2013 x")
        self.assertEqual(self.norm("a\u00a0\u00a0b\t\tc"), "a b c")
        self.assertEqual(self.norm("zero\u200bwidth\u00adsoft"), "zerowidthsoft")

    def test_bullet_glyphs(self):
        for glyph in "\u2022\u25cf\u25aa\u25e6\u2023\u2219\u00b7\u25ba\u25b6\u27a2\u27a4\u2713\u2714\u25a0\u25c6\u2756":
            self.assertEqual(self.norm(glyph + " Led a team"), "\u2022 Led a team", glyph)
        self.assertEqual(self.norm("- Led a team"), "\u2022 Led a team")
        self.assertEqual(self.norm("* Led a team"), "\u2022 Led a team")
        self.assertEqual(self.norm("\u2013 Led a team"), "\u2022 Led a team")
        self.assertEqual(self.norm("\uf0b7 Led a team"), "\u2022 Led a team")       # Word Symbol bullet
        self.assertEqual(self.norm("o Managed the register"), "\u2022 Managed the register")
        self.assertEqual(self.norm("\u2013 Present"), "\u2013 Present")            # split date range kept
        self.assertEqual(self.norm("- May 2024"), "- May 2024")
        self.assertEqual(self.norm("-5 degrees"), "-5 degrees")
        self.assertEqual(self.norm("well-known"), "well-known")

    def test_private_use_and_replacement_counts(self):
        st = TextStats()
        self.assertEqual(normalize_line("\uf095 (555) 010-0199 \ufffd \U000f0001", st), "\u25a1 (555) 010-0199 \ufffd \u25a1")
        self.assertEqual(st.private_use, 2)
        self.assertEqual(st.replacement, 1)
        st = TextStats()
        self.assertEqual(normalize_line("\ud800x", st), "\ufffdx")          # lone surrogate
        self.assertEqual(st.replacement, 1)

    def test_garbled(self):
        self.assertFalse(is_garbled("Planned 24 Instagram posts and grew followers 18% in 10 weeks " * 3))
        self.assertFalse(is_garbled("SQL AWS HTML CSS C++ C# .NET Node.js A/B testing B2B Q3 2025 GPA 3.8 "
                                    "avery.quinn@example.com linkedin.com/in/avery-quinn"))
        self.assertTrue(is_garbled("Jrdn Lqn Mrktng Bcklr Cmmnctns Strtgy Dvlpmnt Anlytcs Rsrch Prjct "
                                   "Mngmnt Prfrmnc Spcls Cmpgns Crtv Wrtng Dsgn Prdctn Brndng Skls"))
        self.assertTrue(is_garbled("text " * 50 + "\ufffd" * 10))
        self.assertTrue(is_garbled(" ".join(["(cid:3)(cid:4)"] * 25)))
        self.assertFalse(is_garbled("\u041e\u043f\u044b\u0442 \u0440\u0430\u0431\u043e\u0442\u044b " * 10))  # Cyrillic is fine
        self.assertFalse(is_garbled(""))

    def test_letter_spacing_and_words(self):
        self.assertEqual(letter_spaced_count("J O R D A N and E X P E R I E N C E but not I am a"), 2)
        self.assertEqual(word_count("Planned 24 posts, grew 18% \u2022 C++ & A/B"), 7)

    def test_date_ranges_and_headings(self):
        for s in ("Jun 2025 - Aug 2025", "June 2025 \u2013 Present", "05/2024 to 08/2024", "2019 \u2013 2023",
                  "Summer 2024 \u2013 Fall 2024", "Sept. 2023 through current"):
            self.assertTrue(has_date_range(s), s)
        self.assertFalse(has_date_range("Call (555) 010-0199"))
        self.assertTrue(looks_like_heading("EXPERIENCE"))
        self.assertTrue(looks_like_heading("Work Experience", bold=True))
        self.assertTrue(looks_like_heading("Profile", style="heading 1"))
        self.assertFalse(looks_like_heading("Managed experience for five clients."))

    def test_page_furniture(self):
        self.assertEqual(page_number_lines(["Page 1 of 2", "2 / 3", "- 4 -", "Page 7", "Planned 24 posts"]), 4)
        pages = [["Avery Quinn | page 1", "Experience", "x", "y", "Footer text"],
                 ["Avery Quinn | page 2", "Skills", "z", "w", "Footer text"]]
        self.assertEqual(repeated_page_lines(pages), 2)
        self.assertEqual(repeated_page_lines(pages[:1]), 0)


if __name__ == "__main__":
    unittest.main()
