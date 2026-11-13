#!/usr/bin/env bash
# Publish / update https://github.com/MiFactory/job-apply-bot   (run from anywhere:  bash publish_to_github.sh ["commit message"])
#   - first run  : creates the repo (private) if it does not exist, otherwise just pushes
#   - next runs  : commits what changed and pushes (history kept)
#   - safety     : your real data (data/, CVs, answers, profiles, logs, csv) is NEVER staged — the script aborts if it finds any
#   - tests      : unit tests run first (SKIP_TESTS=1 to skip, FULL_TESTS=1 to add the slow end-to-end test)
# Needs git; for a first push also the GitHub CLI (`gh auth login`) or a git credential for github.com (Git Credential Manager on Windows).
set -euo pipefail
cd "$(dirname "$0")"
REPO="MiFactory/job-apply-bot"; URL="${REPO_URL:-https://github.com/${REPO}.git}"; BRANCH="main"

say() { printf '\n== %s\n' "$*"; }
die() { printf '\n!! %s\n' "$*" >&2; exit 1; }
command -v git >/dev/null || die "git is not installed"

VER=$(sed -n 's/^__version__ *= *"\([^"]*\)".*/\1/p' jobbot/__init__.py | head -n1); VER=${VER:-?}
MSG=${1:-"v${VER} - several applications at the same time (parallel_applications 1..10, one tab per job)"}

# ---- 0. keep private files out of git
say "Checking .gitignore"
touch .gitignore
for pat in "data/" "*.csv" "browser_profile/" "qt_profile/" "__pycache__/" "*.pyc" ".venv/" "*.pdf" "*.docx" "*.zip" "*.log" ".env"; do
  grep -qxF "$pat" .gitignore || { echo "$pat" >> .gitignore; echo "  + added $pat to .gitignore"; }
done

# ---- 1. repository + remote
[ -d .git ] || { say "git init"; git init -b "$BRANCH" >/dev/null; }
git checkout -q "$BRANCH" 2>/dev/null || git checkout -q -b "$BRANCH"
if git remote | grep -qx origin; then git remote set-url origin "$URL"; else git remote add origin "$URL"; fi
git config user.name  >/dev/null 2>&1 || git config user.name  "MiFactory"
git config user.email >/dev/null 2>&1 || git config user.email "it@pharmatec.be"

# ---- 2. tests
if [ "${SKIP_TESTS:-0}" != "1" ]; then
  say "Running tests"
  PY=$(command -v python3 || command -v python || command -v py || true)
  if [ -z "$PY" ]; then echo "  (python not found: tests skipped)"; else
    mods="tests.test_unit tests.test_labels tests.test_answerer"; [ "${FULL_TESTS:-0}" = "1" ] && mods="$mods tests.test_e2e"
    for m in $mods; do [ -f "tests/${m#tests.}.py" ] || continue; echo "  - $m"; "$PY" -m "$m" >/tmp/jobbot_test.out 2>&1 || { tail -n 25 /tmp/jobbot_test.out; die "tests failed ($m) - nothing was published (SKIP_TESTS=1 to force)"; }; done
    echo "  all tests passed"
  fi
fi

# ---- 3. sync with GitHub (a fresh local repo adopts the remote history instead of clashing with it)
say "Fetching ${REPO}"
if git fetch origin "$BRANCH" 2>/dev/null; then
  if ! git rev-parse -q --verify HEAD >/dev/null 2>&1; then git reset --soft "origin/${BRANCH}"; fi
  git merge-base --is-ancestor "origin/${BRANCH}" HEAD 2>/dev/null || { git pull --rebase origin "$BRANCH" || die "remote has newer commits that conflict - resolve them, then run again"; }
  REMOTE_OK=1
else
  REMOTE_OK=0; echo "  (remote branch not found - first publication)"
fi

# ---- 4. stage + safety guard
say "Staging"
git add -A
BAD=$(git diff --cached --name-only | grep -Ei '(^|/)data/|\.csv$|\.pdf$|\.docx$|\.zip$|\.log$|browser_profile|qt_profile|(^|/)\.env$|(^|/)(answers|profile|criteria|motivation)\.json$' | grep -v '^examples/' || true)
if [ -n "$BAD" ]; then git reset -q; printf '%s\n' "$BAD"; die "private/personal files would be published - aborted, nothing committed"; fi
if git diff --cached --quiet; then say "Nothing new to commit"; else git commit -q -m "$MSG"; git log --oneline -n 1; fi

# ---- 5. push
say "Pushing to ${URL}"
if [ "$REMOTE_OK" = "0" ] && command -v gh >/dev/null 2>&1 && ! gh repo view "$REPO" >/dev/null 2>&1; then
  gh repo create "$REPO" --private --source . --remote origin --push || die "gh repo create failed"
else
  git push -u origin "$BRANCH" || die "push failed - check your GitHub login (gh auth login) / credentials"
fi
say "Done: v${VER} published -> https://github.com/${REPO}"
