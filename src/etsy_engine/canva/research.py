"""Competitor DESIGN research for the Canva line.

The engine already reads a niche's demand/price/tags (`scoring.etsy_market`). This adds the
missing half: what the WINNING listings in that niche actually LOOK like. It pulls the hero
images of the current top-selling listings, tiles them into ONE collage, and asks Claude vision
for the niche's winning design language (palette, motifs, layout, typography) + which of our
aesthetics fits + a short directive. That brief steers `poster.build_prompt`, so a product is
designed to what buyers in THAT niche buy, instead of one generic boutique look every time.

Cost-lean: one collage => ONE vision call per product (cached to disk). ADDITIVE: it never
touches the PDF pipeline and fails soft (no images / no key => returns None, generic look).
"""
from __future__ import annotations

import json
from io import BytesIO
from urllib.parse import quote

from ..config import DATA_DIR
from . import design as D

_CACHE = DATA_DIR / "canva_style_briefs.json"


def _load_cache() -> dict:
    if _CACHE.exists():
        try:
            return json.loads(_CACHE.read_text())
        except (ValueError, OSError):
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    try:
        _CACHE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE.write_text(json.dumps(cache, indent=2))
    except OSError:
        pass


def _top_hero_urls(keyword: str, n: int) -> list[str]:
    """Hero image URLs of the top-ranked (best-seller-proxy) listings for a keyword.

    `/listings/active` returns no images even with includes, so we take the top listing_ids
    and fetch each listing's hero via `/listings/{id}/images` (cheap app-key GETs).
    """
    from ..publish import etsy_client as ec
    try:
        data = ec.app_request(
            "GET",
            f"/listings/active?keywords={quote(keyword)}&limit={min(n, 24)}&sort_on=score",
        )
    except Exception as e:  # noqa: BLE001 - fail soft, research is optional
        print(f"[research] listings '{keyword}' failed: {e}")
        return []
    ids = [r.get("listing_id") for r in (data.get("results") or [])[:n] if r.get("listing_id")]
    urls: list[str] = []
    for lid in ids:
        try:
            im = ec.app_request("GET", f"/listings/{lid}/images?limit=1")
            res = im.get("results") or []
            if res:
                u = res[0].get("url_570xN") or res[0].get("url_fullxfull")
                if u:
                    urls.append(u)
        except Exception:  # noqa: BLE001
            continue
    return urls


def _collage(urls: list[str], cell: int = 420) -> bytes | None:
    """Download the hero images and tile them into one grid (so vision costs ONE call)."""
    import requests
    from PIL import Image

    tiles: list[Image.Image] = []
    for u in urls:
        try:
            b = requests.get(u, timeout=30).content
            im = Image.open(BytesIO(b)).convert("RGB")
            im.thumbnail((cell, cell))
            canvas = Image.new("RGB", (cell, cell), (255, 255, 255))
            canvas.paste(im, ((cell - im.width) // 2, (cell - im.height) // 2))
            tiles.append(canvas)
        except Exception:  # noqa: BLE001
            continue
    if not tiles:
        return None
    cols = 3 if len(tiles) > 4 else 2
    rows = (len(tiles) + cols - 1) // cols
    grid = Image.new("RGB", (cols * cell, rows * cell), (245, 245, 245))
    for i, t in enumerate(tiles):
        grid.paste(t, ((i % cols) * cell, (i // cols) * cell))
    buf = BytesIO()
    grid.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


_SYS = (
    "You are an Etsy design analyst. The image is a grid of the hero photos of the current "
    "TOP-SELLING listings for ONE product niche. Infer the DESIGN LANGUAGE that is winning with "
    "buyers so a NEW product can be designed to that taste (learn, never copy). "
    "Return JSON ONLY:\n"
    '{"palette":"dominant colors buyers are actually buying",'
    '"motifs":"decoration style: watercolor florals / fine line-art / none-minimal / photos / bold shapes",'
    '"layout":"common composition + hierarchy patterns",'
    '"typography":"serif / sans / script; bold or delicate",'
    '"vibe":"one short phrase e.g. modern minimalist, boho watercolor, bold retro, cute pastel",'
    f'"recommended_aesthetic":"one of exactly: {", ".join(D.AESTHETICS)}",'
    '"brief":"2-3 sentence directive telling an image model the exact look to produce so the '
    'design fits what sells in THIS niche (colors, motifs, type, mood). Be specific and concrete.",'
    '"differentiator":"the ONE concrete visual axis to push PAST this niche\'s mean so our product '
    'stops the scroll, while staying instantly recognizable as this niche. Name a single lever a '
    'buyer would SEE at thumbnail size: a bolder color block / higher figure-ground contrast / a '
    'sharper focal hierarchy / a distinctive but on-theme motif. Not a new niche, not an audience '
    'swap: the same buyer, one notch bolder than the incumbents."}'
)


def design_brief(niche: str, n: int = 6, refresh: bool = False) -> dict | None:
    """Distill the niche's winning design style from real top-seller hero images.

    Returns {palette, motifs, layout, typography, vibe, recommended_aesthetic, brief,
    differentiator} or None (no images / no key). Cached per niche so it costs at most one vision
    call per new niche.
    """
    key = niche.strip().lower()
    cache = _load_cache()
    if not refresh and key in cache:
        return cache[key]

    urls = _top_hero_urls(niche, n)
    if not urls:
        return None
    collage = _collage(urls)
    if not collage:
        return None

    from ..llm import vision_json
    try:
        out = vision_json(_SYS, f"Niche: {niche}. Analyze the winning design language.",
                          collage, max_tokens=700)
    except Exception as e:  # noqa: BLE001
        print(f"[research] vision failed for '{niche}': {e}")
        return None
    if not isinstance(out, dict) or not out.get("brief"):
        return None
    rec = out.get("recommended_aesthetic")
    if rec not in D.AESTHETICS:
        out["recommended_aesthetic"] = None
    out["_sample"] = len(urls)
    cache[key] = out
    _save_cache(cache)
    return out
