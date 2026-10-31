"""Job Apply Bot — reads offers on LinkedIn / Indeed in a real browser and applies for you.
Usage:
  python main.py setup  --cv "..\\CV_EN.pdf" [--cv-fr "..\\CV_FR.pdf"]   # analyse CV → profile + criteria (asks what is missing)
  python main.py login [--google you@gmail.com]                            # open the browser once; log in by hand or via your Gmail account
  python main.py run [--site linkedin|indeed|both] [--max 30] [--dry-run] [--unattended]
  python main.py report                                                    # summary of applications + pending questions
"""
import argparse, sys, json, collections, csv, pathlib
from jobbot import profile as P, store, cv_analyzer, profiles

ROOT = pathlib.Path(__file__).resolve().parent

def ask(q, default=""):
    a = input(f"{q} [{default}]: ").strip()
    return a or default

def cmd_setup(a):
    prof, crit = P.load_profile(), P.load_criteria()
    if not a.cv: sys.exit("Give your CV: --cv path.pdf|docx")
    info = cv_analyzer.analyze(a.cv)
    print("\n📄 CV analysis:", json.dumps({k: v for k, v in info.items() if k != "chars"}, indent=2, ensure_ascii=False))
    full = ask("Full name", info["name"] if not prof["first_name"] else f'{prof["first_name"]} {prof["last_name"]}')
    parts = full.split(" ", 1); prof["first_name"], prof["last_name"] = parts[0], (parts[1] if len(parts) > 1 else "")
    prof["email"] = ask("Email", prof["email"] or info["email"])
    prof["phone"] = ask("Phone (international)", prof["phone"] or info["phone"])
    prof["phone_national"] = ask("Phone without country code", prof["phone_national"] or "".join(c for c in prof["phone"] if c.isdigit())[-9:])
    prof["city"] = ask("City", prof["city"]); prof["postal_code"] = ask("Postal code", prof["postal_code"])
    prof["linkedin_url"] = ask("LinkedIn URL", prof["linkedin_url"])
    prof["years_experience_total"] = int(ask("Total years of experience", str(info["years_experience"] or prof["years_experience_total"])))
    prof["salary_year_eur"] = int(ask("Expected gross salary / YEAR (EUR)", str(prof["salary_year_eur"]))); prof["salary_month_eur"] = round(prof["salary_year_eur"] / 12)
    prof["notice_period"] = ask("Notice period", prof["notice_period"])
    prof["authorized_to_work"] = ask("Authorised to work in Belgium? (y/n)", "y").lower().startswith("y")
    prof["needs_sponsorship"] = ask("Need visa sponsorship? (y/n)", "n").lower().startswith("y")
    langs = {}
    for l in info["languages"] or ["english", "french"]:
        langs[l] = ask(f"Level for {l}", prof["languages"].get(l, "Professional"))
    prof["languages"] = langs
    prof["cv_files"]["en"] = str(pathlib.Path(a.cv).resolve())
    if a.cv_fr: prof["cv_files"]["fr"] = str(pathlib.Path(a.cv_fr).resolve())
    sugg = info["suggested_titles"]
    print("\n🎯 Suggested job titles from your CV:", ", ".join(sugg))
    t = ask("Job titles to search (comma-separated)", ", ".join(crit["titles"] or sugg))
    crit["titles"] = [x.strip() for x in t.split(",") if x.strip()]
    crit["locations"] = [x.strip() for x in ask("Locations (comma-separated)", ", ".join(crit["locations"])).split(",")]
    crit["exclude"] = [x.strip() for x in ask("Exclude words in title", ", ".join(crit["exclude"])).split(",")]
    crit["posted_within_days"] = int(ask("Posted within days", str(crit["posted_within_days"])))
    crit["easy_apply_only"] = ask("Only Easy Apply / Indeed Apply? (y/n)", "y").lower().startswith("y")
    P.save(P.PROFILE, prof); P.save(P.CRITERIA, crit)
    print("\n✅ Saved data/profile.json and data/criteria.json (edit them any time).")

def cmd_login(a):
    from jobbot.browser import Browser, pause_for_human, google_session, login_with_google
    prof = P.load_profile()
    email = a.google or prof.get("google_email", "")
    with Browser() as b:
        if email:   # Gmail / "Continue with Google" mode
            prof["google_email"] = email; P.save(P.PROFILE, prof)
            print(f"Gmail mode: {email}")
            google_session(b, email)
            for site, url in (("LinkedIn", "https://www.linkedin.com/login"), ("Indeed", "https://secure.indeed.com/auth?hl=fr_BE")):
                try:
                    pg = b.live_page(); pg.goto(url); pg.wait_for_timeout(2000)
                    ok = login_with_google(pg, site, email)
                except Exception as e:
                    print(f"   ({site}: {type(e).__name__} — falling back to manual)"); ok = False
                if not ok:
                    try: pause_for_human(f"{site}: click 'Continue with Google' and pick your account (or log in as usual). Skip Indeed if you don't use it.")
                    except Exception: pass
        else:
            b.page.goto("https://www.linkedin.com/login"); pause_for_human("Log in to LinkedIn.")
            b.page.goto("https://be.indeed.com/account/login"); pause_for_human("Log in to Indeed (optional).")
    print("✅ Sessions saved in data/browser_profile (reused on every run).")

def cmd_run(a):
    from jobbot.browser import Browser
    prof, crit = P.load_profile(), P.load_criteria()
    if not crit["titles"]: sys.exit("No job titles — run: python main.py setup --cv ...")
    sites = crit["sites"] if a.site == "both" else [a.site]
    from jobbot.runner import run_jobs
    import json
    mp = P.PROFILE.parent / "motivation.json"; mot = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else {}
    with Browser() as b:
        total = run_jobs(b.page, prof, crit, sites, a.max, a.dry_run, not a.unattended, None, mot)
    print(f"\nDone: {total} application(s) this run. Log: {store.APPS}")
    cmd_report(a)

def cmd_report(a):
    if not store.APPS.exists(): return print("No applications yet.")
    rows = list(csv.DictReader(open(store.APPS, encoding="utf-8-sig"), delimiter=";"))
    print("Status counts:", dict(collections.Counter(r["status"] for r in rows)))
    if store.PENDING.exists():
        q = collections.Counter(r["question"] for r in csv.DictReader(open(store.PENDING, encoding="utf-8-sig"), delimiter=";"))
        print("Questions I could not answer (add them to data/answers.json):")
        for k, v in q.most_common(15): print(f"  {v}× {k}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--profile", help="profile name (see data/profiles); default = last used"); sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("setup"); s.add_argument("--cv"); s.add_argument("--cv-fr")
    l = sp.add_parser("login"); l.add_argument("--google", help="Gmail address to sign in with (Continue with Google)"); sp.add_parser("report")
    r = sp.add_parser("run"); r.add_argument("--site", default="both", choices=["linkedin", "indeed", "both"])
    r.add_argument("--max", type=int, default=30); r.add_argument("--dry-run", action="store_true"); r.add_argument("--unattended", action="store_true")
    a = ap.parse_args(); profiles.migrate(); profiles.activate(a.profile or profiles.active()); print(f"Profile: {profiles.active()}"); {"setup": cmd_setup, "login": cmd_login, "run": cmd_run, "report": cmd_report}[a.cmd](a)
