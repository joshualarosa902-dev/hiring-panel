#!/usr/bin/env python3
"""Hiring Panel: the one command-line entry point (ARCHITECTURE.md section 13).

    python3 <SKILL_DIR>/scripts/hp.py <command> [arguments]

Commands: doctor, init, ledger, screen, validate, synthesize, truth, render, report, status, recheck.

Every command prints exactly ONE JSON object on stdout and nothing else there; hints and diagnostics
go to stderr. Exit codes:
    0  ok
    1  a check failed (truth errors, an invalid review, the render gate, render refused)
    2  bad arguments or unreadable input
    3  the resume is longer than its page target
    4  PDF skipped (the .docx and .md were still written)
`validate` follows the same rule: "ok" is the only verdict (true with exit 0, false with exit 1);
"partial_ok" only says whether synthesize could still use part of a review that stays invalid after the
one retry, and "next" says what to do. `-h` on any command prints its help once, inside the JSON object
("help": one string per line).

This file finds its own folder through __file__ and puts it first on sys.path, so it works from any
working directory. Never run it with `python3 -I` (that drops the folder from the path). Python 3.8+
standard library only; nothing here touches the network.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if not sys.path or sys.path[0] != HERE:
    sys.path.insert(0, HERE)

import argparse  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import traceback  # noqa: E402
from datetime import date  # noqa: E402

EXIT_OK, EXIT_CHECK, EXIT_INPUT, EXIT_LONG, EXIT_NO_PDF = 0, 1, 2, 3, 4
MAX_TEXT_BYTES = 2 * 1024 * 1024          # a pasted resume, transcript or posting larger than this is refused
MAX_TERMS_BYTES = 1024 * 1024
TEXT_FILE_EXTS = (".txt", ".md", ".markdown", ".text", "")
DOC_FILE_EXTS = (".docx", ".pdf", ".rtf", ".doc", ".odt", ".pages", ".html", ".htm")
KNOWN_FORMATS = ("docx", "pdf", "txt", "md", "rtf", "doc", "pages", "odt")
LOCALE_RE = re.compile(r"^([A-Za-z]{2,3})(?:[-_]([A-Za-z]{2}|[0-9]{3}))?$")
AS_OF_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
JD_SOURCE_RE = re.compile(r"^(pasted|file|none|url:\S+)$")
OVERRIDE_RE = re.compile(r"^J[0-9]+=[a-z]+$")


class CliError(Exception):
    """Ends a command with one JSON error object. code 2 = bad arguments or unreadable input."""

    def __init__(self, message, code=EXIT_INPUT, extra=None):
        Exception.__init__(self, message)
        self.message = message
        self.code = code
        self.extra = extra or {}


class _HelpRequested(Exception):
    def __init__(self, text, command=None):
        Exception.__init__(self, text)
        self.text = text
        self.command = command


class Parser(argparse.ArgumentParser):
    """argparse that never prints to stdout and never calls sys.exit on its own."""

    def error(self, message):
        raise CliError("%s (see `%s -h`)" % (message, self.prog))

    def print_help(self, file=None):
        parts = self.prog.split()
        raise _HelpRequested(self.format_help(), parts[1] if len(parts) > 1 else None)

    def exit(self, status=0, message=None):
        if status:
            raise CliError((message or "bad arguments").strip())
        raise _HelpRequested(message or "")


def hint(text):
    """A human hint on stderr (stdout carries only the JSON object)."""
    try:
        sys.stderr.write("hp.py: %s\n" % text)
    except (OSError, ValueError):
        pass


# ============================================================================================ helpers
def read_text_file(path, what, limit=MAX_TEXT_BYTES):
    """Read a UTF-8 (or UTF-16 with BOM, or Windows-1252) text file. Raises CliError on any problem."""
    if not path:
        raise CliError("%s: no file given" % what)
    p = os.path.abspath(os.path.expanduser(path))
    if not os.path.exists(p):
        raise CliError("%s: no file at %s" % (what, p))
    if os.path.isdir(p):
        raise CliError("%s: %s is a folder, not a file" % (what, p))
    try:
        size = os.path.getsize(p)
        if size > limit:
            raise CliError("%s: the file is %d bytes; the limit is %d" % (what, size, limit))
        with open(p, "rb") as f:
            data = f.read(limit + 1)
    except OSError as e:
        raise CliError("%s: cannot read %s (%s)" % (what, p, e.__class__.__name__))
    return decode_text(data, what)


def decode_text(data, what):
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    elif data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            raise CliError("%s: the file is not readable text" % what)
    if b"\x00" in data:
        raise CliError("%s: the file looks like binary data, not text" % what)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", "replace")


def clean_newlines(text):
    """\\r\\n and \\r -> \\n; non-empty text ends with exactly one newline."""
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    return (t.rstrip("\n") + "\n") if t.strip() else ""


def read_jd(path):
    """The job posting as text. A .docx/.pdf/.rtf posting is read through hp.ingest."""
    if path == "-":
        data = sys.stdin.buffer.read(MAX_TEXT_BYTES + 1) if hasattr(sys.stdin, "buffer") else \
            sys.stdin.read(MAX_TEXT_BYTES + 1).encode("utf-8")
        if len(data) > MAX_TEXT_BYTES:
            raise CliError("job posting: more than %d bytes on stdin" % MAX_TEXT_BYTES)
        return clean_newlines(decode_text(data, "job posting"))
    ext = os.path.splitext(path)[1].lower()
    if ext in DOC_FILE_EXTS and ext not in (".html", ".htm"):
        from hp.ingest import ingest_file, needs_transcription
        p = os.path.abspath(os.path.expanduser(path))
        if not os.path.isfile(p):
            raise CliError("job posting: no file at %s" % p)
        doc = ingest_file(p)
        lines = [h.get("text") or "" for h in doc.get("header_footer") or []]
        lines += [ln.get("text") or "" for ln in doc.get("lines") or []]
        text = "\n".join(x for x in lines if x.strip())
        if not text.strip() or needs_transcription(doc):
            raise CliError("job posting: no readable text in %s; paste the posting as text instead" % p)
        return clean_newlines(text)
    return clean_newlines(read_text_file(path, "job posting"))


def write_raw(path, text):
    """Write text exactly (no newline added), creating folders."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def copy_exact(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src, dst)


def make_readable(path):
    """Deliverables are written via mkstemp (mode 0600); make them 0644 so other apps can open them."""
    try:
        os.chmod(path, 0o644)
    except OSError:
        pass


def load_json(path, what, required=True):
    from hp.util import read_json
    if not os.path.isfile(path):
        if required:
            raise CliError("%s is missing (%s)" % (what, path))
        return None
    try:
        return read_json(path)
    except (OSError, ValueError) as e:
        raise CliError("%s is not valid JSON (%s: %s)" % (what, e.__class__.__name__, str(e)[:160]))


def get_run(arg):
    from hp import run as hprun
    try:
        run = hprun.resolve_run(arg)
        return run, hprun.load_state(run)
    except hprun.RunError as e:
        raise CliError(str(e))


def norm_locale(value):
    m = LOCALE_RE.match((value or "").strip())
    if not m:
        raise CliError("--locale must be a code like en-US, en-GB or de-DE; got %r" % value)
    lang, region = m.group(1).lower(), (m.group(2) or "").upper()
    return lang + ("-" + region if region else "")


def check_as_of(value):
    if not AS_OF_RE.match(value or ""):
        raise CliError("--as-of must be YYYY-MM-DD; got %r" % value)
    try:
        date(int(value[:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        raise CliError("--as-of is not a real date: %r" % value)
    return value


def screening_summary(result):
    """The compact screening block printed by init, screen and recheck."""
    from hp.report_build import screening_side
    from hp.screen import required_line
    side = screening_side(result)
    kw = (result.get("keywords") or {})
    km = (result.get("scores") or {}).get("keyword_match") or {}
    line = required_line(result) or (km.get("band") or "")
    return {
        "overall": side["overall"], "band": side["band"],
        "machine_readability": side["machine_readability"],
        "keyword_match": side["keyword_match"],
        "content_signals": side["content_signals"],
        "required": {"found": side["required"]["found"], "total": side["required"]["total"],
                     "listed_only": side["required"]["listed_only"]},
        "required_line": line,
        "keywords_status": kw.get("status"),
        "top_issues": [{"id": i.get("id"), "severity": i.get("severity"), "title": i.get("title")}
                       for i in (result.get("issues") or [])[:5] if isinstance(i, dict)],
    }


def ledger_summary(ledger):
    from hp.panel.ledger import kinds_summary
    return {"resume_lines": len(ledger.get("resume_lines") or []), "jd_items": len(ledger.get("jd_items") or []),
            "kinds": kinds_summary(ledger)}


def screen_run(run, state, doc, jd_text, terms=None):
    """Run the before screening for a run and write screening.json, screening.md and brief.json."""
    from hp.screen import LexiconError, make_brief, render_screening_md, run_screening
    from hp.util import write_json, write_text
    from hp import run as hprun
    p = hprun.paths(run)
    url = state.get("jd_source")[4:] if str(state.get("jd_source") or "").startswith("url:") else None
    try:
        result = run_screening(doc, jd_text, stage=state.get("candidate_stage") or "student",
                               as_of=state.get("as_of"), locale=state.get("locale") or "en-US", jd_url=url,
                               jd_title=state.get("role") or None, terms=terms)
    except LexiconError as e:
        raise CliError("the keyword dictionary in scripts/hp/data is damaged or missing: %s" % e)
    result["extraction"]["ats_view_file"] = "inputs/ats_view.txt"
    write_json(p["screening"], result)
    write_text(p["screening_md"], render_screening_md(result))
    write_json(p["brief"], make_brief(result))
    return result


def resume_flags(doc, result, stage):
    """thin, long and non_english (ARCHITECTURE.md section 14 and references/edge-cases.md)."""
    words = int(doc.get("words") or 0)
    entries = [e for e in ((result.get("experience") or {}).get("entries") or [])
               if isinstance(e, dict) and e.get("section") != "education"]
    has_text = bool(doc.get("lines"))
    pages = doc.get("pages") if isinstance(doc.get("pages"), int) and doc.get("pages") > 0 else None
    if pages is None:
        pages = int(math.ceil(words / 500.0)) if words else 0     # rough: about 500 words per resume page
    limit = 3 if stage == "experienced" else 2
    return {"thin": has_text and (words < 150 or len(entries) < 2),
            "long": pages > limit,
            "non_english": has_text and result.get("language") not in ("en", "und")}


def load_resume_doc(run, state):
    """Re-read the run's resume (original file, transcript or pasted text) into a Document."""
    from hp.ingest import apply_resume_text, ingest_file, ingest_text
    from hp import run as hprun
    p = hprun.paths(run)
    src = state.get("resume_input") or {}
    f = os.path.join(p["work"], src["file"]) if src.get("file") else None
    t = os.path.join(p["work"], src["text"]) if src.get("text") else None
    if f and not os.path.isfile(f):
        raise CliError("the run's copy of the resume is missing (%s)" % f)
    text = read_text_file(t, "resume text") if t else None
    if f and text is not None:
        return apply_resume_text(ingest_file(f), text)
    if f:
        return ingest_file(f)
    if text is not None:
        return ingest_text(text)
    raise CliError("state.json does not say where the resume came from; start a new run with init")


def read_terms(path):
    """--terms file: a JSON list of {term, aliases, importance, jd_quote} (or {"terms": [...]})."""
    from hp.util import read_json
    p = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(p):
        raise CliError("--terms: no file at %s" % p)
    if os.path.getsize(p) > MAX_TERMS_BYTES:
        raise CliError("--terms: the file is larger than %d bytes" % MAX_TERMS_BYTES)
    try:
        data = read_json(p)
    except (OSError, ValueError) as e:
        raise CliError("--terms: not valid JSON (%s)" % str(e)[:160])
    if isinstance(data, dict) and isinstance(data.get("terms"), list):
        data = data["terms"]
    if not isinstance(data, list):
        raise CliError("--terms: expected a JSON list of {term, aliases, importance, jd_quote}")
    return p, data


def screening_ctx(run, state):
    """What the gate needs to re-run the screening exactly like the before check."""
    from hp import run as hprun
    p = hprun.paths(run)
    terms = None
    if os.path.isfile(p["terms"]):
        try:
            _, terms = read_terms(p["terms"])
        except CliError:
            terms = None
    src = str(state.get("jd_source") or "")
    return {"stage": state.get("candidate_stage") or "student", "as_of": state.get("as_of"),
            "locale": state.get("locale") or "en-US", "jd_url": src[4:] if src.startswith("url:") else None,
            "jd_title": state.get("role") or None, "terms": terms}


def read_jd_md(run):
    from hp import run as hprun
    p = hprun.paths(run)["jd_md"]
    try:
        with open(p, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


# ============================================================================================ commands
def cmd_doctor(args):
    import importlib.util
    import platform
    from hp import __version__
    from hp import run as hprun
    from hp.render import doctor as render_doctor
    env = render_doctor()
    backends = [m for m in ("pdfplumber", "pypdf") if importlib.util.find_spec(m) is not None]
    if platform.system() == "Darwin" and os.path.exists("/usr/bin/osascript"):
        backends.append("pdfkit")
    backends.append("builtin")
    lexicon = "ok"
    try:
        from hp.screen import load_lexicon
        load_lexicon()
    except Exception as e:   # report, never crash: doctor is the first thing a student runs
        lexicon = "error: %s" % str(e)[:200]
    return EXIT_OK, {
        "ok": lexicon == "ok",
        "hp_version": __version__,
        "python": env.get("python"),
        "platform": env.get("platform"),
        "surface": hprun.detect_surface(),
        "outputs_dir": hprun.outputs_dir(),
        "default_base": hprun.default_base(),
        "pdf_engines": env.get("pdf_engines") or [],
        "pdf_text_backends": backends,
        "git_repo": hprun.in_git_repo(os.getcwd()),
        "lexicon": lexicon,
        "script": os.path.abspath(__file__),
    }


def cmd_init(args):
    from hp import run as hprun
    from hp.ingest import (apply_resume_text, doc_to_resume_md, ingest_file, ingest_text, needs_transcription,
                           transcription_reason, write_ats_view)
    from hp.panel.common import PanelError
    from hp.panel.ledger import build_run_ledger
    from hp.util import today_iso, write_text

    # ---- validate every argument before anything is created
    if not args.resume and not args.resume_text:
        raise CliError("init needs --resume PATH or --resume-text PATH")
    if bool(args.jd) == bool(args.no_jd):
        raise CliError("init needs exactly one of --jd PATH, --jd - (stdin) or --no-jd")
    role = (args.role or "").strip()
    if not role:
        raise CliError("--role must name the job you are applying for")
    company = (args.company or "").strip() or None
    locale = norm_locale(args.locale or "en-US")
    as_of = check_as_of(args.as_of) if args.as_of else today_iso()
    if args.as_of is None:
        check_as_of(as_of)
    jd_source = args.jd_source
    if jd_source is not None and not JD_SOURCE_RE.match(jd_source):
        raise CliError("--jd-source must be pasted, file or url:<URL>; got %r" % jd_source)

    resume_path = os.path.abspath(os.path.expanduser(args.resume)) if args.resume else None
    resume_text = read_text_file(args.resume_text, "resume text") if args.resume_text else None
    if resume_text is not None and not resume_text.strip():
        raise CliError("resume text: the file is empty")
    jd_text = "" if args.no_jd else read_jd(args.jd)
    general_review = not jd_text.strip()
    if general_review:
        jd_text = ""
        jd_source = "none"
    elif jd_source is None:
        jd_source = "pasted" if args.jd == "-" else "file"

    # ---- read the resume (never raises on content)
    file_doc = None
    if resume_path:
        if not os.path.exists(resume_path):
            raise CliError("resume: no file at %s" % resume_path)
        if os.path.isdir(resume_path):
            raise CliError("resume: %s is a folder, not a file" % resume_path)
        file_doc = ingest_file(resume_path)
        codes = [e.get("code") for e in file_doc.get("errors") or []]
        if "not_found" in codes or ("unreadable" in codes and not file_doc.get("sha256")):
            raise CliError("resume: cannot read %s" % resume_path)
        if "empty_file" in codes and resume_text is None:
            raise CliError("resume: %s is empty" % resume_path)
        has_text = any((ln.get("text") or "").strip() for ln in (file_doc.get("lines") or []) +
                       (file_doc.get("header_footer") or []))
        if resume_text is None and not has_text and not needs_transcription(file_doc):
            # Nothing was read and there is nothing to transcribe (for example a file over 15 MB).
            detail = "; ".join("%s: %s" % (e.get("code"), e.get("detail") or "") for e in file_doc.get("errors") or [])
            raise CliError("resume: no text could be read from %s (%s). Ask for a .docx, a normal PDF or "
                           "pasted text." % (resume_path, detail or "no text"))
    if file_doc is not None and resume_text is not None:
        doc = apply_resume_text(file_doc, resume_text)
    elif file_doc is not None:
        doc = file_doc
    else:
        doc = ingest_text(resume_text)

    # ---- create the run
    base = hprun.ensure_base(hprun.resolve_base(args.out))
    run = hprun.new_run_dir(base, company, role)
    p = hprun.paths(run)
    resume_input = {"file": None, "text": None}
    if resume_path:
        ext = file_doc.get("format") if file_doc.get("format") in KNOWN_FORMATS else \
            (re.sub(r"[^a-z0-9]", "", os.path.splitext(resume_path)[1].lower())[:5] or "bin")
        if os.path.getsize(resume_path) <= 15 * 1024 * 1024:
            copy_exact(resume_path, os.path.join(p["inputs"], "original." + ext))
            resume_input["file"] = "inputs/original." + ext
        if resume_text is not None:
            copy_exact(os.path.abspath(os.path.expanduser(args.resume_text)), p["transcript"])
            resume_input["text"] = "inputs/transcript.txt"
    else:
        ext = os.path.splitext(args.resume_text)[1].lower()
        ext = ext[1:] if ext in (".txt", ".md") else "txt"
        copy_exact(os.path.abspath(os.path.expanduser(args.resume_text)), os.path.join(p["inputs"], "original." + ext))
        resume_input["text"] = "inputs/original." + ext
    write_text(p["resume_md"], doc_to_resume_md(doc))
    write_ats_view(doc, p["ats_view"])
    write_raw(p["jd_md"], jd_text)

    state = hprun.new_state(as_of, args.stage, args.role_level, locale, "en", role, company, jd_source,
                            general_review, {})
    state["resume_input"] = resume_input
    result = screen_run(run, state, doc, jd_text)
    flags = resume_flags(doc, result, args.stage)
    flags["needs_transcription"] = bool(needs_transcription(doc))
    state["flags"] = flags
    state["language"] = result.get("language") or "und"
    try:
        ledger, _ = build_run_ledger(run, hprun.ledger_target(state))
    except PanelError as e:
        raise CliError(str(e))
    hprun.mark_step(state, "init")
    hprun.mark_step(state, "screen")
    hprun.save_state(run, state)

    reason = transcription_reason(doc)
    detail = ""
    for e in doc.get("errors") or []:
        if e.get("code") == "needs_transcription":
            detail = e.get("detail") or ""
    if flags["needs_transcription"]:
        if reason in ("image_only", "garbled"):
            nxt = ("Transcribe the resume word for word into %s, confirm it with the student, then run init "
                   "again with the same arguments plus --resume-text %s" % (p["transcript"], p["transcript"]))
        else:
            nxt = "Ask the student for a .docx, a normal PDF or pasted text (%s)" % (reason or "unreadable")
    else:
        nxt = "Run the panel (SKILL.md Step 3), validate each review, then synthesize %s --mode <mode>" % run
    kw_status = (result.get("keywords") or {}).get("status")
    out = {
        "ok": True,
        "run": run,
        "resume": {"format": doc.get("format"), "method": doc.get("method"),
                   "lines": len([ln for ln in doc.get("lines") or [] if (ln.get("text") or "").strip()]),
                   "words": int(doc.get("words") or 0), "pages": doc.get("pages"),
                   "needs_transcription": flags["needs_transcription"], "transcription_reason": reason,
                   "transcription_hint": detail.split(":", 1)[1].strip() if ":" in detail else detail,
                   "warnings": [w for w in doc.get("warnings") or []][:12],
                   "errors": [e.get("code") for e in doc.get("errors") or []]},
        "jd": {"chars": len(jd_text.strip()), "too_thin": kw_status == "thin_jd",
               "general_review": general_review, "source": jd_source,
               "title_guess": ((result.get("inputs") or {}).get("job_description") or {}).get("title_guess")},
        "flags": {"thin": flags["thin"], "long": flags["long"], "non_english": flags["non_english"]},
        "screening": screening_summary(result),
        "ledger": ledger_summary(ledger),
        "git_warning": hprun.in_git_repo(base),
        "base": base,
        "next": nxt,
    }
    return EXIT_OK, out


def cmd_ledger(args):
    from hp import run as hprun
    from hp.panel.common import PanelError
    from hp.panel.ledger import apply_overrides, build_run_ledger
    run, state = get_run(args.run)
    p = hprun.paths(run)
    bad = [o for o in args.override if not OVERRIDE_RE.match(o.strip())]
    if bad:
        raise CliError("--override takes J#=kind pairs like J3=must; got %s" % ", ".join(bad))
    ledger = load_json(p["ledger"], "work/inputs/ledger.json")
    try:
        _, log = apply_overrides(ledger, [o.strip() for o in args.override])
    except ValueError as e:
        raise CliError(str(e))
    state["ledger_overrides"] = list(state.get("ledger_overrides") or []) + log
    try:
        new_ledger, _ = build_run_ledger(run, hprun.ledger_target(state), overrides=state["ledger_overrides"])
    except (PanelError, ValueError) as e:
        raise CliError(str(e))
    hprun.save_state(run, state)
    return EXIT_OK, {"ok": True, "run": run, "overrides": log, "all_overrides": state["ledger_overrides"],
                     "ledger": ledger_summary(new_ledger)}


def cmd_screen(args):
    from hp import run as hprun
    from hp.panel.common import PanelError
    from hp.panel.ledger import build_run_ledger
    from hp.util import write_json
    run, state = get_run(args.run)
    p = hprun.paths(run)
    terms = None
    if args.terms:
        src, terms = read_terms(args.terms)
        if os.path.abspath(src) != os.path.abspath(p["terms"]):
            write_json(p["terms"], terms)
    elif os.path.isfile(p["terms"]):
        _, terms = read_terms(p["terms"])
    doc = load_resume_doc(run, state)
    result = screen_run(run, state, doc, read_jd_md(run), terms=terms)
    try:
        ledger, _ = build_run_ledger(run, hprun.ledger_target(state), overrides=state.get("ledger_overrides"))
    except (PanelError, ValueError) as e:
        raise CliError(str(e))
    hprun.mark_step(state, "screen")
    hprun.save_state(run, state)
    term_stats = (result.get("inputs") or {}).get("terms") or {}
    rejected = [w for w in (result.get("extraction") or {}).get("warnings") or []
                if isinstance(w, str) and w.startswith("terms")]
    return EXIT_OK, {"ok": True, "run": run, "terms": term_stats, "term_messages": rejected,
                     "screening": screening_summary(result), "ledger": ledger_summary(ledger)}


def cmd_validate(args):
    from hp.panel.review_check import check_review
    run, _state = get_run(args.run)
    path = args.path
    if not os.path.isabs(path) and os.path.exists(path):
        path = os.path.abspath(path)
    res = check_review(run, path)
    ok = bool(res.get("ok"))
    # Live test 3.4: "ok" alone decides (exit 0 valid, exit 1 invalid). partial_ok only says what synthesize
    # does with a file that stays invalid after the one retry.
    partial = (not ok) and bool(res.get("usable"))
    if ok:
        nxt = "Valid. Go on to the next reviewer."
    elif partial:
        nxt = ("Invalid. Redo this reviewer once, adding only these errors. If it fails again, go on: "
               "synthesize keeps the parts of this review it can use.")
    else:
        nxt = ("Invalid. Redo this reviewer once, adding only these errors. If it fails again, go on without it: "
               "synthesize skips this file.")
    out = {"ok": ok, "reviewer_id": res.get("reviewer_id"),
           "errors": res.get("errors") or [], "warnings": res.get("warnings") or [],
           "repairs": res.get("repairs") or [], "partial_ok": partial, "next": nxt}
    return (EXIT_OK if ok else EXIT_CHECK), out


def cmd_synthesize(args):
    from hp import run as hprun
    from hp.panel.common import PanelError
    from hp.panel.synth import cli_summary, synthesize
    run, state = get_run(args.run)
    merges = None
    if args.merges:
        merges = os.path.abspath(os.path.expanduser(args.merges))
        if not os.path.isfile(merges):
            raise CliError("--merges: no file at %s" % merges)
    try:
        result = synthesize(run, mode=args.mode, merges_path=merges)
    except PanelError as e:
        raise CliError(str(e))
    state["mode"] = args.mode
    hprun.mark_step(state, "synthesize")
    hprun.save_state(run, state)
    out = {"ok": True, "run": run, "mode": args.mode}
    out.update(cli_summary(result))
    out["panel_size"] = result.get("panel_size")
    out["missing_reviewers"] = result.get("missing_reviewers") or []
    out["pinned_integrity"] = result.get("pinned_integrity") or []
    out["synthesis"] = hprun.paths(run)["synthesis"]
    if not result.get("panel_size"):
        out["warnings"] = ["No review file could be used, so the ranking holds only the screening script's "
                           "findings. Run the reviewers again before reporting."]
    return EXIT_OK, out


def _truth(run):
    """Run the truth check on the current files and write truth.json. Returns (truth, resume, ledger, answers)."""
    from hp import run as hprun
    from hp.rewrite import check_truth
    from hp.util import write_json
    p = hprun.paths(run)
    if not os.path.isfile(p["resume_json"]):
        raise CliError("work/rewrite/resume.json is missing; write the rewrite first (SKILL.md Step 6)")
    resume = load_json(p["resume_json"], "work/rewrite/resume.json")
    ledger = load_json(p["ledger"], "work/inputs/ledger.json")
    answers = None
    if os.path.isfile(p["answers"]):
        try:
            answers = load_json(p["answers"], "work/answers.json")
        except CliError:
            answers = []          # unreadable answers: the truth check reports INVALID_INPUT
    truth = check_truth(ledger, answers, resume)
    write_json(p["truth"], truth)
    return truth, resume, ledger, answers


def cmd_truth(args):
    from hp import run as hprun
    run, state = get_run(args.run)
    truth, _resume, _ledger, answers = _truth(run)
    if answers is not None:
        hprun.mark_step(state, "answers")
    if truth.get("passed"):
        hprun.mark_step(state, "truth")
    else:
        state.get("steps", {}).pop("truth", None)
    hprun.save_state(run, state)
    flagged = []
    for w in truth.get("warnings") or []:
        if isinstance(w, dict) and w.get("code") == "NEW_WORDING" and w.get("bullet_id") not in flagged:
            flagged.append(w.get("bullet_id"))
    warnings = truth.get("warnings") or []
    out = {"ok": bool(truth.get("passed")), "run": run, "passed": bool(truth.get("passed")),
           "errors": truth.get("errors") or [], "warnings": warnings[:40],
           "warnings_total": len(warnings), "stats": truth.get("stats") or {},
           "needs_audit": flagged, "truth": hprun.paths(run)["truth"]}
    if not truth.get("passed"):
        hint("the truth check found %d problem(s); fix each claim, never the evidence" % len(out["errors"]))
    return (EXIT_OK if out["passed"] else EXIT_CHECK), out


def cmd_render(args):
    from hp import gate as hpgate
    from hp import run as hprun
    from hp.render import RenderError, render_resume
    from hp.rewrite import check_provenance
    from hp.util import write_json
    run, state = get_run(args.run)
    p = hprun.paths(run)
    truth, resume, _ledger, _answers = _truth(run)
    if not truth.get("passed"):
        state.get("steps", {}).pop("truth", None)
        hprun.save_state(run, state)
        return EXIT_CHECK, {"ok": False, "run": run, "refused": "truth",
                            "message": "The truth check has not passed. Fix the errors, run truth, then render.",
                            "errors": truth.get("errors") or []}
    hprun.mark_step(state, "truth")
    provenance = load_json(p["provenance"], "work/rewrite/provenance.json", required=False)
    prov = check_provenance(resume, provenance, truth)
    if not prov.get("passed"):
        hprun.save_state(run, state)
        return EXIT_CHECK, {"ok": False, "run": run, "refused": "provenance",
                            "message": "The provenance audit does not cover every flagged bullet, or a soften/"
                                       "remove verdict was not applied (references/provenance-audit.md).",
                            "missing": prov.get("missing") or [], "unresolved": prov.get("unresolved") or [],
                            "errors": prov.get("errors") or []}
    if provenance is not None:
        hprun.mark_step(state, "provenance")

    meta = resume.get("meta") if isinstance(resume.get("meta"), dict) else {}
    layout = args.layout or (meta.get("layout") if meta.get("layout") in ("classic", "inline") else None)
    ctx = screening_ctx(run, state)
    jd_text = read_jd_md(run)
    before = load_json(p["screening"], "work/screening/before/screening.json", required=False)
    attempts = []
    info = None
    final = None
    for _attempt in range(2):
        try:
            info = render_resume(resume, run, formats=("docx", "pdf", "md"), pdf_engine=args.pdf_engine,
                                 layout=layout, draft=args.draft)
        except RenderError as e:
            hprun.save_state(run, state)
            raise CliError("render: %s" % e)
        for f in info["files"].values():
            make_readable(f)
        final = hpgate.run_gate(info["files"], info["files"].get("md"), jd_text, ctx, p["after"])
        attempts.append({"layout": info["layout"], "passed": final["passed"], "failures": final["failures"]})
        if final["passed"] or not final["retryable"] or info["layout"] != "classic":
            break
        hint("the gate failed on merged words or reading order with the classic layout; retrying inline")
        layout = "inline"
    record = hpgate.gate_record(attempts, final, info["layout"], before)
    record["files"] = dict((k, os.path.basename(v)) for k, v in sorted(info["files"].items()))
    record["pdf_engine"] = (info.get("pdfEngine") or "").split(":")[0] or None
    record["pdf_skipped"] = bool(info.get("pdfSkipped"))
    write_json(p["gate"], record)

    code = EXIT_OK
    if info.get("overflow"):
        code = EXIT_LONG
    elif not final["passed"]:
        code = EXIT_CHECK
    elif info.get("pdfSkipped"):
        code = EXIT_NO_PDF
    if code != EXIT_LONG:
        hprun.mark_step(state, "render")
        hprun.mark_step(state, "gate")
    else:
        state.get("steps", {}).pop("render", None)
    hprun.save_state(run, state)

    def side(kind):
        c = final["checks"].get(kind) or {}
        if not c.get("checked"):
            return {"checked": False, "reason": c.get("reason")}
        return {"checked": True, "overall": c.get("overall"), "parse_safety": c.get("parse_safety"),
                "parse_band": c.get("parse_band"), "word_recovery": c.get("word_recovery"),
                "order_match": c.get("order_match"), "passed": c.get("passed")}
    out = {
        "ok": code == EXIT_OK,
        "run": run,
        "files": info["files"],
        "pdf_engine": info.get("pdfEngine"),
        "pages": info.get("pages"),
        "target_pages": info.get("targetPages"),
        "layout": info.get("layout"),
        "overflow": info.get("overflow"),
        "pdf_skipped": info.get("pdfSkipped"),
        "warnings": info.get("warnings") or [],
        "gate": {"passed": final["passed"], "retried_inline": len(attempts) > 1, "failures": final["failures"],
                 "docx": side("docx"), "pdf": side("pdf"), "gate_json": p["gate"]},
        "provenance": {"passed": True, "audited": provenance is not None},
    }
    if code == EXIT_LONG:
        hint(info["overflow"])
    elif info.get("pdfSkipped"):
        hint(info["pdfSkipped"])
    return code, out


def cmd_report(args):
    from hp import run as hprun
    from hp.render import RenderError, render_report
    from hp.render import report as report_render
    from hp.report_build import ReportError, build_report, validate_report
    from hp.util import write_json, write_text
    run, state = get_run(args.run)
    p = hprun.paths(run)
    try:
        notes = []
        report = build_report(run, notes=notes)
    except (ReportError, hprun.RunError) as e:
        raise CliError(str(e))
    schema_errors = validate_report(report)
    for e in schema_errors:
        hint("report.json schema: %s" % e)
    write_json(p["report"], report)
    try:
        info = render_report(report, run)
    except RenderError as e:
        raise CliError("report: %s" % e)
    if info.get("pdfSkipped"):
        report["files"].pop("report_pdf", None)
        write_json(p["report"], report)
        write_text(info["files"]["html"], report_render.build_report_html(report, onepage=False))
        write_text(info["files"]["md"], report_render.build_report_md(report))
    for f in info["files"].values():
        make_readable(f)
    hprun.mark_step(state, "report_final" if report["stage"] == "final" else "report_panel")
    hprun.save_state(run, state)

    deliverables = [os.path.join(run, n) for k, n in sorted(report["files"].items())
                    if os.path.isfile(os.path.join(run, n))]
    copied = []
    if args.copy_to:
        dest = os.path.abspath(os.path.expanduser(args.copy_to))
        try:
            os.makedirs(dest, exist_ok=True)
            for f in deliverables:
                target = os.path.join(dest, os.path.basename(f))
                shutil.copyfile(f, target)
                make_readable(target)
                copied.append(target)
        except OSError as e:
            raise CliError("--copy-to: cannot copy into %s (%s)" % (dest, e.__class__.__name__))
    before = (report.get("screening") or {}).get("before") or {}
    req = before.get("required") or {}
    summary = {
        "vote_label": report["verdict_strip"]["vote_label"],
        "screening": "Simulated screening check: %s (%s)" % (before.get("overall"), before.get("band"))
        if before.get("overall") is not None else "Simulated screening check: %s" % before.get("band"),
        "machine_readability": (before.get("machine_readability") or {}).get("band"),
        "required": {"found": req.get("found"), "total": req.get("total"), "listed_only": req.get("listed_only")},
        "pinned": [x["title"] for x in report.get("pinned_integrity") or []],
        "top_weaknesses": [{"title": w["title"], "flagged_count": w["flagged_count"], "status": w["status"]}
                           for w in (report.get("weaknesses") or [])[:3]],
        "mode_note": report.get("mode_note") or "",
        "strong_resume": bool(report.get("strong_resume")),
        "strong_line": report["verdict_strip"].get("strong_line") or "",
        "mixed_line": report["verdict_strip"].get("mixed_line") or "",
        "first_impression": report.get("first_impression"),
        "real_gaps": [x["title"] for x in report.get("real_gaps") or []],
    }
    code = EXIT_NO_PDF if info.get("pdfSkipped") else EXIT_OK
    out = {"ok": code == EXIT_OK, "run": run, "stage": report["stage"], "report_json": p["report"],
           "files": info["files"], "deliverables": deliverables, "pdf_engine": info.get("pdfEngine"),
           "pages": info.get("pages"), "pdf_skipped": info.get("pdfSkipped"), "copied": copied,
           "summary": summary, "notes": notes, "schema_errors": schema_errors}
    if info.get("pdfSkipped"):
        hint(info["pdfSkipped"])
    return code, out


def cmd_status(args):
    from hp import run as hprun
    run, state = get_run(args.run)
    step, command, text = hprun.next_step(run, state)
    script = os.path.abspath(__file__)
    cmd = ("python3 %s %s" % (script, command.replace("RUN", run))) if command else ""
    text = text.replace("RUN", run)
    nxt = ("%s Command: %s" % (text, cmd)) if cmd else text
    steps = state.get("steps") or {}
    return EXIT_OK, {
        "ok": True, "run": run, "role": state.get("role"), "company": state.get("company"),
        "mode": state.get("mode"), "general_review": bool(state.get("general_review")),
        "flags": state.get("flags") or {},
        "steps": steps, "done": [s for s in hprun.STEPS if s in steps],
        "reviews": hprun.review_files(run),
        "next_step": step, "next": nxt, "command": cmd, "script": script,
    }


def cmd_recheck(args):
    from hp import run as hprun
    from hp.ingest import doc_to_resume_md, ingest_file, write_ats_view
    from hp.panel.common import PanelError
    from hp.panel.ledger import build_run_ledger
    from hp.util import read_json, write_json, write_text
    run, state = get_run(args.run)
    p = hprun.paths(run)
    gate = load_json(p["gate"], "work/gate.json (run render first)")
    name = ((gate or {}).get("files") or {}).get("docx")
    docx = os.path.join(run, name) if name else None
    if not docx or not os.path.isfile(docx):
        raise CliError("no generated .docx in %s; run render first" % run)
    target = p["recheck"]
    if os.path.exists(target):        # keep an earlier re-read; never delete it
        n = 1
        while os.path.exists("%s-prev-%d" % (target, n)):
            n += 1
        os.rename(target, "%s-prev-%d" % (target, n))
    os.makedirs(os.path.join(target, "work", "inputs"))
    hprun.ensure_gitignore(target)
    q = hprun.paths(target)
    copy_exact(docx, os.path.join(q["inputs"], "original.docx"))
    doc = ingest_file(os.path.join(q["inputs"], "original.docx"))
    write_text(q["resume_md"], doc_to_resume_md(doc))
    write_ats_view(doc, q["ats_view"])
    jd_text = read_jd_md(run)
    write_raw(q["jd_md"], jd_text)
    if os.path.isfile(p["terms"]):
        copy_exact(p["terms"], q["terms"])
    new = hprun.new_state(state.get("as_of"), state.get("candidate_stage") or "student",
                          state.get("role_level") or "unknown", state.get("locale") or "en-US",
                          state.get("language") or "en", state.get("role") or "", state.get("company"),
                          state.get("jd_source") or "none", bool(state.get("general_review")), {})
    new["resume_input"] = {"file": "inputs/original.docx", "text": None}
    new["recheck_of"] = run
    new["ledger_overrides"] = list(state.get("ledger_overrides") or [])
    terms = read_json(q["terms"]) if os.path.isfile(q["terms"]) else None
    result = screen_run(target, new, doc, jd_text, terms=terms if isinstance(terms, list) else None)
    new["flags"] = resume_flags(doc, result, new["candidate_stage"])
    new["flags"]["needs_transcription"] = False
    try:
        ledger, _ = build_run_ledger(target, hprun.ledger_target(new), overrides=new["ledger_overrides"])
    except (PanelError, ValueError) as e:
        raise CliError(str(e))
    hprun.mark_step(new, "init")
    hprun.mark_step(new, "screen")
    hprun.save_state(target, new)
    state.setdefault("steps", {})["recheck"] = hprun.now_iso()
    hprun.save_state(run, state)
    return EXIT_OK, {
        "ok": True, "run": target, "recheck_of": run,
        "screening": screening_summary(result), "ledger": ledger_summary(ledger),
        "next": "Launch the seven reviewers with %s as RUN (references/panel-parallel.md section 5), validate "
                "each, run synthesize %s --mode parallel, then report %s" % (target, target, run),
    }


# ============================================================================================ parser
def build_parser():
    ap = Parser(prog="hp.py", description="Hiring Panel command line. Every command prints one JSON object on "
                                          "stdout. Exit codes: 0 ok; 1 a check failed; 2 bad arguments or "
                                          "unreadable input; 3 resume longer than its page target; 4 PDF "
                                          "skipped (.docx and .md still written).")
    sub = ap.add_subparsers(dest="command", parser_class=Parser)

    sub.add_parser("doctor", help="Python, surface, outputs folder, PDF engines",
                   description="Report the Python version, surface (Claude Code or claude.ai), the outputs "
                               "folder and the PDF engines. Run it first.")

    s = sub.add_parser("init", help="read the files, run the screening check, number the lines, start the run",
                       description="Start a run: read the resume and posting, run the screening check, number "
                                   "the lines (ledger.json) and write state.json. Give --resume or --resume-text, "
                                   "and exactly one of --jd or --no-jd.")
    s.add_argument("--resume", metavar="PATH", help="the resume file (.pdf, .docx, .txt, .md, .rtf ...)")
    s.add_argument("--resume-text", metavar="PATH",
                   help="a text file with the resume words (pasted text, or a transcript of an image-only file)")
    s.add_argument("--jd", metavar="PATH", help="the job posting as a file; '-' reads it from stdin")
    s.add_argument("--no-jd", action="store_true", help="no job posting: a general review against the role title")
    s.add_argument("--role", metavar="TEXT", help="the job title (required)")
    s.add_argument("--company", metavar="TEXT", help="the employer's name, if known")
    s.add_argument("--jd-source", metavar="SOURCE", help="pasted, file, none or url:<URL> (where the posting came from)")
    s.add_argument("--stage", choices=("student", "early_career", "experienced"), default="student",
                   help="career stage (default student)")
    s.add_argument("--role-level", choices=("intern", "entry", "mid", "senior", "unknown"), default="unknown",
                   help="level of the job (default unknown)")
    s.add_argument("--locale", default="en-US", metavar="CODE", help="country norms, e.g. en-US, en-GB, de-DE "
                                                                     "(default en-US)")
    s.add_argument("--out", metavar="BASE", help="folder that holds run folders (default ./hiring-panel-runs, or "
                                                 "the claude.ai outputs folder)")
    s.add_argument("--as-of", metavar="YYYY-MM-DD", help="today's date for date checks (default: today)")

    s = sub.add_parser("ledger", help="fix a job-posting line's kind (J3=must)",
                       description="Change the kind of posting lines in ledger.json when the classifier got one "
                                   "clearly wrong. Logged in state.json.")
    s.add_argument("run", help="the run folder init printed")
    s.add_argument("--override", nargs="+", required=True, metavar="J#=KIND",
                   help="one or more of J3=must, J4=nice, J5=responsibility, J6=company, J7=logistics, J8=other")

    s = sub.add_parser("screen", help="re-run the screening check, optionally with Claude-extracted terms",
                       description="Re-run the before screening check (and brief.json).")
    s.add_argument("run", help="the run folder init printed")
    s.add_argument("--terms", metavar="PATH", help="terms.json with verbatim quotes from the posting")

    s = sub.add_parser("validate", help="check one review file",
                       description="Check one review file. Exit 0 and ok true: valid. Exit 1 and ok false: "
                                   "invalid; redo that reviewer once with only the listed errors. partial_ok "
                                   "says whether synthesize could still use part of a review that stays invalid. "
                                   "Exit 2: bad arguments.")
    s.add_argument("run", help="the run folder init printed")
    s.add_argument("path", help="the review file, e.g. RUN/work/reviews/recruiter.json")

    s = sub.add_parser("synthesize", help="combine and rank the reviews",
                       description="Combine the review files, rank the weaknesses and write synthesis.json.")
    s.add_argument("run", help="the run folder init printed")
    s.add_argument("--mode", choices=("parallel", "sequential", "lite"), required=True,
                   help="how the panel ran: parallel (separate subagents), sequential or lite (one chat)")
    s.add_argument("--merges", metavar="PATH", help="merges.json listing issues that are true duplicates")

    s = sub.add_parser("truth", help="check the rewrite against the sources",
                       description="Check work/rewrite/resume.json against the resume lines and answers. Exit 1 "
                                   "on errors; fix them and run it again until it passes.")
    s.add_argument("run", help="the run folder init printed")

    s = sub.add_parser("render", help="build the resume files and run the quality gate",
                       description="Build the resume .docx, .pdf and .md, then run the quality gate. Refuses "
                                   "unless truth and the provenance audit passed. Exit 3: longer than the page "
                                   "target; exit 4: PDF skipped.")
    s.add_argument("run", help="the run folder init printed")
    s.add_argument("--pdf-engine", choices=("auto", "chrome", "soffice", "builtin"), default="auto",
                   help="which PDF engine to use (default auto)")
    s.add_argument("--layout", choices=("classic", "inline"), help="classic (dates on the right) or inline")
    s.add_argument("--draft", action="store_true", help="allow open placeholders (a draft, never to send)")

    s = sub.add_parser("report", help="build the report (panel stage or final)",
                       description="Build report.json and Hiring_Panel_Report.pdf, .md and .html. The stage "
                                   "(panel or final) follows from the run.")
    s.add_argument("run", help="the run folder init printed")
    s.add_argument("--copy-to", metavar="DIR", help="also copy the deliverables here (the claude.ai outputs folder)")

    s = sub.add_parser("status", help="which steps are done and what to run next",
                       description="Say which steps are done and what to do next, so a run can resume.")
    s.add_argument("run", help="the run folder init printed")

    s = sub.add_parser("recheck", help="opt-in: set up a fresh re-read of the new resume",
                       description="Opt-in: build RUN/recheck/ from the generated .docx for a fresh panel re-read.")
    s.add_argument("run", help="the run folder init printed")
    return ap


COMMANDS = {"doctor": cmd_doctor, "init": cmd_init, "ledger": cmd_ledger, "screen": cmd_screen,
            "validate": cmd_validate, "synthesize": cmd_synthesize, "truth": cmd_truth, "render": cmd_render,
            "report": cmd_report, "status": cmd_status, "recheck": cmd_recheck}


def emit(stream, obj):
    text = json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
    try:
        stream.buffer.write(text.encode("utf-8"))
        stream.flush()
    except AttributeError:
        stream.write(text)
        stream.flush()


def main(argv=None):
    real_stdout = sys.stdout
    sys.stdout = sys.stderr            # nothing but the final JSON object may reach stdout
    command = None
    try:
        args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
        command = args.command
        if not command:
            raise CliError("give a command: " + ", ".join(sorted(COMMANDS)))
        code, out = COMMANDS[command](args)
        out = dict(out)
        out.setdefault("command", command)
    except _HelpRequested as h:
        # Printed once, inside the JSON object, one line per list item (live test 2.12).
        code, out = EXIT_OK, {"ok": True, "command": h.command or command,
                              "help": h.text.rstrip("\n").split("\n")}
    except CliError as e:
        code = e.code
        out = {"ok": False, "command": command, "error": e.message}
        out.update(e.extra)
        hint(e.message)
    except KeyboardInterrupt:
        code, out = EXIT_INPUT, {"ok": False, "command": command, "error": "interrupted"}
    except Exception as e:    # never a traceback on stdout; the JSON says what failed
        traceback.print_exc(file=sys.stderr)
        code = EXIT_INPUT
        out = {"ok": False, "command": command, "error": "internal error: %s: %s" % (e.__class__.__name__,
                                                                                    str(e)[:300])}
    finally:
        sys.stdout = real_stdout
    emit(real_stdout, out)
    return code


if __name__ == "__main__":
    sys.exit(main())
