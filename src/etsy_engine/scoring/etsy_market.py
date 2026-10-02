"""Etsy market validation + market intelligence.

Turns Etsy's own search into REAL signals, replacing the LLM's guesses. For a
keyword we read the top active listings (the same data eRank surfaces, but pulled
straight from the Etsy API — unlimited, no 5-search cap):
- result count             -> competition (fewer = better, log-scaled)
- top listings' favorites  -> demand proxy (log-scaled)
- views / listing age      -> avg daily views (true demand, like eRank)
- listing ages             -> beatability (newer top results = winnable)
- top listings' tags       -> real winning tags (frequency-ranked) for SEO
- top listings' taxonomy   -> dominant category -> product ARCHETYPE (planner vs print)
- top listings' price      -> niche median price

eRank's only edge over this is internal search VOLUME + keyword-difficulty; we use
it as a manual cross-check for high-stakes calls. Everything else is computed here.

Uses app-only auth (x-api-key), no OAuth needed.
"""
from __future__ import annotations

import json
import math
import statistics
import time
from collections import Counter
from urllib.parse import quote

from ..config import DATA_DIR
from ..publish import etsy_client as ec

# Category-path keywords that imply each product archetype. Used to read the
# dominant FORMAT of a niche (what actually sells) from top listings' taxonomy.
PRINT_CATEGORY_HINTS = (
    "digital prints", "drawing & illustration", "wall decor", "prints",
    "clip art", "collage sheets", "digital", "illustration", "wall art",
)
PLANNER_CATEGORY_HINTS = (
    "calendars & planners", "paper & party", "stationery", "journals",
    "notebooks", "planner", "paper",
)


def _competition_score(count: int) -> float:
    """Fewer competing listings = higher score. ~0 listings->1.0, ~100k->0.0."""
    return max(0.0, min(1.0, 1.0 - math.log10(count + 1) / 5.0))


def _demand_score(avg_favorites: float) -> float:
    """More favorites on top listings = more proven demand. log-scaled to [0,1]."""
    return max(0.0, min(1.0, math.log10(avg_favorites + 1) / 3.0))


# Keyword-keyed caches so a niche's Etsy data is fetched ONCE per run/batch, not re-fetched by
# every caller (architect market_signal + the validate stage + repeat products all hit these).
_TITLES_CACHE: dict[tuple, list] = {}
_INTEL_CACHE: dict[tuple, dict | None] = {}


def top_listing_titles(keyword: str, n: int = 12) -> list[str]:
    """Cached facade over the Etsy fetch (see `_top_listing_titles_uncached`)."""
    key = (keyword.lower().strip(), n)
    if key not in _TITLES_CACHE:
        _TITLES_CACHE[key] = _top_listing_titles_uncached(keyword, n)
    return _TITLES_CACHE[key]


def _top_listing_titles_uncached(keyword: str, n: int = 12) -> list[str]:
    """Titles of the best-ranking active listings for a keyword (text only).

    Used to inform bundle design with what's proven to sell — structure/components/
    positioning — NOT to copy. We read only public titles, never images.
    """
    try:
        data = ec.app_request(
            "GET",
            f"/listings/active?keywords={quote(keyword)}&limit={n}&sort_on=score",
        )
    except Exception as e:
        print(f"[market] titles '{keyword}' failed: {e}")
        return []
    return [r.get("title", "") for r in (data.get("results") or []) if r.get("title")]


def market_signal(keyword: str, sample: int = 25) -> dict | None:
    """Return real Etsy market data for a keyword, or None on failure."""
    try:
        data = ec.app_request(
            "GET",
            f"/listings/active?keywords={quote(keyword)}&limit={sample}&sort_on=score",
        )
    except Exception as e:
        print(f"[market] '{keyword}' failed: {e}")
        return None
    count = int(data.get("count", 0) or 0)
    results = data.get("results", []) or []
    favs = [int(r.get("num_favorers", 0) or 0) for r in results]
    avg_fav = sum(favs) / len(favs) if favs else 0.0
    return {
        "count": count,
        "avg_favorites": round(avg_fav, 1),
        "competition_score": round(_competition_score(count), 4),
        "demand_score": round(_demand_score(avg_fav), 4),
    }


# --- Market intelligence (rich, eRank-equivalent signals) ---

_TAXO_CACHE = DATA_DIR / "etsy_taxonomy_map.json"


def _taxonomy_map() -> dict[str, str]:
    """id(str) -> full category path name, e.g. '954' -> 'Art & Collectibles >
    Prints > Digital Prints'. Cached to disk; one API call to build."""
    if _TAXO_CACHE.exists():
        try:
            return json.loads(_TAXO_CACHE.read_text())
        except (ValueError, OSError):
            pass
    try:
        data = ec.app_request("GET", "/seller-taxonomy/nodes")
    except Exception as e:
        print(f"[market] taxonomy fetch failed: {e}")
        return {}

    # The tree is nested: each node carries a `children` list. Flatten ALL nodes
    # (top-level nodes only would leave deep leaves like "Digital Prints" unresolved).
    flat: list[dict] = []

    def _walk(nodes: list[dict]) -> None:
        for n in nodes:
            flat.append(n)
            _walk(n.get("children") or [])

    _walk(data.get("results", []) or [])
    name_by_id = {str(n["id"]): n.get("name", "") for n in flat}
    path_by_id: dict[str, str] = {}
    for n in flat:
        ids = n.get("full_path_taxonomy_ids") or [n["id"]]
        path_by_id[str(n["id"])] = " > ".join(
            name_by_id.get(str(i), "") for i in ids
        ).strip(" >")
    try:
        _TAXO_CACHE.write_text(json.dumps(path_by_id, ensure_ascii=False))
    except OSError:
        pass
    return path_by_id


def _price_usd(price: dict | None) -> float | None:
    try:
        return round(price["amount"] / price["divisor"], 2)
    except (TypeError, KeyError, ZeroDivisionError):
        return None


# Emerging-niche detection (Bahattin: a small shop climbing fast = winnable).
SMALL_SHOP_MAX = 60      # active listings — a "small shop" ceiling
EMERGING_MIN_FPD = 0.5   # favorites/day to count as "climbing"
EMERGING_MAX_AGE = 200   # days — the riser must be recent, not an old bestseller
_SHOP_SIZE_CACHE_FILE = DATA_DIR / "etsy_shop_sizes.json"
_SHOP_SIZE_CACHE: dict[str, int] | None = None


def _shop_active_count(shop_id) -> int | None:
    """Active-listing count for a shop, cached to disk (bounded API cost)."""
    global _SHOP_SIZE_CACHE
    if shop_id is None:
        return None
    if _SHOP_SIZE_CACHE is None:
        try:
            _SHOP_SIZE_CACHE = json.loads(_SHOP_SIZE_CACHE_FILE.read_text())
        except (OSError, ValueError):
            _SHOP_SIZE_CACHE = {}
    key = str(shop_id)
    if key in _SHOP_SIZE_CACHE:
        return _SHOP_SIZE_CACHE[key]
    try:
        data = ec.app_request("GET", f"/shops/{key}")
        count = int(data.get("listing_active_count") or 0)
    except Exception:
        return None
    _SHOP_SIZE_CACHE[key] = count
    try:
        _SHOP_SIZE_CACHE_FILE.write_text(json.dumps(_SHOP_SIZE_CACHE))
    except OSError:
        pass
    return count


def _emerging_niche(rows: list[dict], now_ts: float, max_lookups: int = 8) -> tuple[float, int]:
    """Detect small-shop fast-risers among a keyword's top listings.

    Returns (score 0..1, emerging_shop_count). Only the highest-velocity listings
    are shop-size-checked, to bound API calls. A niche where several small shops
    are climbing is one a new entrant can still win.
    """
    ranked = sorted(rows, key=lambda r: r["fpd"], reverse=True)[:max_lookups]
    emerging = 0
    for r in ranked:
        if r["fpd"] < EMERGING_MIN_FPD or r["age_days"] > EMERGING_MAX_AGE:
            continue
        size = _shop_active_count(r["shop_id"])
        if size is not None and size <= SMALL_SHOP_MAX:
            emerging += 1
    score = round(min(1.0, emerging / 3.0), 3)  # 3+ small-shop risers = strong
    return score, emerging


def classify_archetype(category_paths: list[str]) -> tuple[str, float]:
    """Infer the dominant product FORMAT of a niche from top listings' categories.

    Returns (archetype, confidence) where archetype is 'print' (cheap single-image
    art/PNG/wall art) or 'planner' (multi-page printable kit). Confidence is the
    share of the winning side among categorised listings.
    """
    p = sum(any(h in c.lower() for h in PRINT_CATEGORY_HINTS) for c in category_paths)
    k = sum(any(h in c.lower() for h in PLANNER_CATEGORY_HINTS) for c in category_paths)
    total = p + k
    if total == 0:
        return ("planner", 0.0)  # default to our original archetype when unknown
    if p >= k:
        return ("print", round(p / total, 2))
    return ("planner", round(k / total, 2))


def market_intel(keyword: str, sample: int = 100) -> dict | None:
    """Cached facade over the Etsy market fetch (see `_market_intel_uncached`)."""
    key = (keyword.lower().strip(), sample)
    if key not in _INTEL_CACHE:
        _INTEL_CACHE[key] = _market_intel_uncached(keyword, sample)
    return _INTEL_CACHE[key]


def _market_intel_uncached(keyword: str, sample: int = 100) -> dict | None:
    """Rich market intelligence for a keyword, computed from the Etsy API.

    Mirrors what eRank's Keyword Tool shows (minus internal search volume):
    competition, avg daily views, beatability, top tags, dominant category,
    recommended archetype, and median price.
    """
    try:
        data = ec.app_request(
            "GET",
            f"/listings/active?keywords={quote(keyword)}&limit={min(sample, 100)}"
            "&sort_on=score",
        )
    except Exception as e:
        print(f"[market] intel '{keyword}' failed: {e}")
        return None

    count = int(data.get("count", 0) or 0)
    results = data.get("results", []) or []
    if not results:
        return {"keyword": keyword, "count": count, "analyzed": 0}

    taxo = _taxonomy_map()
    now_ts = time.time()
    tag_counter: Counter[str] = Counter()
    cat_paths: list[str] = []
    cat_counter: Counter[str] = Counter()
    prices, ages, favs, views_l = [], [], [], []
    listing_rows: list[dict] = []  # per-listing, for emerging-niche detection

    for r in results:
        for t in (r.get("tags") or []):
            tag_counter[t.strip().lower()] += 1
        tid = str(r.get("taxonomy_id") or "")
        path = taxo.get(tid, "")
        if path:
            cat_paths.append(path)
            cat_counter[path] += 1
        pr = _price_usd(r.get("price"))
        if pr is not None:
            prices.append(pr)
        rv = int(r.get("views") or 0)
        rf = int(r.get("num_favorers") or 0)
        views_l.append(rv)
        favs.append(rf)
        created = int(r.get("original_creation_timestamp") or 0)
        if created:
            age_days = max(1.0, (now_ts - created) / 86400)
            ages.append(age_days)
            listing_rows.append({
                "fpd": rf / age_days, "age_days": age_days,
                "shop_id": r.get("shop_id"),
            })

    n = len(results)
    # Use MEDIANS (not means) for demand — a few viral listings massively skew the
    # mean (world cup mean views ~1176 vs median ~tens). Median views / median age
    # tracks eRank's "Avg Daily Views" closely and is robust to outliers.
    avg_views = sum(views_l) / len(views_l) if views_l else 0.0
    median_views = statistics.median(views_l) if views_l else 0.0
    median_age = round(statistics.median(ages), 0) if ages else None
    avg_daily = round(median_views / median_age, 2) if median_age else 0.0
    fresh_share = round(sum(a <= 365 for a in ages) / len(ages), 2) if ages else 0.0
    archetype, arch_conf = classify_archetype(cat_paths)
    emerging_niche, emerging_shops = _emerging_niche(listing_rows, now_ts)

    result = {
        "keyword": keyword,
        "count": count,                       # competition (total listings)
        "analyzed": n,
        "competition_score": round(_competition_score(count), 4),
        "avg_favorites": round(sum(favs) / n, 1) if favs else 0.0,
        "avg_views": round(avg_views, 1),
        "median_views": round(median_views, 1),
        "avg_daily_views": avg_daily,         # true demand (eRank's headline metric)
        "demand_score": round(_demand_score(avg_daily * 30), 4),  # ~monthly views scale
        "median_price": round(statistics.median(prices), 2) if prices else None,
        "median_age_days": median_age,        # entrenchment
        "fresh_share": fresh_share,           # beatability: share of top <= 1yr old
        "beatability": round(_competition_score(count) * 0.5 + fresh_share * 0.5, 4),
        "emerging_niche": emerging_niche,     # small shops climbing = winnable
        "emerging_shops": emerging_shops,     # how many small-shop risers we saw
        "archetype": archetype,               # 'print' | 'planner'
        "archetype_confidence": arch_conf,
        "top_tags": [t for t, _ in tag_counter.most_common(25)],
        "top_categories": [{"path": c, "share": round(cnt / n, 2)}
                           for c, cnt in cat_counter.most_common(5)],
    }

    # Self-improving product ideas: feed winning niches back
    try:
        from ..product_ideas import feedback_from_intel
        feedback_from_intel(keyword, result)
    except Exception:
        pass

    return result
