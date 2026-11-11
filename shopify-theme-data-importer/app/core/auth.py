"""Admin API access: access token, client credentials, OAuth (custom distribution)."""
import hashlib
import hmac
import secrets
import time
from urllib.parse import urlencode

from .shopify import Store, normalize_domain, safe_json, short_err

# Har kaam ke liye kaunse scopes chahiye: (zaroori, optional)
SCOPES = {
    "migrate_source": (["read_products", "read_files", "read_content"],
                       ["read_online_store_navigation", "read_themes", "read_inventory"]),
    "migrate_dest": (["write_products", "write_files", "write_content"],
                     ["write_inventory", "read_locations", "write_online_store_navigation", "write_themes"]),
    "demo_dest": (["write_products", "write_files", "write_content"], ["read_themes"]),
    "woo_dest": (["write_products"], ["write_inventory", "read_locations", "write_online_store_navigation"]),
    "blog_dest": (["write_content"], ["write_files"]),
}

ALL_RECOMMENDED = ["write_products", "write_inventory", "read_locations", "write_files", "write_content",
                   "write_online_store_navigation", "write_themes"]
SOURCE_RECOMMENDED = ["read_products", "read_inventory", "read_files", "read_content",
                      "read_online_store_navigation", "read_themes"]


class AuthError(Exception):
    pass


def _implied(granted):
    have = set(granted or [])
    for s in list(have):
        if s.startswith("write_"):
            have.add("read_" + s[6:])
        if s.startswith("unauthenticated_"):
            continue
    return have


def scope_report(granted, role):
    req, opt = SCOPES.get(role, ([], []))
    if granted is None:
        return {"known": False, "missing": [], "missing_optional": []}
    have = _implied(granted)
    return {"known": True, "missing": [s for s in req if s not in have],
            "missing_optional": [s for s in opt if s not in have]}


def verify(session, domain, token, role=None, refresh=None):
    """Token test: shop info + scopes."""
    store = Store(session, domain, token, refresh=refresh)
    r = store.get("shop.json")
    if r is None:
        raise AuthError("Store tak connection nahi hua -- domain aur internet check karo.")
    if r.status_code == 401:
        raise AuthError("Token ghalat hai ya expire ho chuka hai (401).")
    if r.status_code == 403:
        raise AuthError("Token theek hai lekin is kaam ki permission (scope) nahi hai (403).")
    if r.status_code == 404:
        raise AuthError("Store nahi mila -- myshopify.com domain check karo (404).")
    if r.status_code != 200:
        raise AuthError(short_err(r))
    shop = safe_json(r).get("shop", {})
    granted = store.granted_scopes()
    return {
        "shop": {"name": shop.get("name"), "domain": shop.get("domain"),
                 "myshopify_domain": shop.get("myshopify_domain") or store.domain,
                 "plan": shop.get("plan_display_name") or shop.get("plan_name"),
                 "email": shop.get("email"), "currency": shop.get("currency")},
        "scopes": granted,
        "token": store.token,
        "report": scope_report(granted, role) if role else None,
    }


CC_ERRORS = {
    "invalid_client": "Client ID ya Client Secret ghalat hai.",
    "app_not_installed": "App is store par install nahi hai -- Dev Dashboard me app ko is store par install karo.",
    "shop_not_permitted": "Yeh store app ki organization me nahi hai. Client ke store ke liye 'OAuth' tareeqa use karo.",
    "invalid_request": "Request ghalat -- Client ID / Secret dobara copy karo.",
}


def client_credentials(session, domain, client_id, client_secret):
    """Dev Dashboard app + store SAME organization me hon to token (24 ghante) deta hai."""
    domain = normalize_domain(domain)
    if not client_id or not client_secret:
        raise AuthError("Client ID aur Client Secret dono chahiye.")
    try:
        r = session.post(f"https://{domain}/admin/oauth/access_token",
                         data={"grant_type": "client_credentials", "client_id": client_id.strip(),
                               "client_secret": client_secret.strip()},
                         headers={"Accept": "application/json"}, timeout=30)
    except Exception as e:  # noqa: BLE001
        raise AuthError(f"Connection nahi hua: {e}") from e
    data = safe_json(r)
    if r.status_code == 200 and data.get("access_token"):
        return {"token": data["access_token"], "scope": data.get("scope", ""),
                "expires_in": data.get("expires_in"), "obtained": time.time()}
    code = str(data.get("error") or "")
    desc = str(data.get("error_description") or "")
    msg = CC_ERRORS.get(code) or desc or short_err(r)
    if r.status_code in (400, 401, 403) and not CC_ERRORS.get(code):
        msg += (" -- Agar yeh client ka store hai (aap ki organization me nahi) to client credentials "
                "kaam nahi karta. 'OAuth (client store)' tareeqa use karo.")
    raise AuthError(msg)


def make_refresher(session, domain, client_id, client_secret):
    def refresh():
        try:
            return client_credentials(session, domain, client_id, client_secret)["token"]
        except AuthError:
            return None
    return refresh


# ----------------------------------------------------------------- OAuth
def authorize_url(domain, client_id, scopes, redirect_uri, state):
    domain = normalize_domain(domain)
    return f"https://{domain}/admin/oauth/authorize?" + urlencode({
        "client_id": client_id.strip(), "scope": ",".join(scopes) if isinstance(scopes, (list, tuple)) else scopes,
        "redirect_uri": redirect_uri, "state": state})


def valid_hmac(params, secret):
    given = params.get("hmac", "")
    message = "&".join(f"{k}={v}" for k, v in sorted(params.items()) if k not in ("hmac", "signature"))
    digest = hmac.new(secret.strip().encode(), message.encode(), hashlib.sha256).hexdigest()
    return bool(given) and hmac.compare_digest(digest, given)


def exchange_code(session, domain, client_id, client_secret, code):
    domain = normalize_domain(domain)
    r = session.post(f"https://{domain}/admin/oauth/access_token",
                     json={"client_id": client_id.strip(), "client_secret": client_secret.strip(), "code": code},
                     headers={"Accept": "application/json"}, timeout=30)
    data = safe_json(r)
    if r.status_code != 200 or not data.get("access_token"):
        raise AuthError(f"Token exchange fail: {data.get('error_description') or short_err(r)}")
    return {"token": data["access_token"], "scope": data.get("scope", "")}


class OAuthFlows:
    """Pending OAuth flows (state -> details)."""

    def __init__(self):
        self.flows = {}

    def start(self, domain, client_id, client_secret, scopes, redirect_uri):
        if not client_id or not client_secret:
            raise AuthError("Client ID aur Client Secret dono chahiye.")
        state = secrets.token_urlsafe(18)
        domain = normalize_domain(domain)
        self.flows[state] = {"domain": domain, "client_id": client_id.strip(),
                             "client_secret": client_secret.strip(), "redirect_uri": redirect_uri,
                             "status": "waiting", "created": time.time(), "result": None, "error": None}
        return state, authorize_url(domain, client_id, scopes, redirect_uri, state)

    def complete(self, session, params):
        state = params.get("state", "")
        flow = self.flows.get(state)
        if not flow:
            raise AuthError("Yeh authorization request purani hai ya match nahi hui -- tool me dobara 'Authorize' dabao.")
        try:
            if normalize_domain(params.get("shop", "")) != flow["domain"]:
                raise AuthError(f"Shop match nahi hua: {params.get('shop')}")
            if not valid_hmac(params, flow["client_secret"]):
                raise AuthError("HMAC verify nahi hua -- Client Secret check karo.")
            if not params.get("code"):
                raise AuthError("Shopify ne code nahi bheja (approve nahi hua?).")
            flow["result"] = exchange_code(session, flow["domain"], flow["client_id"],
                                           flow["client_secret"], params["code"])
            flow["status"] = "done"
            return flow
        except AuthError as e:
            flow["status"], flow["error"] = "error", str(e)
            raise

    def status(self, state):
        f = self.flows.get(state)
        if not f:
            return {"status": "unknown"}
        out = {"status": f["status"], "error": f["error"]}
        if f["result"]:
            out.update(f["result"])
        return out
