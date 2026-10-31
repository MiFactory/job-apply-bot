"""CLI tests: argument errors are friendly (no tracebacks), setup/report work, and the headless `schedule` loop behaves.
Run:  python -m unittest tests.test_cli -v"""
import sys, os, shutil, subprocess, pathlib, tempfile, unittest, io, contextlib, json, types
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class CliProcess(unittest.TestCase):
    """Runs main.py in a throw-away COPY of the project so the real data folder is never touched."""
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(); cls.dir = pathlib.Path(cls.tmp.name) / "app"
        shutil.copytree(ROOT, cls.dir, ignore=shutil.ignore_patterns(".git", "data", "__pycache__", "*.pyc"))
    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()
    def run_cli(self, *args, stdin=""):
        return subprocess.run([sys.executable, "main.py", *args], cwd=self.dir, input=stdin, capture_output=True, text=True, timeout=60, encoding="utf-8")

    def test_help_and_syntax(self):
        r = self.run_cli("--help"); self.assertEqual(r.returncode, 0); self.assertIn("schedule", r.stdout)
        for f in list(ROOT.glob("*.py")) + list(ROOT.glob("jobbot/*.py")) + list(ROOT.glob("tests/*.py")): compile(f.read_text(encoding="utf-8"), str(f), "exec")

    def test_bad_arguments_are_friendly(self):
        for args, msg in [(("schedule", "--days", "xyz"), "Invalid --days"), (("schedule", "--time", "25:99"), "Invalid --time"), (("schedule", "--time", "abc"), "Invalid --time"),
                          (("schedule", "--days", "mon-"), "Invalid --days")]:
            r = self.run_cli(*args); self.assertNotEqual(r.returncode, 0); self.assertIn(msg, r.stderr + r.stdout, args); self.assertNotIn("Traceback", r.stderr, args)
        r = self.run_cli("run"); self.assertIn("No job titles", r.stderr + r.stdout); self.assertNotIn("Traceback", r.stderr)
        r = self.run_cli("bogus"); self.assertNotEqual(r.returncode, 0)

    def test_report_with_nothing_and_setup_roundtrip(self):
        r = self.run_cli("report"); self.assertEqual(r.returncode, 0); self.assertIn("No applications", r.stdout)
        cv = self.dir / "cv.txt"; cv.write_text("Jane Doe\njane.doe@example.com +32 470 12 34 56\nSenior Account Manager, 8 years experience. B2B sales, Salesforce.\nEnglish, French", encoding="utf-8")
        r = self.run_cli("setup", "--cv", str(cv), stdin="\n" * 40); self.assertEqual(r.returncode, 0, r.stderr[-500:]); self.assertNotIn("Traceback", r.stderr)
        prof = next((self.dir / "data" / "profiles").glob("*/profile.json")); d = json.loads(prof.read_text(encoding="utf-8")); self.assertEqual(d["email"], "jane.doe@example.com")
        crit = json.loads(next((self.dir / "data" / "profiles").glob("*/criteria.json")).read_text(encoding="utf-8")); self.assertTrue(crit["titles"])
        r = self.run_cli("setup", "--cv", str(self.dir / "missing.pdf"), stdin="\n" * 40); self.assertNotEqual(r.returncode, 0)

    def test_schedule_cli_saves_settings_then_needs_titles(self):
        with tempfile.TemporaryDirectory() as t:
            fresh = pathlib.Path(t) / "app"; shutil.copytree(ROOT, fresh, ignore=shutil.ignore_patterns(".git", "data", "__pycache__", "*.pyc"))
            r = subprocess.run([sys.executable, "main.py", "schedule", "--days", "mon,wed", "--time", "7:30"], cwd=fresh, capture_output=True, text=True, timeout=60)
            self.assertIn("No job titles", r.stderr + r.stdout); self.assertNotIn("Traceback", r.stderr)


class ScheduleLoop(unittest.TestCase):
    def test_loop_runs_then_waits_after_limit(self):
        import main, time
        from jobbot import profile as P, browser as B, runner, scheduler as S, profiles
        tmp = tempfile.TemporaryDirectory(); d = pathlib.Path(tmp.name)
        old = (P.PROFILE, P.CRITERIA, runner.run_jobs, B.Browser, time.sleep)
        try:
            P.PROFILE, P.CRITERIA = d / "profile.json", d / "criteria.json"; P.save(P.CRITERIA, {**P.DEFAULT_CRITERIA, "titles": ["x"], "sites": ["linkedin"]})
            calls = []
            def fake_run(*a, **k): calls.append(1); B.HOOKS["result"] = "limit"; return 0
            class FakeBrowser:
                def __enter__(s): s.page = object(); return s
                def __exit__(s, *a): pass
                def live_page(s): return s.page
            n = {"k": 0}
            def fake_sleep(sec):
                n["k"] += 1
                if n["k"] >= 3: raise KeyboardInterrupt
            runner.run_jobs = fake_run; B.Browser = FakeBrowser; time.sleep = fake_sleep
            import jobbot.browser as JB; JB.Browser = FakeBrowser
            a = types.SimpleNamespace(days="all", time="09:00", retry=5, max=3, now=True)
            out = io.StringIO()
            with contextlib.redirect_stdout(out): main.cmd_schedule(a)
            text = out.getvalue(); self.assertEqual(len(calls), 1, text); self.assertIn("result: limit", text); self.assertIn("testing again", text); self.assertIn("bye", text)
            self.assertTrue(S.load()["enabled"]); self.assertEqual(S.load()["retry_minutes"], 5)
        finally:
            P.PROFILE, P.CRITERIA, runner.run_jobs, B.Browser, time.sleep = old; tmp.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=2)
