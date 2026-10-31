import re, time, urllib.parse
from . import store, profile as P
from .browser import human_check, pause_for_human, login_with_google, should_stop, HOOKS
from .formfiller import Filler, NeedInfo

LIMIT_RE = re.compile(r"(daily|weekly)? ?limit|limite|reached the .*limit|atteint la limite|too many|trop de candidatures|nombre maximum", re.I)
BTN = {
 "next": r"continue to next step|next|passer à l.étape suivante|suivant|volgende",
 "review": r"review your application|vérifier votre candidature|review|controleren",
 "submit": r"submit application|envoyer la candidature|soumettre|verzenden|sollicitatie versturen",
}

class LimitReached(Exception): pass

def search_url(title, loc, crit, start=0):
    q = {"keywords": title, "location": loc, "sortBy": "DD", "start": start,
         "f_TPR": f"r{crit['posted_within_days'] * 86400}"}
    if crit["easy_apply_only"]: q["f_AL"] = "true"
    return "https://www.linkedin.com/jobs/search/?" + urllib.parse.urlencode(q)

def is_logged_in(page):
    page.goto("https://www.linkedin.com/feed/"); page.wait_for_timeout(2500)
    return "login" not in page.url and "authwall" not in page.url and "checkpoint" not in page.url

def ensure_login(page, google_email=""):
    if not is_logged_in(page) and google_email:
        page.goto("https://www.linkedin.com/login"); page.wait_for_timeout(2000)
        login_with_google(page, "LinkedIn", google_email)
    if not is_logged_in(page):
        pause_for_human("LinkedIn: please LOG IN in the browser window (the bot never handles your password).")
        if not is_logged_in(page): raise SystemExit("LinkedIn login not completed.")

def job_cards(page):
    page.wait_for_timeout(2000)
    for _ in range(6):  # lazy-load list
        try: page.mouse.wheel(0, 1800)
        except Exception: pass
        page.wait_for_timeout(500)
    return page.locator("li[data-occludable-job-id], div.job-card-container[data-job-id]")

def read_detail(page):
    g = lambda sel: (page.locator(sel).first.inner_text().strip() if page.locator(sel).count() else "")
    title = g(".job-details-jobs-unified-top-card__job-title, h1")
    company = g(".job-details-jobs-unified-top-card__company-name, .job-details-jobs-unified-top-card__primary-description-container a")
    loc = g(".job-details-jobs-unified-top-card__primary-description-container")
    desc = g("#job-details, .jobs-description__content, .jobs-box__html-content")
    return title, company, loc.split("·")[0].strip(), desc

def click_btn(modal, key):
    for b in modal.locator("button").all():
        try:
            t = ((b.get_attribute("aria-label") or "") + " " + b.inner_text()).strip()
            if re.search(BTN[key], t, re.I) and b.is_visible() and b.is_enabled():
                b.click(); return True
        except Exception: pass
    return False

def easy_apply(page, filler, resume_path, dry_run):
    btn = page.locator("button.jobs-apply-button:visible, .jobs-apply-button--top-card button:visible").first
    if not btn.count() or not re.search(r"easy apply|candidature simplifiée|eenvoudig solliciteren", btn.inner_text(), re.I):
        return "SKIP", "not Easy Apply"
    btn.click(); page.wait_for_timeout(1500)
    modal = page.locator("div[role=dialog], .jobs-easy-apply-modal").first
    if not modal.count(): return "SKIP", "modal did not open"
    if LIMIT_RE.search(modal.inner_text()[:600]): raise LimitReached(modal.inner_text()[:200])
    for _ in range(14):
        filler.fill(modal, resume_path)
        page.wait_for_timeout(400)
        # uncheck "follow company"
        for cb in modal.locator("input[type=checkbox]").all():
            try:
                if cb.is_checked() and re.search(r"follow|suivre|volgen", cb.evaluate("e=>e.closest('div').innerText").lower()):
                    cb.uncheck(force=True)
            except Exception: pass
        if click_btn(modal, "submit"):
            if dry_run:
                return "DRY_RUN", "stopped before final submit"
            page.wait_for_timeout(2500)
            body = page.inner_text("body")
            if LIMIT_RE.search(body[:3000]) and "limit" in body.lower(): raise LimitReached("limit message after submit")
            try: page.locator("button[aria-label*=Dismiss], button[aria-label*=Ignorer], button:has-text('Done'), button:has-text('Terminé')").first.click(timeout=2000)
            except Exception: pass
            return "APPLIED", ""
        if click_btn(modal, "review") or click_btn(modal, "next"):
            page.wait_for_timeout(900)
            err = modal.locator(".artdeco-inline-feedback--error, [data-test-form-element-error-messages]")
            if err.count() and err.first.is_visible():
                raise NeedInfo("form error: " + err.first.inner_text()[:120])
            continue
        raise NeedInfo("could not find next/submit button")
    raise NeedInfo("too many steps")

def discard(page):
    try:
        page.keyboard.press("Escape"); page.wait_for_timeout(500)
        page.locator("button:has-text('Discard'), button:has-text('Abandonner'), button:has-text('Annuler')").first.click(timeout=2000)
    except Exception: pass

def run(page, profile, criteria, max_apps, dry_run, interactive, asker=None, motivation=None):
    ensure_login(page, profile.get("google_email", ""))
    filler = Filler(profile, criteria, interactive, asker, motivation)
    seen = store.seen_jobs(); done = 0
    for title_q in criteria["titles"]:
        for loc in criteria["locations"]:
            for start in range(0, 100, 25):
                page.goto(search_url(title_q, loc, criteria, start)); human_check(page, "LinkedIn")
                cards = job_cards(page)
                n = cards.count()
                if n == 0: break
                for i in range(n):
                    if should_stop(): HOOKS["log"]("⏹ stopped by user"); return done
                    if done >= max_apps or store.count_today() >= criteria["max_applications_per_day"]:
                        HOOKS["log"]("✅ daily/run quota reached"); return done
                    try:
                        card = cards.nth(i); jid = card.get_attribute("data-occludable-job-id") or card.get_attribute("data-job-id") or str(i)
                        if ("linkedin", jid) in seen: continue
                        card.scroll_into_view_if_needed(timeout=4000)
                        try: card.locator("a").first.click(timeout=4000)
                        except Exception: card.click(timeout=4000, force=True)
                        page.wait_for_timeout(1400)
                        human_check(page, "LinkedIn")
                        title, company, loc_txt, desc = read_detail(page)
                        url = f"https://www.linkedin.com/jobs/view/{jid}/"
                        if company.lower() in [c.lower() for c in criteria["exclude_companies"]]:
                            store.log_application("linkedin", jid, title, company, loc_txt, url, "SKIPPED", "excluded company"); seen.add(("linkedin", jid)); continue
                        sc, why = P.score_job(title, desc, criteria)
                        if not P.location_ok(loc_txt, criteria): sc, why = 0, f"location outside target: {loc_txt}"
                        if sc < criteria["min_score"]:
                            store.log_application("linkedin", jid, title, company, loc_txt, url, "SKIPPED", why); seen.add(("linkedin", jid)); continue
                        lang = P.detect_lang(desc[:1500])
                        resume = profile["cv_files"].get(lang) or profile["cv_files"].get(profile["default_cv_lang"]) or ""
                        filler.ctx = {"title": title, "company": company, "lang": lang}
                        HOOKS["log"](f"→ {title} @ {company} ({loc_txt}) score={sc} cv={lang}")
                        try:
                            status, note = easy_apply(page, filler, resume, dry_run)
                        except NeedInfo as e:
                            status, note = "NEEDS_INFO", e.question; store.log_pending("linkedin", title, company, e.question, url); discard(page)
                        store.log_application("linkedin", jid, title, company, loc_txt, url, status, note); seen.add(("linkedin", jid))
                        if status in ("APPLIED", "DRY_RUN"): done += 1; HOOKS["log"](f"   ✅ applied ({done})"); page.wait_for_timeout(2500)
                    except LimitReached as e:
                        HOOKS["log"](f"🛑 LinkedIn limit reached: {e}. Stopping — try again tomorrow."); return done
                    except Exception as e:
                        HOOKS["log"](f"   ⚠ {type(e).__name__}: {str(e)[:100]}"); discard(page)
    return done
