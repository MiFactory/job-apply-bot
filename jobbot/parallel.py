"""Several applications at the same time (setting «parallel_applications», 1 = one by one, max 10).

Each job gets its own browser tab and its own *task*: a generator that does one small action (open the page, fill a form
step, press Next…) and then yields the number of milliseconds it wants to wait. run_tasks() gives every tab its turn while
the others are waiting, so the page loads and the pauses of all the tabs overlap instead of adding up.
Playwright's sync API must stay on ONE thread: this is cooperative scheduling, not threads."""
import time
from .browser import HOOKS, should_stop

MAX_PARALLEL = 10
WAIT_CAP_MS = None          # tests only: cap every pause (the human-like delays are not needed against a local fake)


def clamp(value):
    """«parallel_applications» as an int between 1 and MAX_PARALLEL (garbage / missing = 1 = one by one)."""
    try: n = int(value)
    except Exception: return 1
    return max(1, min(MAX_PARALLEL, n))


def drive(page, gen):
    """Run a task generator alone on its page (the classic one-by-one mode); returns the task's result."""
    try:
        while True: page.wait_for_timeout(next(gen))
    except StopIteration as s:
        return s.value


def run_tasks(main_page, jobs, make_task, on_abort=None, is_fatal=None):
    """Open one tab per job and advance all the tasks in turn.
    make_task(page, job, tab_no) -> generator yielding milliseconds and returning a result.
    is_fatal(result) -> True stops the other tabs at once (LinkedIn limit). on_abort(page) cleans a tab stopped half-way.
    Returns [(job, result)]: result is None for a tab stopped before the end, an Exception when its task crashed."""
    ctx = main_page.context; slots = []; out = []
    for k, job in enumerate(jobs):
        try: pg = ctx.new_page()
        except Exception as e: out.append((job, e)); continue
        slots.append({"page": pg, "job": job, "gen": make_task(pg, job, k + 1), "wake": 0.0})

    def finish(s, result):
        out.append((s["job"], result)); slots.remove(s)
        try: s["page"].close()
        except Exception: pass

    def abort_all():
        for s in list(slots):
            try: s["gen"].close()
            except Exception: pass
            if on_abort:
                try: on_abort(s["page"])
                except Exception: pass
            finish(s, None)

    while slots:
        if should_stop(): abort_all(); break
        ran = False
        for s in list(slots):
            if s["wake"] > time.monotonic(): continue
            ran = True
            try:
                try: s["page"].bring_to_front()             # a background tab is throttled by Chrome and may not render its form
                except Exception: pass
                ms = next(s["gen"])
                if WAIT_CAP_MS is not None: ms = min(ms, WAIT_CAP_MS)
                s["wake"] = time.monotonic() + max(0, ms) / 1000.0
            except StopIteration as stop:
                finish(s, stop.value)
                if is_fatal and is_fatal(stop.value): abort_all(); break
            except Exception as e:
                finish(s, e)
            if should_stop(): break
        if slots and not ran:
            nap = max(0.02, min(0.25, min(s["wake"] for s in slots) - time.monotonic()))
            try: main_page.wait_for_timeout(nap * 1000)      # keeps Playwright's event loop running while every tab waits
            except Exception: time.sleep(nap)
    return out
