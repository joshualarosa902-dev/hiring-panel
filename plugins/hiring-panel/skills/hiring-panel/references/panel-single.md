# Panel, single-conversation mode (claude.ai, or no Agent tool)

Without the Agent tool you play all seven reviewers yourself, one after another, in this
conversation. Later reviewers can be pulled toward what earlier ones said (anchoring), and
warnings alone don't remove that. So this protocol limits it with structure, the ranking
script gives agreement less weight, and you tell the student plainly what this mode is.

Two variants:
- **sequential**: full persona files. For Pro and Max plans.
- **lite**: short persona cards and less re-reading. For the Free plan, a student who asks
  for a quick run, or when you don't know the plan. It uses noticeably less of the
  student's usage, which matters because a usage limit can cut a run off midway.

In both, the resume and the posting come from `<RUN>/work/inputs/ledger.json`, which holds
every line of both with its R# or J# id. Don't read resume.md or jd.md for the panel: the
ledger has the same text, so reading them too only uses more of the student's plan.

## 1. The disclosure (always)

Before the first reviewer, tell the student:

> In this chat I play all seven reviewers one after another. I keep them apart as best I
> can, but they aren't fully independent. For a fully independent panel, run Hiring Panel
> in Claude Code.

The report repeats this (its `mode_note`), and so does your final message. Never describe
a single-conversation panel as independent.

## 2. Run order (this mode only)

Gatekeepers go first, so the verdicts that matter most for getting an interview are the
least influenced by earlier reviews. This is only the order you play them in. Everywhere
else (the report, SKILL.md, your summary) reviewers appear in the report order.

| Run order | id | Display name | Persona file |
|---|---|---|---|
| 1 | screening | Automated Screening Check | 01-screening.md |
| 2 | recruiter | Recruiter | 03-recruiter.md |
| 3 | hiring_manager | Hiring Manager | 02-hiring-manager.md |
| 4 | teammate | Future Teammate | 06-teammate.md |
| 5 | ceo | CEO | 05-ceo.md |
| 6 | competitor | Competing Applicant | 04-competitor.md |
| 7 | skeptic | Skeptic | 07-skeptic.md |

Files live in `<SKILL_DIR>/references/reviewers/`. Inputs live in `<RUN>/work/inputs/`.

## 3. Sequential protocol

Before EACH reviewer:
1. Re-read `_shared-rules.md`, that reviewer's persona file and `_output-format.md`.
2. Re-read `<RUN>/work/inputs/ledger.json` from disk. The screening reviewer also reads
   `<RUN>/work/screening/before/brief.json` and `<RUN>/work/inputs/ats_view.txt`. Work
   from these files, not from your memory of earlier reviews.

While writing each review:
3. Write the JSON straight to `<RUN>/work/reviews/<id>.json` with your file tool or code
   execution. Don't show it in chat.
4. Never mention or lean on another reviewer ("as the recruiter noted" is not allowed).
   Never open `<RUN>/work/reviews/` for anything except writing your own file and running
   validate. Stay inside the persona's lens.
5. Judge each reviewer's verdict and `advance` answer from that reviewer's own decision
   question only.

After each reviewer:
6. `python3 <SKILL_DIR>/scripts/hp.py validate <RUN> <RUN>/work/reviews/<id>.json`.
   Exit 1: fix only the listed errors, once, re-reading the source files first. If it
   still fails, move on without it.
7. One short progress line in chat, nothing else, numbered by run order: "Reviewer 3 of 7
   (Hiring Manager): done".

When all seven are done:

```
python3 <SKILL_DIR>/scripts/hp.py synthesize <RUN> --mode sequential
```

## 4. Lite protocol

Same run order, same files written, same validation and progress lines. The differences:

1. Read only `_lite-cards.md` and `<RUN>/work/inputs/ledger.json`. Don't read
   `_shared-rules.md`, `_output-format.md` or the full persona files: each card carries the
   rules and the allowed values its reviewer needs. Quotes are still copied word for word
   from the ledger's R# and J# lines.
2. Before each reviewer, re-read that reviewer's card (with the rules at the top of
   `_lite-cards.md`) and `ledger.json`, then play only that card. The screening reviewer also reads `<RUN>/work/screening/before/brief.json` and
   `<RUN>/work/inputs/ats_view.txt`, as its card says.
3. If a review fails validation, fix only the listed errors. Open `_output-format.md` only
   if the error message alone doesn't tell you the allowed value.
4. Keep each review short: the fewest findings that cover the real problems.

When all seven are done:

```
python3 <SKILL_DIR>/scripts/hp.py synthesize <RUN> --mode lite
```

## 5. If you get cut off

The early report in SKILL.md Step 4 exists for this mode. Build and share it right after
synthesis, before the questions, so the student keeps the feedback even if a usage limit
stops the rewrite. If a limit hits mid-panel, the review files already written are kept;
when the student comes back in the same chat, run `status <RUN>`, then continue with the
next reviewer that has no valid file.

## 6. Provenance audit in this mode

There's no fresh subagent here, so you do the audit yourself (references/provenance-audit.md,
`"mode": "self"`) and say so. The report shows the audit as "self".
