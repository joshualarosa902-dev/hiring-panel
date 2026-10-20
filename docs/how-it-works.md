# How Hiring Panel works

This page is for anyone curious about what happens between "Use Hiring Panel" and the six
files you get back. The binding technical contract is [ARCHITECTURE.md](../ARCHITECTURE.md);
this is the readable version.

## The short version

```
your resume + one job posting
        |
        v
1. init         a script reads the file, runs the simulated screening check,
                and numbers every line (R1, R2, ... and J1, J2, ...)
        |
        v
2. panel        seven reviewers each write a structured review that must quote
                your exact lines as evidence
        |
        v
3. synthesize   a script checks every quote, merges duplicates and ranks the
                weaknesses; the early report is built right away
        |
        v
4. questions    one batch of at most 7 questions (numbers, keywords, confirmations;
                up to 8 for a very short resume), one fact per question
        |
        v
5. rewrite      Claude rebuilds the resume from your lines and your answers only
        |
        v
6. checks       truth check (script) + provenance audit (a fresh Skeptic)
        |
        v
7. render       .docx, .pdf, .md, then the screening check runs again on the new files
        |
        v
8. report       one-page PDF + full .md and .html
```

Claude does the reading, reviewing and writing. Scripts do every count, score, ranking
and check, so the numbers are the same every time for the same inputs.

## The seven reviewers

| # | Reviewer | Decision question |
|---|---|---|
| 1 | Automated Screening Check | Would this file parse cleanly and come up when a recruiter searches? |
| 2 | Hiring Manager | Would I spend 45 minutes interviewing this person? |
| 3 | Recruiter | In my first fast pass, does this go to the hiring manager? |
| 4 | Competing Applicant | Next to a typical strong applicant, would this resume win? |
| 5 | CEO | Would this person move something the business cares about? |
| 6 | Future Teammate | Would I want them on my team next sprint? |
| 7 | Skeptic | Which lines wouldn't survive a five-minute follow-up question? |

Each reviewer has its own lens (a fixed list of problem types it may raise), so seven
copies of the same model don't just echo each other. Every finding must quote a resume or
posting line word for word; a script throws out quotes that don't match and "missing
keyword" claims for words that are actually on the resume. Each reviewer also answers one
shared question: "From your seat, should this resume move to the next step for this job?"
The headline vote ("2 of 7 would move you forward") counts those answers.
Right under the vote, the report shows the Recruiter's 7-second first impression. Only
when at least 5 reviewers say yes and nothing critical or major turned up does it call the
resume strong, and then it also names the reviewer who came closest to saying no (the
lowest verdict) and that reviewer's top issue, so a strong result is never flattery.

Where the ideas behind each persona come from, with quality labels:
[references/sources.md](../plugins/hiring-panel/skills/hiring-panel/references/sources.md).

## Three ways the panel runs

| Mode | Where | How independent |
|---|---|---|
| parallel | Claude Code (Pro or Max) | Seven separate subagents, each with a fresh context, launched at once. Their prompt holds file paths only. |
| sequential | claude.ai | One conversation plays the seven in turn, re-reading the files before each, gatekeepers first. Approximate independence, disclosed in chat and in the report. Agreement counts for less in the ranking. |
| lite | claude.ai Free, or "quick run" | Like sequential, with shorter reviewer cards and less re-reading, to save usage. Same disclosure. |

In every mode a reviewer reads its own instructions plus one file of numbered lines (the
"ledger"), which holds the whole resume and the whole posting. Reviewers don't get separate
copies of the resume and posting on top of that, which keeps each one's reading, and your
plan usage, down. The screening reviewer also reads the script's results. In Claude Code,
"quick run" keeps the seven separate reviewers and runs them on a lighter model.

There's also a manual mode for machines with no Python: same flow, but every check is
Claude's own judgment, labeled model-only, with no scores.

## The simulated screening check

Applicant tracking systems mostly parse resumes into profile fields and let recruiters
search and filter them. Automatic rejection usually comes from application questions
(work authorization, location, degree), not from resume wording. So the check looks for
the two things you can actually fix:

- **Machine readability:** problems that publicly documented parsers struggle with: scans,
  text boxes, tables, columns, contact details in headers, graphics, hidden text,
  letter-spaced words, missing dates.
- **Job-keyword match:** which required and preferred terms from the posting your resume
  shows, and whether you show them in real experience or only list them.

It reports **one** number, in steps of 5:

> Overall = 40% file readability + 40% job-keyword match + 20% content signals, rounded to
> steps of 5. Weights are our judgment, not calibrated to hiring outcomes.

Every number comes with a band and exact counts ("Required terms: 9 of 12 found (2 only in
your skills list)"). It's always called a simulated screening check, because no vendor
publishes how its system ranks resumes.

## How weaknesses get ranked

The ranking script merges findings about the same problem, then scores each issue by:
severity (critical, major, moderate, minor) x how many reviewers flagged it x how early in
hiring it bites (screening, recruiter skim, hiring manager, interview) x confidence x
whether it touches a must-have requirement. The weights are documented design choices,
not research findings. Inflated or unverifiable claims are pinned to "Fix before you send"
whatever their rank, and real disagreements between reviewers are shown, not averaged.

## Keeping the rewrite honest

1. **Evidence on every bullet.** Each line of the new resume points at the original lines
   (R12) or your answers (Q2) it came from. The job posting is never evidence.
2. **Truth check (script).** Blocks new employers, titles, dates (or added date
   precision), numbers, tools, skills, upgraded ownership ("helped" to "led"), dropped
   hedges ("about 600" to "600"), changed contact details and leftover placeholders.
3. **Provenance audit.** A fresh Skeptic (a separate subagent in Claude Code) reads each
   reworded bullet next to its source and flags invented outcomes or scope that no script
   can catch. Its soften and remove calls must be applied before the files get built.
4. **Missing numbers.** If a bullet would be stronger with a number, Claude asks you. "Not
   sure" is a fine answer; the bullet then uses honest wording without a number.
5. **Your choices stay yours.** The headline uses only facts from your resume and answers.
   If the screening check suggests putting the job's title there, Claude offers it as your
   choice instead of adding it. Skill ratings drawn as dots or bars are dropped, never
   turned into a level like "advanced".

The report only says "0 invented facts" when the script truth check actually ran and
passed.

## The files

The resume is rendered from one structured source into .docx, .pdf and .md: single column,
standard headings, real bullets, contact details in the body, no tables, text boxes,
images or hidden text, and nothing in the file that names the tool. The PDF comes from
Chrome, Edge or Brave if installed, then LibreOffice, then a built-in writer. Then the
screening check runs again on the generated .docx and .pdf, and a quality gate requires
clean readability, no merged words, at least 98% of words recovered from each file, and those
words coming back in reading order. Claude also skims the new resume once to confirm every
entry name, organization and bullet made it into the files, and says so if anything didn't. If the right-aligned dates read badly, it rebuilds once with
the dates inline. The result is saved in `work/gate.json`.

## What it can't do

- It isn't any company's real system and can't see an employer's application questions.
- The keyword dictionary is English-only and finite; you can help it by pasting the full
  posting.
- Reviewers are models. They can be wrong, and you can ignore any advice.
- No cover letters, LinkedIn rewrites or interview coaching in this version.
