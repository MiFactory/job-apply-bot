"""Shared run logic used by the CLI and the GUI."""
import pathlib
from . import profile as P

ROOT = pathlib.Path(__file__).resolve().parent.parent

def resolve_cvs(prof):
    for k, v in prof["cv_files"].items():
        if v and not pathlib.Path(v).is_absolute():
            prof["cv_files"][k] = str((ROOT / v).resolve())
    return prof

def run_jobs(page, prof, crit, sites, max_apps, dry_run, interactive=True, asker=None, motivation=None):
    from .browser import HOOKS
    HOOKS["result"] = ""; prof = resolve_cvs(prof); total = 0
    if "linkedin" in sites:
        from . import linkedin
        total += linkedin.run(page, prof, crit, max_apps, dry_run, interactive, asker, motivation)
    if "indeed" in sites and total < max_apps and HOOKS["result"] != "stopped":
        from . import indeed
        total += indeed.run(page, prof, crit, max_apps - total, dry_run, interactive, asker, motivation)
    return total


def last_result():
    """How the last run ended: 'limit' | 'quota' | 'stopped' | 'finished'."""
    from .browser import HOOKS
    return HOOKS["result"] or "finished"
