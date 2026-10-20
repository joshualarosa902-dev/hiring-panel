#!/usr/bin/env bash
# Build the two Hiring Panel release files:
#
#   dist/hiring-panel.plugin     zip whose single top-level folder is hiring-panel/ (the plugin,
#                                with .claude-plugin/plugin.json): claude.ai "Upload plugin"
#   dist/hiring-panel-skill.zip  zip whose single top-level folder is hiring-panel/ (the skill
#                                folder with SKILL.md): claude.ai "Customize > Skills" upload
#
# Before building it checks that no OWNER placeholder remains, that every version string
# agrees, and that `claude plugin validate --strict` passes for the plugin and the
# marketplace. Archives are deterministic: sorted entries, fixed timestamps, no
# __pycache__, .pyc, .DS_Store or tests folders.
#
# Usage: bash scripts/release.sh [--allow-placeholder] [--skip-validate] [--out DIR]

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bash scripts/release.sh [options]

Options:
  --allow-placeholder  Build even if the "OWNER" GitHub placeholder remains (local testing only)
  --skip-validate      Skip `claude plugin validate` (when the Claude Code CLI isn't installed)
  --out DIR            Write the release files to DIR instead of dist/
  -h, --help           Show this help
EOF
}

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/dist"
ALLOW_PLACEHOLDER=0
SKIP_VALIDATE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --allow-placeholder) ALLOW_PLACEHOLDER=1 ;;
    --skip-validate) SKIP_VALIDATE=1 ;;
    --out)
      if [ $# -lt 2 ] || [ -z "$2" ]; then
        echo "release.sh: --out needs a folder" >&2
        exit 2
      fi
      OUT="$2"
      shift
      ;;
    -h|--help) usage; exit 0 ;;
    *) echo "release.sh: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

PLUGIN_DIR="$ROOT/plugins/hiring-panel"
SKILL_DIR="$PLUGIN_DIR/skills/hiring-panel"

fail() { echo "release.sh: $*" >&2; exit 1; }

# --- Find a Python 3 without triggering the macOS developer-tools pop-up -------------------
find_python() {
  if [ -n "${PYTHON:-}" ]; then echo "$PYTHON"; return 0; fi
  local candidates="python3 python"
  if [ "$(uname -s 2>/dev/null)" = "Darwin" ] && ! xcode-select -p >/dev/null 2>&1; then
    # /usr/bin/python3 is a stub that opens an install dialog when the tools are missing.
    candidates="/opt/homebrew/bin/python3 /usr/local/bin/python3"
  fi
  local c
  for c in $candidates; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1; then
      echo "$c"; return 0
    fi
  done
  return 1
}
PY="$(find_python)" || fail "no Python 3.8+ found (set PYTHON=/path/to/python3)"

for f in "$PLUGIN_DIR/.claude-plugin/plugin.json" "$ROOT/.claude-plugin/marketplace.json" \
         "$SKILL_DIR/SKILL.md" "$SKILL_DIR/scripts/hp.py" "$PLUGIN_DIR/LICENSE" "$PLUGIN_DIR/README.md"; do
  [ -f "$f" ] || fail "missing required file: ${f#"$ROOT"/}"
done

# --- 1. The OWNER placeholder ------------------------------------------------------------
# ARCHITECTURE.md documents the placeholder and scripts/ and tests/ mention it on purpose,
# so they are not scanned.
SCAN_PATHS=()
for p in README.md SECURITY.md CHANGELOG.md NOTICE CITATION.cff docs .claude-plugin plugins .github; do
  [ -e "$ROOT/$p" ] && SCAN_PATHS+=("$ROOT/$p")
done
# docs/releasing.md explains the placeholder itself, so it is skipped too.
PLACEHOLDERS="$(grep -rnIw --exclude-dir=__pycache__ --exclude=releasing.md 'OWNER' ${SCAN_PATHS[@]+"${SCAN_PATHS[@]}"} 2>/dev/null || true)"
if [ -n "$PLACEHOLDERS" ]; then
  if [ "$ALLOW_PLACEHOLDER" -eq 1 ]; then
    echo "release.sh: WARNING: building with the OWNER placeholder still present (--allow-placeholder)." >&2
  else
    echo "$PLACEHOLDERS" | sed "s|$ROOT/||" >&2
    fail "the GitHub owner placeholder \"OWNER\" is still present (see above). Replace it, or pass --allow-placeholder for a local test build."
  fi
fi

# --- 2. Names and versions agree ----------------------------------------------------------
"$PY" - "$ROOT" <<'PYEOF'
import json, os, re, sys

root = sys.argv[1]
problems = []

def load(rel):
    with open(os.path.join(root, rel), encoding="utf-8") as fh:
        return json.load(fh)

plugin = load("plugins/hiring-panel/.claude-plugin/plugin.json")
market = load(".claude-plugin/marketplace.json")
version = plugin.get("version")
if plugin.get("name") != "hiring-panel":
    problems.append("plugin.json name must be 'hiring-panel'")
if not re.match(r"^\d+\.\d+\.\d+$", str(version)):
    problems.append("plugin.json version must look like 1.2.3")

entries = [p for p in market.get("plugins", []) if p.get("name") == "hiring-panel"]
if len(entries) != 1:
    problems.append("marketplace.json must list exactly one 'hiring-panel' plugin")
else:
    entry = entries[0]
    if entry.get("source") != "./plugins/hiring-panel":
        problems.append("marketplace.json plugin source must be ./plugins/hiring-panel")
    if "version" in entry and entry["version"] != version:
        problems.append("marketplace.json plugin version %r != plugin.json %r" % (entry["version"], version))
meta_version = market.get("metadata", {}).get("version")
if meta_version is not None and meta_version != version:
    problems.append("marketplace.json metadata.version %r != plugin.json %r" % (meta_version, version))

init_path = os.path.join(root, "plugins/hiring-panel/skills/hiring-panel/scripts/hp/__init__.py")
with open(init_path, encoding="utf-8") as fh:
    m = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", fh.read())
if not m or m.group(1) != version:
    problems.append("hp/__init__.py __version__ %r != plugin.json %r" % (m and m.group(1), version))

with open(os.path.join(root, "plugins/hiring-panel/skills/hiring-panel/SKILL.md"), encoding="utf-8") as fh:
    skill = fh.read()
fm = re.match(r"^---\n(.*?)\n---\n", skill, re.S)
if not fm or not re.search(r"^name: hiring-panel$", fm.group(1), re.M):
    problems.append("SKILL.md frontmatter must start the file and say 'name: hiring-panel'")
else:
    # metadata.version (an indented "version:" line in the frontmatter), when present, must agree.
    mv = re.search(r"^[ \t]+version:[ \t]*[\"']?([^\"'\s]+)", fm.group(1), re.M)
    if mv and mv.group(1) != version:
        problems.append("SKILL.md metadata version %r != plugin.json %r" % (mv.group(1), version))

changelog = os.path.join(root, "CHANGELOG.md")
if os.path.exists(changelog):
    with open(changelog, encoding="utf-8") as fh:
        if "## [%s]" % version not in fh.read():
            problems.append("CHANGELOG.md has no '## [%s]' section" % version)
citation = os.path.join(root, "CITATION.cff")
if os.path.exists(citation):
    with open(citation, encoding="utf-8") as fh:
        cff = fh.read()
    # The top-level version line only (references to other software are indented).
    m = re.search(r"^version:\s*[\"']?([^\"'\s]+)", cff, re.M)
    if not m or m.group(1) != version:
        problems.append("CITATION.cff version %r != plugin.json %r" % (m and m.group(1), version))
readme = os.path.join(root, "README.md")
if os.path.exists(readme):
    with open(readme, encoding="utf-8") as fh:
        if "Version %s" % version not in fh.read():
            problems.append("README.md footer does not say 'Version %s'" % version)

if problems:
    for p in problems:
        print("release.sh: " + p, file=sys.stderr)
    sys.exit(1)
print("Version %s: plugin.json, marketplace.json, hp/__init__.py, SKILL.md, CHANGELOG, CITATION.cff and README "
      "agree." % version)
PYEOF

# --- 3. claude plugin validate ------------------------------------------------------------
if [ "$SKIP_VALIDATE" -eq 1 ]; then
  echo "release.sh: skipping claude plugin validate (--skip-validate)." >&2
else
  command -v claude >/dev/null 2>&1 || fail "the Claude Code CLI ('claude') is not installed. Install it, or pass --skip-validate."
  claude plugin validate --strict "$PLUGIN_DIR" || fail "claude plugin validate failed for the plugin"
  claude plugin validate --strict "$ROOT" || fail "claude plugin validate failed for the marketplace"
fi

# --- 4. Build both archives deterministically, then check their structure -----------------
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"

"$PY" - "$PLUGIN_DIR" "$SKILL_DIR" "$OUT" <<'PYEOF'
import hashlib, os, stat, sys, tempfile, zipfile

plugin_dir, skill_dir, out_dir = sys.argv[1:4]
SKIP_DIRS = {"__pycache__", "tests", ".git", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
SKIP_FILES = {".DS_Store", "Thumbs.db", "desktop.ini"}
SKIP_SUFFIXES = (".pyc", ".pyo")
FIXED_TIME = (1980, 1, 1, 0, 0, 0)


def skipped(name):
    return name in SKIP_FILES or name.endswith(SKIP_SUFFIXES) or name.startswith("._")


def collect(src):
    """Sorted list of (relative path, absolute path, is_dir); refuses symlinks."""
    items = []
    for here, dirs, files in os.walk(src):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for d in dirs:
            full = os.path.join(here, d)
            if os.path.islink(full):
                sys.exit("release.sh: refusing to package a symlink: %s" % full)
            items.append((os.path.relpath(full, src), full, True))
        for f in sorted(files):
            full = os.path.join(here, f)
            if skipped(f):
                continue
            if os.path.islink(full):
                sys.exit("release.sh: refusing to package a symlink: %s" % full)
            items.append((os.path.relpath(full, src), full, False))
    return sorted(items, key=lambda it: it[0].replace(os.sep, "/"))


def build(src, top, dest):
    """Zip src so that every entry sits under the single top-level folder `top`."""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(dest), suffix=".tmp")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            root_info = zipfile.ZipInfo(top + "/", date_time=FIXED_TIME)
            root_info.create_system = 3
            root_info.external_attr = (0o40755 << 16) | 0x10
            z.writestr(root_info, b"")
            for rel, full, is_dir in collect(src):
                arc = top + "/" + rel.replace(os.sep, "/")
                if is_dir:
                    info = zipfile.ZipInfo(arc + "/", date_time=FIXED_TIME)
                    info.create_system = 3
                    info.external_attr = (0o40755 << 16) | 0x10
                    z.writestr(info, b"")
                    continue
                mode = 0o755 if os.stat(full).st_mode & stat.S_IXUSR else 0o644
                info = zipfile.ZipInfo(arc, date_time=FIXED_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | mode) << 16
                with open(full, "rb") as fh:
                    z.writestr(info, fh.read())
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def check(dest, required):
    with zipfile.ZipFile(dest) as z:
        bad = z.testzip()
        if bad:
            sys.exit("release.sh: corrupt entry %s in %s" % (bad, dest))
        names = z.namelist()
    tops = {n.split("/", 1)[0] for n in names}
    if tops != {"hiring-panel"}:
        sys.exit("release.sh: %s must have exactly one top-level folder, found %s" % (dest, sorted(tops)))
    for r in required:
        if r not in names:
            sys.exit("release.sh: %s is missing %s" % (dest, r))
    for n in names:
        parts = n.rstrip("/").split("/")
        if any(p in SKIP_DIRS for p in parts) or skipped(parts[-1]):
            sys.exit("release.sh: %s contains an excluded file: %s" % (dest, n))
    return len([n for n in names if not n.endswith("/")])


targets = [
    (plugin_dir, os.path.join(out_dir, "hiring-panel.plugin"),
     ["hiring-panel/.claude-plugin/plugin.json", "hiring-panel/skills/hiring-panel/SKILL.md",
      "hiring-panel/skills/hiring-panel/scripts/hp.py", "hiring-panel/LICENSE", "hiring-panel/README.md"]),
    (skill_dir, os.path.join(out_dir, "hiring-panel-skill.zip"),
     ["hiring-panel/SKILL.md", "hiring-panel/scripts/hp.py"]),
]
for src, dest, required in targets:
    build(src, "hiring-panel", dest)
    count = check(dest, required)
    with open(dest, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    print("%-26s %4d files  %8d bytes  sha256 %s" % (os.path.basename(dest), count, os.path.getsize(dest), digest))
PYEOF

echo "Release files are in ${OUT}."
