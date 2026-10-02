"""Rank tracker — monitors where our live Etsy listings appear in search results.

Uses the public Etsy search API (app-only auth, no OAuth) to find our listing's
position for a target keyword. Snapshots are stored so we can see trends over time
and identify buried listings worth optimizing.
"""
from __future__ import annotations

import re
import time
from urllib.parse import quote

from .. import db
from ..publish import etsy_client as ec

DEFAULT_SAMPLE = 100
SLEEP_BETWEEN = 0.6

# Generic words to strip when deriving a keyword from a title.
STOP = {
    "the", "a", "an", "and", "for", "of", "in", "on", "at", "to", "with",
    "by", "from", "printable", "printables", "digital", "download", "instant",
    "pdf", "kit", "bundle", "set", "pack", "planner", "print", "prints",
    "wall", "art", "decor", "poster", "2026", "2025",
}


def search_rank(keyword: str, listing_id: int, sample: int = DEFAULT_SAMPLE) -> dict:
    """Find our listing's rank for a keyword in Etsy's search results.

    Returns a dict with rank (1-indexed), total_results, result_count, page,
    and found. If the listing is not in the first `sample` results, rank is None
    but we still record total_results so we know it's buried.
    """
    try:
        data = ec.app_request(
            "GET",
            f"/listings/active?keywords={quote(keyword)}&limit={sample}&sort_on=score",
        )
    except Exception as e:
        raise RuntimeError(f"Etsy search failed for '{keyword}': {e}") from e

    results = data.get("results") or []
    total_results = int(data.get("count", 0) or 0)
    target = int(listing_id)

    for idx, r in enumerate(results):
        if int(r.get("listing_id", 0)) == target:
            rank = idx + 1
            return {
                "rank": rank,
                "total_results": total_results,
                "result_count": len(results),
                "page": (rank - 1) // sample + 1,
                "found": True,
            }

    return {
        "rank": None,
        "total_results": total_results,
        "result_count": len(results),
        "page": 1,
        "found": False,
    }


def _clean_word(word: str) -> str | None:
    w = re.sub(r"[^a-z0-9]", "", word.lower())
    return w if w and w not in STOP and len(w) >= 2 else None


def derive_keyword(product_id: int) -> str | None:
    """Derive a target keyword from the listing title if none is stored.

    Takes the text before the first '|' or '—', strips generic words, and returns
    the first 2-4 meaningful words joined by spaces.
    """
    listing = db.get_listing(product_id)
    if not listing:
        return None
    title = (listing.get("title") or "").strip()
    for sep in ("|", "—", " - "):
        if sep in title:
            title = title.split(sep, 1)[0].strip()
            break

    # Split on any non-alphanumeric so em-dashes, slashes, etc. don't glue words.
    raw_words = re.split(r"[^a-zA-Z0-9]+", title)
    words = [_clean_word(w) for w in raw_words]
    words = [w for w in words if w]
    if not words:
        return None
    return " ".join(words[:4])


def track_listing(product_id: int, listing_id: int, keyword: str | None = None) -> dict:
    """Snapshot the rank for one listing/keyword."""
    if not keyword:
        keyword = db.primary_keyword_for(listing_id) or derive_keyword(product_id)
    if not keyword:
        print(f"[rank-track] #{product_id} ({listing_id}): no keyword available")
        return {}

    result = search_rank(keyword, listing_id)
    db.insert_rank_snapshot(
        etsy_listing_id=listing_id,
        keyword=keyword,
        rank=result["rank"],
        total_results=result["total_results"],
        result_count=result["result_count"],
        page=result["page"],
        found=result["found"],
    )
    rank_str = f"#{result['rank']}" if result["rank"] else f">{DEFAULT_SAMPLE}"
    print(f"[rank-track] {listing_id} '{keyword[:40]}' → rank={rank_str} "
          f"(results={result['total_results']})")
    return result


def track_all() -> int:
    """Snapshot ranks for every known Etsy listing. Returns count tracked."""
    listings = db.all_etsy_listings()
    if not listings:
        print("[rank-track] no Etsy listings found")
        return 0

    tracked = 0
    for row in listings:
        product_id = row.get("product_id")
        listing_id = row.get("etsy_listing_id")
        if not product_id or not listing_id:
            continue
        try:
            track_listing(product_id, listing_id)
            tracked += 1
        except Exception as e:
            print(f"[rank-track] {listing_id} failed: {e}")
        if len(listings) > 1:
            time.sleep(SLEEP_BETWEEN)
    print(f"[rank-track] tracked {tracked}/{len(listings)} listings")
    return tracked
