"""Generic form filler: maps field labels → profile values → remembered answers → ask the user."""
import re
from . import store

class NeedInfo(Exception):
    def __init__(self, q): self.question = q; super().__init__(q)

YES = ("yes", "oui", "ja", "si", "sí")
NO = ("no", "non", "nee")

def rules(p):
    ph = re.sub(r"\D", "", p["phone_national"] or p["phone"])
    yrs = str(p["years_experience_total"])
    return [
     (r"first name|prénom|voornaam", p["first_name"]),
     (r"last name|family name|surname|nom de famille|achternaam", p["last_name"]),
     (r"^(full )?name$|^nom( complet)?$", f'{p["first_name"]} {p["last_name"]}'.strip()),
     (r"e-?mail", p["email"]),
     (r"country code|indicatif|code pays|landcode", p["phone_country_code"]),
     (r"phone|mobile|téléphone|telefoon|gsm", ph),
     (r"postal|zip|code postal|postcode", p["postal_code"]),
     (r"city|ville|stad|location \(city\)|town", p["city"]),
     (r"linkedin", p["linkedin_url"]),
     (r"website|portfolio|site web", p["website"] or p["linkedin_url"]),
     (r"headline|titre", p["headline"]),
     (r"notice|préavis|opzeg|disponib|available|start date|date de début", p["notice_period"]),
     (r"salary.*(month|mois|maand)|(month|mois|maand).*salary|salaire.*mensuel", str(p["salary_month_eur"])),
     (r"salary|salaire|loon|rémunération|compensation|expected", str(p["salary_year_eur"])),
     (r"sponsor", "no" if not p["needs_sponsorship"] else "yes"),
     (r"authori[sz]ed|legally|right to work|work permit|permis de travail|autorisé|eligible to work", "yes" if p["authorized_to_work"] else "no"),
     (r"relocat|déménag|verhuizen", "yes" if p["willing_relocate"] else "no"),
     (r"driv|permis de conduire|rijbewijs", "yes" if p["driving_licence"] else "no"),
     (r"degree|diploma|diplôme|bachelor|master|education level|niveau d.étude", "yes"),
     (r"how many years|years of (work )?experience|années d.expérience|jaren ervaring|experience.*years", None),  # handled below
    ]

def answer_for(label: str, p: dict, kind: str = "text"):
    l = label.lower().strip()
    m = re.search(r"(?:years|ans|jaar).*?(?:of )?(?:experience|expérience)?.*?(?:with|in|using|en|avec|met)\s+(.+?)[\?\.]?$", l)
    if re.search(r"how many years|years of|années d|jaren|experience.*years", l):
        for sk, y in p["years_by_skill"].items():
            if sk.lower() in l:
                return str(y)
        return str(p["years_experience_total"])
    for lang, lvl in p["languages"].items():
        if lang in l or {"english": "anglais", "french": "français", "dutch": "néerlandais"}.get(lang, "#") in l:
            if re.search(r"proficien|level|niveau|fluen|speak|parl", l):
                return lvl
    for pat, val in rules(p):
        if val is not None and re.search(pat, l):
            return val
    return None

def pick_option(options, wanted: str):
    w = (wanted or "").lower()
    if w in ("yes", "no"):
        group = YES if w == "yes" else NO
        for o in options:
            if o.lower().strip().startswith(group):
                return o
    for o in options:
        if w and (w in o.lower() or o.lower() in w):
            return o
    return None

LABEL_JS = """el => {
  const t = x => (x && x.innerText || '').trim();
  let s = '';
  if (el.id) { const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); s = t(l); }
  if (!s) { const lb = el.getAttribute('aria-labelledby'); if (lb) s = lb.split(' ').map(i => t(document.getElementById(i))).join(' ').trim(); }
  if (!s) s = el.getAttribute('aria-label') || '';
  if (!s) { const fs = el.closest('fieldset'); if (fs) s = t(fs.querySelector('legend')) || t(fs.querySelector('span')); }
  if (!s) { const g = el.closest('[data-test-form-element], .fb-dash-form-element, .jobs-easy-apply-form-section__grouping, div'); s = g ? (g.innerText || '').split('\\n')[0] : ''; }
  if (!s) s = el.placeholder || el.name || '';
  return s.replace(/\\s+/g, ' ').trim();
}"""

GROUP_JS = """el => {
  const t = x => (x && x.innerText || '').trim();
  let s = '';
  const fs = el.closest('fieldset, [role=radiogroup], [role=group]');
  if (fs) { s = t(fs.querySelector('legend')) || t(fs.querySelector('[data-test-form-builder-radio-button-form-component__title], span, label')); 
            const lb = fs.getAttribute('aria-labelledby'); if (!s && lb) s = lb.split(' ').map(i => t(document.getElementById(i))).join(' '); }
  if (!s) { const g = el.closest('div'); s = g && g.parentElement ? (g.parentElement.innerText || '').split('\\n')[0] : ''; }
  return s.replace(/\\s+/g, ' ').trim();
}"""

def clean_label(l: str) -> str:
    l = re.sub(r"\s+", " ", l or "").strip()
    h = len(l) // 2
    if len(l) > 6 and l[:h].strip() == l[h:].strip(): l = l[:h].strip()        # "X X" -> "X"
    words = l.split(" ")
    if len(words) > 3 and len(words) % 2 == 0 and words[:len(words)//2] == words[len(words)//2:]: l = " ".join(words[:len(words)//2])
    return l

FILE_LIKE = re.compile(r"\.(pdf|docx?|odt|rtf)\b", re.I)
COVER = re.compile(r"cover letter|motivation|lettre de motivation|motivatiebrief|message to (the )?(hiring|recruiter)|why (do you want|are you interested)|pourquoi", re.I)

class Filler:
    def __init__(self, profile, criteria, interactive=True, asker=None, motivation=None):
        self.p, self.c, self.interactive, self.asker = profile, criteria, interactive, asker
        self.motivation = motivation or {}      # {"en": "...", "fr": "..."}  with {company} {title}
        self.ctx = {"title": "", "company": "", "lang": "en"}
        self.answers = store.load_answers()

    def resolve(self, label, kind="text", options=None):
        label = clean_label(label)
        if COVER.search(label) and (self.motivation.get(self.ctx["lang"]) or self.motivation.get("default")):
            t = self.motivation.get(self.ctx["lang"]) or self.motivation.get("default")
            return t.replace("{full_name}", (self.p["first_name"] + " " + self.p["last_name"]).strip()).replace("{company}", self.ctx["company"] or "your company").replace("{title}", self.ctx["title"] or "this position")
        a = answer_for(label, self.p, kind)
        if a is None:
            a = self.answers.get(store.norm(label)) or store.load_answers().get(store.norm(label))
        if a is None and self.asker:
            a = self.asker(label, options or [], self.ctx)      # GUI: blocks until user answers in the right panel
            if a: store.save_answer(label, a)
        elif a is None:
            if self.c.get("ask_user_when_unknown") and self.interactive:
                print(f"\n❓ Question in the form: {label}" + (f"\n   options: {options}" if options else ""))
                a = input("   Your answer (saved for next time; empty = skip this job): ").strip()
                if a: store.save_answer(label, a)
            if not a:
                raise NeedInfo(label)
        return a

    def fill(self, scope, resume_path=None):
        """Fill all visible, empty fields inside scope (Locator or Page). Returns number of fields touched."""
        n = 0
        # resume upload
        for fi in scope.locator("input[type=file]").all():
            try:
                if resume_path and fi.is_visible() or (resume_path and fi.count()):
                    fi.set_input_files(resume_path); n += 1
            except Exception: pass
        # text / number / textarea
        for el in scope.locator("input:not([type=hidden]):not([type=file]):not([type=submit]):not([type=button]):not([type=radio]):not([type=checkbox]), textarea").all():
            try:
                if not el.is_visible() or el.is_disabled(): continue
                if (el.input_value() or "").strip(): continue
                label = el.evaluate(LABEL_JS)
                if FILE_LIKE.search(label): continue
                val = self.resolve(label, "text")
                el.fill(str(val)); n += 1
                if el.get_attribute("role") == "combobox" or el.get_attribute("aria-autocomplete"):
                    el.page.wait_for_timeout(700); el.press("ArrowDown"); el.press("Enter")
            except NeedInfo: raise
            except Exception: continue
        # selects
        for el in scope.locator("select").all():
            try:
                if not el.is_visible() or el.is_disabled(): continue
                cur = el.evaluate("e => e.selectedOptions[0] ? e.selectedOptions[0].text : ''")
                if cur and not re.search(r"select|choisir|sélection|kies|^-", cur.lower()): continue
                label = el.evaluate(LABEL_JS)
                opts = [o.strip() for o in el.locator("option").all_inner_texts() if o.strip()]
                want = self.resolve(label, "select", opts)
                o = pick_option(opts, want)
                if not o: raise NeedInfo(f"{label} (no matching option for '{want}': {opts})")
                el.select_option(label=o); n += 1
            except NeedInfo: raise
            except Exception: continue
        # radio groups
        seen = set()
        for r in scope.locator("input[type=radio]").all():
            try:
                name = r.get_attribute("name")
                if name in seen: continue
                seen.add(name)
                grp = scope.locator(f'input[type=radio][name="{name}"]')
                if any(g.is_checked() for g in grp.all()): continue
                label = r.evaluate(GROUP_JS)
                if FILE_LIKE.search(label): continue            # resume chooser: keep LinkedIn's pre-selected CV
                labs = []
                for g in grp.all():
                    gid = g.get_attribute("id")
                    lab = scope.locator(f'label[for="{gid}"]').first.inner_text().strip() if gid else ""
                    labs.append(lab)
                want = self.resolve(label, "radio", labs)
                o = pick_option(labs, want)
                if not o: raise NeedInfo(f"{label} (options {labs})")
                i = labs.index(o)
                try: grp.nth(i).check(force=True)
                except Exception: scope.locator(f'label:has-text("{o}")').first.click()
                n += 1
            except NeedInfo: raise
            except Exception: continue
        # required checkboxes (consent) – only tick when label is about confirming data / terms; never "follow company"
        for cb in scope.locator("input[type=checkbox]").all():
            try:
                if not cb.is_visible() or cb.is_checked(): continue
                label = cb.evaluate(LABEL_JS).lower()
                if re.search(r"follow|suivre|volgen|newsletter|marketing|job alert", label): continue
                if re.search(r"agree|accept|certify|confirm|j.accepte|terms|conditions|privacy|consent|akkoord", label):
                    cb.check(force=True); n += 1
            except Exception: continue
        return n
