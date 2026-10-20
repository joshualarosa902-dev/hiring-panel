# Simulated screening check

This is a simulation, not a real applicant tracking system. The note at the end explains what it can and can't tell you.

**Overall: 90 (Ready to send)**

- Machine readability: 100 (Clean)
- Job-keyword match: 80 (Strong match). Required terms: 5 of 6 found (2 only in your skills list).
- Content signals: 85 (Polished)

Scores move in steps of 5 on purpose. A 70 and a 75 are not meaningfully different. The counts and the issue list matter more than the number.

Overall = 40% file readability + 40% job-keyword match + 20% content signals, rounded to steps of 5. Weights are our judgment, not calibrated to hiring outcomes.

## Biggest issues first

1. **Required job terms are missing from your resume** (Medium, KW-001)
   - Seen: Not found: "communication".
   - Why it matters: Recruiters search and filter by the posting's terms, and AI graders check each basic qualification against your resume.
   - Fix: For each missing term you truly have, show it in a bullet about real work. If you don't have it, leave it out.
   - Honesty: Only add a term you can back up in an interview.
2. **Some job terms are only listed, not shown in your experience** (Medium, KW-002)
   - Seen: "SQL" appears only in a list, not in a bullet about your work; "VLOOKUP" appears only in a list, not in a bullet about your work; "Mailchimp" appears only in a list, not in a bullet about your work.
   - Why it matters: A skill in a list is weaker evidence than a bullet that shows you using it.
   - Fix: Where it is true, mention the skill in a bullet that describes the work you did with it.
   - Honesty: Only add a term you can back up in an interview.
3. **Some bullets start with weak openers** (Low, CONTENT-002)
   - Seen: Responsible for the weekly email newsletter to about 600 subscribers; Helped with Instagram posts 3x a week and tracked likes in a spreadsheet; Helped organize 2 Excel workshops for first-year students.
   - Why it matters: Openers like "Responsible for" describe duties, not what you did.
   - Fix: Start with a verb that says what you did, such as "Built" or "Organized".
   - Honesty: Keep your real role. "Helped with" should not become "Led".

## Notes (not scored)

- **Preferred job terms are missing** (KW-005). Add only the ones you can show in real work. Seen: Not found: "dashboards"; Not found: "A/B testing".

## Job keywords

| Term | Importance | Status | Where on your resume |
|---|---|---|---|
| SQL | Required | Found | Coursework, Skills (only in a list) |
| Microsoft Excel | Required | Found | Experience, Leadership, Projects, Skills (shown in your experience) |
| Business Analytics, Marketing, Statistics | Required | Found ("Business Analytics") | Education (shown in your experience) |
| pivot tables | Required | Found | Projects, Skills (shown in your experience) |
| VLOOKUP | Required | Found | Skills (only in a list) |
| communication | Required | Not found | - |
| dashboards | Duties | Not found | - |
| sales | Duties | Found | Experience (shown in your experience) |
| A/B testing | Duties | Not found | - |
| CRM | Duties | Not found | - |
| marketing | Duties | Found | Experience, Projects, Coursework, Education (shown in your experience) |
| Tableau or Power BI | Preferred | Not found | - |
| Google Analytics | Preferred | Not found | - |
| email marketing | Preferred | Found | Experience, Skills (shown in your experience) |
| Mailchimp | Preferred | Found | Skills (only in a list) |
| Marketing Analytics | Other | Partly found | Education (only in a list) |

Only add a term you can back up in an interview.

## Questions the application may ask (not scored)

- **On-site or hybrid** (Unclear): "Northwind Foods – Columbus, OH (Hybrid)" The posting sets where you work. Answer honestly in the application; your resume doesn't need to address it.
- **Degree** (Looks met): "Currently pursuing a bachelor's degree in Business Analytics, Marketing, Statistics or a related field" Make sure your degree and graduation date (or expected date) are written out in your Education section.
- **Major** (Looks met): "Currently pursuing a bachelor's degree in Business Analytics, Marketing, Statistics or a related field" Make sure your major is written out in your Education section.
- **Work authorization** (Application question): "Applicants must be authorized to work in the United States." This is usually an application question. Answer truthfully; the resume can't and shouldn't address it.
- **Visa sponsorship** (Application question): "Northwind Foods does not sponsor visas for this role." This is usually an application question. Answer truthfully; the resume can't and shouldn't address it.

## What the parser read

- Contact: name found, email found, phone found, location found, LinkedIn found.
- Contact as read (masked): r***@e***.com, ***-***-0147
- Sections in order: Education, Experience, Projects, Leadership, Skills.
- Dated entries: 5. Gaps longer than 6 months: 0 (for your information only).
- Text was read with: docx-xml.

## Limitations

- We don't run Workday, Greenhouse, Lever, iCIMS or Taleo; their parsers differ by vendor, version and employer settings.
- Our text extraction stands in for theirs (method: docx-xml).
- The skills dictionary is finite, and AI matchers may credit related experience differently.
- We can't see the application questions the employer set up.
- Scores aren't probabilities and aren't calibrated against interview outcomes.
- Column detection is limited to Word section settings.
- Dates are read to the month; seasons are approximated.

## About this check

This is a simulation, not a real applicant tracking system. Every employer sets up its own software, and none of the big vendors publish exactly how they parse or rank resumes. This check looks for problems known to break resume parsing and for job-description requirements your resume doesn't show. A high score doesn't guarantee an interview, and a low score doesn't mean a robot rejected you. Most automatic rejections come from application questions (work authorization, location, degree, availability), and no resume edit changes those.
