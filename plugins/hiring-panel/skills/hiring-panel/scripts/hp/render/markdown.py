"""Blocks -> resume Markdown (the plain-text deliverable).

Kept close to what the PDF shows so the release gate can compare words: links are written as plain
text (no duplicated URLs), italics use *asterisks* (underscores would stick to words for \\w
tokenizers), and right-column text follows the left after " | ".
"""
import re


def md_esc(s):
    return re.sub(r"([\\`*_\[\]<>#|])", r"\\\1", s or "")


def md_runs(runs):
    out = []
    for r in runs:
        raw = r.get("t") or ""
        core = raw.strip()
        if not core:
            out.append(raw)
            continue
        lead, trail = raw[:len(raw) - len(raw.lstrip())], raw[len(raw.rstrip()):]
        if core == "|":
            out.append(lead + "|" + trail)
            continue
        s = md_esc(core)
        if r.get("hl"):
            s = "==%s==" % s
        if r.get("b"):
            s = "**%s**" % s
        if r.get("i"):
            s = "*%s*" % s
        out.append(lead + s + trail)
    return "".join(out)


def build_resume_md(blocks):
    out = []
    for b in blocks:
        k = b["k"]
        if k == "name":
            out.append("# " + md_esc(b["text"]))
        elif k == "headline":
            out.append("")
            out.append(md_esc(b["text"]))
        elif k == "contact":
            out.append("")
            out.append(" | ".join(md_esc(p["t"]) for p in b["parts"]))
        elif k == "h":
            out.append("")
            out.append("## " + md_esc(b["text"]))
            out.append("")
        elif k == "row":
            line = md_runs(b["left"])
            if b.get("right"):
                line += " | " + md_esc(b["right"])
            if b.get("first") and out and out[-1] != "":
                out.append("")
            out.append(line + "  ")
        elif k == "bullet":
            out.append("- " + md_runs(b["runs"]))
        elif k == "para":
            out.append(md_runs(b["runs"]) + "  ")
    text = "\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"
