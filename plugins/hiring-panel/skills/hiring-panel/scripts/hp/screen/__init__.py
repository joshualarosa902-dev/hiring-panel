"""Simulated screening check (ARCHITECTURE 6; ATS spec sections 6-17).

    from hp.screen import run_screening, render_screening_md, make_brief, load_lexicon
    result = run_screening(doc, jd_text, stage="student", as_of="2026-10-20", locale="en-US",
                           jd_url=None, jd_title=None, terms=None, data_dir=None)
    md = render_screening_md(result)     # student-facing, contact masked, "simulated" wording
    brief = make_brief(result)           # compact brief for reviewer subagents

Standard library only. Deterministic. Never called an "ATS score".
"""
from .core import run_screening
from .lexicon import LexiconError, load_lexicon
from .render import make_brief, render_screening_md, required_line

__all__ = ["run_screening", "render_screening_md", "make_brief", "load_lexicon", "LexiconError",
           "required_line"]
