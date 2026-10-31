"""Browser control: a persistent Chrome profile so the user logs in ONCE by hand (no password is ever stored/typed by the bot)."""
import pathlib, os
from playwright.sync_api import sync_playwright

PROFILE_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "browser_profile"

class Browser:
    def __enter__(self):
        self.pw = sync_playwright().start()
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        kw = dict(user_data_dir=str(PROFILE_DIR), headless=False, no_viewport=True,
                  chromium_sandbox=True, ignore_default_args=["--enable-automation"], args=[])
        if os.name != "nt" and hasattr(os, "geteuid") and os.geteuid() == 0: kw["chromium_sandbox"] = False   # containers only
        try:
            self.ctx = self.pw.chromium.launch_persistent_context(channel="chrome", **kw)  # installed Google Chrome
        except Exception:
            self.ctx = self.pw.chromium.launch_persistent_context(**kw)                    # bundled Chromium
        self.ctx.add_init_script("try{var z=localStorage.getItem('jobbotZoom');if(z){document.addEventListener('DOMContentLoaded',function(){document.documentElement.style.zoom=z})}}catch(e){}")
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.page.set_default_timeout(15000)
        return self

    def live_page(self):
        """Always return an open tab (the user or a popup may have closed the previous one)."""
        for p in self.ctx.pages:
            if not p.is_closed():
                self.page = p; return p
        self.page = self.ctx.new_page(); self.page.set_default_timeout(15000)
        return self.page
    def __exit__(self, *a):
        try: self.ctx.close()
        except Exception: pass
        try: self.pw.stop()
        except Exception: pass

HOOKS = {"pause": None, "stop": False, "log": print, "result": ""}   # result: "", "limit", "quota", "stopped" (set by the site modules)

def should_stop(): return HOOKS["stop"]

def pause_for_human(msg):
    if HOOKS["pause"]:
        return HOOKS["pause"](msg)       # GUI: shows a "Continue" button
    input(f"\n⏸  {msg}\n   Do it in the browser window, then press ENTER here to continue... ")

def human_check(page, site):
    """Detect captcha / security checkpoint → hand control to the user (the bot never bypasses them)."""
    u = page.url.lower()
    body = ""
    try: body = page.inner_text("body")[:2000].lower()
    except Exception: pass
    if any(k in u for k in ("checkpoint", "captcha", "authwall", "challenge", "/login", "uas/login")) or \
       any(k in body for k in ("verify you are human", "vérifiez que vous êtes humain", "security check", "contrôle de sécurité", "just a moment")):
        pause_for_human(f"{site}: login or security check required.")
        return True
    return False


GOOGLE_BTN = ("iframe[src*='accounts.google.com/gsi'], div[role=button]:has-text('Google'), button:has-text('Google'), "
              "a:has-text('Google'), [data-provider='google'], button:has-text('Continuer avec Google'), button:has-text('Sign in with Google')")

def google_signed_in(ctx):
    """True when the persistent profile already has a Google session (cookie check, no password involved)."""
    return any(c["name"] in ("SID", "SAPISID", "__Secure-1PSID") for c in ctx.cookies("https://accounts.google.com"))

def google_session(b, email):
    """Open Google once; the USER types password / 2-step code. We only check that a session exists."""
    if google_signed_in(b.ctx): return True
    b.page.goto("https://accounts.google.com/ServiceLogin?hl=en")
    if email:
        try: b.page.fill("input[type=email]", email); b.page.click("#identifierNext")  # e-mail only, never the password
        except Exception: pass
    pause_for_human(f"Google: sign in as {email or 'your Gmail account'} (password / 2-step code typed by YOU).")
    return google_signed_in(b.ctx)

def pick_google_account(popup_or_page, email):
    """In the Google account chooser, click the account matching `email`; otherwise let the user choose."""
    p = popup_or_page
    p.wait_for_timeout(2500)
    try:
        if email:
            acc = p.locator(f"[data-identifier='{email}'], div[data-email='{email}']").first
            if acc.count(): acc.click(); p.wait_for_timeout(1500)
        for txt in ("Continue", "Continuer", "Allow", "Autoriser", "Sign in", "Se connecter"):
            btn = p.locator(f"button:has-text('{txt}')").first
            if btn.count() and btn.is_visible(): btn.click(); p.wait_for_timeout(1500); break
    except Exception: pass

def login_with_google(page, site, email):
    """Click 'Continue with Google' on the current login page and complete the chooser. Falls back to manual."""
    ctx = page.context
    try:
        btn = page.locator(GOOGLE_BTN).first
        if not btn.count(): return False
        with ctx.expect_page(timeout=6000) as pop:
            if btn.evaluate("e => e.tagName") == "IFRAME":
                page.frame_locator("iframe[src*='accounts.google.com/gsi']").first.locator("div[role=button]").first.click()
            else:
                btn.click()
        popup = pop.value
        pick_google_account(popup, email)
    except Exception:
        try:  # same-tab redirect flow (no popup)
            if "accounts.google.com" in page.url: pick_google_account(page, email)
        except Exception: pass
    try:
        page.wait_for_timeout(3000)
        return "accounts.google.com" not in page.url
    except Exception:   # tab closed by the popup flow → caller re-opens a live tab
        return False
