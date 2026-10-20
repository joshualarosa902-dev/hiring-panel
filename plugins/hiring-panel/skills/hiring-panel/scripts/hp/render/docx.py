"""Blocks -> .docx (WordprocessingML written by hand and zipped with the standard library).

ATS-safe by construction: one column, no tables, no text boxes, no header/footer, no images, real
heading styles, real bullet numbering, contact details in the body. Fonts, sizes, colors and tab stops
are repeated as direct formatting because Apple's importer ignores some style-level settings.

Word layout fix (critic C-P1): a right tab stop is how the classic layout right-aligns dates, but
naive extractors drop w:tab and glue the words on both sides together ("AustinAustin, TX"). So every
w:tab is preceded by a real space in the same run: tab-dropping readers still see a word boundary,
and Word still right-aligns the text after the tab.

Output is deterministic: fixed part order, fixed zip timestamps, and a creation date pinned to
util.today_iso() (HP_AS_OF in tests). No docProps/app.xml, so nothing names the tool; dc:creator is
the candidate.
"""
import html
import re
import zipfile
import io

from .. import util
from .model import THEME, CONTROL_RE

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
OD_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
XML_HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'


def x(s):
    """Escape for XML text and attributes; drop characters XML 1.0 forbids."""
    return html.escape(CONTROL_RE.sub("", s or ""), quote=True)


def tw(pt):
    """Points -> twentieths of a point (twips)."""
    return int(round(pt * 20))


def hp(pt):
    """Points -> half-points (w:sz)."""
    return int(round(pt * 2))


def _rpr(font, size_pt, color, b=False, i=False, hl=False, spacing=None):
    """Run properties in ECMA-376 child order: rFonts, b, bCs, i, iCs, color, spacing, sz, szCs, highlight."""
    out = ['<w:rFonts w:ascii="%s" w:hAnsi="%s" w:eastAsia="%s" w:cs="%s"/>' % (font, font, font, font)]
    if b:
        out.append("<w:b/><w:bCs/>")
    if i:
        out.append("<w:i/><w:iCs/>")
    out.append('<w:color w:val="%s"/>' % color)
    if spacing:
        out.append('<w:spacing w:val="%d"/>' % spacing)
    out.append('<w:sz w:val="%d"/><w:szCs w:val="%d"/>' % (hp(size_pt), hp(size_pt)))
    if hl:
        out.append('<w:highlight w:val="yellow"/>')
    return "<w:rPr>%s</w:rPr>" % "".join(out)


def _run(text, font, size, color, b=False, i=False, hl=False, spacing=None):
    return '<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>' % (
        _rpr(font, size, color, b, i, hl, spacing), x(text))


def _tab_run(font, size, color):
    """A space and then the tab, in one run: the space survives tab-dropping text extraction."""
    return '<w:r>%s<w:t xml:space="preserve"> </w:t><w:tab/></w:r>' % _rpr(font, size, color)


def _para(content, style, ppr_extra=""):
    ppr = '<w:pStyle w:val="%s"/>' % style + ppr_extra
    return "<w:p><w:pPr>%s</w:pPr>%s</w:p>" % (ppr, content)


def _lang_tag(loc):
    return loc if re.match(r"^[a-z]{2,3}(-[A-Z]{2})?$", loc or "") else "en-US"


def build_document_xml(blocks, setup):
    """Return (document.xml text, hyperlink relationships [(rId, url)])."""
    t = THEME
    font = t["font"]
    pw, ph = setup["page_w"], setup["page_h"]
    page_w, page_h = tw(pw), tw(ph)
    mar = int(round(t["margin_in"] * 1440))
    text_w = page_w - 2 * mar
    tabs = '<w:tabs><w:tab w:val="right" w:pos="%d"/></w:tabs>' % text_w
    rels = []
    body = []
    body_pt, ink, muted, accent = t["body_pt"], t["ink"], t["muted"], t["accent"]

    prev = None
    for b in blocks:
        k = b["k"]
        after_heading, prev = prev == "h", k
        if k == "name":
            body.append(_para(_run(b["text"], font, t["name_pt"], accent, b=True, spacing=10), "Title",
                              '<w:keepNext/><w:spacing w:after="40"/><w:jc w:val="center"/>'))
        elif k == "headline":
            body.append(_para(_run(b["text"], font, t["headline_pt"], muted), "HPHeadline",
                              '<w:keepNext/><w:spacing w:after="20"/><w:jc w:val="center"/>'))
        elif k == "contact":
            segs = []
            for idx, part in enumerate(b["parts"]):
                if idx:
                    segs.append(_run("  |  ", font, t["contact_pt"], muted))
                run = _run(part["t"], font, t["contact_pt"], muted)
                if part.get("url"):
                    rid = "rIdL%d" % (len(rels) + 1)
                    rels.append((rid, part["url"]))
                    segs.append('<w:hyperlink r:id="%s" w:history="1">%s</w:hyperlink>' % (rid, run))
                else:
                    segs.append(run)
            body.append(_para("".join(segs), "HPContact",
                              '<w:spacing w:after="60"/><w:jc w:val="center"/>'))
        elif k == "h":
            # Real capitals in the text (not w:caps): extracted text keeps the case we show.
            border = ('<w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" w:color="%s"/></w:pBdr>'
                      % t["rule"])
            body.append(_para(_run(b["text"].upper(), font, t["heading_pt"], accent, b=True, spacing=12),
                              "Heading1",
                              '<w:keepNext/><w:keepLines/>%s<w:spacing w:before="%d" w:after="%d"/>'
                              '<w:outlineLvl w:val="0"/>'
                              % (border, tw(t["heading_before_pt"]), tw(t["heading_after_pt"]))))
        elif k == "row":
            content = "".join(_run(r["t"], font, body_pt, ink, b=r.get("b"), i=r.get("i"))
                              for r in b["left"] if r.get("t"))
            if b.get("right"):
                content += _tab_run(font, body_pt, ink) + _run(b["right"], font, body_pt, ink)
            # the first entry under a heading sits right under the rule (same gap in Chrome and the builtin PDF)
            before = ('<w:spacing w:before="%d"/>' % (0 if after_heading else tw(t["entry_before_pt"]))) if b.get("first") else ""
            body.append(_para(content, "HPEntry" if b.get("first") else "HPEntrySub",
                              "<w:keepNext/><w:keepLines/>%s%s" % (tabs, before)))
        elif k == "bullet":
            content = "".join(_run(r["t"], font, body_pt, ink, b=r.get("b"), i=r.get("i"), hl=r.get("hl"))
                              for r in b["runs"] if r.get("t"))
            body.append(_para(content, "HPBullet",
                              '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>'
                              '<w:spacing w:after="%d"/><w:ind w:left="%d" w:hanging="%d"/>'
                              % (tw(t["bullet_after_pt"]), tw(t["bullet_indent_pt"]), tw(t["bullet_hanging_pt"]))))
        elif k == "para":
            content = "".join(_run(r["t"], font, body_pt, ink, b=r.get("b"), i=r.get("i"), hl=r.get("hl"))
                              for r in b["runs"] if r.get("t"))
            body.append(_para(content, "HPBody", '<w:spacing w:after="%d"/>' % tw(t["bullet_after_pt"])))

    sect = ('<w:sectPr><w:pgSz w:w="%d" w:h="%d"/>'
            '<w:pgMar w:top="%d" w:right="%d" w:bottom="%d" w:left="%d" w:header="432" w:footer="432" w:gutter="0"/>'
            '<w:cols w:space="720"/></w:sectPr>') % (page_w, page_h, mar, mar, mar, mar)
    doc = (XML_HEAD + '<w:document xmlns:w="%s" xmlns:r="%s"><w:body>%s%s</w:body></w:document>'
           % (W_NS, R_NS, "".join(body), sect))
    return doc, rels


def styles_xml(setup):
    t = THEME
    font = t["font"]
    lang = _lang_tag(setup.get("lang"))
    # Word's "auto" line spacing is a multiple of the font's natural height (Arial ~1.149 em);
    # this keeps Word's line pitch close to the 1.2 em used by Chrome and the builtin writer.
    line = int(round(240 * (t["line"] / 1.149)))
    text_w = tw(setup["page_w"]) - 2 * int(round(t["margin_in"] * 1440))
    rfonts = '<w:rFonts w:ascii="%s" w:hAnsi="%s" w:eastAsia="%s" w:cs="%s"/>' % (font, font, font, font)

    def sz(pt):
        return '<w:sz w:val="%d"/><w:szCs w:val="%d"/>' % (hp(pt), hp(pt))

    tabs = '<w:tabs><w:tab w:val="right" w:pos="%d"/></w:tabs>' % text_w
    return (XML_HEAD + '<w:styles xmlns:w="%s">' % W_NS +
            '<w:docDefaults><w:rPrDefault><w:rPr>%s%s<w:lang w:val="%s"/></w:rPr></w:rPrDefault>'
            % (rfonts, sz(t["body_pt"]), lang) +
            '<w:pPrDefault><w:pPr><w:spacing w:after="0" w:line="%d" w:lineRule="auto"/></w:pPr></w:pPrDefault>'
            '</w:docDefaults>' % line +
            '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/>'
            '<w:rPr>%s<w:color w:val="%s"/>%s</w:rPr></w:style>' % (rfonts, t["ink"], sz(t["body_pt"])) +
            '<w:style w:type="character" w:default="1" w:styleId="DefaultParagraphFont">'
            '<w:name w:val="Default Paragraph Font"/><w:uiPriority w:val="1"/><w:semiHidden/><w:unhideWhenUsed/></w:style>'
            '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/>'
            '<w:next w:val="Normal"/><w:uiPriority w:val="10"/><w:qFormat/><w:pPr><w:keepNext/>'
            '<w:spacing w:after="40"/><w:jc w:val="center"/></w:pPr><w:rPr><w:b/><w:bCs/><w:color w:val="%s"/>'
            '<w:spacing w:val="10"/>%s</w:rPr></w:style>' % (t["accent"], sz(t["name_pt"])) +
            '<w:style w:type="paragraph" w:customStyle="1" w:styleId="HPHeadline"><w:name w:val="HP Headline"/>'
            '<w:basedOn w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:after="20"/><w:jc w:val="center"/>'
            '</w:pPr><w:rPr><w:color w:val="%s"/></w:rPr></w:style>' % t["muted"] +
            '<w:style w:type="paragraph" w:customStyle="1" w:styleId="HPContact"><w:name w:val="HP Contact"/>'
            '<w:basedOn w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:after="60"/><w:jc w:val="center"/></w:pPr>'
            '<w:rPr><w:color w:val="%s"/>%s</w:rPr></w:style>' % (t["muted"], sz(t["contact_pt"])) +
            '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>'
            '<w:next w:val="Normal"/><w:uiPriority w:val="9"/><w:qFormat/><w:pPr><w:keepNext/><w:keepLines/>'
            '<w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" w:color="%s"/></w:pBdr>'
            '<w:spacing w:before="%d" w:after="%d"/><w:outlineLvl w:val="0"/></w:pPr>'
            '<w:rPr><w:b/><w:bCs/><w:color w:val="%s"/><w:spacing w:val="12"/>%s</w:rPr></w:style>'
            % (t["rule"], tw(t["heading_before_pt"]), tw(t["heading_after_pt"]), t["accent"], sz(t["heading_pt"])) +
            '<w:style w:type="paragraph" w:customStyle="1" w:styleId="HPEntry"><w:name w:val="HP Entry"/>'
            '<w:basedOn w:val="Normal"/><w:next w:val="HPEntrySub"/><w:qFormat/><w:pPr><w:keepNext/><w:keepLines/>'
            '%s<w:spacing w:before="%d"/></w:pPr></w:style>' % (tabs, tw(t["entry_before_pt"])) +
            '<w:style w:type="paragraph" w:customStyle="1" w:styleId="HPEntrySub"><w:name w:val="HP Entry Sub"/>'
            '<w:basedOn w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:keepLines/>%s</w:pPr></w:style>' % tabs +
            '<w:style w:type="paragraph" w:customStyle="1" w:styleId="HPBullet"><w:name w:val="HP Bullet"/>'
            '<w:basedOn w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:after="%d"/><w:ind w:left="%d" w:hanging="%d"/>'
            '</w:pPr></w:style>' % (tw(t["bullet_after_pt"]), tw(t["bullet_indent_pt"]), tw(t["bullet_hanging_pt"])) +
            '<w:style w:type="paragraph" w:customStyle="1" w:styleId="HPBody"><w:name w:val="HP Body"/>'
            '<w:basedOn w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:after="%d"/></w:pPr></w:style>'
            % tw(t["bullet_after_pt"]) +
            '</w:styles>')


def numbering_xml():
    t = THEME
    font = t["font"]
    return (XML_HEAD + '<w:numbering xmlns:w="%s"><w:abstractNum w:abstractNumId="0">' % W_NS +
            '<w:multiLevelType w:val="singleLevel"/><w:lvl w:ilvl="0"><w:start w:val="1"/>'
            '<w:numFmt w:val="bullet"/><w:lvlText w:val="•"/><w:lvlJc w:val="left"/>'
            '<w:pPr><w:ind w:left="%d" w:hanging="%d"/></w:pPr>' % (tw(t["bullet_indent_pt"]), tw(t["bullet_hanging_pt"])) +
            '<w:rPr><w:rFonts w:ascii="%s" w:hAnsi="%s" w:hint="default"/><w:color w:val="%s"/></w:rPr></w:lvl>'
            % (font, font, t["ink"]) +
            '</w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>')


def settings_xml():
    return (XML_HEAD + '<w:settings xmlns:w="%s"><w:zoom w:percent="100"/><w:defaultTabStop w:val="720"/>'
            '<w:characterSpacingControl w:val="doNotCompress"/><w:compat><w:compatSetting '
            'w:name="compatibilityMode" w:uri="http://schemas.microsoft.com/office/word" w:val="15"/>'
            '</w:compat></w:settings>' % W_NS)


def content_types_xml():
    return (XML_HEAD + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
            '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>'
            '<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>'
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            '</Types>')


def root_rels_xml():
    return (XML_HEAD + '<Relationships xmlns="%s">' % REL_NS +
            '<Relationship Id="rId1" Type="%s/officeDocument" Target="word/document.xml"/>' % OD_REL +
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            '</Relationships>')


def document_rels_xml(links):
    out = [XML_HEAD + '<Relationships xmlns="%s">' % REL_NS,
           '<Relationship Id="rId1" Type="%s/styles" Target="styles.xml"/>' % OD_REL,
           '<Relationship Id="rId2" Type="%s/numbering" Target="numbering.xml"/>' % OD_REL,
           '<Relationship Id="rId3" Type="%s/settings" Target="settings.xml"/>' % OD_REL]
    for rid, url in links:
        out.append('<Relationship Id="%s" Type="%s/hyperlink" Target="%s" TargetMode="External"/>'
                   % (rid, OD_REL, x(url)))
    out.append("</Relationships>")
    return "".join(out)


def core_xml(title, creator, stamp):
    return (XML_HEAD + '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            '<dc:title>%s</dc:title><dc:creator>%s</dc:creator><cp:lastModifiedBy>%s</cp:lastModifiedBy>'
            '<dcterms:created xsi:type="dcterms:W3CDTF">%s</dcterms:created>'
            '<dcterms:modified xsi:type="dcterms:W3CDTF">%s</dcterms:modified></cp:coreProperties>'
            % (x(title), x(creator), x(creator), stamp, stamp))


def _stamp():
    day = util.today_iso()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", day or ""):
        day = "2026-01-01"
    return day + "T00:00:00Z"


def static_parts(setup):
    """The parts that do not depend on the resume text (also shipped as assets/docx-skeleton)."""
    return [("[Content_Types].xml", content_types_xml()), ("_rels/.rels", root_rels_xml()),
            ("word/styles.xml", styles_xml(setup)), ("word/numbering.xml", numbering_xml()),
            ("word/settings.xml", settings_xml())]


def build_docx_bytes(blocks, setup):
    """Return the .docx file as bytes (deterministic for the same blocks, setup and day)."""
    document, links = build_document_xml(blocks, setup)
    name = blocks[0]["text"] if blocks and blocks[0].get("k") == "name" else ""
    word = "CV" if setup.get("word", "").lower() == "cv" else "Resume"
    parts = static_parts(setup)
    parts.insert(2, ("word/document.xml", document))
    parts.append(("word/_rels/document.xml.rels", document_rels_xml(links)))
    parts.append(("docProps/core.xml", core_xml(("%s %s" % (name, word)).strip(), name, _stamp())))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for arc, content in parts:
            zi = zipfile.ZipInfo(arc, date_time=(1980, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.create_system = 0
            zi.external_attr = 0o600 << 16
            z.writestr(zi, content.encode("utf-8"))
    return buf.getvalue()


def write_docx(blocks, setup, path):
    util._atomic_write_bytes(path, build_docx_bytes(blocks, setup))
    return path
