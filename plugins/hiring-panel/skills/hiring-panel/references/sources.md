# Sources

Where the panel's personas, the screening check and the product's platform decisions come
from. Read this when a student asks "says who?". Quote carefully: several figures come from
vendors or small samples, and the labels below say so.

Collected October 2026. Web pages change; treat dates as "last checked".

## Quality labels

| Label | Meaning |
|---|---|
| **Primary** | Official documentation or the institution's own page, read directly. |
| **Primary (summary only)** | Official page seen only through a search-engine summary; the page itself didn't load. |
| **Study** | A survey, interview set or test. The sponsor is noted; vendor studies are marked. |
| **Academic** | Peer-reviewed paper or academic preprint. |
| **Secondary** | Blog, press coverage or marketing. Not independently verified. |
| **Design** | Our own product judgment. No outside source claims it. |

## How applicant tracking systems actually behave (the screening check)

| Source | Label | What it supports |
|---|---|---|
| Greenhouse, "Unsuccessful resume parse" https://support.greenhouse.io/hc/en-us/articles/200989175-Unsuccessful-resume-parse | Primary | Parse failures: 2.5 MB limit, placeholder text, graphics, image uploads, tables, headers and footers, contact details in headers, footers or text boxes, columns, letter-spaced text, abbreviated titles. |
| Greenhouse, "Application Rules Overview" https://support.greenhouse.io/hc/en-us/articles/203105595-Application-Rules-Overview | Primary | Auto-reject and auto-advance fire on application-question answers (some plans), not on resume prose. |
| Greenhouse blog, "What really happens after you apply" https://my.greenhouse.com/blogs/what-really-happens-after-you-apply-for-a-job | Primary | Auto-rejection is recruiter-set rules; AI suggests keywords for recruiter searches. |
| Greenhouse newsroom, May 2025 https://www.greenhouse.com/newsroom/greenhouse-unveils-new-ai-driven-products-at-unleash-to-streamline-hiring-in-saturated-job-market | Primary | AI filters for years of experience and skills. |
| Workday admin guide, parsing https://doc.workday.com/admin-guide/en-us/human-capital-management/recruiting/candidates/set-up-prospects-and-candidates/hdc1552497830785.html | Primary | Parsing varies with format and word order; Skills and Languages fields aren't filled by parsing. |
| Workday HiredScore release notes, Aug 2026 https://doc.workday.com/hiredscore/en-us/workday-hiredscore/hiredscore-release-notes/2026/august/wednesday--5th-august.html | Primary | A to D grades; an LLM checks each qualification against the parsed resume; basic qualifications decide the top grades. |
| Oracle Taleo, candidate prescreening https://docs.oracle.com/en/cloud/saas/taleo-enterprise/20b/otrec/candidate-prescreening.html | Primary | Disqualification questions can end an application; Required versus Asset criteria. |
| Oracle Taleo, disqualification questions https://docs.oracle.com/en/cloud/saas/taleo-enterprise/23c/otfru/t-createdusqualificationquestioninlibrary.html | Primary | Answers set to pass, disqualify or verify. |
| Textkernel, resume parser getting started https://developer.textkernel.com/tx-platform/v9/resume-parser/overview/getting-started/ | Primary | Check the converted text first; scans need OCR; design-heavy resumes parse poorly. |
| RChilli, "Tips for Creating Awesome Electronic Resumes" (2020) https://docs.rchilli.com/resumeparser/Tips%20for%20Creating%20Awesome%20Electronic%20Resumes.pdf | Primary (parser vendor) | PDF columns read left first; headers and footers ignored; tables; capitals by formatting; combined headings; year-only and split dates. |
| Lever, resume parsing https://help.lever.co/hc/en-us/articles/20087345054749 | Primary (summary only) | Image files can't be parsed; if you can't highlight the text, it likely won't parse. |
| Lever, auto-archive https://help.lever.co/hc/en-us/articles/20087374094365 | Primary (summary only) | Knockout questions commonly auto-archive candidates. |
| iCIMS Role Fit release notes (2021) https://community.icims.com/articles/Knowledge/Release-Notes-Winter-Release-2021-iCIMS-Talent-Cloud-AI | Primary (summary only) | Candidate ranking per job once the AI module is on. |
| Jobscan tutorial https://www.jobscan.co/jobscan-tutorial | Primary (vendor) | Recommends a match rate; publishes no formula or outcome calibration. |
| Jobscan, resume keywords https://www.jobscan.co/blog/resume-keywords/ | Secondary (vendor) | Recruiters filter and search, often by job title first. |
| Jobscan, ATS-friendly templates https://jobscan.co/blog/20-ats-friendly-resume-templates/ | Secondary (vendor) | Single-column, standard-heading layout guidance. |
| Harvard Gazette on Fuller, 2021 https://news.harvard.edu/gazette/story/2021/09/new-study-says-hidden-workers-are-being-excluded/ | Primary | Half of US companies filter out applicants not employed in the last six months (why gaps are noted, never penalized). |
| HBS and Accenture, "Hidden Workers" (2021) https://nahr.shrm.org/sites/default/files/hiddenworkers09032021.pdf ; coverage https://www.theregister.com/2021/09/08/harvard_jobs_report/ | Study | 88% (high-skill) and 94% (middle-skill) of employers say qualified people are screened out for not matching exact criteria. |
| Enhancv, recruiter interviews (2025) https://enhancv.com/blog/does-ats-reject-resumes/ ; coverage https://betanews.com/2025/11/10/study-debunks-viral-claim-that-ai-filters-out-most-job-applicants/ | Study (vendor, 25 recruiters) | Most say content doesn't auto-reject; knockout questions are the common automatic filter; entry-level roles draw hundreds of applications in days. |
| Enhancv, two-column extraction test https://enhancv.com/blog/two-column-resume-ats-test/ | Study (vendor) | Columns keep words but can scramble section order. |
| "75% rejected" myth https://itbrief.co.uk/story/study-reveals-ats-rarely-auto-rejects-cvs-debunks-75-myth | Secondary | The famous figure traces to a 2012 marketing claim. |
| Hidden prompts in resumes https://builtin.com/articles/hidden-ai-prompts-in-resume | Secondary | Roughly 1% of resumes carry hidden text (Greenhouse estimate); recruiters reject it. |
| Mobley v. Workday commentary https://www.lawandtheworkplace.com/?p=10832 | Secondary | Ongoing litigation over AI screening (why we describe vendors carefully). |
| O*NET license https://www.onetcenter.org/license_agreements.html | Primary (summary only) | Most O*NET content is CC BY 4.0 (credited in NOTICE if used). |
| Lightcast open terms https://legal.lightcast.io/lightcast-legal/open-terms-of-use | Primary | Why Lightcast skill data isn't redistributed. |

## The seven personas

| Source | Label | Used by | What it supports |
|---|---|---|---|
| Sackett, Zhang, Berry and Lievens (2022), via SIOP TIP https://www.siop.org/tip-article/is-cognitive-ability-the-best-predictor-of-job-performance | Academic (via summary) | Hiring Manager | Structured interviews, job knowledge and work samples predict performance, so managers look for proof of doing the work. |
| Laszlo Bock's X-Y-Z formula https://www.businessinsider.in/googles-former-hr-boss-says-this-is-the-key-to-a-perfect-resume/articleshow/54925993.cms | Secondary | Hiring Manager, CEO, Skeptic | "Accomplished X as measured by Y by doing Z." |
| NACE, what employers seek on a resume https://naceweb.org/talent-acquisition/candidate-selection/what-employers-seek-on-a-resume | Study | Hiring Manager, Future Teammate | Problem solving, teamwork, communication and initiative are the most sought attributes. |
| NACE, GPA screening https://naceweb.org/talent-acquisition/candidate-selection/use-of-gpa-as-candidate-selection-tool-falls | Study | Recruiter | Fewer employers screen by GPA (46.3% in Job Outlook 2022); 3.0 is the common cutoff (US only). |
| Ladders eye-tracking study (2012), original https://www.bu.edu/com/files/2018/10/TheLadders-EyeTracking-StudyC2.pdf ; summary https://flowingdata.com/2012/04/11/how-recruiters-look-at-your-resume/ | Study (vendor, 30 recruiters) | Recruiter | About 6 seconds on the first fit decision, mostly on six data points. |
| Ladders update (2018) https://onrec.com/news/news-archive/ladders-updates-popular-recruiter-eye-tracking-study-with-new-key-insights-how-job | Secondary (coverage of a vendor study) | Recruiter, Screening | About 7.4 seconds; simple layouts did best, multi-column clutter worst. |
| CareerBuilder and Harris Poll (2017 to 2018) https://www.cbia.com/news/hr-safety/resume-lies/ | Study (vendor-commissioned) | Recruiter | Many hiring managers spend under a minute per resume. |
| Bohnet, van Geen and Bazerman (2016) https://hbswk.hbs.edu/item/when-performance-trumps-gender-bias-joint-versus-separate-evaluation | Academic (via summary) | Competing Applicant | Side-by-side comparison shifts decisions toward performance evidence. |
| LinkedIn application volume (2025) https://www.eweek.com/de/news/ai-job-applications-linkedin/ | Secondary | Competing Applicant | Very high application volume; AI-written resumes look alike. Figures vary by source. |
| Netflix culture memo, keeper test https://jobs.netflix.com/culture | Primary | CEO | "Would I fight to keep them?" |
| Amazon Leadership Principles https://www.aboutamazon.com/about-us/leadership-principles | Primary | CEO | Ownership, deliver results, customer obsession. |
| Google re:Work, team effectiveness https://rework.withgoogle.com/en/guides/understanding-team-effectiveness | Primary | Future Teammate | Dependability and how people work together matter most. Also the source of the four-level rubric (poor, borderline, solid, outstanding). |
| Amazon, how Amazon hires (Bar Raiser) https://www.aboutamazon.com/news/workplace/how-amazon-hires | Primary | Skeptic | An outside reviewer who protects a fair, accurate assessment. |
| CareerBuilder and Harris Poll (2014) https://www.cutimes.com/amp/2014/08/19/jobseekers-often-lie-on-resumes-careerbuilder/ | Study (vendor-commissioned) | Skeptic | Embellished skills and responsibilities are the lies most often caught. |
| CareerBuilder (2006) https://creativepro.com/fifty-seven-percent-of-hiring-managers-say-they-have-caught-a-lie-on-a-resume-careerbuilder-com-survey-finds | Study (vendor, older) | Skeptic | Most managers who caught a lie didn't hire. |

## Why the panel works the way it does

| Source | Label | What it supports |
|---|---|---|
| Zheng et al. (2023), LLM-as-a-judge https://arxiv.org/pdf/2306.05685 | Academic | Model judges have position and self-preference biases, so evidence is checked by script. |
| Stureborg et al. (2024) https://arxiv.org/pdf/2405.01724 | Academic (preprint) | Model numeric ratings are inconsistent, so there are no per-reviewer scores. |
| Choi, Zhu and Li (NeurIPS 2025) https://arxiv.org/abs/2508.17536 | Academic | Independent answers plus voting capture most of the benefit of multi-agent debate. |
| Kapetanovic et al. (2026) https://arxiv.org/pdf/2608.25869 | Academic (preprint; abstract read) | Anchoring on earlier output in one conversation; why single-chat mode is disclosed and weighted down. |
| Panickssery, Bowman and Feng (NeurIPS 2024) https://arxiv.org/abs/2404.13076 | Academic | Models favor text they wrote, so "after" verdicts need fresh reviewers and are labeled directional. |
| Anthropic, multi-agent research system https://www.anthropic.com/engineering/multi-agent-research-system | Primary | Parallel subagents with separate contexts. |
| Amazon Bar Raiser debrief https://www.aboutamazon.com/news/workplace/how-amazon-hires | Primary | Show disagreement instead of averaging it away. |

## Platform facts (install, sandbox, privacy)

| Source | Label | What it supports |
|---|---|---|
| Claude plugins overview https://claude.com/docs/plugins/overview | Primary (checked 2026-10-20) | Customize > Plugins; Add marketplace with owner/repo; Upload plugin as .zip or .plugin; Sync automatically; plugins sync to Claude Code (`/reload-plugins`). |
| Plugin structure and platform support https://claude.com/docs/plugins/build ; https://claude.com/docs/plugins/platform-support | Primary | One plugin folder works in chat, Cowork and Claude Code; agents are ignored in chat. |
| Claude Code, install plugins https://code.claude.com/docs/en/plugins/install | Primary (checked 2026-10-20) | `/plugin marketplace add`, `/plugin install name@marketplace`, auto-update off by default for third-party marketplaces, skills invoked as `/plugin:skill`. |
| Claude Code, marketplaces https://code.claude.com/docs/en/plugins/create-marketplace ; https://code.claude.com/docs/en/plugins/marketplace-reference | Primary | marketplace.json format; relative plugin sources. |
| Claude Code, plugin components and evals https://code.claude.com/docs/en/plugins/components ; https://code.claude.com/docs/en/plugin-evals | Primary | What a plugin may contain; `claude plugin eval` for behavior tests. |
| Claude skills how-to https://claude.com/docs/skills/how-to | Primary | Packaging a skill folder as a zip for upload. |
| Agent Skills reference validator https://github.com/agentskills/agentskills/tree/main/skills-ref | Primary (code) | A validator for the SKILL.md format. |
| Claude Code, skills https://code.claude.com/docs/en/skills | Primary (checked 2026-10-20) | `${CLAUDE_SKILL_DIR}` is filled in only by Claude Code; allowed-tools pre-approval lasts one turn; argument placeholders. |
| Claude Code, subagents https://code.claude.com/docs/en/sub-agents | Primary (checked 2026-10-20) | Fresh isolated context per subagent; per-call model; 20 concurrent by default; transcripts kept locally for 30 days by default. |
| Creating custom skills https://support.claude.com/en/articles/12512198-creating-custom-skills | Primary | 200-character description limit; the skill folder sits at the zip root. |
| Using skills in Claude https://support.claude.com/en/articles/12512180-using-skills-in-claude | Primary | Skills work on Free, Pro, Max, Team and Enterprise with code execution on; Customize > Skills upload. |
| Create and edit files https://support.claude.com/en/articles/12111783-create-and-edit-files-with-claude | Primary | The code execution and file creation setting. |
| Claude Code plans https://support.claude.com/en/articles/11145838 | Primary | Claude Code comes with Pro and Max. |
| Agent Skills overview https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview ; code execution tool https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool | Primary | Sandbox constraints; preinstalled packages differ by surface, so our scripts use the standard library only. |
| Agent Skills specification https://agentskills.io/specification | Primary | SKILL.md format; keep it under 500 lines. |
| Anthropic consumer terms https://www.anthropic.com/legal/consumer-terms ; 2025 update https://www.anthropic.com/news/updates-to-our-consumer-terms | Primary | Users must be 18+; chat retention depends on the training setting (check the current terms). |
| GitHub, linking to releases https://docs.github.com/en/repositories/releasing-projects-on-github/linking-to-releases | Primary | `/releases/latest/download/<file>` is a stable download link. |
| Safari auto-unzips downloads https://kb.yoast.com/kb/safari-automatically-unzips-archive/ | Secondary | Why the README has a Safari note and offers a .plugin file. |
| macOS python3 stub https://developer.apple.com/forums/thread/712657 | Secondary (forum) | `/usr/bin/python3` can trigger the developer-tools install pop-up, hence `xcode-select -p` first. |
| Chrome headless printing https://developer.chrome.com/docs/automation-and-testing/headless-cli ; https://developer.chrome.com/docs/chromium/new-headless | Primary | The PDF engine flags. |
| Anthropic docx skill, LibreOffice wrapper https://github.com/anthropics/skills/blob/main/skills/docx/scripts/office/soffice.py | Primary (code) | LibreOffice as a PDF route in sandboxes. |
| Edge headless exit-code report https://www.powershellgallery.com/packages/CopilotAtelier/3.0.0/Content/Skills%5Cevidence-package-assembly%5Cscripts%5CBuild-EvidencePackage.ps1 | Secondary (community script) | Edge can exit 0 without writing a PDF, so the renderer checks the file itself. |
| Windows tar https://winaero.com/windows-10-now-supports-tar-curl/ | Secondary | tar.exe ships with Windows 10 and later (manual-mode zip route, less tested). |
| Arial and Liberation Sans metrics https://en.wikipedia.org/wiki/Arial ; https://en.wikipedia.org/wiki/Liberation_fonts | Secondary | Same character widths, so Word and PDF break lines alike. |

## Our own design choices (no outside source)

These are product judgment. Never present them as research findings.

- The screening formula: Overall = 40% file readability + 40% job-keyword match + 20%
  content signals, rounded to steps of 5. Keyword match weights required terms 0.70,
  preferred 0.20 and evidence in experience 0.10. Band cutoffs.
- Content thresholds: bullets over 35 words, under 35% of bullets quantified, under 70%
  starting with an action verb, more than 8 bullets per entry.
- The ranking: severity weights 8, 4, 2, 1; hiring-stage weights 1.5, 1.4, 1.25, 1.0;
  confidence and requirement weights; agreement weight 0.5 in parallel mode and 0.3 in
  single-conversation modes.
- Lens limits (at most 2 findings outside a reviewer's lens), the 7-question batch (8 for
  the builder interview), the 300-character rule for posting links.
- Release gate: readability at least 90, no critical or high parse issue, at least 98% of
  words recovered from the PDF.

## Quoting rules

- Vendor studies (Ladders, Enhancv, Jobscan, CareerBuilder) have small or self-selected
  samples. Say "a vendor survey found", never "studies prove".
- Never say a named system "rejects" resumes for formatting. Their documents don't say
  that; they say parsing gets worse.
- No statistic about the real applicant pool for a specific job exists in this skill. The
  Competing Applicant's benchmark is an assumption built from the posting.
