# Hiring Panel data files

Dictionaries read by the screening check (`hp.screen`), the renderer (`hp.render`) and, through
`references/locale-norms.md`, the reviewers. Formats are fixed by ARCHITECTURE.md sections 6.4 and
6.5. Lines starting with `#` are comments in every `.txt` file. All files are UTF-8, LF, no BOM.
Hand-written for Hiring Panel; no O*NET or Lightcast data is included, so no attribution is owed.

| File | What it holds |
|---|---|
| `skills.json` | about 1,450 skills, tools, certifications, domains, soft skills and job titles |
| `headings.json` | resume section synonyms (16 sections) and job-posting block headings |
| `action_verbs.txt` | 580+ bullet-opening verbs; `base` or `base\|past` |
| `weak_openers.txt` | prefixes such as "responsible for", "helped with" |
| `buzzwords.txt` | about 80 filler claims, flagged only when nothing backs them up |
| `stopwords_en.txt` | English function words (also used to spot non-English text) |
| `jd_stopwords.txt` | job-posting filler ("ability", "strong", "excellent") |
| `us_states.json` | 50 states, DC and 5 territories, `{"TX": "Texas"}` |
| `countries.txt` | country names and common short forms |
| `locale_norms.json` | paper, page targets, photo and date-of-birth norms, grades, with sources |
| `VERSION` | dictionary version, `1.0.0` |

## skills.json entries

```
{"id", "canonical", "kind": hard|tool|cert|domain|soft|title,
 "aliases": [], "acronyms": [], "case_sensitive": bool, "ambiguous": bool,
 "context": [], "implies": []}
```

- Forms are `canonical` + `aliases` + `acronyms`. Each is a literal (use `re.escape`) bounded by
  `(?<![\w+#.])` and `(?![\w+#])`. Every form is already in `util.norm_text` form.
- `case_sensitive: false`: compare all forms casefolded. Acronyms of such entries are never
  ordinary English words (tests enforce it), so casefolding them is safe; matching short acronyms
  case-sensitively is still recommended.
- `case_sensitive: true`: compare every form exactly as written. Used where the lowercase word is
  ordinary English (Excel, Slack, Zoom, Agile, REST). Such entries list the case variants they
  accept, including lowercase multi-word forms such as "agile methodology".
- `ambiguous: true`: a hit counts in full only when a `context` word (case-insensitive, same
  boundaries) is on the same line; otherwise give the reduced "ambiguous" credit. On the job
  posting side, drop ambiguous hits without context. Multi-word forms of an ambiguous entry always
  contain one of its context words, so "Google Cloud Platform" disambiguates itself and only "GCP"
  needs help.
- `implies`: entry ids, already closed transitively and sorted (PostgreSQL implies SQL and
  Relational Databases; Pivot Tables implies Microsoft Excel and Microsoft Office).
- Kind `title` entries never use plural aliases and never a bare generic word (Engineer, Designer,
  Server), so "partner with designers" never becomes a title requirement.
- Entries are sorted by `id`, one per line, so diffs stay readable. Edit the JSON directly and run
  `python3 -m unittest discover -s tests -p 'test_lexicon_*.py'` before committing.

## Matching notes for the screening code

- Phrases containing an apostrophe ("Raiser's Edge", "teacher's aide", "Commercial Driver's
  License") or " & " ("mergers & acquisitions") need the matcher to treat `'` and `&` between
  words as joiners; apostrophe-free and "and" variants are listed where people use them.
- A few forms contain commas ("Diversity, Equity, and Inclusion"); a phrase matcher that breaks on
  commas will rely on their acronyms and comma-free aliases instead.
- Plural stemming maps "logistic" (as in logistic regression) to Logistics and "Canvas" to Canva;
  Canva is ambiguous for that reason. Prefer an exact longer match over a stem match on the same
  words.

- Do not add slash pairs of two certifications or tools as one alias ("BLS/CPR"). The screening
  code reads "BLS/CPR", "Python or R" and "Tableau, Looker or Power BI" as one requirement that any
  member satisfies, so each member must be found on its own.
- Programming languages that are also letters or words (R, C, Go, Swift) imply
  `computer-programming`; the screening code then also accepts "in R" on a line about data or code,
  "R (", or another language on the same line, besides the `context` words.

## Adding an entry

1. Pick the most common written form as `canonical`; add real variants as aliases (spelling,
   hyphenation, plural for multi-word skills, "X certification" for certs).
2. If any form is an ordinary English word, mark the entry `case_sensitive`, or `ambiguous` with at
   least three context words, or drop that form.
3. Never add a form that another entry already owns, and never a bare US state or Canadian
   province code (PA, QC, OR).
4. Keep `implies` closed: if A implies B and B implies C, A lists both.
