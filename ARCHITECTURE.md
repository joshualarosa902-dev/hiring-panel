# Hiring Panel: architecture and build contract (v2)

This file is the single source of truth for how the pieces fit. Every module, script, prompt and
doc must agree with it. If you must deviate, keep the deviation small and list it in your report.

Research behind these decisions (read-only; port and adapt, never copy blindly):
`$RESEARCH` = `/private/tmp/claude-501/-Users-joshualarosa/f57a77eb-78ee-45b5-bbd9-ef653a9c9b2a/scratchpad/hp-research`
- `$RESEARCH/_results/critic.txt`: the completeness critic. ITS DECISIONS ARE ALREADY FOLDED INTO THIS
  FILE AND OVERRIDE THE OTHER REPORTS where they conflict. Read its "spec" (sections 1 to 5).
- `$RESEARCH/_results/platform.txt`: packaging, install paths, claude.ai vs Claude Code.
- `$RESEARCH/_results/ats.txt`: the screening-check spec (sections 0 to 19), issue catalogue, scoring.
- `$RESEARCH/_results/reviewers.txt`: the 7 personas, review schema, synthesis algorithm.
- `$RESEARCH/_results/rewrite-output.txt`: rewrite rules, truth check, renderers, report design.
- Prototypes: `$RESEARCH/ats-screening-check/` (screening.schema.json, sources.json, proto/probe.py,
  proto/make_fixtures.py, fixtures), `$RESEARCH/reviewers-synthesis/` (reviewers/*.md, schema/,
  scripts/build_ledger.py, scripts/synthesize.py, fixture/), `$RESEARCH/resume-and-files/`
  (prototype/scripts/render.py, check_truth.py, extract_text.py, schemas/, sample/, previews/).

## 1. Product promise (from the Reel; every item must be literally true)

The Reel: "make 7 Claudes reject your resume first ... the first one checks for readability issues and
missing keywords, the second plays the hiring manager, then five more read it independently, including a
recruiter, a competing applicant and the CEO ... combines all the feedback, puts your biggest weaknesses
first, and builds an improved resume around your actual experience ... completely free."

1. Automated Screening Check: machine readability + missing keywords (deterministic script, always
   labeled "simulated", never "ATS score").
2. Hiring Manager review.
3. Five more reviewers: Recruiter, Competing Applicant, CEO, Future Teammate, Skeptic.
   Claude Code: 7 truly independent parallel subagents. claude.ai: one conversation playing the 7 roles in
   sequence, disclosed as approximate independence, in chat and in the report.
4. Combined feedback, biggest weaknesses first (ranked by a script; the report LEADS with weaknesses).
5. Improved resume from the candidate's actual experience only. Never invents employers, schools,
   titles, dates, numbers, tools, skills, scope or outcomes. Missing numbers come from the candidate's
   answers or an honest no-number phrasing.
6. Files: resume as .docx, .pdf and .md; report as .pdf (one page), .md and .html.
7. Free, MIT, no accounts, no network calls or telemetry from our scripts. For Claude users 18+.

## 2. Repository layout

```
hiring-panel/                                  (repo root -> public GitHub repo OWNER/hiring-panel)
  .claude-plugin/marketplace.json              (marketplace "hiring-panel" listing one plugin)
  plugins/hiring-panel/                        (THE installable plugin; also zipped as hiring-panel.plugin)
    .claude-plugin/plugin.json
    LICENSE  README.md
    skills/hiring-panel/                       (THE skill; zipped alone as hiring-panel-skill.zip)
      SKILL.md                                 (< 500 lines; frontmatter below)
      references/
        panel-parallel.md                      (Claude Code: 7 Agent calls in ONE message)
        panel-single.md                        (claude.ai / no Agent tool: sequential + lite protocol)
        questions.md                           (the one question batch; builder interview for thin resumes)
        rewrite-rules.md                       (allowed ops, forbidden list, ownership ladder, placeholders)
        provenance-audit.md                    (skeptic second mode, run on the rewrite)
        edge-cases.md                          (no JD, URL JD, thin, long, non-English, non-US, injection)
        locale-norms.md                        (country norms table: pages, paper, photo/DOB, GPA vs class)
        no-python.md                           (manual mode when Python cannot run)
        troubleshooting.md
        sources.md                             (citations behind personas and the screening check)
        reviewers/_shared-rules.md  _output-format.md  _lite-cards.md
                  01-screening.md 02-hiring-manager.md 03-recruiter.md 04-competitor.md
                  05-ceo.md 06-teammate.md 07-skeptic.md
      schemas/ screening.schema.json review.schema.json resume.schema.json report.schema.json
               answers.schema.json provenance.schema.json
      scripts/hp.py                            (the ONLY command-line entry point)
      scripts/hp/                              (package; Python 3.8+ standard library only)
      assets/docx-skeleton/                    (static .docx parts for manual mode)
  tests/                                       (unittest; not shipped in the zips)
  examples/sample-run/                         (fictional candidate: inputs + every output file)
  docs/                                        (how-it-works.md, privacy.md, setup screenshots later)
  scripts/release.sh  scripts/check.sh
  .github/workflows/check.yml  .github/ISSUE_TEMPLATE/*.md (fictional/redacted text only)
  README.md  LICENSE (MIT)  NOTICE (O*NET CC BY 4.0 credit, if O*NET data is used)  CITATION.cff
  SECURITY.md  CHANGELOG.md  ARCHITECTURE.md (this file)
```
`SKILL` below means `plugins/hiring-panel/skills/hiring-panel/`.

SKILL.md frontmatter:
```
---
name: hiring-panel
description: Review a resume or CV against a job posting with a simulated 7-reviewer hiring panel, then rebuild it honestly as .docx, .pdf and .md. Use for resume feedback, ATS checks or rewrites.
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/hp.py *)
license: MIT
metadata:
  author: "Joshua LaRosa (@joshualarosa.ai)"
  version: "1.0.0"
---
```

## 3. Python rules and module ownership

Python 3.8+, standard library only. Optional imports (pdfplumber, pypdf) only inside
`try/except ImportError`. No 3.9+ features: no `str.removeprefix`, no `functools.cache`, no
`list[str]`/`dict[..]`/`X | Y` in runtime-evaluated annotations, no `match`, no `zip(strict=)`,
no parenthesized context managers. hp.py finds its own folder via `__file__` and inserts it at
sys.path[0]; never assume the cwd; never run with `-I`. Never rely on `${CLAUDE_SKILL_DIR}` being
expanded by a shell. No network calls anywhere (tests enforce it). Deterministic output: same inputs
give byte-identical JSON (timestamps only in state.json).

```
scripts/hp.py                     CLI                                                  (integration)
scripts/hp/__init__.py            __version__ = "1.0.0"                                (exists)
scripts/hp/util.py                shared helpers (EXISTS; read it. Others may APPEND functions, never
                                  change existing ones): write_json, read_json, write_text,
                                  sha256_file, norm_text, norm_for_match, round5, slugify,
                                  today_iso (HP_AS_OF pin), now_stamp (HP_NOW pin), mask_contact,
                                  EMAIL_RE, PHONE_US_RE, PHONE_INTL_RE, LINKEDIN_RE, GITHUB_RE, URL_RE
scripts/hp/run.py                 run folder paths + state.json                       (integration)
scripts/hp/ingest/                file -> Document                                    (builder: ingest)
scripts/hp/screen/                Document + JD -> screening.json, brief.json         (builder: screen)
scripts/hp/data/                  dictionaries + locale_norms.json                    (builder: lexicon)
scripts/hp/panel/ledger.py        resume.md + screening JD blocks -> ledger.json      (builder: panel)
scripts/hp/panel/synth.py         reviews + screening.json -> synthesis.json          (builder: panel)
scripts/hp/rewrite/truth.py       ledger + answers + resume.json -> truth.json        (builder: output)
scripts/hp/rewrite/provenance.py  provenance gate                                     (builder: output)
scripts/hp/render/                resume.json / report.json -> files; doctor          (builder: output)
scripts/hp/gate.py                release gate on generated files                     (integration)
scripts/hp/report_build.py        run artifacts -> report.json                        (integration)
```

## 4. The run folder

```
<BASE>/                                          BASE default ./hiring-panel-runs ; contains .gitignore "*"
  <now_stamp>-<company-slug>-<role-slug>/        e.g. 2026-10-20-1430-northwind-foods-marketing-intern
    First_Last_Resume.docx  First_Last_Resume.pdf  First_Last_Resume.md        (deliverables)
    Hiring_Panel_Report.pdf  Hiring_Panel_Report.md  Hiring_Panel_Report.html
    work/
      state.json                                   see 4.1
      inputs/original.<ext>                        byte-identical copy of the upload (if a file was given)
      inputs/transcript.txt                        only when Claude transcribed an image-only file
      inputs/resume.md                             canonical resume text, verbatim (5.3)
      inputs/ats_view.txt                          what a parser reads (5.3)
      inputs/jd.md                                 job posting text ("" in general review)
      inputs/ledger.json                           R#/J# lines (section 7)
      inputs/terms.json                            optional Claude-extracted JD terms (verbatim quotes)
      screening/before/screening.json  screening.md  brief.json
      screening/after/docx/{screening.json, screening.md, ats_view.txt}
      screening/after/pdf/{...}                    skipped when no PDF
      reviews/<reviewer_id>.json                   7 files
      merges.json                                  optional
      synthesis.json
      answers.json
      rewrite/resume.json  truth.json  provenance.json
      gate.json
      report.json
    recheck/                                       optional opt-in re-read (Claude Code): a full run layout
                                                   built from the generated .docx with the same JD
```
On claude.ai, BASE = `/mnt/user-data/outputs/hiring-panel-runs` when `/mnt/user-data/outputs` exists
(detected by hp.py, overridable with --out), and `report --copy-to /mnt/user-data/outputs` copies the 6
deliverables to the top so they appear as download cards. If BASE is inside a git work tree
(`git rev-parse` succeeds; do it with subprocess and a 3 s timeout, ignore failures), init returns
`git_warning: true` (the .gitignore still protects it).
First_Last: resume.json basics.name ASCII-folded, spaces -> "_"; fallback "My_Resume".

### 4.1 state.json
```
{"schema_version":"1.0","hp_version":"1.0.0","created":ISO,"as_of":"YYYY-MM-DD",
 "candidate_stage":"student|early_career|experienced","role_level":"intern|entry|mid|senior|unknown",
 "locale":"en-US","language":"en","role":str,"company":str|null,
 "jd_source":"pasted|file|url:<url>|none","general_review":bool,
 "mode":null|"parallel"|"sequential"|"lite"|"manual",
 "flags":{"thin":bool,"long":bool,"needs_transcription":bool,"non_english":bool},
 "ledger_overrides":[{"id":"J3","from":"other","to":"must"}],
 "steps":{"init":ISO,"screen":ISO,"synthesize":ISO,"report_panel":ISO,"answers":ISO,"truth":ISO,
          "provenance":ISO,"render":ISO,"gate":ISO,"report_final":ISO}}
```
`hp.py status RUN` reads it and says what to run next, so a run cut off by a usage limit can resume.

## 5. Ingest (builder: ingest) `hp.ingest`

### 5.1 API
```python
from hp.ingest import ingest_file, ingest_text, doc_to_resume_md, write_ats_view
doc = ingest_file(path)              # never raises on bad content; problems go in doc["errors"]/signals
doc = ingest_text(text)              # pasted or transcribed text (format "txt")
md  = doc_to_resume_md(doc)          # 5.3
write_ats_view(doc, path)            # 5.3
```
### 5.2 Document dict (JSON-serializable, fixed keys)
```
{
 "format": "docx|pdf|txt|md|rtf|doc|pages|odt|image|unknown",
 "sha256": str|null, "bytes": int, "pages": int|null, "producer": str|null, "creator": str|null,
 "method": "docx-xml|pdfplumber|pypdf|pdfkit|builtin-pdf|text|rtf|none",
 "lines": [ {"text": str, "style": str|null, "list": bool, "bold": bool,
             "where": "body|table|textbox"} ],                # body order, normalized text
 "header_footer": [ {"where": "header|footer", "text": str} ],
 "text_chars": int, "words": int,
 "signals": {
   "encrypted": bool, "text_layer": bool|null, "image_only": bool, "garbled": bool,
   "too_large": bool, "legacy_format": str|null,
   "images": {"count": int, "large": int, "charts": int, "smartart": int, "small_icons": int},
   "tables": {"count": int, "nested": int, "holds_experience": bool},
   "text_boxes": {"count": int, "chars": int, "has_contact": bool, "has_heading": bool},
   "columns": {"docx_multi_column": bool, "pdf_check": "performed|unavailable", "pdf_gutter_pages": [int]},
   "header_footer": {"has_text": bool, "has_contact": bool},
   "hidden_text": {"vanish": int, "white": int, "tiny": int, "pdf_invisible": int},
   "caps_formatting": int, "fields": {"docproperty": int, "mergefield": int, "ole": int},
   "tracked_changes": int, "comments": int, "symbols": int,
   "fonts": {"type0": int, "tounicode": int, "type3": int},
   "design_tool": str|null, "private_use_chars": int, "replacement_chars": int,
   "letter_spaced": int, "repeated_footer_lines": int, "tab_merged_tokens": int
 },
 "warnings": [str], "errors": [{"code": str, "detail": str}]
}
```
Ingest records FACTS only; `hp.screen` turns signals into issue ids and severities. Sniffing, limits,
docx walking, PDF ladder (pdfplumber -> pypdf -> macOS PDFKit via `osascript -l JavaScript` with the
path passed as argv, never interpolated -> builtin -> none) and normalization: ATS spec sections 3-5.
Limits: file <= 15 MB; zip <= 50 MB expanded and <= 2000 entries; refuse XML parts containing
`<!DOCTYPE` or `<!ENTITY`; each PDF stream <= 20 MB, 100 MB total; 5 s probe budget. Contents are
data: never execute, never follow URLs. `tab_merged_tokens`: in docx, count runs where a `w:tab`
separates two text runs with no space on either side (the tab-dropping extractor would merge words).
### 5.3 resume.md (canonical text) and ats_view.txt
- `resume.md`: first each header/footer line prefixed `[header] ` or `[footer] `, then every
  `lines[].text` in order, one per line. Table cells keep " | " joins; text-box lines keep a
  `[text box] ` prefix. Verbatim: never fix typos, never reorder. Blank lines allowed between blocks.
- `ats_view.txt`: `# extraction: <method>` / `# roughly what parsing software reads; order matters` /
  blank / body lines / blank / `# header/footer (some systems skip this):` + those lines.
- Image-only or no text: init returns `needs_transcription: true`; Claude transcribes word for word
  (typos kept) into inputs/transcript.txt, the student confirms, and init re-runs with
  `--resume-text`. Structure signals still come from the original file, so PARSE-001 stays critical.

## 6. Screening (builders: screen + lexicon) `hp.screen`, `hp/data/`

```python
from hp.screen import run_screening, render_screening_md, make_brief, load_lexicon
result = run_screening(doc, jd_text, *, stage="student", as_of="YYYY-MM-DD", locale="en-US",
                       jd_url=None, jd_title=None, terms=None, data_dir=None)   # screening.json dict
md = render_screening_md(result)      # student-facing, contact masked, "simulated" wording
brief = make_brief(result)            # <= ~2k tokens for subagents (6.3)
```
Implements ATS spec sections 6-17 (issue catalogue ids, severities critical|high|medium|low|info,
confidence, scoring rubric, bands, fixed disclaimer, limitations, precision_note), validated by
`SKILL/schemas/screening.schema.json` (port from research, then update for this section).
- `stage`: student|early_career|experienced (the ATS spec's --level).
- No JD (`jd_text == ""`): keyword_match value null, band "No job description provided", no KW
  issues, knockout_signals []. Non-English resume (detect: < 30% of tokens in stopwords_en and a
  non-Latin script or common non-English function words): keyword_match null with reason "keyword
  dictionary is English-only"; parse checks still run.
- Locale: contact/phone/location regexes accept non-US formats; no US-only advice when locale != en-US.
- `terms`: `[{term, aliases, importance: required|preferred|unspecified, jd_quote}]`, accepted only if
  jd_quote appears in the JD (whitespace-normalized) and contains the term; rejects logged in
  `extraction.warnings`.
- NEW: `tab_merged_tokens > 0` -> issue PARSE-023 medium "Words may merge when tabs are dropped".
### 6.1 JD blocks (the ONE job-posting classifier)
`result["inputs"]["job_description"]["blocks"]` = `[{"kind": "required|preferred|responsibility|
boilerplate|unspecified", "heading": str|null, "lines": [str]}]`. The blocks PARTITION every non-empty
line of jd.md in order (lossless; nothing dropped, headings included as the block's first line).
The ledger numbers J# from these lines.
### 6.2 Keyword truth
`result["keywords"]` is the only keyword source. The report prints
"Required terms: X of Y found (Z only in your skills list)" from it. Nobody recomputes coverage.
### 6.3 brief.json
`{"scores": {overall, parse_safety, keyword_match, content_signals: {value, band}}, "precision_note",
  "disclaimer", "top_issues": [<= 12 {id, severity, title, evidence (<= 160 chars)}],
  "keywords": [<= 30 {term, importance, found, match_type, evidence_level, resume_wording}],
  "coverage": {...}, "knockouts": [...], "job_title", "platform_guess", "language"}`
### 6.4 Data (builder: lexicon) in `hp/data/` (lines starting with # are comments in .txt files)
- `skills.json`: `{"version": "1.0.0", "entries": [{id, canonical, kind: hard|tool|cert|domain|soft|title,
  aliases[], acronyms[], case_sensitive, ambiguous, context[], implies[]}]}`. Broad coverage across the
  fields college students apply to (software/data, business/finance/accounting, marketing/comms/social,
  sales, operations/supply chain, HR, healthcare/nursing/public health, education, engineering
  (mech/civil/electrical/chemical), science/lab, design/UX/creative, legal/policy, hospitality/retail,
  nonprofit/government) plus common job titles (kind title).
- `headings.json`: `{"resume": {"<section>": [synonyms]}, "jd": {"required": [...], "preferred": [...],
  "responsibility": [...], "boilerplate": [...]}}` (sections per ATS spec 7).
- `action_verbs.txt` (one base verb per line; irregulars as `base|past`, e.g. `lead|led`),
  `weak_openers.txt`, `buzzwords.txt`, `stopwords_en.txt`, `jd_stopwords.txt`,
  `us_states.json` (`{"TX": "Texas"}`), `countries.txt`, `locale_norms.json` (see 6.5), `VERSION`.
### 6.5 locale_norms.json
`{"en-US": {"paper": "letter", "pages_student": 1, "pages_experienced": 2, "word": "resume",
  "photo": "omit", "dob": "omit", "gpa": "optional_3.0_plus", "notes": [...]}, "en-CA": ..., "en-GB":
  {"paper": "a4", "word": "CV", "gpa": "degree_classification", ...}, "en-IE", "en-AU", "en-NZ", "en-IN",
  "de-DE"/"de-AT"/"de-CH" ("photo": "customary", "dob": "customary"), "fr-FR", "es-ES", "default"}`.
Used by the recruiter persona (via references/locale-norms.md, written from the same table), the
renderer (paper size, page target) and screening (no US-only advice outside en-US).

## 7. Ledger (builder: panel) `hp.panel.ledger`

```python
from hp.panel.ledger import build_ledger, apply_overrides
ledger = build_ledger(resume_md_text, jd_blocks, target={"role_title","role_level","company","locale"})
ledger, log = apply_overrides(ledger, {"J3": "must"})   # kind fields only; unknown id -> ValueError
```
```
{"schema_version":"1.0",
 "resume_lines":[{"id":"R1","section":"header_footer|contact|summary|education|experience|projects|skills|leadership|other","text":str}],
 "jd_items":[{"id":"J1","kind":"must|nice|responsibility|company|logistics|other","block":int,"text":str}],
 "target":{"role_title":str,"role_level":str,"company":str|null,"locale":str,"general_review":bool}}
```
R ids number the NON-EMPTY lines of resume.md in order (including `[header]`/`[footer]` lines).
J ids number the non-empty lines of the JD blocks in order. Kind map: required->must,
preferred->nice, responsibility->responsibility, boilerplate->company or logistics (logistics if the
line is about location, schedule, pay, benefits, authorization, travel, EEO), unspecified->other.

## 8. Reviews (builder: panel)

| id | display name | Reel/report order | sequential order |
|---|---|---|---|
| screening | Automated Screening Check | 1 | 1 |
| hiring_manager | Hiring Manager | 2 | 3 |
| recruiter | Recruiter | 3 | 2 |
| competitor | Competing Applicant | 4 | 6 |
| ceo | CEO | 5 | 5 |
| teammate | Future Teammate | 6 | 4 |
| skeptic | Skeptic | 7 | 7 |

Anchors: `R#` (resume line), `J#` (JD line), `A:<ISSUE-ID>` (an issue id in screening.json, e.g.
`A:PARSE-006`), `Q#` (an answer; only in the provenance audit). Pattern:
`^([RJ][0-9]+|A:[A-Z]+-[0-9]{3}b?|Q[0-9]+)$`. R/J evidence needs a verbatim quote of that line;
A: evidence needs the id to exist in screening.json (quote optional).
Every review adds two shared fields: `advance: "yes"|"no"|"unsure"` answering "From your seat, should
this resume move to the next step for this job?" and `one_line_take` (<= 20 words, plain language).
`strengths` may be empty (minItems 0; thin resumes must not get invented praise).
The screening reviewer reads `work/screening/before/brief.json` and `work/inputs/ats_view.txt`, copies
keyword status from the brief (never recomputes coverage; drop must_have_coverage_pct), and bases its
verdict on the script's bands.
Locale: the recruiter applies `references/locale-norms.md` (photo/DOB not a red flag where customary;
GPA vs degree class). Never infer or mention protected traits; never advise changing a name or hiding
age or identity markers.
General review (no JD): KEYWORD_GAP and REQUIREMENT_UNPROVEN are not allowed; hiring manager and
competitor judge against the role title with the caveat "no posting provided".
Subagents read `_shared-rules.md`, their persona file and `_output-format.md` (a compact contract with
one example, a few KB; the full schema is for the validator only). They write
`work/reviews/<id>.json` and reply with the single word `DONE`.
Lite mode (claude.ai Free or "quick run"): `_lite-cards.md` holds 7 persona cards of <= 400 words each;
before each reviewer re-read only resume.md and jd.md.

## 9. Synthesis (builder: panel) `hp.panel.synth`

```python
from hp.panel.synth import validate_review, synthesize
ok, errors = validate_review(run_dir, review_path)
result = synthesize(run_dir, mode="parallel|sequential|lite", merges_path=None)  # writes work/synthesis.json
```
synth.py is the ONLY ranker. Algorithm: research reviewers spec "SYNTHESIS ALGORITHM" plus:
- One severity scale: critical|major|moderate|minor. Screening issues map critical->critical,
  high->major, medium->moderate, low->minor, info->notes (shown, never ranked).
- Screening issues at medium or above are read in AUTOMATICALLY as screening-lens findings with
  `A:<id>` anchors and the script's confidence (category map PARSE-*->PARSE_FORMAT,
  CONTACT-*->CONTACT_HEADER, KW-001/003/005->KEYWORD_GAP (attach J anchors by matching each term's
  jd_quote to ledger jd_items), KW-002->SKILL_UNSUPPORTED, KW-004->TITLE_MISMATCH, SECT-001->
  EDUCATION_PRESENTATION, SECT-*->LAYOUT_SKIM, DATE-*->TRAJECTORY_GAP or LAYOUT_SKIM,
  CONTENT-001->METRIC_MISSING, CONTENT-002->VAGUE_LANGUAGE, CONTENT-003/004/009->LENGTH_DENSITY,
  other CONTENT->TYPO_GRAMMAR). They bypass the lens cap. PARSE-016 (hidden text) is pinned.
- panel_vote counts `advance == "yes"` (not lens verdicts).
- CONS lambda: parallel 0.5, sequential 0.3, lite 0.3.
Output (fixed keys):
```
{"schema_version":"1.0","mode","panel_size","missing_reviewers":[...],
 "reviewers":[{"id","name","verdict","advance","confidence","one_line_take","decision_question"}],  (report order)
 "panel_vote":{"advance":int,"unsure":int,"total":int},
 "verdict_split":{...},
 "closest_to_reject":{"reviewer","verdict","issue_id"|null,"reason"}|null,   (section 17.4; null for an empty panel)
 "issues":[{"id":"I1","rank":1,"title","family","categories":[...],"severity","priority":float,
            "reviewers":[ids],"reviewer_count":int,"from_script":bool,"stage",
            "lane":"fixed_by_rewrite|needs_your_input|real_gap",
            "evidence":[{"anchor","quote","reviewer"}],"detail",
            "fixes":[{"fix_type","suggestion","candidate_question","reviewer"}],
            "jd_anchors":[...],"is_pattern":bool,"instances":[...]}],
 "notes":[{"id","title"}],                          (screening info items, unranked)
 "top3":["I1","I2","I3"], "pinned_integrity":["I7"],
 "conflicts":[...], "strengths":[{"id":"S1","title","reviewers":[...],"anchors":[...],"underused":bool}],
 "questions_for_candidate":[{"id":"RQ1","question","why","issue_ids":[...],"related_anchors":[...]}],
 "interview_prep":[{"question","from":"hiring_manager|skeptic","anchor"}],          (<= 6)
 "validation_log":[...]}
```
Issue ids I1.. follow rank order. questions_for_candidate (<= 6) are raw material; Claude builds the
final batch per references/questions.md and stores it in answers.json with Q# ids.

## 10. Answers, rewrite, truth, provenance (builder: output)

answers.json (ONE batch of at most 7 questions; builder interview for thin resumes: at most 8):
```
{"schema_version":"1.0","mode":"interactive|skipped",
 "answers":[{"id":"Q1","kind":"integrity|keywords|number|reviewer|builder","question":str,
             "answer":str|null,"status":"answered|declined|skipped",
             "items":[{"term":str,"answer":"yes|some|no","detail":str}]|null}]}
```
Batch order: integrity confirmations, then ONE combined yes/some/no list of missing must-have
keywords (kind keywords, with items), then number placeholders, then reviewer questions. Evidence from
answers uses ref `Q1`; for keyword items only `yes`/`some` items count as evidence (term + detail).
resume.json: research resume.schema.json with: evidence `{src:"orig"|"user", ref:"R12"|"R12-R14"|"Q2",
quote}` (the JD is NEVER evidence); `meta.addressed: [{"issue_id","status":"fixed|needs_you|gap",
"note"<=140}]`; `meta.cuts: [{"ref":"R18","reason"}]` for every source line dropped; placeholders
`{{p1}}` + required `textIfUnknown`; `meta.layout` classic|inline; `meta.locale`, `meta.pageSize`.
truth.py: `check_truth(ledger, answers, resume) -> dict` -> work/rewrite/truth.json
`{"passed","errors":[{"code","where","detail"}],"warnings":[{"code","bullet_id","detail"}],
  "stats":{"bullets","bullets_with_evidence","placeholders_open","numbers_from_answers"}}`
Error codes: ENTITY_NOT_IN_SOURCE, DATE_NOT_IN_SOURCE, DATE_PRECISION_ADDED, NUMBER_NOT_IN_SOURCE,
TERM_NOT_IN_SOURCE, SKILL_NOT_IN_SOURCE, OWNERSHIP_UPGRADED, HEDGE_REMOVED, EVIDENCE_QUOTE_NOT_FOUND,
NO_EVIDENCE, PLACEHOLDER_LEFT, CONTACT_CHANGED, JD_AS_EVIDENCE, BAD_REF. Warnings: NEW_WORDING,
HEADLINE_NEW_WORD.
provenance.json (skeptic provenance audit; subagent in Claude Code, `mode: "self"` otherwise):
```
{"schema_version":"1.0","auditor":"skeptic-provenance","mode":"subagent|self",
 "items":[{"bullet_id","audited_text","verdict":"ok|soften|remove","problem":str|null,"suggested_text":str|null}]}
```
`check_provenance(resume, provenance, truth) -> {"passed","unresolved":[ids],"missing":[ids]}`:
every NEW_WORDING bullet must appear in items; every soften/remove item must now differ from
`audited_text` (or be removed).

## 11. Rendering (builder: output) `hp.render`

```python
from hp.render import render_resume, render_report, doctor
info = render_resume(resume, out_dir, formats=("docx","pdf","md"), pdf_engine="auto", layout=None, draft=False)
info = render_report(report, out_dir, pdf_engine="auto")      # Hiring_Panel_Report.{pdf,md,html}
env = doctor()
```
Port the research render.py (split into modules). PDF ladder: Chrome/Edge/Brave -> soffice -> builtin
-> skip (no reportlab route). resume.json is the source of truth; .md is an output.
Word layout fix (critic C-P1): never a bare `w:tab` between two text runs; a space precedes every tab
so tab-dropping extractors still see a word boundary. Default layout "classic" (right-aligned dates
via tab stop); "inline" puts dates after " | ". Paper size and page target from meta.locale /
locale_norms. No branding or app.xml in the resume; the report footer says
"Hiring Panel v<version> · free and open source · not affiliated with Anthropic or any ATS vendor".
Return dicts: `files`, `pdfEngine`, `pages`, `warnings`, `overflow`, `pdfSkipped`, `layout`.

## 12. report.json (integration builds it; output renders it)

Built ONLY by `hp.report_build.build_report(run_dir)`; the model never writes report numbers.
Works at two stages: `panel` (after synthesis, before the rewrite; delivered early so a usage limit
cannot lose the feedback) and `final`. Contact details are masked everywhere in the report.
```
{"schema_version":"1.0","stage":"panel|final","hp_version","candidate":str,"target":{"role","company"},
 "date":"YYYY-MM-DD","mode":"parallel|sequential|lite|manual","general_review":bool,
 "mode_note":str,                                 (sequential/lite: approximate-independence disclosure)
 "verdict_strip":{"vote_label":"2 of 7 would move you forward","screening_band":str,"mode_label":str,
                  "strong_line":str},                 ("" unless strong_resume; fixed template, section 17.4)
 "strong_resume":bool, "closest_to_reject":{"reviewer","name","verdict","issue_id","severity","reason"}|null,
 "first_impression":str|null,                     (section 17.5)
 "pinned_integrity":[{"issue_id","title","fix"}],                                   ("Fix before you send")
 "weaknesses":[{"rank","issue_id","title","severity","flagged_by":[ids],"flagged_count","from_script":bool,
                "why","evidence_quote","status":"fixed|needs_you|gap|open","fix"}],  (all; PDF shows top 5)
 "changes":{"bullets_rewritten","reordered","numbers_from_you","cut":[{"ref","text","reason"}]}|null,
 "needs_you":[{"where","ask"}], "real_gaps":[{"title","honest_route"}],
 "panel":[{"id","name","lens","verdict","advance","take"}],                            (7 rows)
 "panel_after":null|{"vote_label","rows":[...],"note":"Re-read by fresh reviewers; directional."},
 "screening":{"label":"Simulated screening check","method":"Overall = 40% file readability + 40% job-keyword match + 20% content signals, rounded to steps of 5. Weights are our judgment, not calibrated to hiring outcomes.",
              "before":{"overall","band","machine_readability":{"value","band"},"keyword_match":{"value","band"},
                        "content_signals":{"value","band"},"required":{"found","total","listed_only"}},
              "after":{same}|null,"after_source":"docx|pdf"|null,"precision_note","disclaimer"},
 "disagreements":[{"claim","sides":[{"reviewer","view","quote"}],"which_matters"}],  (<= 2)
 "keyword_gaps":[{"term","status":"gap|listed_only|added_with_evidence","note"}],    (<= 6)
 "strengths":[{"title","flagged_by":[ids],"underused":bool}],                        (<= 4)
 "interview_prep":[{"question","from"}],                                              (<= 6)
 "knockouts":[{"type","jd_quote","advice"}],                                          (<= 4)
 "truth_check":{"ran":"script|model_only|not_run","passed":bool|null,"invented_facts":int|null,
                "bullets_traced":int,"bullets_total":int,"provenance":"subagent|self|unresolved|not_run"},
 "limitations":[str], "next_steps":[str],                                              (templated, <= 4)
 "files":{"resume_docx","resume_pdf","resume_md","report_pdf","report_md","report_html"}}
```
Display order (critic C12), top to bottom: 1 header + verdict strip (vote, screening band, mode);
2 Fix before you send; 3 Biggest weaknesses, most serious first (top 5); 4 What changed / needs you /
real gaps; 5 The panel (7 rows: name, lens, verdict chip, advance, take); 6 Where the panel disagreed;
7 Keyword gaps to close honestly; 8 What's already working; 9 Interview prep; 10 Mode and limitations.
The one-page PDF holds 1-5; .md and .html hold everything. One number only: the screening Overall
(multiple of 5), always next to "Simulated screening check", its band, machine readability band and the
exact keyword counts. Never "ATS score", never per-reviewer numbers, never probabilities, never
"interview-ready" style headlines. "0 invented facts" only when truth_check.ran == "script" and passed.
Status: resume.meta.addressed when present, else lane (fixed_by_rewrite->fixed, needs_your_input->
needs_you unless every linked question was answered -> fixed, real_gap->gap); stage panel -> "open".
Report text states only facts from the inputs or cited constants (no outside claims about courses,
certifications, durations or costs). next_steps are fixed templates chosen by rules.

## 13. CLI (integration) `python3 <SKILL_DIR>/scripts/hp.py <command>`

Every command prints exactly ONE JSON object to stdout and nothing else there; hints go to stderr.
Exit codes: 0 ok; 1 a check failed (truth errors, invalid review, gate failed); 2 bad arguments or
unreadable input; 3 resume longer than its page target; 4 PDF skipped (docx + md still written).
```
doctor        -> {"python","platform","surface":"claude_code|claude_ai|unknown","outputs_dir","pdf_engines",
                  "pdf_text_backends","git_repo":bool}
init  (--resume PATH [--resume-text PATH] | --resume-text PATH)  (--jd PATH | --jd - | --no-jd)
      --role TEXT [--company TEXT] [--jd-source pasted|file|url:<URL>]
      [--stage student|early_career|experienced] [--role-level intern|entry|mid|senior|unknown]
      [--locale en-US] [--out BASE] [--as-of YYYY-MM-DD]
      ingest + screen(before) + brief + ledger + state.json in one call ->
      {"run","resume":{"format","method","lines","words","needs_transcription","warnings"},
       "jd":{"chars","too_thin":bool,"general_review":bool},"flags":{thin,long,non_english},
       "screening":{"overall","band","machine_readability","keyword_match","content_signals",
                    "required":{found,total,listed_only},"top_issues":[{id,severity,title}]},
       "ledger":{"resume_lines","jd_items","kinds":{must,nice,...}},"git_warning":bool,"next":str}
ledger RUN --override J3=must [J4=nice ...]     kinds only, logged in state.json
screen RUN [--terms PATH]                       re-run the before screening (+ brief) with Claude terms
validate RUN PATH                               validate one review file (exit 1 + errors if invalid)
synthesize RUN --mode parallel|sequential|lite [--merges PATH]
      -> {"panel_vote","reviewers":[{id,verdict,advance,one_line_take}],"top":[{id,title,severity,flagged_by}],
          "questions":[...],"dropped":int}
truth RUN                                       -> truth summary; exit 1 on errors
render RUN [--pdf-engine auto|chrome|soffice|builtin] [--layout classic|inline] [--draft]
      refuses unless truth passed and the provenance gate passed; renders the resume, then runs the
      gate (screening after on .docx and .pdf, PDF word recovery >= 98% vs resume.md text, no tab-merged
      tokens, parse_safety >= 90 and no critical/high PARSE issue); if the gate fails on merged tokens
      or reading order with layout classic, it re-renders inline once and re-gates. Writes gate.json.
report RUN [--copy-to DIR]                      builds report.json (stage panel or final) + renders it
status RUN                                      steps done, next command
recheck RUN                                     opt-in: builds RUN/recheck/ from the generated .docx
```

## 14. SKILL.md flow (both surfaces)

0. Setup: SKILL_DIR = the folder containing SKILL.md (Claude Code: `${CLAUDE_SKILL_DIR}`; elsewhere
   the directory you read SKILL.md from; never let a shell expand an unset variable). macOS: check
   `xcode-select -p` before python3; Windows: `py -3`. Run doctor. Pick mode: parallel (Agent tool
   available), sequential (claude.ai), lite (sequential with lite cards when the student is on Free or
   asks for a quick run), manual (no Python; references/no-python.md).
1. Intake: resume file (PDF/DOCX/TXT or pasted), job posting (paste preferred; URL fetched once and
   accepted only if >= 300 chars with requirement/responsibility headings), role, company, stage,
   locale (inferred, confirmed in one line). One-line privacy note. No JD after one ask -> general
   review. Never invent a posting. One JD per run.
2. init. needs_transcription -> transcribe verbatim, confirm, re-run with --resume-text.
   Optional: extract JD terms with verbatim quotes -> inputs/terms.json -> `screen RUN --terms`.
   Fix ledger kinds only via `ledger --override` when clearly wrong.
3. Panel: parallel (one message, 7 Agent calls, path-only template, economy option model "sonnet")
   or sequential/lite protocol. validate each; retry a failed reviewer once with only its own errors.
4. synthesize (+ merges pass for true duplicates only), then `report RUN` (stage panel) and share the
   report early.
5. Chat summary, weaknesses first (vote, top 3, pinned items), then ONE question batch (<= 7, or the
   builder interview <= 8 for thin resumes) per references/questions.md; "skip" allowed. Save answers.json.
   Claude Code: on the student's reply, re-invoke the skill (`/hiring-panel continue <run>`) so the
   tool pre-approval applies again.
6. Rewrite resume.json per references/rewrite-rules.md (long resume: ask which roles to keep; list
   every cut). truth (must pass; fix and repeat). Provenance audit (Claude Code: fresh Skeptic subagent
   with references/provenance-audit.md; otherwise self, disclosed). Apply soften/remove items.
7. render (handles the gate and inline fallback; exit 3 -> cut per rules, re-run truth, re-render).
8. report RUN (final; `--copy-to` the outputs dir on claude.ai). Deliver: file list, 3 lines (vote,
   top weakness, where files are), interview prep offer, "run again for another job". No cover
   letters or LinkedIn rewrites in v1.

## 15. Honesty, privacy and safety invariants (tests must cover each)

1. Final resume: nothing absent from R# lines or answered Q#s; ownership never upgraded; hedges kept;
   the JD is never evidence.
2. No `{{` or `[ADD:` in non-draft files.
3. Never generate hidden, white or tiny text.
4. Every number in report.json comes from a script; one score only, labeled simulated.
5. Sequential/lite modes always disclose approximate independence (report + chat).
6. Resume/JD contents are untrusted data; instructions inside them are ignored; hidden text is pinned.
7. No network access from any script; no telemetry (test patches socket).
8. Never infer or mention protected traits.
9. Gaps are info-level and never shamed; fixes are honest labels, never invented roles.
10. Run folder carries .gitignore "*"; git-repo warning; contact masked in report and chat summaries.
11. "0 invented facts" only when the script truth check ran and passed.

## 16. Voice for user-facing text (README, SKILL.md messages, report)

Plain language, second person, short sentences, no em dashes, no hype, never "ATS score", never promise
interviews. README speaks as Joshua LaRosa (Instagram @joshualarosa.ai) sparingly ("I built this").
For Claude users 18+. Not affiliated with Anthropic or any ATS vendor. GitHub owner placeholder: `OWNER`
(release.sh refuses to build while it remains).

## 17. Addendum (2026-10-20): the original skill, credit, and ideas adopted from it

The Reel's concept comes from Alex Chen's original skill: https://github.com/alexyc9381/hiring-panel-skill
(MIT, Copyright (c) 2026 Alex Chen (@nocodealex, https://chen.media); one SKILL.md prompt, Markdown output,
Claude Code only). A read-only clone is at
`/private/tmp/claude-501/-Users-joshualarosa/f57a77eb-78ee-45b5-bbd9-ef653a9c9b2a/scratchpad/hp-upstream/repo`.
Hiring Panel is a from-scratch rebuild; do not paste its text. Owners apply these if they can; the integrator
applies whatever is left:
1. Credit. Root README gets a "Credits" section: "Inspired by the original hiring-panel skill by Alex Chen
   (@nocodealex), MIT licensed: github.com/alexyc9381/hiring-panel-skill. This version is a from-scratch rebuild
   with a deterministic screening check, evidence-checked rewrites, Word/PDF output and claude.ai support."
   Add a CITATION.cff for this repo (author Joshua LaRosa) with a `references:` entry for Alex's work.
   If any of his text is ever reused, NOTICE must carry his MIT copyright and permission notice.
2. SKILL.md frontmatter: add `license: MIT` and `metadata: {author: "Joshua LaRosa (@joshualarosa.ai)",
   version: "1.0.0"}`. (argument-hint was tried, then dropped for v1.0.0: Claude Code-only, claude.ai acceptance unverified.) Previously: add argument-hint only if
   `claude plugin validate` accepts it, and record it as a risk for the claude.ai upload test.
3. One-line use in Claude Code: `/hiring-panel ~/Documents/resume.pdf Marketing intern at Northwind` (the
   first argument is the resume path or text; the rest is the job posting, a link, or a role). SKILL.md reads
   the arguments; if there is no role or posting at all, it asks ONE question first.
4. Strong-resume honesty: synthesis.json adds `closest_to_reject: {"reviewer", "verdict", "issue_id"|null,
   "reason"}` (the reviewer with the lowest verdict, ties broken by report order, and its top-ranked issue).
   When the panel vote is >= 5 of 7 and there is no critical or major issue, the chat summary and the report's
   verdict strip say plainly that the resume is strong and name who came closest to rejecting it and why it
   still held. Never flatter otherwise.
5. First impression: report.json adds `first_impression` (the recruiter's 7-second takeaway from its
   lens_data, <= 30 words) shown right under the verdict strip ("What a recruiter sees in 7 seconds").
6. README install option for Claude Code users: paste
   `https://github.com/OWNER/hiring-panel  Install this skill, then confirm /hiring-panel works.`
   into Claude Code (alongside the /plugin commands).
7. Name collision: Alex's skill is also named `hiring-panel`. README troubleshooting tells users who
   installed both to remove one, since the command names collide.

## 18. Changes after the live tests (2026-10-20)

Two live runs (Claude Code parallel; single-chat lite) produced the findings fixed in v1.0.0. Contract changes:
- Reviewers read only `_shared-rules.md`, their persona, `_output-format.md` and `work/inputs/ledger.json`
  (screening also `brief.json` and `ats_view.txt`). Lite mode reads only `_lite-cards.md` + `ledger.json`.
  The ledger is written compactly, posting first; J items may be sentence-sized spans of a line (lossless).
  EEO and benefits lines are kind `company`. Ids (R#/J#/A:) appear only in anchor fields; synthesis scrubs
  leftovers from student-facing text.
- synthesis: `panel_vote.no`; issues gain `has_real_gap` and `real_gap_routes`; fixes[0] comes from the lead
  finding; keyword questions use the posting's wording (no degree-field or credential questions when shown).
- report: statuses are verified against the AFTER screening (`improved` added); final keyword gaps come from
  the after screening; real gaps come from `has_real_gap`; `verdict_strip.mixed_line` explains a high
  screening band next to a low vote; legend under the panel table; leftover ids replaced by quotes.
- `status` after the panel stage tells Claude to save answers and go to Step 6 if the student already replied.
- Screening, ingest, truth and render changes from wave 1 are listed in CHANGELOG.md.
