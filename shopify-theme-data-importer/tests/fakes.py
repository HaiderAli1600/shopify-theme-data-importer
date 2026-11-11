"""In-memory fakes: Shopify Admin API (REST + GraphQL), staged uploads, demo storefront,
WooCommerce API, WordPress API and a generic blog. Used by all tests."""
import base64
import itertools
import json
import re
from urllib.parse import parse_qsl, urlencode, urlparse

_ids = itertools.count(5000)


def nid():
    return next(_ids)


class Resp:
    def __init__(self, status=200, body=None, headers=None, url="", text=None, content=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.url = url
        if text is not None:
            self.text = text
        elif isinstance(body, (dict, list)):
            self.text = json.dumps(body)
        else:
            self.text = str(body or "")
        self.content = content if content is not None else self.text.encode()

    def json(self):
        if isinstance(self._body, (dict, list)):
            return self._body
        return json.loads(self.text)

    def iter_content(self, n):
        yield self.content


# ============================================================ fake Shopify store
class FakeStore:
    def __init__(self, domain, token="tok", scopes=None):
        self.domain, self.token = domain, token
        self.scopes = scopes or ["write_products", "write_files", "write_content", "write_inventory",
                                 "read_locations", "write_online_store_navigation", "write_themes"]
        self.products, self.custom, self.smart, self.collects = [], [], [], []
        self.blogs, self.articles, self.pages = [], {}, []
        self.metafields = {}          # owner -> list
        self.files = []               # {id, typename, filename, url, alt, used_in_product}
        self.menus = []
        self.themes = []              # {id, name, role, processing, assets{key: value}}
        self.redirects = []
        self.inventory = []
        self.image_puts = []
        self.calls = []
        self.client_id, self.client_secret = "cid", "secret"
        self.cc_allowed = True        # client credentials (same org)

    # ---------------- helpers
    def cdn(self, name):
        return f"https://cdn.shopify.com/s/files/1/0{abs(hash(self.domain)) % 999}/files/{name}?v=1"

    def add_file(self, filename, typename="MediaImage", alt="", used_in_product=False, url=None):
        f = {"id": f"gid://shopify/{typename}/{nid()}", "typename": typename, "filename": filename,
             "url": url or self.cdn(filename), "alt": alt, "used": used_in_product}
        self.files.append(f)
        return f

    def file_node(self, f):
        base = {"__typename": f["typename"], "id": f["id"], "alt": f["alt"], "fileStatus": "READY"}
        if f["typename"] == "MediaImage":
            base["image"] = {"url": f["url"]}
        elif f["typename"] == "GenericFile":
            base.update(url=f["url"], mimeType="application/octet-stream")
        else:
            base.update(filename=f["filename"], originalSource={"url": f["url"], "mimeType": "video/mp4", "fileSize": 10})
        return base

    # ---------------- REST
    def rest(self, method, path, q, body, params):
        self.calls.append((method, path))
        if path.startswith("oauth/") or path == "access_token":
            pass
        m = re.match(r"^(.*?)/?metafields\.json$", path)
        if m:
            owner = m.group(1)
            if method == "GET":
                return Resp(200, {"metafields": self.metafields.get(owner, [])})
            mf = body["metafield"]
            lst = self.metafields.setdefault(owner, [])
            if any(x["namespace"] == mf["namespace"] and x["key"] == mf["key"] for x in lst):
                return Resp(422, {"errors": {"key": ["must be unique, has already been taken"]}})
            lst.append(dict(mf, id=nid()))
            return Resp(201, {"metafield": mf})
        if path == "shop.json":
            return Resp(200, {"shop": {"name": f"Shop {self.domain}", "domain": self.domain,
                                       "myshopify_domain": self.domain, "plan_display_name": "Basic"}})
        if path == "locations.json":
            return Resp(200, {"locations": [{"id": 77, "active": True}]})
        if path == "inventory_levels/set.json":
            self.inventory.append(body)
            return Resp(200, {"inventory_level": body})
        if path == "redirects.json":
            if any(r["path"] == body["redirect"]["path"] for r in self.redirects):
                return Resp(422, {"errors": {"path": ["has already been taken"]}})
            self.redirects.append(body["redirect"])
            return Resp(201, body)
        lists = {"products.json": self.products, "custom_collections.json": self.custom,
                 "smart_collections.json": self.smart, "pages.json": self.pages, "blogs.json": self.blogs}
        if path in lists:
            lst = lists[path]
            key = path[:-5]
            if method == "GET":
                fields = q.get("fields")
                items = [{k: v for k, v in x.items() if not fields or k in fields.split(",")} for x in lst]
                return Resp(200, {key: items})
            singular = key[:-1]
            obj = dict(body[singular], id=nid())
            if obj.get("handle") and any(x.get("handle") == obj["handle"] for x in lst):
                obj["handle"] = obj["handle"] + "-1"
            obj.setdefault("handle", re.sub(r"[^a-z0-9]+", "-", (obj.get("title") or "x").lower()).strip("-"))
            if key == "products":
                obj["variants"] = [dict(v, id=nid(), inventory_item_id=nid()) for v in obj.get("variants") or [{}]]
                obj["images"] = [dict(img, id=nid(), position=i + 1) for i, img in enumerate(obj.get("images") or [])]
                for img in obj["images"]:
                    self.add_file(img["src"].split("/")[-1].split("?")[0], used_in_product=True)
            if key == "custom_collections":
                for c in obj.pop("collects", []) or []:
                    self.collects.append({"collection_id": obj["id"], "product_id": c["product_id"]})
            if key == "blogs":
                self.articles[obj["id"]] = []
            lst.append(obj)
            return Resp(201, {singular: obj})
        m = re.match(r"^products/(\d+)\.json$", path)
        if m:
            p = next((x for x in self.products if x["id"] == int(m.group(1))), None)
            return Resp(200, {"product": p}) if p else Resp(404, {"errors": "Not Found"})
        m = re.match(r"^products/(\d+)/images/(\d+)\.json$", path)
        if m and method == "PUT":
            self.image_puts.append((int(m.group(1)), int(m.group(2)), body["image"]["variant_ids"]))
            return Resp(200, {"image": body["image"]})
        if path == "collects.json":
            if method == "GET":
                cid = int(q["collection_id"])
                if any(s["id"] == cid for s in self.smart):
                    return Resp(200, {"collects": []})          # real Shopify: smart collection -> no collects
                return Resp(200, {"collects": [dict(c, position=i + 1) for i, c in enumerate(self.collects)
                                               if c["collection_id"] == cid]})
            self.collects.append(body["collect"])
            return Resp(201, body)
        m = re.match(r"^blogs/(\d+)/articles\.json$", path)
        if m:
            bid = int(m.group(1))
            if method == "GET":
                fields = q.get("fields")
                return Resp(200, {"articles": [{k: v for k, v in a.items() if not fields or k in fields.split(",")}
                                               for a in self.articles.get(bid, [])]})
            a = dict(body["article"], id=nid())
            if a.get("image") and "broken" in a["image"].get("src", ""):
                return Resp(422, {"errors": {"image": ["could not be downloaded"]}})
            self.articles.setdefault(bid, []).append(a)
            return Resp(201, {"article": a})
        if path == "themes.json":
            return Resp(200, {"themes": [{k: t[k] for k in ("id", "name", "role")} for t in self.themes]})
        m = re.match(r"^themes/(\d+)\.json$", path)
        if m:
            t = next(t for t in self.themes if t["id"] == int(m.group(1)))
            return Resp(200, {"theme": {"id": t["id"], "processing": False}})
        m = re.match(r"^themes/(\d+)/assets\.json$", path)
        if m:
            t = next(t for t in self.themes if t["id"] == int(m.group(1)))
            if "asset[key]" in params:
                return Resp(200, {"asset": {"key": params["asset[key]"], "value": t["assets"].get(params["asset[key]"], "")}})
            return Resp(200, {"assets": [{"key": k} for k in t["assets"]]})
        raise AssertionError(f"{self.domain}: unexpected REST {method} {path}")

    # ---------------- GraphQL
    def graphql(self, body):
        q, v = body["query"], body.get("variables") or {}
        page = {"hasNextPage": False, "endCursor": None}
        if "fileCreate" in q:
            files, errors = [], []
            for i, f in enumerate(v["files"]):
                name = f.get("filename") or f["originalSource"].split("/")[-1].split("?")[0]
                if f.get("duplicateResolutionMode") == "RAISE_ERROR" and any(x["filename"] == name for x in self.files):
                    errors.append({"field": ["files", str(i), "filename"], "message": "Filename already exists",
                                   "code": "FILENAME_ALREADY_EXISTS"})
                    continue
                if f.get("duplicateResolutionMode") is None and any(x["filename"] == name for x in self.files):
                    stem, ext = name.rsplit(".", 1) if "." in name else (name, "")
                    name = f"{stem}_{nid()}.{ext}"
                if "trial-blocked" in name:
                    errors.append({"field": ["files", str(i)], "message": "no", "code": "UNACCEPTABLE_TRIAL_ASSET"})
                    continue
                typename = {"IMAGE": "MediaImage", "VIDEO": "Video"}.get(f.get("contentType"), "GenericFile")
                files.append(self.add_file(name, typename, f.get("alt") or ""))
            if errors:           # real Shopify: batch with errors -> nothing created
                for created in files:
                    self.files.remove(created)
                files = []
            return {"data": {"fileCreate": {"files": [{"id": f["id"], "fileStatus": "UPLOADED"} for f in files],
                                            "userErrors": errors}}}
        if "stagedUploadsCreate" in q:
            inp = v["input"][0]
            return {"data": {"stagedUploadsCreate": {"stagedTargets": [{
                "url": "https://staged.example/upload", "resourceUrl": f"https://staged.example/r/{inp['filename']}",
                "parameters": [{"name": "key", "value": "abc"}]}], "userErrors": []}}}
        if "fileDelete" in q:
            self.files = [f for f in self.files if f["id"] not in v["ids"]]
            return {"data": {"fileDelete": {"deletedFileIds": v["ids"]}}}
        if "nodes(ids" in q:
            return {"data": {"nodes": [self.file_node(f) for f in self.files if f["id"] in v["ids"]]}}
        if re.search(r"\bfiles\(first", q) and "theme(id" not in q:
            qq = v.get("q")
            nodes = [self.file_node(f) for f in self.files if qq != "used_in:product" or f["used"]]
            return {"data": {"files": {"nodes": nodes, "pageInfo": page}}}
        if "menuCreate" in q:
            self.menus.append({"id": f"gid://shopify/Menu/{nid()}", "handle": v["handle"], "title": v["title"],
                               "isDefault": False, "items": v["items"]})
            return {"data": {"menuCreate": {"menu": {"id": self.menus[-1]["id"]}, "userErrors": []}}}
        if "menuUpdate" in q:
            m = next(m for m in self.menus if m["id"] == v["id"])
            m.update(title=v["title"], items=v["items"])
            return {"data": {"menuUpdate": {"menu": {"id": m["id"]}, "userErrors": []}}}
        if "menus(first" in q:
            return {"data": {"menus": {"nodes": self.menus, "pageInfo": page}}}
        if "themeCreate" in q:
            t = {"id": nid(), "name": v["name"], "role": "unpublished", "processing": False,
                 "assets": {"templates/index.json": '{"sections":{}}'}}
            self.themes.append(t)
            return {"data": {"themeCreate": {"theme": {"id": f"gid://shopify/OnlineStoreTheme/{t['id']}",
                                                       "name": t["name"], "processing": True}, "userErrors": []}}}
        if "themes(first" in q:
            return {"data": {"themes": {"nodes": [{"id": f"gid://shopify/OnlineStoreTheme/{t['id']}", "name": t["name"]}
                                                  for t in self.themes if t["role"] == "main"]}}}
        if "theme(id" in q:
            tid = int(v["id"].split("/")[-1])
            t = next(t for t in self.themes if t["id"] == tid)
            nodes = []
            for k, val in t["assets"].items():
                if isinstance(val, bytes):
                    nodes.append({"filename": k, "body": {"__typename": "OnlineStoreThemeFileBodyBase64",
                                                          "contentBase64": base64.b64encode(val).decode()}})
                else:
                    nodes.append({"filename": k, "body": {"__typename": "OnlineStoreThemeFileBodyText", "content": val}})
            return {"data": {"theme": {"files": {"nodes": nodes, "pageInfo": page}}}}
        raise AssertionError(f"{self.domain}: unexpected GraphQL {q[:120]}")

    # ---------------- OAuth endpoint
    def oauth(self, body, data):
        if data and data.get("grant_type") == "client_credentials":
            if data.get("client_id") != self.client_id or data.get("client_secret") != self.client_secret:
                return Resp(400, {"error": "invalid_client", "error_description": "bad"})
            if not self.cc_allowed:
                return Resp(400, {"error": "shop_not_permitted"})
            return Resp(200, {"access_token": self.token, "scope": ",".join(self.scopes), "expires_in": 86399})
        if body and body.get("code") == "good-code" and body.get("client_secret") == self.client_secret:
            return Resp(200, {"access_token": self.token, "scope": ",".join(self.scopes)})
        return Resp(400, {"error": "invalid_request", "error_description": "code invalid"})


# ============================================================ fake web
class FakeWeb:
    """All HTTP goes through here: Shopify stores + websites."""

    def __init__(self):
        self.stores = {}
        self.sites = {}          # host -> callable(method, path, query, data) -> Resp
        self.log = []
        self.cookies = {}

    def store(self, s):
        self.stores[s.domain] = s
        return s

    def site(self, host, handler):
        self.sites[host] = handler

    def request(self, method, url, headers=None, json=None, params=None, data=None, timeout=None, auth=None,
                files=None, stream=False, allow_redirects=True, **kw):
        p = urlparse(url)
        q = dict(parse_qsl(p.query))
        if params:
            q.update({k: str(v) for k, v in params.items()})
        self.log.append((method, p.netloc, p.path, q))
        if p.netloc in self.stores:
            st = self.stores[p.netloc]
            if p.path == "/admin/oauth/access_token":
                return st.oauth(json, data)
            tok = (headers or {}).get("X-Shopify-Access-Token")
            if tok != st.token:
                return Resp(401, {"errors": "[API] Invalid API key or access token"})
            if p.path == "/admin/oauth/access_scopes.json":
                return Resp(200, {"access_scopes": [{"handle": s} for s in st.scopes]})
            path = re.sub(r"^/admin/api/[^/]+/", "", p.path)
            if path == "graphql.json":
                return Resp(200, st.graphql(json))
            return st.rest(method, path, q, json, params or {})
        if p.netloc == "staged.example":
            return Resp(201, "")
        if p.netloc in self.sites:
            r = self.sites[p.netloc](method, p.path, q, data, auth)
            if not r.url:
                r.url = url
            return r
        return Resp(404, "not found", url=url)

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)

    def mount(self, *a):
        pass


def qs(d):
    return urlencode(d)
