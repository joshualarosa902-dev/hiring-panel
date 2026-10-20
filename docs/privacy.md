# Privacy

A resume holds your name, contact details, schools and work history. Here's exactly where
that information goes when you use Hiring Panel.

## What Hiring Panel's own code does

- **Runs where Claude runs.** On claude.ai, the scripts run inside that chat's code
  execution sandbox. In Claude Code, they run on your computer.
- **No network calls, no telemetry.** The scripts use only the Python standard library and
  never connect to the internet. Nothing is counted, logged remotely or sent to me or
  anyone else. The automated tests block network access and fail if any code tries.
- **One run folder.** Every run writes into its own folder:
  - Claude Code: `hiring-panel-runs/<date>-<company>-<role>/` inside the folder you
    started Claude Code in.
  - claude.ai: the sandbox's outputs folder. The six finished files are also offered as
    downloads in the chat.
- **Protected from git.** The `hiring-panel-runs` folder gets its own `.gitignore`
  containing `*`, so the files aren't committed by accident. If the folder is inside a git
  repository, Claude warns you once anyway.
- **Masked contact details.** Your email address and phone number are masked in the
  report and in the chat summaries. Your resume files keep them, of course.
- **Clean files.** The generated resume lists you as the author and contains nothing that
  names the tool.
- **Other people stay private.** If one of your answers mentions someone else (for
  example a relative you help care for), the resume and the report use only a short label
  for your own role, such as "Family caregiver". Their health and other personal details
  never go into either file. Your answers themselves are kept word for word in the run
  folder's `work/answers.json`, so delete the folder if you'd rather not keep them.

## What a run folder contains

Your deliverables (resume and report), plus a `work/` folder with: an exact copy of the
file you uploaded, the text extracted from it, the job posting, the seven reviews, the
ranking, your answers, the rewrite data and the checks. Delete the folder whenever you
like; nothing else depends on it.

## What Claude itself keeps

Hiring Panel runs inside a normal Claude conversation, so your Claude account's settings
apply:

- **Training and retention.** In **Settings > Privacy**, the **Help improve Claude**
  setting controls whether your chats may be used to improve Anthropic's models, and how
  long chats are kept depends on it. The current rules are in
  [Anthropic's consumer terms](https://www.anthropic.com/legal/consumer-terms) and the
  [2025 update](https://www.anthropic.com/news/updates-to-our-consumer-terms). You can
  delete the chat after your run.
- **Claude Code transcripts.** Claude Code saves conversation transcripts on your
  computer, including each reviewer's, under `~/.claude/projects/`. By default it deletes
  them after 30 days.
- **School or work accounts.** Your organization's admins may have their own retention
  and access rules.

## Tips

- Use a personal Claude account for your job search if you can.
- Remove other people's phone numbers and emails (for example, references) from your
  resume before uploading; the panel will suggest that anyway.
- **Never paste your real resume into a GitHub issue.** Issues are public. Use made-up or
  redacted text when reporting a bug.

Questions or a privacy problem? See [SECURITY.md](../SECURITY.md).
