"""Rendering for Hiring Panel (standard library only).

    from hp.render import render_resume, render_report, doctor
    info = render_resume(resume, out_dir, formats=("docx", "pdf", "md"), pdf_engine="auto", layout=None, draft=False)
    info = render_report(report, out_dir, pdf_engine="auto")   # Hiring_Panel_Report.{pdf,md,html}
    env = doctor()

Both render functions raise RenderError (a ValueError) for input they cannot render; everything
else (no PDF engine, a long resume) is reported in the returned dict.
"""
import platform
import sys

from .model import RenderError
from .resume import render_resume
from .report import render_report
from . import pdf_engines

__all__ = ["render_resume", "render_report", "doctor", "RenderError"]


def doctor():
    """Which PDF engines this machine has, in ladder order (chrome -> soffice -> builtin)."""
    engines = pdf_engines.engines_available()
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "pdf_engines": [e["engine"] if not e["path"] else "%s:%s" % (e["engine"], e["path"]) for e in engines],
        "browsers": pdf_engines.browser_candidates(),
        "soffice": pdf_engines.soffice_candidates(),
        "builtin": True,
    }
