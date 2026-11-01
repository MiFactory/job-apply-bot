# Changelog

## 1.3.6
- **Default answers instead of skipping**: when no rule, CV evidence or earlier answer fits, the bot now answers by default policy — yes · at least 2 years · notice/availability "1 month" · salary "Conventional" (else first option) — instead of asking/skipping. Sensitive questions (gender, health, birth date…) are never guessed. Switch off with `"default_answers": false` in profile.json.
- **Radio options were empty** (`['','']`) on the new LinkedIn form: question now read from the input's aria-label and the option text from the element next to the input.
- Job details retry (5x) with page-title fallback ("job details did not load").
- "Could not find next/submit button" now logs the visible buttons and the form text to the log file.

## 1.3.5
- **Wrong question text ("Yes")**: on the new LinkedIn form, Yes/No questions have no fieldset, so the bot took the first answer ("Yes") as the question and asked you about it. The question is now read from the text just above the options.
- Language levels in any language now match the form's options (Native → "Natif ou bilingue", Fluent → "Professionnel", …), with the nearest level as fallback.
- Jobs already marked "Candidature envoyée" / "Applied" on the card are skipped without opening them.

## 1.3.4
- **All jobs of a results page are now processed** (new layout): the bot counted only 3–5 "cards"; it now reads the ~25 job cards of each page (job id from the card itself) and goes through pages 1–4, so a search with 99 results is fully covered.

## 1.3.3
- **LinkedIn's new results layout** (`/jobs/search-results/`, scrambled class names): job cards and the job details (title, company, location, description) are now found without class names, so searches no longer report "0 job card(s)" while jobs are visible. The old layout still works.
- The Easy Apply form of the new layout is a native `<dialog>` on the job's own page: it is now found (before, every job ended as "modal did not open"), and after each job the bot returns to the results list by itself. Every job now logs its result (`→ result: APPLIED / DRY_RUN / SKIP … reason`).

## 1.3.1
- **Belgium search no longer lands in Paris**: LinkedIn searches now send the country ID (Belgium, France, Luxembourg, …), so the location text can't fall back to your profile city. A warning is logged if LinkedIn still searches elsewhere.
- **Run log** `data/logs/jobbot.log` (GUI button 📄 Log): every message plus each error with full stack trace, the page URL/title and the step the bot was on.
- Every skipped job now shows its reason in the log; every search page shows how many job cards it found; a reminder is logged when Dry-run is ON (nothing is submitted).
- Fixed "Navigation … interrupted by another navigation" at login (retry), and search-box suggestion lists no longer reported as closed pop-ups.

## 1.3.0
**New**
- **Answers itself when you don't:** unknown form questions wait for you (default 30 s, *Wait for my answer* in Search criteria, `answer_timeout_seconds`, 0 = forever), then the bot answers from your **CV, profile and earlier answers** (`jobbot/answerer.py`). Experience / skill / certificate questions are answered *yes* only if the CV shows it (otherwise *no* / *0*), willingness questions (relocate, travel, start now…) *yes*, years from the CV, open questions composed from the CV. **Sensitive questions (gender, disability, ethnicity, religion, criminal record, birth date, nationality, health, bank…) are never guessed** ("prefer not to say" if offered, else the job waits for you).
- Guessed answers are saved with an **auto** mark (orange *auto (CV guess)* in the right-hand list); correct one and it becomes a normal answer. Switch off with *auto_answer* = false. The question box shows the suggestion and a countdown. CLI: suggestion + timed prompt.

- **Draft applications:** saved-jobs runs (⭐ button, *Saved jobs* setting) now also finish your LinkedIn **drafts** (*Suivi des emplois › Brouillon*, applications you started but never sent). Checkbox *Also finish my draft applications* / `include_drafts`.

**Fixed**
- **Saved job: "nothing clickable after 15s"** — the Easy Apply button is now found by its text (also «Continuer la candidature») and, if an overlay covers it, clicked directly; a disabled button is never forced.
- **Bot "only saved" jobs and moved on:** a dry run logged jobs as final, so a real run never applied to them. `DRY_RUN` and `ERROR` jobs are now retried; `NEEDS_INFO` jobs are retried once their question is answered.
- The dry run left the half-filled Easy Apply form open, covering the next job (repeated `Locator.click: Timeout` on the same job). It is now closed after every dry run / skipped job.
- Stale detail pane: after a click the bot checks that LinkedIn really switched to that job (URL `currentJobId` / title), retries the click once, otherwise skips it.
- Getting stuck: after 4 failed jobs in a row the page is reloaded, after 8 the rest of that page is skipped; a failed card is never retried in the same run.

## 1.2.0
**New**
- **Saved jobs:** apply to your LinkedIn *Saved jobs* automatically (⭐ button, *Saved jobs* setting for normal/scheduled runs, `--saved off|first|only`). Search filters are not applied to saved jobs; optional *remove from Saved after applying*.
- **Timeout setting:** *Timeout per click / page* (Search criteria, per profile) and `--timeout`, default 15 s.
- **Pop-up handling** (`jobbot/popups.py`): closes LinkedIn's post-apply window and its *Supprimer de votre candidature ?* confirmation, the *Save this application?* dialog, and plain close buttons — never presses destructive buttons on dialogs it does not recognise.

**Fixed**
- After the first successful application the bot clicked the post-apply "Ignorer" button, which opened a confirmation covering the page; every following click then failed with `Locator.click: Timeout 15000ms exceeded`.
- A job whose page did not load was logged as `SKIPPED` forever (empty title); it is now left to be retried.
- Readable log line for timeouts instead of a raw Playwright error.

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
