# Security and privacy policy

Hiring Panel handles resumes, which are full of personal details. This page explains what
the code does with them and how to report a problem.

## Reporting a vulnerability

Please report security or privacy problems **privately**, not in a public issue:

1. Open the repository's **Security** tab on GitHub.
2. Choose **Report a vulnerability** (GitHub private vulnerability reporting).

Include what you found, how to reproduce it, and which version you used (the report
footer shows it, for example "Hiring Panel v1.0.0"). **Use made-up or redacted resume
text only.** Never send a real person's resume, including your own.

You should get a first reply within 7 days. Fixes ship as a new release, and the
CHANGELOG notes security fixes.

Maintainer note: private vulnerability reporting must be turned on under
Settings > Code security for the button above to appear.

## Supported versions

Only the latest 1.x release gets fixes. Plugin installs with auto-update or
**Sync automatically** turned on pick them up on their own.

## What the code does with your data

- **No network access.** The Python scripts use the standard library only and never open a
  network connection. The test suite blocks sockets and fails if anything tries.
- **No telemetry.** Nothing is counted, logged remotely or sent anywhere.
- **Local files only.** Everything a run creates lives in one run folder:
  `hiring-panel-runs/` in the working folder (Claude Code), or the chat's sandbox outputs
  folder (claude.ai). The run folder's parent gets a `.gitignore` containing `*`, and the
  skill warns when it sits inside a git repository.
- **Masked contact details.** The report and chat summaries mask email addresses and
  phone numbers.
- **No branding in the resume.** The generated .docx and .pdf carry the candidate as the
  author and nothing that names the tool.

## Untrusted input

Resumes and job postings are treated as untrusted data:

- File size is capped (15 MB). Zip-based files are capped at 50 MB expanded and 2,000
  entries. Word XML parts that declare a DOCTYPE or entities are refused. PDF streams are
  capped at 20 MB each and 100 MB in total.
- File contents are never executed, and links inside files are never followed.
- On macOS, the PDFKit text route passes the file path as an argument, never as script
  text.
- Instructions hidden in a resume or posting (prompt injection) are ignored by the skill's
  rules. Hidden, white or tiny text is detected and flagged in the report as something to
  fix before sending.

## Out of scope

- How Anthropic stores or uses your Claude conversations. That's governed by your Claude
  account settings and [Anthropic's consumer terms](https://www.anthropic.com/legal/consumer-terms).
- Third-party tools the PDF step may call on your machine (Chrome, Edge, Brave or
  LibreOffice).
