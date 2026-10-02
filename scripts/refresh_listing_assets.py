"""Replace a draft listing's images AND digital files with the current local ones.

Used after regenerating a product's mockups/pages (e.g. an honesty fix) to push the
corrected assets to the existing Etsy draft without recreating the listing.
Etsy won't let you delete the last image/file, so we upload the new ones first,
then delete the old ones.

Usage: .venv/bin/python scripts/refresh_listing_assets.py <product_id> <listing_id>
"""
from __future__ import annotations

import sys
from pathlib import Path

from etsy_engine import db
from etsy_engine.config import settings
from etsy_engine.models import MOCKUP_KINDS
from etsy_engine.publish import etsy_client as ec
from etsy_engine.publish.publisher import _build_bundle_pdf, _build_pages_zip


def refresh(product_id: int, listing_id: int) -> None:
    shop = settings.etsy_shop_id

    # --- images (mockups) ---
    old_imgs = [im["listing_image_id"]
                for im in ec.request("GET", f"/listings/{listing_id}/images").get("results", [])]
    rank = {k: i for i, k in enumerate(MOCKUP_KINDS)}
    mks = sorted(db.mockups_for_product(product_id), key=lambda m: rank.get(m["kind"], 9))
    for i, m in enumerate(mks, start=1):
        p = Path(m["file_path"])
        if not p.exists():
            continue
        with p.open("rb") as fh:
            ec.upload(f"/shops/{shop}/listings/{listing_id}/images",
                      files={"image": (p.name, fh, "image/jpeg")}, data={"rank": i})
        print(f"  image {i}: {m['kind']}")
    for iid in old_imgs:
        ec.request("DELETE", f"/shops/{shop}/listings/{listing_id}/images/{iid}")
    print(f"  replaced {len(mks)} images (removed {len(old_imgs)} old)")

    # --- digital files (bundle.pdf + individual-pages.zip) ---
    old_files = [f["listing_file_id"]
                 for f in ec.request("GET", f"/shops/{shop}/listings/{listing_id}/files").get("results", [])]
    deliverables = [(_build_bundle_pdf(product_id), "application/pdf"),
                    (_build_pages_zip(product_id), "application/zip")]
    for rk, (fpath, mime) in enumerate(deliverables, start=1):
        if not fpath:
            continue
        with Path(fpath).open("rb") as fh:
            ec.upload(f"/shops/{shop}/listings/{listing_id}/files",
                      files={"file": (Path(fpath).name, fh, mime)},
                      data={"name": Path(fpath).name[:70], "rank": rk})
        print(f"  file: {Path(fpath).name}")
    for fid in old_files:
        ec.request("DELETE", f"/shops/{shop}/listings/{listing_id}/files/{fid}")
    print(f"  replaced {len(deliverables)} files (removed {len(old_files)} old)")
    print(f"#{product_id} listing {listing_id} refreshed")


if __name__ == "__main__":
    refresh(int(sys.argv[1]), int(sys.argv[2]))
