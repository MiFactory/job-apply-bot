# Job Apply Bot

> **Created by [MiFactory](https://mifactory.ma) · concept & design: [mifactory.ma](https://mifactory.ma)** · free & open source (MIT)

Desktop app (Python + Playwright + Qt) that **reads job offers on LinkedIn and Indeed in a real Chrome window and applies for you** — using your CV, your search criteria and a growing list of automatic answers. Anything it cannot answer it asks you once, remembers it, and reuses it in every later application. It stops by itself at the platform's limit.

> ⚠️ Automating LinkedIn / Indeed is against their terms of service. Your account can be limited or banned. Use it at your own risk, with moderate volumes (20–40 applications a day), and only for your own applications. The bot never types or stores your password and never bypasses CAPTCHAs or security checks.

## Features

| Area | What it does |
|---|---|
| **GUI** (`gui.py`) | Left: drop CVs (PDF/DOCX, any language) + default motivation message per language + search criteria. Centre: the browser the bot drives (embedded in the window on Windows) and a log. Right: every parameter / question the bot answers automatically — edit, filter, add, delete. |
| **Profiles** | Several candidates in one install. Each profile has its own CVs, criteria, messages, learned answers, applications log and browser login session. |
| **CV analysis** | Reads a CV, detects skills, languages, years of experience and suggests job titles (`python main.py setup --cv ...`). |
| **Offer reading** | Opens each offer, reads title / company / location / description, scores it against your criteria, rejects junior / intern / excluded-company / wrong-country / wrong-language ads. |
| **Auto apply** | LinkedIn *Easy Apply* and Indeed *Apply*: fills every step (contact, salary, notice period, work permit, sponsorship, years of experience, language levels, radios, selects, cover letter), picks the CV that matches the ad's language, submits. |
| **Questions memory** | Unknown form question → red box in the GUI → you answer once → saved and reused. Unanswered ones are listed in red. |
| **Safety** | Dry-run mode (fills but does not submit), daily cap, stops at LinkedIn's limit, hands the browser to you on CAPTCHA / login / security checks, never ticks "follow company" or marketing boxes, never applies twice to the same offer. |
| **Log** | `applications.csv` (`;`-separated, opens directly in Excel FR): date, site, job id, title, company, location, URL, status, note. |
| **Google sign-in** | `Continue with Google` supported: you type the password/2-step code, the bot only picks the account. |
| **CLI** | Everything also works without the GUI (`main.py`). |

## Install

Requirements: Python 3.10+, Google Chrome (recommended; bundled Chromium is the fallback).

```bash
git clone https://github.com/MiFactory/job-apply-bot.git
cd job-apply-bot
pip install -r requirements.txt
python -m playwright install chromium
```

## Quick start (GUI)

```bash
python gui.py          # Windows: double-click run_gui.bat
```

1. Wait for Chrome to appear and the log to say **browser ready**. Click **🔑 LinkedIn** (and **🔑 Indeed**) and log in once — by hand, or with *Continue with Google*. The session is kept in your profile folder.
2. **Left › CV & message** — drop your CV(s). Language is detected (editable). Edit the default motivation message (`{title}`, `{company}`, `{full_name}`), click **Save**.
3. **Right** — check your parameters (name, phone, salary, notice period, work permit, sponsorship…). Edit any cell.
4. **Left › Search criteria** — job titles, locations, excluded words, days, sites, max per run. Keep **Dry-run** ticked for the first test.
5. **▶ Start applying**. When a red box appears, type the answer → **Save answer & continue** (or **Skip this job**).
6. When the dry-run looks right, untick Dry-run and run again.

Toolbar: `◧ Left` / `Right ◨` hide side panels · zoom `−/+` and slider · **Centre** slider moves the browser · **Browser** drop-down (*Inside (child)*, *Docked*, *Separate window*) + **🔄 Reopen browser**.

## Quick start (CLI)

```bash
python main.py setup --cv path/to/CV_EN.pdf --cv-fr path/to/CV_FR.pdf   # analyse CV, create profile + criteria
python main.py login --google you@gmail.com                              # or: python main.py login
python main.py run --dry-run --max 3                                     # test, nothing is submitted
python main.py run --max 30                                              # real run (--site linkedin|indeed|both, --unattended)
python main.py report                                                    # status counts + questions it could not answer
python main.py --profile "Alex" run                                      # pick a profile
```

## Scheduling & automatic retry

Run every chosen weekday at a set hour, and keep going after a LinkedIn limit without you.

* **GUI:** tick **⏰ Schedule** (centre panel), choose the days, the hour and the retry interval (default 5 min). The status line shows the next run. Keep the window open and the PC awake.
* **CLI (no window to watch):** `python main.py schedule --days mon-fri --time 09:00 --retry 5 [--max 30] [--now]` (settings are saved per profile in `data/profiles/<name>/schedule.json`, shared with the GUI).
* **LinkedIn limit:** the run stops, then the bot tests again every N minutes (a normal run that stops at once while the limit is active) and continues by itself as soon as applying works again. It gives up after 48 h and waits for the next scheduled day.
* **Your own daily cap** (`max_applications_per_day`) is not retried until the next scheduled day. **⏹ Stop** cancels the current retry cycle.
* Scheduled runs are unattended: unknown form questions are not asked, they are added in red to the right-hand list (answer them later; they are reused). A login or security check still pauses and waits for you.
* A run is only started while the app (or `main.py schedule`) is running: nothing happens if the PC is off.

## Project layout

```
gui.py                 Qt GUI (3 panels, profiles, browser embedding, question dialog)
main.py                CLI (setup / login / run / report)
jobbot/
  browser.py           Playwright persistent Chrome profile, human-check pause, Google sign-in helper, hooks (log/pause/stop)
  linkedin.py          LinkedIn search → offer → Easy Apply wizard
  indeed.py            Indeed search → offer → Indeed Apply wizard
  formfiller.py        Label → answer engine (profile rules → learned answers → ask the user)
  profile.py           Profile/criteria defaults, job scoring, language detection
  profiles.py          Multi-profile management (data/profiles/<name>/)
  cv_analyzer.py       CV text extraction + skill/language/title suggestions
  store.py             applications.csv, answers.json, pending questions
  runner.py            Shared run loop used by CLI and GUI
examples/              Fictive sample profile / criteria / messages / answers
docs/                  How it works · Configuration reference · Troubleshooting
tests/                 Offline test of the form filler
```

## Your data stays local

Everything personal lives in `data/` (git-ignored): `data/profiles/<name>/{profile,criteria,motivation,answers}.json`, `applications.csv`, `browser_profile/` (your login session). Nothing is sent anywhere except to LinkedIn / Indeed through your own browser. The repository ships only **fictive example data** (`examples/`, "Alex Martin").

## More

- [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) — architecture, the apply loop, the answer engine, threading, browser embedding
- [docs/CONFIGURATION.md](docs/CONFIGURATION.md) — every setting in `profile.json` / `criteria.json`
- [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) — common problems and fixes
- `python tests/test_formfiller.py` — offline self-test

## Status / limitations

- LinkedIn and Indeed change their pages regularly: if clicks fail, fix the selectors in `jobbot/linkedin.py` / `jobbot/indeed.py` (one place per site).
- Indeed applications that redirect to a company site are skipped.
- Embedding Chrome inside the window is Windows-only; other systems use a separate window.

## Credits

**Job Apply Bot** was created by **MiFactory — [mifactory.ma](https://mifactory.ma)**, who also made the concept and the design of the app. Please keep this credit when you share or fork it (the MIT licence requires keeping the copyright notice).

## License

[MIT](LICENSE) — free for any use (personal or commercial): use, copy, modify, share. Provided "as is", without warranty. Use it responsibly and at your own risk (see the terms-of-service warning above).

## Contributing

Bugs and fixes are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). Typical fix: update a changed selector in `jobbot/linkedin.py` / `jobbot/indeed.py`, run `python tests/test_formfiller.py`, open a pull request.
