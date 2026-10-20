"""examples/sample-run stays complete, consistent and in sync with the code.

The sample is a real run of the CLI on the fictional e2e fixture. Rebuilding its report from its own
work/ files must give back the committed report.json byte for byte, so the example can never drift
from what the scripts produce.
"""
import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "fixtures", "e2e"))
import support as S  # noqa: E402

sys.path.insert(0, S.SCRIPTS)

SAMPLE = os.path.join(S.ROOT, "examples", "sample-run")
DELIVERABLES = ("Riley_Castellano_Resume.docx", "Riley_Castellano_Resume.pdf", "Riley_Castellano_Resume.md",
                "Hiring_Panel_Report.pdf", "Hiring_Panel_Report.md", "Hiring_Panel_Report.html")
WORK = ("state.json", "inputs/resume.md", "inputs/ats_view.txt", "inputs/jd.md", "inputs/ledger.json",
        "screening/before/screening.json", "screening/before/brief.json", "synthesis.json", "answers.json",
        "rewrite/resume.json", "rewrite/truth.json", "rewrite/provenance.json", "gate.json", "report.json")


class SampleRunTest(unittest.TestCase):
    def test_complete(self):
        for name in DELIVERABLES + ("README.md", "inputs/resume.docx", "inputs/jd.txt",
                                    "panel-stage/Hiring_Panel_Report.pdf"):
            self.assertTrue(os.path.isfile(os.path.join(SAMPLE, name)), name)
        for rel in WORK:
            self.assertTrue(os.path.isfile(os.path.join(SAMPLE, "work", rel)), rel)
        for rid in S.REVIEWER_IDS:
            self.assertTrue(os.path.isfile(os.path.join(SAMPLE, "work", "reviews", rid + ".json")), rid)

    def test_report_is_valid_and_consistent(self):
        from hp.report_build import validate_report
        report = S.load(os.path.join(SAMPLE, "work", "report.json"))
        self.assertEqual(validate_report(report), [])
        self.assertEqual(validate_report(S.load(os.path.join(SAMPLE, "panel-stage", "report.panel.json"))), [])
        before = S.load(os.path.join(SAMPLE, "work", "screening", "before", "screening.json"))
        synth = S.load(os.path.join(SAMPLE, "work", "synthesis.json"))
        self.assertEqual(report["screening"]["before"]["overall"], before["scores"]["overall"]["value"])
        v = synth["panel_vote"]
        self.assertEqual(report["verdict_strip"]["vote_label"], "%d of %d would move you forward" % (v["advance"], v["total"]))
        self.assertTrue(report["truth_check"]["passed"])
        self.assertTrue(S.load(os.path.join(SAMPLE, "work", "gate.json"))["passed"])

    def test_fictional_and_masked(self):
        for here, _dirs, files in os.walk(SAMPLE):
            for name in files:
                if not name.endswith((".md", ".json", ".txt", ".html")):
                    continue
                text = S.read(os.path.join(here, name))
                for email in re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", text):
                    self.assertTrue(email.endswith("example.com"), (name, email))
        for name in ("Hiring_Panel_Report.md", "Hiring_Panel_Report.html", "work/report.json"):
            text = S.read(os.path.join(SAMPLE, name))
            self.assertNotIn("riley.castellano@example.com", text)
            self.assertNotIn("010-0147", text.replace("***-***-0147", ""))
            self.assertNotIn("{{", text)

    def test_rebuilding_the_report_reproduces_it(self):
        tmp = tempfile.mkdtemp(prefix="hp-sample-")
        try:
            run = os.path.join(tmp, "run")
            shutil.copytree(SAMPLE, run)
            r = S.hp(["report", run], tmp, S.env(pdf_engines="builtin"))
            self.assertEqual(r.code, 0, r)
            for rel in ("work/report.json", "Hiring_Panel_Report.md", "Hiring_Panel_Report.html"):
                self.assertEqual(S.read(os.path.join(run, rel), "rb"), S.read(os.path.join(SAMPLE, rel), "rb"),
                                 "examples/sample-run/%s is out of date; regenerate it" % rel)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
