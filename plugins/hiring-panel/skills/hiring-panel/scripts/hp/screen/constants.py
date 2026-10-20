"""Fixed numbers and fixed text for the simulated screening check.

Everything a student reads that is not taken from their own files lives here, so the wording can be
reviewed in one place. Thresholds are documented heuristics (career-center convention and product
judgment), not research findings. See ATS spec sections 6, 10, 14 and 15.

Voice rules for every string below: plain language, second person, short sentences, no em dashes,
never "ATS score", never promise interviews.
"""

SCHEMA_VERSION = "1.0"
TOOL_NAME = "hiring-panel-screen"

SEVERITIES = ("critical", "high", "medium", "low", "info")
SEVERITY_RANK = {s: i for i, s in enumerate(SEVERITIES)}
CONFIDENCES = ("high", "medium", "low")
CONFIDENCE_MULT = {"high": 1.0, "medium": 0.7, "low": 0.4}
CATEGORY_ORDER = ("parse", "contact", "keywords", "sections", "dates", "content")
CATEGORY_BY_PREFIX = {"PARSE": "parse", "CONTACT": "contact", "KW": "keywords", "SECT": "sections",
                      "DATE": "dates", "CONTENT": "content"}

STAGES = ("student", "early_career", "experienced")

# ---------------------------------------------------------------- content thresholds (spec 10)
BULLET_TOO_LONG = 35          # words; a bullet over this is "too long"
BULLET_TOO_SHORT = 5          # words; a bullet under this is "too short"
TARGET_ACTION_SHARE = 0.70
TARGET_QUANT_SHARE = 0.35
REPEATED_OPENER_LIMIT = 3     # the same opener more than this many times
MAX_BULLETS_PER_ENTRY = 8
MIN_BULLETS_TO_JUDGE = 4      # fewer bullets than this: content signals are capped at CS_FEW_BULLETS_CAP
CS_FEW_BULLETS_CAP = 65       # the top of the "Needs work" band
GAP_MONTHS = 6                # gaps and pauses longer than this are reported (info only)
TOP_LINES_FOR_CONTACT = 12
TEXTBOX_SHARE_HIGH = 0.15
FILE_SIZE_LIMIT = 2500000     # bytes; the 2.5 MB parse limit (Greenhouse)
PAGE_LIMIT = {"student": 2, "early_career": 2, "experienced": 3}

# ---------------------------------------------------------------- scoring (spec 14)
PS_POINTS = {"critical": 45, "high": 15, "medium": 7, "low": 2, "info": 0}
PS_CRITICAL_CAP = 40
# Issues that count against Parse Safety besides every PARSE-* id: things the parser-vendor sources
# say break parsing (headings, year-only and split dates, two-digit years, abbreviated titles).
PS_EXTRA_IDS = ("SECT-004", "SECT-005", "SECT-007", "DATE-002", "DATE-003", "DATE-009", "CONTENT-010")

KM_WEIGHTS = {"required": 0.70, "preferred": 0.20, "evidence": 0.10}
KM_WEIGHTS_SIMPLE = {"required": 0.90, "evidence": 0.10}
KM_MIN_JD_CHARS = 300
KM_MIN_TERMS = 5
TERM_BASE_WEIGHT = {"required": 3.0, "responsibility": 1.5, "preferred": 1.0, "unspecified": 1.0}
TERM_KIND_FACTOR = {"hard": 1.0, "tool": 1.0, "cert": 1.0, "title": 1.0, "domain": 0.8,
                    "unknown": 0.6, "soft": 0.4}
IMPORTANCE_RANK = {"required": 3, "responsibility": 2, "preferred": 1, "unspecified": 0}
MATCH_CREDIT = {"exact": 1.0, "alias": 1.0, "acronym": 1.0, "inflection": 0.9, "implied": 0.8,
                "partial": 0.5, "ambiguous": 0.5, "none": 0.0}
FOUND_TYPES = ("exact", "alias", "acronym", "inflection", "implied")
MAX_NGRAM_TERMS = 20
MAX_LLM_TERMS = 60

OVERALL_WEIGHTS = {"parse_safety": 0.40, "keyword_match": 0.40, "content_signals": 0.20}
OVERALL_WEIGHTS_NO_KM = {"parse_safety": 0.65, "keyword_match": 0.0, "content_signals": 0.35}
OVERALL_GATE_CAP = 40
# Fewer than half of the required terms found: Overall stays in "Needs work" at most, so a clean file
# can't make a resume that misses most requirements look nearly ready.
KM_COVERAGE_FLOOR = 0.5
OVERALL_LOW_COVERAGE_CAP = 60
OVERALL_LOW_COVERAGE_NOTE = (" Capped at 60 (Needs work) because fewer than half of the required job terms "
                             "were found.")

PS_BANDS = ((90, "Clean"), (75, "Minor risks"), (50, "Risky"), (0, "Likely to mis-parse"))
KM_BANDS = ((80, "Strong match"), (60, "Good match"), (40, "Partial match"), (0, "Weak match"))
CS_BANDS = ((85, "Polished"), (70, "Solid"), (50, "Needs work"), (0, "Major gaps"))
OVERALL_BANDS = ((80, "Ready to send"), (65, "Close, fix the top items"), (45, "Needs work"),
                 (0, "Not ready"))
GATE_BAND = "Fix the file first"
PS_ONLY_BAND = "File readability only: {band}"
PS_FAIL_BAND = "Likely to mis-parse"
TEXT_NOT_CHECKED = " (text not checked)"

KM_BAND_NO_JD = "No job description provided"
KM_BAND_THIN = "Not enough job description to judge"
KM_BAND_NOT_ENGLISH = "Not checked: keyword dictionary is English-only"
KM_BAND_NO_TEXT = "Not checked: no resume text"
CS_BAND_NOT_ENGLISH = "Not checked: content checks are English-only"
CS_BAND_NO_TEXT = "Not checked: no resume text"
KM_REASON_NOT_ENGLISH = "keyword dictionary is English-only"

# ---------------------------------------------------------------- fixed output text (spec 15)
PRECISION_NOTE = ("Scores move in steps of 5 on purpose. A 70 and a 75 are not meaningfully different. "
                  "The counts and the issue list matter more than the number.")

DISCLAIMER = ("This is a simulation, not a real applicant tracking system. Every employer sets up its "
              "own software, and none of the big vendors publish exactly how they parse or rank resumes. "
              "This check looks for problems known to break resume parsing and for job-description "
              "requirements your resume doesn't show. A high score doesn't guarantee an interview, and a "
              "low score doesn't mean a robot rejected you. Most automatic rejections come from "
              "application questions (work authorization, location, degree, availability), and no "
              "resume edit changes those.")

OVERALL_METHOD = ("Overall = 40% file readability + 40% job-keyword match + 20% content signals, rounded "
                  "to steps of 5. Weights are our judgment, not calibrated to hiring outcomes.")
OVERALL_METHOD_NO_KM = ("Overall = 65% file readability + 35% content signals (no keyword match), rounded "
                        "to steps of 5. Weights are our judgment, not calibrated to hiring outcomes.")
OVERALL_METHOD_PS_ONLY = ("Overall is based on file readability only, because the keyword and content "
                          "checks are English-only. Rounded to steps of 5.")

LIMITATIONS_BASE = (
    "We don't run Workday, Greenhouse, Lever, iCIMS or Taleo; their parsers differ by vendor, version "
    "and employer settings.",
    "Our text extraction stands in for theirs (method: {method}).",
    "The skills dictionary is finite, and AI matchers may credit related experience differently.",
    "We can't see the application questions the employer set up.",
    "Scores aren't probabilities and aren't calibrated against interview outcomes.",
    "{columns}",
    "Dates are read to the month; seasons are approximated.",
)
COLUMN_TEXT = {
    "performed": "Column detection was performed.",
    "docx_section_only": "Column detection is limited to Word section settings.",
    "unavailable": "Column detection is unavailable without a PDF layout library.",
    "not_applicable": "Column detection does not apply to pasted text.",
}
LIMITATION_NO_JD = "No job posting was provided, so job keywords were not checked."
LIMITATION_NOT_ENGLISH = ("Keyword and content checks are English-only, so they were skipped for this "
                          "{doc}.")
LIMITATION_THIN_JD = ("The job posting was too short to judge keywords fairly, so the keyword match has "
                      "no number.")

KW_HONESTY = "Only add a term you can back up in an interview."
KNOCKOUT_BY_DESIGN = ("This is usually an application question. Answer truthfully; the resume can't "
                      "and shouldn't address it.")
READABILITY_NOTE = "For information only; not scored."

PLATFORM_NOTES = {
    "workday": [("On Workday applications, type your skills into the Skills field yourself; parsing "
                 "doesn't fill it.", ["wd_parsing_admin"])],
    "greenhouse": [("On Greenhouse, answers to application questions can trigger automatic rejection "
                    "on some plans. Answer them carefully and truthfully.", ["gh_app_rules"])],
    "taleo": [("On Taleo, eligibility questions can end an application. Answer them carefully and "
               "truthfully.", ["taleo_prescreen", "taleo_dq_23c"])],
    "lever": [("On Lever, knockout answers can move an application to the archive automatically. "
               "Answer them carefully and truthfully.", ["lever_archive"])],
}

# ---------------------------------------------------------------- issue catalogue (spec 6 + PARSE-023)
# Fields: title, why, fix, honesty (or None), detected_by, refs. "{doc}" becomes "resume" or "CV" by
# locale. Optional "variants" override fields for a named variant (chosen by the hazard detector).
CATALOGUE = {
    "PARSE-001": {
        "title": "No selectable text found in this file",
        "why": "Screening software reads the text layer of your file. A scan or a picture of text has "
               "none, so the parser may see a blank {doc}.",
        "fix": "Export your {doc} from Word or Google Docs as a .docx or a text-based PDF. Test it: if "
               "you can highlight and copy the words, software can read them.",
        "detected_by": "file_structure", "refs": ["lever_parsing", "gh_parse_fail",
                                                  "textkernel_getting_started"]},
    "PARSE-002": {
        "title": "The file is password-protected or encrypted",
        "why": "Parsers usually can't open protected files, so your {doc} may arrive empty.",
        "fix": "Save a copy without a password or editing restrictions and upload that copy.",
        "detected_by": "file_structure", "refs": ["rchilli_tips_2020"]},
    "PARSE-003": {
        "title": "The text in this file can't be read reliably",
        "why": "When the extracted text comes out scrambled or broken, the parser fills your profile "
               "with the same scrambled text.",
        "fix": "Export again from the original document using a standard font. Then copy all the text "
               "into a plain editor and check that it reads normally.",
        "detected_by": "extracted_text", "refs": ["textkernel_getting_started"]},
    "PARSE-004": {
        "title": "Some fonts lack the mapping that turns them back into text",
        "why": "Without that mapping, some PDF readers turn your words into odd symbols.",
        "fix": "Export again from Word or Google Docs with a common font, or upload a .docx if the "
               "posting accepts it.",
        "detected_by": "file_structure", "refs": ["textkernel_getting_started"]},
    "PARSE-005": {
        "title": "The PDF uses Type 3 fonts, which some readers can't extract",
        "why": "Type 3 fonts are drawn as shapes, so text extraction can drop or garble letters.",
        "fix": "Export again with a standard font, or upload a .docx if the posting accepts it.",
        "detected_by": "file_structure", "refs": ["textkernel_getting_started"]},
    "PARSE-006": {
        "title": "Contact details are only in the header or footer",
        "why": "Some parsers skip headers and footers, so your email or phone may never reach your "
               "profile.",
        "fix": "Move your name, email, phone and city into the first lines of the page body.",
        "detected_by": "file_structure", "refs": ["gh_parse_fail", "rchilli_tips_2020"]},
    "PARSE-007": {
        "title": "Text sits inside a text box",
        "why": "Parsers often skip text boxes or read them out of order.",
        "fix": "Move the text out of the text box into normal paragraphs.",
        "detected_by": "file_structure", "refs": ["gh_parse_fail"]},
    "PARSE-008": {
        "title": "Part of your {doc} is inside a table",
        "why": "Tables can scramble reading order. Job details inside cells may land in the wrong "
               "fields.",
        "fix": "Rebuild that part as plain lines: job title, organization and dates on one line, then "
               "bullets.",
        "detected_by": "file_structure", "refs": ["gh_parse_fail", "rchilli_tips_2020"],
        "variants": {"layout": {
            "why": "Tables can scramble reading order. Here the table seems to hold layout or a "
                   "list, which is a smaller risk."}}},
    "PARSE-009": {
        "title": "The layout uses more than one column",
        "why": "Parsers often read one column after the other. That can separate job titles from "
               "their dates and bullets.",
        "fix": "Use a single-column layout and keep each date on the same line as its job.",
        "detected_by": "file_structure", "refs": ["gh_parse_fail", "rchilli_tips_2020",
                                                  "enhancv_columns_test"]},
    "PARSE-009b": {
        "title": "Dates appear separated from their job details",
        "why": "Several dates in a row followed by bullets usually means the text was read out of "
               "order, often from a sidebar or a second column.",
        "fix": "Use a single-column layout and keep each date on the same line as its job.",
        "detected_by": "heuristic", "refs": ["rchilli_tips_2020", "enhancv_columns_test"]},
    "PARSE-010": {
        "title": "Images, charts or rating graphics carry information",
        "why": "Parsers can't read images. Skill bars, charts and icons are lost or turn into stray "
               "symbols.",
        "fix": "Say it in words instead, for example \"Spanish (conversational)\". Keep any image "
               "purely decorative.",
        "detected_by": "file_structure", "refs": ["gh_parse_fail", "wd_parsing_admin"],
        "variants": {
            "icons": {"title": "Small icons or images are in the file",
                      "why": "Parsers skip images. Small icons are a minor risk, but anything they "
                             "say is lost."},
            "photo_customary": {"title": "The file contains an image, such as a photo",
                                "why": "A photo is customary where you are applying, but parsers "
                                       "skip images. Keep every detail in text outside the image."}}},
    "PARSE-011": {
        "title": "The file is larger than 2.5 MB",
        "why": "Some systems stop parsing files larger than 2.5 MB.",
        "fix": "Remove or compress large images, then export again.",
        "detected_by": "file_structure", "refs": ["gh_parse_fail"]},
    "PARSE-012": {
        "title": "This file type may not be accepted or parsed well",
        "why": "Older .doc files, Pages files and unknown formats are often refused or parsed poorly.",
        "fix": "Save as .docx or as a text-based PDF, whichever the posting asks for.",
        "detected_by": "file_structure", "refs": []},
    "PARSE-013": {
        "title": "The PDF was made in a design tool",
        "why": "Design-tool PDFs often use layered text, columns or graphics that parse poorly.",
        "fix": "If you can, rebuild it in Word or Google Docs with a simple layout, and check that "
               "copied text comes out in order.",
        "detected_by": "file_structure", "refs": ["textkernel_getting_started"]},
    "PARSE-014": {
        "title": "Some words are letter-spaced, like \"S K I L L S\"",
        "why": "Parsers read spaced letters as separate one-letter words, so headings and names can "
               "be missed.",
        "fix": "Use normal letter spacing. Make headings stand out with bold or size instead.",
        "detected_by": "extracted_text", "refs": ["gh_parse_fail"],
        "variants": {"headings": {
            "title": "Section headings are letter-spaced, like \"E D U C A T I O N\"",
            "why": "The text comes out as separate letters, so a parser may not see an Education or "
                   "Experience heading at all and can file your details in the wrong place. This check "
                   "joined the letters back up; many systems won't.",
            "fix": "Type each heading as a normal word (\"Education\", \"Experience\"). Make headings "
                   "stand out with bold or size instead of letter spacing."}}},
    "PARSE-015": {
        "title": "Icon-font symbols will show up as boxes",
        "why": "Icons from icon fonts usually come out as blank boxes or random characters.",
        "fix": "Replace icons with plain words, such as \"Email:\" or \"Phone:\", or remove them.",
        "detected_by": "extracted_text", "refs": []},
    "PARSE-016": {
        "title": "Hidden text was found (white, tiny or hidden words)",
        "why": "Screening software shows recruiters the plain text, hidden words included. Recruiters "
               "read hidden keywords as stuffing.",
        "fix": "Delete all hidden, white or tiny text. Put real skills in visible bullets.",
        "honesty": "Hidden keywords show up in the plain-text view and can sink an application. "
                   "Hiring Panel never adds hidden text.",
        "detected_by": "file_structure", "refs": ["hidden_text_builtin"]},
    "PARSE-017": {
        "title": "Capital letters come from formatting, not the text",
        "why": "Extracted text keeps the letters you typed, so a parser may read a styled heading "
               "differently from what you see.",
        "fix": "Type headings in the case you want them to appear.",
        "detected_by": "file_structure", "refs": ["rchilli_tips_2020"]},
    "PARSE-018": {
        "title": "The file contains document fields",
        "why": "Document fields may come out as codes or blank space when the file is parsed.",
        "fix": "Replace fields with plain typed text.",
        "detected_by": "file_structure", "refs": ["rchilli_tips_2020"],
        "variants": {"ole": {"title": "The file contains embedded objects",
                             "why": "Embedded objects usually come out blank when the file is "
                                    "parsed.",
                             "fix": "Remove embedded objects and type their content as text."}}},
    "PARSE-019": {
        "title": "Tracked changes or comments are still in the file",
        "why": "Parsers may read deleted text or comments as part of your {doc}.",
        "fix": "Accept or reject all changes, delete all comments, then save a clean copy.",
        "detected_by": "file_structure", "refs": []},
    "PARSE-020": {
        "title": "Placeholder or template text is still in the file",
        "why": "Text like \"Company A\" or \"Lorem ipsum\" tells a reader the {doc} isn't finished, "
               "and parsers skip placeholder data.",
        "fix": "Replace every placeholder with your real details or delete it.",
        "detected_by": "extracted_text", "refs": ["gh_parse_fail"]},
    "PARSE-021": {
        "title": "Page numbers or footer text leak into the body",
        "why": "Repeated lines such as \"Page 1 of 2\" can split a section in the parsed text.",
        "fix": "Remove page numbers and repeated footer lines from the main text.",
        "detected_by": "extracted_text", "refs": []},
    "PARSE-022": {
        "title": "Your {doc} runs longer than {pages} pages",
        "why": "Long files parse fine, but readers skim. Every extra page also adds layout risk.",
        "fix": "Keep what supports this job and cut older or less relevant items first.",
        "detected_by": "file_structure", "refs": []},
    "PARSE-023": {
        "title": "Words may merge when tabs are dropped",
        "why": "Some parsers ignore tab characters. Text on each side of a tab can then run together, "
               "like \"AustinAustin, TX\".",
        "fix": "Put a space or a separator such as \" | \" before each tab, or write dates after a "
               "separator on the same line.",
        "detected_by": "file_structure", "refs": []},

    "PARSE-024": {
        "title": "Skill ratings are shown as dots, bars or stars",
        "why": "Rating symbols mean nothing to a parser. They come out as stray characters, and a reader "
               "can't tell what three dots out of five means.",
        "fix": "Drop the rating symbols. List the skill plainly, and show how you used it in a bullet.",
        "honesty": "Never turn dots into a level word you can't back up, such as \"advanced\".",
        "detected_by": "extracted_text", "refs": ["gh_parse_fail"]},

    "CONTACT-001": {
        "title": "No email address found",
        "why": "Recruiters and the system need an email address to reach you.",
        "fix": "Add an email address you check every day near the top of the page.",
        "detected_by": "extracted_text", "refs": []},
    "CONTACT-002": {
        "title": "No phone number found",
        "why": "Many recruiters call or text to schedule interviews.",
        "fix": "Add a phone number near the top, in the format used where you are applying.",
        "detected_by": "extracted_text", "refs": []},
    "CONTACT-003": {
        "title": "No location found",
        "why": "Recruiters often filter by location. Your city and region or country is enough.",
        "fix": "Add your city and region or country near the top, or \"Remote\" if that is accurate.",
        "detected_by": "extracted_text", "refs": []},
    "CONTACT-004": {
        "title": "No LinkedIn profile link",
        "why": "Many recruiters look for a LinkedIn profile. It is optional.",
        "fix": "If you have a LinkedIn profile, add its link next to your other contact details.",
        "detected_by": "extracted_text", "refs": []},
    "CONTACT-005": {
        "title": "Your full street address is listed",
        "why": "City and region are enough for screening. A street address adds privacy risk without "
               "helping you.",
        "fix": "Replace the street address with your city and state or region.",
        "detected_by": "extracted_text", "refs": []},
    "CONTACT-006": {
        "title": "Contact details are not near the top",
        "why": "Parsers and recruiters look for contact details in the first lines of the page.",
        "fix": "Move your email and phone into the first few lines, right under your name.",
        "detected_by": "extracted_text", "refs": []},
    "CONTACT-007": {
        "title": "More than one email address is listed",
        "why": "Two email addresses can confuse the parser about which one to use.",
        "fix": "Keep one email address that you check every day.",
        "detected_by": "extracted_text", "refs": []},

    "SECT-001": {
        "title": "No Education section found",
        "why": "For students, Education is one of the first things a screener looks for.",
        "fix": "Add an \"Education\" heading with your school, degree and graduation date (or "
               "expected date).",
        "detected_by": "extracted_text", "refs": []},
    "SECT-002": {
        "title": "No Experience, Projects or Leadership section found",
        "why": "Screeners look for a section that shows what you have done.",
        "fix": "Add an \"Experience\" or \"Projects\" section about real work: jobs, class projects, "
               "clubs or volunteering.",
        "detected_by": "extracted_text", "refs": [],
        "variants": {"no_experience": {
            "title": "No Experience section found",
            "why": "Your Projects or Leadership section helps, but many screeners look for an "
                   "Experience heading first.",
            "fix": "If you have any job, internship or volunteer role, list it under \"Experience\". "
                   "If not, a strong Projects section is fine."}}},
    "SECT-003": {
        "title": "No Skills section found",
        "why": "A Skills section helps keyword search and lets a recruiter scan your tools quickly.",
        "fix": "Add a short \"Skills\" section with tools you can back up with examples.",
        "detected_by": "extracted_text", "refs": []},
    "SECT-004": {
        "title": "A section heading is not a standard name",
        "why": "Parsers sort your {doc} into fields by its headings. Unusual names may be missed.",
        "fix": "Use standard headings such as Experience, Education, Projects and Skills.",
        "detected_by": "extracted_text", "refs": ["rchilli_tips_2020"]},
    "SECT-005": {
        "title": "A heading combines two sections",
        "why": "A combined heading such as \"Awards, Training\" can confuse where each item belongs.",
        "fix": "Split it into separate headings, or use the one name that fits most items.",
        "detected_by": "extracted_text", "refs": ["rchilli_tips_2020"]},
    "SECT-006": {
        "title": "References or \"references available upon request\" are included",
        "why": "This line uses space without adding information. A reference list also shares other "
               "people's contact details.",
        "fix": "Delete it. Share references only when an employer asks for them.",
        "detected_by": "extracted_text", "refs": []},

    "SECT-007": {
        "title": "A section heading wasn't recognized",
        "why": "Your {doc} seems to have this section, but its heading wasn't recognized. Parsers sort "
               "text into fields by heading, so your details may land in the wrong place.",
        "fix": "Put a plain heading such as \"Education\" or \"Experience\" on its own line, typed as "
               "a normal word.",
        "detected_by": "extracted_text", "refs": ["rchilli_tips_2020"]},

    "DATE-001": {
        "title": "Some entries have no dates",
        "why": "Parsers use dates to build your work history. Entries without dates may be dropped "
               "or misplaced.",
        "fix": "Add a month and year to each entry, for example \"Jun 2024 – Aug 2024\".",
        "detected_by": "extracted_text", "refs": ["rchilli_tips_2020"]},
    "DATE-002": {
        "title": "Some dates show only the year",
        "why": "Year-only dates make it hard for a parser to tell how long you held a role.",
        "fix": "Use month and year where you know them, for example \"Jan 2023 – May 2024\".",
        "detected_by": "extracted_text", "refs": ["rchilli_tips_2020"]},
    "DATE-003": {
        "title": "A date range is split across two lines",
        "why": "A parser may read only half of the range.",
        "fix": "Keep each date range on one line.",
        "detected_by": "extracted_text", "refs": ["rchilli_tips_2020"]},
    "DATE-004": {
        "title": "Date formats are mixed",
        "why": "Mixing styles such as \"Jan 2024\" and \"01/2023\" can confuse parsers.",
        "fix": "Pick one date style and use it everywhere.",
        "detected_by": "extracted_text", "refs": []},
    "DATE-005": {
        "title": "A start date comes after its end date",
        "why": "This looks like a typo, and it can break how a parser reads your history.",
        "fix": "Check those dates and correct the order.",
        "detected_by": "extracted_text", "refs": []},
    "DATE-006": {
        "title": "A future date isn't marked as expected",
        "why": "Without \"Expected\", a reader may think you already finished.",
        "fix": "Add \"Expected\" before future dates, for example \"Expected May 2027\".",
        "detected_by": "extracted_text", "refs": []},
    "DATE-007": {
        "title": "Entries are not in reverse-chronological order",
        "why": "Most readers expect the most recent item first in each section.",
        "fix": "Put current and most recent entries at the top of each section.",
        "detected_by": "extracted_text", "refs": []},
    "DATE-008": {
        "title": "Your dates show a gap or a recent pause",
        "why": "Some employers screen for recent activity. This is common and is not a mistake.",
        "fix": "If you want, add a one-line honest label for that time, such as \"Full-time "
               "student\" or \"Family caregiving\".",
        "honesty": "Use a true label only. Never invent a role to fill a gap.",
        "detected_by": "extracted_text", "refs": ["harvard_gazette_2021"]},
    "DATE-009": {
        "title": "Some years have only two digits",
        "why": "Two-digit years like \"06/24\" are easy for a parser to misread.",
        "fix": "Write four-digit years, for example \"Jun 2024\".",
        "detected_by": "extracted_text", "refs": ["rchilli_tips_2020"]},

    "KW-001": {
        "title": "Required job terms are missing from your {doc}",
        "why": "Recruiters search and filter by the posting's terms, and AI graders check each basic "
               "qualification against your {doc}.",
        "fix": "For each missing term you truly have, show it in a bullet about real work. If you "
               "don't have it, leave it out.",
        "honesty": KW_HONESTY,
        "detected_by": "jd_comparison", "refs": ["wd_hiredscore_2026_08", "gh_blog_after_apply"]},
    "KW-002": {
        "title": "Some job terms are only listed, not shown in your experience",
        "why": "A skill in a list is weaker evidence than a bullet that shows you using it.",
        "fix": "Where it is true, mention the skill in a bullet that describes the work you did with "
               "it.",
        "honesty": KW_HONESTY,
        "detected_by": "jd_comparison", "refs": ["wd_hiredscore_2026_08"]},
    "KW-003": {
        "title": "Your wording differs from the posting's",
        "why": "Some searches look for the exact words in the posting.",
        "fix": "Write both forms once, for example \"search engine optimization (SEO)\".",
        "honesty": KW_HONESTY,
        "detected_by": "jd_comparison", "refs": []},
    "KW-004": {
        "title": "The posting's job title doesn't appear on your {doc}",
        "why": "Recruiters often search by job title.",
        "fix": "Never change a past job title. If it fits, add a short headline under your name that "
               "names the role you are applying for.",
        "honesty": KW_HONESTY,
        "detected_by": "jd_comparison", "refs": []},
    "KW-005": {
        "title": "Preferred job terms are missing",
        "why": "Preferred terms are not required, but they can separate similar applicants.",
        "fix": "Add only the ones you can show in real work.",
        "honesty": KW_HONESTY,
        "detected_by": "jd_comparison", "refs": []},

    "CONTENT-001": {
        "title": "Few bullets show numbers",
        "why": "Numbers help a reader judge scale: how many, how often, how much, how fast.",
        "fix": "Use true scale or scope numbers (people, frequency, volume, time). Never estimate a "
               "number you can't defend.",
        "honesty": "Use only numbers you can explain. A range or \"about\" is fine when it is honest.",
        "detected_by": "heuristic", "refs": []},
    "CONTENT-002": {
        "title": "Some bullets start with weak openers",
        "why": "Openers like \"Responsible for\" describe duties, not what you did.",
        "fix": "Start with a verb that says what you did, such as \"Built\" or \"Organized\".",
        "honesty": "Keep your real role. \"Helped with\" should not become \"Led\".",
        "detected_by": "heuristic", "refs": []},
    "CONTENT-003": {
        "title": "Some bullets are longer than 35 words",
        "why": "Long bullets are hard to skim.",
        "fix": "Split them or trim each to one main point.",
        "detected_by": "heuristic", "refs": []},
    "CONTENT-004": {
        "title": "Some bullets are shorter than 5 words",
        "why": "Very short bullets often leave out what you did and why it mattered.",
        "fix": "Add the action and, if you know it, the result.",
        "detected_by": "heuristic", "refs": []},
    "CONTENT-005": {
        "title": "First-person words like \"I\" or \"my\" appear",
        "why": "A {doc} is usually written without \"I\" and \"my\".",
        "fix": "Start bullets with the verb, for example \"Organized\" instead of \"I organized\".",
        "detected_by": "heuristic", "refs": []},
    "CONTENT-006": {
        "title": "Many bullets start with the same word",
        "why": "Repeated openers make different work look the same.",
        "fix": "Vary the opening verbs so each bullet stands out, keeping each one accurate.",
        "detected_by": "heuristic", "refs": []},
    "CONTENT-007": {
        "title": "Past roles are written in present tense",
        "why": "Present tense suggests you still hold a role that has ended.",
        "fix": "Use past tense for roles that have ended.",
        "detected_by": "heuristic", "refs": []},
    "CONTENT-008": {
        "title": "Buzzwords appear without examples",
        "why": "Words like \"hard-working\" or \"team player\" don't show anything on their own.",
        "fix": "Replace them with a short, true example that shows the trait.",
        "detected_by": "heuristic", "refs": []},
    "CONTENT-009": {
        "title": "An entry has no bullets or more than 8",
        "why": "Entries with no detail are easy to skip. Very long entries bury your best points.",
        "fix": "Aim for 1 to 6 bullets per entry, most important first.",
        "detected_by": "heuristic", "refs": []},
    "CONTENT-010": {
        "title": "Job titles use abbreviations",
        "why": "Parsers and searches may not expand short forms like \"Sr.\" or \"Asst.\".",
        "fix": "Spell titles out, for example \"Senior\" and \"Assistant\".",
        "detected_by": "extracted_text", "refs": ["gh_parse_fail"]},
}

# Section names (ATS spec 7). "contact" is the block above the first heading.
SECTIONS = ("contact", "summary", "experience", "education", "skills", "projects", "certifications",
            "leadership_activities", "volunteer", "awards", "publications", "coursework", "languages",
            "interests", "references", "other")
ENTRY_SECTIONS = ("experience", "projects", "leadership_activities", "volunteer")
DATED_SECTIONS = ("experience", "leadership_activities", "volunteer", "education")
CHRONO_SECTIONS = ("experience", "leadership_activities", "volunteer", "education")
EVIDENCE_BY_SECTION = {
    "experience": "demonstrated", "projects": "demonstrated", "leadership_activities": "demonstrated",
    "volunteer": "demonstrated", "publications": "demonstrated",
    "skills": "listed", "certifications": "listed", "coursework": "listed", "languages": "listed",
    "education": "listed", "awards": "listed", "interests": "listed", "other": "listed",
    "references": "listed",
    "summary": "claimed", "contact": "claimed", "header_footer": "claimed",
}
EVIDENCE_RANK = {"demonstrated": 3, "listed": 2, "claimed": 1, "none": 0}
