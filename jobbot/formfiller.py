"""Generic form filler: maps field labels → profile values → remembered answers → ask the user."""
import re
from . import store
from .answerer import Auto

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
     (r"^(your |votre |uw |contact )?(primary )?e-?mail( address| adres)?[\s\*\?:]*$|e-?mail address|adresse e-?mail|e-?mailadres", p["email"]),
     (r"country code|indicatif|code pays|landcode", p["phone_country_code"]),
     (r"phone|mobile (phone )?number|^mobile$|téléphone|telefoon|\bgsm\b", ph),
     (r"postal|\bzip\b|code postal|postcode", p["postal_code"]),
     (r"^(current )?(city|ville|stad|town)\b.{0,25}$|location \(city\)|^city\b", p["city"]),
     (r"linkedin", p["linkedin_url"]),
     (r"website|portfolio|site web", p["website"] or p["linkedin_url"]),
     (r"^headline|^titre\b|professional headline", p["headline"]),
     (r"notice period|notice|préavis|opzegtermijn|disponibilit|availability|available (from|as of|starting)|earliest start|start date|date de début|when can you start", p["notice_period"]),
     (r"salary.*(month|mois|maand)|(month|mois|maand).*salary|salaire.*mensuel|maandloon|maandsalaris|bruto ?maand", (str(p["salary_month_eur"]) if p["salary_month_eur"] else None)),
     (r"salary|salaire|\bloon\b|jaarloon|jaarsalaris|salaris|rémunération|compensation|expected (annual|yearly|gross|base|pay)", (str(p["salary_year_eur"]) if p["salary_year_eur"] else None)),
     (r"sponsor", "no" if not p["needs_sponsorship"] else "yes"),
     (r"authori[sz]ed|legally|right to work|work permit|permis de travail|autorisé|eligible to work", "yes" if p["authorized_to_work"] else "no"),
     (r"relocat|déménag|verhuizen", "yes" if p["willing_relocate"] else "no"),
     (r"driv(er|ing).{0,20}licen|licen.{0,20}driv|permis de conduire|rijbewijs", "yes" if p["driving_licence"] else "no"),
     (r"\bdegree\b|diploma|diplôme|\bbachelor|\bmaster.s\b|education level|niveau d.étude", "yes"),
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

LEVELS = [   # language / skill levels in EN-FR-NL, best match first
    ("native", r"native|natif|bilingu|mother|maternelle|moedertaal"),
    ("fluent", r"fluent|courant|full professional|professionnel|professional|vloeiend|advanced|avanc"),
    ("professional", r"professional|professionnel|working|vloeiend|intermediate|interm|goed"),
    ("conversational", r"conversation|limited|limit|basic|élémentaire|elementary|beginner|débutant|gesprek|basis"),
    ("none", r"inexistant|none|aucun|no proficiency|geen"),
]

def pick_level(options, w):
    keys = [k for k, _ in LEVELS]
    for i, (key, rx) in enumerate(LEVELS):
        if key in w or (key == "fluent" and re.search(r"courant|vloeiend", w)):
            for j in sorted(range(len(LEVELS)), key=lambda j: (abs(j - i), j)):   # the level itself, then the nearest ones
                if keys[j] == "none" and keys[i] != "none": continue
                for o in options:
                    if re.search(LEVELS[j][1], o.lower()): return o
            return None
    return None

def pick_option(options, wanted: str):
    w = (wanted or "").lower()
    if re.search(r"native|fluent|professional|conversation|basic|none|natif|courant|professionnel|bilingu", w):
        o = pick_level(options, w)
        if o: return o
    if w in ("yes", "no"):
        group = YES if w == "yes" else NO
        for o in options:
            if o.lower().strip().startswith(group):
                return o
    for o in options:
        if w and (w in o.lower() or o.lower() in w):
            return o
    return None

OPT_JS = """el => {            // text of ONE radio option: label[for], wrapping label, or the text next to the input (new form: <div><input><label for></div><div><p>Yes</p></div>)
  const t = x => (x && x.innerText || '').trim();
  let s = el.id ? t(document.querySelector('label[for="' + CSS.escape(el.id) + '"]')) : '';
  if (!s) s = t(el.closest('label'));
  if (!s && el.parentElement) s = t(el.parentElement.nextElementSibling);
  if (!s && el.nextElementSibling) s = t(el.nextElementSibling);
  if (!s && el.parentElement && el.parentElement.parentElement) s = t(el.parentElement.parentElement);
  return s.replace(/\\s+/g, ' ').trim();
}"""

LABEL_JS = """el => {
  const t = x => (x && x.innerText || '').trim();
  let s = '';
  if (el.id) { const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); s = t(l); }
  if (!s) { const lb = el.getAttribute('aria-labelledby'); if (lb) s = lb.split(' ').map(i => t(document.getElementById(i))).join(' ').trim(); }
  if (!s) s = el.getAttribute('aria-label') || '';
  if (!s) { const w = el.closest('label'); if (w) s = t(w); }
  if (!s) { const fs = el.closest('fieldset'); if (fs) s = t(fs.querySelector('legend')) || t(fs.querySelector('span')); }
  if (!s) { const g = el.closest('[data-test-form-element], .fb-dash-form-element, .jobs-easy-apply-form-section__grouping, div'); s = g ? (g.innerText || '').split('\\n')[0] : ''; }
  if (!s) s = el.placeholder || el.name || '';
  return s.replace(/\\s+/g, ' ').trim();
}"""

GROUP_JS = """el => {
  const t = x => (x && x.innerText || '').trim();
  let s = '';
  const al = (el.getAttribute('aria-label') || '').trim();
  if (al.length >= 8) return al.replace(/\\s+/g, ' ').replace(/\\s*\\*$/, '');          // new LinkedIn form: the question is the aria-label of every radio
  const fs = el.closest('fieldset, [role=radiogroup], [role=group]');
  if (fs) { s = t(fs.querySelector('legend')) || t(fs.querySelector('[data-test-form-builder-radio-button-form-component__title], span, label')); 
            const lb = fs.getAttribute('aria-labelledby'); if (!s && lb) s = lb.split(' ').map(i => t(document.getElementById(i))).join(' '); }
  if (!s) {      // no fieldset (new LinkedIn form): climb to the nearest block that holds text other than the options, take the line just before the first option
    const grp = [...document.querySelectorAll('input[type=radio]')].filter(r => r.name === el.name);
    const opts = new Set(['yes', 'no', 'oui', 'non', 'ja', 'nee']);
    grp.forEach(r => { const l = r.id && document.querySelector('label[for="' + CSS.escape(r.id) + '"]'); if (l) opts.add(t(l).toLowerCase()); });
    let e = el.closest('div');
    while (e && e.tagName !== 'DIALOG' && e.tagName !== 'BODY') {
      const lines = (e.innerText || '').split('\\n').map(x => x.trim()).filter(Boolean);
      const fi = lines.findIndex(l => opts.has(l.toLowerCase()));
      const before = (fi > 0 ? lines.slice(0, fi) : lines.filter(l => !opts.has(l.toLowerCase()))).filter(l => !opts.has(l.toLowerCase()));
      if (before.length) { s = fi > 0 ? before[before.length - 1] : before[0]; break; }
      e = e.parentElement;
    }
  }
  return s.replace(/\\s+/g, ' ').replace(/\\s*\\*$/, '').trim();
}"""

def clean_label(l: str) -> str:
    l = re.sub(r"\s+", " ", l or "").strip()
    h = len(l) // 2
    if len(l) > 6 and l[:h].strip() == l[h:].strip(): l = l[:h].strip()        # "X X" -> "X"
    words = l.split(" ")
    if len(words) > 3 and len(words) % 2 == 0 and words[:len(words)//2] == words[len(words)//2:]: l = " ".join(words[:len(words)//2])
    return l

FILE_LIKE = re.compile(r"\.(pdf|docx?|odt|rtf)\b|\b\d+([.,]\d+)?\s*(ko|mo|kb|mb)\b|derni[eè]re utilisation|last used|import[ée]+ le|uploaded on", re.I)
COVER = re.compile(r"cover letter|motivation|lettre de motivation|motivatiebrief|message to (the )?(hiring|recruiter)|why (do you want|are you interested)|pourquoi", re.I)

_Q = None
def timed_input(prompt, seconds=0):
    """input() with a time limit (None on timeout; 0 = wait forever). One reader thread is reused, so a late line is not lost."""
    global _Q
    import threading, queue, sys
    if not seconds: return input(prompt).strip()
    if _Q is None:
        _Q = queue.Queue()
        def reader():
            while True:
                try: _Q.put(sys.stdin.readline())
                except Exception: _Q.put(""); return
        threading.Thread(target=reader, daemon=True).start()
    print(prompt, end="", flush=True)
    try:
        line = _Q.get(timeout=seconds)
        return line.strip() if line else None
    except queue.Empty:
        print(); return None


class Filler:
    def __init__(self, profile, criteria, interactive=True, asker=None, motivation=None):
        self.p, self.c, self.interactive, self.asker = profile, criteria, interactive, asker
        self.motivation = motivation or {}      # {"en": "...", "fr": "..."}  with {company} {title}
        self.ctx = {"title": "", "company": "", "lang": "en"}
        self.answers = store.load_answers()
        self._answerer = None

    def resolve(self, label, kind="text", options=None):
        label = clean_label(label)
        if COVER.search(label) and (self.motivation.get(self.ctx["lang"]) or self.motivation.get("default")):
            t = self.motivation.get(self.ctx["lang"]) or self.motivation.get("default")
            return t.replace("{full_name}", (self.p["first_name"] + " " + self.p["last_name"]).strip()).replace("{company}", self.ctx["company"] or "your company").replace("{title}", self.ctx["title"] or "this position")
        a = answer_for(label, self.p, kind)
        if a is None:
            a = self.answers.get(store.norm(label)) or store.load_answers().get(store.norm(label))
        if a is not None: return a
        sug, why = self.suggest(label, kind, options)            # best guess from the CV / profile / earlier answers (or None)
        if self.asker:
            ctx = dict(self.ctx, suggest=sug or "", why=why, wait=self.wait_seconds() if sug else 0)
            a = self.asker(label, options or [], ctx)           # GUI: waits for you; after the delay it returns Auto(suggestion)
        elif self.c.get("ask_user_when_unknown") and self.interactive:
            a = self.ask_cli(label, options, sug, why)
        else:
            a = Auto(sug) if sug else None                       # unattended run
        if a and not self.c.get("auto_answer", True) and isinstance(a, Auto): a = None
        if not a: raise NeedInfo(label)                         # "Skip this job": never type "None" into the form
        store.save_answer(label, str(a), auto=isinstance(a, Auto))
        return a

    def fallback_option(self, label, kind, options):
        """The profile answer matched no option: use the CV guess / default policy instead of skipping the job."""
        sug, why = self.suggest(label, kind, options)
        o = pick_option(options, sug) if sug else None
        if o:
            store.save_answer(label, str(o), auto=True)
        return o

    # ---- CV-based guess + waiting time
    def wait_seconds(self):
        try: return max(0, int(self.c.get("answer_timeout_seconds", 30)))
        except Exception: return 30

    def suggest(self, label, kind="text", options=None):
        if not self.c.get("auto_answer", True): return None, "auto-answer off"
        try:
            if self._answerer is None:
                from . import answerer; self._answerer = answerer.build(self.p)
            self._answerer.learned = {k: v for k, v in store.load_answers().items() if k not in store.load_auto()}
            s, why = self._answerer.suggest(label, kind, options, self.ctx)
            return (str(s) if s not in (None, "") else None), why
        except Exception as e:
            return None, f"answerer error: {type(e).__name__}"

    def ask_cli(self, label, options, sug, why):
        print(f"\n❓ Question in the form: {label}" + (f"\n   options: {options}" if options else ""))
        w = self.wait_seconds() if sug else 0
        if sug: print(f"   suggestion: {sug}  ({why}) — used automatically after {w}s" if w else f"   suggestion: {sug}  ({why}) — Enter accepts it")
        a = timed_input("   Your answer (empty = " + ("accept suggestion" if sug else "skip this job") + "): ", w if sug else 0)
        if a is None or (a == "" and sug): return Auto(sug) if sug else None
        return a or None

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
                o = pick_option(opts, want) or self.fallback_option(label, "select", opts)
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
                    try: lab = g.evaluate(OPT_JS)
                    except Exception: lab = ""
                    labs.append(lab)
                want = self.resolve(label, "radio", labs)
                o = pick_option(labs, want) or self.fallback_option(label, "radio", labs)
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
