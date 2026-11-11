"""MODE 4: Kisi bhi website ke blogs -> Shopify blog."""
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..core.shopify import article_handles, compact, get_or_create_blog, safe_json, short_err, slugify
from ..core.web import (article_jsonld, clean_article_html, diagnose, fetch, jsonld_author, jsonld_image,
                        meta, rehost_images, replace_srcs, soup_of)

STEPS = [
    ("discover", "Posts dhoondna"),
    ("scrape", "Har post ka data"),
    ("images", "Images apne store par copy"),
    ("import", "Shopify blog me articles"),
]
SKIP_SEGMENTS = {"tag", "tags", "page", "product", "products", "checkout", "search", "account", "author",
                 "tagged", "category", "categories", "cart", "collections", "pages", "policies", "wp-content",
                 "feed", "login", "wp-admin"}


def clean_url(url):
    url = (url or "").strip()
    if not url.startswith("http"):
        url = "https://" + url
    return url.rstrip("/")


def text_of(html):
    return BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True)


# ------------------------------------------------------------- WordPress REST
def wp_api(session, listing, job):
    """WordPress site ho to /wp-json/wp/v2/posts se seedha saare posts."""
    p = urlparse(listing)
    origin = f"{p.scheme}://{p.netloc}"
    r = fetch(session, f"{origin}/wp-json/wp/v2/posts", job, params={"per_page": 1})
    if r is None or r.status_code != 200 or not isinstance(safe_json(r), list):
        return None
    params = {"per_page": 100, "_embed": 1}
    m = re.search(r"/category/([^/]+)", p.path)
    if m:
        c = fetch(session, f"{origin}/wp-json/wp/v2/categories", job, params={"slug": m.group(1).split("/")[-1]})
        cats = safe_json(c) if c is not None else []
        if isinstance(cats, list) and cats:
            params["categories"] = cats[0]["id"]
            job.log(f"WordPress category '{m.group(1)}' ke posts")
    posts, page = [], 1
    while True:
        r = fetch(session, f"{origin}/wp-json/wp/v2/posts", job, params=dict(params, page=page))
        batch = safe_json(r) if r is not None and r.status_code == 200 else []
        if not isinstance(batch, list) or not batch:
            break
        for wp in batch:
            emb = wp.get("_embedded") or {}
            media = (emb.get("wp:featuredmedia") or [{}])[0] or {}
            terms = [t.get("name") for group in emb.get("wp:term") or [] for t in group or [] if t.get("name")]
            posts.append({
                "url": wp.get("link"), "handle": wp.get("slug"),
                "title": text_of((wp.get("title") or {}).get("rendered")),
                "body_html": (wp.get("content") or {}).get("rendered") or "",
                "summary_html": (wp.get("excerpt") or {}).get("rendered") or None,
                "published_at": (wp.get("date_gmt") + "Z") if wp.get("date_gmt") else wp.get("date"),
                "author": ((emb.get("author") or [{}])[0] or {}).get("name") or "",
                "image": media.get("source_url"), "image_alt": media.get("alt_text") or None,
                "tags": ", ".join(dict.fromkeys(t for t in terms if t.lower() != "uncategorized")),
            })
        job.progress(len(posts), None, f"WordPress API: {len(posts)} posts")
        total = r.headers.get("X-WP-TotalPages")
        if (total and page >= int(total)) or len(batch) < 100:
            break
        page += 1
    return posts


# ------------------------------------------------------------- generic discovery
def sitemap_groups(session, origin, job):
    """{sitemap_file_url: [page urls]} -- index sitemaps ke andar wali files bhi."""
    groups, seen = {}, set()
    todo = [urljoin(origin, p) for p in ("/sitemap.xml", "/sitemap_index.xml", "/post-sitemap.xml",
                                         "/sitemap_blogs_1.xml", "/blog-sitemap.xml")]
    while todo and len(seen) < 30:
        sm = todo.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        r = fetch(session, sm, job, timeout=20)
        if r is None or r.status_code != 200 or ("<urlset" not in r.text and "<sitemapindex" not in r.text):
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        locs = [loc.get_text(strip=True) for loc in soup.find_all("loc") if loc.get_text(strip=True)]
        if soup.find("sitemapindex"):
            todo += [u for u in locs if u not in seen]
        else:
            groups[sm] = locs
    return groups


def sitemap_extra(session, base, links, nav, job):
    """Sirf un sitemap files se posts lo jin me pehle se mila koi post maujood ho
    (ya jinka naam post/blog/article ho) -- taake About/Contact jaise pages na aayein."""
    known = {u.rstrip("/") for u in links}
    extra = set()
    for sm, urls in sitemap_groups(session, f"{base.scheme}://{base.netloc}", job).items():
        has_known = any(u.rstrip("/") in known for u in urls)
        named = re.search(r"(post|blog|article|news)", sm.lower())
        if not has_known and not (named and not known):
            continue
        for u in urls:
            pu = urlparse(u)
            path = pu.path.strip("/")
            if pu.netloc.replace("www.", "") != base.netloc.replace("www.", "") or not path:
                continue
            if path.split("/")[0].lower() in SKIP_SEGMENTS - {"blogs"} or u.rstrip("/") in nav:
                continue
            if re.search(r"\.(xml|jpe?g|png|webp|gif|pdf)$", path, re.I):
                continue
            extra.add(u.split("#")[0])
    return extra


def discover_links(session, listing, job, max_pages=40, max_links=1000):
    base = urlparse(listing)
    queue, seen_pages, links, nav = [listing], set(), set(), set()
    first_status = None
    while queue and len(seen_pages) < max_pages and len(links) < max_links:
        page_url = queue.pop(0)
        if page_url in seen_pages:
            continue
        seen_pages.add(page_url)
        r = fetch(session, page_url, job)
        if page_url == listing:
            for _ in range(2):
                if r is not None:
                    break
                job.sleep(3)
                r = fetch(session, page_url, job)
            first_status = r.status_code if r is not None else None
        if r is None or r.status_code != 200:
            continue
        soup = soup_of(r.text)
        if page_url == listing:
            for area in (soup.find("nav"), soup.find("header"), soup.find("footer")):
                for a in (area.find_all("a", href=True) if area else []):
                    nav.add(urljoin(page_url, a["href"]).split("#")[0].rstrip("/"))
        main = soup.find("main") or soup
        heading_links = set()
        for h in main.find_all(["h1", "h2", "h3", "h4"]):
            a = h.find("a", href=True) or h.find_parent("a", href=True)
            if a:
                heading_links.add(urljoin(page_url, a["href"]).split("#")[0])
        counts, texts = {}, {}
        for a in main.find_all("a", href=True):
            full = urljoin(page_url, a["href"]).split("#")[0]
            if urlparse(full).netloc != base.netloc:
                continue
            counts[full] = counts.get(full, 0) + 1
            t = a.get_text(" ", strip=True)
            if len(t) > len(texts.get(full, "")):
                texts[full] = t
        repeated = {h for h, c in counts.items() if c >= 2}
        long_text = {h for h, t in texts.items() if len(t) >= 25 and not t.isdigit()}
        for full in heading_links | repeated | long_text:
            clean = full.rstrip("/")
            path = urlparse(full).path.strip("/")
            if not path or clean in nav or clean == listing.rstrip("/"):
                continue
            if path.split("/")[0].lower() in SKIP_SEGMENTS or "/tagged/" in f"/{path}/":
                continue
            links.add(full)
        rel_next = soup.find("a", attrs={"rel": re.compile(r"\bnext\b", re.I)}, href=True) or \
            soup.find("link", attrs={"rel": re.compile(r"\bnext\b", re.I)}, href=True)
        if rel_next:
            nxt = urljoin(page_url, rel_next["href"])
            if nxt not in seen_pages and nxt not in queue:
                queue.append(nxt)
        for a in soup.find_all("a", href=True):
            if a.get_text(strip=True).isdigit():
                href = urljoin(page_url, a["href"])
                if urlparse(href).netloc == base.netloc and href not in seen_pages and href not in queue:
                    queue.append(href)
        job.progress(len(seen_pages), None, f"{len(seen_pages)} listing pages, {len(links)} posts")
        job.sleep(0.25)
    if not links:
        job.warn(f"Listing page status: {first_status}. " + (diagnose(listing) if first_status is None else ""))
    # Sitemap se extra posts (JS pagination / Load more wali sites)
    extra = sitemap_extra(session, base, links, nav, job)
    new = extra - links
    if new:
        job.log(f"Sitemap se {len(new)} extra posts mile")
    return sorted(links | extra)[:max_links]


def scrape_generic(session, url, job):
    r = fetch(session, url, job)
    if r is None or r.status_code != 200:
        return None
    soup = soup_of(r.text)
    ld = article_jsonld(soup)
    title = (ld or {}).get("headline") or meta(soup, "og:title") or meta(soup, "twitter:title", "name")
    if not title and soup.find("h1"):
        title = soup.find("h1").get_text(" ", strip=True)
    if not title:
        return None
    title = re.sub(r"\s+", " ", title).strip()
    scope = (soup.find("article") or soup.find(attrs={"class": re.compile(r"\b(post|blog)[-_]?(content|body|entry)\b", re.I)})
             or soup.find("main") or soup)
    for junk in scope.find_all(["nav", "footer", "header", "aside"]):
        junk.decompose()
    body = scope.find(class_=re.compile(r"\b(rte|entry-content|post-content|article-body|blog-content|post-body|article__content)\b", re.I))
    if body is None:
        cands = scope.find_all(["div", "section"])
        body = max(cands, key=lambda t: len(t.get_text(strip=True)), default=None) or scope
    body_html = clean_article_html(body, url)
    if len(text_of(body_html)) < 40:
        body_html = clean_article_html(scope, url)
    image = jsonld_image(ld) or meta(soup, "og:image") or meta(soup, "twitter:image", "name")
    if not image:
        first = soup_of(body_html).find("img")
        image = first.get("src") if first else None
    if image and image.startswith("//"):
        image = "https:" + image
    tags = []
    if ld:
        for key in ("articleSection", "keywords"):
            v = ld.get(key)
            if isinstance(v, list):
                tags += [str(x) for x in v if x]
            elif isinstance(v, str):
                tags += [t.strip() for t in v.split(",") if t.strip()]
    if not tags:
        crumb = soup.find(class_=re.compile("breadcrumb", re.I))
        if crumb:
            tags += [a.get_text(strip=True) for a in crumb.find_all("a")[1:]
                     if a.get_text(strip=True).lower() not in ("home", "blog", "blogs")]
    slug = urlparse(url).path.rstrip("/").split("/")[-1]
    return {
        "url": url, "handle": slugify(re.sub(r"\.html?$", "", slug)) or slugify(title), "title": title,
        "body_html": body_html, "summary_html": None,
        "published_at": (ld or {}).get("datePublished") or meta(soup, "article:published_time"),
        "author": (jsonld_author(ld) or meta(soup, "article:author") or meta(soup, "author", "name") or "").strip(),
        "image": urljoin(url, image) if image else None, "image_alt": None,
        "tags": ", ".join(list(dict.fromkeys(tags))[:8]),
        "description": meta(soup, "og:description") or meta(soup, "description", "name"),
    }


# ------------------------------------------------------------- runner
def run(job, p):
    session, dst = p["web_session"], p["dest"]
    listing = clean_url(p["listing_url"])
    max_posts = int(p.get("max_posts") or 500)
    posts = None
    with job.step("discover"):
        posts = wp_api(session, listing, job)
        if posts is not None:
            job.ok(f"WordPress site mili -- API se {len(posts)} posts (sab se accurate tareeqa)")
            links = []
        else:
            links = discover_links(session, listing, job, max_links=max_posts)
            job.log(f"{len(links)} post links mile")
            if not links:
                raise RuntimeError("Koi post nahi mila. Ho sakta hai site JavaScript se posts load karti ho "
                                   "(infinite scroll / Load more). Blog ki listing URL dobara check karo.")
    with job.step("scrape"):
        if posts is not None:
            for i, post in enumerate(posts[:max_posts], 1):
                job.progress(i, min(len(posts), max_posts), post["title"])
        if posts is None:
            posts = []
            for i, link in enumerate(links[:max_posts], 1):
                job.progress(i, min(len(links), max_posts), link)
                art = scrape_generic(session, link, job)
                if art:
                    posts.append(art)
                else:
                    job.add("Posts", "failed")
                    job.note(f"Post ka data nahi mila: {link}")
                job.sleep(0.3)
        posts = posts[:max_posts]
        job.add("Posts", "found", len(posts))
        job.ok(f"{len(posts)} posts ka data tayar")
    if p.get("rehost_images", True):
        with job.step("images"):
            srcs = [img.get("src") for post in posts for img in soup_of(post["body_html"]).find_all("img") if img.get("src")]
            job.log(f"{len(set(srcs))} content images apne Shopify Files me copy ho rahi hain...")
            mapping = rehost_images(dst, srcs, job)
            for post in posts:
                post["body_html"] = replace_srcs(post["body_html"], mapping)
    else:
        job.skip_step("images")
    with job.step("import"):
        title = (p.get("blog_title") or "").strip() or urlparse(listing).netloc.replace("www.", "").split(".")[0].title()
        blog_id, new = get_or_create_blog(dst, title)
        job.log(f"Shopify blog: '{title}'" + (" (naya bana)" if new else " (pehle se tha)"))
        have, have_titles = article_handles(dst, blog_id)
        for i, post in enumerate(posts, 1):
            job.progress(i, len(posts), post["title"])
            if post.get("handle") in have or post["title"].strip().lower() in have_titles:
                job.add("Articles", "already")
                job.log(f"Pehle se maujood: {post['title']}")
                continue
            summary = post.get("summary_html") or (f"<p>{post['description']}</p>" if post.get("description") else None)
            payload = {"article": compact({
                "title": post["title"], "handle": post.get("handle"), "author": post.get("author") or None,
                "body_html": post["body_html"], "summary_html": summary, "tags": post.get("tags") or None,
                "published": True, "published_at": post.get("published_at") if p.get("keep_dates", True) else None,
                "image": compact({"src": post["image"], "alt": post.get("image_alt")}) if post.get("image") else None})}
            r = dst.post(f"blogs/{blog_id}/articles.json", payload)
            if r is not None and r.status_code == 422 and "image" in r.text.lower() and post.get("image"):
                payload["article"].pop("image", None)          # featured image fail ho to bina image ke
                r = dst.post(f"blogs/{blog_id}/articles.json", payload)
                job.note(f"'{post['title']}': featured image nahi aa saki")
            if r is None or r.status_code not in (200, 201):
                job.add("Articles", "failed")
                job.note(f"Article '{post['title']}' -- {short_err(r)}")
                continue
            have[post.get("handle")] = safe_json(r).get("article", {}).get("id")
            job.add("Articles", "created")
            job.ok(f"Article: {post['title']}")
    job.link("Shopify blog posts kholo", f"https://{dst.domain}/admin/articles")
