"""PDF engines: headless Chrome/Edge/Brave, LibreOffice (soffice), plus PDF file helpers.

Ladder (first that works wins): chrome -> soffice -> builtin -> skip. Engines run locally as
subprocesses with a throwaway profile; nothing here touches the network. Every produced file is
checked to start with %PDF- and to be larger than 500 bytes (Edge can exit 0 without writing).

Environment overrides (for power users and tests): HP_BROWSER=/path/to/chrome adds a browser first;
HP_SOFFICE=/path/to/soffice adds a LibreOffice binary first; HP_PDF_ENGINES="builtin" (comma list)
limits the engines the auto ladder may try.
"""
import os
import platform
import re
import shutil
import subprocess
import tempfile
import zlib

BROWSER_APPS = ("Google Chrome", "Microsoft Edge", "Brave Browser", "Chromium", "Google Chrome Canary")


def browser_candidates():
    c = []
    if os.environ.get("HP_BROWSER"):
        c.append(os.environ["HP_BROWSER"])
    sysname = platform.system()
    if sysname == "Darwin":
        for root in ("/Applications", os.path.expanduser("~/Applications")):
            for app in BROWSER_APPS:
                c.append("%s/%s.app/Contents/MacOS/%s" % (root, app, app))
    elif sysname == "Windows":
        bases = [os.environ.get(v) for v in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")]
        rels = [r"Google\Chrome\Application\chrome.exe", r"Microsoft\Edge\Application\msedge.exe",
                r"BraveSoftware\Brave-Browser\Application\brave.exe", r"Chromium\Application\chrome.exe"]
        for rel in rels:
            for base in bases:
                if base:
                    c.append(os.path.join(base, rel))
    for exe in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge",
                "microsoft-edge-stable", "brave-browser", "msedge", "chrome"):
        p = shutil.which(exe)
        if p:
            c.append(p)
    seen, out = set(), []
    for p in c:
        if p and p not in seen and os.path.isfile(p):
            seen.add(p)
            out.append(p)
    return out


def soffice_candidates():
    c = [os.environ.get("HP_SOFFICE"), shutil.which("soffice"), shutil.which("libreoffice"),
         "/Applications/LibreOffice.app/Contents/MacOS/soffice", "/usr/bin/soffice", "/opt/libreoffice/program/soffice"]
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if base:
            c.append(os.path.join(base, "LibreOffice", "program", "soffice.exe"))
    seen, out = set(), []
    for p in c:
        if p and p not in seen and os.path.isfile(p):
            seen.add(p)
            out.append(p)
    return out


def allowed_engines():
    raw = os.environ.get("HP_PDF_ENGINES")
    if not raw:
        return None
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def is_pdf(path):
    try:
        with open(path, "rb") as f:
            return f.read(5) == b"%PDF-" and os.path.getsize(path) > 500
    except OSError:
        return False


def _file_url(path):
    p = os.path.abspath(path).replace("\\", "/")
    if not p.startswith("/"):
        p = "/" + p
    return "file://" + p


def chrome_pdf(html_path, pdf_path, log):
    """Print an HTML file to PDF with the first browser that works. Returns 'chrome:<binary>' or None."""
    for exe in browser_candidates():
        profile = tempfile.mkdtemp(prefix="hp-chrome-")
        args = [exe, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                "--disable-extensions", "--disable-background-networking", "--disable-sync",
                "--disable-component-update", "--disable-default-apps", "--no-pings",
                "--user-data-dir=" + profile, "--no-pdf-header-footer", "--print-to-pdf-no-header",
                "--print-to-pdf=" + os.path.abspath(pdf_path), _file_url(html_path)]
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            args.insert(1, "--no-sandbox")
        try:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)
            subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90)
        except (OSError, subprocess.SubprocessError) as e:
            log.append("chrome: %s failed (%s)" % (os.path.basename(exe), e.__class__.__name__))
            continue
        finally:
            shutil.rmtree(profile, ignore_errors=True)
        if is_pdf(pdf_path):
            scrub_pdf_creator(pdf_path)
            return "chrome:" + os.path.basename(exe)
        log.append("chrome: %s produced no PDF" % os.path.basename(exe))
    return None


def soffice_pdf(docx_path, pdf_path, log):
    """Convert the .docx with LibreOffice so Word and PDF match. Returns 'soffice' or None."""
    for exe in soffice_candidates():
        outdir = tempfile.mkdtemp(prefix="hp-soffice-")
        try:
            env = dict(os.environ, SAL_USE_VCLPLUGIN="svp")
            profile = _file_url(os.path.join(outdir, "profile"))
            subprocess.run([exe, "-env:UserInstallation=" + profile, "--headless", "--norestore",
                            "--convert-to", "pdf", "--outdir", outdir, os.path.abspath(docx_path)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120, env=env)
            produced = os.path.join(outdir, os.path.splitext(os.path.basename(docx_path))[0] + ".pdf")
            if is_pdf(produced):
                shutil.move(produced, pdf_path)
                return "soffice"
            log.append("soffice: no PDF produced")
        except (OSError, subprocess.SubprocessError) as e:
            log.append("soffice: %s" % e.__class__.__name__)
        finally:
            shutil.rmtree(outdir, ignore_errors=True)
    return None


def scrub_pdf_creator(path):
    """Blank the browser user agent Chrome writes into /Creator. Same byte length, so the xref stays valid."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return False

    def blank(m):
        return m.group(1) + b"(" + b" " * (len(m.group(2)) - 2) + b")"
    new = re.sub(rb"(/Creator\s*)(\((?:\\.|[^\\)])*\))", blank, data, count=1)
    if new != data and len(new) == len(data):
        with open(path, "wb") as f:
            f.write(new)
        return True
    return False


def _inflated(data, limit=20 * 1024 * 1024):
    blobs = []
    for sm in re.finditer(rb"stream\r?\n", data):
        d = zlib.decompressobj()
        try:
            chunk = d.decompress(data[sm.end():sm.end() + limit], limit)
        except zlib.error:
            continue
        if chunk:
            blobs.append(chunk)
    return b"\n".join(blobs)


def pdf_page_count(path):
    """Count /Type /Page objects (also inside compressed object streams); fall back to /Count."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    pat = rb"/Type\s*/Page(?![a-zA-Z])"
    n = len(re.findall(pat, data))
    if not n:
        n = len(re.findall(pat, _inflated(data)))
    if n:
        return n
    counts = [int(m) for m in re.findall(rb"/Count\s+(\d+)", data)]
    return max(counts) if counts else None


def engines_available():
    """What this machine can use, in ladder order (for doctor)."""
    out = []
    for b in browser_candidates():
        out.append({"engine": "chrome", "path": b})
    for s in soffice_candidates():
        out.append({"engine": "soffice", "path": s})
    out.append({"engine": "builtin", "path": None})
    return out
