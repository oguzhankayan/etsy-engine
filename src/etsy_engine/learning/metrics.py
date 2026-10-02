"""Metrics puller (Faz 5). Reads listing performance from the Etsy API.

For each published listing we record views + favorites (from getListing) and
sales (best-effort count of transactions for the listing). Snapshots accumulate
in the `metrics` table so the feedback loop can track change over time.
"""
from __future__ import annotations

from .. import db
from ..publish import etsy_client as ec
from ..publish.publisher import resolve_shop_id
from ..scoring.etsy_market import _price_usd


_sales_warned = False


def _sales_count(shop_id: str, listing_id: int) -> int:
    """Best-effort: count transactions for this listing. Returns 0 on any issue,
    but warn on the first failure — a token missing transactions_r 403s on every
    listing, which used to silently record sales=0 across the whole shop."""
    global _sales_warned
    try:
        data = ec.request(
            "GET", f"/shops/{shop_id}/listings/{listing_id}/transactions?limit=100"
        )
        return int(data.get("count", 0))
    except Exception as e:
        if not _sales_warned:
            _sales_warned = True
            print(f"[metrics] WARNING: transactions lookup failing (sales will "
                  f"read 0). First error: {e}")
            if "403" in str(e):
                print("[metrics] 403 usually means the token lacks transactions_r "
                      "— re-run: etsy-engine etsy-auth")
        return 0


def pull_metrics() -> int:
    """Snapshot metrics for every published Etsy listing. Returns rows written."""
    listings = db.all_etsy_listings()
    if not listings:
        print("[metrics] no published listings yet")
        return 0
    shop_id = resolve_shop_id()
    written = 0
    for row in listings:
        lid = row["etsy_listing_id"]
        try:
            listing = ec.request("GET", f"/listings/{lid}")
        except Exception as e:
            print(f"[metrics] listing {lid} failed: {e}")
            continue
        views = int(listing.get("views", 0) or 0)
        favorites = int(listing.get("num_favorers", 0) or 0)
        sales = _sales_count(shop_id, lid)
        price = _price_usd(listing.get("price")) or 0.0
        db.insert_metric(lid, views, favorites, sales, price)
        # Sync the real listing state back (owner publishes drafts in the Etsy
        # UI, so local rows otherwise claim 'draft' forever).
        state = str(listing.get("state") or "")
        db.set_listing_state(lid, state)
        db.sync_product_status_from_listing(lid, state)
        written += 1
        print(f"[metrics] {lid}: views={views} favs={favorites} sales={sales} "
              f"price=${price:.2f} [{listing.get('state', '?')}]")

    # Self-learning, performance-gated: listings that proved buyer interest feed
    # their trend terms back into the discovery seed pool.
    try:
        from ..sources.seeds import feedback_winning_seeds
        winners = feedback_winning_seeds()
        if winners:
            print(f"[metrics] seed feedback: {len(winners)} proven terms -> seeds")
    except Exception as e:
        print(f"[metrics] seed feedback skipped: {e}")
    return written
