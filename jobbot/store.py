"""Persistence: applications log (CSV ';'), answers memory, pending questions."""
import csv, json, re, datetime, pathlib, threading

_LOCK = threading.RLock()      # the GUI thread and the bot thread both write these files

DATA = pathlib.Path(__file__).resolve().parent.parent / "data"
DATA.mkdir(exist_ok=True)
APPS = DATA / "applications.csv"
ANSWERS = DATA / "answers.json"
PENDING = DATA / "pending_questions.csv"


def set_dir(d):
    """Point the log / answers files at another profile folder."""
    global APPS, ANSWERS, PENDING
    d = pathlib.Path(d); d.mkdir(parents=True, exist_ok=True)
    APPS, ANSWERS, PENDING = d / "applications.csv", d / "answers.json", d / "pending_questions.csv"
FIELDS = ["date", "site", "job_id", "title", "company", "location", "url", "status", "note"]


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (s or "").lower()).strip()


def _write_header(path, fields):
    if not path.exists():
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f, delimiter=";").writerow(fields)


def seen_jobs():
    if not APPS.exists():
        return set()
    with open(APPS, encoding="utf-8-sig") as f:
        return {(r["site"], r["job_id"]) for r in csv.DictReader(f, delimiter=";")}


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


def save_answer(question, answer):
    with _LOCK:
        a = load_answers()
        a[norm(question)] = answer
        ANSWERS.write_text(json.dumps(a, indent=2, ensure_ascii=False), encoding="utf-8")


def log_pending(site, title, company, question, url):
    with _LOCK:
        _write_header(PENDING, ["date", "site", "title", "company", "question", "url"])
        with open(PENDING, "a", newline="", encoding="utf-8") as f:
            csv.writer(f, delimiter=";").writerow(
                [datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), site, title, company, question, url])
