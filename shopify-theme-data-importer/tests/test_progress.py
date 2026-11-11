"""Har mode ke har step ka live progress aata hai? (UI isi par chalti hai)"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.jobs import Job                                   # noqa: E402
from app.core.shopify import Store                              # noqa: E402
from app.modes import blog, demo, migrate, woo                  # noqa: E402
from tests.fakes import FakeWeb                                 # noqa: E402
from tests.test_migrate import cdn_site, make_dest, make_source  # noqa: E402
from tests.test_other_modes import dest_store, demo_site, generic_site, woo_site, wp_site  # noqa: E402


class RecordingJob(Job):
    def __init__(self, *a):
        super().__init__(*a)
        self.trace = []
        self.sleep = lambda s: None

    def progress(self, current, total=None, detail=None):
        if self._current:
            self.trace.append((self._current["key"], "progress", current, total, detail))
        super().progress(current, total, detail)

    def detail(self, text):
        if self._current:
            self.trace.append((self._current["key"], "detail", None, None, text))
        super().detail(text)

    def log(self, msg, level="info"):
        if self._current:
            self.trace.append((self._current["key"], "log", None, None, msg))
        super().log(msg, level)


def check(job, require_counted=()):
    ran = [s["key"] for s in job.steps if s["status"] not in ("skipped", "pending")]
    assert ran, "koi step nahi chala"
    for key in ran:
        live = [t for t in job.trace if t[0] == key and t[1] in ("progress", "detail")]
        logs = [t for t in job.trace if t[0] == key and t[1] == "log"]
        assert live, f"step '{key}' ne koi live progress nahi bheja"
        assert logs, f"step '{key}' ne koi log line nahi likhi"
    for key in require_counted:
        counted = [t for t in job.trace if t[0] == key and t[1] == "progress" and t[3]]
        assert counted, f"step '{key}' me 'x/total' counter nahi aaya"
        assert counted[-1][2] == counted[-1][3], f"step '{key}' ka counter poora nahi hua: {counted[-1]}"
    assert all(s["status"] == "done" for s in job.steps if s["key"] in ran), [(s["key"], s["status"]) for s in job.steps]


def stores(web, src_dst):
    return [Store(web, s.domain, s.token, s.domain, None) for s in src_dst]


def test_progress_migrate(tmp_path):
    web = FakeWeb()
    web.site("cdn.shopify.com", cdn_site)
    s, d = web.store(make_source()), web.store(make_dest())
    job = RecordingJob("migrate", "t", migrate.STEPS)
    src, dst = (Store(web, x.domain, x.token, x.domain, job) for x in (s, d))
    src.write_pause = dst.write_pause = 0
    migrate.run(job, {"session": web, "source": src, "dest": dst, "out_dir": str(tmp_path)})
    check(job, require_counted=["files", "products", "collections", "blogs", "pages", "menus", "shopmeta", "theme", "verify"])


def run_mode(mode, web, d, params, steps):
    job = RecordingJob(mode.__name__, "t", steps)
    st = Store(web, d.domain, d.token, "DEST", job)
    st.write_pause = 0
    mode.run(job, dict(params, dest=st, web_session=web))
    return job


def test_progress_demo():
    web = FakeWeb()
    web.site("kitty-demo.myshopify.com", demo_site())
    d = dest_store(web)
    job = run_mode(demo, web, d, {"demo_url": "kitty-demo.myshopify.com", "password": "1"}, demo.STEPS)
    check(job, require_counted=["files", "products", "collections", "blogs", "pages", "verify"])


def test_progress_woo():
    web = FakeWeb()
    web.site("wooshop.com", woo_site())
    d = dest_store(web)
    job = run_mode(woo, web, d, {"wc_url": "wooshop.com", "ck": "ck_1", "cs": "cs_1", "include_drafts": True}, woo.STEPS)
    check(job, require_counted=["products", "collections", "redirects"])
    job = run_mode(woo, web, d, {"wc_url": "wooshop.com", "ck": "ck_1", "cs": "cs_1", "verify_only": True}, woo.VERIFY_STEPS)
    check(job, require_counted=["verify"])


def test_progress_blog():
    web = FakeWeb()
    web.site("wpblog.com", wp_site)
    web.site("genericblog.com", generic_site)
    d = dest_store(web)
    job = run_mode(blog, web, d, {"listing_url": "wpblog.com"}, blog.STEPS)
    check(job, require_counted=["images", "import"])
    job = run_mode(blog, web, d, {"listing_url": "genericblog.com/blog", "rehost_images": False}, blog.STEPS)
    check(job, require_counted=["scrape", "import"])
