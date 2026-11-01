"""Candidate profile + search criteria (data/profile.json, data/criteria.json)."""
import json, pathlib, re

DATA = pathlib.Path(__file__).resolve().parent.parent / "data"
PROFILE = DATA / "profile.json"
CRITERIA = DATA / "criteria.json"

DEFAULT_PROFILE = {
    "first_name": "", "last_name": "", "email": "", "phone": "", "phone_country_code": "+32", "phone_national": "",
    "city": "", "postal_code": "", "country": "Belgium", "address": "",
    "linkedin_url": "", "website": "", "headline": "",
    "years_experience_total": 5, "years_by_skill": {},
    "salary_year_eur": 0, "salary_month_eur": 0, "notice_period": "1 month", "available_from": "1 month", "default_answers": True,
    "authorized_to_work": True, "needs_sponsorship": False, "willing_relocate": True, "driving_licence": True,
    "languages": {"english": "Professional", "french": "Native"}, "education": "Master's degree",
    "google_email": "", "cv_files": {"en": "", "fr": "", "nl": ""}, "default_cv_lang": "en", "cover_letter": ""
}
DEFAULT_CRITERIA = {
    "sites": ["linkedin", "indeed"],
    "titles": [],               # job titles to search
    "locations": ["Belgium"],   # search locations
    "must_have_any": [],        # at least one in title/description (empty = no check)
    "exclude": ["stage", "intern", "internship", "stagiaire", "student", "apprentice", "junior", "trainee", "alternance"],
    "exclude_companies": [],
    "title_must_match_any": [], # at least one word in the title (empty = no check)
    "posted_within_days": 30,
    "easy_apply_only": True,
    "min_score": 1,
    "max_applications_per_day": 40,
    "skip_languages": ["nl"],
    "location_must_contain": ["belg", "brussel", "bruxel", "wallon", "vlaan", "flan", "namur", "liège", "luik", "charleroi", "gent", "antwerp", "anvers", "leuven", "mons", "nivelles", "waterloo", "wavre"],   # skip ads written in these languages (nl = Dutch-only ads)
    "saved_jobs": "off",        # LinkedIn «Saved jobs»: off | first (apply to saved jobs, then search) | only
    "include_drafts": True,     # saved-jobs runs also finish your LinkedIn drafts («Brouillon» / unsent applications)
    "unsave_after_apply": False,  # remove a saved job from your Saved list once applied
    "timeout_seconds": 15,      # how long a click / page may wait before the job is skipped (GUI: Search criteria › Timeout)
    "answer_timeout_seconds": 30,   # wait this long for YOUR answer to an unknown form question (0 = forever), then …
    "auto_answer": True,            # … answer from the CV / profile / earlier answers (marked «auto»; sensitive questions are never guessed)
    "ask_user_when_unknown": True
}


def read_json(path, default):
    """Tolerant JSON read: UTF-8 BOM (Windows Notepad), empty/corrupt/non-object files never crash the app.
    A corrupt file is kept as <name>.bad (so nothing is lost) and the default is returned."""
    path = pathlib.Path(path)
    if not path.exists(): return default
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict): return data
        raise ValueError("JSON root is not an object")
    except Exception as e:
        try:
            bad = path.with_suffix(path.suffix + ".bad"); bad.write_bytes(path.read_bytes())
        except Exception: pass
        print(f"⚠ {path.name} is not valid JSON ({type(e).__name__}) — using defaults; a copy was saved as {path.name}.bad")
        return default


def load(path, default):
    d = json.loads(json.dumps(default))
    d.update(read_json(path, {}))
    return d


def load_profile(): return load(PROFILE, DEFAULT_PROFILE)
def load_criteria(): return load(CRITERIA, DEFAULT_CRITERIA)


def save(path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def detect_lang(text: str) -> str:
    t = " " + re.sub(r"[^a-zà-ÿ ]", " ", text.lower()) + " "
    sc = {"fr": sum(t.count(w) for w in (" le ", " la ", " les ", " des ", " et ", " vous ", " nous ", " pour ", " avec ", " une ")),
          "nl": sum(t.count(w) for w in (" de ", " het ", " een ", " en ", " wij ", " jij ", " voor ", " met ", " van ", " je ")),
          "es": sum(t.count(w) for w in (" el ", " los ", " las ", " del ", " para ", " con ", " una ", " usted ", " nosotros ", " y ")),
          "de": sum(t.count(w) for w in (" der ", " die ", " das ", " und ", " mit ", " für ", " wir ", " sie ", " ein ", " eine ")),
          "en": sum(t.count(w) for w in (" the ", " and ", " you ", " we ", " with ", " for ", " our ", " will ", " your ", " to "))}
    return max(sc, key=sc.get)


def location_ok(loc: str, crit: dict) -> bool:
    keys = crit.get("location_must_contain") or []
    return (not keys) or any(k in (loc or "").lower() for k in keys)


def score_job(title: str, desc: str, crit: dict):
    """Return (score, reason). score<=0 → reject."""
    tl, full = title.lower(), (title + " " + desc).lower()
    for w in crit["exclude"]:
        if re.search(r"\b" + re.escape(w.lower()) + r"\b", tl):
            return 0, f"excluded word in title: {w}"
    if crit["title_must_match_any"] and not any(w.lower() in tl for w in crit["title_must_match_any"]):
        return 0, "title does not match"
    if detect_lang(desc[:1500]) in crit["skip_languages"] and len(desc) > 300:
        return 0, "ad language skipped"
    s = 1
    if crit["must_have_any"]:
        hits = [k for k in crit["must_have_any"] if k.lower() in full]
        if not hits:
            return 0, "no required keyword"
        s += len(hits)
    s += sum(2 for t in crit["titles"] if t.lower() in tl)
    return s, "ok"
