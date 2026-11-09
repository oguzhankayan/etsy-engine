"""Connect with Raywake: sign in from the terminal instead of copying an API key.

`etsy-engine login` asks Raywake for an eight-letter code (OAuth 2.0 device authorization, RFC 8628),
opens your browser on raywake.si/connect with that code, and waits. You sign in, check that the code
on the page matches the one in your terminal, and approve. etsy-engine then receives an API key limited
to generating and reading your own jobs, and keeps it in ~/.config/etsy-engine/raywake.json (only you can
read it). You can disconnect at any time from API keys on raywake.si, or with `etsy-engine logout`.

RAYWAKE_API_KEY in .env still works and wins when both are present.

The module only needs `requests`; another app can reuse it by changing CLIENT_ID and the config folder.
"""
from __future__ import annotations

import json
import os
import time
import webbrowser
from datetime import datetime, UTC
from pathlib import Path
from collections.abc import Callable

import requests

CLIENT_ID = "etsy-engine"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "etsy-engine"
CREDENTIALS = CONFIG_DIR / "raywake.json"


class ConnectError(RuntimeError):
    pass


def stored_key(path: Path | None = None) -> str:
    """The key saved by `etsy-engine login`, or "" when there is none."""
    try:
        return str(json.loads((path or CREDENTIALS).read_text()).get("api_key") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def save_key(key: str, path: Path | None = None) -> Path:
    path = path or CREDENTIALS
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    # Created owner-only before the key is written, then moved into place.
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump({"api_key": key, "connected_at": datetime.now(UTC).isoformat()}, handle)
    os.replace(temporary, path)
    os.chmod(path, 0o600)
    return path


def forget_key(path: Path | None = None) -> bool:
    try:
        (path or CREDENTIALS).unlink()
        return True
    except FileNotFoundError:
        return False


def _post(base: str, path: str, data: dict, timeout: int = 30) -> tuple[int, dict]:
    try:
        response = requests.post(f"{base}{path}", data=data, timeout=timeout,
                                 headers={"Accept": "application/json", "User-Agent": f"{CLIENT_ID} (+https://raywake.si)"})
    except requests.RequestException as exc:
        raise ConnectError(f"Raywake could not be reached: {str(exc)[:160]}") from exc
    try:
        body = response.json()
    except ValueError:
        body = {}
    return response.status_code, body if isinstance(body, dict) else {}


def login(base: str, *, say: Callable[[str], None] = print, open_browser: bool = True,
          sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
          path: Path | None = None) -> Path:
    """Run the device flow and save the key. Raises ConnectError when declined or expired."""
    base = base.rstrip("/")
    status, start = _post(base, "/v1/oauth/device", {"client_id": CLIENT_ID})
    if status != 200 or not start.get("device_code"):
        raise ConnectError(start.get("error_description") or start.get("error") or f"Raywake answered {status}.")
    code, url = start["user_code"], start.get("verification_uri_complete") or start["verification_uri"]
    say(f"Your code: {code}")
    say(f"Approve it at {url}  (check that the page shows the same code)")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass  # the address above still works on any device
    interval = max(1, int(start.get("interval") or 5))
    deadline = clock() + int(start.get("expires_in") or 600)
    while clock() < deadline:
        sleep(interval)
        status, token = _post(base, "/v1/oauth/token", {"grant_type": DEVICE_GRANT, "device_code": start["device_code"],
                                                        "client_id": CLIENT_ID})
        if status == 200 and token.get("access_token"):
            saved = save_key(token["access_token"], path)
            say(f"Connected. Your key is saved in {saved} (only you can read it).")
            return saved
        error = token.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        if error == "access_denied":
            raise ConnectError("The connection was declined in the browser.")
        if error == "expired_token":
            break
        raise ConnectError(token.get("error_description") or error or f"Raywake answered {status}.")
    raise ConnectError("The code expired before it was approved. Run `etsy-engine login` again.")
