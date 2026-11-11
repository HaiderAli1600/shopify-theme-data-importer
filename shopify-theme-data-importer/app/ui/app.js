/* =====================================================================
   Shopify Theme Data Importer — UI logic (vanilla JS, offline)
   ===================================================================== */
(() => {
"use strict";

// ------------------------------------------------------------------ utils
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const store = {
  get(k) { try { return sessionStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { sessionStorage.setItem(k, v); } catch (e) { /* private mode */ } },
};

let KEY = new URLSearchParams(location.search).get("k") || store.get("stdi-key") || "";
if (KEY) { store.set("stdi-key", KEY); history.replaceState(null, "", "/"); }

let INFO = null;
const SESSION = {};          // domain -> {method, token, client_id, client_secret, shop, scopes}
let CURRENT_JOB = null;
let LAST_FORM_VIEW = "home";

async function api(path, body = {}) {
  let res;
  try {
    res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json", "X-App-Key": KEY }, body: JSON.stringify(body) });
  } catch (e) {
    throw new Error("Tool ka engine band hai — tool dobara kholo.");
  }
  let data = {};
  try { data = await res.json(); } catch (e) { /* ignore */ }
  if (res.status === 401) { sessionExpired(); throw new Error(data.error || "Session expire"); }
  if (!res.ok) throw new Error(data.error || `Error ${res.status}`);
  return data;
}

function toast(msg, kind = "info", ms = 4200) {
  const t = document.createElement("div");
  t.className = `toast ${kind}`;
  t.innerHTML = `<i></i><div>${esc(msg)}</div>`;
  $("#toasts").appendChild(t);
  setTimeout(() => { t.classList.add("out"); setTimeout(() => t.remove(), 320); }, ms);
}

function confirmBox(title, text, yes = "Haan, shuru karo", no = "Nahi") {
  return new Promise((resolve) => {
    $("#mTitle").textContent = title;
    $("#mText").innerHTML = text;
    $("#mYes").textContent = yes;
    $("#mNo").textContent = no;
    const m = $("#modal");
    m.classList.add("show");
    const done = (v) => { m.classList.remove("show"); $("#mYes").onclick = $("#mNo").onclick = null; resolve(v); };
    $("#mYes").onclick = () => done(true);
    $("#mNo").onclick = () => done(false);
  });
}

function sessionExpired() {
  if ($("#modal").classList.contains("show")) return;
  confirmBox("Session khatam", "Tool ka engine is window ko pehchaan nahi raha. Tool (exe) ko band kar ke dobara kholo.", "Theek hai", "Band karo");
}

async function copy(text) {
  try { await navigator.clipboard.writeText(text); toast("Copy ho gaya", "ok", 1800); }
  catch (e) {
    const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); toast("Copy ho gaya", "ok", 1800); } catch (e2) { toast("Copy nahi hua", "err"); }
    ta.remove();
  }
}

// ------------------------------------------------------------------ icons
const I = {
  home: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/></svg>',
  migrate: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h13l-3-3"/><path d="M20 17H7l3 3"/><rect x="2" y="10" width="6" height="4" rx="1.2"/><rect x="16" y="10" width="6" height="4" rx="1.2"/></svg>',
  demo: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.8 4.6L18.5 9l-4.7 1.4L12 15l-1.8-4.6L5.5 9l4.7-1.4z"/><path d="M19 15l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/><path d="M5 16l.6 1.4L7 18l-1.4.6L5 20l-.6-1.4L3 18l1.4-.6z"/></svg>',
  woo: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M3 4h2l2.4 11.2a2 2 0 0 0 2 1.6h7.7a2 2 0 0 0 1.9-1.4L21 8H6.2"/><circle cx="10" cy="20" r="1.4"/><circle cx="17" cy="20" r="1.4"/></svg>',
  blog: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M20 4c-6 0-11 4-12 11l-2 5 5-2c7-1 9-7 9-14z"/><path d="M8 15l5-5"/></svg>',
  key: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="15" r="4"/><path d="M11 12l9-9"/><path d="M16 7l3 3"/><path d="M14 9l2 2"/></svg>',
  book: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z"/><path d="M4 19V5"/><path d="M8 7h7M8 11h5"/></svg>',
  live: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12h4l3-8 4 16 3-8h4"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
  x: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  arrow: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>',
  play: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5.5v13a1 1 0 0 0 1.5.86l10.4-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5z"/></svg>',
  plug: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M9 7V3M15 7V3"/><path d="M6 7h12v4a6 6 0 0 1-12 0z"/><path d="M12 17v4"/></svg>',
  info: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/></svg>',
  stop: '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2.5"/></svg>',
  save: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12M7 10l5 5 5-5"/><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/></svg>',
  ext: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 4h6v6M20 4l-9 9"/><path d="M19 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h4"/></svg>',
};

// ------------------------------------------------------------------ help (Roman Urdu)
const HELP = {
  "migrate": { t: "Store → Store Migration", b: `
    <p>Jo store aap ne apne (ya dev) store par bana kar final kiya hai, usay <b>client ke store</b> par hu-ba-hu le jata hai.</p>
    <ol><li>Upar <b>Source</b> (aap ka store) connect karo — sirf <i>read</i> access chahiye.</li>
    <li>Neeche <b>Destination</b> (client ka store) connect karo — <i>write</i> access chahiye.</li>
    <li>Jo cheezein le jaani hain un par tick karo, phir <b>Migration shuru karo</b>.</li></ol>
    <div class="tip">Handles, templates, smart collection rules, variant images, inventory, menus, metafields aur theme — sab same rehte hain. Dobara chalao to jo pehle aa chuka hai woh skip hota hai.</div>` },
  "demo": { t: "Theme Demo → Store", b: `
    <p>Envato / ThemeForest theme ke <b>password wale demo store</b> se demo content (section images, products, collections, blogs, pages) aap ke store me laata hai — taake theme bilkul demo jaisa dikhe.</p>
    <ol><li>Pehle theme khud apne store me install karo (theme ZIP upload).</li><li>Demo URL + password do.</li><li>Destination store connect karo aur Run dabao.</li></ol>
    <div class="tip">Theme settings me jo images <code>shop_images</code> se lagi hoti hain, tool unhe <b>same filename</b> ke saath Files me daalta hai — is liye sections khud image utha lete hain.</div>` },
  "woo": { t: "WooCommerce → Shopify", b: `
    <p>WordPress / WooCommerce store ke saare products — variants, prices, sale prices, stock, images, categories — Shopify me le aata hai. Categories collections ban jaati hain (parent categories me child ke products bhi).</p>
    <div class="tip">Purane URLs (<code>/product/...</code>) ke redirects bhi ban jaate hain taake Google ranking na gire.</div>` },
  "blog": { t: "Blog Import", b: `
    <p>Kisi bhi website (WordPress, Wix, Duda, Squarespace, Shopify…) ke blog posts Shopify blog me articles ki tarah aa jaate hain — title, content, featured image, author, date, tags.</p>
    <div class="tip">WordPress site ho to tool khud uski API pehchaan leta hai — sab se accurate result. Baaqi sites ke liye smart scraping + sitemap.</div>` },
  "token": { t: "API Access — Token Lab", b: `
    <p>Yahan kisi bhi store ka Admin API access test karo ya <b>Client ID + Secret se token banao</b>.</p>
    <ol><li><b>Access Token</b>: agar aap ke paas <code>shpat_...</code> token hai.</li>
    <li><b>Client ID + Secret</b>: Dev Dashboard app jo <i>aap ki apni organization</i> ke store par install hai.</li>
    <li><b>Client store (OAuth)</b>: client ka store jo aap ki organization me nahi — Custom distribution app.</li></ol>
    <div class="warn">Token password ki tarah hai. Kisi ko na bhejo. Tool token ko kahin save nahi karta — sirf is session me yaad rakhta hai.</div>` },

  "conn.domain": { t: "Store domain", b: `
    <p>Store ka <b>myshopify.com</b> wala address. Yeh sab chal jaata hai:</p>
    <ul><li><code>client-store.myshopify.com</code></li><li><code>https://client-store.myshopify.com/</code></li><li><code>admin.shopify.com/store/client-store</code></li><li>sirf <code>client-store</code></li></ul>
    <p>Kahan milega: Shopify admin → <b>Settings</b> → neeche store ke naam ke saath likha hota hai.</p>
    <div class="warn">Custom domain (jaise <code>clientstore.com</code>) yahan na likho — sirf myshopify wala.</div>` },
  "conn.method": { t: "Access ka tareeqa", b: `
    <ul><li><b>Access Token</b> — <code>shpat_</code> token hai to yeh. (Purani "Develop apps" custom app se milta tha.)</li>
    <li><b>Client ID + Secret</b> — Dev Dashboard app aur store <b>ek hi organization</b> me hon (jaise aap ka partner dev store, ya client ne khud apne Dev Dashboard me app banayi ho). Token 24 ghante chalta hai — tool khud renew kar leta hai.</li>
    <li><b>Client store (OAuth)</b> — store aap ki organization me nahi (client ka store). App ko <i>Custom distribution</i> se install karwao, phir yahan <b>Authorize</b> dabao.</li></ul>
    <p>Poori step-by-step guide: left menu → <b>Guide</b>.</p>` },
  "conn.token": { t: "Admin API access token", b: `
    <p><code>shpat_</code> se shuru hone wala token.</p>
    <ol><li>Shopify admin → Settings → Apps → <b>Develop apps</b>.</li><li>App kholo → <b>API credentials</b>.</li><li><b>Admin API access token</b> → Reveal token (sirf ek dafa dikhta hai).</li></ol>
    <div class="warn">1 Jan 2026 ke baad naye merchant stores par yeh purana tareeqa band hai — wahan "Client ID + Secret" ya "OAuth" use karo.</div>` },
  "conn.cc": { t: "Client ID + Client Secret", b: `
    <p>Jab store <b>aap ki apni Dev Dashboard organization</b> me ho (aap ka dev store / Source).</p>
    <ol><li>Dev Dashboard → Apps → <b>Create app</b>.</li>
    <li>App URL <code>https://example.com</code> · Embed <b>untick</b> · Legacy install flow <b>untick</b>.</li>
    <li>Scopes: source ke liye read list, destination ke liye write list.</li>
    <li>Baaqi fields default → <b>Create app</b> → <b>Install app</b> → apna store.</li>
    <li><b>Settings</b> → Client ID + Client secret yahan paste.</li></ol>
    <p><a href="#" data-setup="own"><b>→ Poora setup guide (exact values + Copy)</b></a></p>
    <div class="tip">Token 24 ghante ka — tool khud renew kar leta hai.</div>
    <div class="warn">Error "shop_not_permitted" = store aap ki organization me nahi → "Client store (OAuth)" use karo.</div>` },
  "conn.oauth": { t: "Client store (OAuth)", b: `
    <p>Client ka store (aap ki organization me nahi). Dev Dashboard app me <b>bilkul yeh</b>:</p>
    <ol><li><b>App URL</b>: <code>https://example.com</code></li>
    <li><b>Embed app in Shopify admin</b>: untick</li>
    <li><b>Allowed redirection URL(s)</b>: <code>http://localhost:8765/oauth/callback</code></li>
    <li><b>Use legacy install flow</b>: untick</li>
    <li><b>Scopes</b>: poori write list · baaqi fields default → <b>Create app</b></li>
    <li><b>Distribution → Custom distribution</b>: domain <code>store.myshopify.com</code> (https:// ke baghair, aakhir me / nahi) · <b>Allow multi-store install…</b> untick → <b>Generate link</b> → client install kare</li>
    <li>Settings se Client ID + Secret yahan → <b>Authorize</b> → Shopify par <b>Approve</b>.</li></ol>
    <p><a href="#" data-setup="client"><b>→ Poora setup guide (exact values + Copy)</b></a></p>
    <div class="tip">Localhost redirect save na ho: <code>https://example.com/callback</code> daalo aur approve ke baad ka poora URL neeche "Paste URL" me daal do.</div>` },

  "migrate.steps": { t: "Kya kya migrate karna hai", b: `
    <ul><li><b>Files</b>: Content → Files ki images, SVG, PDF, videos — same naam se (theme sections inhi naamon se image dhoondte hain). Product images yahan nahi — woh products ke saath aati hain.</li>
    <li><b>Products</b>: handle, status (draft/active), template, variants, barcode, weight, image alt, variant images, inventory.</li>
    <li><b>Collections</b>: manual collections ke products + <b>smart collections ke rules</b>, image, description, sort order, template.</li>
    <li><b>Blogs/Pages</b>: handle, template, publish date, excerpt.</li>
    <li><b>Menus</b>: main menu, footer menu — links naye store ke products/collections par.</li>
    <li><b>Theme</b>: source ka published theme ZIP ban kar destination par <b>unpublished</b> theme ki tarah upload hota hai.</li></ul>` },
  "migrate.options": { t: "Options", b: `
    <ul><li><b>Inventory</b>: har variant ki quantity destination ki pehli location par set hoti hai (scope: write_inventory + read_locations).</li>
    <li><b>Metafields</b>: products/collections/pages/blogs/articles/store ki metafields. Reference type (jaise product_reference) admin me khud set karni hoti hain — report me list aayegi.</li></ul>` },

  "demo.url": { t: "Demo store URL", b: `
    <p>Theme ke live demo ka address, jaise <code>https://kitty-theme.myshopify.com</code>.</p>
    <div class="tip"><b>Multi-demo themes</b> (ek domain par kai layouts — Boho, Jewellery…): woh specific demo kholo, neeche Shopify preview bar me <b>Copy link</b> dabao aur poora URL (<code>?preview_theme_id=...</code> wala) yahan paste karo.</div>` },
  "demo.password": { t: "Demo password", b: `<p>Theme seller demo ka password deta hai (aksar <code>1</code> ya theme page / documentation par likha hota hai). Agar demo password ke baghair khulta hai to khali chhor do.</p><p><b>Test karo</b> dabao — tool login check karke products ki ginti bata dega.</p>` },
  "demo.scope": { t: "Images kahan se uthani hain", b: `<p>Tool demo ke pages khol kar section images (banners, icons, backgrounds) dhoondta hai. <b>Sab kuch</b> best hai — Home, ek product, ek collection, blog aur saare "/pages/" pages scan honge.</p><div class="tip">Sirf original image uthai jaati hai (resize wale <code>_600x</code> / <code>width=</code> versions nahi).</div>` },
  "demo.steps": { t: "Kya import karna hai", b: `<ul><li><b>Section images</b> → Files (same filename).</li><li><b>Products</b> handle, variants, images, variant images ke saath.</li><li><b>Collections</b> + unke products.</li><li><b>Blogs</b> (Atom feed se poora content aur date).</li><li><b>Pages</b> — aur theme me <code>page.contact</code>, <code>page.about</code> jaisa template mile to khud lag jaata hai.</li></ul>` },

  "woo.url": { t: "WordPress site URL", b: `<p>WooCommerce store ka address, jaise <code>https://clientstore.com</code>. <b>https</b> zaroori hai.</p><div class="warn">Agar 404 aaye: WordPress → Settings → Permalinks → <b>Post name</b> select karke Save karo.</div>` },
  "woo.keys": { t: "WooCommerce REST API keys", b: `<ol><li>WordPress admin → <b>WooCommerce → Settings → Advanced → REST API</b>.</li><li><b>Add key</b> → Description likho → Permissions: <b>Read</b>.</li><li><b>Generate API key</b> → Consumer key (<code>ck_...</code>) aur Consumer secret (<code>cs_...</code>) copy karo.</li></ol><div class="tip">Tool teen tareeqon se connect try karta hai (query keys, Basic auth, ?rest_route) — hosting kuch bhi ho.</div>` },
  "woo.mode": { t: "Import ya sirf check", b: `<ul><li><b>Import</b>: products + collections banao. Jo pehle se hain (same slug ya same naam) woh skip.</li><li><b>Sirf check</b>: kuch nahi banta — sirf report ke kaun se products / categories Shopify me missing hain.</li></ul>` },

  "blog.url": { t: "Blog listing URL", b: `<p>Woh page jahan saare posts ki list hoti hai:</p><ul><li><code>https://example.com/blog</code></li><li><code>https://example.com/category/news</code> (sirf us category ke posts)</li><li><code>https://store.com/blogs/news</code> (Shopify)</li></ul><p><b>Test karo</b> dabao — tool bata dega kitne posts mile.</p>` },
  "blog.title": { t: "Shopify blog ka naam", b: `<p>Shopify me kis blog me articles daalne hain (jaise <b>News</b> ya <b>Journal</b>). Is naam ka blog na ho to ban jayega. Khali chhoro to website ke naam se banega.</p>` },
  "blog.options": { t: "Options", b: `<ul><li><b>Images copy karo</b>: post ke andar wali images Shopify Files me copy ho kar links badal jaate hain — purani site band ho jaye tab bhi images rahengi.</li><li><b>Asli date</b>: post ki original publish date rakho.</li><li><b>Max posts</b>: zyada se zyada kitne posts.</li></ul>` },
};

// ------------------------------------------------------------------ nav
const NAV = [
  { group: "Overview" },
  { id: "home", label: "Dashboard", icon: "home" },
  { group: "Import / Migrate" },
  { id: "migrate", label: "Store → Store", icon: "migrate", badge: "EXACT" },
  { id: "demo", label: "Theme Demo → Store", icon: "demo" },
  { id: "woo", label: "WooCommerce", icon: "woo" },
  { id: "blog", label: "Blog Import", icon: "blog" },
  { group: "Tools" },
  { id: "token", label: "API Access / Token Lab", icon: "key" },
  { id: "guide", label: "Guide (Roman Urdu)", icon: "book" },
  { id: "run", label: "Live Progress", icon: "live", hidden: true },
];
const TITLES = {
  home: ["Dashboard", "Store data, ek click me"], migrate: ["Store → Store", "Exact Store Migration"],
  demo: ["Theme Demo → Store", "Demo content import"], woo: ["WooCommerce → Shopify", "Product import"],
  blog: ["Blog Import", "Kisi bhi website se blogs"], token: ["API Access", "Token Lab"],
  guide: ["Guide", "Har cheez step-by-step"], run: ["Live Progress", "Kaam chal raha hai"],
};

function renderNav() {
  $("#nav").innerHTML = NAV.map((n, i) => n.group
    ? `<div class="group">${n.group}</div>`
    : `<a href="#${n.id}" data-view="${n.id}" class="${n.hidden ? "hidden" : ""}" style="animation-delay:${0.05 * i}s">${I[n.icon]}<span>${n.label}</span>${n.badge ? `<em class="badge">${n.badge}</em>` : ""}<i class="live"></i></a>`).join("");
  $$("#nav a").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); show(a.dataset.view); }));
}

function show(view) {
  $$(".view").forEach((v) => v.classList.toggle("active", v.dataset.view === view));
  $$("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.view === view));
  const [crumb, title] = TITLES[view] || ["", ""];
  $("#crumb").textContent = crumb;
  $("#pageTitle").textContent = title;
  if (view !== "run") LAST_FORM_VIEW = view;
  $("#content").scrollTop = 0;
  const panel = $(`.view[data-view="${view}"] .help-panel`);
  if (panel) setHelp(panel, view);
}

// ------------------------------------------------------------------ help panel
function setHelp(panel, key) {
  const h = HELP[key];
  if (!h || panel.dataset.key === key) return;
  panel.dataset.key = key;
  panel.innerHTML = `<div class="fade-swap"><div class="hp-tag">${I.info} Guide</div><h3>${h.t}</h3>${h.b}</div>`;
  $$("[data-open]", panel).forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); api("/api/open", { url: a.dataset.open }); }));
}
function bindHelp(root, panel) {
  $$("[data-help]", root).forEach((el) => {
    const key = el.dataset.help;
    el.addEventListener("focusin", () => setHelp(panel, key));
    el.addEventListener("mouseenter", () => { if (!root.contains(document.activeElement) || document.activeElement === document.body) setHelp(panel, key); });
  });
  $$(".q", root).forEach((q) => q.addEventListener("click", () => setHelp(panel, q.dataset.q)));
}

// ------------------------------------------------------------------ form builders
const fieldHTML = ({ id, label, help, placeholder = "", type = "text", hint = "", req = false, mono = false, value = "", btn = "" }) => `
  <div class="field" data-help="${help}">
    <label class="label" for="${id}">${label}${req ? '<span class="req">*</span>' : ""}<button type="button" class="q" data-q="${help}" title="Guide">?</button></label>
    <div class="${btn ? "input-wrap" : ""}">
      <input class="input${mono ? " mono" : ""}" id="${id}" type="${type}" placeholder="${esc(placeholder)}" value="${esc(value)}" autocomplete="off" spellcheck="false">
      ${btn}
    </div>
    ${hint ? `<div class="hint">${hint}</div>` : ""}
    <div class="err-text"></div>
  </div>`;

const showBtn = (id) => `<button type="button" class="in-btn" data-toggle="${id}">Dikhao</button>`;

function optsHTML(name, items, help) {
  return `<div class="opts" data-help="${help}">${items.map((o) => `
    <label class="opt ${o.on !== false ? "on" : ""}" data-key="${o.k}">
      <input type="checkbox" name="${name}" value="${o.k}" ${o.on !== false ? "checked" : ""}>
      <span class="box">${I.check}</span>
      <span><div class="t">${o.t}</div><div class="d">${o.d}</div></span>
      ${o.tag ? `<em class="tag">${o.tag}</em>` : ""}
    </label>`).join("")}</div>`;
}
function bindOpts(root) {
  $$(".opt input", root).forEach((inp) => inp.addEventListener("change", () => inp.closest(".opt").classList.toggle("on", inp.checked)));
  $$("[data-toggle]", root).forEach((b) => b.addEventListener("click", () => {
    const inp = $("#" + b.dataset.toggle);
    inp.type = inp.type === "password" ? "text" : "password";
    b.textContent = inp.type === "password" ? "Dikhao" : "Chhupao";
  }));
}
const checked = (root, name) => $$(`input[name="${name}"]:checked`, root).map((i) => i.value);
const toggleHTML = (id, title, sub, on = true, help = "") => `
  <label class="toggle" data-help="${help}"><input type="checkbox" id="${id}" ${on ? "checked" : ""}><span class="sw"></span><span class="tl">${title}<small>${sub}</small></span></label>`;

function setErr(input, msg) {
  const f = input.closest(".field");
  input.classList.toggle("invalid", !!msg);
  if (f) { f.classList.toggle("has-err", !!msg); $(".err-text", f).textContent = msg || ""; }
  if (msg) input.focus();
  return !msg;
}

// ------------------------------------------------------------------ store connector
const CONNECTORS = {};

function connectorHTML(cid, { title, sub, num, role }) {
  const redirect = INFO ? INFO.redirect_uri : "http://localhost:8765/oauth/callback";
  return `
  <div class="card connector" id="${cid}" data-role="${role}">
    <div class="card-h"><div class="num">${num}</div><div><h2>${title}</h2><p>${sub}</p></div>
      <div class="right conn-right"><button type="button" class="btn sm ghost" data-setup-open title="Dev Dashboard app kaise banayein">${I.book} Setup guide</button><span class="chip" data-conn-state>Connect nahi hua</span></div></div>
    ${fieldHTML({ id: `${cid}-domain`, label: "Store domain", help: "conn.domain", placeholder: "my-store.myshopify.com", req: true, hint: "myshopify.com wala address — admin URL bhi chalega." })}
    <div class="field" data-help="conn.method">
      <label class="label">Access ka tareeqa <button type="button" class="q" data-q="conn.method">?</button></label>
      <div class="seg" data-seg>
        <button type="button" data-m="token" class="on">Access Token <small>shpat_</small></button>
        <button type="button" data-m="cc">Client ID + Secret <small>apni org</small></button>
        <button type="button" data-m="oauth">Client store <small>OAuth</small></button>
      </div>
    </div>
    <div data-pane="token">${fieldHTML({ id: `${cid}-token`, label: "Admin API access token", help: "conn.token", placeholder: "shpat_xxxxxxxxxxxxxxxx", type: "password", mono: true, btn: showBtn(`${cid}-token`), req: true })}</div>
    <div data-pane="cc" class="hidden"><div class="grid g2">
      ${fieldHTML({ id: `${cid}-cid`, label: "Client ID", help: "conn.cc", placeholder: "Dev Dashboard → app → Settings", mono: true, req: true })}
      ${fieldHTML({ id: `${cid}-secret`, label: "Client secret", help: "conn.cc", placeholder: "shpss_... / secret", type: "password", mono: true, btn: showBtn(`${cid}-secret`), req: true })}
    </div></div>
    <div data-pane="oauth" class="hidden">
      <div class="grid g2">
        ${fieldHTML({ id: `${cid}-ocid`, label: "Client ID", help: "conn.oauth", placeholder: "Custom distribution app ka Client ID", mono: true, req: true })}
        ${fieldHTML({ id: `${cid}-osecret`, label: "Client secret", help: "conn.oauth", placeholder: "secret", type: "password", mono: true, btn: showBtn(`${cid}-osecret`), req: true })}
      </div>
      ${fieldHTML({ id: `${cid}-redirect`, label: "Redirect URL (Dev Dashboard me yahi daalo)", help: "conn.oauth", value: redirect, mono: true, btn: `<button type="button" class="in-btn" data-copy="${cid}-redirect">Copy</button>`, hint: INFO && !INFO.oauth_port_ok ? "<b style='color:var(--warn)'>Port 8765 kisi aur program ke paas hai — OAuth ke liye woh program band karo ya Paste URL tareeqa use karo.</b>" : "" })}
      <div class="field hidden" data-oauth-paste>
        <label class="label">Paste URL (agar browser khud wapas na aaye)</label>
        <div class="input-wrap"><input class="input mono" id="${cid}-paste" placeholder="Approve ke baad address bar ka poora URL"><button type="button" class="in-btn" data-paste-go>Use karo</button></div>
      </div>
    </div>
    <div class="btn-row mt16">
      <button type="button" class="btn em" data-connect><span class="spin"></span><span class="lbl-ico">${I.plug}</span><span data-connect-lbl>Connect &amp; Test</span></button>
      <span class="hint" data-conn-hint>Scopes aur store ka naam check ho jayega.</span>
    </div>
    <div class="conn-result" data-result></div>
  </div>`;
}

function initConnector(cid) {
  const root = $("#" + cid);
  const st = CONNECTORS[cid] = { method: "token", verified: null, role: root.dataset.role };
  const dom = $(`#${cid}-domain`);
  const panes = $$("[data-pane]", root);
  const lbl = $("[data-connect-lbl]", root);
  const setMethod = (m) => {
    st.method = m;
    $$("[data-seg] button", root).forEach((b) => b.classList.toggle("on", b.dataset.m === m));
    panes.forEach((p) => p.classList.toggle("hidden", p.dataset.pane !== m));
    lbl.textContent = m === "oauth" ? "Authorize (browser me)" : (m === "cc" ? "Token banao & Test" : "Connect & Test");
    invalidate();
  };
  const invalidate = () => {
    if (!st.verified) return;
    st.verified = null;
    $("[data-conn-state]", root).className = "chip";
    $("[data-conn-state]", root).textContent = "Dobara test karo";
  };
  $$("[data-seg] button", root).forEach((b) => b.addEventListener("click", () => setMethod(b.dataset.m)));
  $$("input", root).forEach((i) => i.addEventListener("input", () => { invalidate(); if (i.classList.contains("invalid")) setErr(i, ""); }));
  $$("[data-copy]", root).forEach((b) => b.addEventListener("click", () => copy($("#" + b.dataset.copy).value)));
  $(`#${cid}-redirect`).readOnly = true;
  dom.addEventListener("change", () => {
    const s = SESSION[normDomain(dom.value)];
    const hint = $("[data-conn-hint]", root);
    if (s && !st.verified) {
      hint.innerHTML = 'Yeh store is session me pehle se connected hai. <button type="button" class="btn sm" data-reuse>Wahi connection use karo</button>';
      $("[data-reuse]", hint).addEventListener("click", () => applySession(cid, s));
    }
  });
  $("[data-connect]", root).addEventListener("click", () => doConnect(cid));
  $("[data-setup-open]", root).addEventListener("click", () => {
    const kind = st.role === "migrate_source" ? "own" : st.role === "migrate_dest" || st.method === "oauth" ? "client" : "own";
    openSetup(kind, dom.value);
  });
  $("[data-paste-go]", root).addEventListener("click", () => manualOAuth(cid));
  st.setMethod = setMethod;
}

function normDomain(v) {
  v = (v || "").trim().toLowerCase();
  const m = v.match(/admin\.shopify\.com\/store\/([a-z0-9-]+)/);
  if (m) return `${m[1]}.myshopify.com`;
  v = v.replace(/^https?:\/\//, "").split("/")[0].split("?")[0];
  return v && !v.includes(".") ? `${v}.myshopify.com` : v;
}

function connPayload(cid) {
  const st = CONNECTORS[cid];
  const d = normDomain($(`#${cid}-domain`).value);
  if (st.method === "cc") return { domain: d, method: "cc", client_id: $(`#${cid}-cid`).value.trim(), client_secret: $(`#${cid}-secret`).value.trim() };
  if (st.method === "oauth") return { domain: d, method: "token", token: st.oauthToken || "" };
  return { domain: d, method: "token", token: $(`#${cid}-token`).value.trim() };
}

function validateConn(cid) {
  const st = CONNECTORS[cid];
  const dom = $(`#${cid}-domain`);
  if (!normDomain(dom.value) || !normDomain(dom.value).includes(".")) return setErr(dom, "Store domain likho — jaise my-store.myshopify.com");
  if (st.method === "token" && !$(`#${cid}-token`).value.trim()) return setErr($(`#${cid}-token`), "Access token likho");
  if (st.method === "cc") {
    if (!$(`#${cid}-cid`).value.trim()) return setErr($(`#${cid}-cid`), "Client ID likho");
    if (!$(`#${cid}-secret`).value.trim()) return setErr($(`#${cid}-secret`), "Client secret likho");
  }
  if (st.method === "oauth") {
    if (!$(`#${cid}-ocid`).value.trim()) return setErr($(`#${cid}-ocid`), "Client ID likho");
    if (!$(`#${cid}-osecret`).value.trim()) return setErr($(`#${cid}-osecret`), "Client secret likho");
  }
  return true;
}

async function doConnect(cid) {
  if (!validateConn(cid)) return false;
  const st = CONNECTORS[cid];
  const root = $("#" + cid);
  const btn = $("[data-connect]", root);
  btn.classList.add("loading"); btn.disabled = true;
  try {
    let res;
    if (st.method === "oauth") {
      res = await runOAuth(cid);
      if (!res) return false;
    } else {
      res = await api("/api/connect", { ...connPayload(cid), role: st.role });
    }
    showResult(cid, res);
    return true;
  } catch (e) {
    showFail(cid, e.message);
    return false;
  } finally {
    btn.classList.remove("loading"); btn.disabled = false;
  }
}

async function runOAuth(cid) {
  const st = CONNECTORS[cid];
  const root = $("#" + cid);
  const start = await api("/api/oauth/start", {
    domain: normDomain($(`#${cid}-domain`).value), client_id: $(`#${cid}-ocid`).value.trim(),
    client_secret: $(`#${cid}-osecret`).value.trim(), scopes: st.role === "migrate_source" ? INFO.source_recommended : INFO.recommended,
    redirect_uri: $(`#${cid}-redirect`).value.trim(),
  });
  st.oauthState = start.state;
  $("[data-oauth-paste]", root).classList.remove("hidden");
  $("[data-conn-hint]", root).innerHTML = "Browser me Shopify page khula hai — <b>Install / Approve</b> dabao. Main yahan wait kar raha hoon…";
  toast("Browser me Shopify ka approval page khul gaya", "info");
  const until = Date.now() + 5 * 60 * 1000;
  while (Date.now() < until && st.oauthState === start.state) {
    await sleep(1500);
    const s = await api("/api/oauth/status", { state: start.state, role: st.role });
    if (s.status === "done") { st.oauthToken = s.token; return Object.assign(s.verify, { method: "oauth" }); }
    if (s.status === "error") throw new Error(s.error);
  }
  if (st.oauthState === start.state) throw new Error("5 minute me approve nahi hua — dobara Authorize dabao.");
  return null;
}

async function manualOAuth(cid) {
  const st = CONNECTORS[cid];
  const url = $(`#${cid}-paste`).value.trim();
  if (!url.includes("code=")) return setErr($(`#${cid}-paste`), "URL me ?code= hona chahiye");
  try {
    const r = await api("/api/oauth/manual", { url, role: st.role });
    st.oauthState = null;
    st.oauthToken = r.token;
    showResult(cid, Object.assign(r.verify, { method: "oauth" }));
  } catch (e) { showFail(cid, e.message); }
}

function showResult(cid, res) {
  const st = CONNECTORS[cid];
  const root = $("#" + cid);
  st.verified = res;
  st.verifiedKey = JSON.stringify(connPayload(cid));
  const rep = res.report || { known: false, missing: [], missing_optional: [] };
  const box = $("[data-result]", root);
  const scopes = res.scopes || [];
  const bad = rep.missing.length > 0;
  box.className = `conn-result show ${bad ? "bad" : "ok"}`;
  const needs = INFO.scopes[st.role] || { required: [], optional: [] };
  const chips = [...needs.required.map((s) => `<span class="chip ${rep.missing.includes(s) ? "miss" : "ok"}">${rep.missing.includes(s) ? "✕" : "✓"} ${s}</span>`),
    ...needs.optional.map((s) => `<span class="chip ${rep.missing_optional.includes(s) ? "optl" : "ok"}">${rep.missing_optional.includes(s) ? "○" : "✓"} ${s}</span>`)].join("");
  const tokenLine = res.token ? `<div class="token-box"><code>${esc(res.token.slice(0, 12))}••••••••••••</code><button type="button" class="btn sm" data-copy-token>Token copy</button></div>` : "";
  box.innerHTML = `
    <div class="cr-h"><div class="cr-ico">${bad ? "!" : "✓"}</div><div>
      <div class="cr-t">${esc(res.shop?.name || res.domain)}</div>
      <div class="cr-s">${esc(res.shop?.myshopify_domain || res.domain)}${res.shop?.plan ? " · " + esc(res.shop.plan) : ""}${res.method === "cc" ? " · token 24 ghante (auto-renew)" : ""}</div></div></div>
    <div class="cr-body">
      ${rep.known ? (bad ? `<b style="color:var(--err)">Yeh scopes missing hain</b> — app ke version me add karo, Release karo, phir store par app update/approve karo:` : `<b style="color:var(--ok)">Saari zaroori permissions maujood hain.</b>${rep.missing_optional.length ? " Peele wale optional hain — un ke baghair woh hissa skip hoga." : ""}`) : "Scopes check nahi ho sake (token phir bhi chal sakta hai)."}
      <div class="chips">${chips || scopes.map((s) => `<span class="chip">${esc(s)}</span>`).join("")}</div>
      ${tokenLine}
    </div>`;
  const tb = $("[data-copy-token]", box);
  if (tb) tb.addEventListener("click", () => copy(res.token));
  const chip = $("[data-conn-state]", root);
  chip.className = `chip ${bad ? "miss" : "ok"}`;
  chip.textContent = bad ? "Scopes kam hain" : "✓ Connected";
  $("[data-conn-hint]", root).textContent = bad ? "Scopes theek karo phir dobara test karo." : "Connected — ab Run kar sakte ho.";
  const d = normDomain($(`#${cid}-domain`).value);
  SESSION[d] = { method: st.method, token: res.token, client_id: $(`#${cid}-cid`).value.trim() || $(`#${cid}-ocid`).value.trim(),
    client_secret: $(`#${cid}-secret`).value.trim(), result: res };
  if (st.method === "oauth") SESSION[d].method = "token";
  rememberDomain(d);
  toast(`${res.shop?.name || d} connected`, bad ? "warn" : "ok");
}

function showFail(cid, msg) {
  const root = $("#" + cid);
  CONNECTORS[cid].verified = null;
  const box = $("[data-result]", root);
  box.className = "conn-result show bad";
  box.innerHTML = `<div class="cr-h"><div class="cr-ico">!</div><div><div class="cr-t">Connect nahi hua</div><div class="cr-s">${esc(msg)}</div></div></div>
    <div class="cr-body">Masle ka hal: left menu → <b>Guide</b> → "Masle aur hal".</div>`;
  const chip = $("[data-conn-state]", root);
  chip.className = "chip miss"; chip.textContent = "Fail";
  $("[data-conn-hint]", root).textContent = "Details check kar ke dobara try karo.";
}

function applySession(cid, s) {
  const st = CONNECTORS[cid];
  $("[data-conn-hint]", $("#" + cid)).textContent = "Pichla connection check ho raha hai…";
  if (s.method === "cc") {
    st.setMethod("cc");
    $(`#${cid}-cid`).value = s.client_id; $(`#${cid}-secret`).value = s.client_secret;
  } else {
    st.setMethod("token");
    $(`#${cid}-token`).value = s.token;
  }
  api("/api/connect", { ...connPayload(cid), role: st.role }).then((r) => showResult(cid, r)).catch((e) => showFail(cid, e.message));
}

// ------------------------------------------------------------------ settings memory (sirf domains / URLs, secrets nahi)
let SETTINGS = {};
function rememberDomain(d) {
  const list = (SETTINGS.domains || []).filter((x) => x !== d);
  list.unshift(d);
  SETTINGS.domains = list.slice(0, 12);
  api("/api/settings", { domains: SETTINGS.domains }).catch(() => {});
  fillDomainList();
}
function fillDomainList() {
  let dl = $("#domainList");
  if (!dl) { dl = document.createElement("datalist"); dl.id = "domainList"; document.body.appendChild(dl); }
  dl.innerHTML = (SETTINGS.domains || []).map((d) => `<option value="${esc(d)}">`).join("");
  $$("input[id$='-domain']").forEach((i) => i.setAttribute("list", "domainList"));
}
function rememberLast(key, values) {
  SETTINGS.last = Object.assign(SETTINGS.last || {}, { [key]: values });
  api("/api/settings", { last: SETTINGS.last }).catch(() => {});
}

// ------------------------------------------------------------------ views
function modeLayout(view, inner) {
  return `<div class="mode-layout"><div class="mode-main">${inner}</div><aside class="help-panel"></aside></div>`;
}
function runBar(view, text, sub, label) {
  return `<div class="sticky-run"><div><div class="sr-t">${text}</div><div class="sr-s">${sub}</div></div><div class="spacer"></div>
    <button class="btn gold lg" data-run="${view}"><span class="spin"></span><span class="lbl-ico">${I.play}</span>${label}</button></div>`;
}

function renderHome() {
  const v = $('.view[data-view="home"]');
  const cards = [
    ["migrate", "Store → Store Migration", "Apne store par bana hua poora store client ke store par — products, collections, files, blogs, pages, menus, metafields aur theme. Bilkul exact.", ["Handles same", "Smart rules", "Theme copy", "Menus"]],
    ["demo", "Theme Demo → Store", "ThemeForest / Envato demo store ka content (section images, products, collections, blogs, pages) apne store me — theme demo jaisa dikhe.", ["Password demo", "Original images", "Page templates"]],
    ["woo", "WooCommerce → Shopify", "WordPress store ke products variants, sale price, stock, images aur categories ke saath. SEO redirects bhi.", ["Variations", "Stock", "Redirects"]],
    ["blog", "Blog Import", "Kisi bhi website ke blog posts — WordPress API auto-detect, baaqi sites smart scraping se. Images bhi copy.", ["WordPress API", "Dates", "Images re-host"]],
  ];
  v.innerHTML = `
    <div class="hero">
      <div class="eyebrow">Premium Edition · v${esc(INFO?.version || "3")}</div>
      <h2>Shopify data transfer — <em>hu-ba-hu</em>, bina kuch tootay.</h2>
      <p>Store migration, theme demo content, WooCommerce products aur blogs — sab ek jagah. Har field ke saath Roman Urdu guide, live progress, aur dobara chalao to duplicate nahi banta.</p>
      <div class="btn-row"><button class="btn gold lg" data-go="migrate">${I.migrate} Migration shuru karo</button><button class="btn lg" data-go="token">${I.key} Pehle API access banao</button></div>
      <div class="stats-strip"><div><b>4</b>Import modes</div><div><b>${esc(INFO?.api_version || "")}</b>Shopify API</div><div><b>100%</b>Local — data kahin aur nahi jata</div><div><b>0</b>Install ki zaroorat</div></div>
    </div>
    <div class="modes">${cards.map(([id, t, d, chips]) => `
      <div class="mode-card" data-go="${id}"><div class="mi">${I[id]}</div><h3>${t}</h3><p>${d}</p>
        <div class="chips">${chips.map((c) => `<span class="chip">${c}</span>`).join("")}</div>
        <div class="go">Shuru karo ${I.arrow}</div></div>`).join("")}</div>
    <div class="steps3">
      <div class="s"><b>01</b><h4>API access banao</h4><p>Token Lab me store connect karo — Guide me Dev Dashboard ka har step hai.</p></div>
      <div class="s"><b>02</b><h4>Mode chuno</h4><p>Store, demo, WooCommerce ya blog — fields bharo, har field ki guide right side par.</p></div>
      <div class="s"><b>03</b><h4>Run & dekho</h4><p>Live progress, har step ka status, aur aakhir me poori report.</p></div>
    </div>`;
  $$("[data-go]", v).forEach((el) => el.addEventListener("click", () => show(el.dataset.go)));
  $$(".mode-card", v).forEach((c) => c.addEventListener("mousemove", (e) => {
    const r = c.getBoundingClientRect();
    c.style.setProperty("--mx", `${e.clientX - r.left}px`); c.style.setProperty("--my", `${e.clientY - r.top}px`);
  }));
}

function renderMigrate() {
  const v = $('.view[data-view="migrate"]');
  v.innerHTML = modeLayout("migrate", `
    ${connectorHTML("mg-src", { num: "1", title: "Source store (jahan store bana hai)", sub: "Aap ka store — sirf read access chahiye", role: "migrate_source" })}
    ${connectorHTML("mg-dst", { num: "2", title: "Destination store (client ka store)", sub: "Jahan sab kuch jana hai — write access chahiye", role: "migrate_dest" })}
    <div class="card">
      <div class="card-h"><div class="num">3</div><div><h2>Kya kya migrate karna hai</h2><p>Sab select rakho = poora store exact</p></div>
        <div class="right"><button class="q" data-q="migrate.steps" style="width:28px;height:28px">?</button></div></div>
      ${optsHTML("mg-steps", [
        { k: "files", t: "Files", d: "Banners, logos, icons, SVG, PDF, videos — same naam" },
        { k: "products", t: "Products", d: "Variants, images, status, templates, SEO" },
        { k: "collections", t: "Collections", d: "Manual + smart rules, images" },
        { k: "blogs", t: "Blogs & articles", d: "Dates, authors, tags, images" },
        { k: "pages", t: "Pages", d: "Templates ke saath (about, contact…)" },
        { k: "menus", t: "Navigation menus", d: "Main + footer, links naye store par" },
        { k: "shopmeta", t: "Store metafields", d: "Shop-level custom data" },
        { k: "theme", t: "Theme copy", d: "Unpublished theme + ZIP backup", tag: "NEW" },
        { k: "verify", t: "Verify", d: "Theme ke har link ki jaanch" },
      ], "migrate.steps")}
      <hr class="gold-line">
      <div class="grid g2" data-help="migrate.options">
        ${toggleHTML("mg-inv", "Inventory quantities", "Har variant ka stock destination location par", true, "migrate.options")}
        ${toggleHTML("mg-meta", "Metafields", "Products, collections, pages, blogs, articles", true, "migrate.options")}
      </div>
    </div>
    ${runBar("migrate", "Tayar ho?", "Pehle dono stores 'Connect & Test' karo. Dobara chalane par jo aa chuka hai woh skip hoga.", "Migration shuru karo")}`);
  initConnector("mg-src"); initConnector("mg-dst");
  bindOpts(v); bindHelp(v, $(".help-panel", v));
}

function renderDemo() {
  const v = $('.view[data-view="demo"]');
  const last = (SETTINGS.last || {}).demo || {};
  v.innerHTML = modeLayout("demo", `
    <div class="card">
      <div class="card-h"><div class="num">1</div><div><h2>Theme demo store</h2><p>Envato / ThemeForest ka password wala demo</p></div></div>
      <div class="grid g2">
        ${fieldHTML({ id: "dm-url", label: "Demo store URL", help: "demo.url", placeholder: "https://theme-demo.myshopify.com/?preview_theme_id=…", req: true, value: last.demo_url || "", hint: "Multi-demo theme? Preview bar ka <b>Copy link</b> wala poora URL do." })}
        ${fieldHTML({ id: "dm-pass", label: "Demo password", help: "demo.password", placeholder: "jaise 1", type: "password", btn: showBtn("dm-pass") })}
      </div>
      <div class="btn-row mt16"><button class="btn" id="dm-test"><span class="spin"></span><span class="lbl-ico">${I.plug}</span>Test karo</button><span class="hint" id="dm-test-out">Login aur products ki ginti check hogi.</span></div>
    </div>
    ${connectorHTML("dm-dst", { num: "2", title: "Aap ka store (destination)", sub: "Jahan theme install hai", role: "demo_dest" })}
    <div class="card">
      <div class="card-h"><div class="num">3</div><div><h2>Kya import karna hai</h2><p>Theme demo jaisa banane ke liye sab select rakho</p></div></div>
      ${optsHTML("dm-steps", [
        { k: "files", t: "Section images", d: "Banners, icons, backgrounds → Files" },
        { k: "products", t: "Products", d: "Variants, images, variant images" },
        { k: "collections", t: "Collections", d: "Image, description, products" },
        { k: "blogs", t: "Blogs", d: "Poora content, date, author" },
        { k: "pages", t: "Pages", d: "Theme template khud lagta hai", tag: "NEW" },
        { k: "verify", t: "Verify", d: "Theme ke links check" },
      ], "demo.steps")}
      <hr class="gold-line">
      <div class="field" data-help="demo.scope" style="max-width:420px">
        <label class="label" for="dm-scope">Images kin pages se <button type="button" class="q" data-q="demo.scope">?</button></label>
        <select class="input" id="dm-scope"><option value="all">Sab kuch (recommended)</option><option value="home">Sirf Home page</option><option value="product">Sirf Product page</option><option value="collection">Sirf Collection page</option><option value="blog">Sirf Blog page</option><option value="pages">Sirf /pages/ pages</option></select>
      </div>
    </div>
    ${runBar("demo", "Demo content import", "Pehle theme apne store me install kar lo — phir yeh run karo.", "Import shuru karo")}`);
  initConnector("dm-dst");
  bindOpts(v); bindHelp(v, $(".help-panel", v));
  $("#dm-test").addEventListener("click", async (e) => {
    const b = e.currentTarget;
    if (!$("#dm-url").value.trim()) return setErr($("#dm-url"), "Demo URL likho");
    b.classList.add("loading");
    try {
      const r = await api("/api/demo/test", { demo_url: $("#dm-url").value.trim(), password: $("#dm-pass").value });
      $("#dm-test-out").innerHTML = r.ok ? `<b style="color:var(--ok)">✓ ${esc(r.message)}</b> ${r.products != null ? `— ${r.products} products mile` : ""}` : `<b style="color:var(--err)">✕ ${esc(r.message)}</b>`;
    } catch (err) { $("#dm-test-out").innerHTML = `<b style="color:var(--err)">✕ ${esc(err.message)}</b>`; }
    b.classList.remove("loading");
  });
}

function renderWoo() {
  const v = $('.view[data-view="woo"]');
  const last = (SETTINGS.last || {}).woo || {};
  v.innerHTML = modeLayout("woo", `
    <div class="card">
      <div class="card-h"><div class="num">1</div><div><h2>WooCommerce store</h2><p>WordPress site + REST API keys</p></div></div>
      ${fieldHTML({ id: "wc-url", label: "WordPress site URL", help: "woo.url", placeholder: "https://clientstore.com", req: true, value: last.wc_url || "" })}
      <div class="grid g2 mt16">
        ${fieldHTML({ id: "wc-ck", label: "Consumer key", help: "woo.keys", placeholder: "ck_xxxxxxxx", mono: true, req: true })}
        ${fieldHTML({ id: "wc-cs", label: "Consumer secret", help: "woo.keys", placeholder: "cs_xxxxxxxx", type: "password", mono: true, req: true, btn: showBtn("wc-cs") })}
      </div>
      <div class="btn-row mt16"><button class="btn" id="wc-test"><span class="spin"></span><span class="lbl-ico">${I.plug}</span>Test karo</button><span class="hint" id="wc-test-out">Keys aur products ki ginti check hogi.</span></div>
    </div>
    ${connectorHTML("wc-dst", { num: "2", title: "Shopify store (destination)", sub: "Jahan products jaane hain", role: "woo_dest" })}
    <div class="card">
      <div class="card-h"><div class="num">3</div><div><h2>Kya karna hai</h2><p>Import ya pehle sirf check</p></div></div>
      <div class="field" data-help="woo.mode"><div class="seg" id="wc-mode"><button type="button" class="on" data-m="import">Import karo</button><button type="button" data-m="verify">Sirf check (report)</button></div></div>
      <div id="wc-import-opts" class="mt16">
        ${optsHTML("wc-steps", [
          { k: "products", t: "Products", d: "Variants, sale price, stock, images" },
          { k: "collections", t: "Categories → Collections", d: "Parent me child ke products bhi" },
          { k: "redirects", t: "SEO redirects", d: "/product/… → /products/…" },
        ], "woo.mode")}
        <hr class="gold-line">
        <div class="grid g2">${toggleHTML("wc-drafts", "Draft products bhi", "Draft / private products Shopify me Draft banenge", false, "woo.mode")}
        ${toggleHTML("wc-attrs", "Baaqi attributes", "Material, brand waghera metafield me (custom.woo_attributes)", true, "woo.mode")}</div>
      </div>
    </div>
    ${runBar("woo", "WooCommerce import", "Jo product pehle se hai (same slug / naam) woh skip hoga.", "Shuru karo")}`);
  initConnector("wc-dst");
  bindOpts(v); bindHelp(v, $(".help-panel", v));
  $$("#wc-mode button").forEach((b) => b.addEventListener("click", () => {
    $$("#wc-mode button").forEach((x) => x.classList.toggle("on", x === b));
    $("#wc-import-opts").classList.toggle("hidden", b.dataset.m === "verify");
  }));
  $("#wc-test").addEventListener("click", async (e) => {
    const b = e.currentTarget;
    if (!$("#wc-url").value.trim()) return setErr($("#wc-url"), "Site URL likho");
    b.classList.add("loading");
    try {
      const r = await api("/api/woo/test", { wc_url: $("#wc-url").value.trim(), ck: $("#wc-ck").value.trim(), cs: $("#wc-cs").value.trim() });
      $("#wc-test-out").innerHTML = r.ok ? `<b style="color:var(--ok)">✓ ${esc(r.message)}</b> ${r.products ? `— ${esc(r.products)} products` : ""}` : `<b style="color:var(--err)">✕ ${esc(r.message)}</b>`;
    } catch (err) { $("#wc-test-out").innerHTML = `<b style="color:var(--err)">✕ ${esc(err.message)}</b>`; }
    b.classList.remove("loading");
  });
}

function renderBlog() {
  const v = $('.view[data-view="blog"]');
  const last = (SETTINGS.last || {}).blog || {};
  v.innerHTML = modeLayout("blog", `
    <div class="card">
      <div class="card-h"><div class="num">1</div><div><h2>Blog kahan se</h2><p>Website ka blog listing page</p></div></div>
      ${fieldHTML({ id: "bl-url", label: "Blog listing URL", help: "blog.url", placeholder: "https://www.example.com/blog", req: true, value: last.listing_url || "" })}
      <div class="btn-row mt16"><button class="btn" id="bl-test"><span class="spin"></span><span class="lbl-ico">${I.plug}</span>Test karo</button><span class="hint" id="bl-test-out">Site ka type aur posts ki ginti check hogi.</span></div>
      <div id="bl-sample" class="hint mt8"></div>
    </div>
    ${connectorHTML("bl-dst", { num: "2", title: "Shopify store (destination)", sub: "Articles yahan banenge", role: "blog_dest" })}
    <div class="card">
      <div class="card-h"><div class="num">3</div><div><h2>Blog settings</h2><p>Shopify me kaise aaye</p></div></div>
      <div class="grid g2">
        ${fieldHTML({ id: "bl-title", label: "Shopify blog ka naam", help: "blog.title", placeholder: "News", value: last.blog_title || "" })}
        ${fieldHTML({ id: "bl-max", label: "Max posts", help: "blog.options", placeholder: "500", type: "number", value: "500" })}
      </div>
      <hr class="gold-line">
      <div class="grid g2">
        ${toggleHTML("bl-rehost", "Images apne store par copy karo", "Post ke andar ki images Shopify Files me — links badal jayenge", true, "blog.options")}
        ${toggleHTML("bl-dates", "Asli publish date rakho", "Post ki original date", true, "blog.options")}
      </div>
    </div>
    ${runBar("blog", "Blog import", "Jo article pehle se hai (same handle / title) woh skip hoga.", "Import shuru karo")}`);
  initConnector("bl-dst");
  bindOpts(v); bindHelp(v, $(".help-panel", v));
  $("#bl-test").addEventListener("click", async (e) => {
    const b = e.currentTarget;
    if (!$("#bl-url").value.trim()) return setErr($("#bl-url"), "Blog URL likho");
    b.classList.add("loading");
    $("#bl-test-out").textContent = "Check ho raha hai…";
    try {
      const r = await api("/api/blog/test", { listing_url: $("#bl-url").value.trim() });
      $("#bl-test-out").innerHTML = `<b style="color:${r.ok ? "var(--ok)" : "var(--err)"}">${r.ok ? "✓" : "✕"} ${esc(r.message)}</b>`;
      $("#bl-sample").innerHTML = (r.sample || []).map((s) => `• ${esc(s)}`).join("<br>");
    } catch (err) { $("#bl-test-out").innerHTML = `<b style="color:var(--err)">✕ ${esc(err.message)}</b>`; }
    b.classList.remove("loading");
  });
}


// ------------------------------------------------------------------ setup guide (Dev Dashboard exact values)
const kv = (k, v, note = "") => `<div class="kv"><span class="k">${k}</span><span class="v"><code>${esc(v)}</code>${note ? `<small>${note}</small>` : ""}</span><button type="button" class="btn sm" data-copytext="${esc(v)}">Copy</button></div>`;
const kvTick = (k, on, note = "") => `<div class="kv"><span class="k">${k}</span><span class="v"><span class="tickbox ${on ? "on" : ""}">${on ? I.check : ""}</span><b>${on ? "Tick lagao" : "Untick (khali chhor do)"}</b>${note ? `<small>${note}</small>` : ""}</span><span></span></div>`;
const kvText = (k, v) => `<div class="kv"><span class="k">${k}</span><span class="v">${v}</span><span></span></div>`;

function scopeLists() {
  return { write: (INFO?.recommended || []).join(","), read: (INFO?.source_recommended || []).join(","),
    redirect: INFO?.redirect_uri || "http://localhost:8765/oauth/callback" };
}

function setupHTML(kind, domain, withInput = true) {
  const s = scopeLists();
  const d = normDomain(domain || "") || "client-store.myshopify.com";
  if (kind === "own") return `
    <div class="setup-intro">Yeh tab us store ke liye hai jo <b>aap ki apni Dev Dashboard organization</b> me hai — jaise aap ka dev store jahan aap ne client ka store banaya (migration ka <b>Source</b>). Tool me tareeqa: <b>Client ID + Secret</b>.</div>
    <ol class="setup-steps">
      <li><h4>Dev Dashboard me nayi app banao</h4><p><a href="#" data-open="https://dev.shopify.com">dev.shopify.com</a> → <b>Apps</b> → <b>Create app</b> → naam likho (jaise <i>Data Importer – Source</i>).</p></li>
      <li><h4>URLs section</h4>
        ${kv("App URL", "https://example.com", "Sirf placeholder — tool ko is ki zaroorat nahi")}
        ${kvTick("Embed app in Shopify admin", false)}
        ${kvText("Allowed redirection URL(s)", "Khali chhor do (is store ke liye zaroorat nahi)")}
        ${kvTick("Use legacy install flow", false)}</li>
      <li><h4>API access → Scopes</h4>
        ${kv("Source store (sirf migration)", s.read, "Sirf read — source store me kuch nahi badlega")}
        ${kv("Agar yahi store destination hai", s.write, "Theme Demo / WooCommerce / Blog import ke liye")}</li>
      <li><h4>Baaqi fields jaise hain waise chhor do</h4><p>Version name, Webhooks API version, optional scopes — kuch na badlo. Upar <b>Create app</b> dabao.</p></li>
      <li><h4>App ko apne store par install karo</h4><p>App ke <b>Home / Overview</b> par <b>Install app</b> → apna store chuno → <b>Install</b>. Distribution badalne ki zaroorat nahi.</p>
        <p class="muted">Install ka button na dikhe to: Distribution → Custom distribution → apne store ka domain → Generate link → link khol kar Install.</p></li>
      <li><h4>Client ID + Secret copy karo</h4><p>App → <b>Settings</b> → <b>Client ID</b> aur <b>Client secret</b>.</p></li>
      <li><h4>Tool me connect karo</h4><p>Store → Store → <b>Source</b> → domain → <b>Client ID + Secret</b> → dono paste → <b>Token banao &amp; Test</b> → green ✓.</p>
        <div class="callout tip">Token 24 ghante ka hota hai — kaam ke beech expire ho jaye to tool khud naya le leta hai.</div></li>
    </ol>
    <div class="callout tip"><b>Doosra tareeqa:</b> agar is store me Settings → Apps → <b>Develop apps</b> me "legacy custom app" abhi bhi banti hai (partner dev store transfer se pehle), to wahan app bana kar <code>shpat_</code> token lo aur tool me <b>Access Token</b> chuno. Scopes wahi upar wale.</div>`;
  return `
    <div class="setup-intro">Yeh tab <b>client ke store</b> ke liye hai — jo aap ki organization me nahi (migration ka <b>Destination</b>). App aap ke Dev Dashboard me banegi, <b>Custom distribution</b> se client ke store par install hogi, aur tool <b>OAuth</b> se token lega.</div>
    ${withInput ? `<div class="field setup-domain"><label class="label" for="setup-dom">Client store domain (yahan likho — neeche har jagah sahi format me aa jayega)</label>
      <input class="input mono" id="setup-dom" placeholder="client-store.myshopify.com" value="${esc(domain && normDomain(domain).includes(".") ? normDomain(domain) : "")}"></div>` : ""}
    <ol class="setup-steps">
      <li><h4>Dev Dashboard me nayi app banao</h4><p><a href="#" data-open="https://dev.shopify.com">dev.shopify.com</a> → <b>Apps</b> → <b>Create app</b> → naam likho (jaise <i>Data Importer – ${esc(d.split(".")[0])}</i>). <b>Har client ke liye alag app</b> banao.</p></li>
      <li><h4>URLs section — bilkul yeh values</h4>
        ${kv("App URL", "https://example.com", "Localhost NAHI — client apne PC par install karega")}
        ${kvTick("Embed app in Shopify admin", false)}
        ${kv("Allowed redirection URL(s)", s.redirect, "Yahi exact URL — tool isi par token leta hai")}
        ${kvTick("Use legacy install flow", false)}</li>
      <li><h4>API access → Scopes</h4>
        ${kv("Scopes", s.write, "Write me read khud shamil hai — chaaron modes ke liye kaafi")}</li>
      <li><h4>Baaqi fields jaise hain waise chhor do</h4><p>Version name, <b>Webhooks API version</b>, optional scopes — kuch na badlo. Upar <b>Create app</b> dabao.</p></li>
      <li><h4>Distribution → Custom distribution</h4>
        ${kv("Store domain", d, "<b>https:// ke baghair</b> aur aakhir me <b>/ nahi</b>")}
        ${kvTick("Allow multi-store install for one Plus organization", false)}
        ${kvText("Phir", "<b>Generate link</b> dabao")}
        <div class="callout warn">Custom distribution ek dafa chun lo to badalti nahi — is liye har client ki alag app.</div></li>
      <li><h4>Install link client ko bhejo</h4><p>Client link khol kar apne store par <b>Install</b> kare. Agar client ke store par aap ke paas apps install karne ki permission hai to aap khud bhi install kar sakte ho.</p></li>
      <li><h4>Client ID + Secret copy karo</h4><p>App → <b>Settings</b> → <b>Client ID</b> aur <b>Client secret</b>.</p></li>
      <li><h4>Tool me Authorize karo</h4><p>Store → Store → <b>Destination</b> → domain <code>${esc(d)}</code> → <b>Client store (OAuth)</b> → Client ID + Secret → <b>Authorize (browser me)</b> → Shopify page par <b>Approve</b>. Browser me "Token tayar hai" aayega aur tool me green ✓.</p></li>
      <li><h4>Migration shuru karo</h4><p>Saare scopes green hon to destination tayar. Phir <b>Source</b> (aap ka store — "Apna store" tab) connect karo aur <b>Migration shuru karo</b>.</p></li>
    </ol>
    <div class="callout tip"><b>Agar Dev Dashboard localhost wala redirect URL save na kare:</b> wahan <code>https://example.com/callback</code> daal do. Tool me bhi Redirect URL wahi likho. Approve ke baad browser jis page par jaye uska <b>poora URL</b> (jisme <code>?code=</code> ho) tool ke <b>Paste URL</b> box me daal do.</div>
    <div class="callout tip"><b>Asaan doosra raasta:</b> client (store owner) khud apne admin me Settings → Apps → Develop apps → <b>Build apps in Dev Dashboard</b> se yahi "Apna store" wale steps kare aur aap ko Client ID + Secret de. Phir tool me <b>Client ID + Secret</b> chuno.</div>`;
}

function modeScopesHTML() {
  const s = scopeLists();
  return `<table class="tbl"><tr><th>Mode</th><th>Kaunsa store connect hoga</th><th>Scopes</th></tr>
    <tr><td><b>Store → Store</b></td><td>Source: aap ka store<br>Destination: client ka store</td><td><code>${esc(s.read)}</code><br><code>${esc(s.write)}</code></td></tr>
    <tr><td><b>Theme Demo → Store</b></td><td>Destination: jis store me theme install hai</td><td>Kam se kam <code>write_products, write_files, write_content, read_themes</code></td></tr>
    <tr><td><b>WooCommerce → Shopify</b></td><td>Destination: Shopify store</td><td>Kam se kam <code>write_products, write_inventory, read_locations, write_online_store_navigation</code></td></tr>
    <tr><td><b>Blog Import</b></td><td>Destination: Shopify store</td><td>Kam se kam <code>write_content, write_files</code></td></tr></table>
    <div class="callout tip">Sab se asaan: har destination app me poori write list <button type="button" class="btn sm" data-copytext="${esc(s.write)}">Copy</button> daal do — ek hi app chaaron modes me chal jayegi. Store aap ki organization me ho to "Apna store" tab, client ka ho to "Client ka store" tab follow karo.</div>`;
}

function renderSetupCard(host, kind = "client", domain = "") {
  host.innerHTML = `
    <div class="card-h"><div class="num">✦</div><div><h2>Setup Guide — Dev Dashboard app</h2><p>Har field ki exact value, Copy button ke saath. Pehle tab chuno:</p></div></div>
    <div class="seg" data-setup-tabs>
      <button type="button" data-k="client" class="${kind === "client" ? "on" : ""}">Client ka store <small>Destination · OAuth</small></button>
      <button type="button" data-k="own" class="${kind === "own" ? "on" : ""}">Apna store <small>Source · Client ID + Secret</small></button>
      <button type="button" data-k="modes" class="${kind === "modes" ? "on" : ""}">Kis mode me kya <small>scopes</small></button>
    </div>
    <div class="setup-body mt16" data-setup-body>${kind === "modes" ? modeScopesHTML() : setupHTML(kind, domain)}</div>`;
  const body = $("[data-setup-body]", host);
  const bindDomain = () => {
    const inp = $("#setup-dom", body);
    if (inp) inp.addEventListener("input", () => {
      const keep = inp.value, pos = inp.selectionStart;
      body.innerHTML = setupHTML("client", keep);
      const ni = $("#setup-dom", body); ni.value = keep; ni.focus(); try { ni.setSelectionRange(pos, pos); } catch (e) { /* ignore */ }
      bindDomain();
    });
  };
  bindDomain();
  $$("[data-setup-tabs] button", host).forEach((b) => b.addEventListener("click", () => {
    $$("[data-setup-tabs] button", host).forEach((x) => x.classList.toggle("on", x === b));
    const dom = $("#setup-dom", body)?.value || domain;
    body.innerHTML = b.dataset.k === "modes" ? modeScopesHTML() : setupHTML(b.dataset.k, dom);
    bindDomain();
  }));
}

function openSetup(kind, domain) {
  show("token");
  const host = $("#setupCard");
  renderSetupCard(host, kind, domain);
  setTimeout(() => host.scrollIntoView({ behavior: "smooth", block: "start" }), 60);
}

function renderToken() {
  const v = $('.view[data-view="token"]');
  const rec = (INFO?.recommended || []).join(", ");
  const srec = (INFO?.source_recommended || []).join(", ");
  v.innerHTML = modeLayout("token", `
    <div class="card setup-card" id="setupCard"></div>
    ${connectorHTML("lab", { num: "★", title: "Store connect / token banao", sub: "Kisi bhi store ka access yahan test karo — doosre modes me domain likhte hi yahi connection use hoga", role: "migrate_dest" })}
    <div class="card">
      <div class="card-h"><div class="num">i</div><div><h2>App me yeh scopes select karo</h2><p>Dev Dashboard → app → Versions → Access / Scopes</p></div></div>
      <div class="field"><label class="label">Destination / import store (write)</label>
        <div class="input-wrap"><input class="input mono" readonly value="${esc(rec)}" id="sc-rec"><button class="in-btn" data-copy="sc-rec">Copy</button></div></div>
      <div class="field"><label class="label">Source store (sirf read — migration ke liye)</label>
        <div class="input-wrap"><input class="input mono" readonly value="${esc(srec)}" id="sc-src"><button class="in-btn" data-copy="sc-src">Copy</button></div></div>
      <div class="field"><label class="label">OAuth redirect URL</label>
        <div class="input-wrap"><input class="input mono" readonly value="${esc(INFO?.redirect_uri || "")}" id="sc-red"><button class="in-btn" data-copy="sc-red">Copy</button></div></div>
      <div class="btn-row mt16"><button class="btn" data-open="https://dev.shopify.com">${I.ext} Dev Dashboard kholo</button><button class="btn ghost" data-go="guide">${I.book} Poori guide</button></div>
    </div>`);
  renderSetupCard($("#setupCard", v), "client");
  initConnector("lab");
  bindOpts(v); bindHelp(v, $(".help-panel", v));
  $$(".card:not(.connector) [data-copy]", v).forEach((b) => b.addEventListener("click", () => copy($("#" + b.dataset.copy).value)));
  $$("[data-open]", v).forEach((b) => b.addEventListener("click", () => api("/api/open", { url: b.dataset.open })));
  $$("[data-go]", v).forEach((b) => b.addEventListener("click", () => show(b.dataset.go)));
}

function renderGuide() {
  const v = $('.view[data-view="guide"]');
  const red = esc(INFO?.redirect_uri || "http://localhost:8765/oauth/callback");
  const rec = esc((INFO?.recommended || []).join(", "));
  const sections = [
    ["Admin API access kya hai aur kaunsa tareeqa mere liye hai?", `
      <p>Tool Shopify store me products, files, pages waghera <b>Admin API</b> se banata hai. Is ke liye store se ek <b>access token</b> chahiye. 1 January 2026 se Shopify ne merchant stores par purani "Develop apps → Create app" (legacy custom app) band kar di hai — ab apps <b>Dev Dashboard</b> me banti hain.</p>
      <table class="tbl"><tr><th>Store kiska hai</th><th>Tareeqa</th><th>Tool me option</th></tr>
      <tr><td>Aap ki Partner/Dev organization ka store (aap ka dev store)</td><td>Dev Dashboard app → install → Client ID + Secret</td><td><b>Client ID + Secret</b></td></tr>
      <tr><td>Client ka store — client khud app bana sakta hai</td><td>Client apne Dev Dashboard me app banaye, install kare, Client ID + Secret de</td><td><b>Client ID + Secret</b></td></tr>
      <tr><td>Client ka store — app aap banayenge</td><td>Aap ke Dev Dashboard me app → Custom distribution → client install kare</td><td><b>Client store (OAuth)</b></td></tr>
      <tr><td>Store jahan "Develop apps" (legacy) abhi bhi chalta hai</td><td>Legacy custom app → shpat_ token</td><td><b>Access Token</b></td></tr></table>
      <div class="callout tip">Client ke store me "Build apps in Dev Dashboard" button nahi aa raha? Iska matlab aap ke account (staff / collaborator) ko app banane ki permission nahi. Ya to store owner (client) app banaye (section 3), ya aap apne Dev Dashboard se Custom distribution app banao (section 4).</div>`],
    ["Apne store ke liye (Source / same organization): Dev Dashboard app + Client ID / Secret", `<div class="setup-body">${setupHTML("own", "", false)}</div>`],
    ["Client ka store: client khud app banaye (sab se aasaan)", `
      <ol><li>Client (store owner) apne admin me jaaye: <b>Settings → Apps → Develop apps</b> → <b>Build apps in Dev Dashboard</b>.</li>
      <li>Upar wale section 2 ke steps 2–7 follow kare (app banao, scopes, release, apne store par install).</li>
      <li>Client aap ko <b>Client ID</b> aur <b>Client secret</b> bheje (private tareeqe se).</li>
      <li>Tool me client store domain + <b>Client ID + Secret</b> → Test.</li></ol>
      <p>Ya client aap ke staff account ko app development ki permission (<b>App developer</b> role / "Develop apps") de de — phir aap khud yeh button dekh sakenge.</p>`],
    ["Client ka store (Destination): Custom distribution + OAuth — exact values", `<div class="setup-body">${setupHTML("client", "", false)}</div>`],
    ["Purana tareeqa: legacy custom app (shpat_ token)", `
      <p>Sirf un stores par jahan yeh abhi bhi allowed hai (jaise partner dev store transfer se pehle, ya purane stores jin me app pehle se bani hai).</p>
      <ol><li>Admin → <b>Settings → Apps → Develop apps</b> → <b>Create an app</b>.</li><li><b>Configure Admin API scopes</b> → scopes tick karo → Save.</li>
      <li><b>Install app</b> → <b>API credentials</b> → <b>Admin API access token</b> → <b>Reveal token once</b>.</li><li><code>shpat_...</code> copy karo → tool me <b>Access Token</b>.</li></ol>`],
    ["Kaunsa scope kis kaam ke liye", `
      <table class="tbl"><tr><th>Scope</th><th>Kis liye</th></tr>
      <tr><td><code>write_products</code></td><td>Products, variants, collections (read bhi isi me)</td></tr>
      <tr><td><code>write_files</code></td><td>Content → Files (images, SVG, PDF, video) + theme ZIP upload</td></tr>
      <tr><td><code>write_content</code></td><td>Blogs, articles, pages</td></tr>
      <tr><td><code>write_inventory</code> + <code>read_locations</code></td><td>Stock quantities</td></tr>
      <tr><td><code>write_online_store_navigation</code></td><td>Menus aur URL redirects</td></tr>
      <tr><td><code>write_themes</code> / <code>read_themes</code></td><td>Theme copy (destination) / theme read + verify</td></tr>
      <tr><td>Source: <code>read_products, read_files, read_content, read_online_store_navigation, read_themes, read_inventory</code></td><td>Migration me source store sirf padha jata hai</td></tr></table>${modeScopesHTML()}`],
    ["Store → Store migration: sahi tarteeb", `
      <ol><li>Source aur destination dono connect karo (dono par green ✓).</li><li>Sab options select rakho aur <b>Migration shuru karo</b>.</li>
      <li>Khatam hone par destination ke <b>Online Store → Themes</b> me "(migrated)" theme aayega — <b>Preview</b> karo, sab theek ho to <b>Publish</b>.</li>
      <li>Report me "manually dekhne wali cheezein" check karo (jaise reference metafields, metafield rules wali smart collections).</li></ol>
      <div class="callout tip">Theme agar auto-upload na ho (permission / trial store) to tool ZIP <b>Output folder → theme-exports</b> me rakh deta hai: Online Store → Themes → <b>Add theme → Upload zip file</b>.</div>
      <div class="callout warn">Orders, customers, discounts, gift cards, shipping/tax settings, apps aur unka data API se copy nahi hote — yeh destination par khud set karo.</div>`],
    ["Theme Demo → Store: sahi tarteeb", `
      <ol><li>Theme ZIP (jo aap ne kharida) apne store me upload karo aur <b>Publish</b> karo.</li><li>Tool me demo URL + password → <b>Test karo</b>.</li>
      <li>Destination connect → sab select → Run.</li><li>Theme editor kholo — sections ki images, collections aur products khud lag jaate hain (handles aur filenames same hain).</li></ol>
      <div class="callout warn">Demo ke menus storefront se nahi milte — Navigation me khud banao. Videos ke asli filenames bhi demo se nahi milte.</div>`],
    ["WooCommerce → Shopify: keys aur sahi tarteeb", `
      <h4>1. WooCommerce REST API keys banao</h4>
      <ol><li>WordPress admin → <b>WooCommerce → Settings → Advanced → REST API</b>.</li>
      <li><b>Add key</b> → Description: <i>Shopify import</i> → User: apna admin → Permissions: <b>Read</b>.</li>
      <li><b>Generate API key</b> → <b>Consumer key</b> (<code>ck_...</code>) aur <b>Consumer secret</b> (<code>cs_...</code>) copy karo — secret sirf ek dafa dikhta hai.</li></ol>
      <h4>2. Tool me</h4>
      <ol><li>WooCommerce mode → Site URL (<code>https://</code> ke saath) → dono keys → <b>Test karo</b> (products ki ginti aa jayegi).</li>
      <li>Shopify destination connect karo (store aap ka ho to "Apna store", client ka ho to "Client ka store" setup).</li>
      <li>Pehli dafa chaho to <b>Sirf check (report)</b> chalao — kuch nahi banta, sirf missing list.</li>
      <li><b>Import karo</b> → Products, Categories → Collections, SEO redirects → <b>Shuru karo</b>.</li></ol>
      <div class="callout warn">404 aaye to WordPress → <b>Settings → Permalinks → Post name</b> → Save. Orders, customers, coupons aur reviews import nahi hote.</div>
      <div class="callout tip">Redirects Shopify admin → <b>Online Store → Navigation → URL redirects</b> me dikhte hain.</div>`],
    ["Blog Import: sahi tarteeb", `
      <ol><li>Website par woh page kholo jahan saare posts ki list hai (jaise <code>/blog</code>, <code>/news</code>, <code>/category/tips</code>) aur uska URL copy karo.</li>
      <li>Blog Import → URL → <b>Test karo</b>. WordPress ho to tool API se saare posts lega (sab se accurate); warna smart scraping + sitemap.</li>
      <li>Destination connect karo (scopes: <code>write_content, write_files</code>).</li>
      <li>Shopify blog ka naam likho (jaise <b>News</b>) — na ho to ban jayega.</li>
      <li><b>Images apne store par copy karo</b> on rakho — purani site band ho jaye tab bhi images rahengi.</li>
      <li><b>Import shuru karo</b> → Shopify admin → <b>Online Store → Blog posts</b>.</li></ol>
      <div class="callout warn">Login wali (private) sites, aur jo posts sirf JavaScript se aate hain un ka content nahi milta. Comments import nahi hote.</div>`],
    ["Masle aur hal (troubleshooting)", `
      <table class="tbl"><tr><th>Masla</th><th>Hal</th></tr>
      <tr><td>401 — token ghalat / expire</td><td>Token dobara copy karo. Client ID+Secret wale token 24 ghante ke hote hain — dobara Test karo.</td></tr>
      <tr><td>403 / scopes missing (laal chips)</td><td>App ke version me woh scopes add karo → Release → store par app update approve karo.</td></tr>
      <tr><td>shop_not_permitted</td><td>Store aap ki organization me nahi — <b>Client store (OAuth)</b> tareeqa use karo.</td></tr>
      <tr><td>app_not_installed</td><td>Dev Dashboard → app → Install app → is store par install karo.</td></tr>
      <tr><td>"trial store par yeh file type allowed nahi"</td><td>Trial stores par PDF/SVG jaisi files block hoti hain — plan select karne ke baad Files step dobara chalao.</td></tr>
      <tr><td>Demo: password ghalat</td><td>Demo URL me <code>/password</code> na ho; seller ka diya password do.</td></tr>
      <tr><td>WooCommerce 404</td><td>WordPress → Settings → Permalinks → <b>Post name</b> → Save.</td></tr>
      <tr><td>Blog: 0 posts</td><td>Asli listing page do (jaise /blog). JavaScript "Load more" wali sites ke liye sitemap se posts uthaye jaate hain.</td></tr>
      <tr><td>Windows "protected your PC"</td><td><b>More info → Run anyway</b> (exe signed nahi hai is liye).</td></tr>
      <tr><td>Finish par "Theme ... shop_images/x.jpg store me NAHI hai"</td><td>Theme ki settings kisi image ka naam yaad rakhti hai. Tool pehle source store me dhoondta hai: mil jaye to <b>khud copy</b> kar deta hai; source me bhi na ho to woh purana demo reference hai (store par koi asar nahi). Sirf woh notes dekho jo baqi rahein — Theme customizer me us section ki image dobara select kar do.</td></tr>
      <tr><td>"Theme ZIP folder kholo" ya "Output folder" nahi khulta</td><td>Folder yahan hai: <code>Documents\Shopify Theme Data Importer\theme-exports</code> — File Explorer se khud khol lo.</td></tr>
      <tr><td>Window band ho gaya</td><td>Exe dobara kholo — kaam dobara chalao, jo ho chuka hai woh skip hoga.</td></tr></table>`],
  ];
  v.innerHTML = `<div class="card" style="margin-bottom:18px"><div class="card-h mt0" style="margin-bottom:0"><div class="num">★</div><div><h2>Mukammal guide — Roman Urdu</h2><p>Har section kholo. Copy buttons se exact values uthao. Interactive version: <a href="#" data-setup="client">API Access → Setup Guide</a>.</p></div></div></div>` +
    sections.map(([t, b], i) => `<details class="acc" ${i === 0 ? "open" : ""}><summary><span class="n">${i + 1}</span>${t}</summary><div class="acc-b">${b}</div></details>`).join("");
  $$("[data-open]", v).forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); api("/api/open", { url: a.dataset.open }); }));
}

// ------------------------------------------------------------------ run
const STAT_LABELS = { created: "Naye", already: "Pehle se", failed: "Fail", source: "Source", uploaded: "Upload", copied: "Copy", skipped: "Skip",
  variant_images: "Variant img", rehosted: "Copy hui", references: "Links", missing: "Missing", found: "Mile", products: "Products",
  categories: "Categories", files: "Files", products_missing: "Products missing", collections_missing: "Collections missing",
  auto_fixed: "Khud copy hui", old_refs: "Purane demo refs (theek)" };

async function startRun(view, btn) {
  let payload;
  const ensure = async (cid) => {
    const st = CONNECTORS[cid];
    if (st.verified && st.verifiedKey !== JSON.stringify(connPayload(cid))) st.verified = null;   // test ke baad kuch badla
    if (!st.verified) {
      toast("Pehle store connect ho raha hai…");
      const ok = await doConnect(cid);
      if (!ok) { $("#" + cid).scrollIntoView({ behavior: "smooth", block: "center" }); return false; }
    }
    return !!CONNECTORS[cid].verified && !(CONNECTORS[cid].verified.report?.missing || []).length;
  };
  const scopeBlock = (cid) => {
    const r = CONNECTORS[cid].verified?.report;
    if (r && r.missing.length) { toast(`Scopes missing: ${r.missing.join(", ")}`, "err", 6000); $("#" + cid).scrollIntoView({ behavior: "smooth", block: "center" }); return true; }
    return false;
  };
  if (view === "migrate") {
    if (!(await ensure("mg-src")) || !(await ensure("mg-dst"))) { scopeBlock("mg-src") || scopeBlock("mg-dst"); return; }
    const steps = checked($('.view[data-view="migrate"]'), "mg-steps");
    if (!steps.length) return toast("Kam se kam ek cheez select karo", "warn");
    if (normDomain($("#mg-src-domain").value) === normDomain($("#mg-dst-domain").value)) return toast("Source aur destination ek hi store hain!", "err");
    payload = { mode: "migrate", source: connPayload("mg-src"), dest: connPayload("mg-dst"), steps, options: { inventory: $("#mg-inv").checked, metafields: $("#mg-meta").checked } };
    if (!(await confirmBox("Migration shuru karein?", `<b>${esc(payload.source.domain)}</b> → <b>${esc(payload.dest.domain)}</b><br><br>${steps.length} hisse copy honge. Source store me kuch nahi badlega. Destination par jo pehle se hai woh skip hoga.`))) return;
  } else if (view === "demo") {
    if (!$("#dm-url").value.trim()) return setErr($("#dm-url"), "Demo URL likho");
    if (!(await ensure("dm-dst"))) { scopeBlock("dm-dst"); return; }
    const steps = checked($('.view[data-view="demo"]'), "dm-steps");
    if (!steps.length) return toast("Kam se kam ek cheez select karo", "warn");
    payload = { mode: "demo", demo_url: $("#dm-url").value.trim(), password: $("#dm-pass").value, dest: connPayload("dm-dst"), steps, image_scope: $("#dm-scope").value };
    rememberLast("demo", { demo_url: payload.demo_url });
  } else if (view === "woo") {
    for (const [id, m] of [["wc-url", "Site URL likho"], ["wc-ck", "Consumer key likho"], ["wc-cs", "Consumer secret likho"]]) if (!$("#" + id).value.trim()) return setErr($("#" + id), m);
    if (!(await ensure("wc-dst"))) { scopeBlock("wc-dst"); return; }
    const verifyOnly = $("#wc-mode .on").dataset.m === "verify";
    payload = { mode: "woo", wc_url: $("#wc-url").value.trim(), ck: $("#wc-ck").value.trim(), cs: $("#wc-cs").value.trim(), dest: connPayload("wc-dst"),
      verify_only: verifyOnly, steps: checked($('.view[data-view="woo"]'), "wc-steps"), include_drafts: $("#wc-drafts").checked, options: { attributes: $("#wc-attrs").checked } };
    rememberLast("woo", { wc_url: payload.wc_url });
  } else if (view === "blog") {
    if (!$("#bl-url").value.trim()) return setErr($("#bl-url"), "Blog URL likho");
    if (!(await ensure("bl-dst"))) { scopeBlock("bl-dst"); return; }
    payload = { mode: "blog", listing_url: $("#bl-url").value.trim(), blog_title: $("#bl-title").value.trim(), dest: connPayload("bl-dst"),
      rehost_images: $("#bl-rehost").checked, keep_dates: $("#bl-dates").checked, max_posts: parseInt($("#bl-max").value, 10) || 500 };
    rememberLast("blog", { listing_url: payload.listing_url, blog_title: payload.blog_title });
  }
  btn.classList.add("loading"); btn.disabled = true;
  try {
    const r = await api("/api/run", payload);
    openRun(r.id);
  } catch (e) { toast(e.message, "err", 6000); }
  finally { btn.classList.remove("loading"); btn.disabled = false; }
}

function renderRunShell() {
  const v = $('.view[data-view="run"]');
  const C = 2 * Math.PI * 82;
  v.innerHTML = `
    <div class="card">
      <div class="run-head">
        <div class="ring running" id="ring"><svg viewBox="0 0 190 190"><circle class="track" cx="95" cy="95" r="82" fill="none" stroke-width="10"/>
          <circle class="bar" id="ringBar" cx="95" cy="95" r="82" fill="none" stroke-width="10" stroke-dasharray="${C}" stroke-dashoffset="${C}"/></svg>
          <div class="center"><div><div class="pct" id="pct">0<small>%</small></div><div class="lbl">Progress</div></div></div></div>
        <div class="run-title"><span class="state-pill running" id="statePill"><i></i><span>Chal raha hai</span></span><h2 id="runTitle">—</h2><div class="now" id="runNow">Shuru ho raha hai…</div>
          <div class="run-meta"><div>Waqt<b id="mElapsed">0:00</b></div><div>Steps<b id="mSteps">0/0</b></div><div>Warnings<b id="mWarn">0</b></div><div>Fail<b id="mFail">0</b></div></div></div>
        <div class="btn-row" style="flex-direction:column;align-items:stretch">
          <button class="btn danger" id="btnStop">${I.stop} Stop</button>
          <button class="btn ghost" id="btnBack">Form par wapas</button></div>
      </div>
    </div>
    <div class="run-body">
      <div class="card"><div class="card-h"><div><h2>Steps</h2><p>Har hissa aur uska status</p></div></div><ul class="timeline" id="timeline"></ul></div>
      <div>
        <div class="counters" id="counters"></div>
        <div class="console"><div class="console-h"><div class="dots"><i></i><i></i><i></i></div><span class="ct">LIVE LOG</span>
          <div class="flt"><button class="on" data-f="all">Sab</button><button data-f="ok">Success</button><button data-f="warn">Warnings</button><button data-f="debug">Details</button><button data-f="copy">Copy</button></div></div>
          <div class="log hide-debug" id="log"></div></div>
        <div class="card finish" id="finish"></div>
      </div>
    </div>`;
  $("#btnStop").addEventListener("click", async () => {
    if (!CURRENT_JOB || !(await confirmBox("Kaam rokna hai?", "Current item khatam kar ke tool ruk jayega. Jo ho chuka hai woh store me rahega — baad me dobara chalao to wahin se aage.", "Haan, roko", "Nahi, chalne do"))) return;
    api("/api/job/cancel", { id: CURRENT_JOB.id });
  });
  $("#btnBack").addEventListener("click", () => show(LAST_FORM_VIEW || "home"));
  $$(".flt button").forEach((b) => b.addEventListener("click", () => {
    const log = $("#log");
    if (b.dataset.f === "copy") return copy($$("div", log).map((d) => d.textContent).join("\n"));
    if (b.dataset.f === "debug") { log.classList.toggle("hide-debug"); b.classList.toggle("on"); return; }
    $$('.flt button:not([data-f="debug"]):not([data-f="copy"])').forEach((x) => x.classList.toggle("on", x === b));
    log.classList.remove("f-ok", "f-warn");
    if (b.dataset.f !== "all") log.classList.add(`f-${b.dataset.f}`);
  }));
}

function openRun(id) {
  CURRENT_JOB = { id, since: 0, warn: 0 };
  renderRunShell();
  const nav = $('#nav a[data-view="run"]');
  nav.classList.remove("hidden"); nav.classList.add("running");
  setBusy(true);
  show("run");
  pollJob();
}

function setBusy(on) {
  const s = $("#status");
  s.classList.toggle("busy", on);
  $("span", s).textContent = on ? "Kaam chal raha hai" : "Ready";
}

const fmtTime = (s) => { s = Math.round(s); const m = Math.floor(s / 60); return `${m}:${String(s % 60).padStart(2, "0")}`; };

async function pollJob() {
  const job = CURRENT_JOB;
  while (job === CURRENT_JOB) {
    let snap;
    try { snap = await api("/api/job", { id: job.id, since: job.since }); }
    catch (e) { await sleep(2000); continue; }
    job.since = snap.next;
    updateRun(snap);
    if (snap.status !== "running") { finishRun(snap); return; }
    await sleep(700);
  }
}

function updateRun(s) {
  $("#runTitle").textContent = s.title;
  const steps = s.steps.filter((x) => x.status !== "skipped");
  let done = 0, cur = null;
  steps.forEach((x) => { if (["done", "failed", "cancelled"].includes(x.status)) done += 1; if (x.status === "running") cur = x; });
  let frac = done;
  if (cur) frac += cur.total ? Math.min(cur.current / cur.total, 0.98) : 0.3;
  const pct = steps.length ? Math.round((frac / steps.length) * 100) : 0;
  const final = s.status !== "running";
  const shown = final && s.status !== "cancelled" ? 100 : pct;
  $("#pct").innerHTML = `${shown}<small>%</small>`;
  const C = 2 * Math.PI * 82;
  $("#ringBar").style.strokeDashoffset = String(C * (1 - shown / 100));
  document.title = final ? "Theme Data Importer" : `(${shown}%) ${s.title}`;
  $("#mElapsed").textContent = fmtTime(s.elapsed);
  $("#mSteps").textContent = `${done}/${steps.length}`;
  $("#mFail").textContent = s.failed;
  $("#runNow").innerHTML = cur ? `<b>${esc(cur.label)}</b>${cur.total ? ` — ${cur.current}/${cur.total}` : ""}${cur.detail ? ` · ${esc(cur.detail)}` : ""}` : (final ? "" : "Tayari…");
  $("#timeline").innerHTML = s.steps.map((x) => {
    const pctS = x.total ? Math.round((x.current / x.total) * 100) : 0;
    const icon = x.status === "done" ? I.check : (x.status === "failed" || x.status === "cancelled") ? I.x : "";
    const det = x.status === "skipped" ? "Skip (select nahi kiya)" : x.status === "running" ? (x.total ? `${x.current}/${x.total} ${esc(x.detail)}` : esc(x.detail || "chal raha hai…")) : x.status === "done" ? "Mukammal" : x.status === "failed" ? "Masla aaya — report dekho" : x.status === "cancelled" ? "Roka gaya" : "Intezar";
    return `<li class="${x.status}"><span class="dot">${icon}</span><div class="st-name">${esc(x.label)}</div><div class="st-detail">${det}</div><div class="st-bar ${x.total ? "" : "indet"}"><i style="width:${pctS}%"></i></div></li>`;
  }).join("");
  $("#counters").innerHTML = Object.entries(s.stats).map(([sec, f]) => `<div class="counter"><div class="c-t">${esc(sec)}</div><div class="c-v">${Object.entries(f).map(([k, n]) =>
    `<span class="${k.includes("fail") || k.includes("missing") ? (n ? "bad" : "") : k === "created" || k === "uploaded" || k === "copied" ? "good" : ""}"><b>${n}</b>${esc(STAT_LABELS[k] || k)}</span>`).join("")}</div></div>`).join("");
  const log = $("#log");
  const nearBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 80;
  const frag = document.createDocumentFragment();
  s.events.forEach((e) => {
    if (e.level === "warn" || e.level === "error") CURRENT_JOB.warn += 1;
    const d = document.createElement("div");
    d.className = `lv-${e.level}`;
    const ts = new Date(e.t * 1000).toLocaleTimeString([], { hour12: false });
    d.innerHTML = `<span class="ts">${ts}</span><span class="${e.level}">${esc(e.msg)}</span>`;
    frag.appendChild(d);
  });
  log.appendChild(frag);
  while (log.childElementCount > 5000) log.firstElementChild.remove();
  if (nearBottom) log.scrollTop = log.scrollHeight;
  $("#mWarn").textContent = CURRENT_JOB.warn;
}

function finishRun(s) {
  $("#ring").classList.remove("running");
  $("#btnStop").classList.add("hidden");
  const nav = $('#nav a[data-view="run"]');
  nav.classList.remove("running");
  setBusy(false);
  const map = { done: ["done", "Mukammal ✓", "Sab kuch kamyabi se ho gaya."], warning: ["warning", "Mukammal — kuch cheezein dekhni hain", "Kaam ho gaya, neeche list check kar lo."],
    failed: ["failed", "Ruk gaya — masla aaya", "Neeche wajah dekho, theek kar ke dobara chalao (jo ho chuka hai woh skip hoga)."], cancelled: ["cancelled", "Roka gaya", "Aap ke kehne par roka. Dobara chalao to aage se shuru."] };
  const [cls, title, sub] = map[s.status] || map.done;
  const pill = $("#statePill");
  pill.className = `state-pill ${cls}`;
  $("span", pill).textContent = title;
  $("#runNow").textContent = sub;
  const fin = $("#finish");
  fin.innerHTML = `<div class="card-h"><div class="num">${cls === "done" ? "✓" : "!"}</div><div><h2>${title}</h2><p>${sub} Waqt: ${fmtTime(s.elapsed)}</p></div></div>
    <div class="btn-row">${s.links.map((l, i) => `<button class="btn ${i === 0 ? "em" : ""}" data-link="${esc(l.url)}">${I.ext} ${esc(l.label)}</button>`).join("")}
      <button class="btn" id="btnSave">${I.save} Log save karo</button><button class="btn ghost" id="btnAgain">Naya run</button></div>
    ${s.notes.length ? `<div class="notes"><div class="label mt16">Manually dekhne wali cheezein (${s.notes.length})</div><ul>${s.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul></div>` : ""}`;
  fin.classList.add("show");
  $$("[data-link]", fin).forEach((b) => b.addEventListener("click", () => api("/api/open", { url: b.dataset.link }).catch((e) => toast(e.message, "err"))));
  $("#btnSave").addEventListener("click", async () => { try { const r = await api("/api/job/save", { id: s.id }); toast(`Log save: ${r.path}`, "ok", 6000); } catch (e) { toast(e.message, "err"); } });
  $("#btnAgain").addEventListener("click", () => show(LAST_FORM_VIEW || "home"));
  toast(title, cls === "done" ? "ok" : cls === "warning" ? "warn" : "err", 6000);
  document.title = "Theme Data Importer";
}

// ------------------------------------------------------------------ preloader & boot
async function preloader() {
  const pl = $("#preloader");
  const title = $("#plTitle");
  title.innerHTML = [...title.textContent].map((ch, i) => `<span style="animation-delay:${0.45 + i * 0.035}s">${ch === " " ? "&nbsp;" : esc(ch)}</span>`).join("");
  requestAnimationFrame(() => pl.classList.add("go"));
  const bar = $("#plBar"), meta = $("#plMeta");
  const msgs = ["INITIALIZING", "LOADING ENGINE", "SECURING LOCAL SESSION", "PREPARING WORKSPACE"];
  let p = 0, i = 0;
  const t0 = Date.now();
  const timer = setInterval(() => { p = Math.min(p + Math.random() * 9, 88); bar.style.width = p + "%"; if (Date.now() - t0 > 650 * (i + 1) && i < msgs.length - 1) meta.textContent = msgs[++i]; }, 120);
  let info = null;
  for (let k = 0; k < 20 && !info; k++) {
    try { info = await api("/api/info"); } catch (e) { await sleep(400); }
  }
  const rest = 2900 - (Date.now() - t0);
  if (rest > 0) await sleep(rest);
  clearInterval(timer);
  bar.style.width = "100%";
  meta.textContent = info ? "READY" : "OFFLINE";
  await sleep(380);
  pl.classList.add("reveal");
  $("#app").classList.remove("boot");
  setTimeout(() => $("#app").classList.add("ready"), 250);
  setTimeout(() => { const a = $("#announce"); a.classList.remove("boot"); a.classList.add("ready"); }, 450);
  setTimeout(() => pl.classList.add("done"), 1250);
  return info;
}

function heartbeat() {
  const ping = () => api("/api/ping").catch(() => {});
  ping();
  setInterval(ping, 5000);
  window.addEventListener("pagehide", () => { try { navigator.sendBeacon("/api/bye", "{}"); } catch (e) { /* ignore */ } });
}

document.addEventListener("click", (e) => {
  const c = e.target.closest("[data-copytext]");
  if (c) { e.preventDefault(); copy(c.dataset.copytext); return; }
  const s = e.target.closest("[data-setup]");
  if (s) { e.preventDefault(); openSetup(s.dataset.setup); return; }
  const o = e.target.closest(".setup-body [data-open]");
  if (o) { e.preventDefault(); api("/api/open", { url: o.dataset.open }).catch(() => {}); }
});

async function boot() {
  renderNav();
  INFO = await preloader();
  if (!INFO) {
    INFO = { version: "3", redirect_uri: "http://localhost:8765/oauth/callback", scopes: {}, recommended: [], source_recommended: [], settings: {} };
    sessionExpired();
  }
  SETTINGS = INFO.settings || {};
  $("#ver").textContent = `v${INFO.version} · API ${INFO.api_version || ""}`;
  $("#author").textContent = INFO.author || "Haider Ali";
  renderHome(); renderMigrate(); renderDemo(); renderWoo(); renderBlog(); renderToken(); renderGuide(); renderRunShell();
  $$("[data-run]").forEach((b) => b.addEventListener("click", () => startRun(b.dataset.run, b)));
  $("#openOutput").addEventListener("click", () => api("/api/open", { url: "output" }).catch((e) => toast(e.message, "err")));
  fillDomainList();
  const route = location.hash.replace("#", "");
  show(TITLES[route] ? route : "home");
  heartbeat();
}

document.addEventListener("DOMContentLoaded", boot);
})();
