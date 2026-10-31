"""GUI smoke / behaviour tests, headless (QT_QPA_PLATFORM=offscreen). No browser is started.
Run:  python -m unittest tests.test_gui -v      (needs PySide6)"""
import os, sys, json, queue, threading, pathlib, unittest, datetime as dt
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTime, Qt
    HAVE_QT = True
except Exception:
    HAVE_QT = False
from jobbot import profile as P, store, scheduler as S, profiles, browser as B
from tests.test_unit import TmpData, PROF


class FakeThread:
    def __init__(self, alive=True): self.q = queue.Queue(); self.alive = alive
    def is_alive(self): return self.alive
    def join(self, t=None): pass


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class GuiTests(TmpData):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        import gui; self.gui = gui
        self.w = gui.Window(); self.w.open_browser = lambda: None; self.w.bthread = FakeThread()
        B.HOOKS.update(stop=False, result="", log=print, pause=None)
    def tearDown(self):
        self.w.sch_timer.stop(); self.w.dock_timer.stop(); self.w.close(); super().tearDown()

    def test_window_builds_and_has_all_controls(self):
        w = self.w; from jobbot import __version__; from PySide6.QtWidgets import QLabel
        self.assertIn(__version__, w.windowTitle()); self.assertTrue(any("mifactory.ma" in l.text() for l in w.statusBar().findChildren(QLabel)), "creator credit missing from the window"); self.assertTrue(callable(w.about))
        for n in ("start_b", "stop_b", "sch_on", "sch_time", "sch_retry", "sch_lbl", "table", "logw", "pcombo", "embed_cb", "zs", "ps", "tl", "tr"): self.assertTrue(hasattr(w, n), n)
        self.assertEqual(len(w.sch_days), 7)

    def test_side_panels_zoom_and_slider_do_not_crash(self):
        w = self.w; w.tl.setChecked(False); w.tr.setChecked(False); self.assertTrue(w.left.isHidden() and w.right.isHidden()); w.tl.setChecked(True); w.tr.setChecked(True)
        for d in (+10, -10, +500, -500, 0): w.zoom(d)
        for v in (0, 50, 100): w.ps.setValue(v)

    def test_schedule_persists_per_profile(self):
        w = self.w; w.sch_on.setChecked(True)
        for i, c in enumerate(w.sch_days): c.setChecked(i in (1, 3))
        w.sch_time.setTime(QTime(7, 45)); w.sch_retry.setValue(7)
        d = S.load(); self.assertEqual((d["enabled"], d["days"], d["time"], d["retry_minutes"]), (True, [1, 3], "07:45", 7)); self.assertIn("Next run", w.sch_lbl.text())
        # other profile has its own (default) schedule
        profiles.create("Other"); w.switch_profile("Other"); self.assertFalse(w.sch_on.isChecked()); self.assertEqual([c.isChecked() for c in w.sch_days][:5], [True] * 5)
        w.switch_profile("default"); self.assertTrue(w.sch_on.isChecked()); self.assertEqual(w.sch_time.time().toString("HH:mm"), "07:45")

    def test_no_day_selected_status(self):
        w = self.w; w.sch_on.setChecked(True)
        for c in w.sch_days: c.setChecked(False)
        self.assertIn("No day", w.sch_lbl.text())

    def _arm(self):
        w = self.w; w.titles.setPlainText("Account Manager"); w.save_search(); w.prof["cv_files"]["en"] = str(self.d / "cv.pdf"); w.sch_on.setChecked(True)
        for c in w.sch_days: c.setChecked(True)
        w.sched.next_at = dt.datetime.now() - dt.timedelta(seconds=5); return w

    def test_scheduled_start_queues_unattended_run(self):
        w = self._arm(); w.sch_tick(); cmd = w.bthread.q.get_nowait()
        self.assertEqual(cmd[0], "run"); self.assertTrue(cmd[-1], "scheduled runs must be flagged unattended"); self.assertFalse(w.start_b.isEnabled()); self.assertTrue(w.stop_b.isEnabled())
        w.sch_tick(); self.assertTrue(w.bthread.q.empty(), "must not start a second run while one is running")

    def test_manual_start_is_interactive(self):
        w = self._arm(); w.start(); cmd = w.bthread.q.get_nowait(); self.assertFalse(cmd[-1])

    def test_limit_result_arms_retry_then_resume(self):
        w = self._arm(); w.sch_tick(); w.bthread.q.get_nowait(); B.HOOKS["result"] = "limit"; w.on_finished(0)
        self.assertEqual(w.sched.state, "retry"); self.assertTrue(w.start_b.isEnabled()); self.assertIn("LinkedIn limit", w.sch_lbl.text())
        w.sch_tick(); self.assertTrue(w.bthread.q.empty(), "too early to retry")
        w.sched.retry_at = dt.datetime.now() - dt.timedelta(seconds=1); w.sch_tick(); self.assertEqual(w.bthread.q.get_nowait()[0], "run")
        B.HOOKS["result"] = ""; w.on_finished(3); self.assertEqual(w.sched.state, "idle")

    def test_scheduled_run_waits_when_browser_closed_and_logs_once(self):
        w = self._arm(); w.bthread = FakeThread(alive=False); w.sch_tick(); w.sch_tick(); w.sch_tick()
        self.assertEqual(w.logw.toPlainText().count("browser is closed"), 1); self.assertTrue(w.start_b.isEnabled())
        w.bthread = FakeThread(); w.sch_tick(); self.assertFalse(w.bthread.q.empty())

    def test_scheduled_run_without_titles_or_cv_is_skipped_not_looped(self):
        w = self._arm(); w.titles.setPlainText(""); w.save_search(); w.sch_tick(); self.assertTrue(w.bthread.q.empty()); self.assertIn("skipped", w.logw.toPlainText()); self.assertEqual(w.sched.state, "idle")

    def test_schedule_off_never_starts(self):
        w = self._arm(); w.sch_on.setChecked(False); w.sched.next_at = dt.datetime.now() - dt.timedelta(days=1); w.sch_tick(); self.assertTrue(w.bthread.q.empty())

    def test_stop_cancels_pending_question(self):
        w = self.w; got = []
        t = threading.Thread(target=lambda: got.append(w.worker_ask("Pet unicorn?", ["a", "b"], {"title": "t", "company": "c"}))); t.start()
        for _ in range(100):
            self.app.processEvents(); t.join(0.02)
            if not t.is_alive() or not w.ask_box.isHidden(): break
        self.assertFalse(w.ask_box.isHidden()); w.stop(); t.join(3); self.assertFalse(t.is_alive()); self.assertEqual(got, [None]); self.assertTrue(B.HOOKS["stop"])

    def test_answer_flow_saves_and_unblocks(self):
        w = self.w; got = []
        t = threading.Thread(target=lambda: got.append(w.worker_ask("Pet unicorn?", [], {}))); t.start()
        for _ in range(100):
            self.app.processEvents(); t.join(0.02)
            if not w.ask_box.isHidden(): break
        w.ask_in.setCurrentText("two"); w.answer_ok(); t.join(3); self.assertEqual(got, ["two"])

    def test_table_edit_add_delete_and_filter(self):
        w = self.w; store.save_answer("Do you have a pet unicorn?", "yes"); w.refresh_table()
        rows = {w.table.item(r, 0).text(): r for r in range(w.table.rowCount())}; self.assertIn("do you have a pet unicorn", rows)
        r = rows["do you have a pet unicorn"]; w.table.item(r, 1).setText("no"); self.assertEqual(store.load_answers()["do you have a pet unicorn"], "no")
        w.table.setCurrentCell(r, 0); w.del_row(); self.assertNotIn("do you have a pet unicorn", store.load_answers())
        w.filter.setText("zzzz-nothing"); self.assertTrue(all(w.table.isRowHidden(i) for i in range(w.table.rowCount()))); w.filter.setText("")
        # profile param edit (bool / int / text) persists
        for r in range(w.table.rowCount()):
            k = w.table.item(r, 0).data(Qt.UserRole)
            if k == "profile:salary_year_eur": w.table.item(r, 1).setText("55000"); w.table.item(r, 1).setText("not a number")
        self.assertEqual(P.load_profile()["salary_year_eur"], 55000)

    def test_pending_questions_listed_red_then_answered(self):
        w = self.w; store.log_pending("linkedin", "t", "c", "Do you hold a security clearance?", "u"); store.log_pending("linkedin", "t", "c", "form error: x", "u"); w.refresh_table()
        texts = [w.table.item(r, 0).text() for r in range(w.table.rowCount())]; self.assertIn("Do you hold a security clearance?", texts); self.assertFalse(any(t.startswith("form error") for t in texts))
        r = texts.index("Do you hold a security clearance?"); w.table.item(r, 1).setText("no"); w.refresh_table()
        kinds = [w.table.item(i, 2).text() for i in range(w.table.rowCount()) if w.table.item(i, 0).text().lower().startswith("do you hold a security")]
        self.assertEqual(kinds, ["learned"])
        self.assertEqual(store.load_answers()[store.norm("Do you hold a security clearance?")], "no")

    def test_profile_switch_create_delete_keeps_data_separate(self):
        w = self.w; w.prof["first_name"] = "Alex"; P.save(P.PROFILE, w.prof); profiles.create("Bob", copy_from="default"); w.switch_profile("Bob")
        w.prof["first_name"] = "Bob"; P.save(P.PROFILE, w.prof); store.save_answer("q one", "bob-answer"); w.switch_profile("default")
        self.assertEqual(P.load_profile()["first_name"], "Alex"); self.assertNotIn("q one", store.load_answers()); w.switch_profile("Bob"); self.assertEqual(store.load_answers()["q one"], "bob-answer")

    def test_corrupt_profile_files_do_not_crash_gui_startup(self):
        pdir = profiles.PROFILES / profiles.active()
        for f in ("profile.json", "criteria.json", "motivation.json", "answers.json", "schedule.json"): (pdir / f).write_text("{corrupt", encoding="utf-8")
        w = self.gui.Window(); w.sch_timer.stop(); w.dock_timer.stop(); w.close()

    def test_finished_and_error_handlers(self):
        w = self.w; w.on_finished(0); w.on_error("boom"); self.assertTrue(w.start_b.isEnabled()); w.on_error("The browser window was closed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
