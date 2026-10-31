"""Job Apply Bot — GUI.
Left   : drop your CVs (any language) + default motivation message per language + search settings
Centre : the browser (embedded Chromium) the bot drives, with log
Right  : every parameter / filter / question the bot answers automatically; unknown questions are added here,
         you answer once and it is reused in every next application.
Run:  python gui.py
"""
import os, sys, json, threading, pathlib, csv, queue, time

from PySide6.QtCore import Qt, QObject, Signal, QTimer
from PySide6.QtGui import QColor, QWindow
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QSplitter, QTabWidget, QLabel,
    QPushButton, QLineEdit, QPlainTextEdit, QTextEdit, QTableWidget, QTableWidgetItem, QComboBox, QSpinBox, QCheckBox,
    QFileDialog, QMessageBox, QHeaderView, QFrame, QDialog, QFormLayout, QAbstractItemView, QSlider, QScrollArea)

from jobbot import profile as P, store, cv_analyzer, profiles
from jobbot import browser as B

ROOT = pathlib.Path(__file__).resolve().parent
DATA = P.DATA
def motiv_path(): return P.PROFILE.parent / "motivation.json"
MARKER = "JOBBOT_BROWSER"
LANGS = {"en": "English", "fr": "Français", "nl": "Nederlands", "es": "Español", "de": "Deutsch"}

DEFAULT_MOTIVATION = {
    "en": "Dear Hiring Team,\n\nI am very interested in the {title} position at {company}. With my background in business development, IT and project work, "
          "my professional English and native French, I can contribute quickly. I am available immediately and authorised to work in Belgium.\n\n"
          "I would be glad to discuss how I can help {company}. Please find my CV attached.\n\nKind regards,\n{full_name}",
    "fr": "Madame, Monsieur,\n\nLe poste de {title} chez {company} a retenu toute mon attention. Fort de mon expérience en développement commercial, IT et gestion de projet, "
          "je peux être rapidement opérationnel. Je suis disponible immédiatement et autorisé à travailler en Belgique.\n\n"
          "Je serais ravi d'échanger avec vous. Vous trouverez mon CV en pièce jointe.\n\nCordialement,\n{full_name}",
}
PARAM_LABELS = [  # (profile key, label shown to the user)
    ("first_name", "First name / Prénom"), ("last_name", "Last name / Nom"), ("email", "Email"), ("phone", "Phone (international)"),
    ("phone_national", "Phone without country code"), ("phone_country_code", "Phone country code"), ("city", "City / Ville"),
    ("postal_code", "Postal code"), ("country", "Country"), ("linkedin_url", "LinkedIn URL"), ("website", "Website / portfolio"),
    ("headline", "Headline"), ("years_experience_total", "Years of experience (total)"), ("salary_year_eur", "Expected salary / year (EUR)"),
    ("salary_month_eur", "Expected salary / month (EUR)"), ("notice_period", "Notice period / availability"),
    ("authorized_to_work", "Authorised to work in Belgium (yes/no)"), ("needs_sponsorship", "Needs visa sponsorship (yes/no)"),
    ("willing_relocate", "Willing to relocate (yes/no)"), ("driving_licence", "Driving licence (yes/no)"), ("education", "Education"),
    ("google_email", "Gmail used for 'Continue with Google'"),
]


def load_motivation():
    m = json.loads(motiv_path().read_text(encoding="utf-8")) if motiv_path().exists() else {}
    for k, v in DEFAULT_MOTIVATION.items(): m.setdefault(k, v)
    return m


# ------------------------------------------------------------------ browser (real Chrome driven by Playwright, embedded in the window on Windows)
def find_chrome_hwnd(marker=MARKER):
    """Windows only: find the Chrome window whose title contains the marker (no extra dependency)."""
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32; found = []
    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        if u.IsWindowVisible(h):
            n = u.GetWindowTextLengthW(h)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1); u.GetWindowTextW(h, buf, n + 1)
                cls = ctypes.create_unicode_buffer(64); u.GetClassNameW(h, cls, 64)
                if marker in buf.value and cls.value.startswith("Chrome_WidgetWin"): found.append(h)
        return True
    u.EnumWindows(cb, 0)
    return found[0] if found else 0


class BrowserThread(threading.Thread):
    """Owns Playwright + Chrome. The GUI sends commands through a queue (goto / run / quit)."""
    def __init__(self, win):
        super().__init__(daemon=True); self.win, self.q = win, queue.Queue()
    def run(self):
        from jobbot.browser import Browser
        from jobbot.runner import run_jobs
        br = self.win.bridge
        try:
            with Browser() as b:
                pg = b.live_page(); pg.goto(f"data:text/html,<meta charset=utf-8><title>{MARKER}</title><body style='font-family:sans-serif'><h2>Job Apply Bot browser</h2>Use the &#128273; buttons above to log in, then press Start.</body>")
                hwnd = 0
                if sys.platform == "win32" and self.win.embed_mode() != 2:
                    for _ in range(20):
                        hwnd = find_chrome_hwnd()
                        if hwnd: break
                        time.sleep(0.25)
                closed = threading.Event(); b.ctx.on("close", lambda *_: closed.set())
                br.ready.emit(int(hwnd))
                while True:
                    try: cmd = self.q.get(timeout=1)
                    except queue.Empty:
                        if closed.is_set(): br.error.emit("The browser window was closed — click 🔄 Reopen browser."); break
                        continue
                    if cmd[0] == "quit": break
                    if closed.is_set(): br.error.emit("The browser window was closed — click 🔄 Reopen browser."); break
                    try:
                        if cmd[0] == "goto": b.live_page().goto(cmd[1])
                        elif cmd[0] == "fn": cmd[1](b.live_page())
                        elif cmd[0] == "run":
                            sites, mx, dry, mot = cmd[1:]
                            n = run_jobs(b.live_page(), self.win.prof, self.win.crit, sites, mx, dry, True, self.win.worker_ask, mot)
                            br.finished.emit(n)
                    except Exception as e:
                        br.error.emit(f"{type(e).__name__}: {str(e)[:300]}")
        except Exception as e:
            br.error.emit(f"Browser could not start: {type(e).__name__}: {str(e)[:300]}")


class NativeHost(QWidget):
    """Plain native widget that hosts Chrome's window as a Win32 CHILD (SetParent) — Chrome keeps owning its window, Qt never destroys it."""
    def __init__(self):
        super().__init__(); self.setAttribute(Qt.WA_NativeWindow, True); self.setAttribute(Qt.WA_DontCreateNativeAncestors, True)
        self.setFocusPolicy(Qt.StrongFocus); self.hwnd = 0
    def attach(self, hwnd):
        import ctypes
        u = ctypes.windll.user32; self.hwnd = hwnd
        st = u.GetWindowLongW(hwnd, -16) & 0xFFFFFFFF
        mask = 0x80000000 | 0x00C00000 | 0x00040000 | 0x00080000 | 0x00020000 | 0x00010000     # popup, caption, frame, sysmenu, min/max
        new = (st & ~mask) | 0x40000000 | 0x10000000                                           # WS_CHILD | WS_VISIBLE
        u.SetParent(hwnd, int(self.winId())); u.SetWindowLongW(hwnd, -16, ctypes.c_long(new).value)
        self.fit()
    def fit(self):
        if not self.hwnd: return
        import ctypes
        d = self.devicePixelRatioF()
        ctypes.windll.user32.SetWindowPos(self.hwnd, 0, 0, 0, int(self.width() * d), int(self.height() * d), 0x0020 | 0x0040 | 0x0004)  # FRAMECHANGED|SHOWWINDOW|NOZORDER
    def resizeEvent(self, e): super().resizeEvent(e); self.fit()
    def release(self):
        if self.hwnd:
            import ctypes
            try: ctypes.windll.user32.SetParent(self.hwnd, 0)       # give the window back before the app/host is destroyed
            except Exception: pass
            self.hwnd = 0


class Bridge(QObject):
    log = Signal(str); ask = Signal(str, list, dict); pause = Signal(str); finished = Signal(int); error = Signal(str); ready = Signal(int); reopen = Signal()


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        profiles.migrate(); profiles.activate(profiles.active())
        self.setWindowTitle(f"Job Apply Bot v8 — {profiles.active()}"); self.resize(1700, 950)
        self.prof, self.crit, self.motiv = P.load_profile(), P.load_criteria(), load_motivation()
        self.bridge = Bridge(); self.bridge.log.connect(self.append_log); self.bridge.ask.connect(self.on_ask)
        self.bridge.pause.connect(self.on_pause); self.bridge.finished.connect(self.on_finished); self.bridge.error.connect(self.on_error); self.bridge.ready.connect(self.on_ready); self.bridge.reopen.connect(self.open_browser)
        self._answer, self._answer_ev, self._pause_ev = None, threading.Event(), threading.Event()
        self.bthread = None
        split = QSplitter(); split.setMinimumWidth(1250); split.setMinimumHeight(720)
        sa = QScrollArea(); sa.setWidgetResizable(True); sa.setWidget(split); sa.setFrameShape(QFrame.NoFrame); self.setCentralWidget(sa)
        self.left, self.center, self.right = self.build_left(), self.build_center(), self.build_right()
        for w_ in (self.left, self.center, self.right): split.addWidget(w_)
        split.setStretchFactor(1, 1); split.setSizes([400, 800, 480]); self.split = split; self.zoom_pct = 100
        self.dock_timer = QTimer(self); self.dock_timer.timeout.connect(self.dock_tick); self.dock_timer.start(120)
        B.HOOKS["log"] = lambda m: self.bridge.log.emit(str(m)); B.HOOKS["pause"] = self.worker_pause
        self.refresh_table(); self.refresh_cvs()
        QTimer.singleShot(500, self.open_browser)

    # ----------------------------------------------------------- LEFT: CVs, motivation, search
    def build_left(self):
        tabs = QTabWidget()
        # --- CV & message
        w = QWidget(); v = QVBoxLayout(w)
        v.addWidget(QLabel("<b>1. Drop your CV(s) here</b> (PDF / DOCX — any language)"))
        self.cv_table = DropTable(self.add_cvs); self.cv_table.setColumnCount(3)
        self.cv_table.setHorizontalHeaderLabels(["CV file", "Language", ""]); self.cv_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.cv_table.setMinimumHeight(150); v.addWidget(self.cv_table)
        b = QPushButton("Browse…"); b.clicked.connect(lambda: self.add_cvs(QFileDialog.getOpenFileNames(self, "CV", str(ROOT.parent), "CV (*.pdf *.docx)")[0])); v.addWidget(b)
        row = QHBoxLayout(); row.addWidget(QLabel("Default CV language:")); self.def_lang = QComboBox(); self.def_lang.addItems(LANGS.keys())
        self.def_lang.setCurrentText(self.prof.get("default_cv_lang", "en")); row.addWidget(self.def_lang); row.addStretch(); v.addLayout(row)
        v.addWidget(QLabel("<b>2. Default motivation message</b> — used when a form asks for a cover letter.<br>"
                           "<small>Placeholders: {title} {company} {full_name}. The bot picks the language of the job ad.</small>"))
        row = QHBoxLayout(); self.mot_lang = QComboBox(); self.mot_lang.addItems(LANGS.keys()); row.addWidget(QLabel("Language:")); row.addWidget(self.mot_lang); row.addStretch(); v.addLayout(row)
        self.mot_edit = QTextEdit(); v.addWidget(self.mot_edit, 1)
        self._mot_cur = "en"; self.mot_lang.currentTextChanged.connect(self.switch_mot); self.mot_edit.setPlainText(self.motiv.get("en", ""))
        sv = QPushButton("💾 Save CVs & messages"); sv.clicked.connect(self.save_left); v.addWidget(sv)
        tabs.addTab(w, "CV & message")
        # --- search
        s = QWidget(); f = QFormLayout(s)
        self.titles = QPlainTextEdit("\n".join(self.crit["titles"])); self.titles.setFixedHeight(120)
        self.locs = QPlainTextEdit("\n".join(self.crit["locations"])); self.locs.setFixedHeight(70)
        self.excl = QPlainTextEdit(", ".join(self.crit["exclude"])); self.excl.setFixedHeight(60)
        self.must = QLineEdit(", ".join(self.crit["must_have_any"])); self.days = QSpinBox(); self.days.setRange(1, 90); self.days.setValue(self.crit["posted_within_days"])
        self.maxrun = QSpinBox(); self.maxrun.setRange(1, 200); self.maxrun.setValue(30)
        self.easy = QCheckBox("Easy Apply / Indeed Apply only"); self.easy.setChecked(self.crit["easy_apply_only"])
        self.cb_li = QCheckBox("LinkedIn"); self.cb_li.setChecked("linkedin" in self.crit["sites"]); self.cb_in = QCheckBox("Indeed"); self.cb_in.setChecked("indeed" in self.crit["sites"])
        self.dry = QCheckBox("Dry-run (fill forms but do NOT submit)"); self.dry.setChecked(True)
        f.addRow("Job titles (1 per line)", self.titles); f.addRow("Locations (1 per line)", self.locs); f.addRow("Exclude words in title", self.excl)
        f.addRow("Must contain any (optional)", self.must); f.addRow("Posted within (days)", self.days); f.addRow("Max applications this run", self.maxrun)
        f.addRow(self.easy); r = QHBoxLayout(); r.addWidget(self.cb_li); r.addWidget(self.cb_in); f.addRow("Sites", r); f.addRow(self.dry)
        sv2 = QPushButton("💾 Save search settings"); sv2.clicked.connect(self.save_search); f.addRow(sv2)
        tabs.addTab(s, "Search criteria")
        return tabs

    def switch_mot(self, lang):
        self.motiv[self._mot_cur] = self.mot_edit.toPlainText(); self._mot_cur = lang; self.mot_edit.setPlainText(self.motiv.get(lang, ""))

    def add_cvs(self, paths):
        for p in paths:
            if not p.lower().endswith((".pdf", ".docx")): continue
            try: lang = P.detect_lang(cv_analyzer.read_text(p)[:4000])
            except Exception: lang = "en"
            self.prof["cv_files"][lang] = p
            if lang not in self.motiv: self.motiv[lang] = self.motiv.get("en", "")
        self.refresh_cvs(); self.save_left(silent=True)

    def refresh_cvs(self):
        self.cv_table.setRowCount(0)
        for lang, path in self.prof["cv_files"].items():
            if not path: continue
            r = self.cv_table.rowCount(); self.cv_table.insertRow(r)
            self.cv_table.setItem(r, 0, QTableWidgetItem(os.path.basename(path))); self.cv_table.item(r, 0).setToolTip(path)
            c = QComboBox(); c.addItems(LANGS.keys()); c.setCurrentText(lang); c.currentTextChanged.connect(lambda new, old=lang: self.change_cv_lang(old, new)); self.cv_table.setCellWidget(r, 1, c)
            x = QPushButton("✖"); x.clicked.connect(lambda _=False, l=lang: self.remove_cv(l)); self.cv_table.setCellWidget(r, 2, x)

    def change_cv_lang(self, old, new):
        if old != new: self.prof["cv_files"][new] = self.prof["cv_files"].get(old, ""); self.prof["cv_files"][old] = ""; QTimer.singleShot(0, self.refresh_cvs)

    def remove_cv(self, lang): self.prof["cv_files"][lang] = ""; QTimer.singleShot(0, self.refresh_cvs)

    def save_left(self, silent=False):
        self.motiv[self._mot_cur] = self.mot_edit.toPlainText(); self.prof["default_cv_lang"] = self.def_lang.currentText()
        P.save(P.PROFILE, self.prof); motiv_path().write_text(json.dumps(self.motiv, indent=2, ensure_ascii=False), encoding="utf-8")
        if not silent: self.append_log("💾 CVs and motivation messages saved")

    def save_search(self):
        self.crit.update(titles=[t.strip() for t in self.titles.toPlainText().splitlines() if t.strip()],
                         locations=[t.strip() for t in self.locs.toPlainText().splitlines() if t.strip()],
                         exclude=[t.strip() for t in self.excl.toPlainText().replace("\n", ",").split(",") if t.strip()],
                         must_have_any=[t.strip() for t in self.must.text().split(",") if t.strip()],
                         posted_within_days=self.days.value(), easy_apply_only=self.easy.isChecked(),
                         sites=[s for s, c in (("linkedin", self.cb_li), ("indeed", self.cb_in)) if c.isChecked()])
        P.save(P.CRITERIA, self.crit); self.append_log("💾 search settings saved")

    # ----------------------------------------------------------- CENTRE: toolbar, browser, log
    def build_center(self):
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(4, 4, 4, 4)
        prow = QHBoxLayout(); prow.addWidget(QLabel("<b>Profile:</b>")); self.pcombo = QComboBox(); self.pcombo.setMinimumWidth(170); prow.addWidget(self.pcombo)
        for txt, fn in (("＋ New", self.new_profile), ("⧉ Duplicate", lambda: self.new_profile(copy=True)), ("🗑 Delete", self.delete_profile)):
            pb_ = QPushButton(txt); pb_.clicked.connect(fn); prow.addWidget(pb_)
        prow.addStretch(); v.addLayout(prow); self.fill_profiles(); self.pcombo.activated.connect(lambda i: self.switch_profile(self.pcombo.itemText(i)))
        bar = QHBoxLayout()
        self.start_b = QPushButton("▶ Start applying"); self.start_b.setStyleSheet("background:#1b7f3b;color:white;font-weight:bold;padding:6px 14px")
        self.stop_b = QPushButton("⏹ Stop"); self.stop_b.setEnabled(False); self.stop_b.setStyleSheet("padding:6px 14px")
        self.start_b.clicked.connect(self.start); self.stop_b.clicked.connect(self.stop)
        bar.addWidget(self.start_b); bar.addWidget(self.stop_b)
        for txt, url in (("LinkedIn", "https://www.linkedin.com/login"), ("Indeed", "https://secure.indeed.com/auth?hl=fr_BE"), ("Google", "https://accounts.google.com/")):
            b = QPushButton(f"🔑 {txt}"); b.clicked.connect(lambda _=False, u=url: self.goto(u)); bar.addWidget(b)
        self.tl = QPushButton("◧ Left"); self.tl.setCheckable(True); self.tl.setChecked(True); self.tl.toggled.connect(lambda on: self.left.setVisible(on))
        self.tr = QPushButton("Right ◨"); self.tr.setCheckable(True); self.tr.setChecked(True); self.tr.toggled.connect(lambda on: self.right.setVisible(on))
        bar2 = QHBoxLayout(); bar2.addWidget(QLabel("View:")); bar2.addWidget(self.tl); bar2.addWidget(self.tr)
        zm = QPushButton("🔍−"); zp = QPushButton("🔍+"); self.zl = QLabel("100%"); zm.setFixedWidth(40); zp.setFixedWidth(40)
        zm.clicked.connect(lambda: self.zoom(-10)); zp.clicked.connect(lambda: self.zoom(+10)); self.zl.mouseDoubleClickEvent = lambda e: self.zoom(0)
        bar2.addSpacing(12); bar2.addWidget(QLabel("Zoom:")); bar2.addWidget(zm)
        self.zs = QSlider(Qt.Horizontal); self.zs.setRange(30, 250); self.zs.setValue(100); self.zs.setFixedWidth(110); self.zs.setToolTip("Zoom the web page")
        self.zs.valueChanged.connect(lambda v: self.zoom(v - self.zoom_pct)); bar2.addWidget(self.zs); bar2.addWidget(self.zl); bar2.addWidget(zp)
        bar2.addSpacing(12); bar2.addWidget(QLabel("Centre:"))
        self.ps = QSlider(Qt.Horizontal); self.ps.setRange(0, 100); self.ps.setValue(50); self.ps.setFixedWidth(130)
        self.ps.setToolTip("Slide to move the browser left / right (shifts the space between the left and right panels)"); self.ps.valueChanged.connect(self.slide_center)
        bar2.addWidget(QLabel("◀")); bar2.addWidget(self.ps); bar2.addWidget(QLabel("▶"))
        rb = QPushButton("🔄 Reopen browser"); rb.clicked.connect(self.reopen_browser); bar.addWidget(rb)
        bar.addStretch(); v.addLayout(bar); bar2.addSpacing(12)
        self.embed_cb = QComboBox(); self.embed_cb.addItems(["Inside (child)", "Docked (follows window)", "Separate window"]); self.embed_cb.setCurrentIndex(0 if sys.platform == "win32" else 2)
        self.embed_cb.setToolTip("How the browser is shown. Press 🔄 Reopen browser after changing."); self.embedded = False; bar2.addWidget(QLabel("Browser:")); bar2.addWidget(self.embed_cb); bar2.addStretch(); v.addLayout(bar2)
        self.host = QWidget(); self.host_l = QVBoxLayout(self.host); self.host_l.setContentsMargins(0, 0, 0, 0)
        self.host_info = QLabel("Starting browser…"); self.host_info.setAlignment(Qt.AlignCenter); self.host_l.addWidget(self.host_info)
        v.addWidget(self.host, 1)
        self.pause_box = QFrame(); self.pause_box.setStyleSheet("background:#fff3cd;border:1px solid #e0a800"); pl = QHBoxLayout(self.pause_box)
        self.pause_lbl = QLabel(); self.pause_lbl.setWordWrap(True); pb = QPushButton("✔ Done — continue"); pb.clicked.connect(self.resume); pl.addWidget(self.pause_lbl, 1); pl.addWidget(pb)
        self.pause_box.hide(); v.addWidget(self.pause_box)
        self.logw = QPlainTextEdit(); self.logw.setReadOnly(True); self.logw.setMaximumHeight(170); v.addWidget(self.logw)
        return w

    def append_log(self, m): self.logw.appendPlainText(m)

    def open_browser(self):
        self.bthread = BrowserThread(self); self.bthread.start()

    def slide_center(self, v):
        """Slider: distribute the free width between the left and right panels, so the browser slides left/right."""
        sz = self.split.sizes(); total = sum(sz); c = sz[1]; free = max(0, total - c)
        l = int(free * v / 100); self.split.setSizes([l, c, free - l])

    # ------------------------------------------------------------ profiles
    def fill_profiles(self):
        self.pcombo.blockSignals(True); self.pcombo.clear(); self.pcombo.addItems(profiles.list_profiles()); self.pcombo.setCurrentText(profiles.active()); self.pcombo.blockSignals(False)

    def busy(self):
        return not self.start_b.isEnabled()

    def new_profile(self, copy=False):
        from PySide6.QtWidgets import QInputDialog
        if self.busy(): return QMessageBox.information(self, "Job Apply Bot", "Stop the current run first.")
        name, ok = QInputDialog.getText(self, "New profile", "Name of the new profile (e.g. a person's name):")
        if not ok or not name.strip(): return
        src = profiles.active() if copy else None
        if not copy and profiles.list_profiles():
            r = QMessageBox.question(self, "New profile", "Start from a copy of the current profile's settings (criteria, answers, motivation)?\nNo = completely empty profile.")
            if r == QMessageBox.Yes: src = profiles.active()
        n = profiles.create(name, src); self.switch_profile(n)

    def delete_profile(self):
        cur = profiles.active()
        if len(profiles.list_profiles()) < 2: return QMessageBox.information(self, "Job Apply Bot", "You need at least one profile.")
        if self.busy(): return QMessageBox.information(self, "Job Apply Bot", "Stop the current run first.")
        if QMessageBox.question(self, "Delete profile", f"Delete profile '{cur}' with its CVs settings, answers, log and browser session?") != QMessageBox.Yes: return
        old = self.bthread
        if old and old.is_alive(): old.q.put(("quit",)); old.join(8)
        self.release_embed(); other = [p for p in profiles.list_profiles() if p != cur][0]
        profiles.activate(other); profiles.delete(cur); self.load_profile_into_ui(); self.open_browser()

    def switch_profile(self, name):
        if name == profiles.active(): return
        if self.busy():
            self.fill_profiles(); return QMessageBox.information(self, "Job Apply Bot", "Stop the current run before switching profile.")
        self.save_left(silent=True)
        old = self.bthread
        if old and old.is_alive(): old.q.put(("quit",)); old.join(8)       # each profile has its own browser session
        self.release_embed(); profiles.activate(name); self.load_profile_into_ui()
        self.host_info.setText("Starting browser…"); self.host_info.show(); self.open_browser()

    def load_profile_into_ui(self):
        self.prof, self.crit, self.motiv = P.load_profile(), P.load_criteria(), load_motivation()
        self.fill_profiles(); self.setWindowTitle(f"Job Apply Bot v8 — {profiles.active()}")
        self.titles.setPlainText("\n".join(self.crit["titles"])); self.locs.setPlainText("\n".join(self.crit["locations"]))
        self.excl.setPlainText(", ".join(self.crit["exclude"])); self.must.setText(", ".join(self.crit["must_have_any"]))
        self.days.setValue(self.crit["posted_within_days"]); self.easy.setChecked(self.crit["easy_apply_only"])
        self.cb_li.setChecked("linkedin" in self.crit["sites"]); self.cb_in.setChecked("indeed" in self.crit["sites"])
        self.def_lang.setCurrentText(self.prof.get("default_cv_lang", "en"))
        self._mot_cur = "en"; self.mot_lang.blockSignals(True); self.mot_lang.setCurrentText("en"); self.mot_lang.blockSignals(False); self.mot_edit.setPlainText(self.motiv.get("en", ""))
        self.refresh_cvs(); self.refresh_table(); self.logw.clear(); self.append_log(f"👤 profile '{profiles.active()}' loaded")

    def embed_mode(self): return self.embed_cb.currentIndex()      # 0 child, 1 docked, 2 separate

    def zoom(self, delta):
        self.zoom_pct = 100 if delta == 0 else max(30, min(250, self.zoom_pct + delta)); self.zl.setText(f"{self.zoom_pct}%")
        self.zs.blockSignals(True); self.zs.setValue(self.zoom_pct); self.zs.blockSignals(False)
        z = self.zoom_pct / 100
        self.goto_fn(lambda pg: pg.evaluate("z => { try { localStorage.setItem('jobbotZoom', z) } catch (e) {} document.documentElement.style.zoom = z }", str(z)))

    def goto_fn(self, fn):
        if self.bthread: self.bthread.q.put(("fn", fn))

    def dock_tick(self):
        """Docked mode: keep Chrome exactly over the centre panel; hide it when the app is minimised."""
        h = getattr(self, "dock_hwnd", 0)
        if not h or sys.platform != "win32": return
        try:
            import ctypes
            u = ctypes.windll.user32
            if self.isMinimized() or not self.center.isVisible(): u.ShowWindow(h, 0); return
            d = self.devicePixelRatioF(); pt = self.host.mapToGlobal(self.host.rect().topLeft())
            u.SetWindowPos(h, 0, int(pt.x() * d) - 7, int(pt.y() * d), int(self.host.width() * d) + 14, int(self.host.height() * d) + 7, 0x0010 | 0x0040)   # NOACTIVATE|SHOWWINDOW
        except Exception: pass

    def release_embed(self):
        self.dock_hwnd = 0
        c = getattr(self, "cont", None)
        if c is not None:
            c.release(); c.setParent(None); c.deleteLater(); self.cont = None
        self.embedded = False

    def reopen_browser(self):
        old = self.bthread
        if old and old.is_alive(): old.q.put(("quit",))
        self.release_embed()
        self.host_info.setText("Starting browser…"); self.host_info.show()
        def later():
            if old: old.join(8)
            self.bridge.reopen.emit()
        threading.Thread(target=later, daemon=True).start()

    def goto(self, url):
        if self.bthread: self.bthread.q.put(("goto", url))

    def on_ready(self, hwnd):
        self.append_log("🌐 browser ready")
        if hwnd and self.embed_mode() == 0:
            try:
                host = NativeHost(); self.host_l.addWidget(host); host.show(); QApplication.processEvents(); host.attach(hwnd)
                self.host_info.hide(); self.cont = host; self.embedded = True
                QTimer.singleShot(2500, lambda: self.bthread and self.bthread.q.put(("fn", lambda pg: pg.title())))   # health check: did Chrome survive?
                return
            except Exception as e:
                self.append_log(f"(child embedding failed: {e} — docking instead)")
                self.embed_cb.setCurrentIndex(1)
        if hwnd and self.embed_mode() == 1:
            try:
                import ctypes
                ctypes.windll.user32.SetWindowLongPtrW(hwnd, -8, int(self.winId()))      # owner = this window: stays on top of it, hides with it, no taskbar button
                self.dock_hwnd = hwnd; self.host_info.setText(""); self.host_info.hide(); self.dock_tick(); return
            except Exception as e:
                self.append_log(f"(docking failed: {e})")
        self.host_info.setText("Browser is open in its own window.\n(Choose 'Inside' or 'Docked' above and press 🔄 Reopen browser.)")

    # ----------------------------------------------------------- RIGHT: parameters & learned answers
    def build_right(self):
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(4, 4, 4, 4)
        v.addWidget(QLabel("<b>Automatic answers</b> — profile parameters, filters and learned questions"))
        self.ask_box = QFrame(); self.ask_box.setStyleSheet("background:#fde8e8;border:1px solid #d33"); al = QVBoxLayout(self.ask_box)
        self.ask_lbl = QLabel(); self.ask_lbl.setWordWrap(True); self.ask_in = QComboBox(); self.ask_in.setEditable(True)
        row = QHBoxLayout(); ok = QPushButton("Save answer & continue"); sk = QPushButton("Skip this job"); ok.clicked.connect(self.answer_ok); sk.clicked.connect(self.answer_skip)
        row.addWidget(ok); row.addWidget(sk); al.addWidget(QLabel("<b>❓ The bot needs your answer:</b>")); al.addWidget(self.ask_lbl); al.addWidget(self.ask_in); al.addLayout(row)
        self.ask_box.hide(); v.addWidget(self.ask_box)
        r = QHBoxLayout(); self.filter = QLineEdit(); self.filter.setPlaceholderText("🔍 filter…"); self.filter.textChanged.connect(self.apply_filter); r.addWidget(self.filter)
        add = QPushButton("＋ Add question"); add.clicked.connect(self.add_row); dele = QPushButton("🗑 Delete"); dele.clicked.connect(self.del_row); r.addWidget(add); r.addWidget(dele); v.addLayout(r)
        self.table = QTableWidget(); self.table.setColumnCount(3); self.table.setHorizontalHeaderLabels(["Question / parameter", "Answer", "Type"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch); self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setWordWrap(True); self.table.cellChanged.connect(self.cell_changed); v.addWidget(self.table, 1)
        v.addWidget(QLabel("<small>Blue = profile parameter · Black = learned answer · Red = unanswered (from the last runs). Edit any cell; it is saved instantly.</small>"))
        return w

    def refresh_table(self):
        self.table.blockSignals(True); self.table.setRowCount(0)
        def add(q, a, kind, color=None, editable_q=False):
            r = self.table.rowCount(); self.table.insertRow(r)
            it = QTableWidgetItem(q); it.setData(Qt.UserRole, kind)
            if not editable_q: it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            ans = QTableWidgetItem(a); tp = QTableWidgetItem(kind); tp.setFlags(tp.flags() & ~Qt.ItemIsEditable)
            if color:
                for x in (it, ans, tp): x.setForeground(QColor(color))
            self.table.setItem(r, 0, it); self.table.setItem(r, 1, ans); self.table.setItem(r, 2, tp)
        pend = self.pending_questions()
        ans_all = store.load_answers()
        for q in pend:
            if store.norm(q) not in ans_all: add(q, "", "unanswered", "#c00000", True)
        for k, label in PARAM_LABELS:
            val = self.prof.get(k, ""); add(label, ("yes" if val is True else "no" if val is False else str(val)), "profile:" + k, "#0b5cad")
        for lang, lvl in self.prof["languages"].items(): add(f"Language level — {lang}", lvl, "lang:" + lang, "#0b5cad")
        for sk, y in self.prof["years_by_skill"].items(): add(f"Years of experience with {sk}", str(y), "skill:" + sk, "#0b5cad")
        for q, a in ans_all.items(): add(q, str(a), "learned", None, True)
        self.table.blockSignals(False); self.apply_filter()

    def pending_questions(self):
        if not store.PENDING.exists(): return []
        seen = []
        for r in csv.DictReader(open(store.PENDING, encoding="utf-8-sig"), delimiter=";"):
            q = r["question"].split(" (")[0].strip()
            if q and q not in seen and len(q) < 200 and not q.lower().startswith(("could not find", "form error", "too many steps", "modal")): seen.append(q)
        return seen

    def apply_filter(self):
        t = self.filter.text().lower()
        for r in range(self.table.rowCount()):
            self.table.setRowHidden(r, bool(t) and t not in (self.table.item(r, 0).text() + self.table.item(r, 1).text()).lower())

    def cell_changed(self, r, c):
        kind = self.table.item(r, 0).data(Qt.UserRole); q = self.table.item(r, 0).text(); a = self.table.item(r, 1).text().strip()
        if kind.startswith("profile:"):
            k = kind.split(":", 1)[1]; cur = self.prof.get(k)
            if isinstance(cur, bool): self.prof[k] = a.lower() in ("yes", "y", "true", "oui", "1")
            elif isinstance(cur, int):
                try: self.prof[k] = int(a)
                except ValueError: pass
            else: self.prof[k] = a
            P.save(P.PROFILE, self.prof)
        elif kind.startswith("lang:"): self.prof["languages"][kind.split(":", 1)[1]] = a; P.save(P.PROFILE, self.prof)
        elif kind.startswith("skill:"):
            try: self.prof["years_by_skill"][kind.split(":", 1)[1]] = int(a); P.save(P.PROFILE, self.prof)
            except ValueError: pass
        else:  # learned / unanswered / new
            if q and a: store.save_answer(q, a)
            elif q and not a:
                d = store.load_answers(); d.pop(store.norm(q), None); store.ANSWERS.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")

    def add_row(self):
        q, ok = QInputDialogText.get(self, "New question / form label (e.g. 'Do you have a security clearance?')")
        if ok and q:
            a, ok2 = QInputDialogText.get(self, f"Answer for:\n{q}")
            if ok2: store.save_answer(q, a); self.refresh_table()

    def del_row(self):
        r = self.table.currentRow()
        if r < 0: return
        kind = self.table.item(r, 0).data(Qt.UserRole)
        if kind in ("learned", "unanswered"):
            d = store.load_answers(); d.pop(store.norm(self.table.item(r, 0).text()), None); store.ANSWERS.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8"); self.refresh_table()

    # ----------------------------------------------------------- bot worker
    def start(self):
        self.save_left(silent=True); self.save_search()
        if not self.crit["titles"]: return QMessageBox.warning(self, "Job Apply Bot", "Add at least one job title (Search criteria tab).")
        if not any(self.prof["cv_files"].values()): return QMessageBox.warning(self, "Job Apply Bot", "Drop at least one CV first.")
        if not self.bthread or not self.bthread.is_alive():
            return QMessageBox.information(self, "Job Apply Bot", "The browser is closed. Click 🔄 Reopen browser, wait for 'browser ready', then press Start again.")
        B.HOOKS["stop"] = False; self.start_b.setEnabled(False); self.stop_b.setEnabled(True)
        sites = self.crit["sites"]; mx = self.maxrun.value(); dry = self.dry.isChecked()
        mot = dict(self.motiv)
        self.append_log(f"▶ start — sites={sites} max={mx} dry_run={dry}")
        self.bthread.q.put(("run", sites, mx, dry, dict(self.motiv)))

    def stop(self): B.HOOKS["stop"] = True; self.append_log("⏹ stopping after the current job…"); self.resume(); self.answer_skip()
    def on_finished(self, n): self.append_log(f"✔ finished — {n} application(s)"); self.start_b.setEnabled(True); self.stop_b.setEnabled(False); self.refresh_table()
    def on_error(self, m):
        if self.embedded and "closed" in m.lower():
            self.append_log("⚠ Chrome closed while embedded as a child — switching to 'Docked' mode (browser follows this window).")
            self.embed_cb.setCurrentIndex(1); self.release_embed(); QTimer.singleShot(800, self.open_browser); return
        self.append_log("❌ " + m); self.start_b.setEnabled(True); self.stop_b.setEnabled(False); self.host_info.setText(m); self.host_info.show()

    # worker-thread side (blocks until the user answers in the GUI)
    def worker_ask(self, label, options, ctx):
        self._answer = None; self._answer_ev.clear(); self.bridge.ask.emit(label, list(options), dict(ctx))
        self._answer_ev.wait(); return self._answer
    def worker_pause(self, msg): self._pause_ev.clear(); self.bridge.pause.emit(msg); self._pause_ev.wait()

    # GUI-thread side
    def on_ask(self, label, options, ctx):
        self.ask_lbl.setText(f"<b>{label}</b><br><small>{ctx.get('title','')} @ {ctx.get('company','')}</small>")
        self.ask_in.clear(); self.ask_in.addItems([o for o in options if not o.lower().startswith(("select", "choisir", "sélection"))]); self.ask_in.setCurrentText("")
        self.ask_box.show(); self.ask_in.setFocus()
    def answer_ok(self):
        self._answer = self.ask_in.currentText().strip() or None; self.ask_box.hide(); self._answer_ev.set(); QTimer.singleShot(300, self.refresh_table)
    def answer_skip(self): self._answer = None; self.ask_box.hide(); self._answer_ev.set()
    def on_pause(self, msg): self.pause_lbl.setText("⏸ " + msg + "  (do it in the browser, then click Continue)"); self.pause_box.show()
    def resume(self): self.pause_box.hide(); self._pause_ev.set()


class DropTable(QTableWidget):
    def __init__(self, cb):
        super().__init__(); self.cb = cb; self.setAcceptDrops(True); self.viewport().setAcceptDrops(True); self.setDragDropMode(QAbstractItemView.DropOnly)
        self.setStyleSheet("QTableWidget{border:2px dashed #888;background:#fafafa}")
    def dragEnterEvent(self, e): e.acceptProposedAction() if e.mimeData().hasUrls() else None
    def dragMoveEvent(self, e): e.acceptProposedAction()
    def dropEvent(self, e): self.cb([u.toLocalFile() for u in e.mimeData().urls()]); e.acceptProposedAction()


class QInputDialogText:
    @staticmethod
    def get(parent, label):
        from PySide6.QtWidgets import QInputDialog
        return QInputDialog.getMultiLineText(parent, "Job Apply Bot", label)


def _closing(w):
    w.release_embed()
    if w.bthread: w.bthread.q.put(("quit",)); w.bthread.join(5)

if __name__ == "__main__":
    app = QApplication(sys.argv); w = Window(); w.show(); app.aboutToQuit.connect(lambda: _closing(w)); sys.exit(app.exec())
