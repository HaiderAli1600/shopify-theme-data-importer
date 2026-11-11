import hashlib
import hmac
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlencode, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import server                              # noqa: E402
from app.core import auth                           # noqa: E402
from app.core.shopify import normalize_domain       # noqa: E402
from tests.fakes import FakeStore, FakeWeb          # noqa: E402
from tests.test_other_modes import wp_site          # noqa: E402

WEB = FakeWeb()
OWN = WEB.store(FakeStore("my-dev.myshopify.com", "own-token"))
CLIENT = WEB.store(FakeStore("client-store.myshopify.com", "client-token"))
CLIENT.cc_allowed = False                     # client store: doosri organization
CLIENT.blogs, CLIENT.articles = [], {}
WEB.site("wpblog.com", wp_site)
OPENED = []
OPENED_LOCAL = []
server.SESSION_FACTORY = lambda: WEB
server.OPEN_URL = OPENED.append
server.OPEN_LOCAL = OPENED_LOCAL.append


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


APP, HTTPD = server.start_server(free_port())
BASE = f"http://127.0.0.1:{APP.port}"


def call(path, body=None, key=True, host=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body or {}).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **({"X-App-Key": APP.key} if key else {}),
                                          **({"Host": host} if host else {})})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=20) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


def test_security():
    assert call("/api/info", key=False)[0] == 401
    assert call("/api/info", host="evil.example.com")[0] == 403
    assert get("/../../etc/passwd")[0] == 404
    assert get("/ui/../server.py")[0] == 404
    st, body, headers = get("/")
    assert st == 200 and b"Theme Data Importer" in body and "frame-ancestors" in headers["Content-Security-Policy"]
    assert get("/app.js")[0] == 200 and get("/fonts/inter.woff2")[2]["Content-Type"] == "font/woff2"
    assert call("/api/open", {"url": "file:///etc/passwd"})[0] == 400
    assert call("/api/open", {"url": "https://dev.shopify.com"})[0] == 200 and OPENED[-1] == "https://dev.shopify.com"


def test_info_and_domains():
    st, info = call("/api/info")
    assert st == 200 and info["redirect_uri"].endswith(":8765/oauth/callback")
    assert "write_products" in info["scopes"]["migrate_dest"]["required"]
    for raw in ("https://client-store.myshopify.com/", "admin.shopify.com/store/client-store/products", "client-store"):
        assert normalize_domain(raw) == "client-store.myshopify.com"


def test_connect_methods():
    st, r = call("/api/connect", {"domain": "my-dev", "method": "token", "token": "own-token", "role": "migrate_dest"})
    assert st == 200 and r["shop"]["myshopify_domain"] == "my-dev.myshopify.com" and r["report"]["missing"] == []
    st, r = call("/api/connect", {"domain": "my-dev", "method": "token", "token": "bad", "role": "migrate_dest"})
    assert st == 400 and "401" in r["error"]
    st, r = call("/api/connect", {"domain": "my-dev", "method": "cc", "client_id": "cid", "client_secret": "secret",
                                  "role": "blog_dest"})
    assert st == 200 and r["token"] == "own-token" and r["expires_in"] == 86399
    st, r = call("/api/connect", {"domain": "my-dev", "method": "cc", "client_id": "cid", "client_secret": "nope"})
    assert st == 400 and "ghalat" in r["error"]
    st, r = call("/api/connect", {"domain": "client-store", "method": "cc", "client_id": "cid", "client_secret": "secret"})
    assert st == 400 and "organization me nahi" in r["error"]
    OWN.scopes = ["read_products"]
    st, r = call("/api/connect", {"domain": "my-dev", "method": "token", "token": "own-token", "role": "migrate_dest"})
    assert r["report"]["missing"] == ["write_products", "write_files", "write_content"]
    OWN.scopes = ["write_products", "write_files", "write_content"]


def test_oauth_flow():
    st, r = call("/api/oauth/start", {"domain": "client-store", "client_id": "cid", "client_secret": "secret",
                                      "scopes": ["write_products"], "redirect_uri": APP.redirect_uri})
    assert st == 200 and OPENED[-1] == r["url"]
    q = parse_qs(urlparse(r["url"]).query)
    assert q["client_id"] == ["cid"] and q["redirect_uri"] == [APP.redirect_uri] and q["state"] == [r["state"]]
    assert call("/api/oauth/status", {"state": r["state"]})[1]["status"] == "waiting"
    # Shopify browser ko callback par bhejta hai (code + hmac + shop + state)
    params = {"code": "good-code", "shop": "client-store.myshopify.com", "state": r["state"], "timestamp": "1700000000"}
    msg = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    params["hmac"] = hmac.new(b"secret", msg.encode(), hashlib.sha256).hexdigest()
    st, body, _ = get("/oauth/callback?" + urlencode(params))
    assert st == 200 and b"Token tayar hai" in body
    st, s = call("/api/oauth/status", {"state": r["state"], "role": "blog_dest"})
    assert s["status"] == "done" and s["token"] == "client-token" and s["verify"]["shop"]["myshopify_domain"] == "client-store.myshopify.com"
    # tampered hmac
    st, r2 = call("/api/oauth/start", {"domain": "client-store", "client_id": "cid", "client_secret": "secret"})
    bad = dict(params, state=r2["state"], hmac="0" * 64)
    st, body, _ = get("/oauth/callback?" + urlencode(bad))
    assert b"HMAC" in body
    assert call("/api/oauth/status", {"state": r2["state"]})[1]["status"] == "error"
    # manual paste fallback
    st, r3 = call("/api/oauth/start", {"domain": "client-store", "client_id": "cid", "client_secret": "secret"})
    p3 = {"code": "good-code", "shop": "client-store.myshopify.com", "state": r3["state"]}
    p3["hmac"] = hmac.new(b"secret", "&".join(f"{k}={v}" for k, v in sorted(p3.items())).encode(), hashlib.sha256).hexdigest()
    st, m = call("/api/oauth/manual", {"url": "https://example.com/cb?" + urlencode(p3)})
    assert st == 200 and m["token"] == "client-token"


def test_run_job_and_save(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "output_dir", lambda: tmp_path)
    st, r = call("/api/run", {"mode": "blog", "listing_url": "wpblog.com", "blog_title": "News",
                              "dest": {"domain": "client-store", "method": "token", "token": "client-token"}})
    assert st == 200
    since, events = 0, []
    for _ in range(200):
        st, snap = call("/api/job", {"id": r["id"], "since": since})
        events += snap["events"]
        since = snap["next"]
        if snap["status"] != "running":
            break
        time.sleep(0.1)
    assert snap["status"] in ("done", "warning"), (snap["status"], snap["notes"], events[-5:])
    assert snap["stats"]["Articles"]["created"] == 3
    assert any("WordPress site mili" in e["msg"] for e in events)
    st, saved = call("/api/job/save", {"id": r["id"], "reveal": False})
    assert st == 200 and "Article: Post & 0" in open(saved["path"], encoding="utf-8").read()
    # bad destination token -> job fails cleanly with a message
    st, r = call("/api/run", {"mode": "blog", "listing_url": "wpblog.com",
                              "dest": {"domain": "client-store", "method": "token", "token": ""}})
    for _ in range(50):
        snap = call("/api/job", {"id": r["id"]})[1]
        if snap["status"] != "running":
            break
        time.sleep(0.1)
    assert snap["status"] == "failed" and any("access token chahiye" in e["msg"] for e in snap["events"])


def test_heartbeat():
    call("/api/ping")
    assert APP.bye_at is None and APP.ever_pinged
    req = urllib.request.Request(BASE + "/api/bye", data=b"{}", method="POST")      # sendBeacon: key nahi hoti
    urllib.request.urlopen(req, timeout=5)
    assert APP.bye_at is not None
    call("/api/ping")
    assert APP.bye_at is None


def test_scope_implication():
    rep = auth.scope_report(["write_products", "write_files", "write_content"], "migrate_source")
    assert rep["missing"] == []          # write_x => read_x


def test_open_local_folders(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "output_dir", lambda: tmp_path)
    exports = tmp_path / "theme-exports"
    exports.mkdir()
    assert call("/api/open", {"url": "local:" + str(exports)})[0] == 200 and OPENED_LOCAL[-1] == exports.resolve()
    assert call("/api/open", {"url": exports.as_uri()})[0] == 200                      # file:/// bhi
    assert call("/api/open", {"url": "output"})[0] == 200 and OPENED_LOCAL[-1] == tmp_path
    st, r = call("/api/open", {"url": "local:/etc"})
    assert st == 400 and "bahar" in r["error"]
    st, r = call("/api/open", {"url": "local:" + str(tmp_path / "nahi-hai")})
    assert st == 400 and "nahi mila" in r["error"]
