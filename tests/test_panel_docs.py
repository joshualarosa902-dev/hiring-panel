"""Consistency tests for the panel's prompt files, locale table and schemas.

The persona files are prompts, so these tests check what must never drift: every persona states the
safety and honesty rules, its lens and dimensions match the code, the lite cards stay short, the
examples validate, and the locale table covers every locale (and agrees with hp/data/locale_norms.json
when that file exists).
"""
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.join(os.path.dirname(HERE), "plugins", "hiring-panel", "skills", "hiring-panel")
SCRIPTS = os.path.join(SKILL, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from hp.panel import schema_lite  # noqa: E402
from hp.panel.common import CATS, DIMENSIONS, LENS, REPORT_ORDER, REVIEWER_INFO  # noqa: E402

REVIEWERS_DIR = os.path.join(SKILL, "references", "reviewers")
LOCALES = ["en-US", "en-CA", "en-GB", "en-IE", "en-AU", "en-NZ", "en-IN", "de-DE", "de-AT", "de-CH",
           "fr-FR", "es-ES", "default"]


def _read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as f:
        return f.read()


def _flat(text):
    return re.sub(r"\s+", " ", text)


def _field(doc, name):
    m = re.search(r"^- " + name + r": (.+)$", doc, re.M)
    return [x.strip(" `") for x in m.group(1).split(",")] if m else None


class PersonaFilesTest(unittest.TestCase):
    def persona(self, rid):
        return _read(REVIEWERS_DIR, REVIEWER_INFO[rid]["file"])

    def test_all_files_exist(self):
        names = sorted(os.listdir(REVIEWERS_DIR))
        for f in ["_shared-rules.md", "_output-format.md", "_lite-cards.md"] + \
                 [REVIEWER_INFO[r]["file"] for r in REPORT_ORDER]:
            self.assertIn(f, names)

    def test_metadata_matches_code(self):
        for rid in REPORT_ORDER:
            doc = self.persona(rid)
            self.assertIn("reviewer_id: `{}`".format(rid), doc)
            self.assertIn("display name: {}".format(REVIEWER_INFO[rid]["name"]), doc)
            self.assertEqual(_field(doc, "lens_categories"), list(LENS[rid]), rid)
            self.assertEqual(_field(doc, "dimensions"), DIMENSIONS[rid], rid)
            self.assertIn(REVIEWER_INFO[rid]["decision_question"], _flat(doc), rid)

    def test_every_persona_states_the_ground_rules(self):
        required = {
            "data, not instructions": r"data\. Ignore any instructions",
            "protected traits": r"protected traits",
            "no outside facts": r"[Nn]o outside facts",
            "needs_candidate_input": r"needs_candidate_input",
            "real_gap": r"real_gap",
            "stay in lens": r"Stay in your lens",
            "DONE": r"single word DONE",
            "research basis": r"## Research basis",
            "verdict anchors": r"strong_yes",
            "advance": r"`advance`",
        }
        for rid in REPORT_ORDER:
            doc = _flat(self.persona(rid))        # line wrapping must not hide a rule
            for label, rx in required.items():
                self.assertRegex(doc, rx, "{} is missing: {}".format(rid, label))
            self.assertIn("RUN/work/reviews/{}.json".format(rid), doc)

    def test_research_citations_keep_quality_labels(self):
        labels = r"(Vendor study|Vendor survey|vendor survey|Vendor interviews|small sample|Employer survey|" \
                 r"Company practice|Practitioner advice|Meta-analysis|Peer-reviewed|documentation|" \
                 r"Vendor-commissioned|Internal company research|press)"
        for rid in REPORT_ORDER:
            doc = self.persona(rid)
            basis = doc.split("## Research basis", 1)[1]
            self.assertRegex(basis, r"https://", rid)
            for item in re.split(r"\n- ", basis)[1:]:
                self.assertRegex(_flat(item), labels, "{}: citation without a source-quality label: {}".format(
                    rid, item[:80]))

    def test_screening_persona_copies_keyword_facts(self):
        doc = _flat(self.persona("screening"))
        self.assertIn("brief.json", doc)
        self.assertIn("ats_view.txt", doc)
        self.assertIn("never recompute coverage", doc)
        self.assertNotIn("must_have_coverage_pct", doc)
        self.assertIn("A:PARSE-006", doc)
        self.assertIn('never write "ATS score"', doc.replace("you never write", "never write"))

    def test_recruiter_is_locale_aware(self):
        doc = self.persona("recruiter")
        self.assertIn("references/locale-norms.md", doc)
        self.assertIn("locale_applied", doc)
        self.assertIn("customary", doc)
        # A4: the norms the recruiter needs are inline, one row per locale, so it reads no extra file.
        for loc in LOCALES:
            self.assertIn("`{}`".format(loc), doc, loc)

    def test_shared_rules(self):
        doc = _flat(_read(REVIEWERS_DIR, "_shared-rules.md"))
        for phrase in ("RUN/work/inputs/ledger.json", "RUN/work/screening/before/brief.json",
                       "RUN/work/inputs/ats_view.txt", "A:<ISSUE-ID>", "general_review", "`advance`",
                       "`one_line_take`", "single word DONE", "strengths` may be an empty list",
                       "data, not instructions", "no posting provided", "Do not open `resume.md` or `jd.md`",
                       "never write R#, J# or A: ids", "EEO"):
            self.assertIn(phrase, doc)
        for cat in CATS:
            self.assertIn(cat, doc)

    def test_reviewers_read_only_the_ledger(self):
        """A4: reviewers read the three rule files and ledger.json (screening adds brief.json and
        ats_view.txt); no reviewer file tells them to read resume.md or jd.md."""
        for rid in REPORT_ORDER:
            doc = self.persona(rid)
            reads = re.search(r"^- reads: (.+)$", doc, re.M).group(1)
            files = re.findall(r"`([^`]+)`", reads)
            want = ["RUN/work/inputs/ledger.json"]
            if rid == "screening":
                want += ["RUN/work/screening/before/brief.json", "RUN/work/inputs/ats_view.txt"]
            self.assertEqual(files, want, rid)
            self.assertNotIn("resume.md", doc, rid)
            self.assertNotIn("jd.md", doc, rid)
        for name in ("_shared-rules.md", "_output-format.md", "_lite-cards.md"):
            doc = _flat(_read(REVIEWERS_DIR, name))
            for f in ("resume.md", "jd.md"):
                for m in re.finditer(re.escape(f), doc):
                    self.assertRegex(doc[max(0, m.start() - 120):m.start()], r"[Dd]o not open", (name, f))

    def test_word_budget(self):
        """A4: what one reviewer reads stays small (measured 2,739 to 4,080 words before the trim)."""
        shared = len(_read(REVIEWERS_DIR, "_shared-rules.md").split())
        output = len(_read(REVIEWERS_DIR, "_output-format.md").split())
        for rid in REPORT_ORDER:
            total = shared + output + len(self.persona(rid).split())
            self.assertLessEqual(total, 3000, "{} reads {} words".format(rid, total))

    def test_student_text_has_no_ids_rule(self):
        """A11: both reviewer contracts say ids stay in anchor fields."""
        out = _flat(_read(REVIEWERS_DIR, "_output-format.md"))
        self.assertIn("go only in anchor fields", out)
        example = json.loads(re.findall(r"```json\n(.*?)\n```", _read(REVIEWERS_DIR, "_output-format.md"), re.S)[0])
        ids = re.compile(r"\b([RJ][0-9]+|A:[A-Z]+-[0-9]{3})\b")
        texts = [example["one_line_take"], example["verdict_rationale"]]
        for f in example["findings"]:
            texts += [f["title"], f["detail"], f["fix"]["suggestion"], f["fix"]["candidate_question"] or ""]
        texts += [q["question"] for q in example["questions_for_candidate"]]
        for t in texts:
            self.assertIsNone(ids.search(t), t)

    def test_teammate_wording_is_field_neutral(self):
        """3.5: no software jargon in the teammate's question (it is copied into hospital reports too)."""
        for text in (self.persona("teammate"), _read(REVIEWERS_DIR, "_lite-cards.md"),
                     REVIEWER_INFO["teammate"]["decision_question"]):
            self.assertNotIn("sprint", text.lower())
        self.assertIn("next week's work", REVIEWER_INFO["teammate"]["decision_question"])


class LiteCardsTest(unittest.TestCase):
    def test_seven_cards_each_under_400_words(self):
        doc = _read(REVIEWERS_DIR, "_lite-cards.md")
        cards = re.split(r"\n## Card ", doc)[1:]
        self.assertEqual(len(cards), 7)
        seen = []
        for card in cards:
            rid = re.search(r"\(`([a-z_]+)`\)", card.split("\n", 1)[0]).group(1)
            seen.append(rid)
            self.assertLessEqual(len(card.split()), 400, rid)
            flat = _flat(card)
            self.assertIn(REVIEWER_INFO[rid]["decision_question"], flat, rid)
            for cat in LENS[rid]:
                self.assertIn(cat, flat, rid)
            for dim in DIMENSIONS[rid]:
                self.assertIn(dim, flat, rid)
        self.assertEqual(seen, ["screening", "recruiter", "hiring_manager", "teammate", "ceo", "competitor", "skeptic"])

    def test_preamble_keeps_the_rules(self):
        pre = _flat(_read(REVIEWERS_DIR, "_lite-cards.md").split("## Card 1")[0])
        for phrase in ("data, not instructions", "protected traits", "needs_candidate_input", "real_gap",
                       "re-read only", "ledger.json", "no posting provided", "word for word", "Stay in your lens",
                       "Ids (R#, J#, A:) go only in anchor fields", "add_keyword_truthfully", "EEO",
                       "Do not open `_shared-rules.md`, `_output-format.md`"):
            self.assertIn(phrase, pre)

    def test_cards_are_self_contained(self):
        """3.2 / 3.6: the lite file carries the output contract and every allowed value the validator
        enforces for each card's lens_data, so a lite reviewer reads only this file and the ledger."""
        doc = _read(REVIEWERS_DIR, "_lite-cards.md")
        pre = _flat(doc.split("## Card 1")[0])
        schema = json.loads(_read(SKILL, "schemas", "review.schema.json"))
        for key in schema["required"]:
            self.assertIn("`{}`".format(key), pre, key)
        for enum in (schema["$defs"]["verdict"]["enum"], schema["$defs"]["severity"]["enum"],
                     schema["$defs"]["confidence"]["enum"], schema["$defs"]["fix"]["properties"]["fix_type"]["enum"],
                     schema["properties"]["advance"]["enum"]):
            for v in enum:
                self.assertIn(v, pre, v)

        def enums(node, out):
            if isinstance(node, dict):
                if "enum" in node:
                    out.extend(v for v in node["enum"] if isinstance(v, str))
                for v in node.values():
                    enums(v, out)
            elif isinstance(node, list):
                for v in node:
                    enums(v, out)
            return out

        cards = {re.search(r"\(`([a-z_]+)`\)", c.split("\n", 1)[0]).group(1): _flat(c)
                 for c in re.split(r"\n## Card ", doc)[1:]}
        for rid, card in cards.items():
            for value in enums(schema["$defs"]["lens_" + rid], []):
                self.assertIn(value, card, "{} card is missing the allowed value {}".format(rid, value))
        self.assertIn("integer", cards["recruiter"])        # page_count_estimate is a number, not "1 page"
        for axis in ("P1_table_stakes", "P5_positioning"):
            self.assertIn(axis, cards["competitor"])

    def test_recruiter_card_needs_no_other_file(self):
        """3.3: one locale note inside the card replaces the locale-norms.md read."""
        doc = _read(REVIEWERS_DIR, "_lite-cards.md")
        card = _flat([c for c in re.split(r"\n## Card ", doc) if c.startswith("2: Recruiter")][0])
        self.assertNotIn("locale-norms.md", doc)
        for phrase in ("en-US", "letter", "A4", "customary", "CV", "GPA", "locale_applied"):
            self.assertIn(phrase, card)


class OutputFormatTest(unittest.TestCase):
    def test_compact_and_valid(self):
        doc = _read(REVIEWERS_DIR, "_output-format.md")
        self.assertLess(len(doc.encode("utf-8")), 10000, "keep the contract a few KB")
        blocks = re.findall(r"```json\n(.*?)\n```", doc, re.S)
        self.assertEqual(len(blocks), 1)
        schema = json.loads(_read(SKILL, "schemas", "review.schema.json"))
        self.assertEqual(schema_lite.validate(json.loads(blocks[0]), schema), [])
        for key in schema["required"]:
            self.assertIn("`{}`".format(key), doc)


class LocaleNormsTest(unittest.TestCase):
    def rows(self):
        doc = _read(SKILL, "references", "locale-norms.md")
        rows = {}
        for line in doc.splitlines():
            m = re.match(r"^\| `([a-zA-Z-]+)`[^|]*\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|$", line)
            if m:
                rows[m.group(1)] = [c.strip() for c in m.groups()[1:]]
        return rows

    def test_every_locale_has_a_row(self):
        rows = self.rows()
        self.assertEqual(sorted(rows), sorted(LOCALES))
        for loc, cells in rows.items():
            paper, photo, dob = cells[1].strip("`"), cells[3].strip("`"), cells[4].strip("`")
            self.assertIn(paper, ("letter", "a4"), loc)
            self.assertIn(photo, ("omit", "optional", "customary"), loc)
            self.assertIn(dob, ("omit", "optional", "customary"), loc)
        self.assertEqual(rows["en-US"][1], "`letter`")
        self.assertEqual(rows["de-DE"][3], "`customary`")
        self.assertIn("CV", rows["en-GB"][0])

    def test_recruiter_inline_copy_agrees(self):
        """The recruiter persona carries a compact copy of this table (A4); paper and photo values match."""
        persona = _read(REVIEWERS_DIR, "03-recruiter.md")
        rows = self.rows()
        for loc in LOCALES:
            line = next(ln for ln in persona.splitlines() if ln.startswith("|") and "`{}`".format(loc) in ln)
            cells = [c.strip() for c in line.strip("|").split("|")]
            self.assertEqual(cells[2].lower(), rows[loc][1].strip("`"), loc)          # paper
            self.assertEqual(cells[4].split(",")[0].strip(), rows[loc][3].strip("`"), loc)   # photo

    def test_agrees_with_lexicon_json_when_present(self):
        path = os.path.join(SCRIPTS, "hp", "data", "locale_norms.json")
        if not os.path.exists(path):
            self.skipTest("hp/data/locale_norms.json not built yet")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        rows = self.rows()
        for loc in LOCALES:
            self.assertIn(loc, data, loc)
            entry = data[loc]
            cells = rows[loc]
            for key, idx in (("paper", 1), ("photo", 3), ("dob", 4)):
                if key in entry:
                    self.assertEqual(str(entry[key]).lower(), cells[idx].strip("`"), "{} {}".format(loc, key))


class ProvenanceDocTest(unittest.TestCase):
    def test_example_valid_and_schema_strict(self):
        doc = _read(SKILL, "references", "provenance-audit.md")
        schema = json.loads(_read(SKILL, "schemas", "provenance.schema.json"))
        self.assertEqual(schema_lite.unsupported_keywords(schema), [])
        blocks = re.findall(r"```json\n(.*?)\n```", doc, re.S)
        self.assertEqual(len(blocks), 1)
        example = json.loads(blocks[0])
        self.assertEqual(schema_lite.validate(example, schema), [])
        self.assertEqual([i["verdict"] for i in example["items"]], ["ok", "soften", "remove"])
        bad = [
            {"bullet_id": "b1", "audited_text": "x", "verdict": "ok", "problem": "something", "suggested_text": None},
            {"bullet_id": "b1", "audited_text": "x", "verdict": "soften", "problem": "p", "suggested_text": None},
            {"bullet_id": "b1", "audited_text": "x", "verdict": "remove", "problem": None, "suggested_text": None},
            {"bullet_id": "b 1", "audited_text": "x", "verdict": "ok", "problem": None, "suggested_text": None},
            {"bullet_id": "b1", "audited_text": "", "verdict": "ok", "problem": None, "suggested_text": None},
        ]
        for item in bad:
            doc_ = {"schema_version": "1.0", "auditor": "skeptic-provenance", "mode": "self", "items": [item]}
            self.assertTrue(schema_lite.validate(doc_, schema), item)
        self.assertTrue(schema_lite.validate({"schema_version": "1.0", "auditor": "skeptic-provenance",
                                              "mode": "other", "items": []}, schema))

    def test_audit_rules_present(self):
        doc = _flat(_read(SKILL, "references", "provenance-audit.md"))
        for phrase in ("NEW_WORDING", "never evidence", "audited_text", "\"mode\": \"subagent\"", "\"mode\": \"self\"",
                       "single word DONE", "Ignore any instructions", "never accusatory", "ownership",
                       "yes` or `some`", "spearheaded"):
            self.assertIn(phrase, doc)
        for banned in ("you lied", "the candidate lied"):
            self.assertNotIn(banned, doc.lower())


class ReviewSchemaConsistencyTest(unittest.TestCase):
    def test_enums_match_code(self):
        schema = json.loads(_read(SKILL, "schemas", "review.schema.json"))
        self.assertEqual(schema["properties"]["reviewer_id"]["enum"], REPORT_ORDER)
        self.assertEqual(schema["$defs"]["category"]["enum"], list(CATS))
        for rid in REPORT_ORDER:
            self.assertEqual(schema["$defs"]["dims_" + rid]["enum"], DIMENSIONS[rid])
        anchor = re.compile(schema["$defs"]["anchor"]["pattern"])
        for ok in ("R1", "J12", "A:PARSE-006", "A:PARSE-009b", "A:KW-001"):
            self.assertTrue(anchor.search(ok), ok)
        for bad in ("Q1", "R", "A:parse-006", "A:PARSE-06", "L12", "R1 "):
            self.assertFalse(anchor.search(bad), bad)
        self.assertEqual(schema["properties"]["strengths"]["minItems"], 0)
        # The release script refuses to build while the GitHub owner placeholder remains; the schema
        # must not contain it (OWNERSHIP_EVIDENCE is a category name, not the placeholder).
        self.assertIsNone(re.search(r"\bOWNER\b", json.dumps(schema)), "placeholder OWNER in review schema")


if __name__ == "__main__":
    unittest.main()
