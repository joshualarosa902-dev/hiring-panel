# Sample run (fictional)

This folder is one complete Hiring Panel run, produced by the real scripts. Riley Castellano,
Lakeshore State University, Tallgrass Outfitters, Cedar Hollow Market and Northwind Foods are all
made up. The email uses example.com and the phone number is a 555-01xx test number.

Riley is a business analytics student applying for a Marketing Analytics Intern role. The resume
has the usual problems: duty bullets ("Responsible for", "Helped with"), the strongest project buried
near the bottom, and one claim that won't survive an interview question ("Increased online sales by
300%").

## Start here

| File | What it is |
|---|---|
| [Hiring_Panel_Report.pdf](Hiring_Panel_Report.pdf) | The one-page report: vote, simulated screening check, truth check, biggest weaknesses first, the panel |
| [Hiring_Panel_Report.html](Hiring_Panel_Report.html) / [.md](Hiring_Panel_Report.md) | The full report, with disagreements, keyword gaps, strengths, interview prep and limitations |
| [Riley_Castellano_Resume.pdf](Riley_Castellano_Resume.pdf) / [.docx](Riley_Castellano_Resume.docx) / [.md](Riley_Castellano_Resume.md) | The rebuilt resume |
| [inputs/resume.docx](inputs/resume.docx) | The resume as Riley uploaded it ([PDF version](inputs/resume.pdf)) |
| [inputs/jd.txt](inputs/jd.txt) | The job posting as pasted |
| [panel-stage/](panel-stage/) | The early report delivered right after the panel, before any rewrite |

## What happened

1. `init` read the .docx, ran the simulated screening check and numbered every resume line (R1 to
   R32) and posting line (J1 to J21). See `work/inputs/ledger.json` and
   `work/screening/before/screening.md`.
2. Seven reviewers each wrote one file in `work/reviews/`. Every finding quotes a numbered line word
   for word. In a real run these come from seven separate Claude subagents; here they are the
   hand-written fixtures the end-to-end test uses.
3. `synthesize` merged and ranked the findings (`work/synthesis.json`). The panel vote counts the
   reviewers who answered "yes" to "should this resume move to the next step?": 4 of 7.
4. `report` built the early panel report (`panel-stage/`).
5. Riley answered one batch of five questions (`work/answers.json`). The 300% figure turned out to
   compare one sale weekend to a normal weekend, measured by the owner, so the rewrite drops it and
   says what Riley actually did: wrote the sale email. The newsletter open rate was "not sure", so
   that bullet uses its honest no-number wording and the report lists it under "Needs you".
6. The rewrite (`work/rewrite/resume.json`) cites an R line or an answer for every bullet.
   `truth` checked every name, date, number, tool and ownership verb against those sources
   (`work/rewrite/truth.json`), and a Skeptic audit covered the reworded bullets
   (`work/rewrite/provenance.json`).
7. `render` built the .docx, .pdf and .md, then re-read both files the way parsing software would
   (`work/gate.json`, `work/screening/after/`). 100% of the words came back, in order, with no
   readability issues.
8. `report` built the final report (`work/report.json`, then the three report files).

## Reproduce it

From the repository root, with the clock pinned so the output matches:

```
HP_AS_OF=2026-10-20 HP_NOW=2026-10-20-1430 python3 plugins/hiring-panel/skills/hiring-panel/scripts/hp.py init --resume tests/fixtures/e2e/resume.docx --jd tests/fixtures/e2e/jd.txt --role "Marketing Analytics Intern" --company "Northwind Foods" --jd-source pasted --stage student --role-level intern --locale en-US
```

Then copy `tests/fixtures/e2e/reviews/*.json` into the new run's `work/reviews/` and run
`synthesize <RUN> --mode parallel`, `report <RUN>`; copy `answers.json`, `resume.json` and
`provenance.json` into place and run `truth <RUN>`, `render <RUN>` and `report <RUN>`.
`tests/test_e2e_pipeline.py` does exactly this. Every file comes out byte for byte the same except
`work/state.json` (it records when each step ran) and the PDFs, which carry the creation time the PDF
engine stamps into them (so the screening of the PDF records a different file hash).

The simulated screening check is not a real applicant tracking system, and the reviewers are
simulated by Claude. The report says so too.
