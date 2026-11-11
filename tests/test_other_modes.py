import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.jobs import Job                       # noqa: E402
from app.core.shopify import Store                  # noqa: E402
from app.modes import blog, demo, woo               # noqa: E402
from tests.fakes import FakeStore, FakeWeb, Resp    # noqa: E402

CDN = "//cdn.shopify.com/s/files/1/0001/0002/files"


def dest_store(web):
    d = web.store(FakeStore("client-shop.myshopify.com", "dst-token"))
    d.themes = [{"id": 1, "name": "Kitty", "role": "main", "processing": False, "assets": {
        "templates/page.contact.json": "{}", "templates/page.about.json": "{}",
        "templates/index.json": '{"a":"shopify://shop_images/hero.jpg","b":"shopify://shop_images/bg.png"}'}}]
    return d


def run(mode, web, d, params, steps):
    job = Job(mode.__name__, "t", steps)
    job.sleep = lambda s: None
    st = Store(web, d.domain, d.token, "DEST", job)
    st.write_pause = 0
    mode.run(job, dict(params, dest=st, web_session=web))
    return job


# ================================================================== DEMO
def demo_site():
    state = {"logged": False}
    home = f"""<html><head><link rel="stylesheet" href="/cdn/shop/t/5/assets/base.css"></head><body>
    <nav><a href="/collections/chairs">Chairs</a><a href="/pages/about-us">About</a>
    <a href="/pages/contact">Contact</a><a href="/blogs/news">News</a><a href="/blogs/news.atom">rss</a></nav>
    <img src="{CDN}/hero_1200x.jpg?v=1&width=600" srcset="{CDN}/hero.jpg?v=1&width=300 300w, {CDN}/hero.jpg?v=1&width=1200 1200w">
    <div style="background-image:url(/cdn/shop/files/bg.png?v=2&width=3000)"></div>
    <img src="//kitty-demo.myshopify.com/cdn/shop/t/5/assets/logo.svg"><img src="/cdn/shop/products/p1.jpg">
    <script>var x = {{"img":"https:\\/\\/cdn.shopify.com\\/s\\/files\\/1\\/0001\\/0002\\/files\\/promo.webp?v=3"}}</script>
    </body></html>"""
    products = [{"id": 1, "title": "Oak", "handle": "oak", "body_html": f'<img src="https:{CDN}/hero.jpg">',
                 "vendor": "K", "product_type": "Chair", "tags": ["a", "b"],
                 "options": [{"name": "Color", "position": 1, "values": ["Red", "Blue"]}],
                 "variants": [{"id": 11, "option1": "Red", "price": "5.00", "grams": 900, "requires_shipping": True,
                               "taxable": True, "featured_image": None},
                              {"id": 12, "option1": "Blue", "price": "6.00", "grams": 900, "requires_shipping": True,
                               "taxable": True, "featured_image": {"id": 202}}],
                 "images": [{"id": 201, "src": f"https:{CDN}/../products/red_800x.jpg?v=1", "position": 1,
                             "variant_ids": [11], "alt": "red"},
                            {"id": 202, "src": "https://cdn.shopify.com/s/files/1/0001/products/blue.jpg?v=1",
                             "position": 2, "variant_ids": [], "alt": None}]}]
    atom = """<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom">
      <entry><title>First Post</title><link rel="alternate" type="text/html" href="https://kitty-demo.myshopify.com/blogs/news/first-post"/>
      <published>2024-05-01T10:00:00-04:00</published><author><name>Emma</name></author>
      <content type="html">&lt;p&gt;Full content&lt;/p&gt;</content><category term="Style"/></entry></feed>"""

    def handler(method, path, q, data, auth):
        if path == "/password" and method == "POST":
            state["logged"] = data.get("password") == "1"
            return Resp(200, "ok")
        if not state["logged"] and path in ("/", "/password"):
            return Resp(200, "<form>password</form>", url="https://kitty-demo.myshopify.com/password")
        if path == "/":
            return Resp(200, text=home)
        if path == "/cdn/shop/t/5/assets/base.css":
            return Resp(200, text=f".x{{background:url({CDN}/pattern_small.png?v=4)}}")
        if path == "/products.json":
            return Resp(200, {"products": products if q.get("page") == "1" else []})
        if path == "/collections.json":
            return Resp(200, {"collections": [
                {"id": 1, "handle": "all", "title": "All"},
                {"id": 2, "handle": "chairs", "title": "Chairs", "body_html": "<p>c</p>",
                 "image": {"src": f"https:{CDN}/chairs_400x.jpg?v=1", "alt": "chairs"}}] if q.get("page") == "1" else []})
        if path == "/collections/chairs/products.json":
            return Resp(200, {"products": [{"handle": "oak"}] if q.get("page") == "1" else []})
        if path == "/blogs/news":
            if q.get("page"):
                return Resp(200, text="<html></html>")
            return Resp(200, text='<a href="/blogs/news/first-post">First</a><a href="/blogs/news/second-post">2</a>'
                                  '<a href="/blogs/news/tagged/style">tag</a>')
        if path == "/blogs/news.atom":
            return Resp(200, text=atom, content=atom.encode())
        if path.startswith("/blogs/news/"):
            slug = path.split("/")[-1]
            return Resp(200, text=f'<html><head><meta property="og:title" content="{slug.title()}">'
                                  f'<meta property="og:image" content="{CDN}/art.jpg?v=1&width=900"></head><body><article>'
                                  f'<h1>{slug}</h1><div class="rte"><p>Body of {slug}</p></div>'
                                  f'<a href="/blogs/news/tagged/summer-look">t</a></article></body></html>')
        if path.startswith("/pages/"):
            h = path.split("/")[-1]
            return Resp(200, text=f'<main><h1>{h.title()}</h1><div class="rte"><p>{h} text</p></div></main>')
        return Resp(404, "nf")
    return handler


def test_demo_mode():
    web = FakeWeb()
    web.site("kitty-demo.myshopify.com", demo_site())
    d = dest_store(web)
    job = run(demo, web, d, {"demo_url": "kitty-demo.myshopify.com/?preview_theme_id=55", "password": "1"}, demo.STEPS)
    assert all(s["status"] == "done" for s in job.steps), ([(s["key"], s["status"]) for s in job.steps], job.notes)
    names = sorted(f["filename"] for f in d.files if not f["used"])
    assert names == ["bg.png", "hero.jpg", "pattern.png", "promo.webp"], names
    assert all("width=" not in f["url"] for f in d.files)
    p = d.products[0]
    assert p["handle"] == "oak" and p["tags"] == "a, b" and p["variants"][0]["weight"] == 900
    assert p["images"][0]["src"].endswith("red.jpg?v=1")              # original, resize suffix hata
    puts = {img: vids for _p, img, vids in d.image_puts}
    assert puts[p["images"][0]["id"]] == [p["variants"][0]["id"]]
    assert puts[p["images"][1]["id"]] == [p["variants"][1]["id"]]       # featured_image se
    col = d.custom[0]
    assert col["handle"] == "chairs" and col["image"]["src"].endswith("chairs.jpg?v=1")
    assert {"collection_id": col["id"], "product_id": p["id"]} in d.collects
    news = next(b for b in d.blogs if b["handle"] == "news")
    arts = {a["handle"]: a for a in d.articles[news["id"]]}
    assert set(arts) == {"first-post", "second-post"}
    assert arts["first-post"]["published_at"].startswith("2024-05-01") and arts["first-post"]["author"] == "Emma"
    assert arts["first-post"]["body_html"] == "<p>Full content</p>"
    assert arts["second-post"]["tags"] == "summer look"
    pages = {pg["handle"]: pg for pg in d.pages}
    assert pages["contact"]["template_suffix"] == "contact"
    assert pages["about-us"]["template_suffix"] == "about"
    assert job.stats["Theme check"]["missing"] == 0
    # preview_theme_id har request me
    assert all(q.get("preview_theme_id") == "55" for m, host, path, q in web.log
               if host == "kitty-demo.myshopify.com" and not path.startswith("/cdn/"))


def test_demo_wrong_password():
    web = FakeWeb()
    web.site("kitty-demo.myshopify.com", demo_site())
    d = dest_store(web)
    job = Job("demo", "t", demo.STEPS)
    st = Store(web, d.domain, d.token, "DEST", job)
    try:
        demo.run(job, {"demo_url": "https://kitty-demo.myshopify.com", "password": "wrong", "dest": st, "web_session": web})
        raise AssertionError("should fail")
    except RuntimeError as e:
        assert "Password ghalat" in str(e)


# ================================================================== WOOCOMMERCE
def woo_site(basic_only=False):
    cats = [{"id": 1, "name": "Furniture", "slug": "furniture", "parent": 0, "description": "All furniture",
             "image": {"src": "https://wooshop.com/cat.jpg", "alt": ""}},
            {"id": 2, "name": "Chairs", "slug": "chairs", "parent": 1, "description": "", "image": None},
            {"id": 3, "name": "Uncategorized", "slug": "uncategorized", "parent": 0}]
    products = [
        {"id": 10, "name": "Simple Stool", "slug": "simple-stool", "type": "simple", "status": "publish",
         "permalink": "https://wooshop.com/product/simple-stool/", "description": "<p>stool</p>",
         "regular_price": "50", "sale_price": "40", "price": "40", "sku": "ST1", "manage_stock": True,
         "stock_quantity": 5, "weight": "2", "categories": [{"id": 2, "name": "Chairs", "slug": "chairs"}],
         "tags": [{"name": "wood"}], "images": [{"src": "https://wooshop.com/stool.jpg", "alt": "stool"}],
         "attributes": [{"name": "Material", "variation": False, "options": ["Oak"]}], "brands": [{"name": "Acme"}]},
        {"id": 20, "name": "Shirt", "slug": "shirt", "type": "variable", "status": "draft",
         "permalink": "https://wooshop.com/product/shirt/", "description": "", "short_description": "<p>short</p>",
         "price": "20", "categories": [{"id": 1, "name": "Furniture", "slug": "furniture"}], "tags": [],
         "images": [{"src": "https://wooshop.com/shirt.jpg"}],
         "attributes": [{"name": "Size", "variation": True, "options": ["S", "M"]},
                        {"name": "Color", "variation": True, "options": ["Red"]}]}]
    variations = [
        {"id": 21, "attributes": [{"name": "Size", "option": "S"}, {"name": "Color", "option": "Red"}],
         "regular_price": "20", "sale_price": "", "price": "20", "sku": "SH-S", "manage_stock": True,
         "stock_quantity": 3, "image": {"src": "https://wooshop.com/shirt-s.jpg"}},
        {"id": 22, "attributes": [{"name": "Color", "option": "Red"}],      # "Any Size"
         "regular_price": "25", "sale_price": "", "price": "25", "sku": "SH-ANY", "manage_stock": "parent",
         "image": {"src": "https://wooshop.com/shirt.jpg"}}]

    def handler(method, path, q, data, auth):
        if basic_only and auth is None:
            return Resp(401, {"code": "woocommerce_rest_cannot_view"})
        if not basic_only and q.get("consumer_key") != "ck_1":
            return Resp(401, {"code": "unauthorized"})
        page = int(q.get("page", "1"))
        if path == "/wp-json/wc/v3/products":
            items = [p for p in products if q.get("status") in (None, "any") or p["status"] == q.get("status")]
            return Resp(200, (items[:1] if q.get("per_page") == "1" else items) if page == 1 else [])
        if path == "/wp-json/wc/v3/products/categories":
            return Resp(200, cats if page == 1 else [])
        if path == "/wp-json/wc/v3/products/20/variations":
            return Resp(200, variations if page == 1 else [])
        if path == "/wp-json/wc/v3/settings/products/woocommerce_weight_unit":
            return Resp(200, {"value": "lbs"})
        return Resp(404, {})
    return handler


def test_woocommerce_import():
    web = FakeWeb()
    web.site("wooshop.com", woo_site())
    d = dest_store(web)
    job = run(woo, web, d, {"wc_url": "wooshop.com", "ck": "ck_1", "cs": "cs_1", "include_drafts": True}, woo.STEPS)
    assert all(s["status"] == "done" for s in job.steps), ([(s["key"], s["status"]) for s in job.steps], job.notes)
    stool, shirt = d.products
    v = stool["variants"][0]
    assert stool["handle"] == "simple-stool" and stool["vendor"] == "Acme" and stool["status"] == "active"
    assert v["price"] == "40" and v["compare_at_price"] == "50" and v["weight_unit"] == "lb" and v["sku"] == "ST1"
    assert shirt["status"] == "draft" and shirt["body_html"] == "<p>short</p>"
    combos = [(x["option1"], x["option2"]) for x in shirt["variants"]]
    assert combos == [("S", "Red"), ("M", "Red")], combos                   # "Any Size" -> M added, S deduped
    assert shirt["options"] == [{"name": "Size", "values": ["S", "M"]}, {"name": "Color", "values": ["Red"]}]
    inv = sorted(i["available"] for i in d.inventory)
    assert inv == [3, 5], inv
    srcs = [i["src"] for i in shirt["images"]]
    assert srcs == ["https://wooshop.com/shirt.jpg", "https://wooshop.com/shirt-s.jpg"]
    puts = {img: vids for _p, img, vids in d.image_puts}
    assert puts[shirt["images"][1]["id"]] == [shirt["variants"][0]["id"]]
    mf = d.metafields[f"products/{stool['id']}"][0]
    assert mf["key"] == "woo_attributes" and json.loads(mf["value"]) == {"Material": ["Oak"]}
    cols = {c["handle"]: c for c in d.custom}
    assert set(cols) == {"furniture", "chairs"}
    furniture_members = {c["product_id"] for c in d.collects if c["collection_id"] == cols["furniture"]["id"]}
    assert furniture_members == {stool["id"], shirt["id"]}                  # child category rollup
    assert {"path": "/product/simple-stool/", "target": "/products/simple-stool"} in d.redirects
    assert {"path": "/product-category/chairs/", "target": "/collections/chairs"} in d.redirects
    # re-run: sab skip
    job2 = run(woo, web, d, {"wc_url": "wooshop.com", "ck": "ck_1", "cs": "cs_1", "include_drafts": True}, woo.STEPS)
    assert len(d.products) == 2 and job2.stats["Products"]["already"] == 2


def test_woocommerce_basic_auth_fallback_and_verify():
    web = FakeWeb()
    web.site("wooshop.com", woo_site(basic_only=True))
    d = dest_store(web)
    job = run(woo, web, d, {"wc_url": "https://wooshop.com/", "ck": "ck_1", "cs": "cs_1", "verify_only": True},
              woo.VERIFY_STEPS)
    assert job.stats["Verify"]["products_missing"] == 1          # sirf published (draft shirt nahi)
    assert job.stats["Verify"]["collections_missing"] == 2
    assert not d.products


# ================================================================== BLOG IMPORT
def wp_site(method, path, q, data, auth):
    if path == "/wp-json/wp/v2/posts":
        posts = [{"slug": f"post-{i}", "link": f"https://wpblog.com/post-{i}/", "date_gmt": "2023-02-0%dT08:00:00" % (i + 1),
                  "title": {"rendered": f"Post &amp; {i}"},
                  "content": {"rendered": f'<p>Hello {i}</p><img src="https://wpblog.com/wp-content/uploads/img{i}.jpg">'},
                  "excerpt": {"rendered": "<p>ex</p>"},
                  "_embedded": {"author": [{"name": "Sara"}],
                                "wp:featuredmedia": [{"source_url": f"https://wpblog.com/feat{i}.jpg", "alt_text": "f"}],
                                "wp:term": [[{"name": "News"}, {"name": "Uncategorized"}], [{"name": "tips"}]]}}
                 for i in range(3)]
        if q.get("per_page") == "1":
            return Resp(200, posts[:1])
        return Resp(200, posts if q.get("page") == "1" else [], headers={"X-WP-TotalPages": "1"})
    return Resp(404, "")


def test_blog_wordpress_api():
    web = FakeWeb()
    web.site("wpblog.com", wp_site)
    d = dest_store(web)
    job = run(blog, web, d, {"listing_url": "wpblog.com/blog", "blog_title": "Journal"}, blog.STEPS)
    assert all(s["status"] == "done" for s in job.steps), ([(s["key"], s["status"]) for s in job.steps], job.notes)
    b = next(b for b in d.blogs if b["title"] == "Journal")
    arts = d.articles[b["id"]]
    assert [a["handle"] for a in arts] == ["post-0", "post-1", "post-2"]
    a = arts[0]
    assert a["title"] == "Post & 0" and a["author"] == "Sara" and a["tags"] == "News, tips"
    assert a["published_at"] == "2023-02-01T08:00:00Z" and a["image"] == {"src": "https://wpblog.com/feat0.jpg", "alt": "f"}
    assert "cdn.shopify.com" in a["body_html"] and "wpblog.com/wp-content" not in a["body_html"]   # rehosted
    run(blog, web, d, {"listing_url": "wpblog.com/blog", "blog_title": "Journal"}, blog.STEPS)
    assert len(d.articles[b["id"]]) == 3                                 # dobara chalaya: duplicates nahi


def generic_site(method, path, q, data, auth):
    nav = '<header><nav><a href="/about-us-company">About</a><a href="/blog">Blog</a></nav></header>'

    def card(slug, title):
        return f'<article><h2><a href="/blog/{slug}">{title}</a></h2><a href="/blog/{slug}">Read more</a></article>'
    if path == "/blog" or path == "/blog/":
        return Resp(200, text=f'<html>{nav}<main>{card("how-to-choose-a-chair", "How to choose a chair")}'
                              f'{card("best-wood-types-2024", "Best wood types for furniture")}'
                              f'<a href="/blog/page/2">2</a></main></html>')
    if path == "/blog/page/2":
        return Resp(200, text=f'<html>{nav}<main>{card("caring-for-oak-table", "Caring for your oak table")}</main></html>')
    if path.startswith("/blog/"):
        slug = path.split("/")[-1]
        ld = json.dumps({"@context": "https://schema.org", "@type": "BlogPosting", "headline": slug.replace("-", " ").title(),
                         "datePublished": "2022-01-01", "author": {"name": "Ali"}, "image": "https://genericblog.com/i.jpg",
                         "keywords": "wood, care"})
        return Resp(200, text=f'<html><head><script type="application/ld+json">{ld}</script>'
                              f'<meta name="description" content="desc"></head><body>{nav}<article>'
                              f'<div class="entry-content"><p>{"Long text " * 20}</p><img data-src="/img/{slug}.png"></div>'
                              f'</article></body></html>')
    if path == "/sitemap.xml":
        return Resp(200, text='<sitemapindex><sitemap><loc>https://genericblog.com/post-sitemap.xml</loc></sitemap>'
                              '<sitemap><loc>https://genericblog.com/page-sitemap.xml</loc></sitemap></sitemapindex>')
    if path == "/post-sitemap.xml":
        return Resp(200, text='<urlset><url><loc>https://genericblog.com/blog/how-to-choose-a-chair</loc></url>'
                              '<url><loc>https://genericblog.com/blog/hidden-js-loaded-post</loc></url></urlset>')
    if path == "/page-sitemap.xml":
        return Resp(200, text='<urlset><url><loc>https://genericblog.com/about-us-company</loc></url>'
                              '<url><loc>https://genericblog.com/contact-our-team-today</loc></url></urlset>')
    return Resp(404, "")


def test_blog_generic_site():
    web = FakeWeb()
    web.site("genericblog.com", generic_site)
    d = dest_store(web)
    job = run(blog, web, d, {"listing_url": "https://genericblog.com/blog", "rehost_images": False}, blog.STEPS)
    b = next(b for b in d.blogs if b["title"] == "Genericblog")
    handles = sorted(a["handle"] for a in d.articles[b["id"]])
    assert handles == ["best-wood-types-2024", "caring-for-oak-table", "hidden-js-loaded-post", "how-to-choose-a-chair"], handles
    a = next(a for a in d.articles[b["id"]] if a["handle"] == "how-to-choose-a-chair")
    assert a["author"] == "Ali" and a["published_at"] == "2022-01-01" and a["tags"] == "wood, care"
    assert 'src="https://genericblog.com/img/how-to-choose-a-chair.png"' in a["body_html"]
    assert a["summary_html"] == "<p>desc</p>"
    assert job.steps[2]["status"] == "skipped"
