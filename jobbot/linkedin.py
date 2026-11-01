import unicodedata, re, time, urllib.parse
from . import store, profile as P
from . import logger
from .browser import human_check, pause_for_human, login_with_google, should_stop, HOOKS
from .formfiller import Filler, NeedInfo
from . import popups

LIMIT_RE = re.compile(r"(daily|weekly|easy apply|application)s? limit|limit(e|s)? (has been |was )?reached|reached (the |your |today.s )?(daily |weekly )?(easy apply |application )?limit"
                      r"|limite (quotidienne|journalière|de candidatures|atteinte)|atteint (la|votre) limite|limiet (bereikt|van)|(dagelijkse|dagelijks) limiet|bereikt.{0,30}limiet", re.I)
BTN = {
 "next": r"continue to next step|next|passer à l.étape suivante|suivant|volgende",
 "review": r"review your application|vérifier votre candidature|review|controleren",
 "submit": r"submit application|envoyer la candidature|soumettre|verzenden|sollicitatie versturen",
}

class LimitReached(Exception): pass

# LinkedIn country IDs: with only the text "Belgium" LinkedIn may fall back to the city of YOUR profile (e.g. Paris).
GEO_IDS = {"belgium": "100565514", "belgique": "100565514", "belgië": "100565514", "france": "105015875",
           "luxembourg": "104042105", "netherlands": "102890719", "pays-bas": "102890719", "germany": "101282230",
           "allemagne": "101282230", "switzerland": "106693272", "suisse": "106693272", "spain": "105646813",
           "united kingdom": "101165590", "canada": "101174742", "morocco": "102787409", "maroc": "102787409"}

def search_url(title, loc, crit, start=0):
    q = {"keywords": title, "location": loc, "sortBy": "DD", "start": start,
         "f_TPR": f"r{crit['posted_within_days'] * 86400}"}
    gid = GEO_IDS.get((loc or "").strip().lower())
    if gid: q["geoId"] = gid
    if crit["easy_apply_only"]: q["f_AL"] = "true"
    return "https://www.linkedin.com/jobs/search/?" + urllib.parse.urlencode(q)

def check_search_location(page, wanted):
    """Warn (and log) when LinkedIn searches somewhere else than the location asked for."""
    try:
        got = page.evaluate("""() => { const e = document.querySelector("input[id*='location'], input[aria-label*='ocation'], input[aria-label*='Lieu']"); return e ? e.value : ''; }""") or ""
        logger.info(f"SEARCH LOCATION wanted='{wanted}' linkedin_shows='{got}'")
        def n(x): 
            x = "".join(c for c in unicodedata.normalize("NFKD", x.lower()) if not unicodedata.combining(c))
            return x.replace("brussels", "bruxelles").replace("brussel", "bruxelles").replace("belgium", "belgique").replace("belgie", "belgique")
        parts = [x.strip() for x in n(wanted).split(",")]
        if got and wanted and not any(x and x in n(got) for x in parts) and not (len(parts) > 1 and parts[-1] in n(got)):
            HOOKS["log"](f"   ⚠ LinkedIn is searching in '{got}' instead of '{wanted}' — jobs outside the target are skipped. Check the location text in Search criteria.")
    except Exception as e: logger.error("check_search_location", e, page)

BLOCK_URL = ("checkpoint", "challenge", "authwall", "/login", "uas/login", "/signup")

def blocked(page):
    """True when LinkedIn shows a login / security check / guest (logged-out) page instead of the real one."""
    try:
        u = page.url.lower()
        if any(k in u for k in BLOCK_URL): return True
        return bool(page.evaluate("""() => { const t = [...document.querySelectorAll('a,button')].map(e => (e.innerText||'').trim().toLowerCase());
            return t.includes("s'identifier") || t.includes('sign in') || t.includes('inscrivez-vous') && t.includes("s'inscrire"); }"""))
    except Exception: return False

def goto_checked(page, url):
    """Open a LinkedIn page; if it ends on a login / security check (also after a late redirect) hand the browser to the user, then reload."""
    for attempt in range(3):
        page.goto(url, wait_until="domcontentloaded"); page.wait_for_timeout(2500)
        if not blocked(page): return True
        logger.info(f"BLOCKED page at {page.url[:100]} (attempt {attempt + 1})")
        pause_for_human("LinkedIn asks you to log in / pass a security check (or the session expired). Do it in the browser window, then press Continue.")
    return not blocked(page)

def is_logged_in(page):
    for attempt in range(3):                  # "Navigation ... interrupted by another navigation" = LinkedIn redirecting: wait and retry
        try: page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded"); break
        except Exception as e:
            logger.error("is_logged_in goto (attempt %d)" % (attempt + 1), e, page); page.wait_for_timeout(2500)
    page.wait_for_timeout(2500)
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
    try: page.mouse.move(260, 520)                    # over the results list (left pane), so the wheel scrolls the list
    except Exception: pass
    for _ in range(6):  # lazy-load list
        try: page.mouse.wheel(0, 1800)
        except Exception: pass
        page.wait_for_timeout(500)
    legacy = page.locator("li[data-occludable-job-id], div.job-card-container[data-job-id]")
    if legacy.count(): return legacy
    return page.locator(NEW_CARD)            # LinkedIn's new layout (/jobs/search-results/, hashed class names)

NEW_CARD = 'div[role=button][componentkey^="job-card-component-ref-"]'      # all ~25 cards of a page are in the DOM; the job id is in componentkey

def card_id(card, i):
    """Job id of a result card: legacy attributes, or currentJobId=<id> in the link of the new layout."""
    jid = card.get_attribute("data-occludable-job-id") or card.get_attribute("data-job-id")
    if jid: return jid
    try:
        m = re.search(r"job-card-component-ref-(\d+)", card.get_attribute("componentkey") or "")
        if m: return m.group(1)
    except Exception: pass
    try:
        href = card.get_attribute("href") or card.locator("a[href*='currentJobId=']").first.get_attribute("href") or ""
        m = re.search(r"currentJobId=(\d+)", href)
        if m: return m.group(1)
    except Exception: pass
    return str(i)

# New layout detail pane, read without class names (they are hashed and change): the results list is one LazyColumn,
# the job details the other one; title = link to /jobs/view/, company = link to /company/, description = under the "About the job" heading.
NEW_DETAIL_JS = """() => {
  const h = [...document.querySelectorAll('h2')].find(x => /propos de l.offre|about the job/i.test(x.innerText || ''));
  const t = document.querySelector('a[href*="/jobs/view/"]');
  if (!h || !t) return null;
  let det = t.parentElement;                                   // smallest block holding both the title link and the "About the job" heading
  while (det && !det.contains(h)) det = det.parentElement;
  if (!det) return null;
  const lines = det.innerText.split('\\n').map(x => x.trim()).filter(Boolean);
  const co = det.querySelector('a[href*="/company/"]');
  const meta = lines.find(l => /·\\s*(il y a|.*\\bago\\b|republi|reposted)/i.test(l) && l.length < 220) || '';
  const box = h.parentElement && h.parentElement.parentElement;
  return { title: t.innerText.trim(), company: co ? co.innerText.trim() : (lines[0] || ''), loc: meta.split('·')[0].trim(), desc: box ? box.innerText : det.innerText };
}"""

def read_detail(page):
    if not page.locator(".job-details-jobs-unified-top-card__job-title, h1").count():     # new layout
        for attempt in range(5):                                                          # the pane can take a few seconds to fill
            try:
                d = page.evaluate(NEW_DETAIL_JS)
                if d and d.get("title"): return d["title"], d["company"], d["loc"], d["desc"]
            except Exception as e: logger.error("read_detail (new layout)", e, page)
            page.wait_for_timeout(1200)
        try:                                                                              # last resort: the tab title is "Job | Company | LinkedIn"
            parts = [x.strip() for x in page.title().split("|")]
            if parts and parts[0] and "linkedin" not in parts[0].lower():
                body = page.evaluate("() => document.body.innerText") or ""
                logger.info("read_detail: used the tab title " + page.title())
                return parts[0], (parts[1] if len(parts) > 2 else ""), "", body[:6000]
        except Exception as e: logger.error("read_detail (tab title)", e, page)
    g = lambda sel: (page.locator(sel).first.inner_text().strip() if page.locator(sel).count() else "")
    title = g(".job-details-jobs-unified-top-card__job-title, h1")
    company = g(".job-details-jobs-unified-top-card__company-name, .job-details-jobs-unified-top-card__primary-description-container a")
    loc = g(".job-details-jobs-unified-top-card__primary-description-container")
    desc = g("#job-details, .jobs-description__content, .jobs-box__html-content")
    return title, company, loc.split("·")[0].strip(), desc

def click_btn(modal, key, click=True):
    """Find the visible button for `key`; click it unless click=False (used by --dry-run: look, never press Submit)."""
    for b in modal.locator("button").all():
        try:
            t = ((b.get_attribute("aria-label") or "") + " " + b.inner_text()).strip()
            if re.search(BTN[key], t, re.I) and b.is_visible() and b.is_enabled():
                if click: b.click()
                return True
        except Exception: pass
    return False

APPLY_RE = re.compile(r"easy apply|candidature simplifi[ée]e|eenvoudig solliciteren|continue application|continuer la candidature|reprendre|doorgaan met solliciteren", re.I)

def find_apply_button(page):
    """The Easy Apply / «continue application» (draft) button, whatever tag/class LinkedIn uses this week."""
    for sel in ("button.jobs-apply-button:visible, .jobs-apply-button--top-card button:visible", "main button:visible, main a:visible", "button:visible"):
        loc = page.locator(sel).filter(has_text=APPLY_RE)
        if loc.count(): return loc.first
    return None

def click_hard(page, btn):
    """Normal click; if something (chat bubble, sticky bar) intercepts it → JS click."""
    for how in range(2):
        try:
            if how and btn.is_disabled(): return False                 # a really disabled button is never forced
            if how == 0: btn.click()                                    # uses your Timeout setting
            else: btn.evaluate("e => e.click()")                        # reaches the button even when an overlay (chat bubble, sticky bar) covers it
            return True
        except Exception:
            if how == 0: popups.dismiss_popups(page)
    return False

def easy_apply(page, filler, resume_path, dry_run):
    btn = find_apply_button(page)
    if btn is None: return "SKIP", "not Easy Apply"
    if not click_hard(page, btn): raise TimeoutError("apply button could not be clicked")
    page.wait_for_timeout(1500)
    modal = page.locator("dialog[open], div[role=dialog], .jobs-easy-apply-modal").first      # new layout: native <dialog open>
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
        if dry_run and click_btn(modal, "submit", click=False):
            discard(page)                                              # close the half-filled form, otherwise it covers the next job
            popups.dismiss_popups(page)
            return "DRY_RUN", "stopped before final submit"          # the Submit button is only LOOKED AT, never pressed
        if click_btn(modal, "submit"):
            page.wait_for_timeout(2500)
            body = page.inner_text("body")
            if LIMIT_RE.search(body[:3000]): raise LimitReached("limit message after submit")
            popups.dismiss_popups(page)          # post-apply window + its "Supprimer de votre candidature ?" confirmation
            return "APPLIED", ""
        if click_btn(modal, "review") or click_btn(modal, "next"):
            page.wait_for_timeout(900)
            err = modal.locator(".artdeco-inline-feedback--error, [data-test-form-element-error-messages], [role=alert]")
            if err.count() and err.first.is_visible():
                raise NeedInfo("form error: " + err.first.inner_text()[:120])
            continue
        try: btns = [re.sub(r"\s+", " ", (b.inner_text() or b.get_attribute("aria-label") or "")).strip()[:25] for b in modal.locator("button").all() if b.is_visible()]
        except Exception: btns = []
        logger.info(f"NO NEXT BUTTON url={page.url[:80]} buttons={btns} text={re.sub(chr(10)+'+', ' / ', modal.inner_text()[:400])}")
        raise NeedInfo(f"could not find next/submit button (buttons: {btns})")
    raise NeedInfo("too many steps")

SAVE_Q = re.compile(r"enregistrer cette candidature|save this application|candidature sera abandonn|discard (this )?application|abandonn", re.I)
DISCARD_BTN = re.compile(r"^\s*(discard|abandonner|supprimer|annuler la candidature|delete)\s*$", re.I)

def discard(page):
    """Close the Easy Apply form WITHOUT saving: Escape, then press Discard/Abandonner/Supprimer in the 'Save this application?' window."""
    try:
        page.keyboard.press("Escape"); page.wait_for_timeout(700)
        for _ in range(3):
            done = False
            for d in page.locator("dialog[open], div[role=dialog], div[role=alertdialog]").all():
                try:
                    if not d.is_visible() or not SAVE_Q.search(d.inner_text() or ""): continue
                    for b in d.locator("button").all():
                        if b.is_visible() and DISCARD_BTN.match((b.inner_text() or b.get_attribute("aria-label") or "")):
                            b.click(timeout=2000); page.wait_for_timeout(600); done = True; logger.info("discard: pressed " + (b.inner_text() or "")[:20]); break
                except Exception: pass
                if done: break
            if not done: break
    except Exception as e: logger.error("discard", e, page)

def open_card(page, card, jid, timeout_ms=6000):
    """Click a result card and make sure the detail pane really switched to THAT job (LinkedIn keeps the old one when a click is swallowed).
    Returns True when the pane shows the job (URL currentJobId=<jid>, or the title changed); retries the click once."""
    def title():
        try: return page.locator(".job-details-jobs-unified-top-card__job-title, h1").first.inner_text(timeout=1000).strip()
        except Exception: return ""
    before = title()
    for attempt in range(2):
        card.scroll_into_view_if_needed(timeout=4000)
        try:
            if card.locator("a").count(): card.locator("a").first.click(timeout=4000)
            else: card.click(timeout=4000)                          # new layout: the card itself is the button
        except Exception: card.click(timeout=4000, force=True)
        waited = 0
        while waited < timeout_ms:
            page.wait_for_timeout(300); waited += 300
            if f"currentJobId={jid}" in page.url or f"/jobs/view/{jid}" in page.url: break
            t = title()
            if t and t != before: break
        else:
            popups.dismiss_popups(page); continue                   # nothing changed: a pop-up probably swallowed the click
        page.wait_for_timeout(500); return True
    return False


def run(page, profile, criteria, max_apps, dry_run, interactive, asker=None, motivation=None):
    ensure_login(page, profile.get("google_email", ""))
    filler = Filler(profile, criteria, interactive, asker, motivation)
    seen = store.seen_jobs(); done = 0; fails = 0; skipped = 0          # fails = consecutive jobs that went wrong (stuck page)
    for title_q in criteria["titles"]:
        for loc in criteria["locations"]:
            for start in range(0, 100, 25):
                url_s = search_url(title_q, loc, criteria, start); logger.step("linkedin", "", f"search '{title_q}' in '{loc}' page {start // 25 + 1}"); logger.info("GOTO " + url_s)
                if not goto_checked(page, url_s): HOOKS["log"]("⛔ LinkedIn is still on a login / security page — stopping this run. Log in with 🔑 LinkedIn, then start again."); HOOKS["result"] = "login"; return done
                check_search_location(page, loc)
                cards = job_cards(page)
                n = cards.count()
                HOOKS["log"](f"🔎 '{title_q}' / {loc} / page {start // 25 + 1}: {n} job card(s)" + ("" if n else f" — nothing found (page: {page.url[:90]})"))
                if n == 0: break
                for i in range(n):
                    if should_stop(): HOOKS["result"] = "stopped"; HOOKS["log"]("⏹ stopped by user"); return done
                    if done >= max_apps or store.count_today() >= criteria["max_applications_per_day"]:
                        if store.count_today() >= criteria["max_applications_per_day"]: HOOKS["result"] = "quota"
                        HOOKS["log"]("✅ daily/run quota reached"); return done
                    try:
                        popups.dismiss_popups(page)
                        if "/jobs/search" not in page.url:               # the new layout opens the job page itself: go back to the results list
                            HOOKS["log"]("   ↩ back to the search results"); logger.info("RETURN to " + url_s)
                            page.goto(url_s, wait_until="domcontentloaded"); human_check(page, "LinkedIn"); cards = job_cards(page)
                            if cards.count() <= i: break
                        card = cards.nth(i); jid = card_id(card, i)
                        if ("linkedin", jid) in seen: continue
                        if fails >= 8: HOOKS["log"]("   ↻ still stuck — skipping the rest of this page"); fails = 0; break
                        if fails == 4:
                            HOOKS["log"]("   ↻ several jobs failed in a row — reloading the page"); popups.dismiss_popups(page); page.reload(); page.wait_for_timeout(2500); cards = job_cards(page); fails += 1
                            card = cards.nth(i)
                        try: card_txt = card.inner_text(timeout=1500)
                        except Exception: card_txt = ""
                        if re.search(r"candidature envoy|application sent|^applied|postulé", card_txt, re.I | re.M):      # already applied (new layout shows it on the card)
                            seen.add(("linkedin", jid)); HOOKS["log"](f"   ⏭ already applied: {card_txt.splitlines()[0][:60] if card_txt else jid}"); continue
                        if not open_card(page, card, jid):
                            raise TimeoutError("job details did not switch to this job")
                        human_check(page, "LinkedIn")
                        title, company, loc_txt, desc = read_detail(page)
                        if blocked(page) or re.search(r"conditions g[ée]n[ée]rales|terms of service|user agreement|bienvenue dans votre communaut|welcome to your professional", title or "", re.I):
                            logger.info(f"GUEST/BLOCKED page read as job title '{title}'")
                            if not goto_checked(page, url_s): HOOKS["log"]("⛔ LinkedIn session lost — log in with 🔑 LinkedIn and start again."); HOOKS["result"] = "login"; return done
                            break                                     # re-read this results page after the login
                        if not title.strip(): raise TimeoutError("job details did not load")     # never log an unreadable page as SKIPPED
                        url = f"https://www.linkedin.com/jobs/view/{jid}/"
                        if company.lower() in [c.lower() for c in criteria["exclude_companies"]]:
                            store.log_application("linkedin", jid, title, company, loc_txt, url, "SKIPPED", "excluded company"); seen.add(("linkedin", jid)); HOOKS["log"](f"   ⏭ skipped: {title} @ {company} — excluded company"); continue
                        sc, why = P.score_job(title, desc, criteria)
                        if not P.location_ok(loc_txt, criteria): sc, why = 0, f"location outside target: {loc_txt}"
                        if sc < criteria["min_score"]:
                            store.log_application("linkedin", jid, title, company, loc_txt, url, "SKIPPED", why); seen.add(("linkedin", jid)); skipped += 1
                            HOOKS["log"](f"   ⏭ skipped: {title} @ {company} ({loc_txt}) — {why}"); continue
                        lang = P.detect_lang(desc[:1500])
                        resume = profile["cv_files"].get(lang) or profile["cv_files"].get(profile["default_cv_lang"]) or ""
                        filler.ctx = {"title": title, "company": company, "lang": lang}
                        HOOKS["log"](f"→ {title} @ {company} ({loc_txt}) score={sc} cv={lang}"); logger.step("linkedin", f"{jid} {title} @ {company}", "easy apply")
                        try:
                            status, note = easy_apply(page, filler, resume, dry_run)
                        except NeedInfo as e:
                            status, note = "NEEDS_INFO", e.question; store.log_pending("linkedin", title, company, e.question, url); discard(page)
                        store.log_application("linkedin", jid, title, company, loc_txt, url, status, note)
                        HOOKS["log"](f"   → result: {status}" + (f" — {note}" if note else ""))
                        seen.add(("linkedin", jid))                        # once per run; a REAL run tries DRY_RUN jobs again (store.seen_jobs ignores them)
                        fails = 0
                        if status in ("APPLIED", "DRY_RUN"): done += 1; HOOKS["log"](f"   ✅ {'applied' if status == 'APPLIED' else 'ready to apply (dry run)'} ({done})"); page.wait_for_timeout(2500)
                    except LimitReached as e:
                        HOOKS["result"] = "limit"; HOOKS["log"](f"🛑 LinkedIn limit reached: {e}. Run stopped (a schedule retries automatically)."); return done
                    except Exception as e:
                        fails += 1
                        detail = logger.error("linkedin.run", e, page)
                        HOOKS["log"]("   ⚠ " + popups.friendly_error(e, criteria.get("timeout_seconds", 15)) + f"   → details in {logger.log_path().name}"); HOOKS["log"]("      " + detail); popups.dismiss_popups(page); discard(page)
                        try: seen.add(("linkedin", jid))                   # never loop on the same card in this run
                        except Exception: pass
    return done


# ---------------------------------------------------------------------------------------------- saved jobs
SAVED_URL = "https://www.linkedin.com/my-items/saved-jobs/"
CLOSED_RE = re.compile(r"no longer accepting applications|n.accepte plus de candidatures|accepteert geen sollicitaties meer", re.I)
SAVED_STATE_RE = re.compile(r"\b(saved|enregistr[ée]e?|opgeslagen|unsave)\b", re.I)
MORE_RE = re.compile(r"show more|afficher plus|voir plus|meer weergeven", re.I)

DRAFT_URL = "https://www.linkedin.com/jobs-tracker/?stage=draft"      # «Suivi des emplois › Brouillon»: applications you started but never sent

def draft_job_ids(page, max_rounds=12):
    """Job ids of your started-but-unsent applications (drafts)."""
    return saved_job_ids(page, max_rounds, DRAFT_URL)

def saved_job_ids(page, max_rounds=12, url=None):
    """Job ids in your LinkedIn «Saved jobs» list (scrolls / presses «show more» until nothing new appears)."""
    page.goto(url or SAVED_URL); page.wait_for_timeout(2000); human_check(page, "LinkedIn")
    ids = []
    for r in range(max_rounds):
        popups.dismiss_popups(page)
        found = page.evaluate("""() => [...new Set([...document.querySelectorAll('a[href*="/jobs/view/"]')].map(a => (a.href.match(/\\/jobs\\/view\\/(\\d+)/) || [])[1]).filter(Boolean))]""")
        new = [i for i in found if i not in ids]; ids += new
        if r > 0 and not new: break
        try:
            more = page.locator("button").filter(has_text=MORE_RE).first
            if more.count() and more.is_visible(): more.click(timeout=3000)
            else: page.mouse.wheel(0, 3000)
        except Exception: pass
        page.wait_for_timeout(900)
    return ids

def unsave_job(page):
    """Remove the open job from Saved (only if its Save button is in the «Saved» state)."""
    for b in page.locator("button.jobs-save-button, button[aria-label*='save' i], button[aria-label*='enregistr' i], button[aria-label*='opgeslagen' i]").all():
        try:
            t = ((b.get_attribute("aria-label") or "") + " " + b.inner_text()).strip()
            if SAVED_STATE_RE.search(t) and b.is_visible(): b.click(timeout=3000); page.wait_for_timeout(500); return True
        except Exception: pass
    return False

def run_saved(page, profile, criteria, max_apps, dry_run, interactive, asker=None, motivation=None):
    """Apply to the jobs you saved on LinkedIn. Your search filters (title / location / score) are NOT applied: you chose these jobs."""
    ensure_login(page, profile.get("google_email", ""))
    filler = Filler(profile, criteria, interactive, asker, motivation)
    finished = store.finished_saved_jobs(); done = 0
    ids = saved_job_ids(page); HOOKS["log"](f"⭐ {len(ids)} saved job(s) found")
    if criteria.get("include_drafts", True):
        try:
            dr = [i for i in draft_job_ids(page) if i not in ids]; ids += dr; HOOKS["log"](f"📝 {len(dr)} draft application(s) found (started, not sent)")
        except Exception as e: HOOKS["log"]("   ⚠ could not read drafts: " + popups.friendly_error(e, criteria.get("timeout_seconds", 15)))
    for jid in ids:
        if should_stop(): HOOKS["result"] = "stopped"; HOOKS["log"]("⏹ stopped by user"); return done
        if done >= max_apps or store.count_today() >= criteria["max_applications_per_day"]:
            if store.count_today() >= criteria["max_applications_per_day"]: HOOKS["result"] = "quota"
            HOOKS["log"]("✅ daily/run quota reached"); return done
        if ("linkedin", jid) in finished: continue
        url = f"https://www.linkedin.com/jobs/view/{jid}/"
        try:
            popups.dismiss_popups(page)
            page.goto(url); human_check(page, "LinkedIn")
            try: page.wait_for_selector(".job-details-jobs-unified-top-card__job-title, h1", timeout=int(criteria.get("timeout_seconds", 15)) * 1000)
            except Exception: pass
            page.wait_for_timeout(1200)
            title, company, loc_txt, desc = read_detail(page)
            if not title.strip(): raise TimeoutError("job details did not load")
            if company.lower() in [c.lower() for c in criteria["exclude_companies"]]:
                store.log_application("linkedin", jid, title, company, loc_txt, url, "SKIPPED", "saved: excluded company"); finished.add(("linkedin", jid)); continue
            if CLOSED_RE.search(page.inner_text("body")[:6000]):
                HOOKS["log"](f"→ ⭐ {title} @ {company} — no longer accepting applications")
                store.log_application("linkedin", jid, title, company, loc_txt, url, "SKIPPED", "saved: no longer accepting applications"); finished.add(("linkedin", jid)); continue
            lang = P.detect_lang(desc[:1500])
            resume = profile["cv_files"].get(lang) or profile["cv_files"].get(profile["default_cv_lang"]) or ""
            filler.ctx = {"title": title, "company": company, "lang": lang}
            HOOKS["log"](f"→ ⭐ {title} @ {company} ({loc_txt}) cv={lang}")
            try:
                status, note = easy_apply(page, filler, resume, dry_run)
            except NeedInfo as e:
                status, note = "NEEDS_INFO", e.question; store.log_pending("linkedin", title, company, e.question, url); discard(page)
            if status == "SKIP":
                status, note = "SKIPPED", "saved: not Easy Apply — apply on the company site"; finished.add(("linkedin", jid))
            store.log_application("linkedin", jid, title, company, loc_txt, url, status, note if status != "APPLIED" else "saved job")
            if status in ("APPLIED", "DRY_RUN"):
                done += 1; HOOKS["log"](f"   ✅ applied ({done})")
                if status == "APPLIED" and criteria.get("unsave_after_apply") and unsave_job(page): HOOKS["log"]("   ☆ removed from Saved")
                page.wait_for_timeout(2500)
        except LimitReached as e:
            HOOKS["result"] = "limit"; HOOKS["log"](f"🛑 LinkedIn limit reached: {e}. Run stopped (a schedule retries automatically)."); return done
        except Exception as e:
            HOOKS["log"]("   ⚠ " + popups.friendly_error(e, criteria.get("timeout_seconds", 15))); popups.dismiss_popups(page); discard(page)
    return done
