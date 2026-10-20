# Country norms for resumes and CVs

These are hiring CONVENTIONS, not laws and not rules every employer follows. They change over time
and vary by industry and company. Use them to avoid wrong advice (calling a photo a red flag in
Germany, asking a UK student for a GPA), never to judge a candidate.

Who uses this file:
- The Recruiter reviewer applies the row for `target.locale` (ledger.json) and writes that row's key
  in `lens_data.locale_applied` (no row for the locale: `default`). To keep reviewers to one data file,
  the Recruiter persona (`reviewers/03-recruiter.md`) carries a compact copy of this table and the lite
  Recruiter card a one-line summary; when you change a row here, change those two as well.
- The machine-readable twin is `scripts/hp/data/locale_norms.json` (same locales, same facts). The
  renderer and the screening check read the JSON for paper size and page targets. If this table and
  the JSON ever disagree on a point, treat that point as uncertain and raise no finding on it.

## The table

Values in `code` are the values locale_norms.json uses for paper, photo, date of birth and (US, UK,
Ireland) grades; the other grade notes are descriptive.

| Locale | Document is called | Paper | Pages: student / experienced | Photo | Date of birth | Grades |
|---|---|---|---|---|---|---|
| `en-US` United States | resume | `letter` | 1 / 2 | `omit` | `omit` | GPA optional; show it if 3.0 or higher or if the posting asks (`optional_3.0_plus`) |
| `en-CA` Canada | resume (CV for academic roles) | `letter` | 1 / 2 | `omit` | `omit` | GPA optional; scales differ by school (4.0, 4.3, 9 or 12 point, percentages), so give the scale |
| `en-GB` United Kingdom | CV | `a4` | 2 / 2 (1 is fine for school leavers) | `omit` | `omit` | degree classification: First, 2:1, 2:2, Third, or "predicted 2:1" while studying (`degree_classification`) |
| `en-IE` Ireland | CV | `a4` | 2 / 2 | `omit` | `omit` | degree classification: First, 2.1, 2.2, Third (`degree_classification`); some universities also report a GPA |
| `en-AU` Australia | resume (CV used too) | `a4` | 2 / 3 | `omit` | `omit` | WAM (weighted average mark) or GPA on a 7-point scale; honours class where relevant |
| `en-NZ` New Zealand | CV | `a4` | 2 / 3 | `omit` | `omit` | GPA (often on a 9-point scale) or letter grades; give the scale |
| `en-IN` India | resume (CV used too) | `a4` | 1 / 2 | `optional` | `optional` | CGPA on a 10-point scale or a percentage |
| `de-DE` Germany | Lebenslauf (CV) | `a4` | 2 / 2 | `customary` | `customary` | German scale 1.0 to 5.0, 1.0 best |
| `de-AT` Austria | Lebenslauf (CV) | `a4` | 2 / 2 | `customary` | `customary` | Austrian scale 1 to 5, 1 best |
| `de-CH` Switzerland | Lebenslauf (CV) | `a4` | 2 / 2 | `customary` | `customary` | Swiss scale 1 to 6, 6 best |
| `fr-FR` France | CV | `a4` | 1 / 2 | `optional` | `optional` | grades out of 20; honours ("mention") where earned |
| `es-ES` Spain | currículum (CV) | `a4` | 1 / 2 | `optional` | `optional` | 0 to 10 scale, average shown as "nota media" |
| `default` anywhere else | CV or resume (ask once if unsure) | `a4` | 1 / 2 | `omit` | `omit` | as on the transcript, always with its scale |

Meaning of the photo and date-of-birth values:
- `omit`: not expected. A photo or birth date is never a reason to reject, but you may mention it
  once as a `minor` note phrased as the local norm ("Employers here don't usually expect a photo").
- `optional`: common for some employers, expected by none. Never raise it.
- `customary`: traditionally expected and normal. Never a red flag; never advise removing it, and
  never advise adding one either.

## Notes per country (with uncertainty flagged)

- `en-US`: no marital status, nationality or references on the page. 3.0 is the most common GPA
  cutoff among employers that screen by GPA (NACE, Job Outlook 2022: 46.3% of employers screened by
  GPA). Two pages are normal only with substantial experience.
- `en-CA`: very close to US practice. Uncertain: GPA reporting differs a lot by province and school.
- `en-GB`: a short personal profile at the top is common. "References available on request" is
  common but optional. Students often list A-levels or equivalent.
- `en-IE`: close to UK practice. Students may list Leaving Certificate results. Uncertain: whether
  a GPA or a classification is expected depends on the university.
- `en-AU`: longer documents are normal. Listing referees (with their permission) or "available on
  request" is common. Uncertain: the 7-point GPA scale is common but not universal.
- `en-NZ`: similar to Australia; referees often listed. Uncertain: grading scales differ by
  university (9-point GPA at some).
- `en-IN`: students often list Class 10 and Class 12 results. Some employers still expect a photo
  or birth date, many do not. Uncertain: practice varies widely by sector, so do not raise it.
- `de-DE`: the tabular Lebenslauf is standard. Employers cannot require a photo, and more applicants
  now leave it out, so treat it as normal either way. A signature and date at the end are
  traditional but optional. Uncertain: how fast the no-photo trend is moving.
- `de-AT`: close to German practice.
- `de-CH`: close to German practice; nationality and work-permit status are often listed.
- `fr-FR`: one page is the strong norm for students and recent graduates.
- `es-ES`: a photo and personal details are common but not required.
- `default`: give no country-specific advice; keep to what any reader would understand.

Never use any of this to infer age, origin or any other protected trait, and never advise changing
a name or hiding identity markers.
