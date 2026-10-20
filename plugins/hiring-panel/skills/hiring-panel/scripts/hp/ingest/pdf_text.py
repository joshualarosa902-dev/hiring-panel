"""PDF text extraction ladder (ATS spec 4) and the pdfplumber-only column check (ATS spec 5).

Order: pdfplumber -> pypdf -> macOS PDFKit (osascript -l JavaScript; the file path is passed as an
argument, never interpolated into the script; 20 s timeout) -> built-in Tj/TJ reader -> none.
A backend is skipped when it is not installed or fails; its result is accepted when it yields at least
MIN_CHARS non-space characters that are not garbled, otherwise the ladder keeps going and finally keeps
the best result it saw. HP_PDF_BACKENDS (comma list, e.g. "builtin") restricts the ladder for tests.
"""
import json
import math
import os
import subprocess
import sys

from hp.ingest.limits import PDFKIT_TIMEOUT_S, MAX_PDF_PAGES
from hp.ingest.normalize import is_garbled

LADDER = ("pdfplumber", "pypdf", "pdfkit", "builtin")
MIN_CHARS = 20
OSASCRIPT = "/usr/bin/osascript"

# JavaScript for Automation. argv[0] = absolute file path, argv[1] = max pages. Output is pure-ASCII JSON.
PDFKIT_JXA = r"""
ObjC.import('Foundation');
ObjC.import('PDFKit');
function enc(o) {
  return JSON.stringify(o).replace(/[\u007f-\uffff]/g, function (c) {
    return "\\u" + ("0000" + c.charCodeAt(0).toString(16)).slice(-4);
  });
}
function run(argv) {
  var out = {ok: false, pages: 0, locked: false, text: []};
  try {
    var url = $.NSURL.fileURLWithPath(argv[0]);
    var doc = $.PDFDocument.alloc.initWithURL(url);
    if (!doc || doc.isNil()) { out.error = "open"; return enc(out); }
    if (doc.isLocked) {
      if (!doc.unlockWithPassword("")) { out.locked = true; return enc(out); }
    }
    var n = parseInt(doc.pageCount, 10);
    var maxPages = parseInt(argv[1], 10) || 60;
    out.pages = n;
    for (var i = 0; i < n && i < maxPages; i++) {
      var page = doc.pageAtIndex(i);
      var s = page.string;
      out.text.push((s && !s.isNil()) ? s.js : "");
    }
    out.ok = true;
  } catch (e) {
    out.error = String(e);
  }
  return enc(out);
}
"""


def find_gutter(words, page_width, strip=2.0, min_gutter=12.0, row_height=3.0):
    """ATS spec 5 column check on one page of pdfplumber words ({x0, x1, top}).

    Look at 2-pt vertical strips between 25% and 75% of the page width. A gutter is a run of strips at
    least 12 pt wide that fewer than 5% of text rows (3-pt row buckets) cross, while at least 40% of
    rows have words on both sides.
    """
    try:
        width = float(page_width)
    except (TypeError, ValueError):
        return False
    if width <= 0 or not words:
        return False
    rows = {}
    for w in words:
        try:
            x0, x1, top = float(w["x0"]), float(w["x1"]), float(w["top"])
        except (KeyError, TypeError, ValueError):
            continue
        rows.setdefault(int(top // row_height), []).append((x0, x1))
    nrows = len(rows)
    if nrows < 5:
        return False
    need = int(math.ceil(min_gutter / strip))
    run = 0
    x = 0.25 * width
    while x + strip <= 0.75 * width + 1e-9:
        s0, s1 = x, x + strip
        cross = 0
        both = 0
        for spans in rows.values():
            if any(a < s1 and b > s0 for a, b in spans):
                cross += 1
                continue
            if any(b <= s0 for a, b in spans) and any(a >= s1 for a, b in spans):
                both += 1
        if cross < 0.05 * nrows and both >= 0.4 * nrows:
            run += 1
            if run >= need:
                return True
        else:
            run = 0
        x += strip
    return False


def _pdfplumber(path, facts, max_pages):
    try:
        import pdfplumber  # optional
    except Exception:
        return None
    res = {"method": "pdfplumber", "pages": [], "page_count": None, "gutter_pages": [],
           "pdf_check": "unavailable"}
    try:
        checked = False
        with pdfplumber.open(path) as pdf:
            res["page_count"] = len(pdf.pages)
            for i, page in enumerate(pdf.pages):
                if i >= max_pages:
                    break
                res["pages"].append(page.extract_text() or "")
                try:
                    words = page.extract_words() or []
                    if find_gutter(words, page.width):
                        res["gutter_pages"].append(i + 1)
                    checked = True
                except Exception:
                    pass
        res["pdf_check"] = "performed" if checked else "unavailable"
    except Exception as e:
        return {"method": "pdfplumber", "error": type(e).__name__}
    return res


def _pypdf(path, facts, max_pages):
    try:
        import pypdf  # optional
    except Exception:
        return None
    try:
        reader = pypdf.PdfReader(path, strict=False)
        if reader.is_encrypted:
            try:
                if not reader.decrypt(""):
                    return {"method": "pypdf", "error": "locked", "locked": True}
            except Exception:
                return {"method": "pypdf", "error": "locked", "locked": True}
        n = len(reader.pages)
        pages = []
        for i in range(min(n, max_pages)):
            pages.append(reader.pages[i].extract_text() or "")
        return {"method": "pypdf", "pages": pages, "page_count": n}
    except Exception as e:
        return {"method": "pypdf", "error": type(e).__name__}


def pdfkit_available():
    return sys.platform == "darwin" and os.path.exists(OSASCRIPT)


def _pdfkit(path, facts, max_pages):
    if not pdfkit_available():
        return None
    try:
        proc = subprocess.run([OSASCRIPT, "-l", "JavaScript", "-e", PDFKIT_JXA, os.path.abspath(path), str(max_pages)],
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=PDFKIT_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return {"method": "pdfkit", "error": "timeout after %d s" % PDFKIT_TIMEOUT_S}
    except (OSError, ValueError):
        return None
    try:
        obj = json.loads(proc.stdout.decode("utf-8", "replace").strip() or "{}")
    except ValueError:
        return {"method": "pdfkit", "error": "unreadable output"}
    if not isinstance(obj, dict):
        return {"method": "pdfkit", "error": "unreadable output"}
    if obj.get("locked"):
        return {"method": "pdfkit", "error": "locked", "locked": True}
    if not obj.get("ok"):
        return {"method": "pdfkit", "error": str(obj.get("error") or "failed")[:80]}
    try:
        count = int(obj.get("pages") or 0)
    except (TypeError, ValueError):
        count = None
    pages = [t if isinstance(t, str) else "" for t in (obj.get("text") or [])]
    return {"method": "pdfkit", "pages": pages, "page_count": count}


def _builtin(path, facts, max_pages):
    pages = ["\n".join(lines) for lines in (facts.get("builtin_pages") or [])[:max_pages]]
    return {"method": "builtin-pdf", "pages": pages, "page_count": facts.get("pages")}


BACKENDS = {"pdfplumber": _pdfplumber, "pypdf": _pypdf, "pdfkit": _pdfkit, "builtin": _builtin}


def ladder_order(backends=None):
    if backends:
        return [b for b in backends if b in BACKENDS]
    env = os.environ.get("HP_PDF_BACKENDS", "").strip()
    if env:
        chosen = [b.strip() for b in env.split(",") if b.strip() in BACKENDS]
        if chosen:
            return chosen
    return list(LADDER)


def _chars(pages):
    return sum(len("".join(p.split())) for p in pages)


def extract_pdf_text(path, facts, backends=None, max_pages=MAX_PDF_PAGES):
    """Run the ladder. Returns {"method", "pages": [str], "page_count", "pdf_check", "gutter_pages",
    "warnings", "locked"}; method is "none" when no backend produced text."""
    chosen = None
    candidates = []
    out = {"method": "none", "pages": [], "page_count": None, "pdf_check": "unavailable",
           "gutter_pages": [], "warnings": [], "locked": False}
    for name in ladder_order(backends):
        try:
            res = BACKENDS[name](path, facts, max_pages)
        except Exception as e:  # a backend must never take ingest down
            res = {"method": name, "error": type(e).__name__}
        if res is None:
            continue
        if res.get("pdf_check") == "performed":
            out["pdf_check"] = "performed"
            out["gutter_pages"] = list(res.get("gutter_pages") or [])
        if res.get("error"):
            if res.get("locked"):
                out["locked"] = True
            out["warnings"].append("%s could not read the PDF (%s)" % (res.get("method", name), res["error"]))
            continue
        pages = [p if isinstance(p, str) else "" for p in res.get("pages") or []]
        res["pages"] = pages
        n = _chars(pages)
        garbled = is_garbled("\n".join(pages)) if n else False
        candidates.append((res, n, garbled))
        if n >= MIN_CHARS and not garbled:
            chosen = res
            break
    if chosen is None and candidates:
        clean = [c for c in candidates if c[1] > 0 and not c[2]]
        dirty = [c for c in candidates if c[1] > 0]
        if clean:
            chosen = max(clean, key=lambda c: c[1])[0]
        elif dirty:
            chosen = dirty[0][0]
    if chosen is not None:
        out["method"] = chosen["method"]
        out["pages"] = chosen["pages"]
        out["page_count"] = chosen.get("page_count")
    if out["page_count"] is None:
        for res, _n, _g in candidates:
            if res.get("page_count"):
                out["page_count"] = res["page_count"]
                break
    return out
