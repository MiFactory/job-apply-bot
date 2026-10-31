"""Weekly schedule + automatic retry after a LinkedIn limit.

* Pick the weekdays and an hour: the bot starts a run at that time (the app / `main.py schedule` must be running).
* If LinkedIn blocks applying (daily limit), the bot waits and starts again by itself every N minutes (default 5)
  until the restriction is lifted. The probe is simply a normal run: it stops again at once while the limit is active.
* If YOUR own daily cap (max_applications_per_day) is reached, it does not retry until the next scheduled day.
Settings live in data/profiles/<name>/schedule.json (one schedule per profile).
"""
import json, datetime as dt
from . import profile as P

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DEFAULT_SCHEDULE = {
    "enabled": False,
    "days": [0, 1, 2, 3, 4],        # 0 = Monday
    "time": "09:00",                # HH:MM, local time
    "retry_minutes": 5,             # how often to test again after a LinkedIn limit
    "retry_max_hours": 48,          # give up retrying after this long (then wait for the next scheduled day)
    "max_per_run": 30,
}


def path(): return P.PROFILE.parent / "schedule.json"


def load():
    d = json.loads(json.dumps(DEFAULT_SCHEDULE)); d.update(P.read_json(path(), {}))
    try: _hm(d["time"])
    except Exception: d["time"] = DEFAULT_SCHEDULE["time"]
    try: d["retry_minutes"] = max(1, int(d["retry_minutes"]))
    except Exception: d["retry_minutes"] = 5
    try: d["retry_max_hours"] = max(1, float(d["retry_max_hours"]))
    except Exception: d["retry_max_hours"] = 48
    d["days"] = [int(x) for x in d["days"] if str(x).isdigit() and 0 <= int(x) <= 6] if isinstance(d["days"], list) else DEFAULT_SCHEDULE["days"]
    return d


def save(s): path().write_text(json.dumps(s, indent=2), encoding="utf-8")


def parse_days(txt):
    """'mon-fri', 'mon,wed,fri', 'all' → [0..6]"""
    txt = (txt or "").lower().replace(" ", "")
    if txt in ("all", "daily", "everyday", "*"): return list(range(7))
    names = [n.lower() for n in DAY_NAMES]; out = set()
    for part in txt.split(","):
        if "-" in part:
            a, b = part.split("-", 1); i, j = names.index(a[:3]), names.index(b[:3])
            out.update(range(i, j + 1) if i <= j else list(range(i, 7)) + list(range(0, j + 1)))
        elif part: out.add(names.index(part[:3]))
    return sorted(out)


def _hm(s):
    """'HH:MM' → (h, m); anything invalid falls back to 09:00 instead of crashing."""
    try:
        h, m = str(s).strip().split(":")[:2]; h, m = int(h), int(m)
        if 0 <= h <= 23 and 0 <= m <= 59: return h, m
    except Exception: pass
    return 9, 0


def next_start(s, now=None):
    """First allowed day/time strictly after `now`, or None when no day is selected."""
    now = now or dt.datetime.now()
    if not s["days"]: return None
    h, m = _hm(s["time"])
    for add in range(0, 8):
        cand = (now + dt.timedelta(days=add)).replace(hour=h, minute=m, second=0, microsecond=0)
        if cand > now and cand.weekday() in s["days"]: return cand
    return None


class Scheduler:
    """Tiny state machine. Call due() every few seconds; call on_result() when a run ends."""
    def __init__(self, s=None, now=None):
        self.s = s or load(); self.state = "idle"; self.retry_at = None; self.retry_since = None; self.next_at = None
        self.reset(now)

    def reset(self, now=None, s=None):
        if s is not None: self.s = s
        self.state, self.retry_at, self.retry_since = "idle", None, None
        self.next_at = next_start(self.s, now) if self.s["enabled"] else None

    def due(self, now=None):
        now = now or dt.datetime.now()
        if not self.s["enabled"]: return False
        if self.state == "retry": return now >= self.retry_at
        return self.next_at is not None and now >= self.next_at

    def on_result(self, result, now=None):
        """result: 'limit' (LinkedIn limit hit) | 'quota' (own daily cap) | 'finished' | 'stopped'."""
        now = now or dt.datetime.now()
        if not self.s["enabled"]: return
        if result == "limit":
            if self.state != "retry": self.retry_since = now
            if now - self.retry_since > dt.timedelta(hours=self.s["retry_max_hours"]):
                self.reset(now); return                              # gave up → next scheduled day
            self.state = "retry"; self.retry_at = now + dt.timedelta(minutes=max(1, int(self.s["retry_minutes"])))
        elif result == "stopped":
            self.state = "idle"; self.retry_at = None                 # user pressed Stop: wait for next slot, never auto-restart
            self.next_at = next_start(self.s, now)
        else:                                                         # quota / finished → next allowed day
            self.reset(now)

    def status(self, now=None):
        now = now or dt.datetime.now()
        if not self.s["enabled"]: return "Schedule off"
        if self.state == "retry":
            return f"⏳ LinkedIn limit — testing again at {self.retry_at:%H:%M} (every {self.s['retry_minutes']} min)"
        if self.next_at is None: return "No day selected"
        return f"Next run: {self.next_at:%a %d %b %H:%M}"
