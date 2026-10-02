"""Direct Pinterest API v5 client — replaces Postiz (subscription ended).

Follows the owner's decision 0003 in the growth-factory project: Pipedream was
abandoned there over surprise pricing; direct API + a local time-spread queue
is $0 and vendor-lock-free. This is that pattern in Python:

  1. `etsy-engine pinterest-auth`  — one-time OAuth (browser + localhost
     callback), tokens in data/pinterest_tokens.json, auto-refreshed.
  2. `etsy-engine pin-queue --product-id N` — queue the product's mockups as
     pins linking to its Etsy listing, spaced out over hours/days
     (data/pinterest_queue.jsonl).
  3. `etsy-engine pin-spread` — publish every DUE pin (run from the daily
     launchd job; a human-looking cadence with zero cloud dependency).

Needs a Pinterest Developer app (https://developers.pinterest.com/apps/):
set PINTEREST_APP_ID + PINTEREST_APP_SECRET in .env. Images go up as base64
(no external hosting dependency). Limits: title<=100, description<=800.
"""
from __future__ import annotations

import base64
import json
import secrets
import time
from datetime import datetime, timedelta, UTC
from pathlib import Path
from urllib.parse import urlencode

import requests

from ..config import DATA_DIR, settings

AUTH_URL = "https://www.pinterest.com/oauth/"


def _api_base() -> str:
    return settings.pinterest_api_base.rstrip("/")
TOKEN_URL = "https://api.pinterest.com/v5/oauth/token"
SCOPES = "boards:read,boards:write,pins:read,pins:write,user_accounts:read"
TOKEN_FILE = DATA_DIR / "pinterest_tokens.json"
QUEUE_FILE = DATA_DIR / "pinterest_queue.jsonl"


class PinterestError(RuntimeError):
    pass


# --- OAuth ---

def _basic_auth() -> str:
    settings.require("pinterest_app_id", "pinterest_app_secret")
    raw = f"{settings.pinterest_app_id}:{settings.pinterest_app_secret}"
    return "Basic " + base64.b64encode(raw.encode()).decode()


def _save_tokens(tok: dict) -> None:
    tok["obtained_at"] = int(time.time())
    TOKEN_FILE.write_text(json.dumps(tok, indent=2))


def _load_tokens() -> dict:
    if not TOKEN_FILE.exists():
        raise PinterestError("Not authenticated. Run: etsy-engine pinterest-auth")
    return json.loads(TOKEN_FILE.read_text())


def _refresh(tok: dict) -> dict:
    resp = requests.post(TOKEN_URL, headers={"Authorization": _basic_auth()},
                         data={"grant_type": "refresh_token",
                               "refresh_token": tok["refresh_token"]},
                         timeout=30)
    if not resp.ok:
        raise PinterestError(f"token refresh {resp.status_code}: {resp.text[:300]}")
    new = resp.json()
    # Pinterest keeps the refresh token unless rotation is enabled; preserve it.
    new.setdefault("refresh_token", tok["refresh_token"])
    _save_tokens(new)
    return new


def _access_token() -> str:
    tok = _load_tokens()
    # A manually-issued token (developer-portal "pina_" token pasted into the
    # token file) has no refresh_token: use it as-is until Pinterest rejects it.
    if not tok.get("refresh_token"):
        return tok["access_token"]
    age = int(time.time()) - tok.get("obtained_at", 0)
    if age >= int(tok.get("expires_in", 3600)) - 300:  # refresh 5 min early
        tok = _refresh(tok)
    return tok["access_token"]


def authorize(open_browser: bool = True) -> dict:
    """One-time OAuth consent via localhost callback. Returns tokens."""
    import http.server
    import urllib.parse
    import webbrowser
    from urllib.parse import urlparse

    settings.require("pinterest_app_id", "pinterest_app_secret")
    state = secrets.token_urlsafe(16)
    parsed = urlparse(settings.pinterest_redirect_uri)
    host, port = parsed.hostname or "localhost", parsed.port or 80
    url = AUTH_URL + "?" + urlencode({
        "response_type": "code",
        "client_id": settings.pinterest_app_id,
        "redirect_uri": settings.pinterest_redirect_uri,
        "scope": SCOPES,
        "state": state,
    })

    captured: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            qs = urllib.parse.parse_qs(urlparse(self.path).query)
            captured["code"] = (qs.get("code") or [None])[0]
            captured["state"] = (qs.get("state") or [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h2>Pinterest auth complete. Close this tab.</h2>"
                             if captured["code"] else b"<h2>Auth failed.</h2>")

        def log_message(self, *args):
            pass

    print(f"Open to authorize Pinterest:\n{url}\n")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    server = http.server.HTTPServer((host, port), Handler)
    server.handle_request()
    server.server_close()

    if not captured.get("code"):
        raise PinterestError("No authorization code received.")
    if captured.get("state") != state:
        raise PinterestError("State mismatch — possible CSRF, aborting.")
    resp = requests.post(TOKEN_URL, headers={"Authorization": _basic_auth()},
                         data={"grant_type": "authorization_code",
                               "code": captured["code"],
                               "redirect_uri": settings.pinterest_redirect_uri},
                         timeout=30)
    if not resp.ok:
        raise PinterestError(f"token exchange {resp.status_code}: {resp.text[:300]}")
    tok = resp.json()
    _save_tokens(tok)
    return tok


# --- API ---

def _request(method: str, path: str, **kwargs) -> dict:
    headers = {"Authorization": f"Bearer {_access_token()}"}
    headers.update(kwargs.pop("headers", {}))
    resp = requests.request(method, f"{_api_base()}{path}", headers=headers,
                            timeout=60, **kwargs)
    if not resp.ok:
        raise PinterestError(f"{method} {path} -> {resp.status_code}: {resp.text[:300]}")
    return resp.json() if resp.content else {}


def list_boards() -> list[dict]:
    return _request("GET", "/boards?page_size=100").get("items", [])


def create_pin(*, board_id: str, title: str, description: str, link: str,
               image_path: str, alt_text: str = "") -> dict:
    """Publish one image pin NOW. Image goes up base64 (no hosting needed)."""
    data = base64.b64encode(Path(image_path).read_bytes()).decode()
    body = {
        "board_id": board_id,
        "title": title[:100],
        "description": description[:800],
        "link": link,
        "alt_text": (alt_text or title)[:500],
        "media_source": {"source_type": "image_base64",
                         "content_type": "image/jpeg", "data": data},
    }
    return _request("POST", "/pins", json=body)


# --- Local time-spread queue (replaces Postiz scheduling) ---

def queue_pin(*, due_iso: str, board_id: str, title: str, description: str,
              link: str, image_path: str, alt_text: str = "",
              product_id: int | None = None) -> None:
    row = {"due": due_iso, "board_id": board_id, "title": title,
           "description": description, "link": link, "image_path": image_path,
           "alt_text": alt_text, "product_id": product_id,
           "queued_at": datetime.now(UTC).isoformat()}
    with QUEUE_FILE.open("a") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _read_queue() -> list[dict]:
    if not QUEUE_FILE.exists():
        return []
    rows = []
    for line in QUEUE_FILE.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    return rows


def _write_queue(rows: list[dict]) -> None:
    QUEUE_FILE.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def queue_product(product_id: int, board_id: str, start: datetime | None = None,
                  spacing_hours: float = 6.0) -> int:
    """Queue a product's mockups as pins linking to its live Etsy listing,
    spaced `spacing_hours` apart starting at `start` (default: +1h from now)."""
    from .. import db

    el = db.get_etsy_listing(product_id)
    if not el:
        raise PinterestError(f"product {product_id} has no Etsy listing")
    listing = db.get_listing(product_id) or {}
    title = (listing.get("title") or "")[:100]
    desc = (listing.get("description") or "").split("\n")[0][:800]
    when = start or datetime.now(UTC) + timedelta(hours=1)
    n = 0
    for m in db.mockups_for_product(product_id):
        if not Path(m["file_path"]).exists():
            continue
        queue_pin(due_iso=when.isoformat(), board_id=board_id, title=title,
                  description=desc, link=el["url"], image_path=m["file_path"],
                  alt_text=f"{title} — {m['kind']}", product_id=product_id)
        when += timedelta(hours=spacing_hours)
        n += 1
    print(f"[pinterest] queued {n} pins for product {product_id} "
          f"(every {spacing_hours}h)")
    return n


def publish_due(limit: int = 10) -> int:
    """Publish every queued pin whose due time has passed (bounded per run to
    keep a human cadence even if the queue backed up). Failed pins stay queued."""
    now = datetime.now(UTC)
    rows = _read_queue()
    keep, published = [], 0
    for r in rows:
        try:
            due = datetime.fromisoformat(r["due"])
        except (ValueError, KeyError):
            continue  # drop malformed rows
        if due > now or published >= limit:
            keep.append(r)
            continue
        try:
            pin = create_pin(board_id=r["board_id"], title=r["title"],
                             description=r["description"], link=r["link"],
                             image_path=r["image_path"],
                             alt_text=r.get("alt_text", ""))
            published += 1
            print(f"[pinterest] published pin {pin.get('id')} -> {r['link']}")
        except Exception as e:
            print(f"[pinterest] pin failed (stays queued): {e}")
            keep.append(r)
    _write_queue(keep)
    print(f"[pinterest] published {published}, {len(keep)} still queued")
    return published
