# Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: PySide6` | `pip install -r requirements.txt` |
| Chrome does not start | Install Google Chrome, or `python -m playwright install chromium` |
| `TargetClosedError` | The browser window was closed. Click **🔄 Reopen browser** (or restart the app) |
| Browser opens outside the window | Windows only for embedding. Choose *Inside* or *Docked* in the **Browser** drop-down, then **🔄 Reopen browser** |
| Page looks tiny / letter-boxed | Fixed by `no_viewport=True`; make sure you run the latest version (title bar shows the version) |
| Yellow Chrome bar "unsupported command-line flag" | Run the latest version (flags removed) |
| `Locator.click: Timeout` on job cards | LinkedIn re-rendered the list; the bot retries the next card. If it happens on every card, update the selectors in `jobbot/linkedin.py` |
| Jobs outside your country are applied to | Adjust `location_must_contain` in `criteria.json` |
| "Question: CV_xxx.pdf" appears | Run the latest version — the resume chooser is skipped (LinkedIn keeps the selected CV) |
| Google refuses to sign in | Use installed Chrome (not Chromium), sign in manually once with the 🔑 Google button |
| LinkedIn "limit reached" | The bot stops by itself. Try again tomorrow |
| Nothing is submitted | Untick **Dry-run** |
| Wrong answer keeps being used | Right panel → edit/delete the row (learned answers are in black) |

Run `python tests/test_formfiller.py` to verify the form filler works on your machine.
