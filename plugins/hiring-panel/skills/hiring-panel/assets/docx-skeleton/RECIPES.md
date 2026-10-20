# Manual .docx recipe (only when Python cannot run)

This folder holds every part of a Hiring Panel resume `.docx` except `word/document.xml`. The parts are
generated from `scripts/hp/render/docx.py` (Letter page), so a manual file looks like a scripted one.
Use it only in manual mode (`references/no-python.md`); when Python works, `hp.py render` does all of this.

## Steps

1. Copy this folder to a scratch folder (never edit the originals).
2. Write `word/document.xml` from the recipes below, in the order the resume should read.
3. In `docProps/core.xml`, put the candidate's name in `<dc:title>` (for example `Maya Rivera Resume`) and in
   `<dc:creator>`. Nothing else names the tool.
4. Zip the parts, with `[Content_Types].xml` first, into `First_Last_Resume.docx`:
   - macOS / Linux: `cd SCRATCH && zip -X -r ../First_Last_Resume.docx "[Content_Types].xml" _rels docProps word`
   - Windows: `tar.exe --format zip -cf First_Last_Resume.docx "[Content_Types].xml" _rels docProps word`
     (untested on Windows; if it fails, use File Explorer: select the four items, right-click, Compress to
     ZIP, then rename the .zip to .docx).
5. Do not include `RECIPES.md` in the zip.

## Rules (the same ones the script follows)

- Escape `&` as `&amp;`, `<` as `&lt;`, `>` as `&gt;`, `"` as `&quot;` in all text.
- One column. No tables, text boxes, headers, footers, images, icons or emoji.
- Never white, hidden (`w:vanish`) or tiny text. Never paste the job posting.
- Section headings are typed in capitals (`EDUCATION`), not formatted with `w:caps`.
- **A space before every tab.** The classic layout right-aligns dates with a tab stop. Put a space and then the
  tab in one run: `<w:t xml:space="preserve"> </w:t><w:tab/>`. Text extractors that drop tabs then still see
  "Hill Country University Austin, TX", not "Hill Country UniversityAustin, TX". Or use the inline layout
  (`Org | City, ST` with no tab at all).
- A4 page (outside the US and Canada): use `<w:pgSz w:w="11906" w:h="16838"/>` and tab position `9890`
  instead of `12240`/`15840` and `10224`.

## Run properties

Body text (copy this as `RPR`; add `<w:b/><w:bCs/>` after `rFonts` for bold or `<w:i/><w:iCs/>` for italics):

```xml
<w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:eastAsia="Arial" w:cs="Arial"/><w:color w:val="1A1A1A"/><w:sz w:val="21"/><w:szCs w:val="21"/></w:rPr>
```

## Document wrapper

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><w:body>
  ... paragraphs ...
<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1008" w:right="1008" w:bottom="1008" w:left="1008" w:header="432" w:footer="432" w:gutter="0"/><w:cols w:space="720"/></w:sectPr>
</w:body></w:document>
```

## Paragraph recipes

Name:
```xml
<w:p><w:pPr><w:pStyle w:val="Title"/><w:keepNext/><w:spacing w:after="40"/><w:jc w:val="center"/></w:pPr><w:r><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:eastAsia="Arial" w:cs="Arial"/><w:b/><w:bCs/><w:color w:val="1F3A5F"/><w:spacing w:val="10"/><w:sz w:val="42"/><w:szCs w:val="42"/></w:rPr><w:t xml:space="preserve">FULL NAME</w:t></w:r></w:p>
```

Contact line (parts joined by a run holding `  |  `; links as plain text):
```xml
<w:p><w:pPr><w:pStyle w:val="HPContact"/><w:spacing w:after="60"/><w:jc w:val="center"/></w:pPr><w:r><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:eastAsia="Arial" w:cs="Arial"/><w:color w:val="4A4A4A"/><w:sz w:val="19"/><w:szCs w:val="19"/></w:rPr><w:t xml:space="preserve">City, ST  |  phone  |  email  |  linkedin.com/in/handle</w:t></w:r></w:p>
```

Section heading:
```xml
<w:p><w:pPr><w:pStyle w:val="Heading1"/><w:keepNext/><w:keepLines/><w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" w:color="1F3A5F"/></w:pBdr><w:spacing w:before="180" w:after="80"/><w:outlineLvl w:val="0"/></w:pPr><w:r><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:eastAsia="Arial" w:cs="Arial"/><w:b/><w:bCs/><w:color w:val="1F3A5F"/><w:spacing w:val="12"/><w:sz w:val="21"/><w:szCs w:val="21"/></w:rPr><w:t xml:space="preserve">EXPERIENCE</w:t></w:r></w:p>
```

Entry line 1 (organization bold, location right-aligned; use `w:before="0"` for the first entry under a
heading and `w:before="90"` for the others):
```xml
<w:p><w:pPr><w:pStyle w:val="HPEntry"/><w:keepNext/><w:keepLines/><w:tabs><w:tab w:val="right" w:pos="10224"/></w:tabs><w:spacing w:before="90"/></w:pPr><w:r>RPR-BOLD<w:t xml:space="preserve">Organization</w:t></w:r><w:r>RPR<w:t xml:space="preserve"> </w:t><w:tab/></w:r><w:r>RPR<w:t xml:space="preserve">City, ST</w:t></w:r></w:p>
```

Entry line 2 (role italic, dates right-aligned):
```xml
<w:p><w:pPr><w:pStyle w:val="HPEntrySub"/><w:keepNext/><w:keepLines/><w:tabs><w:tab w:val="right" w:pos="10224"/></w:tabs></w:pPr><w:r>RPR-ITALIC<w:t xml:space="preserve">Role title</w:t></w:r><w:r>RPR<w:t xml:space="preserve"> </w:t><w:tab/></w:r><w:r>RPR<w:t xml:space="preserve">Sep 2023 – Present</w:t></w:r></w:p>
```

Bullet:
```xml
<w:p><w:pPr><w:pStyle w:val="HPBullet"/><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr><w:spacing w:after="20"/><w:ind w:left="288" w:hanging="216"/></w:pPr><w:r>RPR<w:t xml:space="preserve">Bullet text</w:t></w:r></w:p>
```

Plain line (GPA and honors, a skills line with a bold label):
```xml
<w:p><w:pPr><w:pStyle w:val="HPBody"/><w:spacing w:after="20"/></w:pPr><w:r>RPR-BOLD<w:t xml:space="preserve">Analytics: </w:t></w:r><w:r>RPR<w:t xml:space="preserve">Excel, Survey design</w:t></w:r></w:p>
```

Replace `RPR`, `RPR-BOLD` and `RPR-ITALIC` with the run properties above before zipping; a literal `RPR` left
in the XML makes the file invalid.
