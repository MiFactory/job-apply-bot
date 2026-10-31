"""Fast unit + robustness tests (no browser).  Run:  python -m unittest tests.test_unit -v"""
import sys, os, json, csv, random, string, pathlib, tempfile, unittest, datetime as dt, threading
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from jobbot import profile as P, store, scheduler as S, formfiller as F, cv_analyzer, profiles, linkedin

PROF = {**P.DEFAULT_PROFILE, "first_name": "Alex", "last_name": "Martin", "email": "alex@example.com", "phone": "+32400000000",
        "phone_national": "400000000", "city": "Brussels", "postal_code": "1000", "salary_year_eur": 48000, "salary_month_eur": 4000,
        "years_experience_total": 3, "years_by_skill": {"python": 2}, "languages": {"english": "Professional", "french": "Native"}}
CRIT = {**P.DEFAULT_CRITERIA, "titles": ["Account Manager"]}


class TmpData(unittest.TestCase):
    """Every test works in a throw-away data folder, never the real one."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.d = pathlib.Path(self.tmp.name)
        self._old = (store.APPS, store.ANSWERS, store.PENDING, P.PROFILE, P.CRITERIA, profiles.DATA, profiles.PROFILES, profiles.ACTIVE, profiles._active)
        profiles.DATA = self.d; profiles.PROFILES = self.d / "profiles"; profiles.ACTIVE = self.d / "active_profile.txt"; profiles._active = None
        P.PROFILE, P.CRITERIA = self.d / "profile.json", self.d / "criteria.json"; store.set_dir(self.d)
    def tearDown(self):
        (store.APPS, store.ANSWERS, store.PENDING, P.PROFILE, P.CRITERIA, profiles.DATA, profiles.PROFILES, profiles.ACTIVE, profiles._active) = self._old
        self.tmp.cleanup()


class TestProfileAndScoring(TmpData):
    def test_defaults_when_missing(self):
        self.assertEqual(P.load_profile()["country"], "Belgium"); self.assertEqual(P.load_criteria()["max_applications_per_day"], 40)

    def test_corrupt_or_wrong_json_never_crashes(self):
        for bad in ["", "{", "not json", "[]", "null", "42", '"str"', "\ufeff{}", "{\"first_name\": 5", "\x00\x01"]:
            with self.subTest(bad=bad):
                P.PROFILE.write_text(bad, encoding="utf-8")
                self.assertIn("first_name", P.load_profile())

    def test_utf8_bom_json(self):
        P.PROFILE.write_bytes(b"\xef\xbb\xbf" + json.dumps({"first_name": "Zoë"}).encode()); self.assertEqual(P.load_profile()["first_name"], "Zoë")

    def test_language_detection(self):
        cases = {"en": "We are looking for an experienced account manager to join our team and you will work with our customers",
                 "fr": "Nous recherchons un responsable commercial pour rejoindre notre équipe et vous travaillerez avec nos clients",
                 "nl": "Wij zoeken een ervaren accountmanager voor ons team en je werkt met de klanten van het bedrijf",
                 "de": "Wir suchen einen erfahrenen Vertriebsleiter für unser Team und Sie arbeiten mit unseren Kunden",
                 "es": "Buscamos un gerente de cuentas con experiencia para nuestro equipo y usted trabajará con los clientes"}
        for k, t in cases.items(): self.assertEqual(P.detect_lang(t), k, k)
        for weird in ["", " ", "12345 !!!", "日本語のテキスト", "a" * 100000, "\x00" * 50]: self.assertIn(P.detect_lang(weird), ("en", "fr", "nl", "es", "de"))

    def test_score_job(self):
        c = {**P.DEFAULT_CRITERIA, "titles": ["Account Manager"]}
        self.assertEqual(P.score_job("Junior Account Manager", "x", c)[0], 0)
        self.assertEqual(P.score_job("Stage commercial", "x", c)[0], 0)
        self.assertGreater(P.score_job("Senior Account Manager", "great job", c)[0], 0)
        self.assertEqual(P.score_job("Internal Sales", "x", c)[0], 1 if "intern" not in "internal sales".split() else 0)  # 'intern' is a whole-word match only
        c2 = {**c, "must_have_any": ["python"]}
        self.assertEqual(P.score_job("Dev", "java only", c2)[0], 0); self.assertGreater(P.score_job("Dev", "uses Python", c2)[0], 0)
        c3 = {**c, "title_must_match_any": ["sales"]}; self.assertEqual(P.score_job("Dev", "", c3)[0], 0)
        self.assertEqual(P.score_job("Account Manager", "Wij zoeken een ervaren verkoper voor ons team en je werkt met de klanten van het bedrijf in een leuke omgeving " * 5, c)[0], 0)  # Dutch-only ad skipped
        for t, d in [("", ""), ("\x00", "\x00"), ("é" * 5000, "x" * 100000), ("(((", "[[[")]: P.score_job(t, d, c)   # no crash / no regex injection

    def test_regex_special_chars_in_exclude(self):
        c = {**P.DEFAULT_CRITERIA, "exclude": ["c++", "(", "[x"], "titles": []}
        self.assertGreater(P.score_job("C++ developer", "", c)[0] + 1, 0)   # must not raise re.error

    def test_location_ok(self):
        c = P.DEFAULT_CRITERIA
        for ok in ["Brussels, Brussels Region, Belgium", "Nivelles, Wallonia", "Bruxelles", "Wavre, Belgique"]: self.assertTrue(P.location_ok(ok, c), ok)
        for bad in ["Paris, France", "Casablanca, Morocco", ""]: self.assertFalse(P.location_ok(bad, c), bad)
        self.assertTrue(P.location_ok("Anywhere", {"location_must_contain": []}))


class TestStore(TmpData):
    def test_csv_semicolon_roundtrip_nasty_values(self):
        nasty = ['A;B', 'He said "hi"', 'line1\nline2', 'é à ü ñ 日本', '=SUM(A1)', '', ' spaces ']
        for i, t in enumerate(nasty): store.log_application("linkedin", str(i), t, "Co;mpany", "Loc", "http://x", "APPLIED", t)
        rows = list(csv.DictReader(open(store.APPS, encoding="utf-8-sig"), delimiter=";"))
        self.assertEqual([r["title"] for r in rows], nasty); self.assertEqual(len(rows), len(nasty))
        self.assertIn(("linkedin", "3"), store.seen_jobs())
        head = open(store.APPS, encoding="utf-8-sig").readline(); self.assertEqual(head.count(";"), 8)

    def test_count_today(self):
        for st in ("APPLIED", "APPLIED", "SKIPPED", "DRY_RUN"): store.log_application("linkedin", st + str(random.random()), "t", "c", "l", "u", st)
        self.assertEqual(store.count_today(), 2); self.assertEqual(store.count_today("SKIPPED"), 1)

    def test_empty_and_missing_files(self):
        self.assertEqual(store.seen_jobs(), set()); self.assertEqual(store.count_today(), 0); self.assertEqual(store.load_answers(), {})

    def test_answers_normalised_and_utf8(self):
        store.save_answer("Do you have a Driver's Licence?", "yes"); store.save_answer("Prénom préféré ?", "Zoë")
        a = store.load_answers(); self.assertEqual(a[store.norm("do you have a drivers licence")], "yes"); self.assertEqual(len(a), 2)

    def test_concurrent_writes_do_not_lose_rows(self):
        def w(k):
            for i in range(25): store.log_application("linkedin", f"{k}-{i}", "t", "c", "l", "u", "APPLIED")
        ts = [threading.Thread(target=w, args=(k,)) for k in range(4)]; [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual(len(store.seen_jobs()), 100)

    def test_corrupt_answers_file(self):
        store.ANSWERS.write_text("{broken", encoding="utf-8")
        try: store.load_answers()
        except Exception as e: self.fail(f"corrupt answers.json crashes the app: {e!r}")


class TestAnswerEngine(unittest.TestCase):
    def test_known_labels(self):
        exp = {"First name": "Alex", "Last name": "Martin", "Email address": "alex@example.com", "Mobile phone number": "400000000", "City": "Brussels",
               "Postal code": "1000", "Phone country code": "+32", "What is your expected annual salary?": "48000", "Expected monthly salary": "4000",
               "How many years of experience do you have with Python?": "2", "How many years of work experience do you have?": "3",
               "Are you legally authorized to work in Belgium?": "yes", "Will you now or in the future require sponsorship?": "no",
               "What is your level of English proficiency?": "Professional", "Niveau de français": "Native",
               "Email *": "alex@example.com", "E-mail": "alex@example.com", "Votre adresse e-mail": "alex@example.com", "Contact email": "alex@example.com", "Email address*": "alex@example.com",
               "Téléphone portable": "400000000", "Phone": "400000000", "Code postal": "1000", "Ville": "Brussels", "Voornaam": "Alex", "Achternaam": "Martin",
               "Prénom": "Alex", "Nom de famille": "Martin", "Salaire annuel souhaité": "48000", "Gewenst jaarloon": "48000", "Zip code": "1000",
               "Combien d'années d'expérience avez-vous ?": "3", "Do you have a valid driver's licence?": "yes", "Are you willing to relocate?": "yes",
               "Do you have a Bachelor's degree?": "yes", "What is your notice period?": "Immediate", "When can you start?": "Immediate", "Availability": "Immediate"}
        for lab, want in exp.items(): self.assertEqual(F.answer_for(lab, PROF), want, lab)

    def test_unknown_questions_are_not_guessed(self):
        """A wrong auto-answer is worse than asking: these must return None (→ asked / pending)."""
        unknown = ["Do you have a pet unicorn?", "Do you understand our remote policy?", "Are you available to work on weekends?",
                   "Have you ever worked for a competitor?", "Describe your biggest failure", "Favourite colour?", "Are you a balloon artist?",
                   "Do you have experience with email marketing?", "Do you have mobile app experience?", "Are you comfortable working in a city office?",
                   "Do you have a master data management background?", "Are you a self-driven person?", "Do you have a zipper factory background?",
                   "What is your favourite programming language?", "Are you willing to undergo a background check?", "Do you require a visa?"]
        for lab in unknown: self.assertIsNone(F.answer_for(lab, PROF), f"auto-answered a question it should not: {lab!r} -> {F.answer_for(lab, PROF)!r}")

    def test_fuzz_never_crashes(self):
        rnd = random.Random(7); alphabet = string.printable + "éàüñ日本語\u200b\x00"
        for _ in range(3000):
            lab = "".join(rnd.choice(alphabet) for _ in range(rnd.randint(0, 200)))
            F.answer_for(lab, PROF); F.clean_label(lab)
        for lab in ["(" * 50, "[[[[", "\\", "*" * 1000, "a" * 100000]: F.answer_for(lab, PROF); F.clean_label(lab)

    def test_profile_with_missing_optional_keys(self):
        p = dict(P.DEFAULT_PROFILE); F.answer_for("How many years of experience with Java?", p); F.answer_for("English level", p)

    def test_clean_label(self):
        self.assertEqual(F.clean_label("First name First name"), "First name"); self.assertEqual(F.clean_label("  a \n b "), "a b"); self.assertEqual(F.clean_label(None), "")

    def test_pick_option(self):
        self.assertEqual(F.pick_option(["Select an option", "Yes", "No"], "no"), "No"); self.assertEqual(F.pick_option(["Oui", "Non"], "yes"), "Oui")
        self.assertEqual(F.pick_option(["Professional", "Native"], "Professional"), "Professional"); self.assertIsNone(F.pick_option(["A", "B"], "zzz")); self.assertIsNone(F.pick_option([], "yes"))


class TestLimitDetection(unittest.TestCase):
    def test_real_limit_messages_detected(self):
        for m in ["You've reached the daily Easy Apply limit", "You have reached the Easy Apply limit for today. Come back tomorrow.", "Daily limit reached",
                  "Vous avez atteint la limite quotidienne de candidatures simplifiées", "Limite de candidatures atteinte", "Je hebt de dagelijkse limiet bereikt"]:
            self.assertTrue(linkedin.LIMIT_RE.search(m), m)

    def test_normal_text_not_flagged(self):
        """False positives would stop the whole run (and start a pointless retry cycle)."""
        for m in ["Contact info Email address Phone country code Mobile phone number", "Upload resume. Maximum file size 2 MB",
                  "Unlimited holidays and a limited number of seats in our office", "Easy Apply Apply to Acme Corp", "We offer too many perks to list here",
                  "Resume Be sure to include an updated resume. DOC, DOCX, PDF (2 MB max)", "Limited time offer: our team is growing"]:
            self.assertFalse(linkedin.LIMIT_RE.search(m), f"false positive: {m!r}")


class TestScheduler(TmpData):
    def sched(self, **kw): return {**S.DEFAULT_SCHEDULE, "enabled": True, **kw}

    def test_parse_days(self):
        self.assertEqual(S.parse_days("mon-fri"), [0, 1, 2, 3, 4]); self.assertEqual(S.parse_days("Mon, Wed ,fri"), [0, 2, 4]); self.assertEqual(S.parse_days("all"), list(range(7)))
        self.assertEqual(S.parse_days("sat-mon"), [0, 5, 6]); self.assertEqual(S.parse_days("monday,tuesday"), [0, 1]); self.assertEqual(S.parse_days(""), [])
        for bad in ["xyz", "mon-", "foo-bar"]:
            with self.assertRaises(ValueError, msg=bad): S.parse_days(bad)

    def test_next_start(self):
        s = self.sched(days=[0], time="09:00")
        self.assertEqual(S.next_start(s, dt.datetime(2026, 10, 31, 12, 0)), dt.datetime(2026, 11, 2, 9, 0))             # Sat → Mon
        self.assertEqual(S.next_start(s, dt.datetime(2026, 11, 2, 8, 59, 59)), dt.datetime(2026, 11, 2, 9, 0))          # same day, before
        self.assertEqual(S.next_start(s, dt.datetime(2026, 11, 2, 9, 0)), dt.datetime(2026, 11, 9, 9, 0))               # exactly at: next week
        self.assertIsNone(S.next_start(self.sched(days=[])))
        self.assertEqual(S.next_start(self.sched(days=list(range(7)), time="00:00"), dt.datetime(2026, 12, 31, 23, 59)), dt.datetime(2027, 1, 1, 0, 0))   # year rollover
        self.assertEqual(S.next_start(self.sched(days=[6], time="23:59"), dt.datetime(2028, 2, 27, 23, 59, 1)), dt.datetime(2028, 3, 5, 23, 59))

    def test_bad_time_values_handled(self):
        for t in ["25:99", "9", "", "ab:cd", "09:00:00", None, "9:5"]:
            try: S.next_start(self.sched(days=[0], time=t))
            except Exception as e: self.fail(f"time {t!r} crashes: {e!r}")

    def test_limit_retry_cycle(self):
        t0 = dt.datetime(2026, 11, 2, 9, 0); sc = S.Scheduler(self.sched(days=[0], time="09:00"), dt.datetime(2026, 11, 2, 8, 0))
        self.assertFalse(sc.due(dt.datetime(2026, 11, 2, 8, 59))); self.assertTrue(sc.due(t0))
        sc.on_result("limit", t0); self.assertEqual(sc.state, "retry"); self.assertFalse(sc.due(t0 + dt.timedelta(minutes=4, seconds=59))); self.assertTrue(sc.due(t0 + dt.timedelta(minutes=5)))
        for k in range(1, 30): sc.on_result("limit", t0 + dt.timedelta(minutes=5 * k)); self.assertEqual(sc.state, "retry")
        sc.on_result("finished", t0 + dt.timedelta(minutes=150)); self.assertEqual(sc.state, "idle"); self.assertEqual(sc.next_at, dt.datetime(2026, 11, 9, 9, 0))

    def test_retry_gives_up_and_other_results(self):
        t0 = dt.datetime(2026, 11, 2, 9, 0); sc = S.Scheduler(self.sched(days=list(range(7)), retry_max_hours=2), t0 - dt.timedelta(hours=1))
        sc.on_result("limit", t0); sc.on_result("limit", t0 + dt.timedelta(hours=3)); self.assertEqual(sc.state, "idle"); self.assertEqual(sc.next_at, dt.datetime(2026, 11, 3, 9, 0))
        sc.on_result("limit", t0 + dt.timedelta(days=1)); sc.on_result("stopped", t0 + dt.timedelta(days=1, minutes=1)); self.assertEqual(sc.state, "idle"); self.assertFalse(sc.due(t0 + dt.timedelta(days=1, minutes=30)))
        sc.on_result("quota", t0 + dt.timedelta(days=1, hours=1)); self.assertEqual(sc.state, "idle")

    def test_disabled_never_due(self):
        sc = S.Scheduler({**S.DEFAULT_SCHEDULE, "enabled": False}); self.assertFalse(sc.due(dt.datetime.now() + dt.timedelta(days=30))); sc.on_result("limit"); self.assertFalse(sc.due()); self.assertEqual(sc.status(), "Schedule off")

    def test_retry_minutes_zero_or_garbage(self):
        sc = S.Scheduler(self.sched(days=[0], retry_minutes=0)); sc.on_result("limit"); self.assertGreaterEqual((sc.retry_at - dt.datetime.now()).total_seconds(), 50)

    def test_schedule_file_corrupt_and_roundtrip(self):
        P.PROFILE = self.d / "profile.json"; S.path().write_text("{oops", encoding="utf-8"); self.assertEqual(S.load()["time"], "09:00")
        s = self.sched(days=[1, 3], time="07:15"); S.save(s); self.assertEqual(S.load()["days"], [1, 3]); S.path().write_text("[1,2]", encoding="utf-8"); self.assertEqual(S.load()["time"], "09:00")

    def test_status_strings(self):
        sc = S.Scheduler(self.sched(days=[])); self.assertEqual(sc.status(), "No day selected")


class TestProfiles(TmpData):
    def test_create_activate_delete(self):
        n = profiles.create("Alex"); profiles.activate(n); self.assertEqual(profiles.active(), "Alex"); self.assertTrue((profiles.PROFILES / "Alex" / "profile.json").exists())
        self.assertEqual(store.APPS.parent.name, "Alex"); profiles.create("Bob", copy_from="Alex"); self.assertEqual(profiles.list_profiles(), ["Alex", "Bob"])
        profiles.delete("Bob"); self.assertEqual(profiles.list_profiles(), ["Alex"])

    def test_hostile_names_cannot_escape(self):
        for name in ["../../evil", "..\\..\\evil", "/etc/passwd", "C:\\Windows", "a/b", "", "   ", "😀", "x" * 500, "con", "."]:
            n = profiles.create(name); p = (profiles.PROFILES / n).resolve()
            self.assertTrue(str(p).startswith(str(profiles.PROFILES.resolve())), f"{name!r} -> {p}"); self.assertTrue(n)

    def test_activate_unknown_and_empty(self):
        self.assertTrue(profiles.activate("")); self.assertTrue(profiles.activate("ghost")); self.assertEqual(profiles.active(), "default")

    def test_migration_from_single_profile_layout(self):
        (self.d / "profile.json").write_text(json.dumps({"first_name": "Zoë"}), encoding="utf-8"); (self.d / "applications.csv").write_text("a;b\n", encoding="utf-8")
        profiles.migrate(); self.assertEqual(profiles.list_profiles(), ["Zoë"]); self.assertTrue((profiles.PROFILES / "Zoë" / "applications.csv").exists()); self.assertFalse((self.d / "profile.json").exists())
        profiles.migrate(); self.assertEqual(profiles.list_profiles(), ["Zoë"])    # idempotent

    def test_migration_with_corrupt_profile(self):
        (self.d / "profile.json").write_text("{bad", encoding="utf-8"); profiles.migrate(); self.assertEqual(profiles.list_profiles(), ["default"])

    def test_active_profile_file_garbage(self):
        profiles.create("A"); profiles.ACTIVE.write_text("nonexistent", encoding="utf-8"); self.assertEqual(profiles.active(), "A")


class TestCvAnalyzer(TmpData):
    def test_text_cv(self):
        f = self.d / "cv.txt"; f.write_text("Jane Doe\njane.doe@example.com  +32 470 12 34 56\nSenior Account Manager, 8 years experience. B2B sales, Salesforce, negotiation.\nLanguages: English, French, Dutch", encoding="utf-8")
        i = cv_analyzer.analyze(f); self.assertEqual(i["email"], "jane.doe@example.com"); self.assertTrue(i["suggested_titles"]); self.assertIn("english", [x.lower() for x in i["languages"]])

    def test_empty_binary_and_missing(self):
        e = self.d / "e.txt"; e.write_text("", encoding="utf-8"); cv_analyzer.analyze(e)
        b = self.d / "b.txt"; b.write_bytes(os.urandom(5000)); cv_analyzer.analyze(b)
        with self.assertRaises(Exception): cv_analyzer.analyze(self.d / "nope.pdf")


if __name__ == "__main__":
    unittest.main(verbosity=2)
