"""hp.ingest public API: the Document contract (ARCHITECTURE.md 5.2), determinism, pasted text,
--resume-text merging and the needs-transcription signal. All data is fictional."""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "fixtures"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "plugins", "hiring-panel", "skills", "hiring-panel", "scripts"))

import make_fixtures  # noqa: E402
from hp.ingest import (ingest_file, ingest_text, doc_to_resume_md, write_ats_view,  # noqa: E402
                       needs_transcription, transcription_reason, apply_resume_text)

FORMATS = {"docx", "pdf", "txt", "md", "rtf", "doc", "pages", "odt", "image", "unknown"}
METHODS = {"docx-xml", "pdfplumber", "pypdf", "pdfkit", "builtin-pdf", "text", "rtf", "none"}
SIGNAL_SHAPE = {
    "encrypted": bool, "text_layer": (bool, type(None)), "image_only": bool, "garbled": bool,
    "too_large": bool, "legacy_format": (str, type(None)),
    "images": {"count": int, "large": int, "charts": int, "smartart": int, "small_icons": int},
    "tables": {"count": int, "nested": int, "holds_experience": bool},
    "text_boxes": {"count": int, "chars": int, "has_contact": bool, "has_heading": bool},
    "columns": {"docx_multi_column": bool, "pdf_check": str, "pdf_gutter_pages": list},
    "header_footer": {"has_text": bool, "has_contact": bool},
    "hidden_text": {"vanish": int, "white": int, "tiny": int, "pdf_invisible": int},
    "caps_formatting": int, "fields": {"docproperty": int, "mergefield": int, "ole": int},
    "tracked_changes": int, "comments": int, "symbols": int,
    "fonts": {"type0": int, "tounicode": int, "type3": int},
    "design_tool": (str, type(None)), "private_use_chars": int, "replacement_chars": int,
    "letter_spaced": int, "repeated_footer_lines": int, "tab_merged_tokens": int,
}
TOP_KEYS = ["format", "sha256", "bytes", "pages", "producer", "creator", "method", "lines", "header_footer",
            "text_chars", "words", "signals", "warnings", "errors"]


def check_document(tc, doc):
    """Assert that doc has exactly the contract's keys and types."""
    tc.assertEqual(list(doc.keys()), TOP_KEYS)
    tc.assertIn(doc["format"], FORMATS)
    tc.assertIn(doc["method"], METHODS)
    tc.assertTrue(doc["sha256"] is None or (isinstance(doc["sha256"], str) and len(doc["sha256"]) == 64))
    tc.assertIsInstance(doc["bytes"], int)
    tc.assertTrue(doc["pages"] is None or isinstance(doc["pages"], int))
    for key in ("producer", "creator"):
        tc.assertTrue(doc[key] is None or isinstance(doc[key], str))
    for line in doc["lines"]:
        tc.assertEqual(sorted(line.keys()), ["bold", "list", "style", "text", "where"])
        tc.assertIsInstance(line["text"], str)
        tc.assertTrue(line["text"].strip())
        tc.assertNotIn("\n", line["text"])
        tc.assertTrue(line["style"] is None or isinstance(line["style"], str))
        tc.assertIsInstance(line["list"], bool)
        tc.assertIsInstance(line["bold"], bool)
        tc.assertIn(line["where"], ("body", "table", "textbox"))
    for hf in doc["header_footer"]:
        tc.assertEqual(sorted(hf.keys()), ["text", "where"])
        tc.assertIn(hf["where"], ("header", "footer"))
    tc.assertIsInstance(doc["text_chars"], int)
    tc.assertIsInstance(doc["words"], int)
    sig = doc["signals"]
    tc.assertEqual(sorted(sig.keys()), sorted(SIGNAL_SHAPE.keys()))
    for key, shape in SIGNAL_SHAPE.items():
        if isinstance(shape, dict):
            tc.assertEqual(sorted(sig[key].keys()), sorted(shape.keys()), key)
            for sub, typ in shape.items():
                tc.assertIsInstance(sig[key][sub], typ, "%s.%s" % (key, sub))
                if typ is int:
                    tc.assertNotIsInstance(sig[key][sub], bool, "%s.%s" % (key, sub))
        else:
            tc.assertIsInstance(sig[key], shape, key)
    tc.assertIn(sig["columns"]["pdf_check"], ("performed", "unavailable"))
    tc.assertTrue(all(isinstance(w, str) for w in doc["warnings"]))
    for e in doc["errors"]:
        tc.assertEqual(sorted(e.keys()), ["code", "detail"])
        tc.assertIsInstance(e["code"], str)
        tc.assertIsInstance(e["detail"], str)
    json.dumps(doc, ensure_ascii=False).encode("utf-8")    # serializable, valid UTF-8


class DocumentContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["HP_PDF_BACKENDS"] = "builtin"    # fast and identical on every machine
        cls.paths = make_fixtures.shared_fixtures()

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("HP_PDF_BACKENDS", None)

    def test_every_fixture_matches_the_contract(self):
        for name, path in sorted(self.paths.items()):
            with self.subTest(fixture=name):
                check_document(self, ingest_file(path))

    def test_same_bytes_give_identical_json(self):
        for name in ("clean.docx", "text.pdf", "resume.rtf", "hidden_text.docx", "invisible_text.pdf"):
            a = json.dumps(ingest_file(self.paths[name]), sort_keys=True, ensure_ascii=False)
            b = json.dumps(ingest_file(self.paths[name]), sort_keys=True, ensure_ascii=False)
            self.assertEqual(a, b, name)

    def test_sha256_and_bytes_describe_the_file(self):
        import hashlib
        path = self.paths["clean.docx"]
        with open(path, "rb") as f:
            data = f.read()
        doc = ingest_file(path)
        self.assertEqual(doc["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(doc["bytes"], len(data))

    def test_pathlike_and_bytes_paths(self):
        import pathlib
        doc = ingest_file(pathlib.Path(self.paths["clean.docx"]))
        self.assertEqual(doc["format"], "docx")
        doc = ingest_file(os.fsencode(self.paths["clean.docx"]))
        self.assertEqual(doc["format"], "docx")

    def test_bad_paths_never_raise(self):
        for bad in (None, 0, 3, 1.5, "", "/definitely/not/here.pdf", os.path.dirname(self.paths["clean.docx"])):
            with self.subTest(path=bad):
                doc = ingest_file(bad)
                check_document(self, doc)
                self.assertTrue(doc["errors"])
                self.assertFalse(needs_transcription(doc))   # nothing was read, nothing to transcribe

    def test_text_chars_and_words_cover_body_and_header(self):
        doc = ingest_file(self.paths["header_contact.docx"])
        expected = sum(len(l["text"]) for l in doc["lines"]) + sum(len(h["text"]) for h in doc["header_footer"])
        self.assertEqual(doc["text_chars"], expected)
        self.assertGreater(doc["words"], 20)


class IngestTextTest(unittest.TestCase):
    def test_pasted_text(self):
        doc = ingest_text("Avery Quinn\navery.quinn@example.com\n\nEXPERIENCE\n- Trained 6 new baristas\n")
        check_document(self, doc)
        self.assertEqual(doc["format"], "txt")
        self.assertEqual(doc["method"], "text")
        self.assertEqual([l["text"] for l in doc["lines"]],
                         ["Avery Quinn", "avery.quinn@example.com", "EXPERIENCE", "\u2022 Trained 6 new baristas"])
        self.assertTrue(doc["lines"][-1]["list"])
        self.assertEqual(len(doc["sha256"]), 64)
        self.assertFalse(needs_transcription(doc))

    def test_odd_inputs_never_raise(self):
        for value in (None, "", b"Avery Quinn\nExperience", bytearray(b"x"), 42, "\ud800 lone surrogate",
                      "\x00\x01\x02 control", "x" * 100000, "\u202e right-to-left override"):
            with self.subTest(value=repr(value)[:30]):
                doc = ingest_text(value)
                check_document(self, doc)
                doc_to_resume_md(doc).encode("utf-8")

    def test_verbatim_typos_and_order_kept(self):
        text = "Experiance\nManaged teh register\nEducation\n"
        doc = ingest_text(text)
        self.assertEqual([l["text"] for l in doc["lines"]], ["Experiance", "Managed teh register", "Education"])

    def test_markdown_reading(self):
        doc = ingest_text("# Avery Quinn\n**Barista**, Harbor Coffee Co.\n## Skills\n* Excel\n---\n")
        self.assertEqual([l["text"] for l in doc["lines"]],
                         ["Avery Quinn", "Barista, Harbor Coffee Co.", "Skills", "\u2022 Excel"])
        self.assertEqual(doc["lines"][0]["style"], "Heading 1")
        self.assertEqual(doc["lines"][2]["style"], "Heading 2")


class TranscriptionSignalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["HP_PDF_BACKENDS"] = "builtin"
        cls.paths = make_fixtures.shared_fixtures()

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("HP_PDF_BACKENDS", None)

    def reason(self, name):
        return transcription_reason(ingest_file(self.paths[name]))

    def test_reasons(self):
        self.assertEqual(self.reason("image_only.pdf"), "image_only")
        self.assertEqual(self.reason("image_only.docx"), "image_only")
        self.assertEqual(self.reason("photo.png"), "image_only")
        self.assertEqual(self.reason("type0_no_tounicode.pdf"), "garbled")
        self.assertEqual(self.reason("encrypted_locked.pdf"), "encrypted")
        self.assertEqual(self.reason("encrypted.docx"), "encrypted")
        self.assertEqual(self.reason("legacy.doc"), "legacy_format")
        self.assertEqual(self.reason("entity.docx"), "refused")
        self.assertEqual(self.reason("zip_bomb.docx"), "refused")

    def test_readable_files_do_not_need_transcription(self):
        for name in ("clean.docx", "text.pdf", "resume.rtf", "utf16.txt", "resume.md", "mojibake.txt",
                     "ocr_scan.pdf", "type0_tounicode.pdf"):
            with self.subTest(fixture=name):
                self.assertIsNone(self.reason(name))

    def test_signal_is_an_error_entry(self):
        doc = ingest_file(self.paths["image_only.pdf"])
        entry = [e for e in doc["errors"] if e["code"] == "needs_transcription"]
        self.assertEqual(len(entry), 1)
        self.assertTrue(entry[0]["detail"].startswith("image_only: "))
        self.assertTrue(needs_transcription(doc))
        # It survives a JSON round trip (the integrator may store the doc).
        self.assertTrue(needs_transcription(json.loads(json.dumps(doc))))

    def test_apply_resume_text_keeps_file_signals(self):
        file_doc = ingest_file(self.paths["image_only.pdf"])
        merged = apply_resume_text(file_doc, "Avery Quinn\navery.quinn@example.com\nExperience\n")
        check_document(self, merged)
        self.assertFalse(needs_transcription(merged))
        self.assertTrue(merged["signals"]["image_only"])          # PARSE-001 stays critical
        self.assertEqual(merged["format"], "pdf")
        self.assertEqual(merged["sha256"], file_doc["sha256"])
        self.assertEqual(merged["method"], "text")
        self.assertEqual([l["text"] for l in merged["lines"]], ["Avery Quinn", "avery.quinn@example.com", "Experience"])
        self.assertTrue(any("pasted text may be cleaner" in w for w in merged["warnings"]))
        self.assertTrue(needs_transcription(file_doc))            # the input is not modified


class WriteAtsViewTest(unittest.TestCase):
    def test_write_creates_utf8_file(self):
        import tempfile
        doc = ingest_text("Caf\u00e9 r\u00e9sum\u00e9\nExperience")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sub", "ats_view.txt")
            write_ats_view(doc, path)
            with open(path, "rb") as f:
                data = f.read()
        text = data.decode("utf-8")
        self.assertTrue(text.startswith("# extraction: text\n"))
        self.assertIn("Caf\u00e9 r\u00e9sum\u00e9", text)
        self.assertTrue(text.endswith("\n"))


if __name__ == "__main__":
    unittest.main()
