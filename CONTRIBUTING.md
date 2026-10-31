# Contributing

Free to use, change and share (MIT licence). Fixes and improvements are welcome.

## Report a problem
Open an issue with: what you did, what you expected, what happened, your OS, Python and Chrome versions, and the text from the app's log box (remove personal data first).

## Fix or improve
1. Fork the repo and create a branch: `git checkout -b fix/short-description`.
2. Make a small, focused change. Most breakages are changed page selectors in `jobbot/linkedin.py` or `jobbot/indeed.py`.
3. Run the offline test: `python tests/test_formfiller.py` (needs `pip install -r requirements.txt` and `python -m playwright install chromium`).
4. Open a pull request describing the problem and the fix.

## Rules
- Never commit personal data (CVs, `data/`, logs, screenshots with names). Use fictive data (see `examples/`).
- Keep login manual: no code that types, stores or sends passwords, and nothing that bypasses CAPTCHAs, security checks or platform limits.
- Keep the code readable; comment the reason for a selector or workaround.
