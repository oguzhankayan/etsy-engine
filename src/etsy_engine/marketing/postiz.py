"""Postiz client — Pinterest distribution (Faz 4.5).

Contract reverse-engineered from a working Postiz integration:
  Auth:    header `authorization: <POSTIZ_API_KEY>`  (raw key, NOT Bearer)
  Base:    https://api.postiz.com
  Upload:  POST /public/v1/upload   (multipart form field `file`) -> {id, path}
  List:    GET  /public/v1/integrations -> [{id, name, platform, disabled}]
  Create:  POST /public/v1/posts   (JSON, see schedule_image_pin) -> [{id|postId}]

We publish a static image pin (our product mockup) linking back to the Etsy
listing. Posts are SCHEDULED (type=schedule) so a human cadence stays intact.
"""
from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path

import requests

from ..config import settings


class PostizError(RuntimeError):
    pass


class PostizClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key or settings.postiz_api_key
        self.base = (base_url or settings.postiz_base_url).rstrip("/")

    def _auth(self) -> dict:
        settings.require("postiz_api_key")
        return {"authorization": self.api_key}

    def list_integrations(self) -> list[dict]:
        """Connected social accounts (read-only). Use to find Pinterest board ids."""
        r = requests.get(
            f"{self.base}/public/v1/integrations", headers=self._auth(), timeout=30
        )
        if not r.ok:
            raise PostizError(f"integrations {r.status_code}: {r.text[:200]}")
        return r.json()

    def upload(self, file_path: str) -> dict:
        """Upload a media file. Returns {id, path}."""
        p = Path(file_path)
        mime = mimetypes.guess_type(p.name)[0] or "image/jpeg"
        with p.open("rb") as fh:
            r = requests.post(
                f"{self.base}/public/v1/upload", headers=self._auth(),
                files={"file": (p.name, fh, mime)}, timeout=120,
            )
        if not r.ok:
            raise PostizError(f"upload {r.status_code}: {r.text[:200]}")
        data = r.json()
        path_out = data.get("path") or data.get("url")
        if not path_out:
            raise PostizError("upload returned no path")
        return {"id": str(data.get("id") or uuid.uuid4()), "path": str(path_out)}

    def schedule_image_pin(
        self, *, image_path: str, title: str, description: str, link: str,
        board: str, publish_at: str, integration_id: str | None = None,
        alt_text: str = "",
    ) -> dict:
        """Schedule a static-image Pinterest pin linking to the Etsy listing.

        publish_at: ISO-8601 datetime. board: Pinterest board name/id in Postiz.
        Returns {payload, response, post_id}.
        """
        integration_id = integration_id or settings.pinterest_postiz_integration_id
        if not integration_id:
            raise PostizError("no Pinterest integration id (set PINTEREST_POSTIZ_INTEGRATION_ID)")
        media = self.upload(image_path)
        payload = {
            "type": "schedule",
            "date": publish_at,
            "shortLink": False,
            "tags": [],
            "posts": [{
                "integration": {"id": integration_id},
                "value": [{
                    "id": str(uuid.uuid4()),
                    "content": description,
                    "image": [{"id": media["id"], "path": media["path"],
                               "alt": alt_text or title}],
                }],
                "group": str(uuid.uuid4()),
                "settings": {"title": title[:100], "link": link, "board": board},
            }],
        }
        r = requests.post(
            f"{self.base}/public/v1/posts",
            headers={**self._auth(), "content-type": "application/json"},
            json=payload, timeout=60,
        )
        resp: object = r.text
        try:
            resp = r.json()
        except ValueError:
            pass
        if not r.ok:
            raise PostizError(f"posts {r.status_code}: {str(resp)[:300]}")
        post_id = None
        if isinstance(resp, list) and resp:
            post_id = resp[0].get("id") or resp[0].get("postId")
        elif isinstance(resp, dict):
            post_id = resp.get("id") or resp.get("postId") or resp.get("_id")
        return {"payload": payload, "response": resp, "post_id": post_id}
