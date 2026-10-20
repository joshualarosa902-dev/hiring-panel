# Troubleshooting

For you (Claude) when a step fails or the student is stuck. Explain the fix to the student
in plain words; never paste a traceback at them. Commands use
`python3 <SKILL_DIR>/scripts/hp.py` as SKILL.md Step 0 describes.

## Exit codes (all commands)

| Code | Meaning | What to do |
|---|---|---|
| 0 | OK | Continue. |
| 1 | A check failed: truth errors, an invalid review, the render gate, or render refused because truth or the provenance audit didn't pass | Read the JSON on stdout. Fix what it names (SKILL.md Steps 3, 6, 7). Never hand-edit outputs to get past a check. |
| 2 | Bad arguments or unreadable input | Re-check the command against SKILL.md's command reference. Check the file path exists and the file opens. |
| 3 | The resume is longer than its page target | Cut per references/rewrite-rules.md, list each cut in `meta.cuts`, run `truth`, then `render` again. |
| 4 | PDF skipped; the .docx and .md were written | Tell the student to open the .docx and save it as PDF. Optionally retry with `--pdf-engine` set to an engine `doctor` listed. |

## Setup problems

| Symptom | Likely cause | Fix |
|---|---|---|
| A command fails with `/scripts/hp.py: No such file or directory` | SKILL_DIR was empty (an unset variable reached the shell) | Redo SKILL.md Step 0.1 and paste the real path. Never use a shell variable for it. |
| `can't open file .../hp.py` | Wrong SKILL_DIR | Run the `find` command from Step 0.1 and use the folder two levels above the `hp.py` it finds. |
| On a Mac, a window asks to install developer tools | `python3` ran without Apple's developer tools | Ask the student to click Cancel. Use manual mode (references/no-python.md). If they want the full version, they can run `xcode-select --install` themselves in Terminal (Apple's free Command Line Tools, a few minutes to download), then start a new run. |
| `xcode-select -p` fails but Homebrew Python exists | No developer tools, but a usable Python | Use `/opt/homebrew/bin/python3` or `/usr/local/bin/python3` as PY. Expect a few more permission prompts. |
| Windows: `python` opens the Microsoft Store or prints nothing | Store alias, no real Python | Try `py -3 -V`. If neither works: manual mode. The student can install Python 3 from python.org (tick "Add to PATH") and start again. |
| `SyntaxError` or a version error from hp.py | Python older than 3.8 | Look for a newer Python (`python3.12 -V`, `python3.11 -V`, ...). If none: manual mode. |
| `ModuleNotFoundError: hp` | The script was copied out of its folder, or Python ran with `-I` | Always call `<SKILL_DIR>/scripts/hp.py` in place, without `-I`. |
| `doctor` shows `surface: unknown` | A setup the script doesn't recognise | Fine. Use `--out` on `init` if the student wants files somewhere specific; otherwise defaults apply. |
| Claude Code asks permission for every script call | The command shape differs from the pre-approved one, or the student already replied once this run | Use exactly `python3 <SKILL_DIR>/scripts/hp.py ...` with no `cd`, pipes or redirects. In phase 2, re-invoke the skill with `continue <RUN>` first. The student can also pick the "don't ask again" option. |
| Paths with spaces fail | Unquoted path | Quote the path. That may cost one extra permission prompt in Claude Code. |
| `/hiring-panel` opens a different skill, or two hiring-panel skills show up | The student also installed Alex Chen's original hiring-panel skill, which uses the same command name | Tell the student to keep only one, since the names collide. To remove his in Claude Code: `/plugin uninstall hiring-panel-skill@hiring-panel-skill`, or delete `~/.claude/skills/hiring-panel` if they copied it there. Until then, `/hiring-panel:hiring-panel` opens this one. |

## Input problems

| Symptom | Fix |
|---|---|
| `init` says `needs_transcription` | Check `resume.transcription_reason`. `image_only` or `garbled`: transcribe verbatim per SKILL.md Step 2. `encrypted`, `legacy_format`, `refused` or `unreadable`: ask for a .docx, a normal PDF or pasted text. |
| Encrypted PDF, legacy .doc, .pages, .odt | Ask for a .docx or an unlocked PDF ("Save As" or "Export"). |
| File over 15 MB | Ask for a smaller export; images usually cause it. |
| Posting link returns little or nothing | Logins and JavaScript pages. Ask for pasted text (references/edge-cases.md). |
| `jd.too_thin` | Ask once for the full posting. If there isn't more, continue; keyword results stay empty. |
| Keyword counts look wrong for the field | Use the optional terms step (`screen <RUN> --terms <PATH>`, SKILL.md Step 2). Quotes must be exact. |
| Garbled text in `ats_view.txt` | The PDF lacks proper text mapping. That's a real finding (the report flags it). A .docx export usually reads cleanly. |

## Panel problems

| Symptom | Fix |
|---|---|
| `validate` exits 1 | Redo only that reviewer once, adding `Your previous output failed validation: <errors>`. If it fails again, continue without it. |
| Quotes keep failing validation | Quotes must be copied character for character from the R# or J# line, typos included. Re-read the ledger line. |
| A lite review fails on an allowed value (an enum or a number type) | Copy the exact value from that reviewer's card in `_lite-cards.md`. Open `_output-format.md` only if the card and the error message don't settle it. |
| An Agent call errors (limits, concurrency) | Retry once. See references/panel-parallel.md section 3 for falling back. |
| A reviewer wrote outside its own file | Ignore it. Only `<RUN>/work/reviews/<id>.json` counts. |
| `synthesize` reports dropped findings | Normal: findings with bad quotes or false "missing keyword" claims are dropped by design. Don't restore them. |

## Rewrite and render problems

| Symptom | Fix |
|---|---|
| `truth` errors such as NUMBER_NOT_IN_SOURCE or SKILL_NOT_IN_SOURCE | Remove or soften that claim, or use the student's answer as Q# evidence if they gave one. Never edit evidence to fit. |
| `truth` error PLACEHOLDER_LEFT | Every `{{...}}` needs an answer or its honest `textIfUnknown`. |
| `render` refuses (exit 1) | Truth or the provenance audit hasn't passed. Finish SKILL.md Step 6, then render again. |
| The rendered resume .md is missing an entry name, organization or bullet | Don't hand the files over as if they were complete. Check the entry uses the fields shown in references/rewrite-rules.md section 14 (for a certification, `name` is the certificate and `org` the issuer), run `truth` and `render` again, and tell the student plainly if anything is still missing. |
| Gate fails on merged words or reading order | render already retried the inline layout. If it still fails, report it honestly; don't hand-edit files. |
| Exit 4 with a non-Latin name or text | The built-in PDF engine handles Western European text only. The .docx is fine; the student saves it as PDF. |
| The .docx looks wrong in Pages or Google Docs | Word is the reference. Suggest opening it in Word or LibreOffice, or using the PDF. |

## Plan, usage and files

| Symptom | Fix |
|---|---|
| A usage limit stopped the run | Same chat later: `status <RUN>` and continue. claude.ai new chat: the sandbox is empty, so start a new run; the early panel report already has the feedback. |
| `status` says to ask the questions, but the student already answered | Save their reply to `work/answers.json` (references/questions.md) and go to SKILL.md Step 6. Never ask a second batch. |
| The student can't find the files | Claude Code: `hiring-panel-runs/` in the folder they started Claude Code in. claude.ai: the download cards from `report --copy-to`; if none showed, run `report <RUN> --copy-to <outputs_dir>` again. |
| `git_warning` | The run folder has its own .gitignore. Remind the student once not to force-add it. |
| The student wants to start over | Start a new run with `init`; old run folders stay as they are. |
| The student asks for a cover letter or LinkedIn summary | Not in this version. Offer interview-prep questions or a run for another job. |
