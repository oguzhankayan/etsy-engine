"""Etsy Open API v3 client — OAuth2 (PKCE) + request wrapper + token storage.

Etsy v3 requires OAuth2 for shop write operations. Flow:
  1. etsy-auth: build the consent URL, run a localhost server to catch the
     redirect, exchange the code for access + refresh tokens (stored on disk).
  2. Subsequent calls auto-refresh the access token when it expires.

Token file: data/etsy_tokens.json (gitignored). Headers on every API call:
  Authorization: Bearer <access_token>
  x-api-key: <keystring>
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from urllib.parse import urlencode

import requests

from ..config import DATA_DIR, settings

API_BASE = "https://openapi.etsy.com/v3/application"
TOKEN_URL = "https://api.etsy.com/v3/public/oauth/token"
CONNECT_URL = "https://www.etsy.com/oauth/connect"
PING_URL = f"{API_BASE}/openapi-ping"
TOKEN_FILE = DATA_DIR / "etsy_tokens.json"


class EtsyError(RuntimeError):
    pass


# Etsy limits: 10 req/sec, 10k/day. validate/velocity runs fire hundreds of
# calls; one 429 or transient 5xx used to kill the whole run. Bounded backoff:
# 3 tries max (2s, 8s waits), honoring Retry-After when Etsy sends it.
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_TRIES = 3


def _send_with_retry(send, label: str):
    """Call `send()` (a zero-arg closure returning a requests.Response); retry
    RETRY_STATUSES with backoff. Returns the final Response (ok or not)."""
    resp = None
    for attempt in range(MAX_TRIES):
        resp = send()
        if resp.status_code not in RETRY_STATUSES:
            return resp
        if attempt < MAX_TRIES - 1:
            try:
                wait = float(resp.headers.get("Retry-After", "") or 0)
            except ValueError:
                wait = 0.0
            wait = min(max(wait, 2.0 * 4 ** attempt), 60.0)
            print(f"[etsy] {label} -> {resp.status_code}, retrying in {wait:.0f}s "
                  f"({attempt + 1}/{MAX_TRIES - 1})")
            time.sleep(wait)
    return resp


# --- PKCE helpers ---

def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def build_auth_url() -> tuple[str, str, str]:
    """Return (auth_url, state, code_verifier)."""
    settings.require("etsy_api_key")
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)
    params = {
        "response_type": "code",
        "client_id": settings.etsy_api_key,
        "redirect_uri": settings.etsy_redirect_uri,
        "scope": settings.etsy_scopes,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{CONNECT_URL}?{urlencode(params)}", state, verifier


def exchange_code(code: str, code_verifier: str) -> dict:
    resp = requests.post(TOKEN_URL, data={
        "grant_type": "authorization_code",
        "client_id": settings.etsy_api_key,
        "redirect_uri": settings.etsy_redirect_uri,
        "code": code,
        "code_verifier": code_verifier,
    }, timeout=30)
    if not resp.ok:
        raise EtsyError(f"token exchange {resp.status_code}: {resp.text[:300]}")
    tok = resp.json()
    _save_tokens(tok)
    return tok


def _save_tokens(tok: dict) -> None:
    tok["obtained_at"] = int(time.time())
    TOKEN_FILE.write_text(json.dumps(tok, indent=2))


def _load_tokens() -> dict:
    if not TOKEN_FILE.exists():
        raise EtsyError("Not authenticated. Run: etsy-engine etsy-auth")
    return json.loads(TOKEN_FILE.read_text())


def _refresh(tok: dict) -> dict:
    resp = requests.post(TOKEN_URL, data={
        "grant_type": "refresh_token",
        "client_id": settings.etsy_api_key,
        "refresh_token": tok["refresh_token"],
    }, timeout=30)
    if not resp.ok:
        raise EtsyError(f"token refresh {resp.status_code}: {resp.text[:300]}")
    new = resp.json()
    # Etsy returns a new refresh_token too; keep it.
    _save_tokens(new)
    return new


def _access_token() -> str:
    tok = _load_tokens()
    age = int(time.time()) - tok.get("obtained_at", 0)
    if age >= tok.get("expires_in", 3600) - 120:  # refresh 2 min early
        tok = _refresh(tok)
    return tok["access_token"]


# --- API wrapper ---

def _api_key_header() -> str:
    """Since 2026-02-09 Etsy requires x-api-key as 'keystring:shared_secret'."""
    settings.require("etsy_api_key", "etsy_shared_secret")
    return f"{settings.etsy_api_key}:{settings.etsy_shared_secret}"


def _headers(extra: dict | None = None) -> dict:
    h = {"Authorization": f"Bearer {_access_token()}", "x-api-key": _api_key_header()}
    if extra:
        h.update(extra)
    return h


def request(method: str, path: str, **kwargs) -> dict:
    """Authenticated JSON request. `path` is relative to API_BASE."""
    url = path if path.startswith("http") else f"{API_BASE}{path}"
    json_body = kwargs.pop("json", None)
    headers = _headers({"Content-Type": "application/json"} if json_body is not None else None)
    headers.update(kwargs.pop("headers", {}))
    resp = _send_with_retry(
        lambda: requests.request(method, url, headers=headers, json=json_body,
                                 timeout=60, **kwargs),
        f"{method} {path}")
    if not resp.ok:
        raise EtsyError(f"{method} {path} -> {resp.status_code}: {resp.text[:400]}")
    return resp.json() if resp.content else {}


def upload(path: str, files: dict, data: dict | None = None) -> dict:
    """Multipart upload (images/files) — no Content-Type header (requests sets it).
    NOTE: no retry here — the file handles in `files` are consumed by a send, so
    a retry would upload empty bodies. Callers own upload retries."""
    url = f"{API_BASE}{path}"
    resp = requests.post(url, headers=_headers(), files=files, data=data or {}, timeout=120)
    if not resp.ok:
        raise EtsyError(f"upload {path} -> {resp.status_code}: {resp.text[:400]}")
    return resp.json() if resp.content else {}


def app_request(method: str, path: str, **kwargs) -> dict:
    """App-only request (x-api-key only, no OAuth Bearer). For public endpoints
    like listing search — used by market validation without needing user auth."""
    url = path if path.startswith("http") else f"{API_BASE}{path}"
    headers = {"x-api-key": _api_key_header()}
    headers.update(kwargs.pop("headers", {}))
    resp = _send_with_retry(
        lambda: requests.request(method, url, headers=headers, timeout=30, **kwargs),
        f"{method} {path}")
    if not resp.ok:
        raise EtsyError(f"{method} {path} -> {resp.status_code}: {resp.text[:300]}")
    return resp.json() if resp.content else {}


def me() -> dict:
    """Current authed user — also resolves shop_id if not set."""
    return request("GET", "/users/me")


# --- Interactive OAuth (localhost callback) ---

def authorize(open_browser: bool = True) -> dict:
    """Run the full consent flow via a one-shot localhost server. Returns tokens."""
    import http.server
    import urllib.parse
    import webbrowser
    from urllib.parse import urlparse

    auth_url, state, verifier = build_auth_url()
    parsed = urlparse(settings.etsy_redirect_uri)
    host, port = parsed.hostname or "localhost", parsed.port or 80

    captured: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            qs = urllib.parse.parse_qs(urlparse(self.path).query)
            captured["code"] = (qs.get("code") or [None])[0]
            captured["state"] = (qs.get("state") or [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            ok = bool(captured["code"])
            self.wfile.write(
                b"<h2>Etsy auth complete. You can close this tab.</h2>"
                if ok else b"<h2>Auth failed - no code returned.</h2>"
            )

        def log_message(self, *args):  # silence
            pass

    print(f"Open this URL to authorize (also trying your browser):\n{auth_url}\n")
    if open_browser:
        try:
            webbrowser.open(auth_url)
        except Exception:
            pass

    server = http.server.HTTPServer((host, port), Handler)
    server.handle_request()  # blocks until the redirect hits
    server.server_close()

    if not captured.get("code"):
        raise EtsyError("No authorization code received.")
    if captured.get("state") != state:
        raise EtsyError("State mismatch — possible CSRF, aborting.")
    return exchange_code(captured["code"], verifier)
