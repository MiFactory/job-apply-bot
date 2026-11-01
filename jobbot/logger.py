"""Run log: everything the bot shows is also written to data/logs/jobbot.log, and every error is
written WITH its full stack trace, the page URL and the step the bot was on.
Open the file (GUI button "📄 Log") and send it when something is stuck."""
import logging, logging.handlers, traceback, pathlib, datetime
from . import store

_log = None
_step = {"site": "", "job": "", "step": ""}


def log_path():
    d = store.DATA / "logs"; d.mkdir(parents=True, exist_ok=True)
    return d / "jobbot.log"


def setup():
    """Create the rotating file logger (1 MB x 5 files). Safe to call several times."""
    global _log
    if _log: return _log
    _log = logging.getLogger("jobbot"); _log.setLevel(logging.DEBUG); _log.propagate = False
    h = logging.handlers.RotatingFileHandler(log_path(), maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S"))
    _log.addHandler(h)
    return _log


def info(msg):
    try: setup().info(str(msg))
    except Exception: pass


def step(site="", job="", what=""):
    """Remember where the bot is, so a later error says exactly what it was doing."""
    if site: _step["site"] = site
    if job: _step["job"] = job
    if what: _step["step"] = what
    info(f"STEP site={_step['site']} job={_step['job']} step={_step['step']}")


def error(where, exc, page=None):
    """Log an error with the full traceback, the page URL/title and the current step."""
    url = title = ""
    try:
        if page is not None: url = page.url; title = page.title()
    except Exception: pass
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    try:
        setup().error(f"ERROR in {where}: {type(exc).__name__}: {exc}\n  step: {_step}\n  page: {url} | {title}\n{tb}")
    except Exception: pass
    return f"{type(exc).__name__}: {exc}  [{where}; step={_step['step'] or '-'}; page={url or '-'}]"
