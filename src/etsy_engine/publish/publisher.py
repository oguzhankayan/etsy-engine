"""Etsy Publisher (Agent 11). Creates a DRAFT digital listing from our data.

Draft only — Etsy creates new listings inactive, and we never flip them to
active. A human reviews in the Etsy dashboard and publishes. We attach the
mockups as listing images and the generated printables as the digital files.
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import db
from ..config import OUTPUT_DIR, settings
from ..learning.rank_tracker import derive_keyword
from ..models import MOCKUP_KINDS
from . import etsy_client as ec


def resolve_shop_id() -> str:
    if settings.etsy_shop_id:
        return settings.etsy_shop_id
    shop_id = ec.me().get("shop_id")
    if not shop_id:
        raise ec.EtsyError("No shop_id in ETSY_SHOP_ID and getMe returned none.")
    return str(shop_id)


class CatalogCapReached(ec.EtsyError):
    """Raised when the shop's ACTIVE-listing count is at/above the configured catalog cap."""


def active_listing_count() -> int:
    """ACTIVE listings in the shop — the catalog size the cap is measured against.

    Prefers the LIVE Etsy count (`shop.listing_active_count`); falls back to the DB's last-synced
    listing states so the cap still holds if the shop call fails."""
    try:
        data = ec.request("GET", f"/shops/{resolve_shop_id()}")
        n = data.get("listing_active_count")
        if n is not None:
            return int(n)
    except Exception:
        pass
    try:
        return sum(1 for r in db.products_with_listings() if r.get("state") == "active")
    except Exception:
        return 0


def enforce_catalog_cap(cap: int | None = None) -> None:
    """Refuse to create a new draft once the shop is at/above the active-listing cap.

    The profitability audit's #1 leak was an over-built catalog (~13x demand): every extra dead
    listing costs a renewal fee and dilutes the shop. `cap`<=0 disables the gate (the default), so
    it is opt-in and changes no behavior until configured. Raises `CatalogCapReached` at the cap."""
    cap = settings.catalog_active_cap if cap is None else cap
    if not cap or cap <= 0:
        return
    n = active_listing_count()
    if n >= cap:
        raise CatalogCapReached(
            f"catalog cap reached: {n} active listings >= cap {cap}; refusing to create a new "
            f"draft (raise settings.catalog_active_cap to override)")


def smoke_draft() -> int:
    """Live-API health check of the publish path: create ONE throwaway Etsy draft and immediately
    delete it, returning its listing id. Exercises auth + taxonomy + POST + DELETE end to end.

    Isolated from the real publish path on purpose: it creates NO product/listing DB row, does not
    run the catalog cap, and touches no existing listing — so `publish_product` behavior for real
    listings is unchanged. If the DELETE fails the created id is surfaced (in the raised error) so a
    human can clean up the one stray draft."""
    settings.require("etsy_api_key")
    shop_id = resolve_shop_id()
    taxonomy_id = settings.etsy_taxonomy_id or settings.etsy_taxonomy_id_print
    body = {
        "quantity": 1,
        "title": "SMOKE TEST — automated, safe to delete",
        "description": "Automated publish-path smoke test. Created and deleted immediately.",
        "price": 1.00,
        "who_made": "i_did",
        "when_made": "2020_2026",
        "taxonomy_id": taxonomy_id,
        "type": "download",
        "is_supply": False,
        "should_auto_renew": False,
    }
    created = ec.request("POST", f"/shops/{shop_id}/listings", json=body)
    lid = int(created["listing_id"])
    try:
        # Etsy's deleteListing is application-scoped (NOT /shops/{id}/listings/{id}, which 404s).
        ec.request("DELETE", f"/listings/{lid}")
    except Exception as e:
        raise ec.EtsyError(f"smoke draft {lid} was created but NOT deleted — clean it up: {e}")
    return lid


def search_taxonomy(query: str) -> list[dict]:
    """Find seller-taxonomy nodes matching a query (for ETSY_TAXONOMY_ID)."""
    nodes = ec.request("GET", "/seller-taxonomy/nodes").get("results", [])
    q = query.lower()
    hits = []
    def walk(node, trail):
        name = node.get("name", "")
        path = trail + [name]
        if q in name.lower():
            hits.append({"id": node.get("id"), "path": " > ".join(path)})
        for child in node.get("children", []) or []:
            walk(child, path)
    for n in nodes:
        walk(n, [])
    return hits


def _asset_paths(product_id: int) -> list[Path]:
    return [Path(a["file_path"]) for a in db.assets_for_product(product_id)
            if Path(a["file_path"]).exists()]


def _build_bundle_pdf(product_id: int):
    """Combine all of a product's printable JPEGs into one print-ready PDF."""
    from PIL import Image

    paths = _asset_paths(product_id)
    if not paths:
        return None
    imgs = [Image.open(p).convert("RGB") for p in paths]
    out = paths[0].parent / "bundle.pdf"
    imgs[0].save(out, save_all=True, append_images=imgs[1:], resolution=300.0)
    return out


def _build_pages_zip(product_id: int):
    """Zip the individual page JPEGs so buyers can download each page separately."""
    import zipfile

    paths = _asset_paths(product_id)
    if not paths:
        return None
    out = paths[0].parent / "individual-pages.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in paths:
            zf.write(p, arcname=p.name)
    return out


# --- Deliverables that honor Etsy's caps (≤5 files, ≤20 MB each) ---
_DLV_DPI, _DLV_Q, _A4 = 220, 80, (2480, 3508)
_MAX_FILE_MB, _MAX_FILES = 19.0, 5


def _fit_a4(path):
    from PIL import Image
    im = Image.open(path).convert("RGB")
    s = min(_A4[0] / im.width, _A4[1] / im.height)
    im = im.resize((int(im.width * s), int(im.height * s)), Image.LANCZOS)
    if im.size == _A4:
        return im
    page = Image.new("RGB", _A4, (255, 255, 255))
    page.paste(im, ((_A4[0] - im.width) // 2, (_A4[1] - im.height) // 2))
    return page


def _write_pdf(paths, out):
    imgs = [_fit_a4(p) for p in paths]
    imgs[0].save(out, "PDF", resolution=float(_DLV_DPI), save_all=True,
                 append_images=imgs[1:], quality=_DLV_Q)
    return out


def _page_groups(product_id: int):
    """Ordered [(group_name, [page_paths])]. Banner assets expand to their per-page
    JPEGs (one group each); all single-sheet JPEGs form one 'Printables' group."""
    from ..generate import banner
    banner_groups, sheets = [], []
    for a in _asset_rows_ordered(product_id):
        fp = Path(a["file_path"])
        if a.get("asset_type") == banner.ASSET_TYPE:
            pages = sorted(banner.page_dir(product_id, a["name"]).glob("*.jpg"))
            if not pages and fp.exists():        # fallback: ship the PDF as-is
                banner_groups.append((a["name"], [fp]))
            elif pages:
                banner_groups.append((a["name"], pages))
        elif fp.exists() and fp.suffix.lower() in (".jpg", ".jpeg", ".png"):
            sheets.append(fp)
    groups = list(banner_groups)
    if sheets:
        groups.append((f"{_slug_name(product_id)}-Printables", sheets))
    return groups


def _asset_rows_ordered(product_id: int):
    return db.assets_for_product(product_id)


def _slug_name(product_id: int) -> str:
    prod = next((p for p in db.products_with_items() if p["id"] == product_id), None)
    base = (prod or {}).get("bundle_type", f"product-{product_id}")
    import re
    return re.sub(r"[^A-Za-z0-9]+", "-", base).strip("-")[:40] or f"product-{product_id}"


def _pack_group(name, paths, out_dir):
    """Write a group to as few PDFs as possible, each < _MAX_FILE_MB."""
    import math
    import re
    base = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-")[:50] or "bundle"
    if len(paths) == 1 and Path(paths[0]).suffix.lower() == ".pdf":
        return [Path(paths[0])]                 # already a PDF asset, keep as-is
    whole = out_dir / f"{base}.pdf"
    _write_pdf(paths, whole)
    if whole.stat().st_size / 1e6 <= _MAX_FILE_MB or len(paths) == 1:
        return [whole]
    n = math.ceil((whole.stat().st_size / 1e6) / _MAX_FILE_MB)
    whole.unlink()
    size = math.ceil(len(paths) / n)
    out = []
    for i in range(0, len(paths), size):
        p = out_dir / f"{base}-{i // size + 1}.pdf"
        _write_pdf(paths[i:i + size], p)
        out.append(p)
    return out


def build_deliverables(product_id: int) -> list[tuple]:
    """Assemble the buyer's files: compressed themed PDFs, ≤5 files & <20 MB each
    (Etsy caps). Banner assets become their own print-and-cut PDF(s); single sheets
    are combined. Returns [(path, 'application/pdf')]."""
    out_dir = OUTPUT_DIR / str(product_id) / "deliverables"
    out_dir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    for name, paths in _page_groups(product_id):
        files += _pack_group(name, paths, out_dir)
    # Etsy hard cap: if a big bundle blew past 5 files, re-pack every page into 5
    # size-balanced PDFs (group labels are sacrificed to fit the platform limit).
    if len(files) > _MAX_FILES:
        import math
        all_pages = [p for _, ps in _page_groups(product_id) for p in ps
                     if Path(p).suffix.lower() != ".pdf"]
        for f in files:
            if f.parent == out_dir:
                f.unlink(missing_ok=True)
        per = math.ceil(len(all_pages) / _MAX_FILES)
        files = []
        for i in range(0, len(all_pages), per):
            p = out_dir / f"{_slug_name(product_id)}-part-{i // per + 1}.pdf"
            _write_pdf(all_pages[i:i + per], p)
            files.append(p)
    return [(f, "application/pdf") for f in files]


def _build_print_files(product_id: int):
    """Wall-art delivery at NATIVE ratio ('fit to page' printing; sizes listed in
    the size-guide image). Single print: 1 PNG + 1 one-page PDF. Print SET (2-4
    separate artworks): one PNG per print + ONE combined multi-page PDF (Etsy
    caps digital files at 5, so up to 4 PNGs + 1 PDF fits). We deliberately do
    NOT re-crop to other aspect ratios. Returns [(path, mime)]."""
    from PIL import Image

    paths = _asset_paths(product_id)
    if not paths:
        return []
    out_dir = paths[0].parent
    imgs = [Image.open(p).convert("RGB") for p in paths[:4]]

    out: list[tuple] = []
    pdf_path = out_dir / "wall-art.pdf"
    imgs[0].save(pdf_path, "PDF", resolution=300.0, save_all=True,
                 append_images=imgs[1:])
    out.append((pdf_path, "application/pdf"))

    for i, im in enumerate(imgs, start=1):
        suffix = f"-{i}" if len(imgs) > 1 else ""
        png_path = out_dir / f"wall-art{suffix}.png"
        im.save(png_path, "PNG", dpi=(300, 300))
        out.append((png_path, "image/png"))
    return out


def delete_listing(listing_id: int, force: bool = False) -> bool:
    """Delete a draft listing (needs listings_d scope). Returns True on success.

    Seasonal listings are protected: deleting one resets its accumulated search /
    sales history and forces next year to start from zero (Berkay's "sakın silme").
    Pass force=True to override the guard.
    """
    if not force:
        seasonal = {r["etsy_listing_id"] for r in db.seasonal_listings()}
        if listing_id in seasonal:
            print(f"[publish] refusing to delete seasonal listing {listing_id} "
                  f"(keep-alive). Pass force=True to override.")
            return False
    try:
        ec.request("DELETE", f"/listings/{listing_id}")
        return True
    except Exception as e:
        print(f"[publish] delete {listing_id} failed: {e}")
        return False


def bundle_price(n_pages: int) -> float:
    """Price a printable bundle by content size (page count), clamped to the bundle
    band. A 20-page coloring book is a substantial product — $5 undersells it — so
    value scales with pages (matches how coloring-book *bundles* sell ~$7-14)."""
    if n_pages >= 18:
        p = 7.99
    elif n_pages >= 12:
        p = 6.99
    elif n_pages >= 8:
        p = 5.99
    else:
        p = settings.bundle_price_min
    return round(min(settings.bundle_price_max, max(settings.bundle_price_min, p)), 2)


def set_listing_price(listing_id: int, price: float) -> float:
    """Update a listing's price. Etsy v3 gotcha: price is read-only on the listing
    object — it lives in the inventory. So GET the inventory, rewrite every
    offering's price, and PUT it back (keeping quantity/enabled + property values).
    Returns the price set.
    """
    price = round(float(price), 2)
    inv = ec.request("GET", f"/listings/{listing_id}/inventory")
    products = []
    for p in inv.get("products") or []:
        offerings = [
            {"price": price, "quantity": o.get("quantity", 999),
             "is_enabled": o.get("is_enabled", True)}
            for o in (p.get("offerings") or [])
        ]
        pvs = [
            {k: pv[k] for k in ("property_id", "value_ids", "values") if k in pv}
            for pv in (p.get("property_values") or [])
        ]
        products.append({"sku": p.get("sku") or "", "offerings": offerings,
                         "property_values": pvs})
    ec.request("PUT", f"/listings/{listing_id}/inventory", json={"products": products})
    return price


# sanitize_title now lives in the shared pre-publish gate (re-exported for existing importers).
from .gate import check_listing, sanitize_title  # noqa: E402,F401


def _order_mockups(mockups: list[dict]) -> list[dict]:
    """Hero first, then the rest in canonical order."""
    rank = {k: i for i, k in enumerate(MOCKUP_KINDS)}
    return sorted(mockups, key=lambda m: rank.get(m["kind"], 99))


LISTING_IMAGE_CAP = 10  # Etsy allows at most 10 images per listing.


def _flat_page_images(product_id: int) -> list[Path]:
    """The generated printable pages, de-duplicated, in generation order. These are
    attached as extra listing images so buyers can read the page detail that the
    styled mockups shrink into illegibility. Free — the pages already exist."""
    seen: set[str] = set()
    out: list[Path] = []
    for a in db.assets_for_product(product_id):
        p = Path(a.get("file_path", ""))
        key = str(p)
        if p.exists() and p.suffix.lower() in (".jpg", ".jpeg", ".png") and key not in seen:
            seen.add(key)
            out.append(p)
    return out


def _attach_page_images(shop_id: str, listing_id: int, product_id: int,
                        start_rank: int, cap: int = LISTING_IMAGE_CAP) -> int:
    """Upload flat page renders as listing images at ranks >= start_rank, filling up
    to the Etsy image cap. Returns the number uploaded."""
    slots = cap - (start_rank - 1)
    if slots <= 0:
        return 0
    uploaded = 0
    for p in _flat_page_images(product_id)[:slots]:
        mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
        rank = start_rank + uploaded
        with p.open("rb") as fh:
            ec.upload(
                f"/shops/{shop_id}/listings/{listing_id}/images",
                files={"image": (p.name, fh, mime)},
                data={"rank": rank},
            )
        uploaded += 1
        print(f"[publish] page image {rank}: {p.name}")
    return uploaded


def seasonal_policy(product_id: int) -> tuple[bool, str, bool]:
    """(is_seasonal, season, auto_renew) for a product, shared by BOTH lines. Keep everything
    alive to accrue search/sales history; only a genuinely one-off VIRAL non-seasonal listing is
    left to lapse (Berkay's rule). Evergreen + seasonal auto-renew so they never expire."""
    from ..models import Tier
    from ..sources.seeds import season_for
    prov = db.provenance(product_id)
    season = season_for(prov.get("term", "") or "")
    is_seasonal = bool(season)
    is_oneoff_viral = int(prov.get("tier", Tier.VIRAL)) == int(Tier.VIRAL) and not is_seasonal
    return is_seasonal, season, (not is_oneoff_viral)


def finalize_listing(product_id: int, listing_id: int, shop_id: str,
                     is_seasonal: bool, season: str) -> str:
    """Post-create listing decoration shared by BOTH the PDF and Canva lines — ONE core so a
    listing feature can never live on one line and be missing on the other (the owner's rule).
    Sets color/occasion attributes, the etsy_listings lifecycle row + product status, the
    rank-tracking primary keyword, and archives provenance (report + durable history). Any future
    listing feature added here reaches both lines for free. Returns the listing URL."""
    url = f"https://www.etsy.com/listing/{listing_id}"
    # Attributes (color/occasion/...) — each acts like a tag and powers Etsy filters.
    try:
        from .attributes import choose_and_set
        product = next((p for p in db.products_with_items() if p["id"] == product_id), None)
        ds = db.get_design_system(product_id)
        choose_and_set(listing_id, shop_id, product, ds, settings.etsy_taxonomy_id)
    except Exception as e:  # noqa: BLE001
        print(f"[publish] attributes skipped: {e}")
    db.upsert_etsy_listing(product_id, listing_id, url, state="draft",
                           is_seasonal=is_seasonal, season=season)
    db.set_product_status(product_id, "drafted")
    if is_seasonal:
        print(f"[publish] tagged seasonal ({season}) — keep-alive, auto-renew on")
    # Store primary target keyword for rank tracking / SEO optimization.
    try:
        keyword = derive_keyword(product_id)
        if keyword:
            db.upsert_listing_keyword(product_id, listing_id, keyword, is_primary=True)
    except Exception as e:  # noqa: BLE001
        print(f"[publish] keyword store skipped: {e}")
    # Archive the decision provenance alongside the product for later audit.
    try:
        from ..reporting import write_product_report
        write_product_report(product_id)
    except Exception as e:  # noqa: BLE001
        print(f"[publish] report skipped: {e}")
    # Append to the durable product history (survives DB resets; dedup source).
    try:
        from ..history import record_product
        record_product(product_id)
    except Exception as e:  # noqa: BLE001
        print(f"[publish] history skipped: {e}")
    return url


def publish_product(product_id: int) -> dict:
    """Create a draft Etsy listing for the product. Returns {listing_id, url}."""
    settings.require("etsy_api_key")
    shop_id = resolve_shop_id()
    enforce_catalog_cap()   # refuse a new draft once the catalog is at its active-listing cap

    product = next((p for p in db.products_with_items() if p["id"] == product_id), None)
    if not product:
        raise ec.EtsyError(f"product {product_id} not found")
    listing = db.get_listing(product_id)
    if not listing:
        raise ec.EtsyError("No SEO listing copy. Run the seo stage first.")

    # Archetype routes taxonomy + price + which files we build/attach.
    pintel = db.get_product_intel(product_id) or {}
    archetype = pintel.get("archetype", "planner")
    if archetype == "print":
        taxonomy_id = settings.etsy_taxonomy_id_print
        med = pintel.get("median_price") or settings.print_price_max
        price = round(min(settings.print_price_max,
                          max(settings.print_price_min, float(med))), 2)
    else:
        taxonomy_id = settings.etsy_taxonomy_id
        # Bundles price by CONTENT (page count), not the keyword median — a coloring
        # keyword's median (~$4) is dominated by single pages/small sets, so it would
        # wrongly pin a full 20-page book to the floor. Value scales with pages.
        price = bundle_price(len(product.get("items", [])))
    if not taxonomy_id:
        raise ec.EtsyError("taxonomy_id unset for archetype " + archetype)

    # Season detection drives the keep-alive registry + auto-renew policy (shared with the Canva line).
    is_seasonal, season, auto_renew = seasonal_policy(product_id)

    tags = json.loads(listing["tags"] or "[]")
    # Single pre-publish gate: sanitize title + tags to Etsy's hard rules and flag honesty issues
    # BEFORE the API call (a tag >20 chars would 400 the whole draft).
    clean, violations = check_listing({"title": listing["title"], "tags": tags}, line="pdf")
    for msg in violations:
        print(f"[publish][gate] {msg}")
    body = {
        "quantity": 999,
        "title": clean["title"],
        "description": listing["description"],
        "price": price,
        "who_made": "i_did",
        # NOT made_to_order: files are ready, so it shows as an instant download.
        "when_made": "2020_2026",
        "taxonomy_id": taxonomy_id,
        "type": "download",          # digital listing
        "is_supply": False,
        "tags": clean["tags"],
        "should_auto_renew": auto_renew,
    }
    created = ec.request("POST", f"/shops/{shop_id}/listings", json=body)
    listing_id = created["listing_id"]
    print(f"[publish] created draft listing {listing_id}")

    # Attach mockups as listing images (hero first), then the flat page renders so
    # buyers can read the fine page detail the mockups shrink away. Both are free —
    # the assets already exist — and Etsy caps listing images at 10.
    n_img = 0
    mockups = _order_mockups(db.mockups_for_product(product_id))
    for m in mockups:
        p = Path(m["file_path"])
        if not p.exists():
            continue
        with p.open("rb") as fh:
            ec.upload(
                f"/shops/{shop_id}/listings/{listing_id}/images",
                files={"image": (p.name, fh, "image/jpeg")},
                data={"rank": n_img + 1},
            )
        n_img += 1
        print(f"[publish] image {n_img}: {m['kind']}")
    _attach_page_images(shop_id, listing_id, product_id, start_rank=n_img + 1)

    # Digital files (Etsy caps at 5). Print archetype: high-res PNG + multi-size
    # print-ready PDF. Planner archetype: combined bundle PDF + ZIP of each page.
    if archetype == "print":
        deliverables = _build_print_files(product_id)
    else:
        # Themed print-and-cut PDFs, ≤5 files & <20 MB each; expands banner assets
        # into their pages (see build_deliverables). Falls back to the legacy
        # single bundle.pdf + zip if page collection somehow yields nothing.
        deliverables = build_deliverables(product_id) or [
            (_build_bundle_pdf(product_id), "application/pdf"),
            (_build_pages_zip(product_id), "application/zip"),
        ]
    for rank, (fpath, mime) in enumerate(deliverables, start=1):
        if not fpath:
            continue
        with fpath.open("rb") as fh:
            ec.upload(
                f"/shops/{shop_id}/listings/{listing_id}/files",
                files={"file": (fpath.name, fh, mime)},
                data={"name": fpath.name[:70], "rank": rank},
            )
        print(f"[publish] digital file: {fpath.name}")

    # Shared post-create decoration (attributes, lifecycle row, keyword, provenance) — same core
    # the Canva line calls, so the two lines can never drift apart on listing features.
    url = finalize_listing(product_id, listing_id, shop_id, is_seasonal, season)
    print(f"[publish] DRAFT ready (review & publish in Etsy): {url}")
    return {"listing_id": listing_id, "url": url}
