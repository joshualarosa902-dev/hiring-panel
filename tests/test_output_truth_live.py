"""Truth-check regressions from the live end-to-end tests (findings A16, A17, A19, B 6.3, 6.4, 6.5, 6.14).

All data is fictional: Avery Quinn, a biology student who works at a market and a library.
"""
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

from hp.rewrite.truth import check_truth, month_years, numbers_in  # noqa: E402

LINES = [
    ("contact", "AVERY QUINN"),
    ("contact", "avery.quinn@example.com | (555) 010-4477 | Columbus, OH"),
    ("education", "EDUCATION"),
    ("education", "Lakeview State University, B.S. Biology, Expected May 2028"),        # R4
    ("experience", "WORK"),
    ("experience", "Cashier, Maple Street Market, 2023 - present"),                      # R6
    ("experience", "- handle returns sometimes and help 20 customers an hour find items"),  # R7
    ("experience", "- trained 2 new cashiers"),                                          # R8
    ("experience", "Library Aide, Columbus Public Library, 2022"),                       # R9
    ("experience", "- shelved nearly 300 books a week"),                                 # R10
    ("experience", "- ran over 40 story times"),                                         # R11
    ("experience", "- made 40+ flyers for events"),                                      # R12
    ("experience", "- helped about 20 to about 60 kids at summer reading"),              # R13
    ("experience", "- answered 3 or 4 calls an hour"),                                   # R14
    ("skills", "SKILLS"),
    ("skills", "Microsoft Excel, Spanish"),                                              # R16
    ("other", "VOLUNTEER"),
    ("other", "Volunteer, Riverbend Animal Shelter, 2023"),                              # R18
    ("other", "- walked dogs on weekends"),                                              # R19
    ("other", "- helped at adoption events for 10 weeks"),                               # R20
    ("leadership", "Biology Club member, 2024 - present"),                               # R21
]
LEDGER = {"schema_version": "1.0",
          "resume_lines": [{"id": "R%d" % (i + 1), "section": s, "text": t} for i, (s, t) in enumerate(LINES)],
          "jd_items": [{"id": "J1", "kind": "must", "block": 0, "text": "Experience with HIPAA and Power BI"}],
          "target": {"role_title": "Lab Assistant", "role_level": "intern", "company": "Northgate Labs",
                     "locale": "en-US", "general_review": False}}


def answer(qid, kind, text, items=None):
    return {"id": qid, "kind": kind, "question": "q", "answer": text, "status": "answered", "items": items}


ANSWERS = {"schema_version": "1.0", "mode": "interactive", "answers": [
    answer("Q1", "keywords", "Excel: yes, I use Excel for the club budget. PowerBI: no. HIPAA: no, but the clinic "
           "data was de-identified and I did the CITI human subjects training",
           [{"term": "Excel", "answer": "yes", "detail": "I use Excel for the club budget"},
            {"term": "Power BI", "answer": "no", "detail": ""},
            {"term": "HIPAA", "answer": "no",
             "detail": "but the clinic data was de-identified and I did the CITI human subjects training"}]),
    answer("Q2", "integrity", "we went from about 20 members to about 60 over the year"),
    answer("Q3", "number", "around 3 or 4 a week"),
    answer("Q4", "reviewer", "I help take care of my grandma a few days a week"),
    answer("Q5", "reviewer", "from March to August 2023, about twice a month"),
    answer("Q6", "reviewer", "I started last summer, about 20 hours a week during school"),
    answer("Q7", "reviewer", "I help my neighbor carry groceries sometimes"),
]}


def ev(ref, quote=None):
    out = {"src": "user" if ref.startswith("Q") else "orig", "ref": ref}
    if quote:
        out["quote"] = quote
    return out


def bullet(bid, text, *evidence):
    return {"id": bid, "text": text, "evidence": list(evidence)}


RESUME = {
    "schemaVersion": "1.0",
    "meta": {"locale": "en-US", "layout": "classic", "stage": "student",
             "cuts": [{"ref": "R11", "reason": "space"}, {"ref": "R13", "reason": "space"}]},
    "basics": {"name": "Avery Quinn", "email": "avery.quinn@example.com", "phone": "(555) 010-4477",
               "location": "Columbus, OH"},
    "sections": [
        {"id": "education", "type": "education", "title": "Education", "items": [
            {"id": "edu1", "school": "Lakeview State University", "degree": "B.S.", "field": "Biology",
             "end": "2028-05", "endLabel": "Expected", "evidence": [ev("R4")]}]},
        {"id": "experience", "type": "experience", "title": "Experience", "items": [
            {"id": "exp1", "org": "Maple Street Market", "role": "Cashier", "start": "2023", "end": "present",
             "evidence": [ev("R6"), ev("Q6", "about 20 hours a week during school")],
             "bullets": [
                 bullet("exp1.b1", "Handle returns sometimes and help 20 customers an hour find items", ev("R7")),
                 bullet("exp1.b2", "Trained 2 new cashiers", ev("R8")),
                 bullet("exp1.b3", "Work about 20 hours a week during school", ev("R6"))]},
            {"id": "exp2", "org": "Columbus Public Library", "role": "Library Aide", "dateText": "2022",
             "evidence": [ev("R9")],
             "bullets": [
                 bullet("exp2.b1", "Shelved nearly 300 books a week", ev("R10")),
                 bullet("exp2.b2", "Made 40+ flyers for events", ev("R12")),
                 bullet("exp2.b3", "Answered 3 or 4 calls an hour", ev("R14"))]}]},
        {"id": "lead", "type": "custom", "title": "Activities", "items": [
            {"id": "lead1", "org": "Biology Club", "role": "Member", "start": "2024", "end": "present",
             "evidence": [ev("R21")],
             "bullets": [
                 bullet("lead1.b1", "Helped grow membership from about 20 to about 60 over the year",
                        ev("R21"), ev("Q2", "from about 20 members to about 60")),
                 bullet("lead1.b2", "Made around 3 or 4 club posters a week", ev("R21"),
                        ev("Q3", "around 3 or 4 a week"))]}]},
        {"id": "vol", "type": "experience", "title": "Volunteer Experience", "items": [
            {"id": "vol1", "org": "Riverbend Animal Shelter", "role": "Volunteer", "dateText": "2023",
             "evidence": [ev("R18")],
             "bullets": [
                 bullet("vol1.b1", "Walked dogs on weekends about twice a month", ev("R19"),
                        ev("Q5", "about twice a month")),
                 bullet("vol1.b2", "Helped at adoption events over 10 weeks", ev("R20"))]}]},
        {"id": "care", "type": "custom", "title": "Family Caregiving", "items": [
            {"id": "care1", "role": "Family Caregiver", "evidence": [ev("Q4", "I help take care of my grandma")],
             "bullets": [bullet("care1.b1", "Help a family member a few days a week",
                                ev("Q4", "I help take care of my grandma a few days a week"))]}]},
        {"id": "skills", "type": "skills", "title": "Skills", "groups": [
            {"label": "Tools", "items": ["Microsoft Excel"], "evidence": [ev("R16")]},
            {"label": "Languages", "items": ["Spanish"], "evidence": [ev("R16")]}]},
    ],
}


def find(resume, bid):
    for s in resume["sections"]:
        for it in s.get("items") or []:
            if it["id"] == bid:
                return it
            for b in it.get("bullets") or []:
                if b["id"] == bid:
                    return b
    raise KeyError(bid)


def section(resume, sid):
    return [s for s in resume["sections"] if s["id"] == sid][0]


class Base(unittest.TestCase):
    def truth(self, mutate=None, answers=None, ledger=None):
        r, a = copy.deepcopy(RESUME), copy.deepcopy(ANSWERS if answers is None else answers)
        if mutate:
            mutate(r, a)
        return check_truth(copy.deepcopy(LEDGER if ledger is None else ledger), a, r)

    def codes(self, out, code, where=None):
        return [e for e in out["errors"] if e["code"] == code and (where is None or e["where"] == where)]

    def assertCode(self, out, code, where=None):
        hits = self.codes(out, code, where)
        self.assertTrue(hits, "expected %s at %s, got %s" % (code, where, json.dumps(out["errors"], indent=1)))
        self.assertFalse(out["passed"])
        return hits[0]

    def set_text(self, bid, text):
        def m(r, a):
            find(r, bid)["text"] = text
        return m


class TestBaseline(Base):
    def test_fictional_base_passes(self):
        out = self.truth()
        self.assertTrue(out["passed"], json.dumps(out["errors"], indent=1))

    def test_numbers_from_answers_count_entry_level_answers(self):
        # B 6.14: lead1 20 + 60 (Q2), 3 + 4 (Q3), vol1 twice (Q5) and exp1.b3 20 hours from the ENTRY's Q6
        # evidence all came from answers. Before the fix entry-level answers counted as resume lines.
        out = self.truth()
        self.assertEqual(out["stats"]["numbers_from_answers"], 6, out["stats"])

    def test_number_from_entry_answer_alone_counts(self):
        def m(r, a):
            section(r, "experience")["items"][0]["bullets"] = [find(r, "exp1.b3")]
            for s in ("lead", "vol"):
                section(r, s)["items"][0]["bullets"] = []
        out = self.truth(m)
        self.assertEqual(out["stats"]["numbers_from_answers"], 1, out)


class TestHedgesA16(Base):
    """A16: a hedge or range on a number, from an answer OR a resume line, must survive the rewrite."""

    def test_answer_about_20_to_about_60_collapsed(self):
        out = self.truth(self.set_text("lead1.b1", "Helped grow membership from 20 to 60 over the year"))
        details = [e["detail"] for e in self.codes(out, "HEDGE_REMOVED", "lead1.b1")]
        self.assertEqual(len(details), 2, out["errors"])
        self.assertIn("keep 'about' next to 20", details[0])
        self.assertIn("keep 'about' next to 60", details[1])

    def test_answer_about_20_to_about_60_as_a_range(self):
        out = self.truth(self.set_text("lead1.b1", "Helped grow membership 20 to 60 over the year"))
        self.assertCode(out, "HEDGE_REMOVED", "lead1.b1")

    def test_answer_around_3_or_4_to_4(self):
        err = self.assertCode(self.truth(self.set_text("lead1.b2", "Made 4 club posters a week")),
                              "HEDGE_REMOVED", "lead1.b2")
        self.assertIn("around 3 or 4", err["detail"])

    def test_answer_around_3_or_4_drops_around(self):
        err = self.assertCode(self.truth(self.set_text("lead1.b2", "Made 3 or 4 club posters a week")),
                              "HEDGE_REMOVED", "lead1.b2")
        self.assertIn("keep 'around'", err["detail"])

    def test_placeholder_value_collapses_range(self):
        def m(r, a):
            b = find(r, "lead1.b2")
            b["text"], b["textIfUnknown"] = "Made {{p1}} club posters a week", "Made club posters each week"
            r["placeholders"] = {"p1": {"bullet": "lead1.b2", "ask": "How many?", "status": "answered",
                                        "value": "4", "question": "Q3"}}
        self.assertCode(self.truth(m), "HEDGE_REMOVED", "lead1.b2")

    def test_answer_about_60_to_over_60(self):
        out = self.truth(self.set_text("lead1.b1", "Helped grow membership from about 20 to over 60 over the year"))
        err = self.assertCode(out, "HEDGE_REMOVED", "lead1.b1")
        self.assertIn("keep 'about'", err["detail"])

    def test_answer_twice_keeps_about(self):
        err = self.assertCode(self.truth(self.set_text("vol1.b1", "Walked dogs on weekends twice a month")),
                              "HEDGE_REMOVED", "vol1.b1")
        self.assertIn("'about'", err["detail"])

    def test_resume_line_hedges(self):
        cases = (("exp2.b1", "Shelved 300 books a week", "nearly"),
                 ("exp2.b2", "Made 40 flyers for events", "+"),
                 ("exp2.b3", "Answered 4 calls an hour", "3 or 4"))
        for bid, text, needle in cases:
            err = self.assertCode(self.truth(self.set_text(bid, text)), "HEDGE_REMOVED", bid)
            self.assertIn(needle, err["detail"], bid)

    def test_resume_line_over_and_range(self):
        def over(r, a):
            r["meta"]["cuts"] = [{"ref": "R13", "reason": "space"}]
            section(r, "experience")["items"][1]["bullets"].append(bullet("exp2.b4", "Ran 40 story times", ev("R11")))
        err = self.assertCode(self.truth(over), "HEDGE_REMOVED", "exp2.b4")
        self.assertIn("keep 'over'", err["detail"])

        def rng(r, a):
            r["meta"]["cuts"] = [{"ref": "R11", "reason": "space"}]
            section(r, "experience")["items"][1]["bullets"].append(
                bullet("exp2.b4", "Helped 20 to 60 kids at summer reading", ev("R13")))
        err = self.assertCode(self.truth(rng), "HEDGE_REMOVED", "exp2.b4")
        self.assertIn("about", err["detail"])

    def test_kept_hedges_pass(self):
        for bid, text in (("exp2.b1", "Shelved nearly 300 books each week"),
                          ("exp2.b3", "Answered 3 to 4 calls an hour"),
                          ("lead1.b2", "Made roughly 3 or 4 club posters a week"),
                          ("vol1.b1", "Walked dogs on weekends, about twice a month")):
            out = self.truth(self.set_text(bid, text))
            self.assertFalse(self.codes(out, "HEDGE_REMOVED"), (bid, out["errors"]))

    def test_exact_number_made_bigger(self):
        for text in ("Trained 2+ new cashiers", "Trained more than 2 new cashiers"):
            err = self.assertCode(self.truth(self.set_text("exp1.b2", text)), "HEDGE_REMOVED", "exp1.b2")
            self.assertIn("claims more", err["detail"])

    def test_over_a_duration_is_not_a_hedge(self):
        out = self.truth(self.set_text("vol1.b2", "Helped at adoption events for 10 weeks"))
        self.assertTrue(out["passed"], out["errors"])

    def test_same_value_different_thing(self):
        # "20 customers an hour" (exact) must not excuse dropping "about" from "about 20 hours a week"
        def m(r, a):
            b = find(r, "exp1.b3")
            b["text"] = "Work 20 hours a week during school"
            b["evidence"] = [ev("R7"), ev("Q6", "about 20 hours a week during school")]
        self.assertCode(self.truth(m), "HEDGE_REMOVED", "exp1.b3")

    def test_numbers_in_groups(self):
        got = numbers_in("about 20 to about 60 kids, from about 20 to about 60, around 3 or 4, between 5 and 9, "
                         "over 10 weeks, ~600 views, 2023-2024")
        by = [(n["raw"], n["h"], n["grp"]) for n in got]
        self.assertIn(("about 20 to about 60", "approx", "60"), by)
        self.assertIn(("about 20", "approx", None), by)          # "from ... to ...": a change, not a range
        self.assertIn(("around 3 or 4", None, "3"), by)
        self.assertIn(("between 5 and 9", None, "9"), by)
        self.assertIn(("10", None, None), by)                    # "over 10 weeks" is a duration
        self.assertIn(("~600", "approx", None), by)
        self.assertTrue(all(n["grp"] is None for n in got if n["v"] in ("2023", "2024")))


class TestQualifierMessage65(Base):
    def test_absolute_word_named_when_hedge_kept(self):
        out = self.truth(self.set_text("exp1.b1", "Handle returns sometimes and help 20 customers each hour find items"))
        err = self.assertCode(out, "HEDGE_REMOVED", "exp1.b1")
        self.assertIn("'each'", err["detail"])
        self.assertIn("sometimes", err["detail"])
        self.assertNotIn("but this says", err["detail"])

    def test_dropped_qualifier_named(self):
        out = self.truth(self.set_text("exp1.b1", "Handle every return and help 20 customers an hour find items"))
        err = self.assertCode(out, "HEDGE_REMOVED", "exp1.b1")
        self.assertIn("drops it", err["detail"])
        self.assertIn("'every'", err["detail"])


class TestNoItemsA17(Base):
    def add_cert(self, quote, name="CITI human subjects training"):
        def m(r, a):
            r["sections"].insert(2, {"id": "cert", "type": "custom", "title": "Certifications", "items": [
                {"id": "cert1", "name": name, "evidence": [ev("Q1", quote)]}]})
        return m

    def test_fact_inside_a_no_item_can_be_cited(self):
        out = self.truth(self.add_cert("I did the CITI human subjects training"))
        self.assertTrue(out["passed"], out["errors"])

    def test_no_term_quote_is_named_not_called_missing(self):
        out = self.truth(self.add_cert("HIPAA: no, but the clinic data was de-identified"))
        err = self.assertCode(out, "BAD_REF", "cert1")
        self.assertIn("inside a 'no' item", err["detail"])
        self.assertIn("HIPAA", err["detail"])
        self.assertNotIn("is not in your answer", err["detail"])

    def test_no_term_never_usable(self):
        def term(r, a):
            b = find(r, "exp1.b1")
            b["text"] = "Kept HIPAA records while handling returns sometimes"
            b["evidence"] = [ev("R7"), ev("Q1", "the clinic data was de-identified")]
        err = self.assertCode(self.truth(term), "TERM_NOT_IN_SOURCE", "exp1.b1")
        self.assertIn("answered 'no'", err["detail"])
        for item in ("Power BI", "PowerBI", "HIPAA"):
            def skill(r, a, item=item):
                section(r, "skills")["groups"][0]["items"].append(item)
            err = self.assertCode(self.truth(skill), "SKILL_NOT_IN_SOURCE")
            self.assertIn("answered 'no'", err["detail"], item)

    def test_no_term_variant_in_free_text_is_masked(self):
        out = self.truth(self.add_cert("PowerBI", name="PowerBI"))
        self.assertCode(out, "BAD_REF", "cert1")


class TestSchemaA19(Base):
    def test_valid_inputs_have_no_schema_errors(self):
        out = self.truth()
        self.assertFalse([e for e in out["errors"] if e["code"] in ("BAD_ANSWERS", "BAD_RESUME_SCHEMA")])

    def test_bad_answers(self):
        answers = copy.deepcopy(ANSWERS)
        answers["answers"][1]["kind"] = "number_question"
        answers["answers"][2]["notes"] = "extra"
        out = self.truth(answers=answers)
        err = self.assertCode(out, "BAD_ANSWERS", "answers[1].kind")
        self.assertIn("answers.json", err["detail"])
        self.assertIn("must be one of", err["detail"])
        err = self.assertCode(out, "BAD_ANSWERS", "answers[2]")
        self.assertIn("unexpected field 'notes'", err["detail"])

    def test_bad_resume(self):
        def m(r, a):
            find(r, "exp1.b2")["ops"] = ["INVENT"]
            find(r, "exp2")["label"] = "Library"
        out = self.truth(m)
        err = self.assertCode(out, "BAD_RESUME_SCHEMA", "sections[1].items[0].bullets[1].ops[0]")
        self.assertIn("resume.json", err["detail"])
        self.assertCode(out, "BAD_RESUME_SCHEMA", "sections[1].items[1]")

    def test_schema_errors_come_first_and_never_raise(self):
        def m(r, a):
            r["sections"].append({"id": "x", "type": "nonsense", "title": 5, "items": "no"})
        out = self.truth(m)
        self.assertEqual(out["errors"][0]["code"], "BAD_RESUME_SCHEMA")
        json.dumps(out)


class TestLabelsAndTitles63(Base):
    def test_family_caregiver_needs_a_family_cue(self):
        def m(r, a):
            item = section(r, "care")["items"][0]
            item["evidence"] = [ev("Q7", "I help my neighbor carry groceries sometimes")]
            item["bullets"] = []
        err = self.assertCode(self.truth(m), "ENTITY_NOT_IN_SOURCE", "care1")
        self.assertIn("honest label", err["detail"])

    def test_invented_self_employed_label(self):
        def m(r, a):
            find(r, "exp2")["org"] = "Self-employed"
        self.assertCode(self.truth(m), "ENTITY_NOT_IN_SOURCE", "exp2")

    def test_clinical_title_is_a_claim(self):
        def m(r, a):
            section(r, "experience")["title"] = "Clinical Experience"
        err = self.assertCode(self.truth(m), "HEADING_CLAIM", "experience.title")
        self.assertIn("'clinical'", err["detail"])

    def test_caregiving_title_without_evidence(self):
        def m(r, a):
            section(r, "vol")["title"] = "Caregiving"
        self.assertCode(self.truth(m), "HEADING_CLAIM", "vol.title")

    def test_titles_from_evidence_or_original_headings_pass(self):
        def m(r, a):
            section(r, "experience")["title"] = "Library and Market Experience"
        self.assertTrue(self.truth(m)["passed"])
        ledger = copy.deepcopy(LEDGER)
        ledger["resume_lines"][4]["text"] = "CLINICAL ROTATIONS"
        def c(r, a):
            section(r, "experience")["title"] = "Clinical Rotations"
        out = self.truth(c, ledger=ledger)
        self.assertFalse(self.codes(out, "HEADING_CLAIM"), out["errors"])

    def test_non_english_title_is_a_warning(self):
        def m(r, a):
            r["meta"]["locale"] = "de-DE"
            section(r, "experience")["title"] = "Klinische Erfahrung"
        out = self.truth(m)
        self.assertFalse(self.codes(out, "HEADING_CLAIM"))
        self.assertIn(("NEW_WORDING", "experience.title"), {(w["code"], w["bullet_id"]) for w in out["warnings"]})
        # the provenance audit must then cover the title like any flagged bullet
        from hp.rewrite import check_provenance
        r = copy.deepcopy(RESUME)
        m(r, None)
        gate = check_provenance(r, {"items": []}, out)
        self.assertIn("experience.title", gate["missing"])
        ok = {"items": [{"bullet_id": w["bullet_id"], "audited_text": "Klinische Erfahrung"
                         if w["bullet_id"] == "experience.title" else find(r, w["bullet_id"])["text"],
                         "verdict": "ok", "problem": None, "suggested_text": None}
                        for w in out["warnings"] if w["code"] == "NEW_WORDING"]}
        self.assertNotIn("experience.title", check_provenance(r, ok, out)["missing"])


class TestDatesFromAnswers64(Base):
    def test_month_range_from_answer(self):
        def m(r, a):
            item = find(r, "vol1")
            item.pop("dateText")
            item["start"], item["end"] = "2023-03", "2023-08"
            item["evidence"].append(ev("Q5", "from March to August 2023"))
        out = self.truth(m)
        self.assertFalse(self.codes(out, "DATE_PRECISION_ADDED"), out["errors"])
        self.assertTrue(out["passed"], out["errors"])

        def t(r, a):
            find(r, "vol1")["dateText"] = "March to August 2023"
            find(r, "vol1")["evidence"].append(ev("Q5", "from March to August 2023"))
        self.assertTrue(self.truth(t)["passed"])

    def test_season_is_not_a_month(self):
        def m(r, a):
            find(r, "exp1")["start"] = "2023-06"
        self.assertCode(self.truth(m), "DATE_PRECISION_ADDED", "exp1")

    def test_month_parsing(self):
        self.assertEqual(month_years("from March to August 2023")[0], {(3, "2023"), (8, "2023")})
        self.assertEqual(month_years("Mar-Aug 2023")[0], {(3, "2023"), (8, "2023")})
        self.assertEqual(month_years("Sept. 2024")[0], {(9, "2024")})
        self.assertEqual(month_years("BBA Marketing 2027")[0], set())      # "Marketing" is not March
        self.assertEqual(month_years("last summer 2024")[0], set())


if __name__ == "__main__":
    unittest.main()
