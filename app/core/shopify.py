"""Shopify Admin API client (REST + GraphQL) shared by every mode."""
import json
import mimetypes
import os
import re
import tempfile
import time
from urllib.parse import unquote, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..version import API_VERSION, APP_NAME, APP_VERSION

USER_AGENT = f"{APP_NAME.replace(' ', '')}/{APP_VERSION}"
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")


def make_session():
    """GET par retry. POST/PUT par nahi (warna duplicate products ban sakte hain)."""
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=1.0, status_forcelist=(500, 502, 503, 504),
                  allowed_methods=["GET", "HEAD"], raise_on_status=False)
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=8)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


def safe_json(resp):
    try:
        return resp.json()
    except Exception:
        return {}


def short_err(resp):
    if resp is None:
        return "connection error (internet / domain check karo)"
    body = resp.text[:300].replace("\n", " ")
    return f"HTTP {resp.status_code}: {body}"


def compact(d):
    return {k: v for k, v in d.items() if v is not None}


def filename_from_url(url):
    return unquote(os.path.basename(urlparse(url or "").path))


def normalize_domain(value):
    """'https://x.myshopify.com/', 'admin.shopify.com/store/x', 'x' -> 'x.myshopify.com'."""
    v = (value or "").strip()
    m = re.search(r"admin\.shopify\.com/store/([a-z0-9][a-z0-9-]*)", v, re.I)
    if m:
        return f"{m.group(1).lower()}.myshopify.com"
    v = re.sub(r"^https?://", "", v, flags=re.I).split("/")[0].split("?")[0].strip().lower()
    if v and "." not in v:
        v += ".myshopify.com"
    return v


class ShopifyError(Exception):
    pass


class Store:
    """Ek Shopify store ka Admin API connection."""

    def __init__(self, session, domain, token, label="Store", job=None, refresh=None):
        self.s = session
        self.domain = normalize_domain(domain)
        self.token = token
        self.label = label
        self.job = job
        self.refresh = refresh             # client-credentials token expire ho to naya lao
        self.write_pause = 0.35

    # ----------------------------------------------------------------- core
    def url(self, path):
        return f"https://{self.domain}/admin/api/{API_VERSION}/{path.lstrip('/')}"

    def _sleep(self, seconds):
        if self.job:
            self.job.sleep(seconds)
        else:
            time.sleep(seconds)

    def request(self, method, path_or_url, **kw):
        url = path_or_url if path_or_url.startswith("http") else self.url(path_or_url)
        kw.setdefault("timeout", 60)
        refreshed = False
        for _ in range(8):
            if self.job:
                self.job.check()
            headers = {"X-Shopify-Access-Token": self.token, "Content-Type": "application/json",
                       "Accept": "application/json", "User-Agent": USER_AGENT}
            try:
                r = self.s.request(method, url, headers=headers, **kw)
            except requests.RequestException:
                if method == "GET":
                    self._sleep(2)
                    continue
                return None
            if r.status_code == 429:
                self._sleep(min(float(r.headers.get("Retry-After", 2) or 2), 10))
                continue
            if r.status_code == 401 and self.refresh and not refreshed:
                refreshed = True
                new = self.refresh()
                if new:
                    self.token = new
                    continue
            used = r.headers.get("X-Shopify-Shop-Api-Call-Limit", "")
            if "/" in used:
                a, b = used.split("/", 1)
                if a.isdigit() and b.isdigit() and int(a) > int(b) * 0.8:
                    self._sleep(1.0)
            return r
        return None

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, payload):
        r = self.request("POST", path, json=payload)
        self._sleep(self.write_pause)
        return r

    def put(self, path, payload):
        r = self.request("PUT", path, json=payload)
        self._sleep(self.write_pause)
        return r

    def delete(self, path):
        return self.request("DELETE", path)

    def get_all(self, path, key, limit=None):
        """REST cursor pagination (Link header)."""
        items, url = [], path
        while url:
            r = self.get(url)
            if r is None or r.status_code != 200:
                if r is not None and r.status_code in (401, 403):
                    raise PermissionError(f"{self.label} {path.split('?')[0]}: {short_err(r)}")
                if r is not None and r.status_code == 404:
                    break
                if r is None or r.status_code >= 500:
                    raise ShopifyError(f"{self.label} {path.split('?')[0]}: {short_err(r)}")
                break
            items.extend(safe_json(r).get(key, []))
            if self.job:
                self.job.detail(f"{self.label}: {key.replace('_', ' ')} {len(items)} mile...")
            if limit and len(items) >= limit:
                return items[:limit]
            url = None
            for part in r.headers.get("Link", "").split(","):
                if 'rel="next"' in part:
                    url = part[part.find("<") + 1:part.find(">")]
        return items

    def gql(self, query, variables=None):
        """(data, errors). Throttle ho to wait."""
        for _ in range(8):
            r = self.request("POST", "graphql.json", json={"query": query, "variables": variables or {}})
            if r is None:
                return {}, ["connection error"]
            body = safe_json(r)
            errors = body.get("errors") or []
            if isinstance(errors, str):
                errors = [errors]
            if any("THROTTLED" in json.dumps(e) for e in errors):
                self._sleep(2)
                continue
            if r.status_code in (401, 403) and not errors:
                errors = [short_err(r)]
            elif r.status_code != 200 and not errors:
                errors = [short_err(r)]
            return body.get("data") or {}, [e.get("message", e) if isinstance(e, dict) else e for e in errors]
        return {}, ["API throttle -- thori der baad try karo"]

    def gql_all(self, query, root, variables=None, limit=None):
        nodes, cursor = [], None
        while True:
            data, errors = self.gql(query, dict(variables or {}, cursor=cursor))
            if errors:
                return nodes, errors
            conn = data
            for part in root.split("."):
                conn = (conn or {}).get(part) or {}
            nodes.extend(conn.get("nodes") or [])
            if self.job:
                self.job.detail(f"{self.label}: {root.split('.')[-1]} {len(nodes)} mile...")
            if limit and len(nodes) >= limit:
                return nodes[:limit], []
            info = conn.get("pageInfo") or {}
            if not info.get("hasNextPage"):
                return nodes, []
            cursor = info.get("endCursor")

    # ----------------------------------------------------------------- info
    def shop(self):
        r = self.get("shop.json")
        if r is None or r.status_code != 200:
            raise ShopifyError(short_err(r))
        return safe_json(r).get("shop", {})

    def granted_scopes(self):
        r = self.request("GET", f"https://{self.domain}/admin/oauth/access_scopes.json")
        if r is None or r.status_code != 200:
            return None
        return sorted(s["handle"] for s in safe_json(r).get("access_scopes", []))

    def primary_location_id(self):
        r = self.get("locations.json")
        if r is None or r.status_code != 200:
            return None
        locs = [loc for loc in safe_json(r).get("locations", []) if loc.get("active")]
        return locs[0]["id"] if locs else None

    def handles(self, resource, key=None):
        key = key or resource
        return {x["handle"]: x["id"] for x in self.get_all(f"{resource}.json?limit=250&fields=id,handle", key)}


# =====================================================================
# Files (Content > Files)
# =====================================================================
FILES_QUERY = """
query($cursor: String, $q: String) {
  files(first: 100, after: $cursor, query: $q) {
    nodes {
      __typename id alt fileStatus
      ... on MediaImage { image { url } }
      ... on GenericFile { url mimeType }
      ... on Video { filename originalSource { url mimeType fileSize } }
    }
    pageInfo { hasNextPage endCursor }
  }
}"""

FILE_NODES_QUERY = """
query($ids: [ID!]!) {
  nodes(ids: $ids) {
    __typename id
    ... on MediaImage { fileStatus image { url } }
    ... on GenericFile { fileStatus url }
    ... on Video { fileStatus originalSource { url } }
  }
}"""

FILE_CREATE = """
mutation fileCreate($files: [FileCreateInput!]!) {
  fileCreate(files: $files) {
    files { id fileStatus }
    userErrors { field message code }
  }
}"""

FILE_DELETE = """
mutation fileDelete($ids: [ID!]!) {
  fileDelete(fileIds: $ids) { deletedFileIds userErrors { message } }
}"""

STAGED_UPLOAD = """
mutation stagedUploadsCreate($input: [StagedUploadInput!]!) {
  stagedUploadsCreate(input: $input) {
    stagedTargets { url resourceUrl parameters { name value } }
    userErrors { field message }
  }
}"""

IMAGE_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".heic", ".tif", ".tiff", ".bmp")
VIDEO_EXT = (".mp4", ".mov", ".webm", ".m4v")


def content_type_for(filename):
    ext = os.path.splitext(filename.lower())[1]
    if ext in IMAGE_EXT:
        return "IMAGE"
    if ext in VIDEO_EXT:
        return "VIDEO"
    return "FILE"        # svg, pdf, json, woff... (SVG Shopify me generic file hai)


def describe_file(node):
    """(filename, url, contentType, alt, mime, size) ya None."""
    t = node.get("__typename")
    if t == "MediaImage":
        url = (node.get("image") or {}).get("url")
        return (filename_from_url(url), url, "IMAGE", node.get("alt"), None, None) if url else None
    if t == "GenericFile":
        url = node.get("url")
        return (filename_from_url(url), url, "FILE", node.get("alt"), node.get("mimeType"), None) if url else None
    if t == "Video":
        src = node.get("originalSource") or {}
        url = src.get("url")
        if not url:
            return None
        return (node.get("filename") or filename_from_url(url), url, "VIDEO", node.get("alt"),
                src.get("mimeType"), src.get("fileSize"))
    return None


def list_files(store, q=None):
    nodes, errors = store.gql_all(FILES_QUERY, "files", {"q": q})
    return [d for d in (describe_file(n) for n in nodes) if d], errors


FILE_ERROR_HELP = {
    "UNACCEPTABLE_TRIAL_ASSET": "trial store par yeh file type allowed nahi (paid plan par chalega)",
    "UNACCEPTABLE_UNVERIFIED_TRIAL_ASSET": "trial store verify nahi -- yeh file type abhi allowed nahi",
    "INVALID_IMAGE_SOURCE_URL": "source URL se image nahi mil saki",
    "NON_IMAGE_MEDIA_PER_SHOP_LIMIT_EXCEEDED": "store ki non-image files ki limit poori",
    "MISMATCHED_FILENAME_AND_ORIGINAL_SOURCE": "filename extension source se match nahi karti",
}


def _file_input(fname, url, ctype, alt, dup=True):
    return compact({"originalSource": url, "contentType": ctype, "filename": fname, "alt": alt or None,
                    "duplicateResolutionMode": "RAISE_ERROR" if dup else None})


def _create_one(store, item, job):
    fname, url, ctype, alt = item
    for dup in (True, False):
        data, errs = store.gql(FILE_CREATE, {"files": [_file_input(fname, url, ctype, alt, dup)]})
        res = data.get("fileCreate") or {}
        ue = res.get("userErrors") or []
        if not errs and not ue and res.get("files"):
            return res["files"][0]["id"], None
        codes = {e.get("code") for e in ue}
        if "FILENAME_ALREADY_EXISTS" in codes:
            return None, "exists"
        if dup and "INVALID_DUPLICATE_MODE_FOR_TYPE" in codes:
            continue
        if errs:
            return None, str(errs)
        e = ue[0] if ue else {}
        return None, FILE_ERROR_HELP.get(e.get("code"), e.get("message") or "unknown")
    return None, "unknown"


def create_files_from_urls(store, items, job=None, batch=10):
    """items: [(filename, url, contentType, alt)] -- public URL se seedha (download nahi).
    Returns {filename: file_id}. Batch me masla ho to har file alag try hoti hai."""
    created = {}
    for i in range(0, len(items), batch):
        chunk = items[i:i + batch]
        data, errs = store.gql(FILE_CREATE, {"files": [_file_input(*it) for it in chunk]})
        res = data.get("fileCreate") or {}
        files = res.get("files") or []
        if not errs and not res.get("userErrors") and len(files) == len(chunk):
            for (fname, *_), f in zip(chunk, files):
                created[fname] = f["id"]
            if job:
                job.add("Files", "uploaded", len(chunk))
        else:
            for item in chunk:                       # precise result per file
                fid, err = _create_one(store, item, job)
                if fid:
                    created[item[0]] = fid
                    if job:
                        job.add("Files", "uploaded")
                elif err == "exists":
                    if job:
                        job.add("Files", "already")
                elif job:
                    job.add("Files", "failed")
                    job.note(f"File '{item[0]}': {err}")
        if job:
            job.progress(min(i + batch, len(items)), len(items), chunk[-1][0])
    return created


def wait_file_urls(store, ids, job=None, timeout=90):
    """File ids -> CDN url (processing complete hone ka wait)."""
    ids = list(ids)
    total = len(ids)
    urls, deadline = {}, time.time() + timeout
    while ids and time.time() < deadline:
        if job:
            job.detail(f"Shopify files process kar raha hai: {total - len(ids)}/{total} tayar")
        pending = []
        for i in range(0, len(ids), 50):
            data, _ = store.gql(FILE_NODES_QUERY, {"ids": ids[i:i + 50]})
            for n in data.get("nodes") or []:
                if not n:
                    continue
                url = ((n.get("image") or {}).get("url") or n.get("url")
                       or (n.get("originalSource") or {}).get("url"))
                if url:
                    urls[n["id"]] = url
                elif n.get("fileStatus") == "FAILED":
                    urls[n["id"]] = None
                else:
                    pending.append(n["id"])
        ids = pending
        if ids:
            (job.sleep if job else time.sleep)(3)
    return urls


def upload_local_file(session, store, path, filename=None, alt=None, content_type=None, mime=None):
    """Local file -> staged upload -> fileCreate. Returns (file_id, error)."""
    filename = filename or os.path.basename(path)
    content_type = content_type or content_type_for(filename)
    mime = mime or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    size = os.path.getsize(path)
    resource = {"IMAGE": "IMAGE", "VIDEO": "VIDEO"}.get(content_type, "FILE")
    data, errors = store.gql(STAGED_UPLOAD, {"input": [{
        "filename": filename, "mimeType": mime, "resource": resource,
        "fileSize": str(size), "httpMethod": "POST"}]})
    res = data.get("stagedUploadsCreate") or {}
    if errors or res.get("userErrors") or not res.get("stagedTargets"):
        return None, f"staged upload: {errors or res.get('userErrors')}"
    target = res["stagedTargets"][0]
    params = {p["name"]: p["value"] for p in target["parameters"]}
    try:
        with open(path, "rb") as f:
            up = session.post(target["url"], data=params, files={"file": (filename, f, mime)}, timeout=900)
    except (requests.RequestException, OSError) as e:
        return None, str(e)
    if up.status_code not in (200, 201, 204):
        return None, f"upload HTTP {up.status_code}"
    data, errors = store.gql(FILE_CREATE, {"files": [compact({
        "originalSource": target["resourceUrl"], "contentType": content_type,
        "filename": filename, "alt": alt or None, "duplicateResolutionMode": "RAISE_ERROR"})]})
    res = data.get("fileCreate") or {}
    if errors or res.get("userErrors"):
        return None, f"{errors or res.get('userErrors')}"
    files = res.get("files") or []
    return (files[0]["id"] if files else None), None


def download_to_temp(session, url, suffix=""):
    r = session.get(url, timeout=600, stream=True, headers={"User-Agent": BROWSER_UA})
    if r.status_code != 200:
        raise ShopifyError(f"download HTTP {r.status_code}")
    fd, tmp = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        for chunk in r.iter_content(1 << 20):
            f.write(chunk)
    return tmp


# =====================================================================
# CDN links (descriptions ke andar ki images) -- source -> destination
# =====================================================================
CDN_FILE_RE = re.compile(
    r'(?:https?:)?//[^\s"\'<>()]+?/(?:s/files/(?:\d+/)+files|cdn/shop/files)/'
    r'([^\s"\'<>()?#]+)(\?[^\s"\'<>()]*)?', re.I)


def rewrite_cdn_urls(html, file_url_map):
    if not html or not file_url_map:
        return html

    def repl(m):
        return file_url_map.get(unquote(m.group(1)).split("/")[-1]) or m.group(0)

    return CDN_FILE_RE.sub(repl, html)


# =====================================================================
# Metafields
# =====================================================================
def metafield_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (dict, list)):
        return json.dumps(v)
    return str(v)


def copy_metafields(src, dst, src_owner, dst_owner, job, label, top=False):
    """Non-reference metafields copy. src_owner e.g. 'products/123' ya '' (shop).
    top=True: yeh khud ek step hai -> har metafield par progress."""
    ps = f"{src_owner}/" if src_owner else ""
    pd = f"{dst_owner}/" if dst_owner else ""
    try:
        mfs = src.get_all(f"{ps}metafields.json?limit=250", "metafields")
    except (PermissionError, ShopifyError):
        return
    if top and not mfs:
        job.log(f"{label}: koi metafield nahi")
    for n, mf in enumerate(mfs, 1):
        ns, key, mtype = mf.get("namespace", ""), mf.get("key", ""), mf.get("type") or ""
        if top:
            job.progress(n, len(mfs), f"{ns}.{key}")
        if ns.startswith("app--") or ns.startswith("shopify") or not mtype:
            continue
        if "reference" in mtype:
            job.add("Metafields", "skipped")
            job.note(f"{label}: metafield {ns}.{key} ({mtype}) reference type hai -- admin me manually set karo")
            continue
        r = dst.post(f"{pd}metafields.json", {"metafield": {
            "namespace": ns, "key": key, "type": mtype, "value": metafield_value(mf.get("value"))}})
        if r is not None and r.status_code in (200, 201):
            job.add("Metafields", "copied")
            if top:
                job.ok(f"{label} metafield: {ns}.{key}")
        elif r is not None and r.status_code == 422 and "taken" in r.text.lower():
            job.add("Metafields", "already")
        else:
            job.add("Metafields", "failed")
            job.note(f"{label}: metafield {ns}.{key} -- {short_err(r)}")


# =====================================================================
# Blogs / articles (shared by demo, migrate, blog-import)
# =====================================================================
def get_or_create_blog(dst, title, handle=None, extra=None):
    blogs = dst.get_all("blogs.json?limit=250", "blogs")
    for b in blogs:
        if (handle and b.get("handle") == handle) or (not handle and b["title"].strip().lower() == title.strip().lower()):
            return b["id"], False
    r = dst.post("blogs.json", {"blog": compact(dict({"title": title or "News", "handle": handle}, **(extra or {})))})
    if r is None or r.status_code not in (200, 201):
        raise ShopifyError(f"Blog '{title}' create nahi hua -- {short_err(r)}")
    return safe_json(r)["blog"]["id"], True


def article_handles(dst, blog_id):
    arts = dst.get_all(f"blogs/{blog_id}/articles.json?limit=250&fields=id,handle,title", "articles")
    return {a["handle"]: a["id"] for a in arts}, {a["title"].strip().lower() for a in arts if a.get("title")}


def slugify(text):
    s = re.sub(r"[^a-z0-9]+", "-", unquote(text or "").lower()).strip("-")
    return s[:200] or None


# =====================================================================
# Theme reference verifier (theme ke JSON me jo cheezein link hain woh store me hain?)
# =====================================================================
THEME_REF_RE = re.compile(r'shopify://(shop_images|collections|products|pages|blogs)/([^"\\\s]+)')


def _store_have(store):
    return {
        "collections": set(store.handles("custom_collections")) | set(store.handles("smart_collections")),
        "products": set(store.handles("products")),
        "pages": set(store.handles("pages")),
        "blogs": {b["handle"] for b in store.get_all("blogs.json?limit=250", "blogs")},
    }


def _verify_targets(dst_themes, theme_id, src):
    """Kaun se themes check karne hain: migrate hua theme (id se, ya source ke main theme ke naam se
    "(migrated)" wala) + destination ka published theme."""
    targets = [t for t in dst_themes if theme_id and str(t.get("id")) == str(theme_id)]
    if not targets and src is not None:
        sr = src.get("themes.json")
        sm = next((t for t in safe_json(sr).get("themes", []) if t.get("role") == "main"), None) if sr is not None else None
        if sm:
            targets += [t for t in dst_themes if t.get("name") == f"{sm['name']} (migrated)"]
    targets += [t for t in dst_themes if t.get("role") == "main" and t not in targets]
    return targets


def verify_theme_refs(dst, job, theme_id=None, src=None):
    """Theme ki JSON files me jo images / products / collections / pages / blogs link hain,
    woh destination store me hain? src diya ho to: jo source me hai magar yahan nahi -> khud copy;
    jo source me bhi nahi tha -> purana/demo reference (koi asar nahi)."""
    r = dst.get("themes.json")
    if r is None or r.status_code != 200:
        job.note(f"Theme read nahi hua ({short_err(r)}) -- read_themes scope do")
        return
    targets = _verify_targets(safe_json(r).get("themes", []), theme_id, src)
    if not targets:
        job.note("Destination par published theme nahi mila")
        return
    names = " + ".join(f"'{t['name']}'" for t in targets)
    job.log(f"Theme check: {names}")
    keys = []
    for t in targets:
        ra = dst.get(f"themes/{t['id']}/assets.json")
        keys += [(t, a["key"]) for a in safe_json(ra).get("assets", [])
                 if a["key"].endswith(".json") and a["key"].split("/")[0] in ("templates", "sections", "config")]
    steps = len(keys) + 2
    refs = {}
    for n, (t, key) in enumerate(keys, 1):
        job.progress(n, steps, f"{t['name']}: {key}")
        a = dst.get(f"themes/{t['id']}/assets.json", params={"asset[key]": key})
        value = (safe_json(a).get("asset", {}).get("value") or "") if a is not None else ""
        value = value.replace("\\/", "/")
        for kind, handle in THEME_REF_RE.findall(value):
            refs.setdefault(kind, {}).setdefault(unquote(handle.split("/")[0]), (t["name"], key))
    job.progress(len(keys), steps, "Store ke products / collections / files se mila raha hai")
    have = dict(_store_have(dst), shop_images={f[0] for f in list_files(dst)[0]})
    total, missing = 0, {}
    for kind, items in refs.items():
        for handle, where in items.items():
            if kind == "collections" and handle == "all":
                continue
            total += 1
            if handle not in have.get(kind, set()):
                missing.setdefault(kind, {})[handle] = where

    fixed, old_refs = 0, 0
    if src is not None and missing:
        job.progress(len(keys) + 1, steps, "Missing cheezein source store me check ho rahi hain")
        src_files = {f[0]: f for f in list_files(src)[0]}
        src_have = dict(_store_have(src), shop_images=set(src_files))
        todo = [(n, src_files[n][1], src_files[n][2], src_files[n][3]) for n in missing.get("shop_images", {})
                if n in src_files and src_files[n][2] != "VIDEO"]
        if todo:
            job.log(f"{len(todo)} theme images source me hain magar yahan nahi -- abhi copy ho rahi hain...")
            create_files_from_urls(dst, todo, job)
            now = {f[0] for f in list_files(dst)[0]}
            for name, *_ in todo:
                if name in now:
                    missing["shop_images"].pop(name, None)
                    fixed += 1
                    job.ok(f"Theme image copy ho gayi: {name}")
        for kind in list(missing):
            for handle, (tname, key) in list(missing[kind].items()):
                if handle not in src_have.get(kind, set()):
                    old_refs += 1
                    missing[kind].pop(handle)
                    job.log(f"{kind}/{handle} ({tname}: {key}) source store me bhi nahi tha -- theme ka purana/demo "
                            "reference hai, store par koi asar nahi", "info")
    real = sum(len(v) for v in missing.values())
    for kind, items in missing.items():
        for handle, (tname, key) in items.items():
            job.note(f"Theme '{tname}' ({key}): {kind}/{handle} store me NAHI hai")
    job.progress(steps, steps, f"{total} links check hue")
    job.add("Theme check", "references", total)
    if fixed:
        job.add("Theme check", "auto_fixed", fixed)
    if old_refs:
        job.add("Theme check", "old_refs", old_refs)
    job.add("Theme check", "missing", real)
    if real:
        job.warn(f"Theme {names}: {total} references me se {real} missing")
    else:
        extra = f" ({fixed} khud copy ki, {old_refs} purane demo references -- koi asar nahi)" if fixed or old_refs else ""
        job.ok(f"Theme {names}: saare zaroori references maujood hain{extra}")
