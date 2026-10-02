"""Reference-image handling for Raywake.

Two needs, two functions:

- `upload(path)` -> a reference the image model can read (mockups pass the REAL
  product pages so each scene shows the exact artwork — Etsy honesty / anti-ban).
  If the file is a Raywake output from this run, that HTTPS URL is reused; otherwise
  the image is sent inline as a compressed data URI. No third-party file host needed.

- `public_url(path)` -> an HTTPS link for services that must fetch the file
  themselves (Canva's import). Only available for images Raywake just generated.

Raywake caps a request body at ~1 MB, so `fit_references` shrinks inline images to
share that budget.
"""
from __future__ import annotations

import base64
import io
from pathlib import Path

BODY_BUDGET = 900_000      # bytes of inline references per request (Raywake body cap ~1 MB)
REF_MAX_SIDE = 1280        # a reference only needs enough detail to reproduce the page


def _matching_output_url(path: str) -> str | None:
    from .raywake import output_url_for
    try:
        return output_url_for(Path(path).read_bytes())
    except OSError:
        return None


def _data_uri(img_bytes: bytes, max_side: int, max_bytes: int) -> str:
    """Re-encode to a JPEG data URI no bigger than max_bytes (base64 included)."""
    from PIL import Image
    im = Image.open(io.BytesIO(img_bytes))
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    side, quality = max_side, 85
    while True:
        scaled = im.copy()
        scaled.thumbnail((side, side))
        buf = io.BytesIO()
        scaled.save(buf, format="JPEG", quality=quality, optimize=True)
        uri = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
        if len(uri) <= max_bytes or side <= 384:
            return uri
        if quality > 60:
            quality -= 10
        else:
            side = int(side * 0.8)


def upload(path: str) -> str | None:
    """A model-readable reference for a local image (name kept for existing callers)."""
    url = _matching_output_url(path)
    if url:
        return url
    try:
        return _data_uri(Path(path).read_bytes(), REF_MAX_SIDE, BODY_BUDGET)
    except Exception as e:  # noqa: BLE001
        print(f"[hosting] could not prepare reference {path}: {e}")
        return None


def public_url(path: str) -> str | None:
    """HTTPS URL for a file Raywake generated in this run (Canva import), else None."""
    url = _matching_output_url(path)
    if not url:
        print(f"[hosting] no public URL for {path} — Canva import needs an HTTPS link; "
              "host the file yourself and pass its URL")
    return url


def fit_references(refs: list[str]) -> list[str]:
    """Shrink inline data-URI references so together they fit one Raywake request."""
    inline = [r for r in refs if r.startswith("data:")]
    if not inline or sum(len(r) for r in inline) <= BODY_BUDGET:
        return refs
    share = BODY_BUDGET // len(inline)
    out = []
    for r in refs:
        if r.startswith("data:") and len(r) > share:
            r = _data_uri(base64.b64decode(r.split(",", 1)[1]), REF_MAX_SIDE, share)
        out.append(r)
    return out
