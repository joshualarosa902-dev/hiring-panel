# Review output format

Write ONE JSON object, nothing else, to `RUN/work/reviews/<reviewer_id>.json`. The validator
(`hp.py validate RUN PATH`) checks it; this page is the whole contract (never read the schema file).

## Top level: all 13 keys, no others

| key | value |
|---|---|
| `schema_version` | `"1.0"` |
| `reviewer_id` | `screening`, `hiring_manager`, `recruiter`, `competitor`, `ceo`, `teammate` or `skeptic` (matches the file name) |
| `decision_question` | your persona's question, copied (200 chars max) |
| `verdict` | `strong_yes`, `lean_yes`, `borderline`, `lean_no` or `strong_no` (decided last) |
| `verdict_rationale` | 60 words max (400 chars), naming the decisive lines in a few quoted words |
| `advance` | `yes`, `no` or `unsure` |
| `one_line_take` | 20 words max, plain language |
| `confidence` | `high`, `medium` or `low` |
| `dimension_scores` | exactly 5: `{dimension_id, score 1-4, evidence_anchors [ids], note (160 chars max)}`, your persona's 5 ids |
| `findings` | 0 to 7, most serious first |
| `strengths` | 0 to 4 (empty is fine; never invent praise) |
| `questions_for_candidate` | 0 to 5: `{question (200 chars), why (160 chars), related_anchors [ids]}` |
| `lens_data` | exactly the shape in your persona file, with its allowed values |

## Pieces

- Finding: `{"id": "<reviewer_id>-<n>", "category": <one of your lens_categories>, "severity":
  "critical|major|moderate|minor", "confidence": "high|medium|low", "title": <= 12 words (90 chars),
  "detail": <= 60 words (420 chars), "evidence": [1 to 4 items], "fix": {...}, "out_of_lens": false}`.
  `KEYWORD_GAP` also needs `"searched_terms": ["SQL", "PostgreSQL", "MySQL"]`.
- Fix: `{"fix_type": "rewrite|reorder|reformat|add_keyword_truthfully|remove|needs_candidate_input|real_gap",
  "suggestion": <= 40 words (280 chars), facts from the cited lines only, "candidate_question": string or null}`.
  `needs_candidate_input` always carries a real question.
- Strength: `{"id": "<reviewer_id>-s<n>", "title": 90 chars max, "evidence": [1 to 3 resume items],
  "underused": true when the strength is buried or undersold}`.
- Evidence: `{"anchor": "R14", "quote": "Built a Python dashboard"}` (resume line) or
  `{"anchor": "J9", "quote": "Proficiency in SQL"}` (posting line), the quote copied word for word from
  that one line (25 words, 220 chars max); `{"anchor": "A:PARSE-006"}` for a brief.json issue
  (Automated Screening Check only).
- Ids (R14, J9, A:PARSE-006) go only in anchor fields; text a student reads quotes words instead.

## Mistakes that fail validation

Paraphrased quotes or quotes from another line; a value outside the allowed lists; a `KEYWORD_GAP` the
resume or the screening check already answers; `one_line_take` over 20 words; text around the JSON.

## Example (Hiring Manager, fictional candidate)

```json
{
  "schema_version": "1.0",
  "reviewer_id": "hiring_manager",
  "decision_question": "Based on this resume alone, would I spend 45 minutes interviewing this person for this role?",
  "verdict": "lean_yes",
  "verdict_rationale": "The food bank dashboard shows Python on real data; SQL, a must-have, is absent.",
  "advance": "yes",
  "one_line_take": "Your food bank dashboard earns the interview; show SQL and results to make it easy.",
  "confidence": "high",
  "dimension_scores": [
    {"dimension_id": "H1_requirement_match", "score": 2, "evidence_anchors": ["J9", "R14"], "note": "Python shown, SQL absent."},
    {"dimension_id": "H2_proof_of_work", "score": 3, "evidence_anchors": ["R14"], "note": "A real dashboard for a campus group."},
    {"dimension_id": "H3_results", "score": 2, "evidence_anchors": ["R8"], "note": "Duties, few outcomes."},
    {"dimension_id": "H4_problem_solving", "score": 2, "evidence_anchors": [], "note": "No decisions described."},
    {"dimension_id": "H5_trajectory", "score": 3, "evidence_anchors": ["R7"], "note": "A job plus an internship."}
  ],
  "findings": [
    {"id": "hiring_manager-1", "category": "REQUIREMENT_UNPROVEN", "severity": "major", "confidence": "high",
     "title": "SQL is required and never shown",
     "detail": "The posting lists SQL as a requirement. Nothing on the page shows it, so I cannot tell whether you would need training on day one.",
     "evidence": [{"anchor": "J9", "quote": "Proficiency in SQL"}],
     "fix": {"fix_type": "needs_candidate_input", "suggestion": "If you have used SQL, name where. If not, treat it as a gap to close.",
             "candidate_question": "Have you written SQL queries in a class, a project or a job?"},
     "out_of_lens": false}
  ],
  "strengths": [
    {"id": "hiring_manager-s1", "title": "A working dashboard with real users",
     "evidence": [{"anchor": "R14", "quote": "Built a Python dashboard ... for the campus food bank"}], "underused": true}
  ],
  "questions_for_candidate": [
    {"question": "Have you used SQL anywhere, even in coursework?", "why": "It is a must-have in the posting.", "related_anchors": ["J9"]}
  ],
  "lens_data": {
    "basis": "posting",
    "requirement_map": [
      {"jd_anchor": "J9", "requirement": "Proficiency in SQL", "status": "absent", "resume_anchors": [], "note": "Not mentioned."},
      {"jd_anchor": "J10", "requirement": "Python or R", "status": "demonstrated", "resume_anchors": ["R14"], "note": "Python dashboard."}
    ],
    "case_for_candidate": "Built a working Python dashboard over 2,000 survey responses for a real campus group, while holding a steady job.",
    "biggest_doubt": "No sign of SQL; internship bullets show duties, not results.",
    "interview_questions": [
      "Walk me through how you built the food bank dashboard.",
      "How did you clean the survey responses before analyzing them?"
    ]
  }
}
```
