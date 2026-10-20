# Releasing (maintainers)

How to ship a version of Hiring Panel so the three install paths in the README keep
working.

## Before the first public release

1. Pick the GitHub owner and replace every `OWNER` placeholder (README.md, SECURITY.md,
   CITATION.cff, the two manifests, the plugin README, docs, issue templates).
   `scripts/release.sh` refuses to build while any remain. Find them with:
   `grep -rnw OWNER --exclude-dir=.git --exclude=ARCHITECTURE.md --exclude-dir=scripts --exclude-dir=tests .`
2. Make the repository public and turn on **Settings > Code security > Private
   vulnerability reporting** (SECURITY.md relies on it).
3. Optional: add the screenshots listed in [img/README.md](img/README.md) (the README's
   written steps work without them). Re-measure run times on Free, Pro and Claude Code and
   update the README's "What to expect" box if they differ from the one test run quoted
   there.
4. Re-test every install path on a fresh account (Free and Pro), then update the "Last
   checked" date in the README.

## Every release

1. Bump the version in all six places (they must match):
   - `plugins/hiring-panel/.claude-plugin/plugin.json` (`version`)
   - `.claude-plugin/marketplace.json` (`metadata.version` and the plugin entry's `version`)
   - `plugins/hiring-panel/skills/hiring-panel/scripts/hp/__init__.py` (`__version__`)
   - `plugins/hiring-panel/skills/hiring-panel/SKILL.md` (`metadata.version` in the frontmatter)
   - the README footer
   - `CITATION.cff` (`version`, and set `date-released` to the release date)
2. Add a `## [X.Y.Z]` section to [CHANGELOG.md](../CHANGELOG.md).
3. Run the checks: `bash scripts/check.sh`.
4. Build locally to inspect: `bash scripts/release.sh`. It writes
   `dist/hiring-panel.plugin` and `dist/hiring-panel-skill.zip` and prints their sizes and
   SHA-256 hashes.
5. Commit, then tag and push: `git tag vX.Y.Z` and `git push origin vX.Y.Z`. The
   `release` job in `.github/workflows/check.yml` runs the tests, builds both files and
   attaches them to the GitHub release, so the README's `/releases/latest/download/`
   links pick them up.
6. Smoke-test option B and option C from the README with the new files.

## release.sh options

| Option | Effect |
|---|---|
| `--allow-placeholder` | Build even though `OWNER` placeholders remain (local testing only; never for a public release) |
| `--skip-validate` | Skip `claude plugin validate` when the Claude Code CLI isn't installed |
| `--out DIR` | Write the two files to DIR instead of `dist/` |

## What goes in each file

- `hiring-panel.plugin`: a zip whose single top-level folder is `hiring-panel/` (the
  plugin, with `.claude-plugin/plugin.json`). For claude.ai **Upload plugin**.
- `hiring-panel-skill.zip`: a zip whose single top-level folder is `hiring-panel/` (the
  skill folder with `SKILL.md`). For claude.ai **Customize > Skills** upload.

Both leave out `__pycache__`, `.pyc` files, `.DS_Store` and any `tests` folder, and use
fixed timestamps so the same source always gives the same bytes.
