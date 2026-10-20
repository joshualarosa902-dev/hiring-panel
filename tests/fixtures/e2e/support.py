"""Helpers shared by tests/test_cli_*.py and tests/test_e2e_*.py (not a test module itself).

Everything runs the real CLI as a subprocess (`python hp.py ...`) with the interpreter running the
tests, the clock pinned (HP_AS_OF, HP_NOW) and a working directory outside the repo, the way Claude
calls it. Every call checks the contract: stdout holds exactly one JSON object.
"""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))                 # tests/fixtures/e2e
TESTS = os.path.dirname(os.path.dirname(HERE))
ROOT = os.path.dirname(TESTS)
SKILL = os.path.join(ROOT, "plugins", "hiring-panel", "skills", "hiring-panel")
SCRIPTS = os.path.join(SKILL, "scripts")
HP = os.path.join(SCRIPTS, "hp.py")
REVIEWS = os.path.join(HERE, "reviews")
REVIEWS_GENERAL = os.path.join(HERE, "reviews_general")
FILES = os.path.join(os.path.dirname(HERE), "files")             # the ingest builder's fixtures
REVIEWER_IDS = ("screening", "hiring_manager", "recruiter", "competitor", "ceo", "teammate", "skeptic")

AS_OF = "2026-10-20"
NOW = "2026-10-20-1430"
ROLE = "Marketing Analytics Intern"
COMPANY = "Northwind Foods"

SITECUSTOMIZE = '''"""Test-only: refuse every network call so a script that tried one would crash loudly."""
import socket


class NetworkBlocked(RuntimeError):
    pass


def _refuse(*args, **kwargs):
    raise NetworkBlocked("network access attempted during a Hiring Panel test")


socket.socket = _refuse
socket.create_connection = _refuse
socket.getaddrinfo = _refuse
socket.gethostbyname = _refuse
'''

if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)


def fixture(name):
    return os.path.join(HERE, name)


def env(extra=None, pdf_engines=None, block_network_dir=None):
    """A clean environment for the CLI: pinned clock, no bytecode files, optional engine limits."""
    e = dict(os.environ)
    for k in ("HP_PDF_ENGINES", "HP_BROWSER", "HP_SOFFICE", "HP_PDF_BACKENDS", "PYTHONPATH", "CLAUDECODE",
              "CLAUDE_CODE_ENTRYPOINT"):
        e.pop(k, None)
    e["HP_AS_OF"] = AS_OF
    e["HP_NOW"] = NOW
    e["PYTHONDONTWRITEBYTECODE"] = "1"
    e["PYTHONIOENCODING"] = "utf-8"
    if pdf_engines:
        e["HP_PDF_ENGINES"] = pdf_engines
    if block_network_dir:
        e["PYTHONPATH"] = block_network_dir
    if extra:
        e.update(extra)
    return e


def network_blocker(tmp):
    """A folder holding a sitecustomize.py that blocks sockets (put it on PYTHONPATH)."""
    d = os.path.join(tmp, "no-network")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "sitecustomize.py"), "w", encoding="utf-8") as f:
        f.write(SITECUSTOMIZE)
    return d


class CliResult(object):
    def __init__(self, code, data, stdout, stderr):
        self.code, self.data, self.stdout, self.stderr = code, data, stdout, stderr

    def __repr__(self):
        return "CliResult(code=%r, data=%s, stderr=%s)" % (self.code, json.dumps(self.data)[:1500],
                                                           self.stderr[-1500:])


def hp(args, cwd, environ=None, stdin=None, timeout=300):
    """Run hp.py; return CliResult. Raises AssertionError unless stdout is exactly one JSON object."""
    proc = subprocess.run([sys.executable, HP] + list(args), cwd=cwd, env=environ or env(),
                          input=stdin.encode("utf-8") if isinstance(stdin, str) else stdin,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    out = proc.stdout.decode("utf-8")
    err = proc.stderr.decode("utf-8", "replace")
    try:
        data = json.loads(out)
    except ValueError:
        raise AssertionError("stdout is not exactly one JSON object (exit %s):\n%s\n--- stderr:\n%s"
                             % (proc.returncode, out[:2000], err[-2000:]))
    if not isinstance(data, dict):
        raise AssertionError("stdout JSON is not an object: %r" % out[:200])
    if "Traceback" in out:
        raise AssertionError("a traceback reached stdout")
    return CliResult(proc.returncode, data, out, err)


def init_args(resume, base, jd=None, extra=()):
    args = ["init", "--resume", resume]
    args += ["--jd", jd, "--jd-source", "pasted"] if jd else ["--no-jd"]
    args += ["--role", ROLE, "--stage", "student", "--role-level", "intern", "--locale", "en-US", "--out", base]
    if jd:
        args += ["--company", COMPANY]
    return args + list(extra)


def copy_reviews(src_dir, run, ids=REVIEWER_IDS):
    d = os.path.join(run, "work", "reviews")
    os.makedirs(d, exist_ok=True)
    for rid in ids:
        shutil.copyfile(os.path.join(src_dir, rid + ".json"), os.path.join(d, rid + ".json"))
    return d


def place(src, run, rel):
    dst = os.path.join(run, "work", rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src, dst)
    return dst


def read(path, mode="r"):
    if mode == "rb":
        with open(path, "rb") as f:
            return f.read()
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def load(path):
    return json.loads(read(path))


def deterministic_files(run):
    """Relative paths of every run file that must be byte-identical between two identical runs.
    state.json (timestamps by design) and PDFs (engines stamp creation dates) are left out."""
    out = []
    for here, dirs, files in os.walk(run):
        dirs.sort()
        for name in sorted(files):
            rel = os.path.relpath(os.path.join(here, name), run)
            if name == "state.json" or name.endswith(".pdf"):
                continue
            out.append(rel)
    return out


def docx_text(path):
    """All XML of a .docx (for scanning generated files)."""
    import zipfile
    with zipfile.ZipFile(path) as z:
        return "\n".join(z.read(n).decode("utf-8", "replace") for n in sorted(z.namelist()) if n.endswith(".xml"))
