"""Plain text, Markdown and pasted text (format txt|md), plus a light HTML-to-text fallback.

Decoding is BOM-aware (UTF-8, UTF-16 LE/BE, UTF-32), then strict UTF-8, then BOM-less UTF-16 when the
byte pattern shows it, then cp1252. Bytes that are mostly control characters are reported as binary.
Markdown-style lines are read as what they mean: "# Heading" -> heading style, "**Whole line**" ->
bold, "- item" / "* item" -> "• item" (list). Words are never changed.
"""
import html
import re

from hp.ingest.limits import MAX_LINES, MAX_TEXT_CHARS
from hp.ingest.normalize import normalize_line

_MD_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_MD_BOLD_LINE = re.compile(r"^\s*(\*\*|__)(.+?)\1\s*:?\s*$")
_MD_BULLET = re.compile(r"^\s*[-*+]\s+(?=\S)")
_MD_RULE = re.compile(r"^\s*(?:[-*_]\s*){3,}$")
_MD_INLINE_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")


def decode_bytes(data):
    """Return (text, encoding, is_binary)."""
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", "replace"), "utf-8-sig", False
    if data.startswith(b"\xff\xfe\x00\x00") or data.startswith(b"\x00\x00\xfe\xff"):
        try:
            return data.decode("utf-32"), "utf-32", False
        except UnicodeDecodeError:
            pass
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16", "replace"), "utf-16", False
    sample = data[:4096]
    if sample and sample.count(b"\x00") > len(sample) // 4:
        evens = sample[0::2].count(b"\x00")
        odds = sample[1::2].count(b"\x00")
        if odds > len(sample) // 3 and evens < len(sample) // 20:
            return data.decode("utf-16-le", "replace"), "utf-16-le", False
        if evens > len(sample) // 3 and odds < len(sample) // 20:
            return data.decode("utf-16-be", "replace"), "utf-16-be", False
        return "", "binary", True
    try:
        text = data.decode("utf-8")
        enc = "utf-8"
    except UnicodeDecodeError:
        text = data.decode("cp1252", "replace")
        enc = "cp1252"
    sample_text = text[:8192]
    if sample_text:
        ctrl = sum(1 for c in sample_text if (ord(c) < 32 and c not in "\t\n\r\f") or c == "\ufffd")
        if ctrl > 0.05 * len(sample_text):
            return "", "binary", True
    return text, enc, False


def html_to_text(s):
    """Very small HTML -> text conversion for resumes saved as web pages (no scripts, no URLs)."""
    s = re.sub(r"(?is)<(script|style|head|noscript|template)\b.*?</\1\s*>", " ", s)
    s = re.sub(r"(?s)<!--.*?-->", " ", s)
    s = re.sub(r"(?i)<li\b[^>]*>", "\n\u2022 ", s)
    s = re.sub(r"(?i)</t[dh]\s*>", " | ", s)
    s = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr|section|article|header|footer|ul|ol|table)\s*>", "\n", s)
    s = re.sub(r"(?s)<[^>]{0,2000}>", "", s)
    s = html.unescape(s)
    lines = []
    for line in s.split("\n"):
        line = re.sub(r"(\s*\|\s*)+$", "", line)
        lines.append(line)
    return "\n".join(lines)


def text_to_lines(text, ctx, markdown=True):
    """Split text into Document line dicts, applying the light Markdown reading when asked.
    (Tabs in plain text are kept by every reader, so tab_merged_tokens stays 0 for text.)"""
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS]
        ctx.warnings.append("text truncated to the first %d characters" % MAX_TEXT_CHARS)
    lines = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        style = None
        bold = False
        is_list = False
        if markdown:
            if _MD_RULE.match(raw):
                continue
            m = _MD_HEADING.match(raw)
            if m:
                style = "Heading %d" % len(m.group(1))
                raw = m.group(2)
            else:
                m = _MD_BOLD_LINE.match(raw)
                if m:
                    bold = True
                    raw = m.group(2) + (":" if raw.rstrip().endswith(":") and not m.group(2).endswith(":") else "")
            raw = _MD_INLINE_BOLD.sub(r"\1", raw)
        text_line = normalize_line(raw, ctx.stats)
        if not text_line:
            continue
        if text_line.startswith("\u2022 "):
            is_list = True
        lines.append({"text": text_line, "style": style, "list": is_list, "bold": bold, "where": "body"})
        if len(lines) >= MAX_LINES:
            ctx.warnings.append("text truncated to the first %d lines" % MAX_LINES)
            break
    return lines
