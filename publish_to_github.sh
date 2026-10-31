#!/usr/bin/env bash
# Publish to https://github.com/MiFactory/job-apply-bot (run once from this folder)
set -e
git init -b main && git add . && git commit -m "Job Apply Bot: LinkedIn/Indeed auto-apply with GUI, profiles and learned answers"
if command -v gh >/dev/null; then gh repo create MiFactory/job-apply-bot --private --source . --remote origin --push
else git remote add origin https://github.com/MiFactory/job-apply-bot.git && git push -u origin main; fi
