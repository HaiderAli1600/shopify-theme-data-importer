"""MODE 2: Live Shopify store -> Shopify store (exact migration)."""
import base64
import os
import zipfile
from datetime import datetime

from ..core.shopify import (compact, copy_metafields, create_files_from_urls, download_to_temp,
                            list_files, rewrite_cdn_urls, safe_json, short_err, upload_local_file,
                            verify_theme_refs, wait_file_urls)

STEPS = [
    ("files", "Files (banners, logos, PDFs, videos)"),
    ("products", "Products + variants + inventory"),
    ("collections", "Collections (manual + smart rules)"),
    ("blogs", "Blogs + articles"),
    ("pages", "Pages"),
    ("menus", "Navigation menus"),
    ("shopmeta", "Store metafields"),
    ("theme", "Theme copy (unpublished)"),
    ("verify", "Verify theme links"),
]
VARIANT_FIELDS = ("option1", "option2", "option3", "price", "compare_at_price", "sku", "barcode",
                  "weight", "weight_unit", "taxable", "requires_shipping", "inventory_policy",
                  "inventory_management")


class Maps:
    def __init__(self):
        self.product, self.collection, self.page, self.blog, self.article = {}, {}, {}, {}, {}
        self.files = {}
        self.theme_id = None

    def gid_map(self):
        m = {}
        for kind, table in (("Product", self.product), ("Collection", self.collection), ("Page", self.page),
                            ("Blog", self.blog), ("Article", self.article)):
            for s, d in table.items():
                m[f"gid://shopify/{kind}/{s}"] = f"gid://shopify/{kind}/{d}"
        return m


# ---------------------------------------------------------------- files
def step_files(job, session, src, dst, maps):
    job.detail("Source ki files ki list aa rahi hai...")
    files, errors = list_files(src)
    if errors:
        raise PermissionError(f"Source files list nahi hui: {errors} (read_files scope)")
    product_files, perr = list_files(src, "used_in:product")
    if not perr:
        used = {f[0] for f in product_files}
        files = [f for f in files if f[0] not in used]
        job.log(f"{len(used)} product images chhodi -- woh products ke saath same naam se aayengi")
    existing = {f[0] for f in list_files(dst)[0]}
    todo = [f for f in files if f[0] and f[0] not in existing]
    job.log(f"{len(files)} files mili: {len(files) - len(todo)} pehle se maujood, {len(todo)} upload hongi")
    job.add("Files", "source", len(files))
    job.add("Files", "already", len(files) - len(todo))
    plain = [(f[0], f[1], f[2], f[3]) for f in todo if f[2] != "VIDEO"]
    created = create_files_from_urls(dst, plain, job)
    for n, (fname, url, _c, alt, mime, _s) in enumerate([f for f in todo if f[2] == "VIDEO"], 1):
        job.progress(n, None, f"video: {fname}")
        tmp = None
        try:
            tmp = download_to_temp(session, url, os.path.splitext(fname)[1])
            fid, err = upload_local_file(session, dst, tmp, fname, alt, "VIDEO", mime)
        except Exception as e:  # noqa: BLE001
            fid, err = None, str(e)
        finally:
            if tmp and os.path.exists(tmp):
                os.remove(tmp)
        if fid:
            created[fname] = fid
            job.add("Files", "uploaded")
            job.ok(f"Video upload: {fname}")
        else:
            job.add("Files", "failed")
            job.note(f"Video '{fname}': {err}")
    job.log("Files process ho rahi hain (naye links ke liye wait)...")
    urls = wait_file_urls(dst, created.values(), job)
    by_id = {v: k for k, v in created.items()}
    maps.files = {by_id[i]: u for i, u in urls.items() if u}
    for f in list_files(dst)[0]:                       # pehle se maujood files ke links bhi
        maps.files.setdefault(f[0], f[1])


# ---------------------------------------------------------------- products
def product_payload(sp, file_map):
    variants = [compact({k: v.get(k) for k in VARIANT_FIELDS}) for v in sp.get("variants", [])]
    images = [compact({"src": i.get("src"), "alt": i.get("alt") or None, "position": i.get("position")})
              for i in sp.get("images", []) if i.get("src")]
    options = [{"name": o.get("name"), "values": o.get("values", [])} for o in sp.get("options", [])]
    return {"product": compact({
        "title": sp.get("title"), "handle": sp.get("handle"),
        "body_html": rewrite_cdn_urls(sp.get("body_html") or "", file_map),
        "vendor": sp.get("vendor"), "product_type": sp.get("product_type"), "tags": sp.get("tags"),
        "status": sp.get("status"), "template_suffix": sp.get("template_suffix") or None,
        "published_scope": sp.get("published_scope"), "published": bool(sp.get("published_at")),
        "options": options or None, "variants": variants or None, "images": images or None})}


def vkey(v):
    return (v.get("option1"), v.get("option2"), v.get("option3"))


def variant_image_groups(sp, created):
    """{new_image_id: [new_variant_ids]} -- image position se match (filename se nahi)."""
    src_pos = {img["id"]: img.get("position") or i + 1 for i, img in enumerate(sp.get("images", []))}
    new_pos = {img.get("position") or i + 1: img["id"] for i, img in enumerate(created.get("images", []))}
    new_var = {vkey(v): v["id"] for v in created.get("variants", [])}
    groups = {}
    for v in sp.get("variants", []):
        if v.get("image_id") in src_pos:
            img, var = new_pos.get(src_pos[v["image_id"]]), new_var.get(vkey(v))
            if img and var:
                groups.setdefault(img, []).append(var)
    return groups


def step_products(job, src, dst, maps, opts):
    products = src.get_all("products.json?limit=250", "products")
    existing = dst.handles("products")
    location = dst.primary_location_id() if opts.get("inventory", True) else None
    if opts.get("inventory", True) and not location:
        job.note("Destination location nahi mili -- inventory copy nahi hoga (read_locations scope)")
    job.add("Products", "source", len(products))
    for i, sp in enumerate(products, 1):
        job.progress(i, len(products), sp.get("title"))
        title, handle = sp.get("title"), sp.get("handle")
        if handle in existing:
            maps.product[sp["id"]] = existing[handle]
            job.add("Products", "already")
            job.log(f"Pehle se maujood: {handle}")
            continue
        r = dst.post("products.json", product_payload(sp, maps.files))
        if r is None or r.status_code not in (200, 201):
            job.add("Products", "failed")
            job.note(f"Product '{title}' -- {short_err(r)}")
            continue
        created = safe_json(r).get("product", {})
        pid = created["id"]
        maps.product[sp["id"]] = pid
        existing[created.get("handle")] = pid
        if created.get("handle") != handle:
            job.note(f"Product '{title}': handle '{handle}' ki jagah '{created.get('handle')}' bana")
        want = len([x for x in sp.get("images", []) if x.get("src")])
        for _ in range(3):
            if len(created.get("images", [])) >= want:
                break
            job.sleep(3)
            g = dst.get(f"products/{pid}.json")
            if g is not None and g.status_code == 200:
                created = safe_json(g).get("product", created)
        if len(created.get("images", [])) < want:
            job.note(f"Product '{title}': {want} me se {len(created.get('images', []))} images aayi")
        linked = 0
        for img_id, vids in variant_image_groups(sp, created).items():
            u = dst.put(f"products/{pid}/images/{img_id}.json", {"image": {"id": img_id, "variant_ids": vids}})
            if u is not None and u.status_code == 200:
                linked += len(vids)
            else:
                job.note(f"Product '{title}': variant image link -- {short_err(u)}")
        job.add("Products", "variant_images", linked)
        if location:
            by_key = {vkey(v): v for v in created.get("variants", [])}
            for v in sp.get("variants", []):
                nv = by_key.get(vkey(v))
                if not nv or v.get("inventory_management") != "shopify":
                    continue
                s = dst.post("inventory_levels/set.json", {"location_id": location,
                                                           "inventory_item_id": nv["inventory_item_id"],
                                                           "available": int(v.get("inventory_quantity") or 0)})
                if s is None or s.status_code != 200:
                    job.note(f"Inventory '{title}' -- {short_err(s)}")
                    if s is not None and s.status_code == 403:
                        location = None
                    break
        if opts.get("metafields", True):
            copy_metafields(src, dst, f"products/{sp['id']}", f"products/{pid}", job, f"Product '{title}'")
        job.add("Products", "created")
        job.ok(f"Product: {title}  ({len(created.get('images', []))} images, {linked} variant images)")


# ---------------------------------------------------------------- collections
def collection_base(sc, file_map):
    img = sc.get("image") or {}
    return compact({
        "title": sc.get("title"), "handle": sc.get("handle"),
        "body_html": rewrite_cdn_urls(sc.get("body_html") or "", file_map),
        "sort_order": sc.get("sort_order"), "template_suffix": sc.get("template_suffix") or None,
        "published_scope": sc.get("published_scope"), "published": bool(sc.get("published_at")),
        "image": compact({"src": img.get("src"), "alt": img.get("alt") or None}) if img.get("src") else None})


def step_collections(job, src, dst, maps, opts):
    custom = src.get_all("custom_collections.json?limit=250", "custom_collections")
    smart = src.get_all("smart_collections.json?limit=250", "smart_collections")
    existing = {**dst.handles("custom_collections"), **dst.handles("smart_collections")}
    total = len(custom) + len(smart)
    job.add("Collections", "source", total)
    n = 0
    for sc in custom:
        n += 1
        job.progress(n, total, sc["title"])
        collects = src.get_all(f"collects.json?collection_id={sc['id']}&limit=250", "collects")
        collects.sort(key=lambda c: c.get("position") or 0)
        pids = [maps.product[c["product_id"]] for c in collects if c["product_id"] in maps.product]
        if len(pids) < len(collects):
            job.note(f"Collection '{sc['title']}': {len(collects) - len(pids)} products map nahi hue")
        if sc["handle"] in existing:
            cid = existing[sc["handle"]]
            have = {c["product_id"] for c in dst.get_all(f"collects.json?collection_id={cid}&limit=250", "collects")}
            for pid in pids:
                if pid not in have:
                    dst.post("collects.json", {"collect": {"collection_id": cid, "product_id": pid}})
            maps.collection[sc["id"]] = cid
            job.add("Collections", "already")
            job.log(f"Pehle se maujood collection: {sc['handle']} (missing products add kiye)")
            continue
        payload = collection_base(sc, maps.files)
        payload["collects"] = [{"product_id": p} for p in pids]
        r = dst.post("custom_collections.json", {"custom_collection": payload})
        if r is None or r.status_code not in (200, 201):
            job.add("Collections", "failed")
            job.note(f"Collection '{sc['title']}' -- {short_err(r)}")
            continue
        cid = safe_json(r)["custom_collection"]["id"]
        maps.collection[sc["id"]] = cid
        job.add("Collections", "created")
        if opts.get("metafields", True):
            copy_metafields(src, dst, f"collections/{sc['id']}", f"collections/{cid}", job, f"Collection '{sc['title']}'")
        job.ok(f"Collection (manual): {sc['title']}  ({len(pids)} products)")
    for sc in smart:
        n += 1
        job.progress(n, total, sc["title"])
        if sc["handle"] in existing:
            maps.collection[sc["id"]] = existing[sc["handle"]]
            job.add("Collections", "already")
            job.log(f"Pehle se maujood smart collection: {sc['handle']}")
            continue
        rules = []
        for rule in sc.get("rules") or []:
            if rule.get("condition_object_id"):
                job.note(f"Smart collection '{sc['title']}': metafield rule ({rule.get('column')}) admin me manually lagao")
                continue
            rules.append({k: rule[k] for k in ("column", "relation", "condition") if k in rule})
        if not rules:
            job.add("Collections", "failed")
            job.note(f"Smart collection '{sc['title']}': koi copy-able rule nahi -- manually banao")
            continue
        payload = collection_base(sc, maps.files)
        payload.update(disjunctive=bool(sc.get("disjunctive")), rules=rules)
        r = dst.post("smart_collections.json", {"smart_collection": payload})
        if r is None or r.status_code not in (200, 201):
            job.add("Collections", "failed")
            job.note(f"Smart collection '{sc['title']}' -- {short_err(r)}")
            continue
        cid = safe_json(r)["smart_collection"]["id"]
        maps.collection[sc["id"]] = cid
        job.add("Collections", "created")
        if opts.get("metafields", True):
            copy_metafields(src, dst, f"collections/{sc['id']}", f"collections/{cid}", job, f"Collection '{sc['title']}'")
        job.ok(f"Collection (smart): {sc['title']}  ({len(rules)} rules)")


# ---------------------------------------------------------------- blogs / pages
def article_payload(a, file_map):
    img = a.get("image") or {}
    published = bool(a.get("published_at"))
    return {"article": compact({
        "title": a.get("title"), "handle": a.get("handle"), "author": a.get("author"),
        "body_html": rewrite_cdn_urls(a.get("body_html") or "", file_map),
        "summary_html": rewrite_cdn_urls(a.get("summary_html") or "", file_map) or None,
        "tags": a.get("tags"), "template_suffix": a.get("template_suffix") or None,
        "published": published, "published_at": a.get("published_at") if published else None,
        "image": compact({"src": img.get("src"), "alt": img.get("alt") or None}) if img.get("src") else None})}


def step_blogs(job, src, dst, maps, opts):
    blogs = src.get_all("blogs.json?limit=250", "blogs")
    existing = {b["handle"]: b["id"] for b in dst.get_all("blogs.json?limit=250", "blogs")}
    for sb in blogs:
        job.check()
        job.detail(f"Blog: {sb.get('title')}")
        if sb["handle"] in existing:
            bid = existing[sb["handle"]]
            job.log(f"Pehle se maujood blog: {sb['handle']}")
        else:
            r = dst.post("blogs.json", {"blog": compact({
                "title": sb.get("title"), "handle": sb.get("handle"), "commentable": sb.get("commentable"),
                "template_suffix": sb.get("template_suffix") or None})})
            if r is None or r.status_code not in (200, 201):
                job.note(f"Blog '{sb.get('title')}' -- {short_err(r)}")
                continue
            bid = safe_json(r)["blog"]["id"]
            if opts.get("metafields", True):
                copy_metafields(src, dst, f"blogs/{sb['id']}", f"blogs/{bid}", job, f"Blog '{sb.get('title')}'")
        maps.blog[sb["id"]] = bid
        articles = src.get_all(f"blogs/{sb['id']}/articles.json?limit=250", "articles")
        have = {a["handle"]: a["id"] for a in dst.get_all(f"blogs/{bid}/articles.json?limit=250&fields=id,handle", "articles")}
        job.add("Articles", "source", len(articles))
        for i, a in enumerate(articles, 1):
            job.progress(i, len(articles), f"{sb.get('title')}: {a.get('title')}")
            if a["handle"] in have:
                maps.article[a["id"]] = have[a["handle"]]
                job.add("Articles", "already")
                job.log(f"Pehle se maujood article: {a['handle']}")
                continue
            r = dst.post(f"blogs/{bid}/articles.json", article_payload(a, maps.files))
            if r is None or r.status_code not in (200, 201):
                job.add("Articles", "failed")
                job.note(f"Article '{a.get('title')}' -- {short_err(r)}")
                continue
            aid = safe_json(r)["article"]["id"]
            maps.article[a["id"]] = aid
            job.add("Articles", "created")
            if opts.get("metafields", True):
                copy_metafields(src, dst, f"articles/{a['id']}", f"articles/{aid}", job, f"Article '{a.get('title')}'")
            job.ok(f"Article: {a.get('title')}")


def step_pages(job, src, dst, maps, opts):
    pages = src.get_all("pages.json?limit=250", "pages")
    existing = dst.handles("pages")
    job.add("Pages", "source", len(pages))
    for i, p in enumerate(pages, 1):
        job.progress(i, len(pages), p.get("title"))
        if p["handle"] in existing:
            maps.page[p["id"]] = existing[p["handle"]]
            job.add("Pages", "already")
            job.log(f"Pehle se maujood page: {p['handle']}")
            continue
        r = dst.post("pages.json", {"page": compact({
            "title": p.get("title"), "handle": p.get("handle"), "author": p.get("author"),
            "body_html": rewrite_cdn_urls(p.get("body_html") or "", maps.files),
            "template_suffix": p.get("template_suffix") or None, "published": bool(p.get("published_at"))})})
        if r is None or r.status_code not in (200, 201):
            job.add("Pages", "failed")
            job.note(f"Page '{p.get('title')}' -- {short_err(r)}")
            continue
        pid = safe_json(r)["page"]["id"]
        maps.page[p["id"]] = pid
        job.add("Pages", "created")
        if opts.get("metafields", True):
            copy_metafields(src, dst, f"pages/{p['id']}", f"pages/{pid}", job, f"Page '{p.get('title')}'")
        job.ok(f"Page: {p.get('title')}  (template: {p.get('template_suffix') or 'default'})")


# ---------------------------------------------------------------- menus
ITEM = "title type url resourceId tags"
MENUS_QUERY = """
query($cursor: String) {
  menus(first: 50, after: $cursor) {
    nodes { id handle title isDefault items { %s items { %s items { %s } } } }
    pageInfo { hasNextPage endCursor }
  }
}""" % (ITEM, ITEM, ITEM)
MENU_CREATE = """
mutation($title: String!, $handle: String!, $items: [MenuItemCreateInput!]!) {
  menuCreate(title: $title, handle: $handle, items: $items) { menu { id } userErrors { field message } }
}"""
MENU_UPDATE = """
mutation($id: ID!, $title: String!, $items: [MenuItemUpdateInput!]!) {
  menuUpdate(id: $id, title: $title, items: $items) { menu { id } userErrors { field message } }
}"""
MAPPABLE = {"PRODUCT", "COLLECTION", "PAGE", "BLOG", "ARTICLE"}


def relative_url(url, source_domain):
    from urllib.parse import urlparse
    if not url:
        return url
    p = urlparse(url)
    if p.netloc and (p.netloc == source_domain or p.netloc.endswith(".myshopify.com")):
        return (p.path or "/") + (f"?{p.query}" if p.query else "")
    return url


def convert_items(items, gid_map, source_domain, job, menu):
    out = []
    for it in items or []:
        new = {"title": it["title"], "type": it["type"]}
        url = relative_url(it.get("url"), source_domain)
        if it.get("tags"):
            new["tags"] = it["tags"]
        rid = it.get("resourceId")
        if rid:
            if it["type"] in MAPPABLE and rid in gid_map:
                new["resourceId"] = gid_map[rid]
            elif url:
                new["type"], new["url"] = "HTTP", url
                job.log(f"Menu '{menu}': '{it['title']}' URL link bana ({url})")
            else:
                job.note(f"Menu '{menu}': '{it['title']}' chhod diya (link nahi mila)")
                continue
        elif url:
            new["url"] = url
        if it.get("items"):
            new["items"] = convert_items(it["items"], gid_map, source_domain, job, menu)
        out.append(new)
    return out


def step_menus(job, src, dst, maps):
    menus, errors = src.gql_all(MENUS_QUERY, "menus")
    if errors:
        raise PermissionError(f"Source menus: {errors} (read_online_store_navigation scope)")
    dest, errors = dst.gql_all(MENUS_QUERY, "menus")
    if errors:
        raise PermissionError(f"Destination menus: {errors} (write_online_store_navigation scope)")
    by_handle = {m["handle"]: m["id"] for m in dest}
    gid_map = maps.gid_map()
    for i, m in enumerate(menus, 1):
        job.progress(i, len(menus), m["handle"])
        items = convert_items(m.get("items"), gid_map, src.domain, job, m["handle"])
        if m["handle"] in by_handle:
            data, errs = dst.gql(MENU_UPDATE, {"id": by_handle[m["handle"]], "title": m["title"], "items": items})
            ue = (data.get("menuUpdate") or {}).get("userErrors")
        else:
            data, errs = dst.gql(MENU_CREATE, {"title": m["title"], "handle": m["handle"], "items": items})
            ue = (data.get("menuCreate") or {}).get("userErrors")
        if errs or ue:
            job.add("Menus", "failed")
            job.note(f"Menu '{m['handle']}' -- {errs or ue}")
        else:
            job.add("Menus", "copied")
            job.ok(f"Menu: {m['handle']}  ({len(items)} links)")


# ---------------------------------------------------------------- theme
THEMES_Q = "query { themes(first: 20, roles: [MAIN]) { nodes { id name } } }"
THEME_FILES_Q = """
query($id: ID!, $cursor: String) {
  theme(id: $id) {
    files(first: 250, after: $cursor) {
      nodes {
        filename
        body {
          __typename
          ... on OnlineStoreThemeFileBodyText { content }
          ... on OnlineStoreThemeFileBodyBase64 { contentBase64 }
          ... on OnlineStoreThemeFileBodyUrl { url }
        }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}"""
THEME_CREATE = """
mutation($source: URL!, $name: String!) {
  themeCreate(source: $source, name: $name, role: UNPUBLISHED) {
    theme { id name processing }
    userErrors { field message }
  }
}"""


def export_theme_zip(job, session, src, out_dir):
    data, errors = src.gql(THEMES_Q)
    if errors:
        raise PermissionError(f"Source theme: {errors} (read_themes scope)")
    nodes = (data.get("themes") or {}).get("nodes") or []
    if not nodes:
        raise RuntimeError("Source par published theme nahi mila")
    theme = nodes[0]
    files, errors = src.gql_all(THEME_FILES_Q, "theme.files", {"id": theme["id"]})
    if errors:
        raise PermissionError(f"Theme files: {errors}")
    os.makedirs(out_dir, exist_ok=True)
    safe = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in theme["name"]).strip()
    path = os.path.join(out_dir, f"{src.domain.split('.')[0]}-{safe}-{datetime.now():%Y%m%d-%H%M}.zip")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for n, f in enumerate(files, 1):
            job.progress(n, len(files), f["filename"])
            body = f.get("body") or {}
            if "content" in body:
                z.writestr(f["filename"], body["content"] or "")
            elif "contentBase64" in body:
                z.writestr(f["filename"], base64.b64decode(body["contentBase64"] or ""))
            elif body.get("url"):
                r = session.get(body["url"], timeout=120)
                if r.status_code == 200:
                    z.writestr(f["filename"], r.content)
                else:
                    job.note(f"Theme file '{f['filename']}' download nahi hui")
    job.add("Theme", "files", len(files))
    job.ok(f"Theme '{theme['name']}' ki ZIP bani: {path}")
    return theme["name"], path


def step_theme(job, session, src, dst, maps, out_dir):
    name, path = export_theme_zip(job, session, src, out_dir)
    job.link("Theme ZIP folder kholo", "local:" + os.path.dirname(path))
    r = dst.get("themes.json")
    same = next((t for t in safe_json(r).get("themes", []) if t.get("name") == f"{name} (migrated)"), None) if r is not None else None
    if same:
        maps.theme_id = same["id"]
        job.add("Theme", "already")
        job.log(f"Theme '{name} (migrated)' destination par pehle se hai -- dobara upload nahi kiya. "
                "Naya chahiye to purana theme delete kar ke dobara chalao (ZIP backup ban chuki hai).")
        return
    job.log("Destination store par theme upload ho raha hai (unpublished)...")
    job.detail(f"Theme ZIP upload: {os.path.getsize(path) / 1048576:.1f} MB")
    fid, err = upload_local_file(session, dst, path, os.path.basename(path), None, "FILE", "application/zip")
    if not fid:
        job.note(f"Theme ZIP auto-upload nahi hui ({err}). ZIP yahan hai: {path} -- "
                 "Online Store > Themes > Add theme > Upload zip file se khud upload karo.")
        return
    url = wait_file_urls(dst, [fid], job).get(fid)
    job.detail("Shopify naya theme bana raha hai...")
    data, errs = dst.gql(THEME_CREATE, {"source": url, "name": f"{name} (migrated)"}) if url else ({}, ["zip url nahi mila"])
    res = data.get("themeCreate") or {}
    dst.gql("mutation($ids:[ID!]!){fileDelete(fileIds:$ids){deletedFileIds}}", {"ids": [fid]})
    if errs or res.get("userErrors") or not res.get("theme"):
        job.note(f"Theme create nahi hua ({errs or res.get('userErrors')}). ZIP yahan hai: {path} -- "
                 "Online Store > Themes > Add theme > Upload zip file se upload karo.")
        return
    maps.theme_id = res["theme"]["id"].split("/")[-1]
    for n in range(40):                               # processing ka wait
        job.detail(f"Theme processing ho raha hai... ({n * 3}s)")
        r = dst.get(f"themes/{maps.theme_id}.json")
        if r is not None and r.status_code == 200 and not safe_json(r).get("theme", {}).get("processing"):
            break
        job.sleep(3)
    job.add("Theme", "uploaded")
    job.ok(f"Theme '{name} (migrated)' destination par aa gaya (UNPUBLISHED). Preview kar ke Publish khud karo.")
    job.link("Destination themes", f"https://{dst.domain}/admin/themes")


# ---------------------------------------------------------------- runner
def run(job, p):
    session, src, dst = p["session"], p["source"], p["dest"]
    steps, opts = set(p.get("steps") or [k for k, _ in STEPS]), p.get("options") or {}
    maps = Maps()
    job.log(f"Source: {src.domain}  ->  Destination: {dst.domain}")
    if src.domain == dst.domain:
        raise RuntimeError("Source aur destination ek hi store hain.")
    plan = [
        ("files", lambda: step_files(job, session, src, dst, maps)),
        ("products", lambda: step_products(job, src, dst, maps, opts)),
        ("collections", lambda: step_collections(job, src, dst, maps, opts)),
        ("blogs", lambda: step_blogs(job, src, dst, maps, opts)),
        ("pages", lambda: step_pages(job, src, dst, maps, opts)),
        ("menus", lambda: step_menus(job, src, dst, maps)),
        ("shopmeta", lambda: copy_metafields(src, dst, "", "", job, "Store", top=True)),
        ("theme", lambda: step_theme(job, session, src, dst, maps, p.get("out_dir") or ".")),
        ("verify", lambda: verify_theme_refs(dst, job, maps.theme_id, src)),
    ]
    for key, fn in plan:
        if key not in steps:
            job.skip_step(key)
            continue
        with job.step(key):
            if key in ("collections", "menus"):
                job.detail("Pehle migrate hui cheezon ko handle se match kar raha hai...")
                fill_maps_by_handle(job, src, dst, maps, key)
            fn()
    job.link("Destination admin kholo", f"https://{dst.domain}/admin")


def fill_maps_by_handle(job, src, dst, maps, for_step):
    """Agar products/pages step is dafa nahi chala to purane migrate hue items handle se match karo."""
    try:
        if not maps.product:
            s, d = src.handles("products"), dst.handles("products")
            maps.product.update({sid: d[h] for h, sid in s.items() if h in d})
        if for_step == "menus":
            if not maps.collection:
                s = {**src.handles("custom_collections"), **src.handles("smart_collections")}
                d = {**dst.handles("custom_collections"), **dst.handles("smart_collections")}
                maps.collection.update({sid: d[h] for h, sid in s.items() if h in d})
            if not maps.page:
                s, d = src.handles("pages"), dst.handles("pages")
                maps.page.update({sid: d[h] for h, sid in s.items() if h in d})
            if not maps.blog:
                s = {b["handle"]: b["id"] for b in src.get_all("blogs.json?limit=250", "blogs")}
                d = {b["handle"]: b["id"] for b in dst.get_all("blogs.json?limit=250", "blogs")}
                maps.blog.update({sid: d[h] for h, sid in s.items() if h in d})
    except Exception as e:  # noqa: BLE001
        job.log(f"Handle matching skip: {e}", "debug")
