"""CV-based answers, auto-answer marks, retry rules for dry-run / needs-info jobs."""
import sys, pathlib, unittest, random, string
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from tests.test_unit import TmpData
from jobbot import store, profile as P
from jobbot.answerer import Answerer, Auto
from jobbot.formfiller import Filler, NeedInfo

CV = ["Business developer, B2B sales, Salesforce CRM, 6 years of experience. Python basics. English, French, Dutch. Bachelor in Management."]
PROF = {"languages": {"english": "C1", "french": "native"}, "headline": "Business Developer", "years_experience_total": 6, "years_by_skill": {}}


class TestAnswerer(unittest.TestCase):
    def setUp(self): self.a = Answerer({**PROF, "default_answers": False}, CV, {})   # strict/honest mode; default policy tested in test_labels
    def s(self, q, kind="text", o=None): return self.a.suggest(q, kind, o, {"company": "Acme", "title": "BD"})[0]

    def test_honest_experience(self):
        self.assertEqual(self.s("Do you have experience with Salesforce?"), "yes")
        self.assertEqual(self.s("Do you have experience with SAP?"), "no")
        self.assertEqual(self.s("How many years of experience with SAP?"), "0")

    def test_willingness_yes(self):
        for q in ("Are you willing to relocate?", "Are you comfortable commuting to Brussels?", "Can you start immediately?"):
            self.assertEqual(self.s(q).lower(), "yes", q)

    def test_sensitive_never_guessed(self):
        for q in ("What is your gender?", "Do you have a criminal record?", "What is your date of birth?", "What is your nationality?", "Do you have a disability?"):
            self.assertIsNone(self.s(q), q)
        self.assertEqual(self.s("Do you have a disability?", "select", ["Yes", "No", "Prefer not to say"]), "Prefer not to say")

    def test_options_respected(self):
        self.assertEqual(self.s("Are you willing to relocate?", "radio", ["Oui", "Non"]) if False else self.s("Do you speak French?", "radio", ["Yes", "No"]), "Yes")
        self.assertEqual(self.s("How did you hear about us?", "select", ["Indeed", "LinkedIn", "Other"]), "LinkedIn")

    def test_learned_similar(self):
        a = Answerer(PROF, CV, {"expected start date weeks": "2"})
        self.assertEqual(a.suggest("Expected start date weeks", "text", None, {})[0], "2")

    def test_open_text_uses_cv(self):
        t = self.s("Why do you want to work here?", "textarea")
        self.assertIn("6 years", t); self.assertIn("Acme", t)

    def test_fuzz_never_crashes(self):
        rnd = random.Random(7)
        for _ in range(400):
            q = "".join(rnd.choice(string.ascii_letters + " ?éà/-0123456789") for _ in range(rnd.randint(0, 120)))
            opts = rnd.choice([None, [], ["Yes", "No"], ["Select an option", "A", "B"]])
            r = self.a.suggest(q, rnd.choice(["text", "textarea", "select", "radio"]), opts, {})
            self.assertEqual(len(r), 2)


class TestRetryRules(TmpData):
    def test_dry_run_and_error_are_retried(self):
        store.log_application("linkedin", "1", "t", "c", "l", "u", "DRY_RUN", "x"); store.log_application("linkedin", "2", "t", "c", "l", "u", "ERROR", "x")
        store.log_application("linkedin", "3", "t", "c", "l", "u", "APPLIED", ""); store.log_application("linkedin", "4", "t", "c", "l", "u", "SKIPPED", "low score")
        self.assertEqual(store.seen_jobs(), {("linkedin", "3"), ("linkedin", "4")})

    def test_needs_info_retried_once_answered(self):
        store.log_application("linkedin", "5", "t", "c", "l", "u", "NEEDS_INFO", "Shoe size?")
        self.assertIn(("linkedin", "5"), store.seen_jobs())
        store.save_answer("Shoe size?", "42"); self.assertNotIn(("linkedin", "5"), store.seen_jobs())

    def test_auto_mark_and_manual_override(self):
        store.save_answer("Q one", "yes", auto=True); self.assertIn(store.norm("Q one"), store.load_auto())
        store.save_answer("Q one", "no"); self.assertNotIn(store.norm("Q one"), store.load_auto()); self.assertEqual(store.load_answers()[store.norm("Q one")], "no")


class TestFillerAuto(TmpData):
    def mk(self, asker=None, **c):
        pr = dict(P.load_profile(), **PROF); crit = dict(P.load_criteria(), **c)
        f = Filler(pr, crit, interactive=False, asker=asker); f._answerer = Answerer(pr, CV, {}); f.ctx = {"title": "BD", "company": "Acme", "lang": "en"}
        return f

    def test_unattended_auto_answers_and_marks(self):
        v = self.mk().resolve("Do you have experience with Salesforce?")
        self.assertEqual(v, "yes"); self.assertIn(store.norm("Do you have experience with Salesforce?"), store.load_auto())

    def test_sensitive_unattended_needs_info(self):
        with self.assertRaises(NeedInfo): self.mk().resolve("What is your gender?")

    def test_auto_off(self):
        with self.assertRaises(NeedInfo): self.mk(auto_answer=False).resolve("Do you have experience with Salesforce?")

    def test_asker_timeout_returns_auto(self):
        seen = {}
        def asker(label, opts, ctx): seen.update(ctx); return Auto(ctx["suggest"])
        self.assertEqual(self.mk(asker).resolve("Do you have experience with Salesforce?"), "yes")
        self.assertEqual(seen["suggest"], "yes"); self.assertEqual(seen["wait"], 30)
        self.assertIn(store.norm("Do you have experience with Salesforce?"), store.load_auto())

    def test_user_answer_wins_and_unmarked(self):
        self.assertEqual(self.mk(lambda l, o, c: "maybe").resolve("Do you have experience with Salesforce?"), "maybe")
        self.assertNotIn(store.norm("Do you have experience with Salesforce?"), store.load_auto())

    def test_skip_raises(self):
        with self.assertRaises(NeedInfo): self.mk(lambda l, o, c: None).resolve("Do you have experience with Salesforce?")


if __name__ == "__main__": unittest.main()
