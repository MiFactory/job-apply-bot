"""Pop-ups that get in the way (LinkedIn "A postulé chez …" window, its "Supprimer de votre candidature ?" confirmation,
"Save this application?", close buttons) and friendly timeout messages.

Why: after Submit, LinkedIn shows a post-apply window. Closing it asks for a confirmation that covers the page, and every
following click then waits 15 s and fails with "Locator.click: Timeout exceeded". dismiss_popups() closes whatever is open,
in the right order, and only presses destructive-looking buttons (Supprimer / Discard) on dialogs it recognises as harmless
(they say it does not affect your profile / it is our own unfinished application)."""
import re
from .browser import HOOKS

# harmless confirmations: the text itself says nothing on the profile is lost
CONFIRM_PROFILE = re.compile(r"n.affectera pas votre profil|won.t affect your profile|will not affect your profile|not affect your linkedin profile|niet van invloed op je profiel|supprimer de votre candidature|delete from your application", re.I)
CONFIRM_SAVE = re.compile(r"save this application|enregistrer cette candidature|sollicitatie opslaan|discard application", re.I)
CONFIRM_BTN = re.compile(r"^(supprimer|delete|discard|abandonner|verwijderen|verwerpen)$", re.I)
CLOSE_SEL = ("button[aria-label*='Dismiss' i], button[aria-label*='Ignorer' i], button[aria-label*='Fermer' i], button[aria-label*='Close' i], "
             "button[aria-label*='Sluiten' i], button.artdeco-modal__dismiss, button:has-text('Ignorer'), button:has-text('Dismiss'), button:has-text('Not now'), button:has-text('Plus tard'), button:has-text('Pas maintenant')")
IGNORE = re.compile(r"suggestions? (disponibles?|available)|use arrow keys|utilisez les fl.ches", re.I)
DIALOGS = "dialog[open], div[role=dialog]:visible, div[role=alertdialog]:visible, .artdeco-modal:visible"


def _click_matching(scope, rx):
    for b in scope.locator("button").all():
        try:
            t = (b.inner_text(timeout=800) or b.get_attribute("aria-label") or "").strip()
            if rx.search(t) and b.is_visible():
                b.click(timeout=2500); return True
        except Exception: pass
    return False


def dismiss_popups(page, rounds=6):
    """Close every pop-up that is open. Returns how many were closed. Never raises."""
    closed = 0; last_sig = None
    try:
        for _ in range(rounds):
            dlgs = page.locator(DIALOGS)
            n = dlgs.count()
            if not n: break
            items = []
            for i in range(n):
                try: items.append((dlgs.nth(i), dlgs.nth(i).inner_text(timeout=1500)))
                except Exception: pass
            items = [(sc, t) for sc, t in items if not IGNORE.search(t)]      # search-box suggestion lists are not pop-ups
            if not items: break
            sig = " | ".join(" ".join(t.split())[:60] for _, t in items)
            if sig == last_sig: break                       # same pop-up still there after our attempt: do not loop on it
            last_sig = sig; done = False
            for scope, text in items:                       # 1) confirmations first (they sit on top of the other window)
                if CONFIRM_PROFILE.search(text) or CONFIRM_SAVE.search(text):
                    done = _click_matching(scope, CONFIRM_BTN)
                    if done: HOOKS["log"]("   ✖ closed confirmation pop-up"); break
            if not done:                                    # 2) then plain windows: the close (X) button of the top one
                scope, text = items[-1]
                try:
                    btn = scope.locator(CLOSE_SEL).first
                    if btn.count(): btn.click(timeout=2500); done = True
                except Exception: pass
                if not done:
                    try: page.keyboard.press("Escape"); page.wait_for_timeout(300); done = True
                    except Exception: pass
                if done: HOOKS["log"](f"   ✖ closed pop-up: {' '.join(text.split())[:50]}")
            if not done: break
            closed += 1; page.wait_for_timeout(300)
    except Exception:
        pass
    return closed


def friendly_error(e, secs=15):
    """Readable log line for an exception raised while handling one job."""
    name = type(e).__name__
    if "Timeout" in name:
        return (f"⏱ nothing clickable after {secs}s (a pop-up or a slow page was in the way) — job skipped for now. "
                f"Slow connection? raise “Timeout” in Search criteria.")
    return f"{name}: {str(e)[:100]}"
