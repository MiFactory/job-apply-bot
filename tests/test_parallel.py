"""Several applications at the same time («parallel_applications»): scheduler unit tests + end-to-end runs against the LOCAL fake LinkedIn
of test_e2e (nothing is sent to linkedin.com).
Run:  python -m unittest tests.test_parallel -v      (needs: pip install playwright && playwright install chromium)"""
import sys, time, pathlib, unittest, subprocess
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from jobbot import profile as P, store, browser as B, parallel
from jobbot.runner import last_result
import tests.test_e2e as T          # (module import: importing the E2E class itself would make unittest run its tests twice)
from tests.test_unit import TmpData


class FakePage:
    """Just enough of a Playwright page for the scheduler."""
    def __init__(self, ctx=None): self.context = ctx or FakeCtx(); self.closed = False; self.fronts = 0
    def wait_for_timeout(self, ms): time.sleep(ms / 1000)
    def bring_to_front(self): self.fronts += 1
    def close(self): self.closed = True
class FakeCtx:
    def __init__(self): self.pages = []
    def new_page(self): p = FakePage(self); self.pages.append(p); return p


class TestScheduler(unittest.TestCase):
    def setUp(self): B.HOOKS.update(stop=False, result="", log=print, pause=None); parallel.WAIT_CAP_MS = None
    def tearDown(self): B.HOOKS.update(stop=False)

    def test_clamp(self):
        for v, want in [(1, 1), (5, 5), (10, 10), (11, 10), (999, 10), (0, 1), (-3, 1), ("4", 4), ("x", 1), (None, 1), ([], 1), (2.9, 2), (True, 1)]:
            self.assertEqual(parallel.clamp(v), want, v)
        self.assertEqual(P.DEFAULT_CRITERIA["parallel_applications"], 1, "one by one must stay the default")

    def test_pauses_overlap_and_every_tab_gets_its_result(self):
        order = []
        def task(pg, job, tab):
            for step in range(3): order.append((job, step)); yield 200
            return job * 10
        main = FakePage(); t = time.monotonic()
        res = parallel.run_tasks(main, [1, 2, 3, 4, 5], task); took = time.monotonic() - t
        self.assertEqual(sorted(res), [(j, j * 10) for j in (1, 2, 3, 4, 5)])
        self.assertLess(took, 1.5, "5 tabs x 3 pauses of 0.2 s must overlap (3 s if done one after the other)")
        self.assertEqual(order[:5], [(j, 0) for j in (1, 2, 3, 4, 5)], "every tab starts before any tab does its 2nd step")
        self.assertTrue(all(p.closed for p in main.context.pages)); self.assertEqual(len(main.context.pages), 5)
        self.assertTrue(all(p.fronts == 4 for p in main.context.pages), "a tab is brought to the front each time it gets its turn")

    def test_crash_in_one_tab_does_not_stop_the_others(self):
        def task(pg, job, tab):
            yield 10
            if job == 2: raise ValueError("boom")
            yield 10; return "ok"
        res = dict(parallel.run_tasks(FakePage(), [1, 2, 3], task))
        self.assertEqual((res[1], res[3]), ("ok", "ok")); self.assertIsInstance(res[2], ValueError)

    def test_fatal_result_and_stop_abort_the_other_tabs_and_clean_them(self):
        cleaned = []
        def task(pg, job, tab):
            yield 10
            if job == 1: return "LIMIT"
            yield 5000; return "late"
        main = FakePage(); t = time.monotonic()
        res = dict(parallel.run_tasks(main, [1, 2, 3], task, on_abort=cleaned.append, is_fatal=lambda r: r == "LIMIT"))
        self.assertLess(time.monotonic() - t, 2); self.assertEqual(res, {1: "LIMIT", 2: None, 3: None}); self.assertEqual(len(cleaned), 2)
        self.assertTrue(all(p.closed for p in main.context.pages))
        def stopper(pg, job, tab):
            yield 10; B.HOOKS["stop"] = True; yield 5000; return "late"
        res = dict(parallel.run_tasks(FakePage(), [1, 2], stopper)); self.assertEqual(res, {1: None, 2: None})

    def test_drive_runs_a_task_alone(self):
        def task():
            yield 5; yield 5; return ("APPLIED", "")
        self.assertEqual(parallel.drive(FakePage(), task()), ("APPLIED", ""))


class TestCli(unittest.TestCase):
    def test_parallel_option_is_validated(self):
        run = lambda *a: subprocess.run([sys.executable, "main.py", *a], cwd=ROOT, capture_output=True, text=True, timeout=60, encoding="utf-8")
        for bad in ("0", "11", "many"):
            r = run("run", "--parallel", bad); self.assertNotEqual(r.returncode, 0, bad); self.assertIn("--parallel", r.stderr); self.assertNotIn("Traceback", r.stderr)
        r = run("run", "--help"); self.assertIn("--parallel", r.stdout); r = run("schedule", "--help"); self.assertIn("--parallel", r.stdout)


class ParallelE2E(T.E2E):
    """Same fake LinkedIn as E2E, with several tabs."""
    def setUp(self):
        super().setUp(); parallel.WAIT_CAP_MS = 120; self.crit["parallel_applications"] = 3; self.max_tabs = 1
        def log(m): self.logs.append(m); self.max_tabs = max(self.max_tabs, len(self.ctx.pages))
        B.HOOKS["log"] = log
    def tearDown(self): parallel.WAIT_CAP_MS = None; super().tearDown()
    def status_by_job(self): return {r["job_id"]: (r["status"], r["note"]) for r in self.rows()}
    def only_main_tab_left(self): self.assertEqual(len(self.ctx.pages), 1, "the job tabs must be closed after the batch"); self.assertFalse(self.page.is_closed())

    def test_search_run_same_results_as_one_by_one(self):
        store.log_application("linkedin", "1006", "Sales Executive", "Zeta", "Liège", "u", "APPLIED")
        n = self.run_bot(); st = self.status_by_job()
        self.assertEqual(st["1001"][0], "APPLIED", self.logs); self.assertEqual(st["1005"][0], "APPLIED", self.logs)
        self.assertEqual(st["1002"][0], "SKIPPED"); self.assertIn("excluded", st["1002"][1]); self.assertEqual(st["1003"][0], "SKIPPED"); self.assertIn("location", st["1003"][1])
        self.assertEqual(st["1004"][0], "NEEDS_INFO"); self.assertIn("unicorn", st["1004"][1].lower()); self.assertTrue("unicorn" in store.PENDING.read_text(encoding="utf-8").lower())
        self.assertEqual(sum(1 for r in self.rows() if r["job_id"] == "1006"), 1, "an already-applied job was processed again")
        self.assertEqual(len(self.rows()), 6, "each job is logged exactly once")
        self.assertEqual(n, 2); self.assertEqual(last_result(), "finished"); self.assertEqual(sorted(s["job"] for s in self.subs), ["1001", "1005"])
        self.assertEqual(self.max_tabs, 4, "3 job tabs + the search tab were open together"); self.only_main_tab_left()
        self.assertTrue(any("Parallel mode" in str(m) for m in self.logs)); self.assertTrue(any(str(m).startswith("[tab ") for m in self.logs))
        self.assertEqual(self.run_bot(), 0, "second run: everything is already handled"); self.assertEqual(len(self.subs), 2)

    def test_one_means_one_by_one_and_garbage_is_one(self):
        for v in (1, "banana", 0, None):
            self.setUp_again(); self.crit["parallel_applications"] = v
            self.assertEqual(self.run_bot(), 3); self.assertEqual(self.max_tabs, 1, f"parallel_applications={v!r} must not open extra tabs")
            self.assertFalse(any("Parallel mode" in str(m) for m in self.logs))
    def setUp_again(self): self.tearDown(); self.setUp()

    def test_ten_tabs_and_more_than_ten_is_capped(self):
        self.crit["parallel_applications"] = 50
        self.assertEqual(self.run_bot(), 3); self.assertEqual(self.max_tabs, 7, "6 offers on the page: 6 tabs + the search tab (cap 10 not reached)"); self.only_main_tab_left()
        self.assertTrue(any("up to 10 applications" in str(m) for m in self.logs))

    def test_dry_run_never_submits(self):
        n = self.run_bot(dry=True); self.assertEqual(n, 3); self.assertEqual(self.subs, []); st = self.status_by_job()
        self.assertEqual((st["1001"][0], st["1005"][0]), ("DRY_RUN", "DRY_RUN")); self.only_main_tab_left()
        self.assertEqual(self.run_bot(), 3, "a real run applies to what the dry run only looked at"); self.assertEqual(sorted(x["job"] for x in self.subs), ["1001", "1005", "1006"])

    def test_run_cap_and_daily_cap_are_never_exceeded(self):
        self.crit["parallel_applications"] = 10
        self.assertEqual(self.run_bot(max_apps=1), 1); self.assertEqual(len(self.subs), 1); self.assertEqual(self.max_tabs, 2, "1 application left = 1 tab")
        self.setUp_again(); self.crit.update(parallel_applications=10, max_applications_per_day=1, exclude=[], location_must_contain=[])     # 5 offers would pass
        self.assertEqual(self.run_bot(), 1); self.assertEqual(len(self.subs), 1); self.assertEqual(last_result(), "quota")
        self.assertEqual(self.run_bot(), 0); self.assertEqual(len(self.subs), 1); self.assertEqual(last_result(), "quota")

    def test_linkedin_limit_stops_all_tabs_and_jobs_stay_retryable(self):
        self.fake.mode = "limit"; n = self.run_bot(); self.assertEqual(n, 0); self.assertEqual(last_result(), "limit"); self.assertEqual(self.subs, [])
        self.assertFalse([r for r in self.rows() if r["status"] in ("APPLIED", "LIMIT")]); self.assertNotIn(("linkedin", "1001"), store.seen_jobs()); self.only_main_tab_left()
        self.fake.mode = "ok"; self.assertEqual(self.run_bot(), 3)

    def test_stop_button_closes_the_tabs(self):
        def log(m):
            self.logs.append(m)
            if "at the same time (" in str(m): B.HOOKS["stop"] = True
        B.HOOKS["log"] = log; n = self.run_bot(); self.assertEqual(n, 0); self.assertEqual(last_result(), "stopped"); self.assertEqual(self.subs, []); self.only_main_tab_left()
        self.assertEqual(self.rows(), [], "a stopped tab logs nothing: its job is tried again next run")

    def test_security_check_in_the_tabs_asks_the_user_once(self):
        calls = []; B.HOOKS["pause"] = lambda m: (calls.append(m), setattr(self.fake, "checkpoint", False))
        self.crit.update(saved_jobs="only", timeout_seconds=3, include_drafts=False); self.fake.saved_ids = ["1001", "1005", "1006"]; self.fake.checkpoint = True      # the Saved list loads, the job pages show the check
        n = self.run_bot(); self.assertEqual(len(calls), 1, "one pause for all the tabs"); self.assertEqual(n, 3, self.logs); self.assertEqual(len(self.subs), 3); self.only_main_tab_left()

    def test_security_check_never_solved_ends_cleanly(self):
        calls = []; B.HOOKS["pause"] = calls.append; self.crit.update(saved_jobs="only", timeout_seconds=2, include_drafts=False); self.fake.saved_ids = ["1001", "1005"]; self.fake.checkpoint = True
        n = self.run_bot(); self.assertEqual(n, 0); self.assertEqual(self.subs, []); self.assertEqual(self.rows(), []); self.assertEqual(len(calls), 1, "no pause loop"); self.only_main_tab_left()
        self.assertTrue(any("left for the next run" in str(m) for m in self.logs))

    def test_saved_jobs_in_parallel(self):
        self.crit.update(saved_jobs="only", timeout_seconds=3, unsave_after_apply=True); store.log_application("linkedin", "1006", "Sales Executive", "Zeta", "Liège", "u", "APPLIED")
        n = self.run_bot(); st = self.status_by_job()
        for jid in ("1001", "1002", "1003"): self.assertEqual(st[jid], ("APPLIED", "saved job"), (jid, st.get(jid), self.logs))     # search filters must NOT apply to saved jobs
        self.assertEqual(st["1004"][0], "NEEDS_INFO"); self.assertEqual(st["1007"][0], "SKIPPED"); self.assertIn("no longer accepting", st["1007"][1])
        self.assertEqual(st["1009"][0], "SKIPPED"); self.assertIn("not Easy Apply", st["1009"][1]); self.assertEqual(n, 3); self.assertEqual(last_result(), "finished")
        self.assertEqual(sum(1 for r in self.rows() if r["job_id"] == "1006"), 1); self.assertFalse([h for h in self.fake.hits if h.startswith("/jobs/search")])
        self.assertEqual(sorted(self.unsaves), ["1001", "1002", "1003"]); self.only_main_tab_left()
        self.assertEqual(self.run_bot(), 0, "applied / closed / external saved jobs are not reopened"); self.assertEqual(len(self.subs), 3)

    def test_unknown_question_is_asked_and_the_answer_reused_by_the_other_tabs(self):
        asked = []
        def asker(label, options, ctx): asked.append(label); return "No"
        old = set(T.UNKNOWN_Q_JOBS); T.UNKNOWN_Q_JOBS.update({"1001", "1005"})
        try: n = self.run_bot(interactive=True, asker=asker)
        finally: T.UNKNOWN_Q_JOBS.clear(); T.UNKNOWN_Q_JOBS.update(old)
        self.assertEqual(n, 4, self.logs); self.assertEqual(len(asked), 1, "asked once, then reused in the other tabs"); self.assertIn("unicorn", asked[0].lower())


for _n in dir(T.E2E):                      # ParallelE2E reuses E2E's fake site and helpers, not its one-by-one tests
    if _n.startswith("test_"): setattr(ParallelE2E, _n, None)

try:
    import tests.test_gui as G; HAVE_QT = G.HAVE_QT
except Exception:
    HAVE_QT = False

if HAVE_QT:
    class ParallelGui(G.GuiTests):
        def test_parallel_setting_saved_loaded_and_clamped(self):
            from jobbot import profiles
            w = self.w; self.assertEqual(w.par.value(), 1); self.assertEqual((w.par.minimum(), w.par.maximum()), (1, 10)); self.assertIn("one by one", w.par.text())
            w.par.setValue(6); w.save_search(); self.assertEqual(P.load_criteria()["parallel_applications"], 6)
            profiles.create("Solo"); w.switch_profile("Solo"); self.assertEqual(w.par.value(), 1); w.switch_profile("default"); self.assertEqual(w.par.value(), 6)
            w.crit["parallel_applications"] = "garbage"; self.assertEqual(w._par_value(), 1); w.crit["parallel_applications"] = 99; self.assertEqual(w._par_value(), 10)
    for _n in dir(G.GuiTests):
        if _n.startswith("test_"): setattr(ParallelGui, _n, None)


if __name__ == "__main__":
    unittest.main()
