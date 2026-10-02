"""Create a DRAFT Etsy listing for a Canva-line product.

Mirrors publish/publisher.py:publish_product but for a Canva set: honest "editable Canva
template" copy, the i2i mockups + flat previews as listing images, and the delivery PDF as
the digital file. DRAFT ONLY (RULES §B4) — Etsy creates listings inactive; the owner ticks
"made with an AI generator" and hits publish. Reuses the shared Etsy client, so it is fully
part of the engine yet additive: it never touches the primary PDF publish path.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..config import DATA_DIR, settings
from ..publish import etsy_client as ec
from ..publish.publisher import resolve_shop_id

CANVA_LEDGER = DATA_DIR / "canva_products.jsonl"
DEFAULT_PRICE = 11.99            # fallback when the niche has no median price
PRICE_MIN, PRICE_MAX = 6.99, 24.99


def refresh_design_images(out_dir: str | Path, urls: list[str]) -> list[str]:
    """Overwrite the local page renders with the FINAL pages the owner edited in Canva.

    THE RULE: mockups + listing images must show what the buyer actually downloads, i.e. the
    design AFTER Magic Layers + the owner's edits, never our pre-edit renders. The agent exports
    the final pages from the owner's Canva design (MCP `export-design`) and passes the download
    URLs here in page order; we overwrite the exact files `canva publish` uploads and mark the
    manifest `canva_final` so publish knows the images are the real deliverable.
    """
    import requests

    from ..models import now
    out = Path(out_dir)
    m = json.loads((out / "manifest.json").read_text())
    paths = m.get("image_paths") or []
    if len(urls) != len(paths):
        raise ValueError(f"Canva export returned {len(urls)} pages but the manifest has {len(paths)}")
    for url, rel in zip(urls, paths):        # paths are repo-root-relative (or absolute), like publish reads them
        Path(rel).write_bytes(requests.get(url, timeout=120).content)
    m["canva_final"] = True
    m["canva_exported_at"] = now()
    (out / "manifest.json").write_text(json.dumps(m, indent=2))
    return paths


def market_price(median: float | None, n_pages: int = 1) -> float:
    """Price a Canva product from its niche's median, not a flat number.

    A multi-page SET is worth more than a single sign, so scale up with page count (capped);
    then sit slightly UNDER the value estimate (a new shop with no reviews wins on price), inside
    a sane editable-template band, at a .99 psychological price. No median -> DEFAULT_PRICE.
    """
    if not median or median <= 0:
        return DEFAULT_PRICE
    value = median * min(1.6, 1.0 + 0.15 * max(0, n_pages - 1))   # set premium over a single
    p = max(PRICE_MIN, min(value * 0.9, PRICE_MAX))              # under-value for launch, banded
    return round(round(p) - 0.01, 2)                             # -> X.99


def _image_alt(title: str, filename: str, rank: int) -> str:
    """An honest, descriptive alt text per listing image (a11y WCAG 1.1.1 + Etsy image SEO).
    Derives the image role from its filename; caps at Etsy's 250-char-safe length."""
    stem = filename.lower()
    if "hero" in stem:
        desc = "framed and displayed, front view"
    elif "lifestyle" in stem:
        desc = "styled in a room setting"
    elif "contents" in stem:
        desc = "all pages shown as a set"
    elif "page" in stem:
        desc = f"page {rank} design preview"
    else:
        desc = "design preview"
    return f"{title} - {desc}"[:250]


def create_draft(listing: dict, image_paths: list, delivery_pdf: str | Path,
                 template_link: str, price: float | None = None,
                 taxonomy_id: int | None = None, product_id: int | None = None,
                 page_images: list | None = None) -> dict:
    """Create the draft listing. `listing` = {title, tags, description}. Returns {listing_id, url}.

    `image_paths` are the styled mockups (hero first); `page_images` are the FLAT page renders,
    appended after the mockups exactly like the PDF line does (publisher._attach_page_images) so
    buyers can read the page detail the styled mockups shrink into illegibility. Reuses the PDF
    line's rule + cap rather than a parallel one."""
    settings.require("etsy_api_key")
    shop_id = resolve_shop_id()
    from ..publish.publisher import enforce_catalog_cap
    enforce_catalog_cap()   # same catalog cap guards the Canva line's drafts too
    tax = taxonomy_id or settings.etsy_taxonomy_id
    if not tax:
        raise ec.EtsyError("etsy_taxonomy_id unset (run `etsy-engine etsy-taxonomy`)")

    # Single pre-publish gate (Canva line: 'editable/Canva' is honest here). Fixes title + tags
    # to Etsy's hard rules before the API call, so a tag >20 chars can't 400 the draft.
    from ..publish.gate import check_listing
    clean, violations = check_listing(listing, line="canva")
    for msg in violations:
        print(f"[canva-publish][gate] {msg}")

    # Same seasonal keep-alive / auto-renew policy the PDF line uses (shared core).
    from ..publish.publisher import finalize_listing, seasonal_policy
    is_seasonal, season, auto_renew = (
        seasonal_policy(product_id) if product_id else (False, "", True))

    body = {
        "quantity": 999,
        "title": clean["title"],
        "description": listing["description"],
        "price": price or DEFAULT_PRICE,
        "who_made": "i_did",
        "when_made": "2020_2026",
        "taxonomy_id": tax,
        "type": "download",                 # digital, instant download
        "is_supply": False,
        "tags": clean["tags"],
        "should_auto_renew": auto_renew,
    }
    created = ec.request("POST", f"/shops/{shop_id}/listings", json=body)
    lid = created["listing_id"]
    print(f"[canva-publish] created draft listing {lid}")

    from ..publish.publisher import LISTING_IMAGE_CAP   # reuse the PDF line's 10-image Etsy cap
    uploaded = 0
    # Styled mockups first (hero leads), then the flat page renders — same order + cap as the PDF
    # line, so a Canva listing shows every readable page too, not just 3 mockups (owner's rule).
    for ip in (Path(p) for p in list(image_paths) + list(page_images or [])):
        if not ip.exists() or uploaded >= LISTING_IMAGE_CAP:
            continue
        uploaded += 1
        with ip.open("rb") as fh:
            ec.upload(f"/shops/{shop_id}/listings/{lid}/images",
                      files={"image": (ip.name, fh, "image/jpeg")},
                      data={"rank": uploaded,
                            "alt_text": _image_alt(clean["title"], ip.name, uploaded)})
        print(f"[canva-publish] image {uploaded}: {ip.name}")

    dp = Path(delivery_pdf)
    with dp.open("rb") as fh:
        ec.upload(f"/shops/{shop_id}/listings/{lid}/files",
                  files={"file": (dp.name, fh, "application/pdf")},
                  data={"name": dp.name[:70], "rank": 1})
    print(f"[canva-publish] digital file: {dp.name}")

    # Shared post-create decoration (attributes, lifecycle row, rank keyword, provenance/history) —
    # the SAME core the PDF line runs, so a Canva listing gets every feature the PDF listing does.
    if product_id:
        url = finalize_listing(product_id, lid, shop_id, is_seasonal, season)
    else:
        url = f"https://www.etsy.com/listing/{lid}"

    CANVA_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with CANVA_LEDGER.open("a") as fh:
        fh.write(json.dumps({"listing_id": lid, "url": url, "title": body["title"],
                             "template_link": template_link, "state": "draft",
                             "product_id": product_id}) + "\n")
    print(f"[canva-publish] DRAFT ready: {url}")
    print("[canva-publish] REMINDER: in the Etsy draft, tick 'made with an AI generator', "
          "confirm the digital file + images, then publish.")
    return {"listing_id": lid, "url": url}
