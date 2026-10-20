"""PDF structure probe (ATS spec 5): facts from the raw file and its inflated streams.

Reports: encryption, text layer, image objects, Type0 fonts vs ToUnicode maps, Type3 fonts, invisible
text (render mode 3/7, or white fill on an unpainted page), Producer/Creator (Info dict, with escaped
parentheses and UTF-16 strings) and XMP CreatorTool, page count, design tool. It also runs the built-in
text reader so the extraction ladder can fall back to it. Bounded by a 5 second budget and the stream
caps in limits.py; never raises.
"""
import re

from hp.ingest.limits import Budget, PROBE_BUDGET_S
from hp.ingest.pdf_lex import decode_text_string
from hp.ingest.pdf_objects import PdfDoc
from hp.ingest.pdf_content import Interpreter, lines_text, hidden_texts

DESIGN_TOOL_RE = re.compile(r"(?i)\b(canva|indesign|illustrator|photoshop|figma|affinity|sketch|pages|keynote)\b")
DESIGN_TOOL_NAMES = {"canva": "Canva", "indesign": "InDesign", "illustrator": "Illustrator",
                     "photoshop": "Photoshop", "figma": "Figma", "affinity": "Affinity",
                     "sketch": "Sketch", "pages": "Pages", "keynote": "Keynote"}
OCR_SHARE = 0.9      # this share of invisible text-show operations = a text layer, not hidden text


def _clean_meta(s):
    if not s:
        return None
    s = "".join(ch for ch in s if ch.isprintable())
    s = re.sub(r"\s+", " ", s).strip()
    return s[:120] or None


def _xmp_value(blob, tag):
    m = re.search(rb"<" + tag + rb">\s*(?:<rdf:Alt>\s*<rdf:li[^>]*>)?([^<]{1,300})<", blob)
    if not m:
        m = re.search(tag + rb"\s*=\s*\"([^\"]{1,300})\"", blob)
    if m:
        try:
            return m.group(1).decode("utf-8", "replace").strip()
        except Exception:  # pragma: no cover
            return None
    return None


def probe_pdf(data, budget_s=PROBE_BUDGET_S):
    """Return a dict of PDF facts (see keys below). `data` is the whole file."""
    budget = Budget(budget_s)
    facts = {
        "encrypted": False, "text_layer": None, "fonts": 0, "type0": 0, "tounicode": 0, "type3": 0,
        "images": 0, "pages": None, "producer": None, "creator": None, "creator_tool": None,
        "design_tool": None, "text_ops": 0, "invisible_spans": 0, "invisible_ops": 0, "white_ops": 0,
        "ocr_layer": False, "hidden_samples": [], "builtin_pages": [], "builtin_unmapped": 0,
        "warnings": [], "truncated": False,
    }
    if b"%%EOF" not in data[-2048:]:
        facts["truncated"] = True
        facts["warnings"].append("the PDF looks truncated (no end-of-file marker)")
    pdf = PdfDoc(data, budget)
    facts["encrypted"] = pdf.encrypted() or bool(re.search(rb"/Encrypt\s*(?:\d+\s+\d+\s+R|<<)", data))

    # Fonts, images and page objects from the object index.
    page_objs = 0
    for num in sorted(pdf.objects):
        v = pdf.objects[num][0]
        if not isinstance(v, dict):
            continue
        t = v.get("Type")
        st = v.get("Subtype")
        if t == "Font" or (st in ("Type0", "Type1", "TrueType", "Type3", "MMType1") and "BaseFont" in v):
            facts["fonts"] += 1
            if st == "Type0":
                facts["type0"] += 1
                if v.get("ToUnicode") is not None:
                    facts["tounicode"] += 1
            elif st == "Type3":
                facts["type3"] += 1
        elif st == "Image" and (t in (None, "XObject")):
            facts["images"] += 1
        elif t == "Page":
            page_objs += 1
    if not pdf.objects:
        # Nothing parsed (badly broken file): fall back to regex counts on the raw bytes.
        facts["fonts"] = len(re.findall(rb"/Type\s*/Font\b", data))
        facts["type0"] = len(re.findall(rb"/Subtype\s*/Type0\b", data))
        facts["tounicode"] = min(facts["type0"], len(re.findall(rb"/ToUnicode\b", data)))
        facts["type3"] = len(re.findall(rb"/Subtype\s*/Type3\b", data))
        facts["images"] = len(re.findall(rb"/Subtype\s*/Image\b", data))
        page_objs = len(re.findall(rb"/Type\s*/Page(?![s\w])", data))

    # Metadata: Info dictionary, then XMP.
    info = pdf.resolve(pdf.trailer.get("Info"))
    if isinstance(info, dict) and not facts["encrypted"]:
        for key, field in (("Producer", "producer"), ("Creator", "creator")):
            val = pdf.resolve(info.get(key))
            if isinstance(val, bytes):
                facts[field] = _clean_meta(decode_text_string(val))
    if facts["producer"] is None and facts["creator"] is None and not pdf.objects:
        for key, field in ((rb"/Producer", "producer"), (rb"/Creator", "creator")):
            m = re.search(key + rb"\s*\(((?:\\.|[^\\)]){0,300})\)", data)
            if m:
                facts[field] = _clean_meta(m.group(1).decode("latin-1").replace("\\(", "(").replace("\\)", ")"))
    for num in sorted(pdf.objects):
        v = pdf.objects[num][0]
        if isinstance(v, dict) and v.get("Type") == "Metadata" and pdf.objects[num][1]:
            blob = pdf.stream_data(num) or b""
            tool = _xmp_value(blob, rb"xmp:CreatorTool")
            if tool:
                facts["creator_tool"] = _clean_meta(tool)
            if facts["producer"] is None:
                prod = _xmp_value(blob, rb"pdf:Producer")
                if prod:
                    facts["producer"] = _clean_meta(prod)
            break
    for field in ("creator_tool", "creator", "producer"):
        m = DESIGN_TOOL_RE.search(facts[field] or "")
        if m:
            facts["design_tool"] = DESIGN_TOOL_NAMES[m.group(1).lower()]
            break

    # Content streams: the built-in reader plus invisible-text facts.
    pages = pdf.pages()
    facts["pages"] = len(pages) if pages else (page_objs or None)
    interp = Interpreter(pdf, budget)
    results = []
    if pages:
        for page in pages[:200]:
            if budget.expired():
                break
            results.append(interp.page(page))
    else:
        for num in sorted(pdf.objects):
            if budget.expired():
                break
            v, stream = pdf.objects[num]
            if not stream or not isinstance(v, dict) or v.get("Subtype") == "Image" or "Length1" in v:
                continue
            raw = pdf.stream_data(num)
            if raw and b"BT" in raw and (b"Tj" in raw or b"TJ" in raw):
                results.append(interp.run_stream(raw, None))
    if budget.expired():
        facts["warnings"].append("the PDF structure check stopped after %d seconds; results are partial" % int(budget_s))
    for r in results:
        facts["text_ops"] += r.text_ops
        facts["invisible_ops"] += r.invisible_ops
        facts["white_ops"] += r.white_ops
        facts["builtin_unmapped"] += r.unmapped
    any_images = facts["images"] > 0 or any(r.images for r in results)
    if any(r.images for r in results) and facts["images"] == 0:
        facts["images"] = sum(r.images for r in results)
    total = facts["text_ops"]
    if total and facts["invisible_ops"] >= OCR_SHARE * total:
        # (Nearly) all text is invisible: it is the page's text layer, not hidden extra text. Either a
        # scan with recognised (OCR) text, or a design export that draws the letters as shapes.
        facts["ocr_layer"] = True
        if any_images:
            facts["warnings"].append("this PDF looks like a scan with a recognised-text (OCR) layer")
        else:
            facts["warnings"].append("this PDF draws its letters as shapes; the readable text is an invisible layer")
        facts["invisible_spans"] = 0
        facts["builtin_pages"] = [lines_text(r, True) for r in results]
    else:
        facts["builtin_pages"] = [lines_text(r, False) for r in results]
        for r in results:
            stretches = hidden_texts(r)
            # One span = one unbroken stretch of invisible text on a line (like the .docx spans).
            facts["invisible_spans"] += len(stretches)
            for s in stretches:
                if len(facts["hidden_samples"]) < 12:
                    facts["hidden_samples"].append(("pdf", s))
    # ATS spec 5: a text layer = at least one font object AND at least one text-show operator.
    if facts["text_ops"] > 0 and facts["fonts"] > 0:
        facts["text_layer"] = True
    elif facts["encrypted"] and facts["text_ops"] == 0:
        facts["text_layer"] = None      # content is encrypted; unknown until a reader opens it
    else:
        facts["text_layer"] = False
    for w in pdf.warnings:
        if w not in facts["warnings"]:
            facts["warnings"].append(w)
    return facts
