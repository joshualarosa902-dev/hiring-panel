"""hp.ingest under hostile input: size limits, zip bombs, entity tricks, fuzzed and mutated bytes,
no network access, performance and deterministic fixtures. Nothing here may raise."""
import io
import json
import os
import random
import socket
import sys
import tempfile
import time
import unittest
import zipfile
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "fixtures"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "plugins", "hiring-panel", "skills", "hiring-panel", "scripts"))

import make_fixtures  # noqa: E402
from hp.ingest import ingest_file, ingest_text, doc_to_resume_md, ats_view_text  # noqa: E402
from hp.ingest import limits  # noqa: E402
from hp.ingest.limits import SafeZip, RefusedInput, parse_xml  # noqa: E402

TOP_KEYS = ["format", "sha256", "bytes", "pages", "producer", "creator", "method", "lines", "header_footer",
            "text_chars", "words", "signals", "warnings", "errors"]


class Workspace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.n = 0

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, data, name="x.bin"):
        self.n += 1
        path = os.path.join(self.tmp.name, "%d-%s" % (self.n, name))
        with open(path, "wb") as f:
            f.write(data)
        return path

    def assert_sane(self, doc, label=""):
        self.assertEqual(list(doc.keys()), TOP_KEYS, label)
        self.assertNotIn("internal_error", [e["code"] for e in doc["errors"]], "%s %s" % (label, doc["errors"]))
        json.dumps(doc, ensure_ascii=False).encode("utf-8")
        doc_to_resume_md(doc).encode("utf-8")
        ats_view_text(doc).encode("utf-8")


class LimitsTest(Workspace):
    def test_file_over_15_mb_is_not_read(self):
        path = os.path.join(self.tmp.name, "huge.pdf")
        with open(path, "wb") as f:
            f.write(b"%PDF-1.4\n")
            f.truncate(limits.MAX_FILE_BYTES + 10)        # sparse: cheap to create
        start = time.time()
        doc = ingest_file(path)
        self.assertLess(time.time() - start, 3.0)
        self.assertEqual(doc["errors"][0]["code"], "file_too_large")
        self.assertTrue(doc["signals"]["too_large"])
        self.assertEqual(doc["format"], "pdf")
        self.assertEqual(doc["bytes"], limits.MAX_FILE_BYTES + 10)
        self.assertEqual(doc["lines"], [])
        self.assert_sane(doc)

    def test_file_over_parse_limit_is_flagged_but_read(self):
        text = ("Avery Quinn\n" + "Planned 24 posts and grew followers 18% in 10 weeks\n" * 60000).encode("utf-8")
        self.assertGreater(len(text), limits.PARSE_LIMIT_BYTES)
        doc = ingest_file(self.write(text, "big.txt"))
        self.assertTrue(doc["signals"]["too_large"])
        self.assertEqual(doc["lines"][0]["text"], "Avery Quinn")
        self.assertTrue(any("truncated" in w for w in doc["warnings"]))     # MAX_LINES cap
        self.assert_sane(doc)

    def test_too_many_zip_entries(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("word/document.xml", "<w:document/>")
            for i in range(limits.MAX_ZIP_ENTRIES + 1):
                z.writestr("x/%d" % i, "")
        doc = ingest_file(self.write(buf.getvalue(), "many.docx"))
        self.assertEqual(doc["errors"][0]["code"], "zip_bomb")

    def test_inflated_budget_is_enforced_on_read(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("a.xml", b"<a>" + b" " * 5000 + b"</a>")
        sz = SafeZip(buf.getvalue())
        sz.remaining = 100
        with self.assertRaises(RefusedInput) as ctx:
            sz.read("a.xml")
        self.assertEqual(ctx.exception.code, "zip_bomb")

    def test_lying_zip_header(self):
        """Declared sizes say 10 bytes; the entry really inflates to 2 MB. Reading stops at the declared
        size and the CRC check turns it into a refusal, not a crash."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("word/document.xml", b" " * (2 * 1024 * 1024))
        data = bytearray(buf.getvalue())
        real = (2 * 1024 * 1024).to_bytes(4, "little")
        idx = 0
        while True:
            idx = data.find(real, idx)
            if idx < 0:
                break
            data[idx:idx + 4] = (10).to_bytes(4, "little")
            idx += 4
        doc = ingest_file(self.write(bytes(data), "liar.docx"))
        self.assertIn(doc["errors"][0]["code"], ("corrupt_file", "zip_bomb"))
        self.assert_sane(doc)

    def test_password_flag_on_zip_entry(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("word/document.xml", "<w:document/>")
        data = bytearray(buf.getvalue())
        # Set the "encrypted" general-purpose flag in the local header (offset 6) and the central
        # directory entry (offset 8), the way a password-protected zip marks its entries.
        local = data.find(b"PK\x03\x04")
        central = data.find(b"PK\x01\x02")
        data[local + 6] |= 0x1
        data[central + 8] |= 0x1
        doc = ingest_file(self.write(bytes(data), "pw.docx"))
        self.assertEqual(doc["errors"][0]["code"], "encrypted")
        self.assertTrue(doc["signals"]["encrypted"])

    def test_dtd_in_any_parsed_part_is_refused(self):
        evil = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><w:hdr/>'
        path = os.path.join(self.tmp.name, "hdr.docx")
        make_fixtures.docx(path, make_fixtures.p("Body"), header="", extra_parts=())
        with zipfile.ZipFile(path) as z:
            parts = [(n, z.read(n)) for n in z.namelist() if n != "word/header1.xml"]
        parts.append(("word/header1.xml", evil))
        make_fixtures.write_zip(path, parts)
        doc = ingest_file(path)
        self.assertEqual(doc["errors"][0]["code"], "xml_dtd_refused")
        self.assertEqual(doc["lines"], [])

    def test_parse_xml_refusals(self):
        for raw in (b"<!DOCTYPE a><a/>", b"<?xml version='1.0'?>\n<!ENTITY x 'y'><a/>", b"<!doctype a><a/>"):
            with self.assertRaises(RefusedInput) as ctx:
                parse_xml(raw)
            self.assertEqual(ctx.exception.code, "xml_dtd_refused")
        with self.assertRaises(RefusedInput):
            parse_xml(b"<a><b></a>")
        self.assertEqual(parse_xml(b"<a>&lt;!DOCTYPE in text is fine&gt;</a>").text, "<!DOCTYPE in text is fine>")

    def test_deeply_nested_xml(self):
        depth = 20000
        body = "<w:sdt><w:sdtContent>" * depth + make_fixtures.p("deep") + "</w:sdtContent></w:sdt>" * depth
        path = os.path.join(self.tmp.name, "deep.docx")
        make_fixtures.docx(path, body)
        doc = ingest_file(path)
        self.assert_sane(doc)


class FuzzTest(Workspace):
    """A few hundred random and mutated inputs; ingest must never raise and must stay fast."""

    PREFIXES = [b"", b"PK\x03\x04", b"%PDF-1.4\n", b"{\\rtf1 ", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",
                b"\x89PNG\r\n\x1a\n", b"\xff\xfe", b"\xef\xbb\xbf", b"<html><body>", b"%PDF-1.7\n1 0 obj\n<<"]

    def run_case(self, data, label, backends=("builtin",)):
        start = time.time()
        doc = ingest_file(self.write(data), pdf_backends=list(backends))
        elapsed = time.time() - start
        self.assertLess(elapsed, 8.0, label)
        self.assert_sane(doc, label)
        return doc

    def test_random_bytes(self):
        rng = random.Random(20261020)
        for i in range(160):
            prefix = self.PREFIXES[i % len(self.PREFIXES)]
            size = rng.choice([0, 1, 7, 64, 512, 4096, 20000])
            data = prefix + bytes(rng.getrandbits(8) for _ in range(size))
            self.run_case(data, "random %d" % i)

    def test_mutated_fixtures(self):
        rng = random.Random(7)
        paths = make_fixtures.shared_fixtures()
        names = sorted(n for n in paths if n != "zip_bomb.docx")
        originals = {}
        for n in names:
            with open(paths[n], "rb") as f:
                originals[n] = f.read()
        for i in range(220):
            name = names[i % len(names)]
            data = bytearray(originals[name])
            op = rng.choice(["flip", "truncate", "insert", "dup", "zero"])
            if not data:
                continue
            if op == "flip":
                for _ in range(rng.randint(1, 20)):
                    pos = rng.randrange(len(data))
                    data[pos] ^= 1 << rng.randrange(8)
            elif op == "truncate":
                data = data[:rng.randrange(len(data))]
            elif op == "insert":
                pos = rng.randrange(len(data))
                data[pos:pos] = bytes(rng.getrandbits(8) for _ in range(rng.randint(1, 200)))
            elif op == "dup":
                a = rng.randrange(len(data))
                b = min(len(data), a + rng.randint(1, 400))
                data[a:a] = data[a:b] * rng.randint(2, 5)
            else:
                a = rng.randrange(len(data))
                data[a:a + rng.randint(1, 100)] = b"\x00" * min(100, len(data) - a)
            # most PDF cases use the built-in reader; every 15th also goes through the full ladder
            backends = None if (name.endswith(".pdf") and i % 15 == 0) else ["builtin"]
            self.run_case(bytes(data), "%s %s %d" % (name, op, i), backends=backends or
                          ["pdfplumber", "pypdf", "pdfkit", "builtin"])

    def test_mutated_word_xml(self):
        """Structure-aware: corrupt document.xml inside an otherwise valid package."""
        rng = random.Random(11)
        xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document %s><w:body>%s</w:body>'
               '</w:document>' % (make_fixtures.NS, make_fixtures.student_body()))
        tokens = ["<w:p>", "</w:p>", "<w:r>", "<w:tbl>", "<w:tr><w:tc>", "<w:tab/>", "<w:br/>",
                  "<mc:AlternateContent>", "<w:txbxContent>", "<w:sdt>", "&amp;", "<w:t>", "\x00", "\ud7ff"]
        for i in range(60):
            s = list(xml)
            for _ in range(rng.randint(1, 8)):
                pos = rng.randrange(len(s))
                if rng.random() < 0.5:
                    del s[pos:pos + rng.randint(1, 30)]
                else:
                    s.insert(pos, rng.choice(tokens))
            path = os.path.join(self.tmp.name, "m%d.docx" % i)
            make_fixtures.docx(path, "", document_xml="".join(s).encode("utf-8", "replace"))
            self.assert_sane(ingest_file(path), "word xml %d" % i)

    def test_pathological_text(self):
        for text in ("\n" * 100000, "a" * 500000, "\u2022 " * 100000, "\t".join(["x"] * 50000),
                     "".join(chr(c) for c in range(0x20, 0x3000)), "\ufeff" * 1000 + "Avery"):
            doc = ingest_text(text)
            self.assert_sane(doc, repr(text[:20]))


class NoNetworkTest(unittest.TestCase):
    def test_ingest_never_opens_a_socket(self):
        paths = make_fixtures.shared_fixtures()

        def refuse(*args, **kwargs):
            raise AssertionError("network access attempted")
        with mock.patch.object(socket, "socket", side_effect=refuse), \
                mock.patch.object(socket, "create_connection", side_effect=refuse), \
                mock.patch.object(socket, "getaddrinfo", side_effect=refuse):
            for name, path in sorted(paths.items()):
                doc = ingest_file(path)
                self.assertNotIn("internal_error", [e["code"] for e in doc["errors"]], name)

    def test_urls_in_resumes_are_only_text(self):
        doc = ingest_text("Portfolio: https://example.com/avery\nfile:///etc/passwd")
        self.assertEqual([l["text"] for l in doc["lines"]], ["Portfolio: https://example.com/avery", "file:///etc/passwd"])


class PerformanceTest(unittest.TestCase):
    def test_fixtures_are_fast(self):
        paths = make_fixtures.shared_fixtures()
        for name in ("two_page.docx", "clean.docx", "resume.rtf", "text.pdf", "multipage.pdf"):
            start = time.time()
            ingest_file(paths[name], pdf_backends=["builtin"])
            self.assertLess(time.time() - start, 1.0, name)

    def test_large_generated_docx(self):
        """About 12 pages of bullets still reads in well under the 2 s budget."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "long.docx")
            body = "".join(make_fixtures.bullet("Coordinated %d weekly events for about %d students" % (i, i * 3))
                           for i in range(600))
            make_fixtures.docx(path, body)
            start = time.time()
            doc = ingest_file(path)
            self.assertLess(time.time() - start, 2.0)
            self.assertEqual(len(doc["lines"]), 600)


class FixtureDeterminismTest(unittest.TestCase):
    def test_build_twice_gives_identical_bytes(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            pa = make_fixtures.build_all(a)
            pb = make_fixtures.build_all(b)
            self.assertEqual(sorted(pa), sorted(pb))
            for name in pa:
                with open(pa[name], "rb") as fa, open(pb[name], "rb") as fb:
                    self.assertEqual(fa.read(), fb.read(), name)

    def test_fixture_people_are_fictional(self):
        """Every email is @example.com and every phone number uses the 555-01xx fiction range."""
        import re
        for name, path in make_fixtures.shared_fixtures().items():
            if name in ("zip_bomb.docx",):
                continue
            doc = ingest_file(path, pdf_backends=["builtin"])
            text = doc_to_resume_md(doc)
            for email in re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", text):
                self.assertTrue(email.endswith("@example.com"), (name, email))
            for phone in re.findall(r"\(\d{3}\) \d{3}-\d{4}", text):
                self.assertTrue(phone.startswith("(555) 01"), (name, phone))


if __name__ == "__main__":
    unittest.main()
