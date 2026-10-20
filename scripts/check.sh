#!/usr/bin/env bash
# Run every local check for Hiring Panel:
#   1. the unittest suite on each Python 3.8+ found on this machine
#   2. `claude plugin validate --strict` on the plugin and on the marketplace
#   3. a no-network check: a static scan of the shipped Python for network modules, plus
#      `hp.py doctor` run with sockets blocked
#   4. `bash -n` on the repo's shell scripts
#
# Usage: bash scripts/check.sh [--no-tests] [--no-validate] [--no-network-check]
# Exit status: 0 when every check that ran passed, 1 otherwise.

set -uo pipefail

usage() {
  cat <<'EOF'
Usage: bash scripts/check.sh [options]

Options:
  --no-tests          Skip the unittest runs
  --no-validate       Skip `claude plugin validate`
  --no-network-check  Skip the no-network checks
  -h, --help          Show this help
EOF
}

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL_DIR="$ROOT/plugins/hiring-panel/skills/hiring-panel"
RUN_TESTS=1
RUN_VALIDATE=1
RUN_NETWORK=1

while [ $# -gt 0 ]; do
  case "$1" in
    --no-tests) RUN_TESTS=0 ;;
    --no-validate) RUN_VALIDATE=0 ;;
    --no-network-check) RUN_NETWORK=0 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "check.sh: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

FAILED=0
pass() { echo "  PASS  $*"; }
flunk() { echo "  FAIL  $*"; FAILED=1; }
skip() { echo "  SKIP  $*"; }

# --- Find every distinct Python 3.8+ (never poke the macOS developer-tools stub) ----------
NO_MAC_TOOLS=0
if [ "$(uname -s 2>/dev/null)" = "Darwin" ] && ! xcode-select -p >/dev/null 2>&1; then
  NO_MAC_TOOLS=1
fi

PYTHONS=()
SEEN=" "
for c in ${PYTHON:-} python3.8 python3.9 python3.10 python3.11 python3.12 python3.13 python3.14 \
         python3 python /usr/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
  path="$(command -v "$c" 2>/dev/null)" || continue
  if [ "$NO_MAC_TOOLS" -eq 1 ] && { [ "$path" = "/usr/bin/python3" ] || [ "$path" = "/usr/bin/python" ]; }; then
    continue
  fi
  real="$("$path" -c 'import os, sys; print(os.path.realpath(sys.executable)) if sys.version_info >= (3, 8) else sys.exit(1)' 2>/dev/null)" || continue
  case "$SEEN" in *" $real "*) continue ;; esac
  SEEN="$SEEN$real "
  PYTHONS+=("$path")
done

echo "Hiring Panel checks ($ROOT)"

# --- 1. Unit tests ---------------------------------------------------------------------
echo
echo "1. Unit tests"
if [ "$RUN_TESTS" -eq 0 ]; then
  skip "unit tests (--no-tests)"
elif [ "${#PYTHONS[@]}" -eq 0 ]; then
  flunk "no Python 3.8+ found"
else
  for py in "${PYTHONS[@]}"; do
    version="$("$py" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
    log="$(mktemp "${TMPDIR:-/tmp}/hp-check.XXXXXX")"
    if (cd "$ROOT" && PYTHONDONTWRITEBYTECODE=1 "$py" -m unittest discover -s tests -p 'test_*.py') >"$log" 2>&1; then
      pass "Python $version ($py): $(grep -E '^Ran [0-9]+ test' "$log" | tail -n 1)"
    else
      flunk "Python $version ($py): $(grep -E '^(Ran [0-9]+ test|FAILED)' "$log" | tr '\n' ' ')"
      tail -n 40 "$log" | sed 's/^/        /'
    fi
    rm -f "$log"
  done
fi

# --- 2. Manifest validation ------------------------------------------------------------
echo
echo "2. Plugin and marketplace manifests"
if [ "$RUN_VALIDATE" -eq 0 ]; then
  skip "claude plugin validate (--no-validate)"
elif ! command -v claude >/dev/null 2>&1; then
  skip "claude plugin validate (the Claude Code CLI is not installed; CI runs it)"
else
  for target in "$ROOT/plugins/hiring-panel" "$ROOT"; do
    label="${target#"$ROOT"}"; label="${label#/}"; label="${label:-.}"
    if out="$(claude plugin validate --strict "$target" 2>&1)"; then
      pass "claude plugin validate --strict $label"
    else
      flunk "claude plugin validate --strict $label"
      echo "$out" | sed 's/^/        /'
    fi
  done
fi

# --- 3. No network ---------------------------------------------------------------------
echo
echo "3. No network access from shipped code"
if [ "$RUN_NETWORK" -eq 0 ]; then
  skip "no-network checks (--no-network-check)"
elif [ "${#PYTHONS[@]}" -eq 0 ]; then
  flunk "no Python 3.8+ found for the no-network checks"
else
  py="${PYTHONS[0]}"
  if "$py" - "$SKILL_DIR/scripts" <<'PYEOF'
import ast, os, sys

# Modules that open network connections (or exist only to do so). urllib.parse is fine.
BANNED = {"socket", "ssl", "socketserver", "http", "urllib.request", "urllib3", "requests",
          "httpx", "aiohttp", "ftplib", "smtplib", "poplib", "imaplib", "telnetlib", "nntplib",
          "xmlrpc", "webbrowser", "websocket", "websockets", "asyncore", "asynchat"}
# Command-line tools that fetch from the network, if a script tried to shell out to them.
BANNED_COMMANDS = {"curl", "wget", "Invoke-WebRequest", "Invoke-RestMethod"}


def banned(module):
    parts = (module or "").split(".")
    return any(".".join(parts[:i]) in BANNED for i in range(1, len(parts) + 1))


root = sys.argv[1]
hits = []
for here, dirs, files in os.walk(root):
    dirs[:] = sorted(d for d in dirs if d != "__pycache__")
    for name in sorted(files):
        if not name.endswith(".py"):
            continue
        full = os.path.join(here, name)
        path = os.path.relpath(full, root)
        with open(full, "rb") as fh:
            try:
                tree = ast.parse(fh.read(), filename=full)
            except SyntaxError as exc:
                hits.append("%s: cannot parse (%s)" % (path, exc))
                continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                hits += ["%s:%d imports %s" % (path, node.lineno, a.name) for a in node.names if banned(a.name)]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and banned(node.module):
                hits.append("%s:%d imports from %s" % (path, node.lineno, node.module))
            elif isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) == "__import__":
                hits.append("%s:%d uses __import__ (check it by hand)" % (path, node.lineno))
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in BANNED_COMMANDS:
                hits.append("%s:%d mentions the command %r" % (path, node.lineno, node.value))
for h in hits:
    print("        scripts/" + h)
sys.exit(1 if hits else 0)
PYEOF
  then
    pass "static scan: no network modules imported under scripts/"
  else
    flunk "static scan found network code (listed above)"
  fi

  if [ -f "$SKILL_DIR/scripts/hp.py" ]; then
    if "$py" - "$SKILL_DIR/scripts/hp.py" <<'PYEOF'
import io, os, runpy, socket, sys

class NetworkBlocked(Exception):
    pass

def refuse(*args, **kwargs):
    raise NetworkBlocked("network access attempted")

# Block every way a socket can be opened or a name resolved.
socket.socket = refuse
socket.create_connection = refuse
socket.getaddrinfo = refuse
socket.gethostbyname = refuse

script = sys.argv[1]
sys.argv = [script, "doctor"]
sys.path.insert(0, os.path.dirname(script))
captured = io.StringIO()
real_stdout, sys.stdout = sys.stdout, captured
code = 0
try:
    runpy.run_path(script, run_name="__main__")
except SystemExit as exc:
    code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
except NetworkBlocked:
    sys.stdout = real_stdout
    print("        hp.py doctor tried to open a network connection")
    sys.exit(1)
finally:
    sys.stdout = real_stdout
if code != 0:
    print("        hp.py doctor exited with %s" % code)
    sys.exit(1)
PYEOF
    then
      pass "hp.py doctor runs with sockets blocked"
    else
      flunk "hp.py doctor with sockets blocked"
    fi
  else
    skip "hp.py doctor with sockets blocked (scripts/hp.py does not exist yet)"
  fi
fi

# --- 4. Shell syntax --------------------------------------------------------------------
echo
echo "4. Shell scripts"
for sh in "$ROOT"/scripts/*.sh; do
  [ -f "$sh" ] || continue
  if bash -n "$sh" 2>/dev/null; then
    pass "bash -n ${sh#"$ROOT"/}"
  else
    flunk "bash -n ${sh#"$ROOT"/}"
  fi
done

echo
if [ "$FAILED" -eq 0 ]; then
  echo "All checks passed."
else
  echo "Some checks failed."
fi
exit "$FAILED"
