import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.jobs import Job                       # noqa: E402
from app.core.shopify import Store                  # noqa: E402
from app.modes import migrate                       # noqa: E402
from tests.fakes import FakeStore, FakeWeb, Resp    # noqa: E402


def cdn_site(method, path, q, data, auth):
    return Resp(200, text="bin", content=b"BIN")


def make_source():
    s = FakeStore("source-shop.myshopify.com", "src-token")
    cdn = s.cdn
    s.products = [{
        "id": 1, "title": "Oak Chair", "handle": "oak-chair-custom", "body_html": f'<img src="{cdn("desc.jpg")}">',
        "vendor": "V", "product_type": "Chair", "tags": "wood, chair", "status": "draft",
        "template_suffix": "configurator", "published_scope": "web", "published_at": None,
        "options": [{"id": 9, "product_id": 1, "name": "Color", "position": 1, "values": ["Red", "Blue"]}],
        "variants": [
            {"id": 11, "option1": "Red", "price": "10.00", "sku": "R", "barcode": "123", "weight": 2.5,
             "weight_unit": "kg", "inventory_management": "shopify", "inventory_quantity": 7, "image_id": 102},
            {"id": 12, "option1": "Blue", "price": "11.00", "sku": "B", "inventory_management": "shopify",
             "inventory_quantity": 3, "image_id": 101}],
        "images": [{"id": 101, "src": cdn("blue.jpg"), "alt": "Blue chair", "position": 1},
                   {"id": 102, "src": cdn("red.jpg"), "alt": "Red chair", "position": 2}]}]
    s.custom = [{"id": 21, "title": "Chairs", "handle": "chairs", "body_html": "<p>c</p>", "sort_order": "manual",
                 "published_at": "2026-01-01", "template_suffix": "wide", "image": {"src": cdn("chairs.jpg"), "alt": "c"}}]
    s.collects = [{"collection_id": 21, "product_id": 1}]
    s.smart = [{"id": 22, "title": "Wood", "handle": "wood", "disjunctive": False, "published_at": "2026-01-01",
                "sort_order": "best-selling",
                "rules": [{"column": "tag", "relation": "equals", "condition": "wood"},
                          {"column": "product_metafield_definition", "relation": "equals", "condition": "x",
                           "condition_object_id": 5}]}]
    s.blogs = [{"id": 31, "title": "Journal", "handle": "journal", "commentable": "no"}]
    s.articles = {31: [{"id": 41, "title": "Hello", "handle": "hello-world", "author": "A",
                        "body_html": f'<img src="{cdn("banner.png")}">', "summary_html": "<p>s</p>", "tags": "t",
                        "published_at": "2025-03-04T10:00:00-05:00", "image": {"src": cdn("art.jpg"), "alt": "art"}}]}
    s.pages = [{"id": 51, "title": "About", "handle": "about-us", "author": "A", "body_html": "<p>x</p>",
                "template_suffix": "about", "published_at": "2025-01-01"},
               {"id": 52, "title": "Draft", "handle": "draft-page", "body_html": "", "published_at": None}]
    s.metafields = {
        "products/1": [{"namespace": "custom", "key": "material", "type": "single_line_text_field", "value": "oak"},
                       {"namespace": "custom", "key": "related", "type": "product_reference", "value": "gid://x"},
                       {"namespace": "app--123", "key": "x", "type": "json", "value": "{}"}],
        "": [{"namespace": "global", "key": "badge", "type": "boolean", "value": True}]}
    s.add_file("banner.png", alt="Banner")
    s.add_file("desc.jpg")
    s.add_file("blue.jpg", used_in_product=True)
    s.add_file("size-guide.pdf", "GenericFile")
    s.add_file("icon star.svg", "GenericFile", url=cdn("icon%20star.svg"))
    s.add_file("hero.mp4", "Video")
    s.menus = [
        {"id": "gid://shopify/Menu/1", "handle": "main-menu", "title": "Main menu", "isDefault": True, "items": [
            {"title": "Home", "type": "FRONTPAGE", "url": "/", "resourceId": None, "tags": [], "items": []},
            {"title": "Chairs", "type": "COLLECTION", "url": "/collections/chairs",
             "resourceId": "gid://shopify/Collection/21", "tags": [], "items": [
                 {"title": "Oak", "type": "PRODUCT", "url": "/products/oak-chair-custom",
                  "resourceId": "gid://shopify/Product/1", "tags": [], "items": []}]},
            {"title": "Refunds", "type": "SHOP_POLICY", "url": "/policies/refund-policy",
             "resourceId": "gid://shopify/ShopPolicy/9", "tags": [], "items": []}]},
        {"id": "gid://shopify/Menu/2", "handle": "footer-extra", "title": "Footer extra", "isDefault": False,
         "items": [{"title": "About", "type": "PAGE", "url": "/pages/about-us", "resourceId": "gid://shopify/Page/51",
                    "tags": [], "items": []}]}]
    s.themes = [{"id": 900, "name": "Dawn Custom", "role": "main", "processing": False, "assets": {
        "layout/theme.liquid": "<html>{{ content_for_layout }}</html>",
        "assets/logo.png": b"\x89PNG-binary",
        "templates/index.json": '{"a":"shopify:\\/\\/shop_images\\/banner.png","b":"shopify://collections/chairs"}'}}]
    return s


def make_dest():
    d = FakeStore("client-shop.myshopify.com", "dst-token")
    d.blogs = [{"id": 600, "title": "News", "handle": "news"}]
    d.articles = {600: []}
    d.menus = [{"id": "gid://shopify/Menu/700", "handle": "main-menu", "title": "Main menu", "isDefault": True, "items": []}]
    d.themes = [{"id": 1, "name": "Dawn", "role": "main", "processing": False, "assets": {
        "templates/index.json": '/* auto */ {"a":"shopify://shop_images/banner.png","c":"shopify://collections/all",'
                                '"d":"shopify://products/missing-sofa"}',
        "sections/footer-group.json": '{"x":"shopify://pages/about-us","y":"shopify://shop_images/gone.jpg"}'}}]
    return d


def test_full_migration(tmp_path):
    web = FakeWeb()
    web.site("cdn.shopify.com", cdn_site)
    src, dst_store = web.store(make_source()), web.store(make_dest())
    job = Job("migrate", "t", migrate.STEPS)
    params = {"session": web, "source": Store(web, src.domain, src.token, "SOURCE", job),
              "dest": Store(web, dst_store.domain, dst_store.token, "DEST", job), "out_dir": str(tmp_path)}
    params["source"].write_pause = params["dest"].write_pause = 0
    job.sleep = lambda s: None
    migrate.run(job, params)
    d = dst_store
    statuses = {s["key"]: s["status"] for s in job.steps}
    assert all(v == "done" for v in statuses.values()), (statuses, job.notes)

    names = sorted(f["filename"] for f in d.files if not f["used"])
    assert "banner.png" in names and "size-guide.pdf" in names and "icon star.svg" in names and "hero.mp4" in names
    assert "blue.jpg" not in [f["filename"] for f in d.files if not f["used"]]   # product image skipped in Files

    p = d.products[0]
    assert p["handle"] == "oak-chair-custom" and p["status"] == "draft" and p["template_suffix"] == "configurator"
    assert p["published"] is False and p["options"] == [{"name": "Color", "values": ["Red", "Blue"]}]
    assert p["variants"][0]["barcode"] == "123" and p["variants"][0]["weight_unit"] == "kg"
    assert p["images"][0]["alt"] == "Blue chair"
    assert dst_store.cdn("desc.jpg").split("?")[0] in p["body_html"], p["body_html"]
    pos = {img["position"]: img["id"] for img in p["images"]}
    puts = {img: vids for _p, img, vids in d.image_puts}
    assert puts[pos[2]] == [p["variants"][0]["id"]] and puts[pos[1]] == [p["variants"][1]["id"]]
    assert [i["available"] for i in d.inventory] == [7, 3]

    cc = d.custom[0]
    assert cc["handle"] == "chairs" and cc["template_suffix"] == "wide" and cc["image"]["alt"] == "c"
    assert {"collection_id": cc["id"], "product_id": p["id"]} in d.collects
    sc = d.smart[0]
    assert sc["rules"] == [{"column": "tag", "relation": "equals", "condition": "wood"}] and sc["sort_order"] == "best-selling"

    journal = next(b for b in d.blogs if b["handle"] == "journal")
    art = d.articles[journal["id"]][0]
    assert art["handle"] == "hello-world" and art["published_at"].startswith("2025-03-04")
    assert dst_store.cdn("banner.png").split("?")[0] in art["body_html"]

    pages = {pg["handle"]: pg for pg in d.pages}
    assert pages["about-us"]["template_suffix"] == "about" and pages["about-us"]["published"] is True
    assert pages["draft-page"]["published"] is False

    assert any(m["key"] == "material" for m in d.metafields[f"products/{p['id']}"])
    assert not any(m["key"] in ("related", "x") for m in d.metafields[f"products/{p['id']}"])
    assert d.metafields[""][0]["value"] == "true"

    main = next(m for m in d.menus if m["handle"] == "main-menu")
    assert main["id"] == "gid://shopify/Menu/700"
    assert main["items"][1]["resourceId"] == f"gid://shopify/Collection/{cc['id']}"
    assert main["items"][1]["items"][0]["resourceId"] == f"gid://shopify/Product/{p['id']}"
    assert main["items"][2] == {"title": "Refunds", "type": "HTTP", "url": "/policies/refund-policy"}
    footer = next(m for m in d.menus if m["handle"] == "footer-extra")
    assert footer["items"][0]["resourceId"] == f"gid://shopify/Page/{pages['about-us']['id']}"

    migrated = next(t for t in d.themes if t["name"] == "Dawn Custom (migrated)")
    assert migrated["role"] == "unpublished"
    zips = [f for f in os.listdir(tmp_path) if f.endswith(".zip")]
    with zipfile.ZipFile(tmp_path / zips[0]) as z:
        assert set(z.namelist()) == {"layout/theme.liquid", "assets/logo.png", "templates/index.json"}
        assert z.read("assets/logo.png") == b"\x89PNG-binary"
    assert not [f for f in d.files if f["filename"].endswith(".zip")]       # temp zip file deleted

    assert job.stats["Theme check"]["missing"] == 0, job.notes                 # verify ran on migrated theme

    # second run = idempotent (sab "already")
    job2 = Job("migrate", "t2", migrate.STEPS)
    job2.sleep = lambda s: None
    params2 = dict(params, source=Store(web, src.domain, src.token, "SOURCE", job2),
                   dest=Store(web, d.domain, d.token, "DEST", job2), steps=["files", "products", "collections", "pages"])
    params2["source"].write_pause = params2["dest"].write_pause = 0
    before = (len(d.products), len(d.custom), len(d.smart), len(d.pages))
    migrate.run(job2, params2)
    assert (len(d.products), len(d.custom), len(d.smart), len(d.pages)) == before
    assert job2.stats["Products"]["already"] == 1
    job3 = Job("migrate", "t3", migrate.STEPS)
    job3.sleep = lambda s: None
    themes_before = len(d.themes)
    migrate.run(job3, dict(params, source=Store(web, src.domain, src.token, "S", job3),
                           dest=Store(web, d.domain, d.token, "D", job3), steps=["theme", "verify"]))
    assert len(d.themes) == themes_before and job3.stats["Theme"]["already"] == 1     # theme dobara nahi bana


def test_menus_only_maps_by_handle(tmp_path):
    """Sirf menus chalaye (products pehle migrate ho chuke) -- links handle se match hon."""
    web = FakeWeb()
    src, d = web.store(make_source()), web.store(make_dest())
    d.products = [{"id": 8001, "handle": "oak-chair-custom", "title": "Oak Chair"}]
    d.custom = [{"id": 8002, "handle": "chairs", "title": "Chairs"}]
    job = Job("migrate", "t", migrate.STEPS)
    job.sleep = lambda s: None
    migrate.run(job, {"session": web, "source": Store(web, src.domain, src.token, "S", job),
                      "dest": Store(web, d.domain, d.token, "D", job), "steps": ["menus"], "out_dir": str(tmp_path)})
    main = next(m for m in d.menus if m["handle"] == "main-menu")
    assert main["items"][1]["resourceId"] == "gid://shopify/Collection/8002"
    assert main["items"][1]["items"][0]["resourceId"] == "gid://shopify/Product/8001"


def test_verify_autofix_and_old_refs():
    """Missing theme image source me hai -> khud copy; source me bhi nahi -> purana reference (note nahi)."""
    from app.core.shopify import verify_theme_refs
    web = FakeWeb()
    s, d = web.store(make_source()), web.store(make_dest())
    s.products.append({"id": 2, "handle": "only-in-source", "title": "X"})
    d.themes = [{"id": 1, "name": "T", "role": "main", "processing": False, "assets": {
        "config/settings_data.json": '{"current":{"a":"shopify://shop_images/blue.jpg",'
                                     '"b":"shopify://shop_images/menu-h3.jpg","c":"shopify://products/only-in-source"}}'}}]
    job = Job("migrate", "t", [("verify", "Verify")])
    job.sleep = lambda s_: None
    with job.step("verify"):
        verify_theme_refs(Store(web, d.domain, d.token, "D", job), job, None, Store(web, s.domain, s.token, "S", job))
    st = job.stats["Theme check"]
    assert st["references"] == 3 and st["auto_fixed"] == 1 and st["old_refs"] == 1 and st["missing"] == 1, st
    assert "blue.jpg" in {f["filename"] for f in d.files}                       # khud copy hui
    assert len(job.notes) == 1 and "products/only-in-source" in job.notes[0]    # sirf asli masla report me
    assert not any("menu-h3" in n for n in job.notes)


def test_verify_without_theme_step_checks_migrated_and_main():
    """Sirf Files + Verify chalaya (theme step nahi): '(migrated)' theme + published theme dono check hon."""
    from app.core.shopify import verify_theme_refs
    web = FakeWeb()
    s, d = web.store(make_source()), web.store(make_dest())
    d.themes = [
        {"id": 1, "name": "Uploaded", "role": "main", "processing": False,
         "assets": {"config/settings_data.json": '{"a":"shopify://products/gone-main"}'}},
        {"id": 2, "name": "Dawn Custom (migrated)", "role": "unpublished", "processing": False,
         "assets": {"config/settings_data.json": '{"a":"shopify://shop_images/blue.jpg"}'}},
        {"id": 3, "name": "Kuch aur", "role": "unpublished", "processing": False,
         "assets": {"config/settings_data.json": '{"a":"shopify://products/ignore-me"}'}},
    ]
    s.products.append({"id": 7, "handle": "gone-main", "title": "G"})
    job = Job("migrate", "t", [("verify", "Verify")])
    job.sleep = lambda s_: None
    with job.step("verify"):
        verify_theme_refs(Store(web, d.domain, d.token, "D", job), job, None, Store(web, s.domain, s.token, "S", job))
    st = job.stats["Theme check"]
    assert st["references"] == 2 and st["auto_fixed"] == 1 and st["missing"] == 1, st
    assert job.notes == ["Theme 'Uploaded' (config/settings_data.json): products/gone-main store me NAHI hai"]
    assert not any("ignore-me" in e["msg"] for e in job.events)
