"""Canonical Etsy shop-profile copy and safe update helper."""
from __future__ import annotations

from ..config import settings
from . import etsy_client as ec


PROFILE = {
    "title": "Printable Planners, Classroom Kits & Digital Downloads",
    "announcement": (
        "Thoughtfully designed printable planners, classroom resources, party kits, "
        "and wall art. Every item is an instant digital download; no physical product "
        "will be shipped. See each listing for included files, sizes, and print guidance."
    ),
    "sale_message": (
        f"Thank you for supporting {settings.shop_name}. Find your files under Etsy "
        "Purchases & Reviews. Message us through Etsy if you need help accessing or "
        "printing your download."
    ),
    "digital_sale_message": (
        "Your digital files are ready in Etsy under Purchases & Reviews. This is an "
        "instant download, so no physical item will arrive. For the best result, review "
        "the included print guidance and choose Actual Size or Fit to Page as directed."
    ),
}


def update_shop_profile(*, dry_run: bool = True) -> dict:
    """Preview or apply the canonical storefront copy through Etsy updateShop."""
    settings.require("etsy_shop_id")
    path = f"/shops/{settings.etsy_shop_id}"
    current = ec.request("GET", path)
    changes = {
        key: {"from": current.get(key), "to": value}
        for key, value in PROFILE.items()
        if current.get(key) != value
    }
    if changes and not dry_run:
        # updateShop accepts application/x-www-form-urlencoded, not JSON.
        ec.request("PUT", path, data=PROFILE)
    return {"dry_run": dry_run, "changes": changes}
