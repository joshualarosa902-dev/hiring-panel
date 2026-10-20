# Hiring Panel

A free, open-source Claude plugin that reviews a resume or CV against one job posting
with a simulated 7-reviewer hiring panel, puts the biggest weaknesses first, and then
rebuilds the resume honestly from the candidate's real experience as .docx, .pdf and .md,
with a one-page report.

## The panel

1. Automated Screening Check (a deterministic script: machine readability and missing
   keywords, always labeled "simulated")
2. Hiring Manager
3. Recruiter
4. Competing Applicant
5. CEO
6. Future Teammate
7. Skeptic

In Claude Code, the seven reviewers run as independent parallel subagents. On claude.ai
(including the Free plan), one conversation plays the seven roles in turn, and the report
discloses that the independence is approximate.

## Use it

Turn on code execution (claude.ai: Settings > Capabilities > Code execution and file
creation), attach a resume, paste a job posting, and say "Use Hiring Panel to review my
resume for this job." In Claude Code you can also do it in one line, for example
`/hiring-panel ~/Documents/resume.pdf Marketing intern at Northwind` (the full form is
`/hiring-panel:hiring-panel`).

## Honesty and privacy

The rewrite never adds employers, titles, dates, numbers, tools, skills or outcomes that
aren't in the original resume or the candidate's own answers, and a script checks every
line before any file is built. The scripts use only the Python standard library, make no
network calls and send no telemetry. Contact details are masked in the report.

Full setup guide, troubleshooting and FAQ: https://github.com/joshualarosa902-dev/hiring-panel

Inspired by the original hiring-panel skill by Alex Chen (@nocodealex), MIT licensed:
https://github.com/alexyc9381/hiring-panel-skill. This version is a from-scratch rebuild. If
you also installed that skill, keep only one, since both use the `hiring-panel` command name.

MIT License. Not affiliated with Anthropic or any ATS vendor. For Claude users 18+.
