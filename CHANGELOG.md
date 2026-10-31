# Changelog

## 1.1.0
**New**
- Scheduling: run on chosen weekdays at a chosen hour (GUI row **⏰ Schedule** or `python main.py schedule --days mon-fri --time 09:00`).
- Automatic retry: after a LinkedIn limit the bot tests again every N minutes (default 5) and continues by itself when applying works again.
- Credits / About box: created by MiFactory (mifactory.ma), concept & design: mifactory.ma. `python main.py --version`.
- Full test suite (`python tests/run_all.py`): unit, robustness/fuzz, CLI, GUI (headless) and browser end-to-end tests against a local fake LinkedIn.

**Fixed** (found by the new tests)
- `--dry-run` on LinkedIn pressed *Submit application* (it only should have looked at the button). It now never clicks Submit.
- "Skip this job" typed the text `None` into the form and submitted the application; it now skips the job.
- The LinkedIn limit detection was far too broad (any page text containing "limit" could stop a run); it now matches real limit messages only (EN/FR/NL).
- Ambiguous form labels were auto-answered wrongly ("Do you *understand*…" → city, "Are you *available* on weekends?" → notice period, "email marketing", "mobile app"…); they are now asked instead.
- Corrupt / empty / BOM-prefixed / non-object JSON files (profile, criteria, answers, motivation, schedule) no longer crash the app (a `.bad` copy is kept).
- Consent checkboxes wrapped in a `<label>` were not recognised.
- Concurrent writes to the applications log could lose a row (now locked).
- Scheduled runs never open a modal dialog nobody could close.
- Friendly errors for invalid `--days` / `--time`.
