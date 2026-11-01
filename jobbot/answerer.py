"""Best-effort answers for form questions the profile rules do not cover — built from YOUR CV, your profile and your earlier answers.

Used when you do not answer within the waiting time (default 30 s) or when a run is unattended. Principles:
  * HONEST — experience / skill / certificate / degree questions are answered "yes" only if the CV contains evidence; otherwise "no" / "0".
  * WILLINGNESS questions (relocate, travel, background check, start immediately, hybrid …) are answered "yes".
  * SENSITIVE questions (disability, gender, ethnicity, religion, criminal record, health, birth date, nationality, bank …) are NEVER guessed:
    the "prefer not to say" option is chosen if it exists, otherwise the question is left for you.
  * Every guess is stored as «auto» (orange in the right-hand list) so you can review / correct it; a correction replaces it.
"""
import re, collections, unicodedata
from . import store

SENSITIVE = re.compile(r"disab|handicap|gender|\bsexe\b|ethnic|\brace\b|racial|veteran|religio|criminal|convict|casier|pregnan|\bhealth|santé|sexual|orientation|marital|"
                       r"date of birth|birth ?date|\bborn\b|date de naissance|nationalit|citizenship|passport|social security|\bssn\b|national (id|number)|\bbsn\b|\biban\b|bank|"
                       r"\bage\b|how old|salary history|current salary|vaccin|drug|alcohol|mental", re.I)
DECLINE_OPT = re.compile(r"prefer not|rather not|decline|ne souhaite pas|préfère ne pas|liever niet|do not wish|don.t wish", re.I)
PLACEHOLDER = re.compile(r"^(select|choisir|sélection|kies|please select|--|—|\s*$)", re.I)
YES = ("yes", "oui", "ja", "si", "sí"); NO = ("no", "non", "nee")

WILLING = re.compile(r"relocat|déménag|verhuizen|willing|ready to|prepared to|open to|comfortable|able to (travel|work|commute|start|relocate)|can you (travel|commute|start|work on|work in)|"
                     r"travel|commut|overtime|weekend|on-?site|hybrid|in-?office|work from (the )?office|background check|reference check|screening|"
                     r"start (immediately|asap)|immediately available|notice|full[- ]time|part[- ]time|shift|night|on[- ]call|"
                     r"agree|consent|acknowledge|confirm that you|certify|understand that|accept", re.I)
CONFLICT = re.compile(r"non-?compete|conflict of interest|relative|family member|currently employed by|worked for us|previously (worked|employed)|already (applied|work)|former employee", re.I)
EXPERIENCE = re.compile(r"experience|proficien|skilled|familiar|knowledge|certif|degree|diploma|licen[cs]e|fluent|fluency|speak|background|trained|worked with|used|manage|lead|"
                        r"expérience|maîtris|connaissance|diplôme|ervaring|beheers|kennis|bachelor|master|years|expertise|hands-on|qualified", re.I)
OPEN_TEXT = re.compile(r"why|describe|tell us|tell me|about yourself|motivation|summary|introduce|cover|pitch|achievement|strength|pourquoi|décrivez|présentez|waarom|beschrijf|vertel", re.I)
HEAR = re.compile(r"how did you (hear|find)|where did you (hear|find)|comment avez-vous connu|hoe heb je ons gevonden|source", re.I)
YEARS_Q = re.compile(r"how many years|years of|number of years|années d|nombre d.années|jaren|ans d.expérience|experience.*\byears?\b", re.I)

STOP = set("""a an the and or of to in on at for with by from as is are be do does did have has had you your yours we our us they their it its this that these those
any ever currently please can could will would should must may might not no yes if when what which who whom whose how why where there here than then also more most
very much many some such into over under about up down out off per via using use used work working worked knowledge skills skill proficient proficiency familiar
experience experiences years year level levels strong good great excellent professional position role job company team within able ability related relevant
le la les un une des du de et ou en dans sur pour avec par vous votre vos nous notre est sont avez avoir être au aux ce cet cette ces que qui quoi comment
een het de en of van voor met op bij je jij uw wij ons is zijn heb heeft hebt""".split())
GENERIC_OK = {"linkedin": ("linkedin", "linked in"), "indeed": ("indeed",)}


class Auto(str):
    """An answer the bot chose itself (user did not answer in time) — stored with the «auto» mark."""


def _norm(s):
    s = unicodedata.normalize("NFKD", (s or "").lower()); return "".join(c for c in s if not unicodedata.combining(c))


def tokens(text, min_len=3):
    return [t for t in re.findall(r"[a-z0-9+#.]+", _norm(text)) if len(t) >= min_len and t not in STOP]


def _yn(options, want):
    grp = YES if want == "yes" else NO
    for o in options or []:
        if _norm(o).strip().startswith(grp): return o
    return want if not options else None


class Answerer:
    def __init__(self, profile, cv_texts=None, learned=None):
        self.p = profile
        self.cv = _norm(" \n ".join(cv_texts or []))
        self.cv_tokens = set(re.findall(r"[a-z0-9+#.]+", self.cv))
        self.learned = learned or {}
        years = [int(y) for y in re.findall(r"(\d{1,2})\s*\+?\s*(?:years|ans|jaar)", self.cv)]
        self.total_years = profile.get("years_experience_total") or (sorted(years)[len(years) // 2] if years else 0)

    # ------------------------------------------------------------------ evidence
    def has(self, word):
        w = _norm(word)
        if w in self.cv_tokens: return True
        if len(w) >= 5: return any(t.startswith(w[:5]) for t in self.cv_tokens) and w[:5] in self.cv           # stems: manage/management
        return bool(w) and (" " + w) in (" " + self.cv)

    def evidence(self, label):
        toks = tokens(label)
        found = [t for t in toks if self.has(t)]
        return found, [t for t in toks if t not in found]

    def years_for(self, label):
        for sk, y in (self.p.get("years_by_skill") or {}).items():
            if _norm(sk) in _norm(label): return str(y)
        found, missing = self.evidence(label)
        subject = [t for t in tokens(label) if t not in ("many",)]
        for t in found:
            m = re.search(re.escape(t) + r".{0,80}?(\d{1,2})\s*\+?\s*(?:years|ans|jaar)|(\d{1,2})\s*\+?\s*(?:years|ans|jaar).{0,80}?" + re.escape(t), self.cv, re.S)
            if m: return str(next(g for g in m.groups() if g))
        floor = 2 if self.p.get("default_answers", True) else 0            # default policy: at least 2 years when the CV is silent
        if subject and not found: return str(floor)
        return str(max(floor, self.total_years or 0))

    # ------------------------------------------------------------------ learned answers
    def learned_match(self, label):
        """Closest earlier answer (same question worded differently)."""
        a = set(tokens(label))
        if len(a) < 2: return None
        best, score = None, 0.0
        for q, ans in self.learned.items():
            b = set(tokens(q))
            if not b: continue
            j = len(a & b) / len(a | b)
            if j > score: best, score = ans, j
        return best if score >= 0.75 else None

    # ------------------------------------------------------------------ main entry
    def suggest(self, label, kind="text", options=None, ctx=None):
        """-> (answer or None, reason). Falls back to the DEFAULT POLICY (yes / 2 years / 1 month / conventional) so the bot rarely skips a job."""
        if self.p.get("default_answers", True) and not SENSITIVE.search(label) and self.learned_match(label) is None \
                and re.search(r"notice|préavis|opzeg|salary|salaire|loon|compensation|remuneration|rémunération", _norm(label)):
            d = self.default(label, kind, [o for o in (options or [])], ctx or {})
            if d: return d
        ans, why = self._suggest(label, kind, options, ctx)
        if ans in (None, "") and self.p.get("default_answers", True):
            d = self.default(label, kind, options or [], ctx or {})
            if d: return d
        return ans, why

    def default(self, label, kind, options, ctx):
        """Never for sensitive questions. Otherwise: yes · at least 2 years · notice 1 month · salary 'conventional' · first usable option."""
        if SENSITIVE.search(label): return None
        l = _norm(label); opts = [o for o in options if not PLACEHOLDER.search(o)]
        why = "default policy"
        if re.search(r"notice|préavis|opzeg|available|availability|disponib|start date|date de début|when can you start", l):
            for o in opts:
                if re.search(r"1 month|one month|30 days|4 weeks|un mois|1 mois|maand", _norm(o)): return o, why + ": 1 month notice"
            return (opts[0] if opts else "1 month"), why + ": 1 month notice"
        if re.search(r"salary|salaire|loon|compensation|rémunération|remuneration|prétention|pretention|expected pay", l):
            for o in opts:
                if re.search(r"convention|negotia|négoci|grid|scale|barème", _norm(o)): return o, why + ": conventional salary"
            return (opts[0] if opts else "Conventional"), why + ": conventional salary"
        if YEARS_Q.search(label) and not opts: return "2", why + ": 2 years minimum"
        if opts:
            for o in opts:
                if _norm(o).strip().startswith(YES): return o, why + ": yes"
            return opts[0], why + ": first option"
        if kind == "textarea" or OPEN_TEXT.search(label): return self.open_text(label, ctx)
        if re.search(r"number|nombre|aantal|how many|combien|hoeveel", l): return "2", why + ": 2"
        return "Yes", why + ": yes"

    def _suggest(self, label, kind="text", options=None, ctx=None):
        """-> (answer or None, reason). `kind`: text | textarea | select | radio."""
        ctx = ctx or {}; options = [o for o in (options or []) if not PLACEHOLDER.search(o)]
        l = _norm(label)
        if SENSITIVE.search(label):
            for o in options:
                if DECLINE_OPT.search(o): return o, "sensitive question → 'prefer not to say'"
            return None, "sensitive question: never auto-answered"
        m = self.learned_match(label)
        if m is not None and (not options or any(_norm(o) == _norm(str(m)) for o in options)): return str(m), "similar earlier answer"
        if HEAR.search(label):
            for o in options:
                if "linkedin" in _norm(o): return o, "source = LinkedIn"
            if not options: return "LinkedIn", "source = LinkedIn"
        if YEARS_Q.search(label) and not options: return self.years_for(label), "years from the CV"
        yn_options = options and all(_norm(o).strip().startswith(YES + NO) or len(o) < 12 for o in options) and any(_norm(o).strip().startswith(YES + NO) for o in options)
        is_yn = bool(yn_options) or (not options and re.match(r"\s*(do|does|did|are|is|have|has|can|will|would|could|were|was|est-ce|avez|êtes|etes|pouvez|heb|ben|kan|wil)\b", l))
        if is_yn:
            ans, why = self.yes_no(label, ctx)
            if ans is None: return None, why
            return (_yn(options, ans) if options else ans), why
        if options: return self.choose(label, options, ctx)
        if kind == "textarea" or OPEN_TEXT.search(label): return self.open_text(label, ctx)
        if re.search(r"salary|salaire|loon|compensation", l): return str(self.p.get("salary_year_eur") or ""), "profile salary" if self.p.get("salary_year_eur") else None
        return None, "no basis for an answer"

    # ------------------------------------------------------------------ yes / no
    def yes_no(self, label, ctx):
        l = _norm(label)
        for lang, lvl in (self.p.get("languages") or {}).items():
            if lang in l and re.search(r"speak|parl|spreek|fluent|proficien|communicat|write|read", l): return "yes", f"profile language: {lang}"
        if CONFLICT.search(label):
            co = _norm(ctx.get("company", ""))
            if re.search(r"worked|employed|already|former|currently employed", l) and co: return ("yes" if self.has(co) else "no"), "company check against the CV"
            return "no", "no conflict declared"
        if EXPERIENCE.search(label) and not re.search(r"willing|ready|open to", l):
            found, missing = self.evidence(label)
            if not tokens(label): return None, "no subject"
            if found and len(found) >= max(1, (len(found) + len(missing) + 1) // 2): return "yes", "CV mentions: " + ", ".join(found[:4])
            if self.p.get("default_answers", True): return "yes", "default yes (nothing in the CV either way): " + ", ".join(missing[:4])
            return "no", "no evidence in the CV for: " + ", ".join(missing[:4])
        if WILLING.search(label): return "yes", "willingness question"
        found, missing = self.evidence(label)
        if found and not missing: return "yes", "CV mentions: " + ", ".join(found[:4])
        if self.p.get("default_answers", True): return "yes", "default yes"
        return None, "yes/no without a safe basis"

    # ------------------------------------------------------------------ multiple choice
    def choose(self, label, options, ctx):
        l = _norm(label)
        if re.search(r"education|degree|diploma|niveau d.étude|studies|opleiding", l):
            edu = _norm(self.p.get("education", ""))
            for o in options:
                if edu and any(w in _norm(o) for w in re.findall(r"[a-z]{4,}", edu)): return o, "profile education"
        if re.search(r"notice|préavis|opzeg|available|start|disponib", l):
            pri = [(i, o) for i, o in enumerate(options) if re.search(r"immediate|asap|now|0\b|1 week|une semaine|direct|meteen", _norm(o))]
            if pri: return pri[0][1], "shortest notice"
        scored = []
        for o in options:
            ot = tokens(o)
            ev = sum(1 for t in ot if self.has(t))
            scored.append((ev, len(ot), o))
        scored.sort(key=lambda x: (-x[0], x[1]))
        if scored and scored[0][0] > 0 and (len(scored) == 1 or scored[0][0] > scored[1][0]): return scored[0][2], "option found in the CV"
        for lang, lvl in (self.p.get("languages") or {}).items():
            if lang in l:
                for o in options:
                    if _norm(lvl) in _norm(o): return o, f"profile level for {lang}"
        return None, "no option supported by the CV"

    # ------------------------------------------------------------------ open text
    def open_text(self, label, ctx):
        skills = [k for k in self._skills()[:5]]
        yrs = self.total_years
        head = self.p.get("headline") or "professional"
        co, title = ctx.get("company") or "your company", ctx.get("title") or "this position"
        parts = [f"I am a {head}" + (f" with {yrs} years of experience" if yrs else "") + (f" in {', '.join(skills)}" if skills else "") + "."]
        if re.search(r"why|pourquoi|waarom|motivation", _norm(label)): parts.append(f"I am motivated to join {co} as {title}: the role matches my background and I can contribute quickly.")
        else: parts.append(f"I would be glad to contribute to {co} as {title} and to discuss the details in an interview.")
        return " ".join(parts), "composed from the CV"

    def _skills(self):
        from .cv_analyzer import SKILLS
        found = collections.Counter()
        for kws in SKILLS.values():
            for k in kws:
                n = self.cv.count(k)
                if n and len(k) > 3: found[k.strip()] += n
        return [k for k, _ in found.most_common()]


def build(profile, criteria=None):
    """Answerer for the current profile: CV texts are read once (all CV files) + learned answers."""
    from .cv_analyzer import read_text
    texts = []
    for path in (profile.get("cv_files") or {}).values():
        try:
            if path: texts.append(read_text(path))
        except Exception: pass
    return Answerer(profile, texts, store.load_answers())
