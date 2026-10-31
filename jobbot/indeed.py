import re, urllib.parse
from . import store, profile as P
from .browser import human_check, pause_for_human, login_with_google, should_stop, HOOKS
from .formfiller import Filler, NeedInfo

NEXT = re.compile(r"^(continue|continuer|suivant|next|volgende)", re.I)
SUBMIT = re.compile(r"(submit your application|envoyer votre candidature|submit|soumettre|verzenden)", re.I)

def domain_for(loc): return "be.indeed.com"

def search_url(title, loc, crit, start=0):
    return f"https://{domain_for(loc)}/jobs?" + urllib.parse.urlencode({"q": title, "l": loc, "fromage": crit["posted_within_days"], "sort": "date", "start": start})

def ensure_login(page, google_email=""):
    page.goto("https://be.indeed.com/"); page.wait_for_timeout(2500); human_check(page, "Indeed")
    if page.locator("a[href*='/account/login'], a[data-gnav-element-name='SignIn']").count():
        if google_email:
            page.goto("https://secure.indeed.com/auth?hl=fr_BE"); page.wait_for_timeout(2500)
            login_with_google(page, "Indeed", google_email)
            page.goto("https://be.indeed.com/"); page.wait_for_timeout(2000)
            if not page.locator("a[href*='/account/login'], a[data-gnav-element-name='SignIn']").count(): return
        pause_for_human("Indeed: please LOG IN in the browser window (the bot never handles your password).")

def run(page, profile, criteria, max_apps, dry_run, interactive, asker=None, motivation=None):
    ensure_login(page, profile.get("google_email", ""))
    filler = Filler(profile, criteria, interactive, asker, motivation); seen = store.seen_jobs(); done = 0
    for tq in criteria["titles"]:
        for loc in criteria["locations"]:
            for start in range(0, 60, 10):
                page.goto(search_url(tq, loc, criteria, start)); page.wait_for_timeout(2000); human_check(page, "Indeed")
                cards = page.locator("div.job_seen_beacon, li div.cardOutline")
                if cards.count() == 0: break
                for i in range(cards.count()):
                    if should_stop() or done >= max_apps or store.count_today() >= criteria["max_applications_per_day"]: return done
                    try:
                        card = cards.nth(i); a = card.locator("a.jcs-JobTitle, h2 a").first
                        jid = a.get_attribute("data-jk") or a.get_attribute("id") or str(i)
                        if ("indeed", jid) in seen: continue
                        a.click(); page.wait_for_timeout(1800); human_check(page, "Indeed")
                        g = lambda s: page.locator(s).first.inner_text().strip() if page.locator(s).count() else ""
                        title = g("h2.jobsearch-JobInfoHeader-title, [data-testid='jobsearch-JobInfoHeader-title']").replace("- job post", "").strip()
                        company = g("[data-testid='inlineHeader-companyName'], [data-company-name]")
                        locn = g("[data-testid='inlineHeader-companyLocation'], [data-testid='job-location']")
                        desc = g("#jobDescriptionText"); url = f"https://{domain_for(loc)}/viewjob?jk={jid}"
                        sc, why = P.score_job(title, desc, criteria)
                        if not P.location_ok(locn, criteria): sc, why = 0, f"location outside target: {locn}"
                        if sc < criteria["min_score"] or company.lower() in [c.lower() for c in criteria["exclude_companies"]]:
                            store.log_application("indeed", jid, title, company, locn, url, "SKIPPED", why); seen.add(("indeed", jid)); continue
                        btn = page.locator("#indeedApplyButton, button:has-text('Postuler maintenant'), button:has-text('Apply now'), button:has-text('Easily apply')").first
                        if not btn.count():
                            store.log_application("indeed", jid, title, company, locn, url, "SKIPPED", "no Indeed Apply (external site)"); seen.add(("indeed", jid)); continue
                        lang = P.detect_lang(desc[:1500])
                        resume = profile["cv_files"].get(lang) or profile["cv_files"].get(profile["default_cv_lang"]) or ""
                        filler.ctx = {"title": title, "company": company, "lang": lang}; HOOKS["log"](f"→ {title} @ {company} ({locn}) cv={lang}")
                        before = len(page.context.pages); btn.click(); page.wait_for_timeout(3000)
                        ap = page.context.pages[-1] if len(page.context.pages) > before else page
                        status, note = "NEEDS_INFO", ""
                        try:
                            human_check(ap, "Indeed")
                            for _ in range(15):
                                filler.fill(ap, resume); ap.wait_for_timeout(500)
                                sub = ap.locator("button").filter(has_text=SUBMIT).first
                                if sub.count() and sub.is_visible():
                                    if dry_run: status, note = "DRY_RUN", "stopped before submit"; break
                                    sub.click(); ap.wait_for_timeout(3000); status, note = "APPLIED", ""; break
                                nx = ap.locator("button").filter(has_text=NEXT).first
                                if nx.count() and nx.is_visible(): nx.click(); ap.wait_for_timeout(1500); continue
                                raise NeedInfo("could not find continue/submit")
                        except NeedInfo as e:
                            status, note = "NEEDS_INFO", e.question; store.log_pending("indeed", title, company, e.question, url)
                        if ap is not page:
                            try: ap.close()
                            except Exception: pass
                        store.log_application("indeed", jid, title, company, locn, url, status, note); seen.add(("indeed", jid))
                        if status in ("APPLIED", "DRY_RUN"): done += 1; HOOKS["log"](f"   ✅ applied ({done})")
                    except Exception as e:
                        HOOKS["log"](f"   ⚠ {type(e).__name__}: {str(e)[:100]}")
    return done
