"""Turn one paragraph's runs into normalized lines (shared by the .docx and .rtf readers).

A reader feeds pieces in document order: text (with hidden/bold/caps flags), tabs, line breaks and
text boxes anchored in the paragraph. finish() then:
- finds hidden spans (vanish or white text with any letters; tiny text of 3+ words), counts them,
  keeps a short quote for the warnings and drops them from the visible text, so hidden keywords never
  become "resume evidence";
- counts tab_merged_tokens: a tab with non-space text directly on both sides, which a tab-dropping
  extractor would fuse into one token ("AustinAustin, TX");
- splits on line breaks, normalizes each line and adds "• " to the first line of a bulleted list item;
- places text boxes before the paragraph's lines when anchored before any visible text, else after.
"""
import re

from hp.ingest.normalize import normalize_line, word_count, BULLET_GLYPHS, PUA_BULLETS

BULLET_ONLY = set(BULLET_GLYPHS) | set(chr(c) for c in PUA_BULLETS) | set("-*+o\u2013")

HIDDEN_KINDS = ("vanish", "white", "tiny")
MAX_HIDDEN_SAMPLES = 12
SAMPLE_CHARS = 160


class Collector(object):
    """Counters that several paragraphs add to. Readers copy them into doc["signals"] at the end."""

    def __init__(self, stats):
        self.stats = stats                    # normalize.TextStats
        self.hidden = {"vanish": 0, "white": 0, "tiny": 0}
        self.hidden_samples = []              # [(kind, text)]
        self.tab_merged = 0
        self.caps_paragraphs = 0

    def add_hidden(self, kind, text):
        self.hidden[kind] += 1
        sample = normalize_line(text)
        if sample and len(self.hidden_samples) < MAX_HIDDEN_SAMPLES:
            if len(sample) > SAMPLE_CHARS:
                sample = sample[:SAMPLE_CHARS - 3].rstrip() + "..."
            self.hidden_samples.append((kind, sample))


class ParagraphBuilder(object):
    def __init__(self):
        self.pieces = []

    def text(self, s, hidden=None, bold=False, caps=False):
        if s:
            self.pieces.append(["t", s, hidden, bool(bold), bool(caps)])

    def tab(self):
        self.pieces.append(["tab"])

    def br(self):
        self.pieces.append(["br"])

    def box(self, lines):
        self.pieces.append(["box", lines])

    def has_text(self):
        return any(p[0] == "t" and p[1].strip() for p in self.pieces)

    def _mark_hidden(self, collector):
        """Return a list parallel to pieces: True where the piece is a counted hidden span."""
        removed = [False] * len(self.pieces)
        i = 0
        n = len(self.pieces)
        while i < n:
            p = self.pieces[i]
            if p[0] != "t" or not p[2]:
                i += 1
                continue
            kind = p[2]
            j = i
            parts = []
            while j < n and self.pieces[j][0] == "t" and self.pieces[j][2] == kind:
                parts.append(self.pieces[j][1])
                j += 1
            joined = "".join(parts)
            counted = False
            if kind in ("vanish", "white"):
                counted = any(c.isalnum() for c in joined)
            elif kind == "tiny":
                counted = word_count(joined) >= 3
            if counted:
                collector.add_hidden(kind, joined)
                for k in range(i, j):
                    removed[k] = True
            i = j
        return removed

    def finish(self, collector, style=None, is_list=False, bullet=False, where="body"):
        """Return the paragraph's line dicts (text boxes included in anchor order)."""
        removed = self._mark_hidden(collector)
        before, after = [], []
        buf = []
        seen_text = False
        bold_all = True
        any_visible = False
        caps = False
        prev_removed = False
        for idx, p in enumerate(self.pieces):
            kind = p[0]
            if kind == "t":
                if removed[idx]:
                    if not prev_removed:
                        buf.append(" ")
                    prev_removed = True
                    continue
                prev_removed = False
                buf.append(p[1])
                if p[1].strip():
                    seen_text = True
                    any_visible = True
                    if not p[3]:
                        bold_all = False
                    if p[4]:
                        caps = True
            elif kind == "tab":
                prev_removed = False
                buf.append("\t")
            elif kind == "br":
                prev_removed = False
                buf.append("\n")
            elif kind == "box":
                (after if seen_text else before).extend(p[1])
        visible = "".join(buf)
        for raw_line in visible.split("\n"):
            for m in re.finditer(r"\t+", raw_line):
                left, right = raw_line[:m.start()], raw_line[m.end():]
                # A tab after a bullet glyph (list text) only separates the bullet from the words.
                if left and right and not left[-1].isspace() and not right[0].isspace() \
                        and left.strip() not in BULLET_ONLY:
                    collector.tab_merged += 1
        if caps:
            collector.caps_paragraphs += 1
        lines = []
        first = True
        for raw_line in visible.split("\n"):
            text = normalize_line(raw_line, collector.stats)
            if not text:
                continue
            if first and bullet and not text.startswith("\u2022"):
                text = "\u2022 " + text
            lines.append({"text": text, "style": style, "list": bool(is_list and first),
                          "bold": bool(any_visible and bold_all), "where": where})
            first = False
        return before + lines + after
