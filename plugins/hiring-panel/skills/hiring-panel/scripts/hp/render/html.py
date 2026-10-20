"""Blocks -> resume HTML. Feeds the headless-browser PDF and doubles as a screen preview.

Single column, real text, no images or icons. The right-aligned column of the classic layout is a
flex row; the browser writes it as positioned text, and PDF extractors see the gap as a word break.
Bullets are a literal "•" in a hanging-indent span (same indents as the .docx), never a CSS marker: Chrome
paints list markers as shapes, which text extraction drops.
"""
import html

from .model import THEME

BULLET = "\u2022"


def h(s):
    return html.escape(s or "", quote=True)


def html_runs(runs):
    out = []
    for r in runs:
        s = h(r.get("t"))
        if r.get("b"):
            s = "<strong>%s</strong>" % s
        if r.get("i"):
            s = "<em>%s</em>" % s
        if r.get("hl"):
            s = "<mark>%s</mark>" % s
        out.append(s)
    return "".join(out)


def build_resume_html(blocks, setup):
    t = THEME
    size = "Letter" if setup["paper"] == "letter" else "A4"
    text_w_in = setup["page_w"] / 72.0 - 2 * t["margin_in"]
    css = """
@page { size: %(size)s; margin: %(m)sin; }
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { margin: 0; background: #fff; color: #%(ink)s;
       font-family: Arial, "Liberation Sans", Helvetica, sans-serif; font-size: %(body)spt; line-height: %(line)s;
       -webkit-font-smoothing: antialiased; font-kerning: normal; }
.page { width: %(tw).3fin; margin: 0 auto; }
@media screen {
  body { background: #eceff3; }
  .page { width: auto; max-width: calc(%(tw).3fin + 2 * %(m)sin); background: #fff; padding: %(m)sin;
          margin: 24px auto; box-shadow: 0 1px 3px rgba(16,24,40,.08), 0 8px 24px rgba(16,24,40,.08); }
}
h1 { font-size: %(name)spt; color: #%(accent)s; text-align: center; margin: 0 0 3pt; letter-spacing: .5pt;
     line-height: 1.1; font-weight: 700; }
.headline { text-align: center; color: #%(muted)s; margin: 0 0 1pt; font-size: %(headline)spt; }
.contact { text-align: center; color: #%(muted)s; font-size: %(contact)spt; margin: 0 0 3pt; }
.contact a { color: inherit; text-decoration: none; }
.contact .part { white-space: nowrap; }
.sep { padding: 0 .55em; }
h2 { font-size: %(heading)spt; color: #%(accent)s; text-transform: uppercase; letter-spacing: .6pt; font-weight: 700;
     border-bottom: .75pt solid #%(rule)s; padding-bottom: 1pt; margin: %(hb)spt 0 %(ha)spt;
     line-height: %(line)s; break-after: avoid; page-break-after: avoid; }
.row { display: flex; justify-content: space-between; gap: 12pt; break-after: avoid; page-break-after: avoid; }
.row.first { margin-top: %(eb)spt; }
h2 + .row.first { margin-top: 0; }
.row .l { min-width: 0; }
.row .r { white-space: nowrap; text-align: right; }
ul { margin: 0; padding: 0; list-style: none; }
li { margin: 0 0 %(ba)spt; padding-left: %(bi)spt; text-indent: -%(bh)spt; }
li .bm { display: inline-block; width: %(bh)spt; text-indent: 0; color: #%(ink)s; }
p { margin: 0 0 %(ba)spt; }
mark { background: #fff3a3; }
""" % {"size": size, "m": t["margin_in"], "ink": t["ink"], "body": t["body_pt"], "line": t["line"],
       "tw": text_w_in, "name": t["name_pt"], "accent": t["accent"], "muted": t["muted"],
       "headline": t["headline_pt"], "contact": t["contact_pt"], "heading": t["heading_pt"], "rule": t["rule"],
       "hb": t["heading_before_pt"], "ha": t["heading_after_pt"], "eb": t["entry_before_pt"],
       "bi": t["bullet_indent_pt"], "bh": t["bullet_hanging_pt"], "ba": t["bullet_after_pt"]}
    name = blocks[0]["text"] if blocks and blocks[0].get("k") == "name" else "Resume"
    word = "CV" if setup.get("word", "").lower() == "cv" else "Resume"
    out = ['<!doctype html><html lang="%s"><head><meta charset="utf-8">' % h(setup.get("lang") or "en-US"),
           '<meta name="viewport" content="width=device-width, initial-scale=1">',
           "<title>%s %s</title><style>%s</style></head><body><main class=\"page\">" % (h(name), word, css)]
    in_ul = False
    for b in blocks:
        k = b["k"]
        if k != "bullet" and in_ul:
            out.append("</ul>")
            in_ul = False
        if k == "name":
            out.append("<h1>%s</h1>" % h(b["text"]))
        elif k == "headline":
            out.append('<p class="headline">%s</p>' % h(b["text"]))
        elif k == "contact":
            segs = []
            for part in b["parts"]:
                if part.get("url"):
                    segs.append('<span class="part"><a href="%s">%s</a></span>' % (h(part["url"]), h(part["t"])))
                else:
                    segs.append('<span class="part">%s</span>' % h(part["t"]))
            out.append('<p class="contact">%s</p>' % '<span class="sep">|</span>'.join(segs))
        elif k == "h":
            out.append("<h2>%s</h2>" % h(b["text"]))
        elif k == "row":
            right = ('<span class="r">%s</span>' % h(b["right"])) if b.get("right") else ""
            out.append('<div class="row%s"><span class="l">%s</span>%s</div>'
                       % (" first" if b.get("first") else "", html_runs(b["left"]), right))
        elif k == "bullet":
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            # A real bullet character, not a CSS list marker: Chrome draws markers as shapes, so text
            # extraction (and parsing software) would lose them and read wrapped lines as new entries.
            out.append('<li><span class="bm">%s</span>%s</li>' % (BULLET, html_runs(b["runs"])))
        elif k == "para":
            out.append("<p>%s</p>" % html_runs(b["runs"]))
    if in_ul:
        out.append("</ul>")
    out.append("</main></body></html>")
    return "\n".join(out) + "\n"
