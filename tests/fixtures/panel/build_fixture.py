"""Regenerate tests/fixtures/panel/run_basic (fictional candidate "Jordan Rivera").

Run from the repo root:  python3 tests/fixtures/panel/build_fixture.py
The tests read the committed JSON; they never run this script. All people, schools and companies are
fictional; the phone number uses the reserved 555-01xx range and the email uses example.com.

The seven reviews are schema-valid but contain deliberate mistakes the synthesis must catch:
  screening-2  KEYWORD_GAP for "Python", which the resume contains          -> overruled (resume text)
  screening-5  cites A:PARSE-099, which is not in screening.json            -> dropped (unknown A: id)
  teammate-4   KEYWORD_GAP "data visualization", found by the screening check -> overruled (script truth)
  recruiter-4  quotes R1's email but anchors it to R3                      -> anchor repaired to R1
  ceo-4        TYPO_GRAMMAR (outside the CEO lens) at minor                 -> dropped (lens rule)
  skeptic-3    quote "Led a team of 12 analysts" is not in the resume       -> dropped (made-up quote)
  competitor-s1 strength quote is on R12 but anchored to R3                 -> anchor repaired
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(REPO, "plugins", "hiring-panel", "skills", "hiring-panel", "scripts"))

from hp.panel.common import DIMENSIONS, REVIEWER_INFO  # noqa: E402
from hp.panel.ledger import build_ledger  # noqa: E402

RUN = os.path.join(HERE, "run_basic")
WORK = os.path.join(RUN, "work")

RESUME_MD = """[header] Jordan Rivera | jordan.rivera@example.com | (512) 555-0198
Jordan Rivera
Austin, TX | linkedin.com/in/jordan-rivera-example

EDUCATION
B.S. Business Analytics, Lakeshore State University, Expected May 2027

EXPERIENCE
Marketing Intern, BrightPath Co., Jun 2025 \u2013 Aug 2025
\u2022 Responsible for social media posts and various tasks
\u2022 Spearheaded company-wide analytics strategy, increasing revenue 300%
\u2022 Helped the team with weekly reports in Excel
Barista, Bean Scene Cafe, Sep 2023 \u2013 Present
\u2022 Trained 6 new baristas and handled opening shifts

PROJECTS
\u2022 Built a Python dashboard tracking 2,000 student survey responses for the campus food bank
\u2022 Worked on a group project analyzing music streaming data

SKILLS
Excel, Python, Tableau, teamwork, communication
"""

JD_MD = """Data Analyst Intern - Northwind Health
About us:
Northwind Health helps rural clinics reduce patient wait times.
Responsibilities:
- Build dashboards that track clinic performance
- Clean and analyze operational data
- Present data visualization to clinic managers
Requirements:
- Proficiency in SQL
- Experience with Python or R
- Experience with Tableau or Power BI
Preferred:
- Experience with healthcare data
Location: Austin, TX (hybrid, 3 days a week in the office)
Northwind Health is an equal opportunity employer.
"""

BLOCKS = [
    {"kind": "unspecified", "heading": None, "lines": ["Data Analyst Intern - Northwind Health"]},
    {"kind": "boilerplate", "heading": "About us:",
     "lines": ["About us:", "Northwind Health helps rural clinics reduce patient wait times."]},
    {"kind": "responsibility", "heading": "Responsibilities:",
     "lines": ["Responsibilities:", "- Build dashboards that track clinic performance",
               "- Clean and analyze operational data", "- Present data visualization to clinic managers"]},
    {"kind": "required", "heading": "Requirements:",
     "lines": ["Requirements:", "- Proficiency in SQL", "- Experience with Python or R",
               "- Experience with Tableau or Power BI"]},
    {"kind": "preferred", "heading": "Preferred:", "lines": ["Preferred:", "- Experience with healthcare data"]},
    {"kind": "boilerplate", "heading": None,
     "lines": ["Location: Austin, TX (hybrid, 3 days a week in the office)",
               "Northwind Health is an equal opportunity employer."]},
]

DISCLAIMER = ("This is a simulation, not a real applicant tracking system. Every employer sets up its own "
              "software, and none of the big vendors publish exactly how they parse or rank resumes.")
PRECISION = ("Scores move in steps of 5 on purpose. A 70 and a 75 are not meaningfully different. The counts "
             "and the issue list matter more than the number.")


def kw(term, importance, found, match_type, level, wording, quote, canonical=None):
    return {"term": term, "canonical": canonical or term, "kind": "tool", "importance": importance,
            "weight": 3.0 if importance == "required" else 1.0, "jd_frequency": 1, "jd_quote": quote,
            "source": "lexicon", "found": found, "match_type": match_type, "resume_wording": wording,
            "evidence_level": level, "resume_locations": [], "snippets": []}


def issue(iid, rank, category, severity, title, evidence, why, fix, conf="high"):
    return {"id": iid, "rank": rank, "category": category, "severity": severity, "title": title,
            "evidence": evidence, "why_it_matters": why, "fix": fix,
            "honesty_note": "Only add a term you can back up in an interview." if iid.startswith("KW") else None,
            "confidence": conf, "detected_by": "jd_comparison" if iid.startswith("KW") else "file_structure",
            "score_impact": {}, "source_refs": []}


SCREENING = {
    "schema_version": "1.0",
    "tool": {"name": "hiring-panel-screen", "version": "1.0.0", "lexicon_version": "fixture"},
    "mode": "script", "generated_at": None, "as_of": "2026-10-20", "level": "student",
    "inputs": {"resume": {"format": "docx", "sha256": "0" * 64, "bytes": 18000, "pages": 1,
                          "producer": None, "creator": None},
               "job_description": {"sha256": "1" * 64, "chars": len(JD_MD), "title_guess": "Data Analyst Intern",
                                   "url": None, "platform_guess": "unknown", "blocks": BLOCKS}},
    "extraction": {"method": "docx-xml", "text_chars": len(RESUME_MD), "ats_view_file": "work/inputs/ats_view.txt",
                   "warnings": []},
    "scores": {
        "overall": {"value": 55, "band": "Needs work", "explanation": "fixture", "drivers": ["KW-001", "PARSE-006"]},
        "parse_safety": {"value": 85, "band": "Minor risks", "explanation": "fixture"},
        "keyword_match": {"value": 50, "band": "Partial match", "explanation": "fixture"},
        "content_signals": {"value": 70, "band": "Solid", "explanation": "fixture"},
        "precision_note": PRECISION},
    "issues": [
        issue("KW-001", 1, "keywords", "high", "Required terms missing: SQL", ['Not found: "SQL"'],
              "The posting lists SQL as a requirement and your resume never shows it.",
              "If you have used SQL, show where. If not, treat it as a gap."),
        issue("PARSE-006", 2, "parse", "high", "Email and phone only in the page header",
              ["[header] Jordan Rivera | jordan.rivera@example.com | (512) 555-0198"],
              "Some parsing software skips page headers, so your email and phone may not reach your profile.",
              "Put your email and phone in the body, right under your name."),
        issue("KW-002", 3, "keywords", "medium", "Tableau appears only in your skills list",
              ['"Tableau" appears only in your skills or other lists.'],
              "A skill that is only listed is weaker than one shown in a bullet.",
              "Show Tableau inside a bullet about real work, if you used it there."),
        issue("CONTENT-002", 4, "content", "low", "Weak openers: Responsible for, Helped, Worked on",
              ["Responsible for social media posts and various tasks"],
              "Weak openers hide what you did.", "Start bullets with what you did."),
        issue("KW-004", 5, "keywords", "low", "The job title Data Analyst Intern is not on your resume",
              ['Posting title: "Data Analyst Intern"'], "Recruiters often search by title.", "Consider a truthful headline."),
        issue("CONTENT-008", 6, "content", "info", "Buzzwords with no evidence: teamwork, communication",
              ["teamwork", "communication"], "Listed soft skills carry little weight.", "Show them in bullets."),
        issue("KW-005", 7, "keywords", "info", "Preferred terms missing: healthcare data",
              ['Not found: "healthcare data"'],
              "Preferred terms help but are not required.", "Only add what you can back up."),
    ],
    "keywords": {
        "required": [
            kw("SQL", "required", False, "none", "none", None, "Proficiency in SQL"),
            kw("Python", "required", True, "exact", "demonstrated", "Python", "Experience with Python or R"),
            kw("Tableau", "required", True, "exact", "listed", "Tableau", "Experience with Tableau or Power BI"),
        ],
        "preferred": [kw("healthcare data", "preferred", False, "none", "none", None,
                         "Experience with healthcare data")],
        "other": [
            kw("dashboards", "responsibility", True, "inflection", "demonstrated", "dashboard",
               "Build dashboards that track clinic performance"),
            kw("data visualization", "responsibility", True, "implied", "listed", "Tableau",
               "Present data visualization to clinic managers"),
        ],
        "job_title": {"jd_title": "Data Analyst Intern", "resume_titles": ["Marketing Intern", "Barista"],
                      "match": "none"},
        "coverage": {"required_found": 2, "required_total": 3, "preferred_found": 0, "preferred_total": 1,
                     "required_weighted": 0.67, "preferred_weighted": 0.0, "evidence_share": 0.6,
                     "listed_only": ["Tableau"]},
    },
    "knockout_signals": [
        {"type": "onsite_hybrid", "importance": "unspecified",
         "jd_quote": "Location: Austin, TX (hybrid, 3 days a week in the office)",
         "resume_evidence": "Austin, TX", "status": "not_on_resume_by_design",
         "advice": "This is usually an application question. Answer truthfully; the resume can't and shouldn't address it."}],
    "sections": {}, "contact": {}, "experience": {}, "bullets": {},
    "limitations": ["fixture 1", "fixture 2", "fixture 3"], "disclaimer": DISCLAIMER,
}

BRIEF = {
    "scores": {"overall": {"value": 55, "band": "Needs work"}, "parse_safety": {"value": 85, "band": "Minor risks"},
               "keyword_match": {"value": 50, "band": "Partial match"},
               "content_signals": {"value": 70, "band": "Solid"}},
    "precision_note": PRECISION, "disclaimer": DISCLAIMER,
    "top_issues": [{"id": i["id"], "severity": i["severity"], "title": i["title"],
                    "evidence": (i["evidence"][0] if i["evidence"] else "")[:160]} for i in SCREENING["issues"]],
    "keywords": [{k: row[k] for k in ("term", "importance", "found", "match_type", "evidence_level", "resume_wording")}
                 for bucket in ("required", "preferred", "other") for row in SCREENING["keywords"][bucket]],
    "coverage": SCREENING["keywords"]["coverage"], "knockouts": SCREENING["knockout_signals"],
    "job_title": "Data Analyst Intern", "platform_guess": "unknown", "language": "en",
}


# ----------------------------------------------------------------------------- review helpers
def E(anchor, quote=None):
    d = {"anchor": anchor}
    if quote is not None:
        d["quote"] = quote
    return d


def fix(t, s="", q=None):
    return {"fix_type": t, "suggestion": s, "candidate_question": q}


def F(fid, cat, sev, title, ev, fx, detail=None, conf="high", ool=False, terms=None):
    d = {"id": fid, "category": cat, "severity": sev, "confidence": conf, "title": title,
         "detail": detail or title + ".", "evidence": ev, "fix": fx, "out_of_lens": ool}
    if terms is not None:
        d["searched_terms"] = terms
    return d


def S(sid, title, ev, underused=False):
    return {"id": sid, "title": title, "evidence": ev, "underused": underused}


def dims(rid, scores, anchors=None):
    anchors = anchors or {}
    return [{"dimension_id": d, "score": s, "evidence_anchors": anchors.get(i, []), "note": ""}
            for i, (d, s) in enumerate(zip(DIMENSIONS[rid], scores))]


def review(rid, verdict, advance, take, rationale, d, findings, strengths, lens, questions=None, conf="high"):
    return {"schema_version": "1.0", "reviewer_id": rid,
            "decision_question": REVIEWER_INFO[rid]["decision_question"], "verdict": verdict,
            "verdict_rationale": rationale, "advance": advance, "one_line_take": take, "confidence": conf,
            "dimension_scores": d, "findings": findings, "strengths": strengths,
            "questions_for_candidate": questions or [], "lens_data": lens}


REVIEWS = {}
REVIEWS["screening"] = review(
    "screening", "borderline", "unsure",
    "The file mostly parses, but SQL is missing and your email hides in the header.",
    "Script bands: Needs work overall, Minor risks for readability, Partial match on keywords. SQL is a "
    "required term the resume never shows (A:KW-001).",
    dims("screening", [3, 2, 2, 3, 2], {0: ["A:PARSE-006"], 1: ["A:KW-001"]}),
    [F("screening-1", "KEYWORD_GAP", "critical", "SQL, a required skill, never appears",
       [E("J9", "Proficiency in SQL"), E("A:KW-001")],
       fix("needs_candidate_input", "", "Have you used SQL in a class, a project or a job?"),
       terms=["SQL", "PostgreSQL", "MySQL", "structured query language"]),
     F("screening-2", "KEYWORD_GAP", "major", "Python is missing",
       [E("J10", "Experience with Python or R")], fix("add_keyword_truthfully"), terms=["Python"]),
     F("screening-3", "TITLE_MISMATCH", "moderate", "No data analyst title or headline near the top",
       [E("R7", "Marketing Intern, BrightPath Co."), E("A:KW-004")],
       fix("rewrite", "Add a truthful headline such as Business Analytics student.")),
     F("screening-4", "CONTACT_HEADER", "major", "Email and phone sit only in the page header",
       [E("A:PARSE-006"), E("R1", "jordan.rivera@example.com")],
       fix("reformat", "Move the email and phone into the body under your name.")),
     F("screening-5", "PARSE_FORMAT", "moderate", "Odd characters may confuse parsers",
       [E("A:PARSE-099")], fix("reformat"))],
    [],
    {"script_bands": {"overall": "Needs work", "parse_safety": "Minor risks", "keyword_match": "Partial match",
                      "content_signals": "Solid"},
     "keyword_table": [
         {"term": "SQL", "importance": "required", "found": False, "match_type": "none", "evidence_level": "none",
          "resume_wording": None, "jd_anchor": "J9", "resume_anchors": [], "truthful_fix": "ask_candidate"},
         {"term": "Python", "importance": "required", "found": True, "match_type": "exact",
          "evidence_level": "demonstrated", "resume_wording": "Python", "jd_anchor": "J10",
          "resume_anchors": ["R14", "R17"], "truthful_fix": "none_needed"},
         {"term": "Tableau", "importance": "required", "found": True, "match_type": "exact",
          "evidence_level": "listed", "resume_wording": "Tableau", "jd_anchor": "J11", "resume_anchors": ["R17"],
          "truthful_fix": "ask_candidate"}],
     "parse_risks": [{"issue_id": "PARSE-006", "script_severity": "high", "note": "Contact only in the header."}],
     "knockouts": [{"type": "onsite_hybrid", "jd_anchor": "J14", "status": "not_on_resume_by_design",
                    "note": "Answer the application question truthfully."}]})

REVIEWS["recruiter"] = review(
    "recruiter", "borderline", "unsure",
    "In seven seconds you read as a marketing intern, not a data analyst.",
    "Top third shows a marketing title and a barista job; the data work is buried in Projects (R14).",
    dims("recruiter", [2, 3, 3, 3, 2]),
    [F("recruiter-1", "TITLE_MISMATCH", "major", "Reads as a marketing candidate in seven seconds",
       [E("R7", "Marketing Intern, BrightPath Co., Jun 2025 - Aug 2025")],
       fix("reorder", "Lead with the Projects section so the dashboard shows first.")),
     F("recruiter-2", "ORDER_PRIORITY", "major", "Your best data work is buried at the bottom",
       [E("R14", "Built a Python dashboard")], fix("reorder", "Move Projects above Experience.")),
     F("recruiter-3", "TYPO_GRAMMAR", "minor", "Bullet starts with a duty phrase",
       [E("R8", "Responsible for social media posts")], fix("rewrite")),
     F("recruiter-4", "CONTACT_HEADER", "minor", "Email is in the page header",
       [E("R3", "jordan.rivera@example.com")], fix("reformat", "Put the email under your name."))],
    [S("recruiter-s1", "Name is clear at the top", [E("R2", "Jordan Rivera")])],
    {"seven_second_takeaway": "Business analytics student; marketing intern and barista; data work not visible.",
     "six_data_points": [
         {"item": "name", "found": True, "anchor": "R2", "findable_in_seconds": True},
         {"item": "current_title_org", "found": True, "anchor": "R11", "findable_in_seconds": True},
         {"item": "previous_title_org", "found": True, "anchor": "R7", "findable_in_seconds": True},
         {"item": "current_dates", "found": True, "anchor": "R11", "findable_in_seconds": True},
         {"item": "previous_dates", "found": True, "anchor": "R7", "findable_in_seconds": True},
         {"item": "education", "found": True, "anchor": "R5", "findable_in_seconds": True}],
     "page_count_estimate": 1, "gpa_note": None, "locale_applied": "en-US"})

REVIEWS["hiring_manager"] = review(
    "hiring_manager", "lean_yes", "yes",
    "The food bank dashboard earns an interview; SQL is the open question.",
    "Python and dashboards are demonstrated (R14); SQL (J9) is absent; most experience bullets list duties "
    "without results (R8, R10).",
    dims("hiring_manager", [2, 3, 2, 3, 3], {0: ["J9", "R14"]}),
    [F("hiring_manager-1", "REQUIREMENT_UNPROVEN", "major", "SQL requirement is not shown anywhere",
       [E("J9", "Proficiency in SQL")],
       fix("needs_candidate_input", "", "Where have you written SQL queries, even in coursework?")),
     F("hiring_manager-2", "IMPACT_MISSING", "moderate", "Duties instead of results",
       [E("R8", "Responsible for social media posts and various tasks")],
       fix("needs_candidate_input", "", "What changed because of your posts?")),
     F("hiring_manager-3", "METRIC_MISSING", "moderate", "Weekly reports have no outcome or scale",
       [E("R10", "weekly reports in Excel")], fix("rewrite", "Say who used the reports and for what.")),
     F("hiring_manager-4", "IMPACT_MISSING", "moderate", "Group project has no result",
       [E("R15", "group project analyzing music streaming data")], fix("needs_candidate_input"))],
    [S("hiring_manager-s1", "A real dashboard with real users",
       [E("R14", "Built a Python dashboard tracking 2,000 student survey responses")], True)],
    {"basis": "posting",
     "requirement_map": [
         {"jd_anchor": "J9", "requirement": "Proficiency in SQL", "status": "absent", "resume_anchors": [],
          "note": "Not mentioned anywhere."},
         {"jd_anchor": "J10", "requirement": "Python or R", "status": "demonstrated", "resume_anchors": ["R14"],
          "note": "Python dashboard project."},
         {"jd_anchor": "J11", "requirement": "Tableau or Power BI", "status": "claimed_only",
          "resume_anchors": ["R17"], "note": "Listed in skills only."}],
     "case_for_candidate": "Built a working Python dashboard over 2,000 survey responses for a real campus group.",
     "biggest_doubt": "No sign of SQL, and the internship bullets show duties rather than results.",
     "interview_questions": ["Walk me through how you built the food bank dashboard.",
                             "How did you clean the 2,000 survey responses before analyzing them?",
                             "What did the weekly Excel reports show, and who used them?"]},
    questions=[{"question": "Have you used SQL anywhere, even in coursework?", "why": "It is a must-have.",
                "related_anchors": ["J9"]}])

REVIEWS["teammate"] = review(
    "teammate", "lean_yes", "yes",
    "I could hand you a dashboard ticket next sprint; show me your part in team work.",
    "The dashboard (R14) is our day-one work; the group project (R15) hides your contribution.",
    dims("teammate", [3, 2, 3, 2, 3]),
    [F("teammate-1", "ATTRIBUTION_UNCLEAR", "moderate", "Unclear what you did in the group project",
       [E("R15", "Worked on a group project")],
       fix("needs_candidate_input", "", "What was your part of the group project?")),
     F("teammate-2", "COLLABORATION_EVIDENCE", "minor", "Teamwork is only listed as a skill",
       [E("R17", "teamwork, communication")], fix("rewrite")),
     F("teammate-3", "SKILL_UNSUPPORTED", "moderate", "Tableau is listed but never used in a bullet",
       [E("R17", "Excel, Python, Tableau")], fix("needs_candidate_input", "", "Where did you use Tableau?")),
     F("teammate-4", "KEYWORD_GAP", "major", "No data visualization experience",
       [E("J7", "Present data visualization to clinic managers")], fix("real_gap"), ool=True,
       terms=["data visualization", "data viz"])],
    [S("teammate-s1", "Training new baristas shows you can teach", [E("R12", "Trained 6 new baristas")], True),
     S("teammate-s2", "The dashboard is our exact day-one work", [E("R14", "Built a Python dashboard")])],
    {"day_one_readiness": "some_ramp",
     "toolkit_overlap": [
         {"tool_or_method": "Python", "jd_anchor": "J10", "status": "demonstrated", "resume_anchors": ["R14"]},
         {"tool_or_method": "Tableau", "jd_anchor": "J11", "status": "listed_only", "resume_anchors": ["R17"]},
         {"tool_or_method": "SQL", "jd_anchor": "J9", "status": "absent", "resume_anchors": []}],
     "peer_interview_questions": ["How did you clean the survey data?"]})

REVIEWS["ceo"] = review(
    "ceo", "borderline", "unsure",
    "One bullet shows real impact; the rest reads like a task list.",
    "The food bank dashboard (R14) served a real group; internship bullets (R8, R10) never say what changed.",
    dims("ceo", [2, 2, 2, 2, 3]),
    [F("ceo-1", "IMPACT_MISSING", "major", "Reads like a task list",
       [E("R8", "various tasks"), E("R10", "Helped the team with weekly reports")],
       fix("needs_candidate_input", "", "What happened because of the weekly reports?")),
     F("ceo-2", "MISSION_ALIGNMENT", "moderate", "No link to rural clinics or patient wait times",
       [E("J3", "reduce patient wait times")],
       fix("real_gap", "Lean on the food bank dashboard as service work for a real community group."), conf="medium"),
     F("ceo-3", "IMPACT_MISSING", "moderate", "Opening shifts: so what?",
       [E("R12", "handled opening shifts")], fix("needs_candidate_input")),
     F("ceo-4", "TYPO_GRAMMAR", "minor", "Comma splice", [E("R9", "Spearheaded")], fix("rewrite"))],
    [S("ceo-s1", "The food bank dashboard shows mission-driven ownership",
       [E("R14", "for the campus food bank")])],
    {"one_sentence_case": "Built a data tool a real campus group used.",
     "so_what_bullets": [{"anchor": "R10", "quote": "Helped the team with weekly reports in Excel",
                          "missing": "outcome"}],
     "keeper_test": "Too early to tell from this page."})

REVIEWS["competitor"] = review(
    "competitor", "lean_no", "no",
    "My resume beats yours on specifics; your dashboard is your best weapon and it is buried.",
    "Generic lines (R8) and vague verbs (R10) lose side by side; the dashboard (R14) is buried.",
    dims("competitor", [2, 2, 1, 2, 1]),
    [F("competitor-1", "GENERIC_DIFFERENTIATION", "major", "Generic phrases any applicant could write",
       [E("R8", "various tasks")], fix("rewrite")),
     F("competitor-2", "VAGUE_LANGUAGE", "moderate", "\"Helped\" hides what you did",
       [E("R10", "Helped the team")], fix("rewrite")),
     F("competitor-3", "PROOF_LINKS", "moderate", "No link to the dashboard",
       [E("R14", "Built a Python dashboard")],
       fix("needs_candidate_input", "", "Is the dashboard on GitHub or a public link?"))],
    [S("competitor-s1", "Training new staff is proof you can teach", [E("R3", "Trained 6 new baristas")])],
    {"benchmark_profile": {"level": "intern", "basis": "posting",
                           "typical_signals": ["SQL from a class or project", "One dashboard or analysis project"],
                           "basis_jd_anchors": ["J9", "J5"],
                           "disclaimer": "Assumed from the job description, not data about real applicants."},
     "head_to_head": [
         {"axis": "P1_table_stakes", "this_resume": "Python yes, SQL no", "typical_competitor": "Python and SQL",
          "edge": "competitor"},
         {"axis": "P2_differentiation", "this_resume": "Food bank dashboard", "typical_competitor": "Class project",
          "edge": "candidate"},
         {"axis": "P3_specificity", "this_resume": "Several generic lines", "typical_competitor": "Specific lines",
          "edge": "competitor"},
         {"axis": "P4_proof_density", "this_resume": "Few numbers, no links",
          "typical_competitor": "Numbers and a link", "edge": "competitor"},
         {"axis": "P5_positioning", "this_resume": "Best work at the bottom",
          "typical_competitor": "Best work first", "edge": "competitor"}],
     "unfair_advantages": [{"anchor": "R14", "why_it_stands_out": "Real users and real data",
                            "currently_buried": True}],
     "generic_phrases": [{"anchor": "R8", "quote": "various tasks"}]})

REVIEWS["skeptic"] = review(
    "skeptic", "strong_no", "no",
    "The 300% revenue line will not survive one follow-up question.",
    "A summer intern claiming company-wide strategy and 300% revenue (R9) reads as inflated, even if true.",
    dims("skeptic", [1, 1, 2, 3, 2]),
    [F("skeptic-1", "SCOPE_INFLATION", "critical", "Company-wide strategy and 300% revenue in a summer internship",
       [E("R9", "Spearheaded company-wide analytics strategy, increasing revenue 300%"),
        E("R9", "Spearheaded company-wide ... revenue 300%")],
       fix("needs_candidate_input", "", "What exactly did you build, and how was the revenue change measured?")),
     F("skeptic-2", "UNVERIFIABLE_CLAIM", "moderate", "2,000 responses: whose survey was it?",
       [E("R14", "tracking 2,000 student survey responses")], fix("rewrite", "Say who ran the survey."),
       conf="medium"),
     F("skeptic-3", "VAGUE_LANGUAGE", "minor", "Team size unclear", [E("R10", "Led a team of 12 analysts")],
       fix("rewrite")),
     F("skeptic-4", "SKILL_UNSUPPORTED", "moderate", "Tableau is claimed but never used",
       [E("R17", "Excel, Python, Tableau")], fix("needs_candidate_input"))],
    [S("skeptic-s1", "Barista training is concrete and checkable", [E("R12", "Trained 6 new baristas")])],
    {"claim_audit": [
        {"anchor": "R9", "quote": "increasing revenue 300%", "claim_type": "metric", "risk": "high",
         "probe_question": "How was the 300% measured, and what was the starting point?", "recommended": "add_context"},
        {"anchor": "R14", "quote": "2,000 student survey responses", "claim_type": "metric", "risk": "medium",
         "probe_question": "Who collected the 2,000 responses, and what did the dashboard change?",
         "recommended": "keep_prepare_story"},
        {"anchor": "R12", "quote": "Trained 6 new baristas", "claim_type": "scope", "risk": "low",
         "probe_question": "How did you train the 6 new baristas?", "recommended": "keep_prepare_story"}],
     "consistency_checks": [{"check": "date overlaps", "result": "pass", "anchors": ["R7", "R11"]}]})


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        if isinstance(data, str):
            f.write(data)
        else:
            f.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def main():
    write(os.path.join(WORK, "inputs", "resume.md"), RESUME_MD)
    write(os.path.join(WORK, "inputs", "jd.md"), JD_MD)
    body = [ln for ln in RESUME_MD.splitlines() if not ln.startswith("[header]")]
    write(os.path.join(WORK, "inputs", "ats_view.txt"),
          "# extraction: docx-xml\n# roughly what parsing software reads; order matters\n\n" + "\n".join(body) +
          "\n\n# header/footer (some systems skip this):\nJordan Rivera | jordan.rivera@example.com | (512) 555-0198\n")
    ledger = build_ledger(RESUME_MD, BLOCKS, {"role_title": "Data Analyst Intern", "role_level": "intern",
                                              "company": "Northwind Health", "locale": "en-US"})
    write(os.path.join(WORK, "inputs", "ledger.json"), ledger)
    write(os.path.join(WORK, "screening", "before", "screening.json"), SCREENING)
    write(os.path.join(WORK, "screening", "before", "brief.json"), BRIEF)
    for rid, r in REVIEWS.items():
        write(os.path.join(WORK, "reviews", rid + ".json"), r)
    print("wrote fixture to", RUN)


if __name__ == "__main__":
    main()
