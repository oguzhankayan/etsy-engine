"""Buried-listing SEO optimizer.

Identifies live Etsy listings that rank poorly for high-demand keywords, then
rewrites their title/tags/description using real winning tags from the Etsy
market. All rewrites start as dry-run suggestions; a separate apply step updates
the live listing so a human stays in the loop.
"""
from __future__ import annotations

import json
import re

from .. import db
from ..llm import complete_json
from ..models import Listing
from ..publish import etsy_client as ec
from ..publish.publisher import resolve_shop_id, sanitize_title
from ..scoring.etsy_market import market_intel
from .writer import build_tags

DEFAULT_MIN_RANK = 20
DEFAULT_MIN_DEMAND = 0.1
MAX_SAMPLE = 100

OPTIMIZE_SYSTEM = """You are an expert Etsy SEO copywriter optimizing an EXISTING
listing. The goal is to improve ranking for the target keyword while staying
honest and on-brand.

Rules:
- TITLE: short, clear, lead with what the item IS. Front-load the primary keyword
  naturally. Hard max 140 chars. Aim 70-110 chars. Use | to separate phrases.
- DESCRIPTION: first 1-2 sentences must read naturally and include the primary
  keyword + 1-2 related phrases. Then bullets of what's included, who it's for,
  printing notes, instant download. Append the existing AI disclosure unchanged.
- ALT TEXTS: one concise alt text per image kind provided.
- FAQ: 3-4 short Q&A pairs (delivery, printing, sizes, personal use).
- NEVER claim editable/customizable/fillable/Canva — these are flat printables.
- NEVER use trademarked names or logos.

Return JSON only:
{"title": "...", "description": "...", "alt_texts": ["..."], "faq": "Q: ...\\nA: ..."}"""


def _normalize_keyword(keyword: str) -> str:
    return re.sub(r"\s+", " ", keyword.lower().strip())


def is_buried(rank: int | None, min_rank: int = DEFAULT_MIN_RANK) -> bool:
    """True if rank is unknown or worse than min_rank."""
    return rank is None or rank > min_rank


def listing_target_keyword(product_id: int, listing_id: int) -> str | None:
    """Best target keyword for a listing: stored primary > derived from title."""
    from ..learning.rank_tracker import derive_keyword

    kw = db.primary_keyword_for(listing_id)
    if kw:
        return kw
    return derive_keyword(product_id)


def find_buried_listings(min_rank: int = DEFAULT_MIN_RANK,
                         min_demand: float = DEFAULT_MIN_DEMAND,
                         min_results: int = 20) -> list[dict]:
    """Return live listings that are buried but have proven demand.

    Each item includes latest rank snapshot + fresh market_intel demand signals.
    """
    candidates = []
    for row in db.latest_ranks():
        rank = row.get("rank")
        if not is_buried(rank, min_rank):
            continue
        keyword = row.get("keyword") or ""
        intel = market_intel(keyword, sample=MAX_SAMPLE) or {}
        demand = intel.get("demand_score", 0.0) or 0.0
        count = intel.get("count", 0) or 0
        if demand < min_demand or count < min_results:
            continue
        candidates.append({
            "product_id": row.get("product_id"),
            "etsy_listing_id": row.get("etsy_listing_id"),
            "bundle_type": row.get("bundle_type"),
            "listing_title": row.get("listing_title"),
            "keyword": keyword,
            "rank": rank,
            "total_results": row.get("total_results"),
            "demand_score": demand,
            "avg_daily_views": intel.get("avg_daily_views", 0),
            "median_price": intel.get("median_price"),
            "archetype": intel.get("archetype", "planner"),
            "top_tags": intel.get("top_tags", []),
        })
    candidates.sort(key=lambda x: x["demand_score"], reverse=True)
    return candidates


def _build_keyword_research(product: dict, keyword: str, intel: dict) -> dict:
    """Assemble a keyword-research-shaped dict from market intelligence."""
    archetype = intel.get("archetype", "planner")
    items = [b.name for b in db.bundle_items_for(product["id"])]
    long_tail = [t for t in (intel.get("top_tags") or []) if " " in t]
    product_types = ["printable planner kit", "planner pages"] if archetype == "planner" \
        else ["digital print", "wall art print", "printable art"]
    return {
        "primary_keyword": keyword,
        "product_type_terms": product_types,
        "long_tail": long_tail,
        "occasions": [],
        "recipients": [],
        "solutions": [],
        "styles": [],
        "formats": ["instant download", "pdf printable", "print at home"],
        "title_keywords": [keyword],
        "included_items": items,
        "bundle_type": product.get("bundle_type", ""),
    }


def build_optimized_listing(product_id: int,
                            keyword: str | None = None) -> dict | None:
    """Generate a new title/tags/description for a buried listing.

    Returns a dict with old/new copy and metadata. Does NOT touch Etsy.
    """
    el = db.get_etsy_listing(product_id)
    if not el:
        print(f"[optimize] product {product_id} has no Etsy listing")
        return None

    product = db.provenance(product_id)
    if not product:
        product = next((p for p in db.products_with_items() if p["id"] == product_id), None)
    if not product:
        print(f"[optimize] product {product_id} not found")
        return None
    # Normalize: provenance uses 'product_id', products_with_items uses 'id'.
    if "product_id" in product and "id" not in product:
        product["id"] = product["product_id"]

    listing_id = el["etsy_listing_id"]
    keyword = keyword or listing_target_keyword(product_id, listing_id)
    if not keyword:
        print(f"[optimize] product {product_id}: no target keyword")
        return None

    old_listing = db.get_listing(product_id) or {}
    old_title = old_listing.get("title", "")
    old_tags = json.loads(old_listing.get("tags") or "[]")
    old_desc = old_listing.get("description", "")

    intel = market_intel(keyword, sample=MAX_SAMPLE) or {}
    kw_research = _build_keyword_research(product, keyword, intel)
    new_tags = build_tags(kw_research, real_tags=intel.get("top_tags"))

    # Preserve AI disclosure from old description if present.
    disclosure_marker = "Disclosed in line with Etsy's policy on AI-assisted content."
    old_disclosure = ""
    if disclosure_marker in old_desc:
        old_disclosure = old_desc[old_desc.find("Please note:"):]

    mockup_kinds = [m["kind"] for m in db.mockups_for_product(product_id)]
    payload = {
        "target_keyword": keyword,
        "bundle_type": product.get("bundle_type", ""),
        "included_items": kw_research["included_items"],
        "current_title": old_title,
        "suggested_tags": new_tags,
        "archetype": intel.get("archetype", "planner"),
        "image_kinds_needing_alt_text": mockup_kinds or ["hero"],
    }
    copy = complete_json(OPTIMIZE_SYSTEM, json.dumps(payload, ensure_ascii=False))

    new_title = sanitize_title((copy.get("title") or old_title).strip())[:140]
    new_desc = (copy.get("description", "") or old_desc).rstrip()
    if old_disclosure and old_disclosure not in new_desc:
        new_desc += "\n\n" + old_disclosure

    return {
        "product_id": product_id,
        "etsy_listing_id": listing_id,
        "keyword": keyword,
        "old_title": old_title,
        "new_title": new_title,
        "old_tags": old_tags,
        "new_tags": new_tags,
        "old_description": old_desc,
        "new_description": new_desc,
        "market_intel": intel,
        "alt_texts": copy.get("alt_texts", []),
        "faq": copy.get("faq", ""),
    }


def apply_to_etsy(product_id: int, optimized: dict | None = None) -> dict:
    """Update the live Etsy listing with optimized copy."""
    if optimized is None:
        optimized = build_optimized_listing(product_id)
    if not optimized:
        raise RuntimeError(f"product {product_id}: no optimization available")

    listing_id = optimized["etsy_listing_id"]
    shop_id = resolve_shop_id()

    body = {
        "title": optimized["new_title"],
        "description": optimized["new_description"],
        "tags": optimized["new_tags"],
    }
    ec.request("PATCH", f"/shops/{shop_id}/listings/{listing_id}", json=body)

    # Update local DB
    db.upsert_listing(Listing(
        product_id=product_id,
        title=optimized["new_title"],
        tags=json.dumps(optimized["new_tags"]),
        description=optimized["new_description"],
        alt_texts=json.dumps(optimized.get("alt_texts", [])),
        faq=optimized.get("faq", ""),
    ))

    # Audit trail
    try:
        from ..history import record_optimization
        record_optimization(product_id, optimized)
    except Exception as e:
        print(f"[optimize] history record skipped: {e}")

    print(f"[optimize] applied #{product_id} listing {listing_id}: "
          f"'{optimized['new_title'][:60]}...'")
    return optimized


def suggest(min_rank: int = DEFAULT_MIN_RANK,
            min_demand: float = DEFAULT_MIN_DEMAND) -> list[dict]:
    """Find and return buried-listing candidates without applying changes."""
    candidates = find_buried_listings(min_rank=min_rank, min_demand=min_demand)
    return candidates


def optimize_product(product_id: int, dry_run: bool = True,
                     keyword: str | None = None) -> dict | None:
    """Build (and optionally apply) an optimization for one product."""
    optimized = build_optimized_listing(product_id, keyword=keyword)
    if not optimized:
        return None
    if dry_run:
        print(f"[optimize/dry-run] #{product_id}")
        print(f"  keyword : {optimized['keyword']}")
        print(f"  old     : {optimized['old_title']}")
        print(f"  new     : {optimized['new_title']}")
        print(f"  tags    : {', '.join(optimized['new_tags'])}")
        return optimized
    return apply_to_etsy(product_id, optimized)
