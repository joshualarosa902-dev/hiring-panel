# Rewrite rules

Read this before you write `work/rewrite/resume.json`. The new resume is built from the candidate's actual
experience only: the numbered lines of their resume (`R#` in `work/inputs/ledger.json`) and the answers they
gave (`Q#` in `work/answers.json`). Nothing else. The job posting tells you which true things to put first and
which words to use for them. It is never evidence.

The script `hp.py truth RUN` checks every claim and must pass before anything is rendered. A second reader (the
Skeptic, in provenance mode) then re-reads every reworded bullet. Write so both pass the first time.

What to read: this file, `work/inputs/ledger.json` (the R# lines), `work/answers.json` (the Q# answers) and the
`weaknesses` list in `work/report.json` (each has `issue_id`, `title` and `fix`; use those ids in
`meta.addressed`). You don't need the much larger `synthesis.json` or the full schema: section 14 shows a
complete, valid resume.json to copy the shape from.

## 1. The evidence model

Every bullet (and a summary, if there is one) carries `evidence`: one or more `{src, ref, quote}` items.

| src | ref | quote |
|---|---|---|
| `orig` | `R12` or a range `R12-R14` | words copied exactly from that line (case and spacing do not matter) |
| `user` | `Q2` | words copied exactly from that answer (for a keyword answer, from a yes/some item's term or detail) |

- Never `J#`, never `src: "jd"`, never a quote copied from the posting. That is `JD_AS_EVIDENCE`.
- Only answers with `status: "answered"` count. A declined or skipped answer is `BAD_REF`.
- For keyword answers, only items answered `yes` or `some` count. A `no` is not evidence, even if the term
  appears in the question.
- Cite every line a bullet draws on. A number, tool or name must be in the lines the bullet cites (or in its
  own entry's header), not just somewhere else in the resume. Moving "15" from the survey line into a job
  bullet is `NUMBER_NOT_IN_SOURCE`.
- Entries (`org`, `role`, dates) and skill groups should cite their lines too (`"evidence": [{"src": "orig", "ref": "R9-R10"}]`).

Example:
```json
{"id": "exp1.b1",
 "text": "Created and posted Instagram content 4x a week for both store locations over 10 weeks, growing the account by {{p1}} followers",
 "textIfUnknown": "Created and posted Instagram content 4x a week for both store locations over 10 weeks",
 "evidence": [{"src": "orig", "ref": "R11", "quote": "made instagram posts 4x a week for both stores for 10 weeks"},
              {"src": "user", "ref": "Q2", "quote": "about 600"}],
 "ops": ["REPHRASE", "QUANTIFY_FROM_USER"]}
```

## 2. Allowed operations (record them in `ops`)

| op | what it means | example |
|---|---|---|
| REORDER | move sections, entries or bullets | Education first for students; the most relevant bullet first |
| REPHRASE | stronger verb, same claim, same ownership level | "made a survey" -> "Designed a survey" |
| TIGHTEN | cut filler, keep every fact | "was responsible for helping customers" -> "Helped customers" |
| SURFACE | bring a fact from another line or an answer into this bullet, and cite both | hours per week from Q4 |
| MERGE / SPLIT | join two related lines, or split one that holds two ideas | spreadsheet + "showed the owner" |
| MIRROR | use the posting's word for something the evidence already shows (section 6) | "pivot tables" -> "Excel pivot tables" only if Excel is in the cited lines |
| QUANTIFY_FROM_SOURCE | a count, frequency, size or length already in the source | "4x a week", "10 weeks" |
| QUANTIFY_FROM_USER | a number the candidate gave, with their hedge | "about 600" stays "about 600" |
| STANDARDIZE | standard headings, one date style, abbreviations written out | "Sept 2023" -> start "2023-09"; "Sr." -> "Senior" |
| RELABEL_SECTION | put a class project under Projects with its context shown | "Marketing Analytics class project" |
| CUT | drop a line; list it in `meta.cuts` with a reason (section 9) | |
| KEEP | unchanged | |

Never compute new numbers (no totals, averages or percentages the candidate did not state). If a total would
help, ask for it in the question batch.

## 3. Forbidden (the truth check or the Skeptic will catch these)

- New employers, schools, titles, degrees, minors, GPA, honors, certifications, awards or locations.
- New dates, or more precision than the source ("Summer 2025" stays "Summer 2025" in `dateText`, never 2025-06).
- New or bigger numbers, rounding up, a percentage without a base, a number moved to a different claim.
- Dropping a hedge: "about 600" -> "600", "50-100" -> "100", "nearly 300" -> "over 300", "some weekends" ->
  "every weekend", "SQL (class)" -> "SQL".
- New tools, technologies, skills or proficiency levels ("Spanish (fluent)" is fine only if the source says fluent).
- Ownership upgrades (section 4).
- Invented outcomes, causes or scope: "which increased sales", "high-volume", "company-wide", "for 5,000
  customers", "with local brand managers". If the source does not say it, the bullet does not say it.
- Changing employment type (volunteer to paid, class project to internship, part-time to full-time).
- Changing contact details. Name, email, phone, city and links stay exactly as given (formatting may change).
- Hidden, white or tiny text; keyword blocks; pasting the posting.
- Anything about protected traits (age, race, religion, disability, family status and so on), and any advice to
  change a name or hide identity.
- Other people's details. When an answer is about someone else (a relative's health, a child, a patient), the
  resume gets a minimal honest label for the candidate's own role, such as "Family caregiver", and bullets about
  what the candidate did ("Help a family member get around the house a few days a week"). Never their health,
  medications, diagnosis, age or name, and never home-language or family-background details. The report never
  repeats them either.

## 4. Ownership ladder (sideways moves only)

| level | verbs |
|---|---|
| 1 | participated, assisted, helped, supported, joined, attended, volunteered |
| 2 | contributed, created, built, made, designed, analyzed, trained, wrote, prepared, presented, planned, tracked, ran |
| 3 | co-led, coordinated, organized, launched, initiated, facilitated |
| 4 | led, managed, directed, supervised, oversaw, owned, headed, spearheaded, founded, chaired |

- A rewrite may use a verb at the same level as the source or lower. Never higher.
- A level 4 verb needs a level 4 word in the cited lines, or a leadership title on the entry (President,
  Captain, Chair, Lead, Manager, Founder, Director, Supervisor).
- "Helped plan", "assisted with", "supported the" keep a helper word: "Helped plan 2 speaker events",
  "Co-planned", or "with the events team". "Planned 2 speaker events" claims more than the candidate did.
- "Responsible for opening shifts" is not "Managed opening shifts". Say what they did: "Opened the store on
  some weekends".

## 5. Hedges

Keep the candidate's uncertainty word for word.
- Numbers: about, around, roughly, approximately, nearly, almost, over, more than, up to, under, ranges
  ("50-100") and "+" ("40+") all stay. Turning "nearly" into "over" is a bigger claim and fails.
- Frequency and extent: "some", "sometimes", "occasionally", "a few", "part of" stay. Do not write "every",
  "all", "always", "daily", "entire", "sole", "independently" unless the source says so.
- Skill qualifiers: "SQL (class)" stays qualified ("SQL (coursework)" is fine). A keyword answered `some` goes
  in with a qualifier taken from the candidate's detail: "SQL (coursework)", "Tableau (class project)".
- Dot, bar or star ratings ("Python ●●●○○", a 4-of-5 bar): drop the rating. List the skill only if a bullet
  shows it or the candidate answered yes or some, with an honest qualifier from their own words when they gave
  one. Never write a level ("advanced", "proficient", "strong") that the dots seemed to imply.

## 6. MIRROR: using the posting's words honestly

Use a posting term only when it names the same thing the evidence shows, or a truthful broader category of it.
- Allowed: the evidence says "pivot tables" and the posting says "Excel (pivot tables, lookups)": "analyzed
  responses with Excel pivot tables" only if Excel is in the cited lines. Spelling or form changes are fine
  ("A/B tests" for "AB testing" when the candidate ran them).
- Allowed: a broader truthful category. "Customer service" for "helped customers at the service desk".
- Not allowed: a posting term the candidate has not shown ("Tableau dashboards" from "made charts"), a level
  they did not claim ("advanced Excel"), or a responsibility they did not do ("A/B testing" from "posted
  content").
- List the posting terms a bullet now uses in `jdTerms`. The truth check flags posting-only words in
  `NEW_WORDING` with "(job posting)"; the Skeptic looks hardest at those.
- General review (no posting): no mirroring at all.

## 7. Placeholders for missing facts

When a bullet would be stronger with a number only the candidate knows, write `{{p1}}` in `text`, write the
honest no-number version in `textIfUnknown` (required), and add the placeholder:
```json
"placeholders": {"p1": {"bullet": "exp1.b1", "ask": "Roughly how many followers did the account gain in your 10 weeks?",
                        "kind": "count", "label": "followers gained", "status": "answered", "value": "about 600", "question": "Q2"}}
```
- The question goes into the one batch (`references/questions.md`); `question` is its Q id.
- `answered`: `value` is the candidate's words verbatim, hedge included, and must appear in that answer.
- `declined`, `not sure`, skipped or no reply: set `status` to `declined` (or leave `open`) and `value` null; the
  file uses `textIfUnknown`.
- `textIfUnknown` must read naturally and claim nothing new. Never invent a "typical" number.
- When the answer comes in, copy it into `placeholders.p#.value` verbatim, set `status` to `answered` and
  `question` to its Q id; a declined number sets `status` to `declined`. A number the candidate already gave in
  another answer can go straight into the bullet with `QUANTIFY_FROM_USER` instead; both are fine.
- Final files never contain `{{` or `[ADD:`. `hp.py render --draft` shows highlighted `[ADD: label]` in a
  `_DRAFT` file for a preview only.

## 8. Shape of a strong student resume

- Sections in this order for students: Education, Experience, Projects, Leadership & Activities (or Volunteer
  Experience), Skills. Experienced candidates: Experience first. Use standard headings in the resume's language.
- Sentence case in bullets. Start with a verb. One idea per bullet, at most two lines, three to five bullets
  per role (fewer for small roles; never pad).
- Lead each bullet with what they did, then the result if the source or an answer gives one. If there is no
  result, stop after the action. No made-up outcomes.
- A headline is optional (at most 80 characters) and uses only evidenced facts, such as the degree field and
  the kinds of work the lines show. Never write the posting's job title into it on your own: it isn't a fact
  about the candidate. When the screening check suggests a headline naming the
  role (KW-004), that is a suggestion for the candidate. Mark that issue `needs_you` with a note offering it as
  their choice; use the title only if they asked for it in their answers.
- Students: no summary by default. Keep one only if the source has one and it states checkable facts.
- Skills: group as "Label: a, b, c", only skills shown in the source or answered yes/some.
- `layout`: "classic" (default; dates right-aligned) or "inline". The render step switches to inline by itself
  if the screening gate finds merged words or reading-order problems.

## 9. Long resumes and cuts

- Page target comes from `meta.locale` and `meta.stage` (`hp/data/locale_norms.json`; US and Canada students
  1 page on Letter, most other countries A4). Set `meta.targetPages` only to override it, and `null` for
  academic or federal CVs (no page target; say they are outside v1 norms).
- If the content is over the target, ask the candidate which roles to keep (one line, in the question batch or
  right after it). Never decide silently which real experience disappears.
- Cut in this order: repeated or weak bullets in old or unrelated roles, then extra bullets in kept roles,
  then (only with the candidate's OK) whole old entries. Never cut contact details, the most recent education,
  or anything the posting requires.
- List every dropped source line in `meta.cuts` as `{"ref": "R19", "reason": "..."}`, on any resume, long or
  short (a profile, interests, a rating line). The report shows each cut. The truth check warns `UNLISTED_CUT`
  for a source line that vanished without being listed.
- Render exit code 3 means the file is still too long: cut per these rules, run truth again, render again.

## 10. Locale, CV wording and the page

- `meta.locale` (for example `en-US`, `en-GB`, `de-DE`) sets paper (Letter for en-US and en-CA, otherwise
  A4), the page target and the document's language tag. Use the word the locale uses (resume or CV) in chat.
- Photo and date of birth: follow `references/locale-norms.md`. Where they are customary (for example
  Germany), keeping them is not a flaw. Never add either; never remove one without telling the candidate why.
- GPA in the US and Canada (keep it if 3.0 or higher, or if the candidate wants it); degree classification
  (for example "Upper Second-Class Honours") in the UK and Ireland. Never convert one to the other.
- Keep phone numbers and addresses in the candidate's own format.

## 11. Non-English resumes

- Rewrite in the resume's language. Never translate unless the candidate asks.
- Use headings in that language and set `meta.labels` for the few words the renderer adds:
  `{"present": "Actualidad", "coursework": "Cursos relevantes", "gpa": "Promedio", "minor": "Especialidad secundaria",
  "months": ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]}`.
- The keyword match is not scored for non-English resumes; do not chase English keywords.
- The built-in PDF writer only handles Western European letters. Names in other scripts need Chrome, Edge,
  Brave or LibreOffice for the PDF; otherwise the render step skips the PDF and the .docx is the file to send.

## 12. Record what you did

- `meta.addressed`: one entry per ranked issue you acted on, `{"issue_id": "I3", "status": "fixed|needs_you|gap",
  "note": "<= 140 characters"}`. Take the ids from `work/report.json` `weaknesses` (re-read them after any
  merge; ids are renumbered). `fixed` only when the new resume actually fixes it; `needs_you` when it waits on
  a fact or a choice from the candidate; `gap` when no honest wording can fix it (say what would, kindly).
- Missing-keyword issues: `fixed` only if every term the issue names is now on the resume from the
  candidate's own lines or yes/some answers. If some terms stay missing, use `needs_you` or `gap` and name them.
- `originalText` on reworded bullets helps the before/after view (optional).

## 13. The truth loop

1. `hp.py truth RUN`. Fix every error, then run it again until it passes:

| code | usual fix |
|---|---|
| ENTITY_NOT_IN_SOURCE | use the employer, school, title or place exactly as the source has it |
| DATE_NOT_IN_SOURCE / DATE_PRECISION_ADDED | copy the source dates; use `dateText` for seasons and vague dates |
| NUMBER_NOT_IN_SOURCE | remove the number, cite the line it comes from, or ask for it as a placeholder |
| TERM_NOT_IN_SOURCE / SKILL_NOT_IN_SOURCE | remove the tool or skill, or cite the line that shows it |
| OWNERSHIP_UPGRADED | go back to the source's level (section 4) |
| HEDGE_REMOVED | put the hedge or qualifier back (section 5) |
| EVIDENCE_QUOTE_NOT_FOUND / BAD_REF | copy the quote exactly and point at the right R# or Q# |
| NO_EVIDENCE | cite the source line or answer, or drop the bullet |
| JD_AS_EVIDENCE | remove the posting reference; the claim needs the candidate's own line |
| PLACEHOLDER_LEFT | add `textIfUnknown` or resolve the placeholder |
| CONTACT_CHANGED | copy the contact details exactly |

2. Audit every `NEW_WORDING` warning (`references/provenance-audit.md`): read the bullet next to its quotes and
   delete any outcome, scope or cause the quotes do not state. In Claude Code a fresh Skeptic subagent writes
   `work/rewrite/provenance.json`; elsewhere you write it yourself with `"mode": "self"`.
3. Apply every `soften` and `remove` verdict, run truth again, then `hp.py render RUN`. Render refuses until the
   truth check and the provenance gate both pass.

## 14. A complete resume.json

Short, but with every required field and one of each common part: education, an experience entry with a
placeholder, a class project, a certification (`name` is the certificate, `org` the issuer), skill groups,
`meta.addressed` and `meta.cuts`. All fictional. It cites lines such as R10 "• Made instagram posts for the
cafe 3x a week", R18 "Excel ●●○○○" (the rating is dropped) and R19-R20 (Interests, cut), plus Q1, a keyword
answer with "Excel" answered `some` ("made budget sheets in my Intro to Business class"), and Q2, a declined
number question. Section types: `education`, `experience`, `projects`, `skills`, `summary` or `custom` (any
other heading, such as Certifications, Volunteer Experience or Leadership & Activities).

```json
{"schemaVersion": "1.0",
 "meta": {"variant": "improved", "locale": "en-US", "stage": "student", "layout": "classic",
          "target": {"role": "Marketing Assistant", "company": "Harbor Books"},
          "addressed": [{"issue_id": "I1", "status": "fixed", "note": "The Instagram bullet now leads your experience."},
                        {"issue_id": "I2", "status": "needs_you", "note": "Add how many followers the account gained if you can find out."},
                        {"issue_id": "I3", "status": "gap", "note": "No Google Analytics yet. A small project of your own that uses it would close this."}],
          "cuts": [{"ref": "R19-R20", "reason": "Interests take space that your experience needs on one page."}]},
 "basics": {"name": "Avery Quinn", "location": "Dayton, OH", "email": "avery.quinn@example.com", "phone": "(555) 010-0199"},
 "sections": [
  {"id": "education", "type": "education", "title": "Education",
   "items": [{"id": "edu1", "school": "Riverbend College", "location": "Dayton, OH", "degree": "B.A.",
              "field": "Communication", "end": "2027-05", "endLabel": "Expected",
              "evidence": [{"src": "orig", "ref": "R4-R5"}]}]},
  {"id": "experience", "type": "experience", "title": "Experience",
   "items": [{"id": "exp1", "org": "Maple Street Cafe", "role": "Barista", "location": "Dayton, OH",
              "start": "2024-06", "end": "present", "evidence": [{"src": "orig", "ref": "R7-R8"}],
              "bullets": [
               {"id": "exp1.b1", "text": "Posted Instagram content for the cafe 3x a week, growing the account by {{p1}} followers",
                "textIfUnknown": "Posted Instagram content for the cafe 3x a week",
                "evidence": [{"src": "orig", "ref": "R10", "quote": "Made instagram posts for the cafe 3x a week"}],
                "ops": ["REPHRASE", "REORDER"], "originalText": "Made instagram posts for the cafe 3x a week"},
               {"id": "exp1.b2", "text": "Helped train new baristas on the espresso machine",
                "evidence": [{"src": "orig", "ref": "R9", "quote": "Helped train new baristas on the espresso machine"}],
                "ops": ["KEEP"]}]}]},
  {"id": "projects", "type": "projects", "title": "Projects",
   "items": [{"id": "proj1", "name": "Campus Food Survey", "context": "Research Methods class project",
              "dateText": "Spring 2025", "evidence": [{"src": "orig", "ref": "R12"}],
              "bullets": [{"id": "proj1.b1", "text": "Designed a 10-question survey and collected 85 responses",
                           "evidence": [{"src": "orig", "ref": "R13", "quote": "Designed a 10 question survey and collected 85 responses"}],
                           "ops": ["TIGHTEN"]}]}]},
  {"id": "certifications", "type": "custom", "title": "Certifications",
   "items": [{"id": "cert1", "name": "ServSafe Food Handler", "org": "National Restaurant Association",
              "dateText": "2024", "evidence": [{"src": "orig", "ref": "R15"}]}]},
  {"id": "skills", "type": "skills", "title": "Skills",
   "groups": [{"label": "Tools", "items": ["Canva", "Google Sheets", "Instagram", "Excel (coursework)"],
               "evidence": [{"src": "orig", "ref": "R17-R18"},
                            {"src": "user", "ref": "Q1", "quote": "made budget sheets in my Intro to Business class"}]}]}],
 "placeholders": {"p1": {"bullet": "exp1.b1", "ask": "Roughly how many followers did the cafe account gain since you started posting?",
                         "kind": "count", "label": "followers gained", "status": "declined", "value": null, "question": "Q2"}}}
```

Q2 was declined, so the files use `textIfUnknown` and I2 stays `needs_you`. Had the candidate answered "about
150", `status` would be `answered`, `value` "about 150", and the bullet would cite Q2 with `QUANTIFY_FROM_USER`.
