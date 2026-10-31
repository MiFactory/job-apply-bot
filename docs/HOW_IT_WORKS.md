# How it works

## Big picture

```
 ┌────────────┐   commands (goto / run / quit)   ┌──────────────────────┐
 │  Qt GUI    │ ───────────────────────────────▶ │  BrowserThread       │
 │ (main      │ ◀─────────────────────────────── │  Playwright + Chrome │
 │  thread)   │   signals: log / ask / pause     │  runner → linkedin / │
 └────────────┘                                  │  indeed → formfiller │
       ▲  right panel = profile.json + answers.json └──────────────────────┘
```

* The **GUI** lives in the main Qt thread. The **BrowserThread** owns Playwright and Chrome (Playwright's sync API must stay in one thread). They talk through a `queue.Queue` (GUI → browser) and Qt signals (browser → GUI).
* When the form filler needs an unknown answer it calls the *asker* hook. The worker emits an `ask` signal and **blocks on a `threading.Event`** until the user answers in the GUI (or skips). CAPTCHA / login pauses use the same mechanism (`pause` signal, "Done — continue" bar).

## The apply loop (`linkedin.py`, `indeed.py`)

For each *job title × location × result page*:

1. Open the search URL (sorted by date, last N days, Easy Apply filter on LinkedIn).
2. For each result card: click it, read title / company / location / description.
3. **Filter** — excluded company, location must contain a target keyword (`location_must_contain`), `score_job()` (excluded words in the title, required keywords, ad language), already-seen offers (`applications.csv`).
4. Pick the **CV language** from the ad text (`profile.detect_lang`) and the matching CV file.
5. Click *Easy Apply* / *Apply*; loop over the wizard steps: `Filler.fill()` → click *Next / Review / Submit*. Validation errors or a missing button raise `NeedInfo` → the job is logged as `NEEDS_INFO`.
6. Log the result; stop when the daily cap, the run cap or the platform limit is hit.

Statuses: `APPLIED`, `DRY_RUN`, `SKIPPED` (with reason), `NEEDS_INFO`.

## The answer engine (`formfiller.py`)

`Filler.fill(scope)` walks the visible fields of the current form step (text/number/textarea, selects, radio groups, consent checkboxes, file inputs) and for each one:

1. Gets the **label** (`label[for]`, `aria-labelledby`, `aria-label`, fieldset legend, nearest text) and cleans duplicated text.
2. Resolves the answer in this order:
   1. cover-letter style question → the **motivation message** of the ad's language (`{title}`, `{company}`, `{full_name}` replaced);
   2. **profile rules** — regex on the label → profile value (name, phone, city, salary, notice, sponsorship, work permit, years of experience *per skill*, language levels…);
   3. **learned answers** (`answers.json`, key = normalised question text);
   4. otherwise **ask the user** (GUI red box, or terminal in CLI) and save the answer.
3. Fills the field (selects/radios choose the option whose text best matches; "yes/no" is understood in EN/FR/NL).

Never ticked: "follow company", newsletters, marketing, job alerts. Consent boxes (terms / privacy) are ticked as part of the form.

## Profiles (`profiles.py`)

`data/profiles/<name>/` contains `profile.json`, `criteria.json`, `motivation.json`, `answers.json`, `applications.csv`, `pending_questions.csv` and `browser_profile/` (that profile's own Chrome session). `profiles.activate(name)` re-points `store`, `profile` and `browser` module paths. Old single-profile layouts are migrated automatically.

## Browser modes (GUI)

* **Inside (child)** — Chrome's window is attached to the centre panel with Win32 `SetParent` (`NativeHost`). A health check runs 2.5 s later; if Chrome died, the app falls back to *Docked*.
* **Docked** — Chrome stays a top-level window *owned* by the app window, positioned over the centre panel every 120 ms (hides when minimised).
* **Separate window** — plain Chrome window (default on Linux/macOS).
* The page is rendered with `no_viewport=True` so it fills the panel. Page zoom uses CSS `zoom` (stored per site in `localStorage`).

## Scheduler (`scheduler.py`)
A small state machine (`Scheduler`) used by the GUI (15 s timer) and by `main.py schedule` (20 s loop). States: *idle* (waiting for the next chosen weekday/hour) and *retry* (LinkedIn limit hit: next test at now + N min). The site modules record how a run ended in `HOOKS["result"]` (`limit`, `quota`, `stopped`, or empty = finished): `limit` → retry, `quota`/finished → next scheduled day, `stopped` (user pressed Stop) → never auto-restart in the same cycle. Retries stop after `retry_max_hours` (48).

## Safety design

* Login is always done by the user in the browser (password never typed or stored by the bot).
* `human_check()` pauses on login walls, CAPTCHAs, "verify you are human", checkpoints.
* `LimitReached` is raised on LinkedIn "limit" messages and ends the run.
* Dry-run fills everything but stops before the final *Submit*.
