"""Multiple candidate profiles: data/profiles/<name>/{profile,criteria,motivation,answers}.json, applications.csv, browser_profile/ (own login session)."""
import json, shutil, re, pathlib
from . import store, profile as P, browser as B

DATA = P.DATA
PROFILES = DATA / "profiles"
ACTIVE = DATA / "active_profile.txt"
COPY_FILES = ["profile.json", "criteria.json", "motivation.json", "answers.json"]
_active = None


def safe(name): return re.sub(r"[^\w\- ]", "", name).strip()[:40] or "profile"


def list_profiles():
    PROFILES.mkdir(parents=True, exist_ok=True)
    return sorted(p.name for p in PROFILES.iterdir() if p.is_dir() and not p.name.startswith("_"))


def active():
    if _active: return _active
    n = ACTIVE.read_text(encoding="utf-8").strip() if ACTIVE.exists() else ""
    return n if n in list_profiles() else (list_profiles() or [""])[0]


def migrate():
    """First start with the old single-profile layout: move it into profiles/<first name>."""
    PROFILES.mkdir(parents=True, exist_ok=True)
    if list_profiles() or not (DATA / "profile.json").exists(): return
    try: name = safe(P.read_json(DATA / "profile.json", {}).get("first_name") or "default")
    except Exception: name = "default"
    d = PROFILES / name; d.mkdir(parents=True, exist_ok=True)
    for f in COPY_FILES + ["applications.csv", "pending_questions.csv", "browser_profile"]:
        src = DATA / f
        if src.exists(): shutil.move(str(src), str(d / f))
    ACTIVE.write_text(name, encoding="utf-8")


def activate(name):
    global _active
    PROFILES.mkdir(parents=True, exist_ok=True)
    if not name or name not in list_profiles():
        name = (list_profiles() or [create("default")])[0]
    d = PROFILES / name
    store.set_dir(d)
    P.PROFILE, P.CRITERIA = d / "profile.json", d / "criteria.json"
    B.PROFILE_DIR = d / "browser_profile"
    _active = name; ACTIVE.write_text(name, encoding="utf-8")
    return name


def create(name, copy_from=None):
    name = safe(name); d = PROFILES / name; d.mkdir(parents=True, exist_ok=True)
    if copy_from and (PROFILES / copy_from).exists():
        for f in COPY_FILES:
            s = PROFILES / copy_from / f
            if s.exists(): shutil.copy(s, d / f)
        # a copy is a different person/account: keep settings but start with a clean log and answers tied to the person
    elif not (d / "profile.json").exists():
        blank = json.loads(json.dumps(P.DEFAULT_PROFILE)); P.save(d / "profile.json", blank)
    return name


def delete(name):
    shutil.rmtree(PROFILES / name, ignore_errors=True)


def project_dir(): return PROFILES / active()
