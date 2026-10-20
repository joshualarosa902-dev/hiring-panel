# Changelog

All notable changes to Hiring Panel are listed here. Versions follow
[Semantic Versioning](https://semver.org/). The version also appears in the report footer
("Hiring Panel v1.0.0") and must match `plugins/hiring-panel/.claude-plugin/plugin.json`,
`.claude-plugin/marketplace.json` and
`plugins/hiring-panel/skills/hiring-panel/scripts/hp/__init__.py`; `scripts/release.sh`
checks this.

## [1.0.0]

First public release.

### Added
- The seven-reviewer panel: Automated Screening Check, Hiring Manager, Recruiter,
  Competing Applicant, CEO, Future Teammate and Skeptic.
- Parallel mode for Claude Code (seven independent subagents) and single-conversation
  modes for claude.ai (sequential, and lite for the Free plan), with the independence
  disclosure in chat and in the report.
- A deterministic, simulated screening check: machine readability, job-keyword match and
  content signals, one overall number in steps of 5, bands and exact counts.
- Script-only ranking of the panel's findings, biggest weaknesses first, with integrity
  issues pinned under "Fix before you send".
- One batch of at most 7 questions before the rewrite (a builder interview of at most 8
  for very short resumes).
- An honest rewrite with a script truth check, a provenance audit, and a quality gate that
  re-runs the screening check on the generated files.
- Resume output as .docx, .pdf and .md; report output as a one-page .pdf plus .md and .html.
- General review when there is no job posting; locale norms for non-US CVs.
- Manual mode for machines without Python.
- Install as a claude.ai or Claude Code plugin, a `.plugin` upload, or a skill zip.
- One-line use in Claude Code: `/hiring-panel <resume file> <job posting, link or role>`.
- The Recruiter's 7-second first impression, right under the report's verdict strip.
- A plain "strong resume" line, shown only when at least 5 of 7 reviewers say yes and nothing
  critical or major turned up. It names the reviewer who came closest to saying no and why the
  resume still held.
- Credits and a CITATION.cff, including the original hiring-panel skill by Alex Chen that
  inspired this rebuild.

### Changed before release (from live end-to-end tests)
- Reviewers read one file of numbered lines (the ledger), which already holds the whole
  resume and posting, instead of separate copies on top of it. Lite reviewers read only
  their card and the ledger. This lowers plan usage.
- Claude reads your stage (for example "student") from your resume and says it in the
  first confirmation, so you can correct it instead of it being guessed silently.
- A shorter first summary: the top 3 weaknesses in chat, one fact per question, one
  closing line, and a single rule for the question batch (at most 7, or a builder
  interview of at most 8 for a very short resume, with the keyword list counting as one).
- The optional posting-terms step only adds skills, tools, certifications and
  qualifications the posting names, never terms picked to raise the score, and tells you
  how many terms it added.
- Answers about other people (a relative's health, a child) become a short label such as
  "Family caregiver"; their details never reach the resume or the report.
- The posting's job title is offered as your choice for the headline, never written in
  for you. Dot and bar skill ratings are dropped instead of being turned into a level.
- After the files are built, Claude checks that every entry and bullet made it into the
  resume, and the final message names real gaps kindly, with an honest way to close each.
- The README gives measured times and plan usage from a test run and written setup steps
  in place of screenshot placeholders.
