"""MODE 3: WooCommerce (WordPress) store -> Shopify."""
import itertools
import json
from urllib.parse import urlparse

import requests

from ..core.shopify import BROWSER_UA, compact, safe_json, short_err, slugify

STEPS = [
    ("fetch", "WooCommerce data fetch"),
    ("products", "Products + variants + inventory"),
    ("collections", "Categories → Collections"),
    ("redirects", "SEO redirects (purane URLs)"),
]
VERIFY_STEPS = [("fetch", "WooCommerce data fetch"), ("verify", "Kya missing hai (sirf report)")]
WEIGHT_UNITS = {"kg": "kg", "g": "g", "lbs": "lb", "lb": "lb", "oz": "oz"}


class Woo:
    def __init__(self, session, url, ck, cs, job=None):
        url = (url or "").strip().rstrip("/")
        self.url = url if url.startswith("http") else "https://" + url
        self.ck, self.cs, self.s, self.job = ck.strip(), cs.strip(), session, job
        self.mode = "query"          # query | basic | rest_route

    def _endpoint(self, path):
        if self.mode == "rest_route":
            return f"{self.url}/?rest_route=/wc/v3/{path}"
        return f"{self.url}/wp-json/wc/v3/{path}"

    def get(self, path, params=None, timeout=40):
        if self.job:
            self.job.check()
        params = dict(params or {})
        headers = {"User-Agent": BROWSER_UA, "Accept": "application/json"}
        auth = None
        if self.mode == "basic":
            auth = (self.ck, self.cs)
        else:
            params.update(consumer_key=self.ck, consumer_secret=self.cs)
        try:
            return self.s.get(self._endpoint(path), params=params, headers=headers, auth=auth, timeout=timeout)
        except requests.RequestException:
            return None

    def connect(self):
        """Teen tareeqe try karta hai (query keys, Basic auth, ?rest_route=)."""
        last = None
        for mode in ("query", "basic", "rest_route"):
            self.mode = mode
            r = self.get("products", {"per_page": 1})
            last = r
            if r is not None and r.status_code == 200 and isinstance(safe_json(r), list):
                return True, f"WooCommerce connect ho gaya ({mode})."
        if last is None:
            return False, "WordPress site tak connection nahi hua -- URL check karo."
        if last.status_code in (401, 403):
            return False, "Keys ghalat hain ya permission 'Read' nahi (401/403)."
        if last.status_code == 404:
            return False, "WooCommerce REST API nahi mila (404) -- WooCommerce active hai? Permalinks 'Post name' karo."
        return False, short_err(last)

    def all(self, path, params=None, quiet=False):
        items = []
        for page in itertools.count(1):
            r = self.get(path, dict(params or {}, per_page=100, page=page))
            if r is None or r.status_code != 200:
                break
            batch = safe_json(r)
            if not isinstance(batch, list) or not batch:
                break
            items.extend(batch)
            if self.job and not quiet:
                self.job.progress(len(items), None, f"WooCommerce {path.split('/')[-1]}: {len(items)} mile")
            total = r.headers.get("X-WP-TotalPages")
            if (total and page >= int(total)) or len(batch) < 100:
                break
        return items

    def weight_unit(self):
        r = self.get("settings/products/woocommerce_weight_unit")
        return WEIGHT_UNITS.get(str(safe_json(r).get("value", "kg")).lower(), "kg") if r is not None and r.status_code == 200 else "kg"


# ------------------------------------------------------------- categories
def ancestor_map(categories):
    by_id = {c["id"]: c for c in categories}
    cache = {}

    def chain(cid):
        if cid in cache:
            return cache[cid]
        out, seen, cur = [], set(), cid
        while cur and cur in by_id and cur not in seen:
            seen.add(cur)
            out.append(by_id[cur])
            cur = by_id[cur].get("parent") or None
        cache[cid] = out
        return out
    return by_id, chain


def product_categories(wp, by_id, chain):
    """Product ki categories + unke parents (rollup)."""
    out = {}
    for c in wp.get("categories", []):
        for cat in (chain(c["id"]) if c.get("id") in by_id else [c]):
            out[cat.get("slug") or slugify(cat.get("name"))] = cat
    return list(out.values())


# ------------------------------------------------------------- product payload
def _price_pair(obj, parent=None):
    sale = obj.get("sale_price") or ""
    regular = obj.get("regular_price") or ""
    price = sale or obj.get("price") or regular or (parent or {}).get("price") or "0.00"
    compare = regular if sale and regular and _num(regular) > _num(sale) else None
    return str(price), compare


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _stock(obj):
    if obj.get("manage_stock") in (True, "parent") and obj.get("stock_quantity") is not None:
        return "shopify", int(obj.get("stock_quantity") or 0)
    return None, None


def build_payload(wp, variations, weight_unit):
    """Returns (payload, variant_meta). variant_meta: [(qty or None, image_src or None)] variant order me."""
    images, seen_src = [], set()
    for img in wp.get("images", []):
        if img.get("src") and img["src"] not in seen_src:
            seen_src.add(img["src"])
            images.append(compact({"src": img["src"], "alt": img.get("alt") or None}))
    var_attrs = [a for a in wp.get("attributes", []) if a.get("variation")][:3]
    names = [a.get("name") or f"Option {i + 1}" for i, a in enumerate(var_attrs)]
    all_values = {a.get("name"): list(a.get("options") or []) for a in var_attrs}
    variants, meta, seen = [], [], set()

    def add_variant(values, src_obj, parent=None):
        key = tuple(values)
        if key in seen or len(variants) >= 100:
            return
        seen.add(key)
        price, compare = _price_pair(src_obj, parent)
        stock_src = parent if (parent and src_obj.get("manage_stock") in ("parent", None)) else src_obj
        mgmt, qty = _stock(stock_src)
        variant = compact({
            "price": price, "compare_at_price": compare, "sku": src_obj.get("sku") or None,
            "barcode": src_obj.get("global_unique_id") or None,
            "weight": _num(src_obj.get("weight") or (parent or {}).get("weight")) or None,
            "weight_unit": weight_unit if (src_obj.get("weight") or (parent or {}).get("weight")) else None,
            "inventory_management": mgmt,
            "inventory_policy": "continue" if src_obj.get("backorders") in ("yes", "notify") else "deny",
            "requires_shipping": not bool(src_obj.get("virtual") or (parent or {}).get("virtual")),
            "taxable": (src_obj.get("tax_status") or (parent or {}).get("tax_status") or "taxable") == "taxable"})
        for i, v in enumerate(values[:3]):
            variant[f"option{i + 1}"] = v
        variants.append(variant)
        img = (src_obj.get("image") or {}).get("src") if src_obj is not parent else None
        if img and img not in seen_src:
            seen_src.add(img)
            images.append({"src": img})
        meta.append((qty, img))

    if wp.get("type") == "variable" and variations and var_attrs:
        for v in variations:
            chosen = {a.get("name"): a.get("option") for a in v.get("attributes") or []}
            # "Any Size" wali variation -> har value ke liye variant
            choices = [[chosen[n]] if chosen.get(n) else (all_values.get(n) or ["Default"]) for n in names]
            for combo in itertools.product(*choices):
                add_variant(list(combo), v, wp)
        options = []
        for i, n in enumerate(names):
            vals = list(dict.fromkeys(var[f"option{i + 1}"] for var in variants if var.get(f"option{i + 1}")))
            options.append({"name": n, "values": vals or ["Default"]})
    else:
        add_variant(["Default Title"], wp)
        options = [{"name": "Title", "values": ["Default Title"]}]

    cats = [c.get("name") for c in wp.get("categories", []) if c.get("name")]
    status = {"publish": "active", "draft": "draft", "pending": "draft", "private": "draft"}.get(wp.get("status"), "active")
    brands = [b.get("name") for b in wp.get("brands") or [] if b.get("name")]
    payload = {"product": compact({
        "title": (wp.get("name") or "").strip(), "handle": wp.get("slug") or None,
        "body_html": wp.get("description") or wp.get("short_description") or "",
        "vendor": brands[0] if brands else None, "product_type": cats[0] if cats else None,
        "tags": ", ".join(t.get("name") for t in wp.get("tags", []) if t.get("name")) or None,
        "status": status, "published": status == "active",
        "options": options, "variants": variants, "images": images or None})}
    return payload, meta


def extra_attributes(wp):
    return {a["name"]: a.get("options") for a in wp.get("attributes", []) if not a.get("variation") and a.get("name")}


# ------------------------------------------------------------- steps
def fetch_all(job, woo, include_drafts):
    job.log("Products fetch ho rahe hain...")
    products = woo.all("products", {"status": "any" if include_drafts else "publish"})
    job.log(f"{len(products)} products mile. Categories fetch ho rahi hain...")
    categories = woo.all("products/categories")
    job.log(f"{len(categories)} categories mili (parent + child).")
    job.add("WooCommerce", "products", len(products))
    job.add("WooCommerce", "categories", len(categories))
    return products, categories


def step_products(job, woo, dst, products, opts):
    weight_unit = woo.weight_unit()
    existing = dst.handles("products")
    existing_titles = {p["title"].strip().lower(): p["id"]
                       for p in dst.get_all("products.json?limit=250&fields=id,title", "products") if p.get("title")}
    location = dst.primary_location_id()
    if not location:
        job.note("Shopify location nahi mili -- stock quantity copy nahi hogi (read_locations scope)")
    ids = {}
    for i, wp in enumerate(products, 1):
        job.progress(i, len(products), wp.get("name"))
        slug, title = wp.get("slug"), (wp.get("name") or "").strip()
        if slug in existing or title.lower() in existing_titles:
            ids[wp["id"]] = existing.get(slug) or existing_titles.get(title.lower())
            job.add("Products", "already")
            job.log(f"Pehle se maujood product: {title}")
            continue
        if wp.get("type") == "variable":
            job.detail(f"{title}: variations aa rahi hain...")
        variations = woo.all(f"products/{wp['id']}/variations", quiet=True) if wp.get("type") == "variable" else []
        payload, meta = build_payload(wp, variations, weight_unit)
        if len(payload["product"]["variants"]) >= 100:
            job.note(f"'{title}': 100 se zyada variants -- pehle 100 import hue (Shopify REST limit)")
        r = dst.post("products.json", payload)
        if r is None or r.status_code not in (200, 201):
            job.add("Products", "failed")
            job.note(f"Product '{title}' -- {short_err(r)}")
            continue
        created = safe_json(r).get("product", {})
        ids[wp["id"]] = created["id"]
        existing[created.get("handle")] = created["id"]
        new_variants = created.get("variants", [])
        img_by_src = {}
        for src_img, new_img in zip(payload["product"].get("images") or [], created.get("images", [])):
            img_by_src[src_img["src"]] = new_img["id"]
        groups = {}
        for (qty, img), nv in zip(meta, new_variants):
            if img and img in img_by_src:
                groups.setdefault(img_by_src[img], []).append(nv["id"])
            if location and qty is not None and nv.get("inventory_item_id"):
                s = dst.post("inventory_levels/set.json", {"location_id": location,
                                                           "inventory_item_id": nv["inventory_item_id"], "available": qty})
                if s is None or s.status_code != 200:
                    job.note(f"Stock '{title}' -- {short_err(s)}")
                    if s is not None and s.status_code == 403:
                        location = None
        for img_id, vids in groups.items():
            dst.put(f"products/{created['id']}/images/{img_id}.json", {"image": {"id": img_id, "variant_ids": vids}})
        attrs = extra_attributes(wp)
        if attrs and opts.get("attributes", True):
            dst.post(f"products/{created['id']}/metafields.json", {"metafield": {
                "namespace": "custom", "key": "woo_attributes", "type": "json", "value": json.dumps(attrs)}})
        job.add("Products", "created")
        job.ok(f"Product: {title}  ({len(new_variants)} variants, {len(created.get('images', []))} images)")
    return ids


def step_collections(job, dst, products, categories, ids):
    by_id, chain = ancestor_map(categories)
    members = {}
    for wp in products:
        for cat in product_categories(wp, by_id, chain):
            if wp["id"] in ids:
                members.setdefault(cat.get("slug") or slugify(cat.get("name")), []).append(ids[wp["id"]])
    existing = {**dst.handles("custom_collections"), **dst.handles("smart_collections")}
    cats = [c for c in categories if c.get("slug") != "uncategorized" or members.get("uncategorized")]
    for i, c in enumerate(cats, 1):
        job.progress(i, len(cats), c.get("name"))
        handle = c.get("slug") or slugify(c.get("name"))
        pids = list(dict.fromkeys(members.get(handle, [])))
        if handle in existing:
            cid = existing[handle]
            have = {x["product_id"] for x in dst.get_all(f"collects.json?collection_id={cid}&limit=250", "collects")}
            for pid in pids:
                if pid not in have:
                    dst.post("collects.json", {"collect": {"collection_id": cid, "product_id": pid}})
            job.add("Collections", "already")
            job.log(f"Pehle se maujood collection: {handle}")
            continue
        img = c.get("image") or {}
        r = dst.post("custom_collections.json", {"custom_collection": compact({
            "title": c.get("name"), "handle": handle, "body_html": c.get("description") or None, "published": True,
            "image": compact({"src": img.get("src"), "alt": img.get("alt") or None}) if img.get("src") else None,
            "collects": [{"product_id": p} for p in pids[:250]]})})
        if r is None or r.status_code not in (200, 201):
            job.add("Collections", "failed")
            job.note(f"Collection '{c.get('name')}' -- {short_err(r)}")
            continue
        cid = safe_json(r)["custom_collection"]["id"]
        for pid in pids[250:]:
            dst.post("collects.json", {"collect": {"collection_id": cid, "product_id": pid}})
        job.add("Collections", "created")
        job.ok(f"Collection: {c.get('name')}  ({len(pids)} products)")


def step_redirects(job, dst, products, categories, ids):
    pairs = []
    for wp in products:
        if wp["id"] in ids and wp.get("permalink"):
            path = urlparse(wp["permalink"]).path
            if path and path != "/":
                pairs.append((path, f"/products/{wp.get('slug')}"))
    for c in categories:
        if c.get("slug"):
            pairs.append((f"/product-category/{c['slug']}/", f"/collections/{c['slug']}"))
    for i, (path, target) in enumerate(pairs, 1):
        job.progress(i, len(pairs), path)
        r = dst.post("redirects.json", {"redirect": {"path": path, "target": target}})
        if r is not None and r.status_code in (200, 201):
            job.add("Redirects", "created")
        elif r is not None and r.status_code == 422:
            job.add("Redirects", "already")
        else:
            job.add("Redirects", "failed")
            if r is not None and r.status_code == 403:
                job.note("Redirects ke liye write_online_store_navigation scope chahiye")
                return


def step_verify(job, dst, products, categories):
    job.progress(1, 3, "Shopify products check")
    handles = set(dst.handles("products"))
    titles = {p["title"].strip().lower() for p in dst.get_all("products.json?limit=250&fields=title", "products")}
    missing = [p.get("name") for p in products if p.get("slug") not in handles and (p.get("name") or "").strip().lower() not in titles]
    job.progress(2, 3, "Shopify collections check")
    cols = set(dst.handles("custom_collections")) | set(dst.handles("smart_collections"))
    job.progress(3, 3, "Report tayar")
    missing_c = [c.get("name") for c in categories if c.get("slug") not in cols and c.get("slug") != "uncategorized"]
    job.add("Verify", "products_missing", len(missing))
    job.add("Verify", "collections_missing", len(missing_c))
    for name in missing[:200]:
        job.note(f"Product missing: {name}")
    for name in missing_c[:200]:
        job.note(f"Collection missing: {name}")
    if not missing and not missing_c:
        job.ok("Sab kuch maujood hai -- import ki zaroorat nahi.")
    else:
        job.warn(f"{len(missing)} products aur {len(missing_c)} collections missing -- 'Import' chalao, maujood cheezein skip hongi.")


def run(job, p):
    session, dst = p["web_session"], p["dest"]
    woo = Woo(session, p["wc_url"], p["ck"], p["cs"], job)
    steps = set(p.get("steps") or [k for k, _ in STEPS])
    with job.step("fetch"):
        ok, msg = woo.connect()
        (job.ok if ok else job.error)(msg)
        if not ok:
            raise RuntimeError(msg)
        products, categories = fetch_all(job, woo, p.get("include_drafts"))
    if p.get("verify_only"):
        with job.step("verify"):
            step_verify(job, dst, products, categories)
        return
    ids = {}
    for key in ("products", "collections", "redirects"):
        if key not in steps:
            job.skip_step(key)
            continue
        with job.step(key):
            if key == "products":
                ids = step_products(job, woo, dst, products, p.get("options") or {})
            elif key == "collections":
                if not ids:
                    handles = dst.handles("products")
                    ids = {wp["id"]: handles[wp["slug"]] for wp in products if wp.get("slug") in handles}
                step_collections(job, dst, products, categories, ids)
            else:
                step_redirects(job, dst, products, categories, ids)
    job.link("Shopify products kholo", f"https://{dst.domain}/admin/products")
