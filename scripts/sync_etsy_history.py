"""Sync live Etsy shop listings into the durable dedup history.

The engine's duplicate-prevention reads data/product_history.jsonl. Listings that
were published from another machine/copy are invisible to local dedup, so the
engine keeps re-producing themes that are already live. This script pulls the
shop's listings (active + draft) and appends a history line for any whose Etsy
listing_id is not already recorded — so future `produce` runs dedup against the
*actual* shop, not just what this machine made.

Theme tokens come from the clean product name (text before the first "|"), since
Etsy titles are keyword-stuffed after the separator.

Idempotent: re-running only adds listings not already in history. Never deletes.

Usage: .venv/bin/python scripts/sync_etsy_history.py
"""
from __future__ import annotations

from etsy_engine import history
from etsy_engine.config import settings
from etsy_engine.publish import etsy_client as ec


def clean_title(title: str) -> str:
    """The human product name — text before the first '|' (or em-dash)."""
    for sep in ("|", "—", " - "):
        if sep in title:
            return title.split(sep, 1)[0].strip()
    return title.strip()


def fetch_listings(state: str) -> list[dict]:
    out, offset = [], 0
    while True:
        d = ec.request(
            "GET", f"/shops/{settings.etsy_shop_id}/listings",
            params={"state": state, "limit": 100, "offset": offset},
        )
        results = d.get("results", [])
        out.extend(results)
        if len(out) >= (d.get("count") or 0) or not results:
            break
        offset += len(results)
    return out


def main() -> None:
    known_ids = {e.get("etsy_listing_id") for e in history.load()
                 if e.get("etsy_listing_id")}
    print(f"[sync] history already knows {len(known_ids)} etsy listing ids")

    listings = fetch_listings("active") + fetch_listings("draft")
    print(f"[sync] fetched {len(listings)} shop listings (active + draft)")

    added = 0
    for ls in listings:
        lid = ls.get("listing_id")
        if not lid or lid in known_ids:
            continue
        name = clean_title(ls.get("title", ""))
        tokens = sorted(history.theme_tokens(name))
        history.record({
            "product_id": None,
            "bundle_type": name,
            "trend_term": name,
            "source": "etsy_sync",
            "tier": ls.get("state"),
            "etsy_listing_id": lid,
            "url": ls.get("url"),
            "theme_tokens": tokens,
        })
        known_ids.add(lid)
        added += 1
        print(f"  + {lid} [{ls.get('state')}] {name[:50]!r} -> {tokens}")

    print(f"[sync] added {added} new listing(s) to history; "
          f"theme vocabulary now {len(history.known_theme_tokens())} tokens")


if __name__ == "__main__":
    main()
