"""render_resume: resume.json -> First_Last_Resume.{docx,pdf,md} (+ optional .html).

resume.json is the source of truth; every format is rendered from the same block list. The PDF
ladder is chrome -> soffice -> builtin -> skip. The page count comes from the real PDF when there is
one, otherwise from the builtin layout estimate (Helvetica = Arial metrics).
"""
import os
import shutil
import tempfile

from .. import util
from .model import THEME, RenderError, compile_resume, file_stem
from .docx import write_docx
from .html import build_resume_html
from .markdown import build_resume_md
from .pdf_builtin import PdfLayout, Unencodable, write_pdf_bytes
from . import pdf_engines

VALID_FORMATS = ("docx", "pdf", "md", "html")
SKIP_MESSAGE = ("No PDF engine worked on this computer. Open %s in Word, Google Docs or Pages and use "
                "File > Save As (or Download) > PDF.")


def _layout_for(blocks, setup):
    lay = PdfLayout(setup["page_w"], setup["page_h"], THEME["margin_in"] * 72, THEME["line"])
    return lay.place_resume(blocks, THEME)


def _engine_order(pdf_engine):
    if pdf_engine and pdf_engine != "auto":
        return [pdf_engine]
    order = ["chrome", "soffice", "builtin"]
    allowed = pdf_engines.allowed_engines()
    if allowed:
        order = [e for e in order if e in allowed]
    return order


def render_resume(resume, out_dir, formats=("docx", "pdf", "md"), pdf_engine="auto", layout=None, draft=False):
    """Render a resume. Returns {files, pdfEngine, pages, warnings, overflow, pdfSkipped, layout, ...}.

    Raises RenderError for input that cannot be rendered (missing name, open placeholder without
    textIfUnknown, '{{' left in a final file, unknown format or engine).
    """
    if isinstance(formats, str):
        formats = [f.strip() for f in formats.split(",")]
    formats = [f for f in (formats or []) if f]
    bad = [f for f in formats if f not in VALID_FORMATS]
    if bad:
        raise RenderError("unknown format(s): %s" % ", ".join(bad))
    if pdf_engine not in ("auto", "chrome", "soffice", "builtin", None):
        raise RenderError("unknown pdf engine: %s" % pdf_engine)
    blocks, warnings, setup = compile_resume(resume, draft=draft, layout=layout)
    stem = file_stem(resume, draft=draft)
    os.makedirs(out_dir, exist_ok=True)
    info = {"files": {}, "pdfEngine": None, "pages": None, "warnings": warnings, "overflow": None,
            "pdfSkipped": None, "layout": setup["layout"], "paper": setup["paper"],
            "targetPages": setup["target_pages"], "estimate": None, "log": []}

    try:
        est = _layout_for(blocks, setup)
        pages_est, fill = est.fill()
        info["estimate"] = {"pages": pages_est, "lastPageFill": round(fill, 2)}
    except Unencodable:
        info["estimate"] = None

    docx_path = os.path.join(out_dir, stem + ".docx")
    if "docx" in formats:
        write_docx(blocks, setup, docx_path)
        info["files"]["docx"] = docx_path
    if "md" in formats:
        p = os.path.join(out_dir, stem + ".md")
        util.write_text(p, build_resume_md(blocks))
        info["files"]["md"] = p
    html_text = build_resume_html(blocks, setup)
    if "html" in formats:
        p = os.path.join(out_dir, stem + ".html")
        util.write_text(p, html_text)
        info["files"]["html"] = p

    if "pdf" in formats:
        pdf_path = os.path.join(out_dir, stem + ".pdf")
        tmp = tempfile.mkdtemp(prefix="hp-render-")
        try:
            engine = None
            for eng in _engine_order(pdf_engine):
                if eng == "chrome":
                    html_path = os.path.join(tmp, stem + ".html")
                    util.write_text(html_path, html_text)
                    engine = pdf_engines.chrome_pdf(html_path, pdf_path, info["log"])
                elif eng == "soffice":
                    src = docx_path if os.path.exists(docx_path) and "docx" in formats else \
                        write_docx(blocks, setup, os.path.join(tmp, stem + ".docx"))
                    engine = pdf_engines.soffice_pdf(src, pdf_path, info["log"])
                elif eng == "builtin":
                    try:
                        data = write_pdf_bytes(_layout_for(blocks, setup), blocks[0]["text"] + " Resume",
                                               blocks[0]["text"], setup["lang"])
                        util._atomic_write_bytes(pdf_path, data)
                        engine = "builtin"
                    except Unencodable as e:
                        info["log"].append("builtin: the character %r is outside Western European text; "
                                           "this engine cannot show it" % str(e))
                if engine:
                    break
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if engine:
            info["files"]["pdf"] = pdf_path
            info["pdfEngine"] = engine
            info["pages"] = pdf_engines.pdf_page_count(pdf_path)
        else:
            if os.path.exists(pdf_path):
                try:
                    os.remove(pdf_path)   # never leave a stale PDF from an earlier run
                except OSError:
                    pass
            info["pdfSkipped"] = SKIP_MESSAGE % (stem + ".docx")
    pages = info["pages"] or (info["estimate"] or {}).get("pages")
    if info["pages"] is None and pages:
        info["pages"] = pages
    target = setup["target_pages"]
    if target and pages and pages > target:
        info["overflow"] = ("The resume runs %d pages; the target is %d. Tighten or cut the weakest bullets "
                            "(list every cut in meta.cuts) and render again." % (pages, target))
    return info
