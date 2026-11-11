"""Storefront / website scraping helpers (demo store, blogs)."""
import json
import re
import warnings
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .shopify import BROWSER_UA, FILE_CREATE, compact, filename_from_url, wait_file_urls

try:
    from bs4 import XMLParsedAsHTMLWarning
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
except ImportError:  # pragma: no cover
    pass

SCRAPE_HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
ARTICLE_TYPES = {"article", "blogposting", "newsarticle", "techarticle", "report"}


def soup_of(html):
    return BeautifulSoup(html or "", "html.parser")


def fetch(session, url, job=None, timeout=30, **kw):
    if job:
        job.check()
    headers = dict(SCRAPE_HEADERS, **kw.pop("headers", {}))
    try:
        return session.get(url, headers=headers, timeout=timeout, **kw)
    except requests.RequestException:
        return None


def diagnose(url):
    """Connection fail ho to Roman Urdu me wajah."""
    try:
        requests.get(url, headers=SCRAPE_HEADERS, timeout=20)
        return "Doosri koshish me connect ho gaya -- pehle wali ghalti temporary thi."
    except requests.exceptions.SSLError:
        return "SSL/certificate error -- site ka https theek nahi."
    except requests.exceptions.ConnectTimeout:
        return "Site respond nahi kar rahi (slow ya block)."
    except requests.exceptions.ConnectionError:
        return "Connection error (DNS / network / site band)."
    except requests.RequestException as e:
        return str(e)


def meta(soup, name, attr="property"):
    tag = soup.find("meta", attrs={attr: name})
    return tag["content"].strip() if tag and tag.get("content") else None


def iter_jsonld(soup):
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = (tag.string or tag.get_text() or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if not isinstance(item, dict):
                continue
            graph = item.get("@graph")
            if isinstance(graph, list):
                yield from (g for g in graph if isinstance(g, dict))
            yield item


def article_jsonld(soup):
    for obj in iter_jsonld(soup):
        t = obj.get("@type")
        types = {str(x).lower() for x in (t if isinstance(t, list) else [t]) if x}
        if types & ARTICLE_TYPES:
            return obj
    return None


def jsonld_image(obj):
    img = obj.get("image") if obj else None
    if isinstance(img, list) and img:
        img = img[0]
    if isinstance(img, str):
        return img
    if isinstance(img, dict):
        return img.get("url") or img.get("contentUrl")
    return None


def jsonld_author(obj):
    a = (obj or {}).get("author")
    if isinstance(a, list) and a:
        a = a[0]
    if isinstance(a, dict):
        return a.get("name")
    return a if isinstance(a, str) else None


# ------------------------------------------------------------ Shopify CDN
SIZE_SUFFIX = re.compile(
    r"_(?:\d+x\d*|x\d+|pico|icon|thumb|small|compact|medium|large|grande|original|master)"
    r"(?:_crop_[a-z]+)?(?:@\dx)?(?=\.[a-z0-9]+$)", re.I)
SHOP_FILES_RE = re.compile(r"/(?:s/files/(?:\d+/)+files|cdn/shop/files)/", re.I)


def is_shop_file_url(url):
    return bool(SHOP_FILES_RE.search(urlparse(url).path))


def original_cdn_url(url):
    """Resize variant (width=, _600x) ki jagah asal image ka URL + asal filename."""
    if url.startswith("//"):
        url = "https:" + url
    p = urlparse(url)
    base = p.path.rsplit("/", 1)
    name = SIZE_SUFFIX.sub("", unquote(base[-1]))
    keep = [(k, v) for k, v in parse_qsl(p.query) if k == "v"]
    path = (base[0] + "/" if len(base) > 1 else "") + name
    return p._replace(path=path, query=urlencode(keep)).geturl(), name


def extract_image_urls(html, base_url):
    """HTML se har tarah ke image URLs (img, srcset, lazy attrs, style, noscript, JSON)."""
    urls = set()
    soup = soup_of(html)

    def add(u):
        if u and not u.startswith("data:"):
            urls.add(urljoin(base_url, u.strip()))

    def add_srcset(val):
        for part in (val or "").split(","):
            bits = part.strip().split()
            if bits:
                add(bits[0])

    for img in soup.find_all(["img", "source"]):
        for attr in ("src", "data-src", "data-original", "data-lazy", "data-bg", "data-image"):
            add(img.get(attr))
        for attr in ("srcset", "data-srcset", "data-lazy-srcset"):
            add_srcset(img.get(attr))
    for ns in soup.find_all("noscript"):
        for img in soup_of(ns.decode_contents()).find_all("img"):
            add(img.get("src"))
    for tag in soup.find_all(style=True):
        for m in re.findall(r"url\((?:'|\")?(.*?)(?:'|\")?\)", tag["style"]):
            add(m)
    for st in soup.find_all("style"):
        for m in re.findall(r"url\((?:'|\")?(.*?)(?:'|\")?\)", st.get_text()):
            add(m)
    for m in re.findall(r'(?:https?:)?\\?/\\?/[^\s"\'<>]+?\.(?:jpe?g|png|webp|gif|svg|avif)(?:\?[^\s"\'<>\\]*)?',
                        html or "", re.I):
        add(m.replace("\\/", "/"))
    return urls


# ------------------------------------------------------------ re-host images
def rehost_images(dst, urls, job=None):
    """External image URLs -> Shopify Files (har URL ki alag file). Returns {old_url: new_cdn_url}."""
    urls = [u for u in dict.fromkeys(urls) if u and u.startswith("http")]
    inputs, owners = [], []
    for u in urls:
        name = filename_from_url(u)
        if not re.search(r"\.(jpe?g|png|gif|webp|avif|svg)$", name, re.I):
            continue
        inputs.append(compact({"originalSource": u, "filename": re.sub(r"[^\w.\-]+", "-", name)[-120:],
                               "contentType": "FILE" if name.lower().endswith(".svg") else "IMAGE"}))
        owners.append(u)
    ids = {}
    for i in range(0, len(inputs), 10):
        chunk, who = inputs[i:i + 10], owners[i:i + 10]
        data, errs = dst.gql(FILE_CREATE, {"files": chunk})
        res = data.get("fileCreate") or {}
        files = res.get("files") or []
        if not errs and not res.get("userErrors") and len(files) == len(chunk):
            ids.update({f["id"]: u for f, u in zip(files, who)})
        else:
            for inp, u in zip(chunk, who):
                d, e = dst.gql(FILE_CREATE, {"files": [inp]})
                fs = (d.get("fileCreate") or {}).get("files") or []
                if fs and not e:
                    ids[fs[0]["id"]] = u
                elif job:
                    job.add("Images", "failed")
        if job:
            job.progress(min(i + 10, len(inputs)), len(inputs), "images copy ho rahi hain")
    new = wait_file_urls(dst, list(ids), job)
    out = {ids[i]: url for i, url in new.items() if url}
    if job:
        job.add("Images", "rehosted", len(out))
    return out


def replace_srcs(html, mapping):
    if not html or not mapping:
        return html
    soup = soup_of(html)
    changed = False
    for img in soup.find_all("img"):
        src = img.get("src")
        if src in mapping:
            img["src"] = mapping[src]
            changed = True
    return str(soup) if changed else html


def clean_article_html(el, base_url):
    """Body element saaf karo: scripts hatao, image links absolute, lazy attrs theek."""
    for junk in el.find_all(["script", "style", "noscript", "form", "iframe"]):
        if junk.name == "iframe" and junk.get("src") and ("youtube" in junk["src"] or "vimeo" in junk["src"]):
            continue
        junk.decompose()
    for img in el.find_all("img"):
        src = img.get("data-src") or img.get("data-lazy-src") or img.get("src")
        if not src and img.get("srcset"):
            src = img["srcset"].split(",")[0].split()[0]
        if src:
            img["src"] = urljoin(base_url, src)
        for attr in ("srcset", "data-src", "data-srcset", "data-lazy-src", "loading", "sizes", "decoding"):
            if img.has_attr(attr):
                del img[attr]
    return el.decode_contents().strip()
