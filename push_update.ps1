# Run from C:\badre\projects\job_apply_bot :  .\push_update.ps1
$ErrorActionPreference = "Continue"
$repo = "https://github.com/MiFactory/job-apply-bot.git"
$ver = (Select-String -Path "jobbot\__init__.py" -Pattern '__version__\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
if (-not (Test-Path ".git")) { git init -b main }
if (-not (git remote)) { git remote add origin $repo }
git fetch origin
git reset --soft origin/main
git add -A
git commit -m "v${ver} - default answers instead of skipping, new LinkedIn layout support, run log, radio option fix"
git push origin main
Write-Host "Done: v${ver}"
