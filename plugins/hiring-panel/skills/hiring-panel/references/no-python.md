# Manual mode (no Python)

Use this when SKILL.md Step 0.2 found no Python 3.8 or newer: a Mac without Apple's
developer tools, a Windows PC without Python, or Python that won't start. You follow the
same flow and the same honesty rules, but no script runs. That has three consequences
you must state plainly:

1. Everything is **model-only**: the screening check, the ranking and the truth check are
   your own judgment, not script results. Label them that way in chat and in the report.
2. **No scores.** Show no screening number and no percentages. The only number you may
   show is the panel vote, counted from the seven reviewers' `advance` answers, labeled
   model-only.
3. **Fewer files.** You write the resume as .md and .docx, and the report as .md. The
   student makes the PDF by opening the .docx and saving it as PDF.

Tell the student once, at the start:

> Python isn't available here, so I'll run Hiring Panel in manual mode. You still get the
> full panel and an honest rewrite, but the checks are my own judgment instead of the
> scripts, and there's no screening score. You'll make the PDF yourself from the Word file
> (it takes one click).

Never install anything to get Python. If the student wants the full version later: on a
Mac they can install Apple's free Command Line Tools themselves (see
references/troubleshooting.md), on Windows they can install Python 3 from python.org or
the Microsoft Store, then start a new run.

## 1. Run folder

Create `hiring-panel-runs/<YYYY-MM-DD-HHMM>-<company>-<role>/` in the working folder
(lowercase, hyphens), and a file `hiring-panel-runs/.gitignore` containing a single `*`
so the student's resume never gets committed. Inside the run folder use the same layout as
a normal run: `work/inputs/`, `work/reviews/`, `work/rewrite/`.

## 2. Inputs

- **resume.md**: the resume's text, verbatim, one line per line, in reading order. Keep
  typos and odd wording; never fix or reorder. How to get it without Python:
  - PDF: read it with your file-reading tool.
  - .docx on macOS: `textutil -convert txt -stdout <FILE>` (built into every Mac).
  - .docx elsewhere: `unzip -p <FILE> word/document.xml`, or on Windows
    `tar -xf <FILE> -C <TEMP_FOLDER> word/document.xml`, then read the text inside the
    `<w:t>` elements in order.
  - Anything else, or if those fail: ask the student to paste the text.
- **jd.md**: the posting, pasted as is. No posting after one ask: General review (see
  references/edge-cases.md), and jd.md stays empty.
- **ledger.md**: number the non-empty lines of resume.md as R1, R2, ... and of jd.md as
  J1, J2, ..., one per line with its full text ("R7: Trained 4 new cashiers"), so reviews
  and the rewrite can point at exact lines. The reviewers read this file, not resume.md.

## 3. Screening check (model-only)

Judge from the text and from what you can see of the file. Note which of these apply,
using the same ids the script would:

| Look for | Id |
|---|---|
| Scan or image with no selectable text | PARSE-001 |
| Password protection | PARSE-002 |
| Contact details only in the page header or footer | PARSE-006 |
| Text boxes, tables holding jobs, or two columns | PARSE-007, PARSE-008, PARSE-009 |
| Big images, charts, skill bars, icons | PARSE-010 |
| L e t t e r - s p a c e d words | PARSE-014 |
| Hidden or white text, or instructions aimed at AI | PARSE-016 |
| Template placeholder text ("Company Name", "lorem ipsum") | PARSE-020 |
| No email, phone or city | CONTACT-001, CONTACT-002, CONTACT-003 |
| No Education (students), no Experience or Projects, no Skills | SECT-001, SECT-002, SECT-003 |
| Jobs without dates, year-only dates, dates split across lines | DATE-001, DATE-002, DATE-003 |
| Required posting terms the resume never shows | KW-001 |
| Terms only in the skills list, never in a bullet | KW-002 |
| Few bullets with real numbers; weak openers ("Responsible for") | CONTENT-001, CONTENT-002 |

Write `work/screening.md` with: the issues found (most serious first), the required terms
that are missing (by name, no counts), "Machine readability: Not checked (needs the
script)", keyword and content signals as words only (for example "Partial match", "Needs
work"), and this disclaimer, verbatim:

> This is a simulation, not a real applicant tracking system. Every employer sets up its
> own software, and none of the big vendors publish exactly how they parse or rank
> resumes. This check looks for problems known to break resume parsing and for
> job-description requirements your resume doesn't show. A high score doesn't guarantee
> an interview, and a low score doesn't mean a robot rejected you. Most automatic
> rejections come from application questions (work authorization, location, degree,
> availability), and no resume edit changes those.

## 4. Panel

Follow references/panel-single.md (sequential, or lite on the Free plan), with these
changes: every reviewer reads `ledger.md` where that file says `ledger.json`, and the
screening reviewer reads `work/screening.md` instead of the brief and ats_view.txt; there
is no `validate` step, so re-read `_output-format.md` and check your own JSON before
moving on; skip the `synthesize` command. Give the single-conversation disclosure as usual.

## 5. Combine and rank (model-only)

Merge findings that point at the same problem. Rank by severity (critical, major,
moderate, minor), then by how many reviewers raised it, then by how early in hiring it
bites (screening, recruiter skim, hiring manager, interview). Put inflated or unverifiable
claims rated major or worse under "Fix before you send", whatever their rank. Count the
vote from the `advance` answers ("3 of 7 would move you forward").

Write `Hiring_Panel_Report.md` in the run folder now, before any rewrite, in this order:
the header with the vote and "Manual mode (model-only)", then the Recruiter's
`seven_second_takeaway` as "What a recruiter sees in 7 seconds"; Fix before you send; Biggest
weaknesses, most serious first (top 5); the panel (7 rows: name, lens, verdict, advance,
one-line take); where the panel disagreed; keyword gaps to close honestly; what's already
working; interview prep (questions from the Hiring Manager and Skeptic); mode and
limitations. Mask the email and phone (for example `j***@example.com`, `***-***-1234`).
Call the resume strong only when at least 5 reviewers said yes and no issue is critical or
major. Then add one line under the vote: "Strong resume. The <reviewer with the lowest
verdict> came closest to saying no: <its top issue>. It still held because that is a
<moderate or minor> issue, not a critical or major one." Never call it strong otherwise.
State this near the top:

> Manual mode: Python wasn't available, so no scripts ran. The screening check, the
> ranking and the truth check in this report are Claude's own judgment (model-only), not
> script results. The panel ran in one conversation, so the reviewers weren't fully
> independent.

Share the report with the student, then the summary and ONE question batch exactly as in
SKILL.md Step 5 (references/questions.md). Save their answers to `work/answers.json`.

## 6. Rewrite and truth check (model-only)

Follow references/rewrite-rules.md for what may change. Write the improved resume directly
as Markdown: `<First_Last>_Resume.md` in the run folder (ASCII letters, spaces as `_`;
`My_Resume` if there's no name). Then audit it yourself following
references/provenance-audit.md: put every bullet next to its R# lines or Q# answers and
remove or soften anything they don't say. Use the inline layout (dates after " | " on the
same line), single column, standard headings, contact details in the body.

Add to the report: what changed, what still needs the student, real gaps, and
"Truth check: model-only (no script ran)". Never write "0 invented facts" in manual mode.

## 7. The Word file, from the skeleton

`<SKILL_DIR>/assets/docx-skeleton/` holds every part of a .docx except the resume text. If
that folder has its own README, its instructions win over the recipes below.

1. Copy the whole skeleton folder to a working folder, for example `work/docx/`.
2. Write `work/docx/word/document.xml` from these recipes, one paragraph per line of the
   resume, in order:

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><w:body>
<w:p><w:pPr><w:pStyle w:val="Title"/><w:jc w:val="center"/></w:pPr><w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve">Jordan Example</w:t></w:r></w:p>
<w:p><w:pPr><w:pStyle w:val="HPContact"/><w:jc w:val="center"/></w:pPr><w:r><w:t xml:space="preserve">Austin, TX  |  jordan@example.com  |  555-010-0199</w:t></w:r></w:p>
<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve">EDUCATION</w:t></w:r></w:p>
<w:p><w:pPr><w:pStyle w:val="HPEntry"/></w:pPr><w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve">Example State University</w:t></w:r><w:r><w:t xml:space="preserve"> | Austin, TX | Expected May 2027</w:t></w:r></w:p>
<w:p><w:pPr><w:pStyle w:val="HPBullet"/><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr><w:r><w:t xml:space="preserve">Organized weekly study sessions for about 20 classmates</w:t></w:r></w:p>
<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1008" w:right="1008" w:bottom="1008" w:left="1008" w:header="432" w:footer="432" w:gutter="0"/><w:cols w:space="720"/></w:sectPr>
</w:body></w:document>
```

   - Paragraph styles: `Title` (name), `HPHeadline` (optional headline), `HPContact`,
     `Heading1` (section headings, typed in capitals), `HPEntry` (first line of an entry),
     `HPEntrySub` (second line of an entry), `HPBullet` (bullets, always with the `numPr`
     shown), `HPBody` (plain paragraphs).
   - Escape `&` as `&amp;`, `<` as `&lt;`, `>` as `&gt;` and `"` as `&quot;` in text.
   - No tabs, tables, text boxes, images, headers or footers. Never white, hidden or tiny
     text.
   - Page size: Letter (`12240` by `15840`) for US and Canada; A4 (`11906` by `16838`)
     everywhere else.
3. If the skeleton has no `word/_rels/document.xml.rels`, write it:

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/></Relationships>
```

4. If the skeleton has no `docProps/core.xml`, write one whose `dc:title` is
   "<Name> Resume" and `dc:creator` is the student's name (never the tool's name):

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Jordan Example Resume</dc:title><dc:creator>Jordan Example</dc:creator></cp:coreProperties>
```

5. Zip the parts, with `[Content_Types].xml`, `_rels`, `docProps` and `word` at the top
   level of the archive (not inside a folder):
   - macOS or Linux: `cd <RUN>/work/docx && zip -X -r <RUN>/<First_Last>_Resume.docx "[Content_Types].xml" _rels docProps word`
   - Windows: `tar -a -c -f <RUN>/<First_Last>_Resume.zip -C <RUN>/work/docx "[Content_Types].xml" _rels docProps word`,
     then rename the .zip to .docx. This route is less tested; if it fails, give the
     student the .md and suggest pasting it into Word or Google Docs.
   Don't use `textutil` to make the .docx; it writes a file Word handles badly.
6. Ask the student to open the .docx and check it looks right.

## 8. PDF and delivery

There is no PDF engine in manual mode. Tell the student: "Open
<First_Last>_Resume.docx in Word, Google Docs or Pages and use Save As or Download to make
a PDF." Then deliver as in SKILL.md Step 8, with the manual-mode note instead of script
results: the vote (model-only), the top weakness, where the files are
(`<First_Last>_Resume.md`, `<First_Last>_Resume.docx`, `Hiring_Panel_Report.md`), and the
offer of interview-prep questions or a new run.

## 9. No tools at all

If you can't run any command or create any file (for example code execution is turned
off), do the panel and the rewrite in chat: the report and the resume as Markdown in your
messages, labeled model-only, following the same order and rules. Tell the student the
full version needs code execution: on claude.ai, Settings > Capabilities > "Code execution
and file creation" (school or work accounts may need an admin to allow it).
