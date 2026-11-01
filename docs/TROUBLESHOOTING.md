# Troubleshooting

| Problem | Fix |
|---|---|
| Log shows jobs "applied" but nothing was submitted | That is **Dry run** (stops before Submit). Untick it and run again — jobs seen in a dry run are retried automatically |
| Many `⚠ … Timeout` lines on the same job | A form/pop-up was covering the page. The bot now closes it, reloads after 4 failures in a row and skips the page after 8; raise *Timeout per click / page* on a slow connection |
| Bot answered a question wrongly | Orange *auto* rows in the right-hand list are guesses from your CV — edit the answer; or set *Wait for my answer* higher / `auto_answer` false |
| `ModuleNotFoundError: PySide6` | `pip install -r requirements.txt` |
| Chrome does not start | Install Google Chrome, or `python -m playwright install chromium` |
| `TargetClosedError` | The browser window was closed. Click **🔄 Reopen browser** (or restart the app) |
| Browser opens outside the window | Windows only for embedding. Choose *Inside* or *Docked* in the **Browser** drop-down, then **🔄 Reopen browser** |
| Page looks tiny / letter-boxed | Fixed by `no_viewport=True`; make sure you run the latest version (title bar shows the version) |
| Yellow Chrome bar "unsupported command-line flag" | Run the latest version (flags removed) |
| `Locator.click: Timeout` / "nothing clickable after Ns" | A pop-up was covering the page (e.g. LinkedIn's *A postulé chez …* window and its *Supprimer de votre candidature ?* confirmation). Since 1.2 the bot closes these itself (`jobbot/popups.py`); the job is skipped and retried later. Slow connection? Raise **Timeout per click / page** in *Search criteria* (or `--timeout 30`). If one specific pop-up still blocks, add its wording to `popups.py` |
| A job is never applied to after a timeout | Timed-out jobs are not logged, so they are retried on the next run |
| Saved jobs: "0 saved job(s) found" | Check you are logged in and that jobs are in LinkedIn › My items › Saved. Tick **LinkedIn** in *Sites*. Try `python main.py run --saved only --dry-run --max 3` |
| Jobs outside your country are applied to | Adjust `location_must_contain` in `criteria.json` |
| "Question: CV_xxx.pdf" appears | Run the latest version — the resume chooser is skipped (LinkedIn keeps the selected CV) |
| Google refuses to sign in | Use installed Chrome (not Chromium), sign in manually once with the 🔑 Google button |
| LinkedIn "limit reached" | The bot stops by itself. Try again tomorrow |
| Nothing is submitted | Untick **Dry-run** |
| Wrong answer keeps being used | Right panel → edit/delete the row (learned answers are in black) |

Run `python tests/test_formfiller.py` to verify the form filler works on your machine.
