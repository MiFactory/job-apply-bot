"""Persistence: applications log (CSV ';'), answers memory, pending questions."""
import csv, json, re, datetime, pathlib, threading

_LOCK = threading.RLock()      # the GUI thread and the bot thread both write these files

DATA = pathlib.Path(__file__).resolve().parent.parent / "data"
DATA.mkdir(exist_ok=True)
APPS = DATA / "applications.csv"
ANSWERS = DATA / "answers.json"
PENDING = DATA / "pending_questions.csv"
AUTO = DATA / "answers_auto.json"       # keys of answers the bot GUESSED (CV-based) — shown in orange, never taught as facts


def set_dir(d):
    """Point the log / answers files at another profile folder."""
    global APPS, ANSWERS, PENDING, AUTO
    d = pathlib.Path(d); d.mkdir(parents=True, exist_ok=True)
    APPS, ANSWERS, PENDING, AUTO = d / "applications.csv", d / "answers.json", d / "pending_questions.csv", d / "answers_auto.json"
FIELDS = ["date", "site", "job_id", "title", "company", "location", "url", "status", "note"]


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (s or "").lower()).strip()


def _write_header(path, fields):
    if not path.exists():
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f, delimiter=";").writerow(fields)


def seen_jobs():
    """Jobs that need no further attempt. NOT final: DRY_RUN (a test run never applied), ERROR, and NEEDS_INFO whose question
    has been answered since — these are tried again, so a real run applies to what a dry run only looked at."""
    if not APPS.exists():
        return set()
    answered = set(load_answers())
    out = set()
    with open(APPS, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f, delimiter=";"):
            st = r.get("status") or ""
            if st in ("DRY_RUN", "ERROR"): continue
            if st == "NEEDS_INFO" and norm(r.get("note") or "") in answered: continue
            out.add((r["site"], r["job_id"]))
    return out


def finished_saved_jobs():
    """Saved jobs that need no more work: applied, or set aside by a saved-jobs run (closed / external site).
    Jobs skipped by the *search* filters, DRY_RUN and NEEDS_INFO are retried when they are in your Saved list."""
    if not APPS.exists():
        return set()
    with open(APPS, encoding="utf-8-sig") as f:
        return {(r["site"], r["job_id"]) for r in csv.DictReader(f, delimiter=";")
                if r.get("status") == "APPLIED" or (r.get("status") == "SKIPPED" and (r.get("note") or "").startswith("saved:"))}


def log_application(site, job_id, title, company, location, url, status, note=""):
    with _LOCK:
        _write_header(APPS, FIELDS)
        with open(APPS, "a", newline="", encoding="utf-8") as f:       # header already carries the BOM; appending must not add another
            csv.writer(f, delimiter=";").writerow(
                [datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), site, job_id, title, company, location, url, status, note])


def count_today(status="APPLIED"):
    if not APPS.exists():
        return 0
    today = datetime.date.today().isoformat()
    with open(APPS, encoding="utf-8-sig") as f:
        return sum(1 for r in csv.DictReader(f, delimiter=";") if r["date"].startswith(today) and r["status"] == status)


def load_answers():
    from .profile import read_json
    return read_json(ANSWERS, {})


def load_auto():
    from .profile import read_json
    d = read_json(AUTO, {}); return set(d.get("keys", [])) if isinstance(d, dict) else set()


def save_answer(question, answer, auto=False):
    """auto=True marks a CV-based guess (you can review / overwrite it; a manual answer removes the mark)."""
    with _LOCK:
        a = load_answers(); k = norm(question)
        a[k] = answer
        ANSWERS.write_text(json.dumps(a, indent=2, ensure_ascii=False), encoding="utf-8")
        keys = load_auto(); keys = (keys | {k}) if auto else (keys - {k})
        AUTO.write_text(json.dumps({"keys": sorted(keys)}, indent=2), encoding="utf-8")


def log_pending(site, title, company, question, url):
    with _LOCK:
        _write_header(PENDING, ["date", "site", "title", "company", "question", "url"])
        with open(PENDING, "a", newline="", encoding="utf-8") as f:
            csv.writer(f, delimiter=";").writerow(
                [datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), site, title, company, question, url])
