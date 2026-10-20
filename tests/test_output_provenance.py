"""Provenance gate (hp.rewrite.provenance): every NEW_WORDING bullet audited, every soften/remove applied."""
import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "plugins", "hiring-panel", "skills", "hiring-panel", "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from hp.rewrite import check_provenance, check_truth  # noqa: E402

SAMPLE = os.path.join(HERE, "fixtures", "output", "sample")


def load(name):
    with open(os.path.join(SAMPLE, name), encoding="utf-8") as f:
        return json.load(f)


LEDGER, ANSWERS, RESUME = load("ledger.json"), load("answers.json"), load("resume.json")
TRUTH = check_truth(LEDGER, ANSWERS, RESUME)
FLAGGED = [w["bullet_id"] for w in TRUTH["warnings"] if w["code"] == "NEW_WORDING"]


def bullets_by_id(resume):
    out = {}
    for sec in resume["sections"]:
        for it in sec.get("items") or []:
            for b in it.get("bullets") or []:
                out[b["id"]] = b
    return out


def audit_all_ok(resume):
    b = bullets_by_id(resume)
    return {"schema_version": "1.0", "auditor": "skeptic-provenance", "mode": "subagent",
            "items": [{"bullet_id": bid, "audited_text": b[bid]["text"], "verdict": "ok", "problem": None,
                       "suggested_text": None} for bid in FLAGGED]}


class TestProvenanceGate(unittest.TestCase):
    def test_sample_has_flagged_bullets(self):
        self.assertTrue(TRUTH["passed"])
        self.assertGreaterEqual(len(FLAGGED), 3)

    def test_full_ok_audit_passes(self):
        out = check_provenance(RESUME, audit_all_ok(RESUME), TRUTH)
        self.assertEqual(out, {"passed": True, "unresolved": [], "missing": [], "errors": []})

    def test_missing_item(self):
        prov = audit_all_ok(RESUME)
        dropped = prov["items"].pop(0)["bullet_id"]
        out = check_provenance(RESUME, prov, TRUTH)
        self.assertFalse(out["passed"])
        self.assertEqual(out["missing"], [dropped])

    def test_no_provenance_file(self):
        out = check_provenance(RESUME, None, TRUTH)
        self.assertFalse(out["passed"])
        self.assertEqual(sorted(out["missing"]), sorted(FLAGGED))

    def test_soften_not_applied_is_unresolved(self):
        prov = audit_all_ok(RESUME)
        prov["items"][0]["verdict"] = "soften"
        prov["items"][0]["problem"] = "'growing the account' implies the posts caused the growth"
        out = check_provenance(RESUME, prov, TRUTH)
        self.assertFalse(out["passed"])
        self.assertEqual(out["unresolved"], [prov["items"][0]["bullet_id"]])

    def test_soften_applied_passes(self):
        prov = audit_all_ok(RESUME)
        prov["items"][0]["verdict"] = "soften"
        resume = copy.deepcopy(RESUME)
        bid = prov["items"][0]["bullet_id"]
        bullets_by_id(resume)[bid]["text"] = bullets_by_id(resume)[bid]["text"].replace("growing the account by",
                                                                                         "while the account gained")
        out = check_provenance(resume, prov, TRUTH)
        self.assertTrue(out["passed"], out)

    def test_remove_applied_by_deleting_bullet(self):
        prov = audit_all_ok(RESUME)
        prov["items"][0]["verdict"] = "remove"
        resume = copy.deepcopy(RESUME)
        bid = prov["items"][0]["bullet_id"]
        for sec in resume["sections"]:
            for it in sec.get("items") or []:
                it["bullets"] = [b for b in it.get("bullets") or [] if b["id"] != bid]
        self.assertTrue(check_provenance(resume, prov, TRUTH)["passed"])

    def test_stale_ok_counts_as_missing(self):
        prov = audit_all_ok(RESUME)
        resume = copy.deepcopy(RESUME)
        bid = prov["items"][1]["bullet_id"]
        bullets_by_id(resume)[bid]["text"] += " for the whole company"
        out = check_provenance(resume, prov, TRUTH)
        self.assertIn(bid, out["missing"])

    def test_ok_audit_of_filled_placeholder_text(self):
        prov = audit_all_ok(RESUME)
        b = bullets_by_id(RESUME)["exp1.b1"]
        for it in prov["items"]:
            if it["bullet_id"] == "exp1.b1":
                it["audited_text"] = b["text"].replace("{{p1}}", "about 600")
        self.assertTrue(check_provenance(RESUME, prov, TRUTH)["passed"])

    def test_truth_not_passed_blocks(self):
        bad = dict(TRUTH, passed=False)
        out = check_provenance(RESUME, audit_all_ok(RESUME), bad)
        self.assertFalse(out["passed"])
        self.assertTrue(out["errors"])

    def test_unknown_verdict(self):
        prov = audit_all_ok(RESUME)
        prov["items"][0]["verdict"] = "maybe"
        out = check_provenance(RESUME, prov, TRUTH)
        self.assertFalse(out["passed"])

    def test_garbage(self):
        for resume, prov, truth in ((None, None, None), (RESUME, "x", TRUTH), (RESUME, {"items": [1, None]}, TRUTH),
                                    (RESUME, audit_all_ok(RESUME), {"warnings": "x"}), ({"sections": 5}, {}, TRUTH)):
            out = check_provenance(resume, prov, truth)
            self.assertIn("passed", out)
            json.dumps(out)


if __name__ == "__main__":
    unittest.main()
