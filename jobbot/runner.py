"""Shared run logic used by the CLI and the GUI."""
import pathlib
from . import profile as P

ROOT = pathlib.Path(__file__).resolve().parent.parent

def resolve_cvs(prof):
    for k, v in prof["cv_files"].items():
        if v and not pathlib.Path(v).is_absolute():
            prof["cv_files"][k] = str((ROOT / v).resolve())
    return prof

def set_timeouts(page, crit):
    """User setting «timeout_seconds» (Search criteria): how long a click / page load may wait before the job is skipped."""
    try: secs = max(2, min(300, int(crit.get("timeout_seconds", 15))))
    except Exception: secs = 15
    crit["timeout_seconds"] = secs
    for obj in (page, getattr(page, "context", None)):
        try: obj.set_default_timeout(secs * 1000); obj.set_default_navigation_timeout(max(30, secs * 2) * 1000)
        except Exception: pass
    return secs

def run_jobs(page, prof, crit, sites, max_apps, dry_run, interactive=True, asker=None, motivation=None):
    from .browser import HOOKS
    from . import logger
    if not getattr(HOOKS["log"], "_logged", False):          # every message shown is also written to data/logs/jobbot.log
        orig = HOOKS["log"]
        def both(m, _o=orig): logger.info(m); _o(m)
        both._logged = True; HOOKS["log"] = both
    logger.info(f"RUN START sites={sites} max={max_apps} dry_run={dry_run} locations={crit.get('locations')} titles={len(crit.get('titles', []))}")
    if dry_run: HOOKS["log"]("ℹ DRY RUN is ON: forms are filled but NOTHING is submitted. Untick 'Dry-run' to really apply.")
    HOOKS["result"] = ""; prof = resolve_cvs(prof); total = 0
    set_timeouts(page, crit)
    mode = crit.get("saved_jobs", "off")              # off | first (saved jobs, then search) | only
    if mode not in ("off", "first", "only"): mode = "off"
    li_blocked = False
    if mode in ("first", "only"):
        if "linkedin" in sites:
            from . import linkedin
            total += linkedin.run_saved(page, prof, crit, max_apps, dry_run, interactive, asker, motivation)
            if HOOKS["result"] in ("stopped", "quota") or total >= max_apps: return total
            li_blocked = HOOKS["result"] == "limit"
        else:
            HOOKS["log"]("⭐ Saved jobs are read from LinkedIn only — tick LinkedIn in Sites.")
    if mode == "only": return total
    if "linkedin" in sites and not li_blocked:
        from . import linkedin
        total += linkedin.run(page, prof, crit, max_apps - total, dry_run, interactive, asker, motivation)
    if "indeed" in sites and total < max_apps and HOOKS["result"] != "stopped":
        from . import indeed
        total += indeed.run(page, prof, crit, max_apps - total, dry_run, interactive, asker, motivation)
    logger.info(f"RUN END result={HOOKS['result'] or 'finished'} applications={total}")
    return total


def last_result():
    """How the last run ended: 'limit' | 'quota' | 'stopped' | 'finished'."""
    from .browser import HOOKS
    return HOOKS["result"] or "finished"
