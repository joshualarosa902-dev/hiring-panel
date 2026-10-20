"""Run folders and state.json (ARCHITECTURE.md section 4).

A run folder holds everything one review produces:

    <BASE>/<now_stamp>-<company-slug>-<role-slug>/
        First_Last_Resume.{docx,pdf,md}  Hiring_Panel_Report.{pdf,md,html}      (deliverables)
        work/state.json  work/inputs/...  work/screening/...  work/reviews/...   (working files)

BASE defaults to ./hiring-panel-runs, or to /mnt/user-data/outputs/hiring-panel-runs on claude.ai, and
always carries a .gitignore containing "*" so a run inside a git work tree is never committed by
accident.

state.json is the only file with wall-clock timestamps; every other JSON file a run writes is
byte-identical for identical inputs. `next_step()` reads state.json and the files on disk and says what
to run next, so a run cut off by a usage limit can resume.

Python 3.8+ standard library only. Nothing here touches the network.
"""
import os
from datetime import datetime

from hp import __version__
from hp.util import now_stamp, read_json, slugify, write_json, write_text

STATE_VERSION = "1.0"
RUNS_DIRNAME = "hiring-panel-runs"
OUTPUTS_DIR = "/mnt/user-data/outputs"          # claude.ai sandbox: files here become download cards

STAGES = ("student", "early_career", "experienced")
ROLE_LEVELS = ("intern", "entry", "mid", "senior", "unknown")
MODES = ("parallel", "sequential", "lite", "manual")
STEPS = ("init", "screen", "synthesize", "report_panel", "answers", "truth", "provenance", "render", "gate",
         "report_final")
REVIEWER_IDS = ("screening", "hiring_manager", "recruiter", "competitor", "ceo", "teammate", "skeptic")
GITIGNORE_TEXT = "# Hiring Panel run folders hold resumes. Never commit them.\n*\n"


class RunError(Exception):
    """A run folder or state.json problem the caller should report as bad input (exit 2)."""


# ------------------------------------------------------------------------------------- environment
def outputs_dir():
    """The claude.ai outputs folder when it exists, else ''."""
    return OUTPUTS_DIR if os.path.isdir(OUTPUTS_DIR) else ""


def detect_surface():
    """claude_ai (sandbox outputs folder present), claude_code (Claude Code sets CLAUDECODE in the
    environment of the commands it runs) or unknown."""
    if outputs_dir():
        return "claude_ai"
    if os.environ.get("CLAUDECODE") or os.environ.get("CLAUDE_CODE_ENTRYPOINT"):
        return "claude_code"
    return "unknown"


def default_base():
    """BASE when --out is not given."""
    out = outputs_dir()
    if out:
        return os.path.join(out, RUNS_DIRNAME)
    return os.path.join(os.getcwd(), RUNS_DIRNAME)


def resolve_base(out=None):
    if out:
        return os.path.abspath(os.path.expanduser(out))
    return default_base()


def ensure_gitignore(folder):
    """Create folder/.gitignore with "*" unless a .gitignore is already there (never clobber one)."""
    path = os.path.join(folder, ".gitignore")
    if not os.path.exists(path):
        write_text(path, GITIGNORE_TEXT)
    return path


def ensure_base(base):
    os.makedirs(base, exist_ok=True)
    ensure_gitignore(base)
    return base


def in_git_repo(path):
    """True when `path` (or the nearest existing parent) sits inside a git work tree.

    This walks up looking for a `.git` entry instead of running `git rev-parse`: on a Mac without
    Apple's developer tools, /usr/bin/git is a stub that opens an "install developer tools" dialog,
    which a student must never see. A `.git` folder or file up the tree is exactly what makes
    `git rev-parse` succeed in a normal checkout."""
    try:
        p = os.path.abspath(path)
        while not os.path.exists(p):
            parent = os.path.dirname(p)
            if parent == p:
                return False
            p = parent
        while True:
            if os.path.exists(os.path.join(p, ".git")):
                return True
            parent = os.path.dirname(p)
            if parent == p:
                return False
            p = parent
    except (OSError, ValueError):
        return False


# ------------------------------------------------------------------------------------- run folders
def run_name(company, role):
    parts = [now_stamp()]
    if company:
        parts.append(slugify(company, 40))
    parts.append(slugify(role or "resume", 50))
    return "-".join(parts)


def new_run_dir(base, company, role):
    """Create a fresh, empty run folder under base (adds -2, -3 ... when the name is taken)."""
    name = run_name(company, role)
    path = os.path.join(base, name)
    n = 2
    while os.path.exists(path):
        path = os.path.join(base, "%s-%d" % (name, n))
        n += 1
    os.makedirs(os.path.join(path, "work", "inputs"))
    ensure_gitignore(path)
    return path


def paths(run):
    """Every path a run uses, from the run folder (absolute)."""
    w = os.path.join(run, "work")
    return {
        "run": run,
        "work": w,
        "state": os.path.join(w, "state.json"),
        "inputs": os.path.join(w, "inputs"),
        "transcript": os.path.join(w, "inputs", "transcript.txt"),
        "resume_md": os.path.join(w, "inputs", "resume.md"),
        "ats_view": os.path.join(w, "inputs", "ats_view.txt"),
        "jd_md": os.path.join(w, "inputs", "jd.md"),
        "ledger": os.path.join(w, "inputs", "ledger.json"),
        "terms": os.path.join(w, "inputs", "terms.json"),
        "before": os.path.join(w, "screening", "before"),
        "screening": os.path.join(w, "screening", "before", "screening.json"),
        "screening_md": os.path.join(w, "screening", "before", "screening.md"),
        "brief": os.path.join(w, "screening", "before", "brief.json"),
        "after": os.path.join(w, "screening", "after"),
        "reviews": os.path.join(w, "reviews"),
        "merges": os.path.join(w, "merges.json"),
        "synthesis": os.path.join(w, "synthesis.json"),
        "answers": os.path.join(w, "answers.json"),
        "rewrite": os.path.join(w, "rewrite"),
        "resume_json": os.path.join(w, "rewrite", "resume.json"),
        "truth": os.path.join(w, "rewrite", "truth.json"),
        "provenance": os.path.join(w, "rewrite", "provenance.json"),
        "gate": os.path.join(w, "gate.json"),
        "report": os.path.join(w, "report.json"),
        "recheck": os.path.join(run, "recheck"),
    }


def resolve_run(arg):
    """Turn the RUN argument (the run folder, its work/ folder or its state.json) into the absolute run
    folder. Raises RunError when it is not a run folder."""
    if not isinstance(arg, str) or not arg.strip():
        raise RunError("RUN must be the run folder that init printed")
    p = os.path.abspath(os.path.expanduser(arg.strip()))
    if os.path.basename(p) == "state.json":
        p = os.path.dirname(p)
    if os.path.basename(p) == "work" and os.path.isfile(os.path.join(p, "state.json")):
        p = os.path.dirname(p)
    if not os.path.isdir(p):
        raise RunError("no run folder at %s" % p)
    if not os.path.isfile(os.path.join(p, "work", "state.json")):
        raise RunError("%s is not a Hiring Panel run folder (work/state.json is missing)" % p)
    return p


# ------------------------------------------------------------------------------------- state.json
def now_iso():
    """Wall-clock time for state.json only (the one file allowed to hold timestamps)."""
    return datetime.now().replace(microsecond=0).isoformat()


def new_state(as_of, stage, role_level, locale, language, role, company, jd_source, general_review, flags):
    return {
        "schema_version": STATE_VERSION,
        "hp_version": __version__,
        "created": now_iso(),
        "as_of": as_of,
        "candidate_stage": stage,
        "role_level": role_level,
        "locale": locale,
        "language": language,
        "role": role,
        "company": company,
        "jd_source": jd_source,
        "general_review": bool(general_review),
        "mode": None,
        "flags": {"thin": bool(flags.get("thin")), "long": bool(flags.get("long")),
                  "needs_transcription": bool(flags.get("needs_transcription")),
                  "non_english": bool(flags.get("non_english"))},
        "ledger_overrides": [],
        "steps": {},
    }


def load_state(run):
    try:
        state = read_json(paths(run)["state"])
    except (OSError, ValueError) as e:
        raise RunError("work/state.json is unreadable (%s)" % e.__class__.__name__)
    if not isinstance(state, dict):
        raise RunError("work/state.json is not a JSON object")
    state.setdefault("steps", {})
    if not isinstance(state["steps"], dict):
        state["steps"] = {}
    if not isinstance(state.get("ledger_overrides"), list):
        state["ledger_overrides"] = []
    if not isinstance(state.get("flags"), dict):
        state["flags"] = {}
    return state


def save_state(run, state):
    write_json(paths(run)["state"], state)


def mark_step(state, step):
    state.setdefault("steps", {})[step] = now_iso()
    return state


def ledger_target(state):
    """The ledger 'target' block, from state.json."""
    return {"role_title": state.get("role") or "", "role_level": state.get("role_level") or "unknown",
            "company": state.get("company"), "locale": state.get("locale") or "en-US",
            "general_review": bool(state.get("general_review"))}


# ------------------------------------------------------------------------------------- status
def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def _newer(a, b):
    """True when file a exists and was modified after file b (or b is missing)."""
    ta, tb = _mtime(a), _mtime(b)
    return ta is not None and (tb is None or ta > tb + 1e-6)


def review_files(run):
    d = paths(run)["reviews"]
    return [rid for rid in REVIEWER_IDS if os.path.isfile(os.path.join(d, rid + ".json"))]


def next_step(run, state):
    """(step, command, hint) for `status`. Commands use RUN as a stand-in for the run folder path."""
    p = paths(run)
    steps = state.get("steps") or {}
    mode = state.get("mode") or "<parallel|sequential|lite>"
    if (state.get("flags") or {}).get("needs_transcription") and not os.path.isfile(p["transcript"]):
        return ("transcribe", "",
                "The file has no readable text. Transcribe it word for word into RUN/work/inputs/transcript.txt, "
                "confirm it with the student, then run init again with the same arguments plus --resume-text "
                "RUN/work/inputs/transcript.txt and use the new run folder.")
    if "synthesize" not in steps or not os.path.isfile(p["synthesis"]):
        have = review_files(run)
        if len(have) < len(REVIEWER_IDS):
            missing = [r for r in REVIEWER_IDS if r not in have]
            return ("panel", "synthesize RUN --mode %s" % mode,
                    "Run the reviewers still missing (%s) and check each file with validate RUN <file>; then "
                    "synthesize." % ", ".join(missing))
        return ("synthesize", "synthesize RUN --mode %s" % mode, "All seven review files exist. Combine them.")
    if "report_panel" not in steps and "report_final" not in steps:
        return ("report_panel", "report RUN", "Build the early panel report so the feedback is saved.")
    if not os.path.isfile(p["answers"]):
        # A re-invoked skill must never ask a second batch (live tests A18, Phase 2): check the chat first.
        return ("answers", "", "If the student already answered the questions, save answers.json and go to Step 6; "
                               "otherwise share the summary and ask the one question batch "
                               "(references/questions.md).")
    if not os.path.isfile(p["resume_json"]):
        return ("rewrite", "", "Write work/rewrite/resume.json per references/rewrite-rules.md.")
    truth = None
    if os.path.isfile(p["truth"]):
        try:
            truth = read_json(p["truth"])
        except (OSError, ValueError):
            truth = None
    stale = _newer(p["resume_json"], p["truth"]) or _newer(p["answers"], p["truth"])
    if not isinstance(truth, dict) or truth.get("passed") is not True or stale:
        return ("truth", "truth RUN", "Run the truth check; fix every error and run it again until it passes.")
    needs_audit = any(isinstance(w, dict) and w.get("code") == "NEW_WORDING" for w in truth.get("warnings") or [])
    if needs_audit and not os.path.isfile(p["provenance"]):
        return ("provenance", "", "Run the provenance audit (references/provenance-audit.md) and write "
                                  "work/rewrite/provenance.json.")
    if "render" not in steps or _newer(p["resume_json"], p["gate"]):
        return ("render", "render RUN", "Build the resume files and run the quality gate.")
    if "report_final" not in steps or _newer(p["gate"], p["report"]):
        return ("report_final", "report RUN", "Build the final report and deliver the files.")
    return ("done", "", "Everything is built. Offer interview practice or a new run for another job.")
