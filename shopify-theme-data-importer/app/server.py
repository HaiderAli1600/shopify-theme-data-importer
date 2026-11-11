"""Local HTTP server: UI files + JSON API + OAuth callback. Sirf 127.0.0.1 par."""
import json
import mimetypes
import os
import secrets
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

from .core import auth
from .core.jobs import JobManager
from .core.shopify import Store, make_session, normalize_domain
from .modes import blog, demo, migrate, woo
from .version import API_VERSION, APP_AUTHOR, APP_NAME, APP_VERSION, OAUTH_PORT

SESSION_FACTORY = make_session          # tests yahan fake laga sakte hain
OPEN_URL = webbrowser.open


def open_local(path):
    """Folder / file Windows Explorer (ya Mac Finder / Linux file manager) me kholo."""
    path = str(path)
    if os.name == "nt":
        os.startfile(path)                  # noqa: S606 -- sirf output folder ke andar ka path
    elif sys.platform == "darwin":
        import subprocess
        subprocess.Popen(["open", path])
    else:
        import subprocess
        try:
            subprocess.Popen(["xdg-open", path])
        except OSError:
            webbrowser.open(Path(path).as_uri())


OPEN_LOCAL = open_local


def resource_dir():
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "app" / "ui"


def data_dir():
    root = os.environ.get("LOCALAPPDATA") or os.path.join(Path.home(), ".local", "share")
    p = Path(root) / "ShopifyThemeDataImporter"
    p.mkdir(parents=True, exist_ok=True)
    return p


def output_dir():
    docs = Path.home() / "Documents"
    p = (docs if docs.exists() else Path.home()) / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


class ApiError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


class App:
    def __init__(self, port):
        self.port = port
        self.key = secrets.token_urlsafe(24)
        self.jobs = JobManager()
        self.oauth = auth.OAuthFlows()
        self.last_ping = time.time()
        self.bye_at = None
        self.ever_pinged = False
        self.settings_path = data_dir() / "settings.json"

    # ------------------------------------------------------------- helpers
    @property
    def redirect_uri(self):
        return f"http://localhost:{OAUTH_PORT}/oauth/callback"

    def settings(self):
        try:
            return json.loads(self.settings_path.read_text("utf-8"))
        except (OSError, ValueError):
            return {}

    def save_settings(self, data):
        allowed = {k: v for k, v in (data or {}).items() if k in ("domains", "last", "ui") and isinstance(v, (dict, list))}
        cur = self.settings()
        cur.update(allowed)
        self.settings_path.write_text(json.dumps(cur, indent=2), "utf-8")
        return cur

    def build_store(self, session, conn, label, job=None):
        if not conn or not conn.get("domain"):
            raise ApiError(f"{label}: store domain likho")
        domain = normalize_domain(conn["domain"])
        method = conn.get("method", "token")
        refresh = None
        if method == "cc":
            res = auth.client_credentials(session, domain, conn.get("client_id", ""), conn.get("client_secret", ""))
            token = res["token"]
            refresh = auth.make_refresher(session, domain, conn["client_id"], conn["client_secret"])
        else:
            token = (conn.get("token") or "").strip()
            if not token:
                raise ApiError(f"{label}: access token chahiye (pehle 'Connect & Test' karo)")
        st = Store(session, domain, token, label, job, refresh)
        return st

    # ------------------------------------------------------------- API
    def api(self, path, body):
        b = body or {}
        if path == "/api/info":
            return {"name": APP_NAME, "version": APP_VERSION, "author": APP_AUTHOR, "api_version": API_VERSION,
                    "redirect_uri": self.redirect_uri, "oauth_port_ok": self.port == OAUTH_PORT,
                    "scopes": {k: {"required": v[0], "optional": v[1]} for k, v in auth.SCOPES.items()},
                    "recommended": auth.ALL_RECOMMENDED, "source_recommended": auth.SOURCE_RECOMMENDED,
                    "output_dir": str(output_dir()), "settings": self.settings()}
        if path == "/api/ping":
            self.last_ping, self.ever_pinged, self.bye_at = time.time(), True, None
            return {"ok": True, "running": len(self.jobs.running())}
        if path == "/api/bye":
            self.bye_at = time.time()
            return {"ok": True}
        if path == "/api/settings":
            return self.save_settings(b)
        if path == "/api/connect":
            return self.connect(b)
        if path == "/api/oauth/start":
            scopes = b.get("scopes") or auth.ALL_RECOMMENDED
            redirect = (b.get("redirect_uri") or self.redirect_uri).strip()
            state, url = self.oauth.start(b.get("domain"), b.get("client_id"), b.get("client_secret"), scopes, redirect)
            if b.get("open", True):
                OPEN_URL(url)
            return {"state": state, "url": url, "redirect_uri": redirect}
        if path == "/api/oauth/status":
            st = self.oauth.status(b.get("state", ""))
            if st.get("status") == "done" and st.get("token"):
                flow = self.oauth.flows[b["state"]]
                st["verify"] = auth.verify(SESSION_FACTORY(), flow["domain"], st["token"], b.get("role"))
            return st
        if path == "/api/oauth/manual":
            params = dict(parse_qsl(urlparse(b.get("url", "")).query))
            flow = self.oauth.complete(SESSION_FACTORY(), params)
            return {"status": "done", "token": flow["result"]["token"],
                    "verify": auth.verify(SESSION_FACTORY(), flow["domain"], flow["result"]["token"], b.get("role"))}
        if path == "/api/demo/test":
            s = SESSION_FACTORY()
            ok, msg = demo.login(s, demo.clean_demo_url(b.get("demo_url", "")), b.get("password", ""))
            count = None
            if ok:
                count = len(demo.storefront_json(s, demo.clean_demo_url(b["demo_url"]), "/products.json", "products", None, 4))
            return {"ok": ok, "message": msg, "products": count}
        if path == "/api/woo/test":
            w = woo.Woo(SESSION_FACTORY(), b.get("wc_url", ""), b.get("ck", ""), b.get("cs", ""))
            ok, msg = w.connect()
            total = None
            if ok:
                r = w.get("products", {"per_page": 1})
                total = r.headers.get("X-WP-Total") if r is not None else None
            return {"ok": ok, "message": msg, "products": total}
        if path == "/api/blog/test":
            return self.blog_test(b)
        if path == "/api/run":
            return self.run(b)
        if path == "/api/job":
            job = self.jobs.get(b.get("id"))
            if not job:
                raise ApiError("Job nahi mili", 404)
            return job.snapshot(int(b.get("since") or 0))
        if path == "/api/job/cancel":
            job = self.jobs.get(b.get("id"))
            if job:
                job.cancel()
            return {"ok": True}
        if path == "/api/job/save":
            job = self.jobs.get(b.get("id"))
            if not job:
                raise ApiError("Job nahi mili", 404)
            logs = output_dir() / "logs"
            logs.mkdir(exist_ok=True)
            f = logs / f"{job.mode}-{time.strftime('%Y%m%d-%H%M%S', time.localtime(job.started))}.txt"
            f.write_text(job.log_text(), "utf-8")
            if b.get("reveal", True):
                OPEN_LOCAL(f)
            return {"path": str(f)}
        if path == "/api/open":
            url = b.get("url", "")
            if url == "output":
                OPEN_LOCAL(output_dir())
                return {"ok": True}
            if url.startswith("local:") or url.startswith("file:"):
                target = self._local_target(url)
                if target is None:
                    raise ApiError("Yeh folder tool ke Output folder ke bahar hai -- nahi khul sakta")
                if not target.exists():
                    raise ApiError(f"Folder nahi mila: {target}")
                OPEN_LOCAL(target)
                return {"ok": True, "path": str(target)}
            if url.startswith(("https://", "http://")):
                OPEN_URL(url)
                return {"ok": True}
            raise ApiError("Yeh link nahi khul sakta")
        raise ApiError("Unknown API", 404)

    @staticmethod
    def _local_target(url):
        """'local:C:\\...\\folder' ya 'file:///C:/...' -> Path, sirf agar Output folder ke andar ho."""
        from urllib.parse import unquote
        from urllib.request import url2pathname
        try:
            if url.startswith("local:"):
                target = Path(url[6:])
            else:
                u = urlparse(url)
                raw = unquote(u.path)
                if u.netloc and len(u.netloc) == 2 and u.netloc[1] == ":":      # file://C:\... (purana format)
                    raw = u.netloc + raw
                target = Path(url2pathname(raw) if not raw[1:3] == ":\\" else raw)
            target = target.resolve()
        except (OSError, ValueError, IndexError):
            return None
        root = output_dir().resolve()
        return target if (target == root or root in target.parents) else None

    def connect(self, b):
        session = SESSION_FACTORY()
        domain = normalize_domain(b.get("domain", ""))
        if not domain or "." not in domain:
            raise ApiError("Sahi store domain likho (jaise my-store.myshopify.com)")
        method = b.get("method", "token")
        extra = {}
        if method == "cc":
            res = auth.client_credentials(session, domain, b.get("client_id", ""), b.get("client_secret", ""))
            token = res["token"]
            extra = {"expires_in": res.get("expires_in")}
        else:
            token = (b.get("token") or "").strip()
            if not token:
                raise ApiError("Access token likho (shpat_... se shuru hota hai)")
        out = auth.verify(session, domain, token, b.get("role"))
        out.update(extra, method=method, domain=domain)
        return out

    def blog_test(self, b):
        s = SESSION_FACTORY()
        url = blog.clean_url(b.get("listing_url", ""))

        class _J:  # chhota sa job jo kuch log nahi karta
            def check(self): pass
            def sleep(self, s): pass
            def progress(self, *a, **k): pass
            def log(self, *a, **k): pass
            warn = ok = note = log
        posts = blog.wp_api(s, url, _J())
        if posts is not None:
            return {"ok": True, "kind": "wordpress", "count": len(posts),
                    "sample": [p["title"] for p in posts[:5]],
                    "message": f"WordPress site -- {len(posts)} posts API se milenge"}
        links = blog.discover_links(s, url, _J(), max_pages=2, max_links=60)
        return {"ok": bool(links), "kind": "generic", "count": len(links), "sample": links[:5],
                "message": (f"Pehle 2 listing pages par {len(links)} posts mile (poore run me pagination + sitemap se aur)"
                            if links else "Is URL par posts nahi mile -- blog ki listing page ka URL do")}

    def run(self, b):
        mode = b.get("mode")
        session = SESSION_FACTORY()
        web_session = SESSION_FACTORY()
        if mode == "migrate":
            p = {"session": session, "steps": b.get("steps"), "options": b.get("options") or {},
                 "out_dir": str(output_dir() / "theme-exports")}
            title, steps, fn = "Store → Store Migration", migrate.STEPS, migrate.run
        elif mode == "demo":
            p = {"web_session": web_session, "demo_url": b.get("demo_url"), "password": b.get("password", ""),
                 "steps": b.get("steps"), "image_scope": b.get("image_scope", "all")}
            title, steps, fn = "Theme Demo → Store", demo.STEPS, demo.run
        elif mode == "woo":
            p = {"web_session": web_session, "wc_url": b.get("wc_url"), "ck": b.get("ck", ""), "cs": b.get("cs", ""),
                 "steps": b.get("steps"), "verify_only": b.get("verify_only"), "include_drafts": b.get("include_drafts"),
                 "options": b.get("options") or {}}
            title = "WooCommerce → Shopify"
            steps, fn = (woo.VERIFY_STEPS if b.get("verify_only") else woo.STEPS), woo.run
        elif mode == "blog":
            p = {"web_session": web_session, "listing_url": b.get("listing_url"), "blog_title": b.get("blog_title"),
                 "rehost_images": b.get("rehost_images", True), "keep_dates": b.get("keep_dates", True),
                 "max_posts": b.get("max_posts") or 500}
            title, steps, fn = "Blog Import", blog.STEPS, blog.run
        else:
            raise ApiError("Mode select karo")
        if self.jobs.running():
            raise ApiError("Ek kaam pehle se chal raha hai -- khatam hone do ya Stop karo.")
        app = self

        def runner(job, params):
            if mode == "migrate":
                params["source"] = app.build_store(session, b.get("source"), "SOURCE", job)
            params["dest"] = app.build_store(session, b.get("dest"), "DESTINATION", job)
            fn(job, params)

        job = self.jobs.start(mode, title, steps, runner, p)
        return {"id": job.id}


def make_handler(app):
    ui = resource_dir()

    class Handler(BaseHTTPRequestHandler):
        server_version = "STDI"
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _host_ok(self):
            host = (self.headers.get("Host") or "").split(":")[0]
            return host in ("127.0.0.1", "localhost")

        def _send(self, status, body, ctype="application/json; charset=utf-8", extra=None):
            data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self._host_ok():
                return self._send(403, {"error": "forbidden"})
            u = urlparse(self.path)
            if u.path == "/oauth/callback":
                return self._oauth_page(dict(parse_qsl(u.query)))
            if u.path == "/installed":
                return self._page("App install ho gayi", "Ab tool me wapas jao aur <b>Authorize</b> dabao.", True)
            if u.path == "/health":
                return self._send(200, {"app": APP_NAME, "version": APP_VERSION})
            rel = "index.html" if u.path in ("/", "/index.html") else u.path.lstrip("/")
            if rel.startswith("ui/"):
                rel = rel[3:]
            root = ui.resolve()
            f = (root / rel).resolve()
            if root not in f.parents or not f.is_file():
                return self._send(404, {"error": "not found"})
            ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
            if f.suffix == ".woff2":
                ctype = "font/woff2"
            if f.suffix == ".js":
                ctype = "text/javascript; charset=utf-8"
            extra = {"Content-Security-Policy": "default-src 'self'; img-src 'self' data: https:; "
                                                "style-src 'self' 'unsafe-inline'; font-src 'self'; "
                                                "connect-src 'self'; frame-ancestors 'none'"} if rel == "index.html" else None
            return self._send(200, f.read_bytes(), ctype, extra)

        def do_POST(self):
            if not self._host_ok():
                return self._send(403, {"error": "forbidden"})
            u = urlparse(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            if u.path == "/api/bye":                       # sendBeacon header nahi bhejta
                app.bye_at = time.time()
                return self._send(200, {"ok": True})
            if self.headers.get("X-App-Key") != app.key:
                return self._send(401, {"error": "Session key ghalat -- tool dobara kholo"})
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except ValueError:
                return self._send(400, {"error": "bad json"})
            try:
                return self._send(200, app.api(u.path, body))
            except auth.AuthError as e:
                return self._send(400, {"error": str(e)})
            except ApiError as e:
                return self._send(e.status, {"error": str(e)})
            except Exception as e:  # noqa: BLE001
                return self._send(500, {"error": f"Andruni ghalti: {e}"})

        def _oauth_page(self, params):
            try:
                app.oauth.complete(SESSION_FACTORY(), params)
                return self._page("Token tayar hai", "Shopify ne access de diya. Is tab ko band kar ke tool me wapas jao — "
                                  "token khud aa chuka hai.", True)
            except auth.AuthError as e:
                return self._page("Authorize nahi hua", str(e), False)

        def _page(self, title, msg, ok):
            color = "#2fd38f" if ok else "#ff7a7a"
            html = f"""<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#050b09;color:#eef5f1;
font:16px/1.6 'Segoe UI',system-ui,sans-serif}}.c{{max-width:460px;margin:24px;padding:40px;border-radius:24px;
background:linear-gradient(160deg,#0e1d18,#08110e);border:1px solid rgba(212,178,106,.25);text-align:center;
box-shadow:0 30px 80px rgba(0,0,0,.5)}}.d{{width:64px;height:64px;margin:0 auto 18px;border-radius:50%;
display:grid;place-items:center;background:{color}22;color:{color};font-size:30px}}h1{{font-weight:600;
margin:0 0 8px;font-size:24px}}p{{color:#a9bdb4;margin:0}}</style></head><body><div class="c">
<div class="d">{'✓' if ok else '!'}</div><h1>{title}</h1><p>{msg}</p></div></body></html>"""
            return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")

    return Handler


def start_server(port=None):
    """8765 try karo (OAuth redirect ke liye), warna koi bhi khali port."""
    for p in ([port] if port else [OAUTH_PORT, 0]):
        try:
            app = App(p)
            httpd = ThreadingHTTPServer(("127.0.0.1", p), make_handler(app))
            app.port = httpd.server_address[1]
            httpd.daemon_threads = True
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            return app, httpd
        except OSError:
            continue
    raise RuntimeError("Koi port khali nahi mila")
