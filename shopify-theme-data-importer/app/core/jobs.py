"""Background jobs with live progress, steps, counters and cancel support."""
import threading
import time
import traceback
import uuid


class Cancelled(Exception):
    """User ne Stop dabaya."""


class Job:
    def __init__(self, mode, title, steps):
        self.id = uuid.uuid4().hex[:12]
        self.mode = mode
        self.title = title
        self.status = "running"          # running | done | warning | failed | cancelled
        self.started = time.time()
        self.finished = None
        self.events = []
        self.notes = []
        self.stats = {}
        self.links = []                  # [{label, url}] report ke buttons
        self.steps = [{"key": k, "label": label, "status": "pending", "current": 0,
                       "total": 0, "detail": ""} for k, label in steps]
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._current = None

    # ------------------------------------------------------------- logging
    def log(self, msg, level="info"):
        with self._lock:
            self.events.append({"i": len(self.events), "t": round(time.time(), 2),
                                "level": level, "msg": str(msg)})

    def ok(self, msg):
        self.log(msg, "ok")

    def warn(self, msg):
        self.log(msg, "warn")

    def error(self, msg):
        self.log(msg, "error")

    def note(self, msg):
        """Report me 'manually dekhne wali cheez' + warning line."""
        with self._lock:
            if len(self.notes) < 500:
                self.notes.append(str(msg))
        self.warn(msg)

    def add(self, section, field, n=1):
        with self._lock:
            sec = self.stats.setdefault(section, {})
            sec[field] = sec.get(field, 0) + n

    def link(self, label, url):
        self.links.append({"label": label, "url": url})

    # ------------------------------------------------------------- steps
    def _step(self, key):
        for s in self.steps:
            if s["key"] == key:
                return s
        s = {"key": key, "label": key, "status": "pending", "current": 0, "total": 0, "detail": ""}
        self.steps.append(s)
        return s

    def skip_step(self, key, why="select nahi kiya"):
        s = self._step(key)
        s["status"], s["detail"] = "skipped", why

    def step(self, key):
        return _StepContext(self, key)

    def detail(self, text):
        """Sirf current step ki live line badlo (counter nahi)."""
        if self._current is not None:
            self._current["detail"] = str(text)[:140]

    def progress(self, current, total=None, detail=None):
        s = self._current
        if s is None:
            return
        s["current"] = current
        if total is not None:
            s["total"] = total
        if detail is not None:
            s["detail"] = str(detail)[:140]

    # ------------------------------------------------------------- cancel
    def cancel(self):
        self._cancel.set()
        self.warn("Stop request mili -- current kaam khatam kar ke ruk raha hoon...")

    @property
    def cancelled(self):
        return self._cancel.is_set()

    def check(self):
        if self._cancel.is_set():
            raise Cancelled()

    def sleep(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            self.check()
            time.sleep(min(0.2, max(0.0, end - time.time())))

    # ------------------------------------------------------------- snapshot
    def snapshot(self, since=0):
        with self._lock:
            events = self.events[since:]
            total_failed = sum(v.get("failed", 0) for v in self.stats.values())
            return {
                "id": self.id, "mode": self.mode, "title": self.title, "status": self.status,
                "started": self.started, "finished": self.finished,
                "elapsed": round((self.finished or time.time()) - self.started, 1),
                "events": events, "next": since + len(events),
                "steps": [dict(s) for s in self.steps],
                "stats": {k: dict(v) for k, v in self.stats.items()},
                "notes": list(self.notes), "failed": total_failed, "links": list(self.links),
            }

    def log_text(self):
        lines = [f"{self.title}  ({time.strftime('%Y-%m-%d %H:%M', time.localtime(self.started))})", ""]
        for e in self.events:
            stamp = time.strftime("%H:%M:%S", time.localtime(e["t"]))
            lines.append(f"[{stamp}] {e['level'].upper():5} {e['msg']}")
        if self.stats:
            lines += ["", "SUMMARY"]
            for sec, fields in self.stats.items():
                lines.append(f"  {sec}: " + ", ".join(f"{k}={v}" for k, v in fields.items()))
        if self.notes:
            lines += ["", "MANUALLY DEKHNE WALI CHEEZEIN"] + [f"  - {n}" for n in self.notes]
        return "\n".join(lines)


class _StepContext:
    def __init__(self, job, key):
        self.job, self.key = job, key

    def __enter__(self):
        s = self.job._step(self.key)
        s["status"] = "running"
        self.job._current = s
        self.job.log(f"━━ {s['label']} ━━", "step")
        return s

    def __exit__(self, exc_type, exc, tb):
        s = self.job._current
        self.job._current = None
        if exc_type is None:
            s["status"] = "done"
            return False
        if issubclass(exc_type, Cancelled):
            s["status"] = "cancelled"
            return False
        s["status"] = "failed"
        if isinstance(exc, PermissionError):
            self.job.note(f"{s['label']}: permission/scope masla -- {exc}")
        else:
            self.job.note(f"{s['label']} step me error: {exc}")
            self.job.log("".join(traceback.format_exception(exc_type, exc, tb))[-1500:], "debug")
        return True          # agla step chalta rahe


class JobManager:
    def __init__(self):
        self.jobs = {}
        self._lock = threading.Lock()

    def start(self, mode, title, steps, fn, params):
        job = Job(mode, title, steps)
        with self._lock:
            self.jobs[job.id] = job
        threading.Thread(target=self._run, args=(job, fn, params), daemon=True).start()
        return job

    def _run(self, job, fn, params):
        try:
            fn(job, params)
            failed = sum(v.get("failed", 0) for v in job.stats.values())
            step_failed = any(s["status"] == "failed" for s in job.steps)
            job.status = "warning" if (failed or step_failed or job.notes) else "done"
            job.ok("Kaam mukammal ho gaya." if job.status == "done"
                   else "Kaam khatam -- kuch cheezein report me dekh lo.")
        except Cancelled:
            job.status = "cancelled"
            for s in job.steps:
                if s["status"] in ("pending", "running"):
                    s["status"] = "cancelled"
            job.warn("Aap ke kehne par kaam rok diya gaya.")
        except Exception as e:  # noqa: BLE001 -- ek ghalti poori app na giraye
            job.status = "failed"
            job.error(f"Ghalti: {e}")
            job.log(traceback.format_exc()[-2000:], "debug")
        finally:
            job.finished = time.time()

    def get(self, job_id):
        return self.jobs.get(job_id)

    def running(self):
        return [j for j in self.jobs.values() if j.status == "running"]
