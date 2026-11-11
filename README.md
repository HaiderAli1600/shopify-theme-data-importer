# Shopify Theme Data Importer

A free, open-source desktop tool that moves store data into Shopify: store-to-store migrations, theme demo content, WooCommerce catalogs and blog posts. It runs **entirely on your own computer** (a local server bound to `127.0.0.1`), so your store credentials never touch a third-party service.

- Python 3.10+ backend, plain HTML/CSS/JS UI (no framework, no CDN calls)
- Ships as a single Windows `.exe` (PyInstaller) or runs straight from source
- Talks to the Shopify Admin API (GraphQL + REST), API version `2026-10`
- Re-runnable: anything that already exists in the destination is skipped, so a second run never creates duplicates

## Four modes

| Mode | What it does |
|------|--------------|
| **Store → Store** | Exact migration from one Shopify store to another: files, products (variants, inventory, images), collections (manual and smart rules), blogs and articles, pages, navigation menus, metafields, and a theme copy (created unpublished) with a verification pass that checks theme settings still point at valid files. |
| **Theme Demo → Store** | Imports section images, products, collections, blogs and pages from a (password-protected) Shopify theme demo store into your development store. |
| **WooCommerce → Shopify** | Products, variants, sale prices, stock, images, categories → collections, and SEO redirects for the old URLs. Uses the WooCommerce REST API (read-only key). |
| **Blog Import** | Imports blog posts from any website into a Shopify blog. WordPress sites are auto-detected via the REST API; other sites use structured-data and HTML scraping. Images are re-hosted on your store. |

## Authentication

- **Dev Dashboard app, Client ID + Secret** (client-credentials token, renewed automatically)
- **OAuth** for stores you don't own (client stores): authorize in the browser, the token is returned to a localhost callback
- **Legacy access token** (`shpat_...`) if your store still allows custom apps

Only store domains and last-used URLs are remembered between sessions (`settings.json`). Tokens and secrets are not written to disk by the tool.

## Quick start

**From source (any OS with Python 3.10+):**

```bash
git clone https://github.com/HaiderAli1600/shopify-theme-data-importer.git
cd shopify-theme-data-importer
pip install -r requirements.txt
python launcher.py
```

On Windows you can also double-click `run_tool.bat`.

**Build a standalone Windows EXE:** double-click `build_exe.bat`. It creates an isolated virtualenv, installs dependencies and produces `dist\Shopify Theme Data Importer.exe`.

The UI opens in an app-style window (Edge/Chrome app mode) or your default browser. Theme ZIP backups and logs are saved to `Documents\Shopify Theme Data Importer\`.

## Tests

```bash
pip install pytest
python -m pytest tests
```

The tests run against in-memory fake Shopify, WooCommerce and demo stores, so no network or real store is needed.

## Project layout

```
app/
  core/      Shopify client (GraphQL/REST, throttling, files), auth, web helpers, job runner
  modes/     migrate.py, demo.py, woo.py, blog.py
  ui/        local web UI (index.html, app.js, app.css, bundled fonts)
  server.py  local HTTP server, JSON API, OAuth callback
tests/       pytest suite with fake stores
docs/        step-by-step setup guide (Roman Urdu)
```

## Documentation language

The in-app help ("?" next to every field) and the setup guide in `docs/GUIDE_ROMAN_URDU.txt` are written in Roman Urdu, to help Urdu/Hindi-speaking Shopify freelancers and small agencies set up Dev Dashboard apps step by step. Translations of the UI help into English are welcome as pull requests.

## Responsible use

Only import content you own or are licensed to use. Respect the terms of service and copyright of any demo store, theme vendor or website you import from, and the robots/terms of sites you run Blog Import against.

## Contributing

Issues and pull requests are welcome. Please run `python -m pytest tests` before opening a PR.

## License

[MIT](LICENSE) © 2026 Haider Ali
