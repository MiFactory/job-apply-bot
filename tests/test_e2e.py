"""End-to-end tests in a real (headless) Chromium against a LOCAL fake LinkedIn (nothing is sent to linkedin.com).
Covers: apply loop, skip rules, unknown questions, CV language choice, dry-run, LinkedIn limit -> automatic retry, own daily cap, stop button,
captcha pause, login pause, form filler on varied controls.
Run:  python -m unittest tests.test_e2e -v      (needs: pip install playwright && playwright install chromium)"""
import sys, json, csv, pathlib, tempfile, unittest, datetime as dt, re, urllib.parse
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from playwright.sync_api import sync_playwright
from jobbot import profile as P, store, scheduler as S, linkedin, browser as B, formfiller as F
from jobbot.runner import run_jobs, last_result
from tests.test_unit import TmpData, PROF

JOBS = {   # id: (title, company, location, description)
 "1001": ("Account Manager", "Acme", "Brussels, Belgium · 1 day ago", "We are looking for an experienced account manager to join our team and you will work with our customers"),
 "1002": ("Junior Sales Intern", "Beta", "Brussels, Belgium", "Internship for students with our team and you will learn"),
 "1003": ("Business Developer", "Gamma", "Paris, France", "We are looking for a business developer to join our team and you will work with our customers"),
 "1004": ("Key Account Manager", "Delta", "Namur, Belgium", "We are looking for a key account manager to join our team and you will work with our customers"),
 "1005": ("Responsable commercial", "Epsilon", "Bruxelles, Belgique", "Nous recherchons un responsable commercial pour rejoindre notre équipe et vous travaillerez avec nos clients et nos partenaires"),
 "1006": ("Sales Executive", "Zeta", "Liège, Belgium", "We are looking for a sales executive to join our team and you will work with our customers"),
}
UNKNOWN_Q_JOBS = {"1004"}
EXTRA = {   # only reachable through the Saved list
 "1007": ("Sales Director", "Eta", "Brussels, Belgium", "We are looking for a sales director to join our team and you will work with our customers"),
 "1009": ("Sales Lead", "Theta", "Brussels, Belgium", "We are looking for a sales lead to join our team and you will work with our customers"),
}
CLOSED, EXTERNAL = ["1007"], ["1009"]

CSS_HIDE = "<style>[hidden]{display:none!important}</style>"
SEARCH_HTML = """<!doctype html><html><body>%(css)s<ul>%(cards)s</ul>
<div id=pane><h1 class="job-details-jobs-unified-top-card__job-title" id=t></h1>
<div class="job-details-jobs-unified-top-card__company-name" id=c></div>
<div class="job-details-jobs-unified-top-card__primary-description-container" id=l></div>
<div id="job-details"></div><button class="jobs-apply-button" id=apply onclick="openModal()">Easy Apply</button>
<button class="jobs-save-button" aria-label="Unsave job" onclick="window.recordUnsave(cur)">Saved</button></div>
<div id=dlg role=dialog hidden></div><div id=toast></div>
<div id=ovl hidden style="position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:50"></div>
<div id=post role=dialog hidden style="position:fixed;z-index:60;top:10%%;left:20%%;background:#fff;padding:20px"><h2>A postulé chez Acme</h2><p>Ran retail operations, led a team of 7</p><button aria-label="Ignorer" onclick="askDel()">X</button></div>
<div id=conf role=alertdialog hidden style="position:fixed;z-index:70;top:30%%;left:30%%;background:#fff;padding:20px"><h3>Supprimer de votre candidature ?</h3><p>Ceci n'affectera pas votre profil LinkedIn ni vos candidatures futures.</p><button onclick="conf.hidden=true">Annuler</button><button onclick="delPost()">Supprimer</button></div>
<div id=dsc role=alertdialog hidden style="position:fixed;z-index:80;top:35%%;left:35%%;background:#fff;padding:20px"><h3>Discard application?</h3><button onclick="dsc.hidden=true">Cancel</button><button onclick="dsc.hidden=true;dlg.hidden=true">Discard</button></div>
<script>
document.addEventListener('keydown',function(e){if(e.key=='Escape'&&!dlg.hidden)dsc.hidden=false;});
var JOBS=%(jobs)s, CLOSED=%(closed)s, EXT=%(ext)s, UNK=%(unk)s, MODE="%(mode)s", cur=null; window.submitted=[]; window.resumes=[];
if(MODE=='stuck') apply.disabled=true;
function askDel(){conf.hidden=false;} function delPost(){conf.hidden=true;post.hidden=true;ovl.hidden=true;}
function show(id){if(MODE=='blank')return; cur=id;var j=JOBS[id];t.innerText=j[0];c.innerText=j[1];l.innerText=j[2];document.getElementById('job-details').innerText=j[3]+(CLOSED.indexOf(id)>=0?' No longer accepting applications':''); apply.hidden=CLOSED.indexOf(id)>=0; apply.innerText=EXT.indexOf(id)>=0?'Apply':'Easy Apply';}
function openModal(){dlg.hidden=false; if(MODE=='limit'){dlg.innerHTML="<h2>Easy Apply</h2><p>You've reached the daily Easy Apply limit. Try again tomorrow.</p>";return;} step1();}
function btn(label,fn){return '<button aria-label="'+label+'" onclick="'+fn+'()">'+label+'</button>'}
function step1(){dlg.innerHTML='<h3>Contact info</h3><label for=fn>First name</label><input id=fn><label for=em>Email address</label><input id=em><label for=ph>Mobile phone number</label><input id=ph>'
 +'<label for=cv>Upload resume</label><input type=file id=cv onchange="window.resumes.push(this.files[0].name)">'+btn('Continue to next step','step2');}
function step2(){ if(UNK.indexOf(cur)>=0) dlg.innerHTML='<h3>Additional questions</h3><label for=q>Do you have a pet unicorn?</label><input id=q>'+btn('Review your application','step3');
 else dlg.innerHTML='<h3>Additional questions</h3><fieldset><legend>Will you now or in the future require sponsorship?</legend><input type=radio name=s id=s1><label for=s1>Yes</label><input type=radio name=s id=s2><label for=s2>No</label></fieldset>'
  +'<label><input type=checkbox id=fol checked> Follow Acme to stay up to date</label>'+btn('Review your application','step3');}
function step3(){var f=document.getElementById('fol'); window.fol=f?f.checked:null; dlg.innerHTML='<h3>Review</h3>'+btn('Submit application','submit');}
function submit(){window.recordSubmit(JSON.stringify({job:cur,follow:window.fol})); dlg.hidden=true; ovl.hidden=false; post.hidden=false;}      // LinkedIn post-apply window: covers the page until closed + confirmed
</script><script>%(auto)s</script></body></html>"""


class FakeLinkedIn:
    def __init__(self): self.mode = "ok"; self.logged_in = True; self.hits = []; self.checkpoint = False; self.draft_ids = []; self.saved_ids = ["1001", "1002", "1003", "1004", "1006", "1007", "1009"]
    def handler(self, route):
        u = urllib.parse.urlparse(route.request.url); q = urllib.parse.parse_qs(u.query); self.hits.append(u.path)
        if self.checkpoint and u.path.startswith("/jobs"):
            return route.fulfill(status=200, content_type="text/html", body="<h1>Security check</h1><p>Please verify you are human</p>")
        if u.path.startswith("/feed"):
            if not self.logged_in: return route.fulfill(status=200, content_type="text/html", body="<script>location.replace('/login')</script>")
            return route.fulfill(status=200, content_type="text/html", body="<h1>Feed</h1>")
        if u.path.startswith("/login"): return route.fulfill(status=200, content_type="text/html", body="<h1>Sign in</h1>")
        if u.path.startswith("/my-items/saved-jobs"):
            links = "".join(f'<li><a href="/jobs/view/{i}/">Saved job {i}</a></li>' for i in self.saved_ids)
            return route.fulfill(status=200, content_type="text/html", body=f"<h1>Saved jobs</h1><ul>{links}</ul>")
        if u.path.startswith("/jobs-tracker"):
            links = "".join(f'<li><a href="/jobs/view/{i}/">Draft {i}</a><button>Continuer la candidature</button></li>' for i in self.draft_ids)
            return route.fulfill(status=200, content_type="text/html", body=f"<h1>Suivi des emplois</h1><ul>{links}</ul>")
        if u.path.startswith("/jobs/view/") or u.path.startswith("/jobs/search"):
            jid = u.path.strip("/").split("/")[-1] if u.path.startswith("/jobs/view/") else ""
            auto = f"show('{jid}')" if jid else ""
            cards = "" if jid else "" if q.get("start", ["0"])[0] != "0" else "".join(f'<li data-occludable-job-id="{i}"><a href="#" onclick="show(\'{i}\');return false">{j[0]}</a></li>' for i, j in JOBS.items())
            return route.fulfill(status=200, content_type="text/html", body=SEARCH_HTML % dict(css=CSS_HIDE, cards=cards, jobs=json.dumps({**JOBS, **EXTRA}), unk=json.dumps(sorted(UNKNOWN_Q_JOBS)), mode=self.mode, closed=json.dumps(CLOSED), ext=json.dumps(EXTERNAL), auto=auto))
        return route.fulfill(status=200, content_type="text/html", body="<p>ok</p>")


from playwright.sync_api import Page
_orig_wait = Page.wait_for_timeout
def _fast_wait(self, ms): return _orig_wait(self, min(ms, 120))     # tests only: the bot's human-like delays are not needed against a local fake


class E2E(TmpData):
    @classmethod
    def setUpClass(cls):
        Page.wait_for_timeout = _fast_wait; cls.pw = sync_playwright().start(); cls.browser = cls.pw.chromium.launch()
    @classmethod
    def tearDownClass(cls): cls.browser.close(); cls.pw.stop(); Page.wait_for_timeout = _orig_wait

    def setUp(self):
        super().setUp()
        self.fake = FakeLinkedIn(); self.ctx = self.browser.new_context(); self.ctx.route(re.compile(r"https://www\.linkedin\.com/.*"), self.fake.handler)
        self.subs = []; self.ctx.expose_function("recordSubmit", lambda x: self.subs.append(json.loads(x)))
        self.unsaves = []; self.ctx.expose_function("recordUnsave", lambda x: self.unsaves.append(x))
        self.page = self.ctx.new_page(); self.page.set_default_timeout(8000)
        self.cv_en = self.d / "CV_EN.pdf"; self.cv_fr = self.d / "CV_FR.pdf"
        self.cv_en.write_bytes(b"%PDF-1.4 en"); self.cv_fr.write_bytes(b"%PDF-1.4 fr")
        self.prof = {**PROF, "cv_files": {"en": str(self.cv_en), "fr": str(self.cv_fr), "nl": ""}, "default_cv_lang": "en", "default_answers": False}
        self.crit = {**P.DEFAULT_CRITERIA, "titles": ["Account Manager"], "locations": ["Belgium"], "sites": ["linkedin"], "max_applications_per_day": 40}
        self.logs = []; B.HOOKS.update(log=self.logs.append, stop=False, pause=None, result="")
    def tearDown(self): self.ctx.close(); B.HOOKS.update(pause=None, stop=False, result="", log=print); super().tearDown()

    def rows(self):
        if not store.APPS.exists(): return []
        with open(store.APPS, encoding="utf-8-sig") as f: return list(csv.DictReader(f, delimiter=";"))
    def run_bot(self, max_apps=30, dry=False, interactive=False, asker=None, sites=("linkedin",)):
        return run_jobs(self.page, dict(self.prof), dict(self.crit), list(sites), max_apps, dry, interactive, asker, {"en": "Hello {company}", "fr": "Bonjour {company}"})

    # ------------------------------------------------------------------ main flow
    def test_full_run_rules_cv_language_and_logging(self):
        store.log_application("linkedin", "1006", "Sales Executive", "Zeta", "Liège", "u", "APPLIED")           # already applied → must not be reopened
        n = self.run_bot()
        by = {r["job_id"]: r for r in self.rows()}
        self.assertEqual(by["1001"]["status"], "APPLIED"); self.assertEqual(by["1005"]["status"], "APPLIED")
        self.assertEqual(by["1002"]["status"], "SKIPPED"); self.assertIn("excluded", by["1002"]["note"])
        self.assertEqual(by["1003"]["status"], "SKIPPED"); self.assertIn("location", by["1003"]["note"])
        self.assertEqual(by["1004"]["status"], "NEEDS_INFO"); self.assertIn("unicorn", by["1004"]["note"].lower())
        self.assertEqual(sum(1 for r in self.rows() if r["job_id"] == "1006"), 1, "an already-applied job was processed again")
        self.assertEqual(n, 2); self.assertEqual(last_result(), "finished")
        self.assertTrue(store.PENDING.exists() and "unicorn" in store.PENDING.read_text(encoding="utf-8").lower())
        self.assertIn(("linkedin", "1004"), store.seen_jobs())

    def test_cv_language_and_follow_checkbox_and_answers(self):
        self.crit["titles"] = ["Account Manager"]; seen = []
        orig = linkedin.easy_apply
        def spy(page, filler, resume, dry):
            r = orig(page, filler, resume, dry); seen.append((filler.ctx["title"], pathlib.Path(resume).name)); return r
        linkedin.easy_apply = spy
        try: self.run_bot()
        finally: linkedin.easy_apply = orig
        d = dict(seen); self.assertEqual(d["Account Manager"], "CV_EN.pdf"); self.assertEqual(d["Responsable commercial"], "CV_FR.pdf")
        sub = self.subs; self.assertTrue(sub and all(s["follow"] is False for s in sub), f"'follow company' must be unticked: {sub}")

    def test_dry_run_never_submits(self):
        n = self.run_bot(dry=True, max_apps=2)
        self.assertEqual(self.subs, [], "dry-run pressed Submit"); self.assertTrue(all(r["status"] != "APPLIED" for r in self.rows())); self.assertEqual(n, 2)
        self.assertIn("DRY_RUN", {r["status"] for r in self.rows()})

    # ------------------------------------------------------------------ stuck / dry-run follow-up
    def test_real_run_applies_to_jobs_a_dry_run_only_looked_at(self):
        self.run_bot(dry=True, max_apps=2); self.assertEqual(self.subs, [])
        dry = {r["job_id"] for r in self.rows() if r["status"] == "DRY_RUN"}; self.assertTrue(dry)
        self.assertFalse(self.page.locator("div[role=dialog]:visible").count(), "dry run left the Easy Apply form open")
        self.run_bot(dry=False)
        applied = {r["job_id"] for r in self.rows() if r["status"] == "APPLIED"}
        self.assertTrue(dry <= applied, f"dry-run jobs {dry} not applied later: {applied}")

    def test_timed_out_answer_is_used_and_marked_auto(self):
        from jobbot.answerer import Auto
        self.run_bot(asker=lambda l, o, c: Auto("no"), interactive=True)
        self.assertEqual({r["job_id"]: r["status"] for r in self.rows()}["1004"], "APPLIED")
        self.assertIn(store.norm("Do you have a pet unicorn?"), store.load_auto())

    def test_open_card_retries_when_first_click_is_swallowed_and_gives_up_otherwise(self):
        html = """<div id=l><a id=c1 href='#'>one</a></div><h1 id=t>Old job</h1><script>
        var n=0; document.getElementById('c1').addEventListener('click',function(e){e.preventDefault(); n++; if(n>=%d){document.getElementById('t').innerText='New job'; history.replaceState({},'','?currentJobId=77');}});</script>"""
        card = lambda: self.page.locator("#l")
        self.page.set_content(html % 2); self.assertTrue(linkedin.open_card(self.page, card(), "77", timeout_ms=900))
        self.page.set_content(html % 99); self.assertFalse(linkedin.open_card(self.page, card(), "77", timeout_ms=600))

    # ------------------------------------------------------------------ pop-ups and timeouts
    def test_post_apply_popup_and_confirmation_are_closed_so_next_job_works(self):
        """Regression: LinkedIn's 'A postulé chez…' window + 'Supprimer de votre candidature ?' confirmation used to cover the page -> 'Locator.click: Timeout 15000ms'."""
        self.crit["timeout_seconds"] = 3; t0 = __import__("time").time(); n = self.run_bot()
        applied = sorted(r["job_id"] for r in self.rows() if r["status"] == "APPLIED")
        self.assertEqual(applied, ["1001", "1005", "1006"], self.logs); self.assertEqual(n, 3); self.assertFalse([m for m in self.logs if "⚠" in str(m)], [m for m in self.logs if "⚠" in str(m)])
        self.assertTrue(any("closed" in str(m) for m in self.logs)); self.assertLess(__import__("time").time() - t0, 60, "a click waited for the timeout")
        self.assertEqual(self.page.locator("#ovl:visible").count(), 0)

    def test_timeout_setting_is_honored_with_friendly_message_and_job_not_lost(self):
        self.fake.mode = "stuck"; self.crit["timeout_seconds"] = 2; t0 = __import__("time").time(); n = self.run_bot(); el = __import__("time").time() - t0
        self.assertEqual(n, 0); msgs = [str(m) for m in self.logs if "nothing clickable after 2s" in str(m)]; self.assertTrue(msgs, self.logs)
        self.assertGreaterEqual(el, 2); self.assertNotIn("TimeoutError: Locator", " ".join(map(str, self.logs)))
        self.assertNotIn(("linkedin", "1001"), store.seen_jobs(), "a job that timed out must stay retryable")

    def test_unreadable_job_details_are_not_logged_as_skipped(self):
        self.fake.mode = "blank"; self.crit["timeout_seconds"] = 2; self.assertEqual(self.run_bot(), 0)
        self.assertFalse(self.rows(), "pages that did not load must not mark jobs as SKIPPED forever")

    def test_set_timeouts_clamps_and_applies(self):
        from jobbot.runner import set_timeouts
        for given, want in [(15, 15), ("7", 7), (1, 2), (99999, 300), ("abc", 15), (None, 15), (0, 2)]:
            c = {"timeout_seconds": given}; self.assertEqual(set_timeouts(self.page, c), want, given); self.assertEqual(c["timeout_seconds"], want)
        set_timeouts(self.page, {"timeout_seconds": 1}); t0 = __import__("time").time()
        with self.assertRaises(Exception): self.page.locator("#does-not-exist").click()
        self.assertLess(__import__("time").time() - t0, 6)

    # ------------------------------------------------------------------ saved jobs
    def status_by_job(self): return {r["job_id"]: (r["status"], r["note"]) for r in self.rows()}

    def test_saved_only_ignores_search_filters_and_never_searches(self):
        self.crit.update(saved_jobs="only", timeout_seconds=3); store.log_application("linkedin", "1006", "Sales Executive", "Zeta", "Liège", "u", "APPLIED")
        n = self.run_bot(); st = self.status_by_job()
        for jid in ("1001", "1002", "1003"): self.assertEqual(st[jid][0], "APPLIED", (jid, st.get(jid), self.logs))      # 1002 = Junior/Intern, 1003 = Paris: filters must NOT apply to saved jobs
        self.assertEqual(st["1004"][0], "NEEDS_INFO"); self.assertEqual(st["1007"][0], "SKIPPED"); self.assertIn("no longer accepting", st["1007"][1])
        self.assertEqual(st["1009"][0], "SKIPPED"); self.assertIn("not Easy Apply", st["1009"][1]); self.assertTrue(st["1007"][1].startswith("saved:"))
        self.assertEqual(sum(1 for r in self.rows() if r["job_id"] == "1006"), 1, "already applied: must not be reopened"); self.assertEqual(n, 3)
        self.assertFalse([h for h in self.fake.hits if h.startswith("/jobs/search")], "'only saved' must not run the search"); self.assertEqual(last_result(), "finished")
        self.assertTrue(any("7 saved job" in str(m) for m in self.logs))

    def test_drafts_are_finished_with_saved_jobs_and_can_be_switched_off(self):
        self.fake.saved_ids = ["1001"]; self.fake.draft_ids = ["1005", "1001"]; self.crit.update(saved_jobs="only", timeout_seconds=3)
        self.run_bot(); st = self.status_by_job()
        self.assertEqual(st["1005"][0], "APPLIED", self.logs); self.assertEqual(sum(1 for r in self.rows() if r["job_id"] == "1001"), 1, "saved+draft duplicate processed twice")
        self.assertTrue(any("draft application" in str(m) for m in self.logs))
        store.APPS.unlink(); self.crit["include_drafts"] = False; self.run_bot(); self.assertNotIn("1005", self.status_by_job())

    def test_apply_button_found_by_text_and_hard_click_when_covered(self):
        self.page.set_content("<main><div style='position:relative'><a id=b href='#' onclick=\"window.hit=1;return false\">Continuer la candidature</a><div style='position:absolute;inset:0;z-index:9'></div></div></main>")
        btn = linkedin.find_apply_button(self.page); self.assertIsNotNone(btn); self.assertTrue(linkedin.click_hard(self.page, btn)); self.assertEqual(self.page.evaluate("window.hit"), 1)
        self.page.set_content("<main><button>Apply on company website</button></main>"); self.assertIsNone(linkedin.find_apply_button(self.page))

    def test_saved_first_then_search(self):
        self.crit.update(saved_jobs="first", timeout_seconds=3); n = self.run_bot(); st = self.status_by_job()
        hits = [h for h in self.fake.hits if h.startswith(("/jobs/search", "/my-items"))]; self.assertTrue(hits[0].startswith("/my-items"), hits); self.assertTrue(any(h.startswith("/jobs/search") for h in hits))
        self.assertEqual(st["1005"][0], "APPLIED", "a job that is not saved is still found by the search"); self.assertEqual(st["1006"][0], "APPLIED"); self.assertEqual(n, 5)

    def test_saved_off_by_default(self):
        self.run_bot(max_apps=1); self.assertFalse([h for h in self.fake.hits if h.startswith("/my-items")])

    def test_saved_unsave_after_apply_only_for_real_applications(self):
        self.fake.saved_ids = ["1001", "1004"]; self.crit.update(saved_jobs="only", unsave_after_apply=True, timeout_seconds=3)
        self.run_bot(); self.assertEqual(self.unsaves, ["1001"], "only successfully applied jobs leave the Saved list")
        self.unsaves.clear(); store.APPS.unlink(); self.fake.saved_ids = ["1001"]; self.run_bot(dry=True); self.assertEqual(self.unsaves, [], "dry-run must never change your Saved list"); self.assertEqual(self.subs[1:], [])

    def test_saved_retry_rules(self):
        self.fake.saved_ids = ["1002", "1004", "1006", "1007"]; self.crit.update(saved_jobs="only", timeout_seconds=3)
        store.log_application("linkedin", "1002", "Junior", "Beta", "x", "u", "SKIPPED", "excluded word in title: intern")      # skipped by the SEARCH filters -> saved run must take it
        store.log_application("linkedin", "1006", "Sales Executive", "Zeta", "x", "u", "APPLIED")
        store.log_application("linkedin", "1007", "Sales Director", "Eta", "x", "u", "SKIPPED", "saved: no longer accepting applications")
        self.run_bot(); rows = [(r["job_id"], r["status"]) for r in self.rows()]
        self.assertIn(("1002", "APPLIED"), rows); self.assertEqual(rows.count(("1006", "APPLIED")), 1); self.assertEqual(sum(1 for r in rows if r[0] == "1007"), 1, "closed saved job must not be reopened every run")
        self.run_bot(); self.assertEqual(sum(1 for r in self.rows() if r["job_id"] == "1002" and r["status"] == "APPLIED"), 1, "applied once only")

    def test_saved_empty_list_and_limit_and_wrong_site(self):
        self.fake.saved_ids = []; self.crit.update(saved_jobs="only", timeout_seconds=3); self.assertEqual(self.run_bot(), 0); self.assertTrue(any("0 saved job" in str(m) for m in self.logs))
        self.fake.saved_ids = ["1001", "1005"]; self.fake.mode = "limit"; self.crit["saved_jobs"] = "first"; self.fake.hits.clear()
        self.assertEqual(self.run_bot(), 0); self.assertEqual(last_result(), "limit"); self.assertFalse([h for h in self.fake.hits if h.startswith("/jobs/search")], "no pointless LinkedIn search after the limit")
        self.assertNotIn(("linkedin", "1001"), store.seen_jobs())
        self.logs.clear(); self.crit["saved_jobs"] = "only"; self.assertEqual(self.run_bot(sites=("indeed",)), 0); self.assertTrue(any("LinkedIn only" in str(m) for m in self.logs))

    def test_saved_garbage_values_in_setting(self):
        self.crit["saved_jobs"] = "banana"; self.run_bot(max_apps=1); self.assertFalse([h for h in self.fake.hits if h.startswith("/my-items")])

    def test_max_per_run(self):
        self.assertEqual(self.run_bot(max_apps=1), 1); self.assertEqual(last_result(), "finished"); self.assertEqual(len(self.subs), 1)

    # ------------------------------------------------------------------ limit / retry / quota / stop
    def test_linkedin_limit_stops_run_and_retry_cycle_resumes(self):
        self.fake.mode = "limit"
        n = self.run_bot(); self.assertEqual(n, 0); self.assertEqual(last_result(), "limit")
        self.assertFalse([r for r in self.rows() if r["status"] == "APPLIED"]); self.assertNotIn(("linkedin", "1001"), store.seen_jobs(), "job hit by the limit must stay retryable")
        # scheduler: Monday 09:00 start, limit, tests every 5 min, limit lifted after 3rd test
        t = dt.datetime(2026, 11, 2, 9, 0); sc = S.Scheduler({**S.DEFAULT_SCHEDULE, "enabled": True, "days": [0], "time": "09:00"}, t - dt.timedelta(minutes=1)); self.assertTrue(sc.due(t))
        sc.on_result(last_result(), t); runs = 1
        for k in range(1, 4):
            now = t + dt.timedelta(minutes=5 * k); self.assertFalse(sc.due(now - dt.timedelta(seconds=1))); self.assertTrue(sc.due(now))
            if k == 3: self.fake.mode = "ok"
            self.run_bot(max_apps=1); runs += 1; sc.on_result(last_result(), now)
            self.assertEqual(sc.state, "retry" if k < 3 else "idle")
        self.assertEqual(len([r for r in self.rows() if r["status"] == "APPLIED"]), 1); self.assertEqual(sc.next_at, dt.datetime(2026, 11, 9, 9, 0))

    def test_own_daily_cap_is_quota_not_limit(self):
        self.crit["max_applications_per_day"] = 1; n = self.run_bot(); self.assertEqual(n, 1); self.assertEqual(last_result(), "quota")
        sc = S.Scheduler({**S.DEFAULT_SCHEDULE, "enabled": True, "days": list(range(7))}); sc.on_result("quota"); self.assertEqual(sc.state, "idle")
        self.assertEqual(self.run_bot(), 0, "second run the same day must do nothing"); self.assertEqual(last_result(), "quota")

    def test_stop_button(self):
        def log(m):
            self.logs.append(m)
            if "applied (1)" in str(m): B.HOOKS["stop"] = True
        B.HOOKS["log"] = log; n = self.run_bot(); self.assertEqual(n, 1); self.assertEqual(last_result(), "stopped")
        sc = S.Scheduler({**S.DEFAULT_SCHEDULE, "enabled": True, "days": list(range(7))}); sc.on_result("limit"); sc.on_result("stopped"); self.assertFalse(sc.due(dt.datetime.now() + dt.timedelta(minutes=30)))

    def test_limit_message_after_submit_detected(self):
        orig = SEARCH_HTML
        self.fake.mode = "ok"
        self.page.goto("https://www.linkedin.com/jobs/search/?keywords=x")
        self.page.evaluate("window.submit = function(){ dlg.innerHTML='<p>You have reached the daily Easy Apply limit</p>'; document.body.insertAdjacentHTML('afterbegin','<div>You have reached the daily Easy Apply limit</div>') }")
        self.page.evaluate("show('1001')"); f = F.Filler(self.prof, self.crit, False, None, {})
        with self.assertRaises(linkedin.LimitReached): linkedin.easy_apply(self.page, f, str(self.cv_en), False)

    # ------------------------------------------------------------------ human in the loop
    def test_captcha_page_pauses_for_human(self):
        calls = []; B.HOOKS["pause"] = lambda m: (calls.append(m), setattr(self.fake, "checkpoint", False))
        self.fake.checkpoint = True; self.page.goto("https://www.linkedin.com/jobs/search/?keywords=x")
        self.assertTrue(B.human_check(self.page, "LinkedIn")); self.assertEqual(len(calls), 1)
        self.page.goto("https://www.linkedin.com/jobs/search/?keywords=x"); self.assertFalse(B.human_check(self.page, "LinkedIn"))

    def test_logged_out_asks_user_then_continues(self):
        self.fake.logged_in = False; calls = []
        B.HOOKS["pause"] = lambda m: (calls.append(m), setattr(self.fake, "logged_in", True))
        self.assertEqual(self.run_bot(max_apps=1), 1); self.assertEqual(len(calls), 1)

    def test_login_never_completed_exits_cleanly(self):
        self.fake.logged_in = False; B.HOOKS["pause"] = lambda m: None
        with self.assertRaises(SystemExit): self.run_bot()

    def test_unknown_question_asker_answers_and_reuses(self):
        asked = []
        def asker(label, options, ctx): asked.append(label); return "yes, two of them"
        self.run_bot(asker=asker, interactive=True)
        self.assertEqual(len(asked), 1, asked); self.assertIn("unicorn", asked[0].lower())
        self.assertEqual({r["job_id"]: r["status"] for r in self.rows()}["1004"], "APPLIED")
        self.assertIn("yes, two of them", json.dumps(store.load_answers()))
        asked.clear(); store.ANSWERS.write_text(store.ANSWERS.read_text(encoding="utf-8"), encoding="utf-8")   # second profile run: answer must be reused silently
        f = F.Filler(self.prof, self.crit, False, None, {}); self.assertEqual(f.resolve("Do you have a pet unicorn?"), "yes, two of them")

    def test_asker_returns_nothing_skips_job_without_crash(self):
        self.run_bot(asker=lambda l, o, c: None, interactive=True)
        self.assertEqual({r["job_id"]: r["status"] for r in self.rows()}["1004"], "NEEDS_INFO")

    def test_site_survives_garbage_pages(self):
        orig = self.fake.handler
        def broken(route):
            if "/jobs/search" in route.request.url: return route.fulfill(status=500, body="boom")
            return orig(route)
        self.ctx.unroute(re.compile(r"https://www\.linkedin\.com/.*")); self.ctx.route(re.compile(r"https://www\.linkedin\.com/.*"), broken)
        self.assertEqual(self.run_bot(), 0)      # no cards → returns, no exception


class FormControls(TmpData):
    HTML = """<!doctype html><div role=dialog>
<label for=a>Prénom</label><input id=a><label for=b>Adresse e-mail</label><input id=b>
<label for=c>Niveau d'anglais</label><select id=c><option>Select an option</option><option>Basic</option><option>Professional</option><option>Native</option></select>
<fieldset><legend>Disposez-vous d'un permis de travail valide ?</legend><input type=radio name=w id=w1><label for=w1>Oui</label><input type=radio name=w id=w2><label for=w2>Non</label></fieldset>
<label for=cl>Lettre de motivation</label><textarea id=cl></textarea>
<label><input type=checkbox id=tc> I agree to the terms and privacy policy</label><label><input type=checkbox id=nl> Subscribe to our newsletter</label><label><input type=checkbox id=fo> Follow company</label>
<input id=pre value="already"><label for=hid>Hidden</label><input id=hid style="display:none"><input id=dis disabled aria-label="Disabled thing">
</div>"""
    @classmethod
    def setUpClass(cls): cls.pw = sync_playwright().start(); cls.br = cls.pw.chromium.launch()
    @classmethod
    def tearDownClass(cls): cls.br.close(); cls.pw.stop()

    def test_many_control_types_french_labels(self):
        pg = self.br.new_page(); pg.set_content(self.HTML)
        f = F.Filler(PROF, P.DEFAULT_CRITERIA, False, None, {"en": "Hello {company} — {title} — {full_name}"}); f.ctx = {"title": "AM", "company": "ACME", "lang": "en"}
        n = f.fill(pg.locator("div[role=dialog]"))
        v = pg.evaluate("[a.value,b.value,c.value,w1.checked,w2.checked,cl.value,tc.checked,nl.checked,fo.checked,pre.value,hid.value,dis.value]")
        self.assertEqual(v[:3], ["Alex", "alex@example.com", "Professional"]); self.assertTrue(v[3]); self.assertFalse(v[4]); self.assertIn("ACME", v[5]); self.assertIn("Alex Martin", v[5])
        self.assertTrue(v[6]); self.assertFalse(v[7]); self.assertFalse(v[8]); self.assertEqual(v[9], "already"); self.assertEqual(v[10], ""); self.assertEqual(v[11], ""); self.assertGreaterEqual(n, 6)

    def test_unknown_required_field_raises_needinfo(self):
        pg = self.br.new_page(); pg.set_content("<div role=dialog><label for=q>What is your favourite dinosaur?</label><input id=q></div>")
        with self.assertRaises(F.NeedInfo) as cm: F.Filler({**PROF, "default_answers": False}, P.DEFAULT_CRITERIA, False, None, {}).fill(pg.locator("div[role=dialog]"))
        self.assertIn("dinosaur", cm.exception.question.lower())

    def test_select_without_matching_option_raises_needinfo(self):
        pg = self.br.new_page(); pg.set_content("<div role=dialog><label for=s>Will you now or in the future require sponsorship?</label><select id=s><option>Select</option><option>Maybe</option><option>Perhaps</option></select></div>")
        with self.assertRaises(F.NeedInfo): F.Filler({**PROF, "default_answers": False}, P.DEFAULT_CRITERIA, False, None, {}).fill(pg.locator("div[role=dialog]"))

    def test_hostile_html_does_not_crash(self):
        pg = self.br.new_page(); pg.set_content("<div role=dialog>" + "<input>" * 30 + "<label for=x>" + "<b>" * 200 + "</label><input id=x name='a\"b'><input type=radio name='a\"b'><input type=radio name='a\"b'></div>")
        try: F.Filler(PROF, P.DEFAULT_CRITERIA, False, lambda l, o, c: "x", {}).fill(pg.locator("div[role=dialog]"))
        except F.NeedInfo: pass


class PopupHandler(TmpData):
    @classmethod
    def setUpClass(cls): cls.pw = sync_playwright().start(); cls.br = cls.pw.chromium.launch()
    @classmethod
    def tearDownClass(cls): cls.br.close(); cls.pw.stop()
    def setUp(self): super().setUp(); B.HOOKS.update(log=lambda m: None)
    def tearDown(self): B.HOOKS.update(log=print); super().tearDown()

    def page(self, html):
        pg = self.br.new_page(); pg.set_default_timeout(3000); pg.set_content("<style>[hidden]{display:none!important}</style>" + html); return pg

    def test_save_application_dialog_is_discarded(self):
        from jobbot import popups
        pg = self.page("<div role=dialog id=d><h3>Enregistrer cette candidature ?</h3><button id=save>Enregistrer</button><button id=disc onclick=\"d.hidden=true\">Abandonner</button></div>")
        self.assertEqual(popups.dismiss_popups(pg), 1); self.assertEqual(pg.locator("#d:visible").count(), 0)

    def test_unrelated_destructive_dialog_is_never_confirmed(self):
        from jobbot import popups
        pg = self.page("<div role=dialog id=d><h3>Delete your account?</h3><button id=del onclick=\"window.deleted=true\">Delete</button><button id=cancel>Cancel</button></div>")
        popups.dismiss_popups(pg); self.assertFalse(pg.evaluate("!!window.deleted"), "pressed Delete on a dialog it does not recognise")

    def test_plain_close_button_and_escape(self):
        from jobbot import popups
        pg = self.page("<div role=dialog id=a><p>Promo</p><button aria-label='Fermer' onclick=\"a.hidden=true\">x</button></div>"); self.assertEqual(popups.dismiss_popups(pg), 1)
        pg = self.page("<div role=dialog id=b><p>No button</p></div><script>document.addEventListener('keydown',e=>{if(e.key=='Escape')b.hidden=true})</script>"); self.assertEqual(popups.dismiss_popups(pg), 1)

    def test_nothing_open_and_unclosable_dialog_terminate(self):
        from jobbot import popups
        self.assertEqual(popups.dismiss_popups(self.page("<p>hello</p>")), 0)
        import time; t0 = time.time(); popups.dismiss_popups(self.page("<div role=dialog><p>stuck forever</p></div>")); self.assertLess(time.time() - t0, 10)

    def test_friendly_error(self):
        from jobbot import popups
        self.assertIn("nothing clickable after 9s", popups.friendly_error(TimeoutError("x"), 9)); self.assertIn("ValueError", popups.friendly_error(ValueError("boom")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
