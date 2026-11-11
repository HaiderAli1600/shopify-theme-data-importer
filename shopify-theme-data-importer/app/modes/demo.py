"""MODE 1: Envato / ThemeForest Shopify demo store (password protected) -> apna store."""
import re
import xml.etree.ElementTree as ET
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse

from ..core.shopify import (compact, create_files_from_urls, list_files, rewrite_cdn_urls, safe_json,
                            short_err, verify_theme_refs)
from ..core.web import (clean_article_html, extract_image_urls, fetch, is_shop_file_url, meta,
                        original_cdn_url, soup_of)
from .migrate import variant_image_groups

STEPS = [
    ("files", "Theme section images (Files)"),
    ("products", "Products + variants + images"),
    ("collections", "Collections"),
    ("blogs", "Blogs + articles"),
    ("pages", "Pages"),
    ("verify", "Verify theme links"),
]


# ------------------------------------------------------------- demo URLs / login
def clean_demo_url(url):
    url = (url or "").strip()
    if not url.startswith("http"):
        url = "https://" + url
    return url.rstrip("/")


def demo_url(base, path=""):
    """Path ke saath preview params (preview_theme_id waghera) barqarar rakho."""
    b = urlparse(base)
    preview = dict(parse_qsl(b.query))
    target = urlparse(urljoin(f"{b.scheme}://{b.netloc}/", path.lstrip("/")))
    q = dict(preview, **dict(parse_qsl(target.query)))
    return target._replace(query=urlencode(q)).geturl()


def with_preview(url, base):
    preview = dict(parse_qsl(urlparse(base).query))
    if not preview:
        return url
    p = urlparse(url)
    return p._replace(query=urlencode(dict(preview, **dict(parse_qsl(p.query))))).geturl()


def login(session, base, password, job=None):
    """Password page se andar jao. Returns (ok, message)."""
    r = fetch(session, demo_url(base, "/"), job)
    if r is None:
        return False, "Demo store tak connection nahi hua -- URL check karo."
    if "/password" not in r.url and r.status_code == 200:
        return True, "Store password protected nahi -- seedha khul gaya."
    if not password:
        return False, "Is demo ka password chahiye."
    fetch(session, demo_url(base, "/password"), job)
    try:
        session.post(demo_url(base, "/password"), timeout=30,
                     data={"form_type": "storefront_password", "utf8": "✓", "password": password},
                     headers={"Referer": demo_url(base, "/password")})
    except Exception:  # noqa: BLE001
        return False, "Password bhejte waqt connection toot gaya."
    check = fetch(session, demo_url(base, "/"), job)
    if check is None:
        return False, "Login ke baad store nahi khula."
    if "/password" in check.url:
        return False, "Password ghalat hai (ya demo URL ghalat)."
    return True, "Demo store login ho gaya."


def storefront_json(session, base, path, key, job, limit_pages=40):
    items, page = [], 1
    while page <= limit_pages:
        if job:
            job.detail(f"Demo se {key} aa rahe hain: {len(items)}...")
        sep = "&" if "?" in path else "?"
        r = fetch(session, demo_url(base, f"{path}{sep}limit=250&page={page}"), job)
        if r is None or r.status_code != 200:
            break
        batch = safe_json(r).get(key, [])
        if not batch:
            break
        items.extend(batch)
        if len(batch) < 250:
            break
        page += 1
    return items


def home_links(session, base, job):
    r = fetch(session, demo_url(base, "/"), job)
    if r is None or r.status_code != 200:
        return set(), ""
    paths = set()
    for a in soup_of(r.text).find_all("a", href=True):
        p = urlparse(urljoin(base + "/", a["href"]))
        if p.netloc == urlparse(base).netloc or not p.netloc:
            paths.add(p.path.rstrip("/"))
    return paths, r.text


# ------------------------------------------------------------- step: images
def sample_pages(session, base, scope, job):
    urls = []
    paths, _ = home_links(session, base, job)
    if scope in ("all", "home"):
        urls.append(demo_url(base, "/"))
    if scope in ("all", "product"):
        items = storefront_json(session, base, "/products.json", "products", job, 1)
        if items:
            urls.append(demo_url(base, f"/products/{items[0]['handle']}"))
    if scope in ("all", "collection"):
        items = storefront_json(session, base, "/collections.json", "collections", job, 1)
        if items:
            urls.append(demo_url(base, f"/collections/{items[0]['handle']}"))
    if scope in ("all", "blog"):
        blogs = sorted({p.split("/")[2] for p in paths if re.match(r"^/blogs/[^/]+$", p)})
        if blogs:
            urls.append(demo_url(base, f"/blogs/{blogs[0]}"))
    if scope in ("all", "pages"):
        pages = sorted(p for p in paths if re.match(r"^/pages/[^/]+$", p))
        urls.extend(demo_url(base, p) for p in pages[:12])
    return list(dict.fromkeys(urls))


def step_files(job, session, base, dst, scope, maps):
    pages = sample_pages(session, base, scope, job)
    job.log(f"{len(pages)} pages scan hongi: " + ", ".join(urlparse(u).path or "/" for u in pages))
    found = set()
    for i, url in enumerate(pages, 1):
        job.progress(i, len(pages), urlparse(url).path or "/")
        r = fetch(session, url, job)
        if r is None or r.status_code != 200:
            job.note(f"Page nahi khula: {url}")
            continue
        found |= extract_image_urls(r.text, url)
        for link in soup_of(r.text).find_all("link", rel="stylesheet", href=True):
            css = fetch(session, urljoin(url, link["href"]), job)
            if css is not None and css.status_code == 200:
                found |= {urljoin(css.url, m) for m in re.findall(r"url\((?:'|\")?(.*?)(?:'|\")?\)", css.text)}
        job.sleep(0.2)
    job.detail("Images ke asal versions nikal raha hai...")
    originals = {}
    for u in found:
        if is_shop_file_url(u):
            url, name = original_cdn_url(u)
            if name:
                originals.setdefault(name, url)
    job.log(f"{len(found)} image links mile -> {len(originals)} asal theme images (Files)")
    job.add("Files", "source", len(originals))
    existing = {f[0] for f in list_files(dst)[0]}
    from ..core.shopify import content_type_for
    todo = [(n, u, content_type_for(n), None) for n, u in sorted(originals.items()) if n not in existing]
    job.add("Files", "already", len(originals) - len(todo))
    create_files_from_urls(dst, todo, job)
    maps.update({f[0]: f[1] for f in list_files(dst)[0]})


# ------------------------------------------------------------- step: products
def demo_product_payload(dp):
    variants = []
    for v in dp.get("variants", []):
        variants.append(compact({
            "option1": v.get("option1"), "option2": v.get("option2"), "option3": v.get("option3"),
            "price": v.get("price"), "compare_at_price": v.get("compare_at_price"), "sku": v.get("sku") or None,
            "weight": v.get("grams"), "weight_unit": "g" if v.get("grams") is not None else None,
            "requires_shipping": v.get("requires_shipping"),
            "taxable": v.get("taxable"), "inventory_policy": "deny"}))
    images = [compact({"src": original_cdn_url(i["src"])[0], "alt": i.get("alt") or None,
                       "position": i.get("position") or n + 1})
              for n, i in enumerate(dp.get("images", [])) if i.get("src")]
    tags = dp.get("tags") or []
    return {"product": compact({
        "title": dp.get("title"), "handle": dp.get("handle"), "body_html": dp.get("body_html") or "",
        "vendor": dp.get("vendor") or None, "product_type": dp.get("product_type") or None,
        "tags": ", ".join(tags) if isinstance(tags, list) else tags, "status": "active", "published": True,
        "options": [{"name": o.get("name"), "values": o.get("values", [])} for o in dp.get("options", [])] or None,
        "variants": variants or None, "images": images or None})}


def as_admin_shape(dp):
    """Storefront JSON (images[].variant_ids) -> variant.image_id shape (migrate helper ke liye)."""
    variants = [dict(v) for v in dp.get("variants", [])]
    by_id = {v["id"]: v for v in variants}
    for img in dp.get("images", []):
        for vid in img.get("variant_ids") or []:
            if vid in by_id:
                by_id[vid]["image_id"] = img["id"]
    for v in variants:
        fi = v.get("featured_image") or {}
        if fi.get("id") and not v.get("image_id"):
            v["image_id"] = fi["id"]
    return {"images": dp.get("images", []), "variants": variants}


def step_products(job, session, base, dst, files_map):
    products = storefront_json(session, base, "/products.json", "products", job)
    existing = dst.handles("products")
    titles = {}
    job.add("Products", "source", len(products))
    for i, dp in enumerate(products, 1):
        job.progress(i, len(products), dp.get("title"))
        if dp.get("handle") in existing:
            job.add("Products", "already")
            job.log(f"Pehle se maujood product: {dp.get('handle')}")
            continue
        payload = demo_product_payload(dp)
        payload["product"]["body_html"] = rewrite_cdn_urls(payload["product"]["body_html"], files_map)
        r = dst.post("products.json", payload)
        if r is None or r.status_code not in (200, 201):
            job.add("Products", "failed")
            job.note(f"Product '{dp.get('title')}' -- {short_err(r)}")
            continue
        created = safe_json(r).get("product", {})
        existing[created.get("handle")] = created["id"]
        titles[dp.get("handle")] = created["id"]
        linked = 0
        for img_id, vids in variant_image_groups(as_admin_shape(dp), created).items():
            u = dst.put(f"products/{created['id']}/images/{img_id}.json", {"image": {"id": img_id, "variant_ids": vids}})
            linked += len(vids) if u is not None and u.status_code == 200 else 0
        job.add("Products", "created")
        job.ok(f"Product: {dp.get('title')}  ({len(created.get('images', []))} images, {linked} variant images)")
    return existing


# ------------------------------------------------------------- step: collections
def step_collections(job, session, base, dst, product_ids):
    collections = [c for c in storefront_json(session, base, "/collections.json", "collections", job)
                   if c.get("handle") != "all"]
    existing = {**dst.handles("custom_collections"), **dst.handles("smart_collections")}
    job.add("Collections", "source", len(collections))
    for i, c in enumerate(collections, 1):
        job.progress(i, len(collections), c.get("title"))
        prods = storefront_json(session, base, f"/collections/{c['handle']}/products.json", "products", job)
        pids = [product_ids[p["handle"]] for p in prods if p.get("handle") in product_ids]
        if c["handle"] in existing:
            cid = existing[c["handle"]]
            have = {x["product_id"] for x in dst.get_all(f"collects.json?collection_id={cid}&limit=250", "collects")}
            added = 0
            for pid in pids:
                if pid not in have:
                    r = dst.post("collects.json", {"collect": {"collection_id": cid, "product_id": pid}})
                    added += 1 if r is not None and r.status_code in (200, 201) else 0
            job.add("Collections", "already")
            job.log(f"Pehle se maujood collection: {c['handle']}")
            if added:
                job.log(f"'{c['title']}' me {added} products add hue")
            continue
        img = c.get("image") or {}
        payload = compact({
            "title": c.get("title"), "handle": c.get("handle"), "body_html": c.get("body_html") or c.get("description"),
            "sort_order": c.get("sort_order") or None, "published": True,
            "image": compact({"src": original_cdn_url(img["src"])[0], "alt": img.get("alt") or None}) if img.get("src") else None,
            "collects": [{"product_id": p} for p in pids]})
        r = dst.post("custom_collections.json", {"custom_collection": payload})
        if r is None or r.status_code not in (200, 201):
            job.add("Collections", "failed")
            job.note(f"Collection '{c.get('title')}' -- {short_err(r)}")
            continue
        job.add("Collections", "created")
        job.ok(f"Collection: {c.get('title')}  ({len(pids)}/{len(prods)} products)")


# ------------------------------------------------------------- step: blogs
ATOM = "{http://www.w3.org/2005/Atom}"


def atom_entries(session, base, handle, job):
    r = fetch(session, demo_url(base, f"/blogs/{handle}.atom"), job)
    if r is None or r.status_code != 200 or "<feed" not in r.text:
        return {}
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError:
        return {}
    out = {}
    for e in root.findall(f"{ATOM}entry"):
        link = e.find(f"{ATOM}link[@rel='alternate']")
        if link is None:
            link = e.find(f"{ATOM}link")
        href = link.get("href") if link is not None else ""
        slug = urlparse(href).path.rstrip("/").split("/")[-1]
        out[slug] = {
            "title": (e.findtext(f"{ATOM}title") or "").strip(),
            "published_at": e.findtext(f"{ATOM}published"),
            "author": (e.findtext(f"{ATOM}author/{ATOM}name") or "").strip(),
            "body_html": e.findtext(f"{ATOM}content") or "",
            "summary_html": e.findtext(f"{ATOM}summary") or None,
            "tags": ", ".join(c.get("term") for c in e.findall(f"{ATOM}category") if c.get("term")),
        }
    return out


def article_links(session, base, handle, job):
    links, page = [], 1
    while page <= 30:
        url = demo_url(base, f"/blogs/{handle}" + (f"?page={page}" if page > 1 else ""))
        r = fetch(session, url, job)
        if r is None or r.status_code != 200:
            break
        found = []
        for a in soup_of(r.text).find_all("a", href=True):
            m = re.match(rf"^/blogs/{re.escape(handle)}/([^/?#]+)$", urlparse(urljoin(base + "/", a["href"])).path)
            if m and m.group(1) != "tagged" and m.group(1) not in links:
                found.append(m.group(1))
        if not found:
            break
        links.extend(dict.fromkeys(found))
        page += 1
    return links


def scrape_article(session, base, handle, slug, job):
    url = demo_url(base, f"/blogs/{handle}/{slug}")
    r = fetch(session, url, job)
    if r is None or r.status_code != 200:
        return None
    soup = soup_of(r.text)
    scope = soup.find("article") or soup.find("main") or soup
    title = meta(soup, "og:title") or (scope.find("h1").get_text(" ", strip=True) if scope.find("h1") else None)
    body_el = scope.find(class_=re.compile(r"\b(rte|article-template__content|article__content|blog-content)\b"))
    if body_el is None:
        cands = scope.find_all(["div", "section"])
        body_el = max(cands, key=lambda t: len(t.get_text(strip=True)), default=None)
    image = meta(soup, "og:image")
    tags = [m.group(1).replace("-", " ") for a in scope.find_all("a", href=True)
            for m in [re.search(r"/tagged/([^/?#]+)", a["href"])] if m]
    return {"title": title, "body_html": clean_article_html(body_el, url) if body_el else "",
            "image": image, "author": meta(soup, "article:author") or meta(soup, "author", "name") or "",
            "published_at": meta(soup, "article:published_time"), "tags": ", ".join(sorted(set(tags))),
            "summary_html": None}


def step_blogs(job, session, base, dst, files_map):
    paths, _ = home_links(session, base, job)
    handles = sorted({p.split("/")[2] for p in paths if re.match(r"^/blogs/[^/.]+$", p)}) or ["news"]
    job.log("Blogs mile: " + ", ".join(handles))
    from ..core.shopify import get_or_create_blog, article_handles
    for handle in handles:
        job.detail(f"Blog '{handle}': feed aur article links aa rahe hain...")
        feed = atom_entries(session, base, handle, job)
        slugs = list(dict.fromkeys(article_links(session, base, handle, job) + list(feed)))
        if not slugs:
            job.log(f"Blog '{handle}' me koi article nahi mila")
            continue
        blog_id, _new = get_or_create_blog(dst, handle.replace("-", " ").title(), handle)
        have, have_titles = article_handles(dst, blog_id)
        job.add("Articles", "source", len(slugs))
        for i, slug in enumerate(slugs, 1):
            job.progress(i, len(slugs), f"{handle}/{slug}")
            if slug in have:
                job.add("Articles", "already")
                job.log(f"Pehle se maujood article: {slug}")
                continue
            page = scrape_article(session, base, handle, slug, job) or {}
            art = dict(page, **{k: v for k, v in feed.get(slug, {}).items() if v})
            if not art.get("title"):
                job.add("Articles", "failed")
                job.note(f"Article '{slug}' ka data nahi mila")
                continue
            if art["title"].strip().lower() in have_titles:
                job.add("Articles", "already")
                continue
            img = art.get("image")
            payload = {"article": compact({
                "title": art["title"], "handle": slug, "author": art.get("author") or None,
                "body_html": rewrite_cdn_urls(art.get("body_html") or "", files_map),
                "summary_html": art.get("summary_html"), "tags": art.get("tags") or None,
                "published": True, "published_at": art.get("published_at"),
                "image": {"src": original_cdn_url(urljoin(base + "/", img))[0]} if img else None})}
            r = dst.post(f"blogs/{blog_id}/articles.json", payload)
            if r is None or r.status_code not in (200, 201):
                job.add("Articles", "failed")
                job.note(f"Article '{art['title']}' -- {short_err(r)}")
                continue
            job.add("Articles", "created")
            job.ok(f"Article: {art['title']}")


# ------------------------------------------------------------- step: pages
def page_templates(dst):
    r = dst.get("themes.json")
    main = next((t for t in safe_json(r).get("themes", []) if t.get("role") == "main"), None) if r is not None else None
    if not main:
        return set()
    r = dst.get(f"themes/{main['id']}/assets.json")
    out = set()
    for a in safe_json(r).get("assets", []) if r is not None else []:
        m = re.match(r"^templates/page\.([^.]+)\.(json|liquid)$", a["key"])
        if m:
            out.add(m.group(1))
    return out


def guess_template(handle, templates):
    if handle in templates:
        return handle
    words = set(handle.split("-"))
    for t in sorted(templates, key=len, reverse=True):
        if t in words or set(t.split("-")) <= words or t.replace("-", "") == handle.replace("-", ""):
            return t
    return None


def step_pages(job, session, base, dst, files_map):
    paths, _ = home_links(session, base, job)
    handles = sorted({p.split("/")[2] for p in paths if re.match(r"^/pages/[^/]+$", p)})
    existing = dst.handles("pages")
    templates = page_templates(dst)
    if templates:
        job.log("Theme ke page templates: " + ", ".join(sorted(templates)))
    job.add("Pages", "source", len(handles))
    for i, handle in enumerate(handles, 1):
        job.progress(i, len(handles), handle)
        if handle in existing:
            job.add("Pages", "already")
            job.log(f"Pehle se maujood page: {handle}")
            continue
        url = demo_url(base, f"/pages/{handle}")
        r = fetch(session, url, job)
        if r is None or r.status_code != 200:
            job.add("Pages", "failed")
            job.note(f"Page '{handle}' nahi khula")
            continue
        soup = soup_of(r.text)
        main = soup.find("main") or soup
        title = (main.find("h1").get_text(" ", strip=True) if main.find("h1") else None) or meta(soup, "og:title") or handle
        body_el = main.find(class_=re.compile(r"\brte\b"))
        template = guess_template(handle, templates)
        r = dst.post("pages.json", {"page": compact({
            "title": title, "handle": handle, "published": True, "template_suffix": template,
            "body_html": rewrite_cdn_urls(clean_article_html(body_el, url), files_map) if body_el else ""})})
        if r is None or r.status_code not in (200, 201):
            job.add("Pages", "failed")
            job.note(f"Page '{title}' -- {short_err(r)}")
            continue
        job.add("Pages", "created")
        job.ok(f"Page: {title}" + (f"  (template: page.{template})" if template else ""))


# ------------------------------------------------------------- runner
def run(job, p):
    session, dst = p["web_session"], p["dest"]
    base = clean_demo_url(p["demo_url"])
    steps = set(p.get("steps") or [k for k, _ in STEPS])
    ok, msg = login(session, base, p.get("password", ""), job)
    (job.ok if ok else job.error)(msg)
    if not ok:
        raise RuntimeError(msg)
    files_map, product_ids = {}, {}
    for key, _label in STEPS:
        if key not in steps:
            job.skip_step(key)
            continue
        with job.step(key):
            if key == "files":
                step_files(job, session, base, dst, p.get("image_scope", "all"), files_map)
            elif key == "products":
                product_ids = step_products(job, session, base, dst, files_map)
            elif key == "collections":
                if not product_ids:
                    product_ids = dst.handles("products")
                step_collections(job, session, base, dst, product_ids)
            elif key == "blogs":
                step_blogs(job, session, base, dst, files_map)
            elif key == "pages":
                step_pages(job, session, base, dst, files_map)
            elif key == "verify":
                verify_theme_refs(dst, job)
    job.link("Store admin kholo", f"https://{dst.domain}/admin")
