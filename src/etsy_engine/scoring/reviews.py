"""Review mining — buyer voice from top listings' reviews (new signal).

For a niche keyword we pull the text reviews of the best-ranking listings and
have Claude distill them into structured insights: what buyers PRAISE (must
match it), what they COMPLAIN about (our differentiation opening), and the
words buyers naturally use (gold for SEO copy).

Read-only public data via app-only auth; insights are cached to disk per
keyword so repeat runs cost no API/LLM calls for ~30 days.

KNOWN LIMITATION (verified 2026-07-02): with the current app's API access tier
Etsy returns count=0 reviews for ALL third-party listings (both app-only and
OAuth auth), even for listings that visibly have hundreds of reviews on the
site. The whole path therefore fails soft (insights=None, cached) today and
costs ~7 API calls per keyword per 30 days. If/when the app is granted full
API access, review mining starts working with no code change. Do NOT replace
this with page scraping (Etsy ToS).
"""
from __future__ import annotations

import json
import time
from urllib.parse import quote

from ..config import DATA_DIR
from ..publish import etsy_client as ec

_CACHE_FILE = DATA_DIR / "review_insights.json"
CACHE_TTL_DAYS = 30
MAX_REVIEW_TEXTS = 60      # cap what we feed the LLM
MIN_REVIEW_TEXTS = 5       # below this the summary would be noise

SYSTEM = """You are an Etsy market researcher. You are given real buyer reviews
of the TOP-SELLING listings in one product niche. Distill the buyer voice.
Respond with JSON only:
{"praises": ["3-6 things buyers consistently love — a new product MUST match these"],
 "complaints": ["2-5 recurring gripes/wishes — gaps a better product can fill"],
 "buyer_words": ["5-10 short phrases buyers naturally use (for SEO copy), lowercase"],
 "summary": "one sentence: what wins in this niche"}
Only report patterns that appear in the reviews; do not invent."""


def listing_reviews(listing_id: int, limit: int = 25) -> list[dict]:
    """Public reviews for one listing: [{rating, review}]. Empty on any failure."""
    try:
        data = ec.app_request("GET", f"/listings/{listing_id}/reviews?limit={limit}")
    except Exception as e:
        print(f"[reviews] listing {listing_id} failed: {e}")
        return []
    return [
        {"rating": r.get("rating"), "review": (r.get("review") or "").strip()}
        for r in (data.get("results") or [])
        if (r.get("review") or "").strip()
    ]


def _load_cache() -> dict:
    if _CACHE_FILE.exists():
        try:
            return json.loads(_CACHE_FILE.read_text())
        except (ValueError, OSError):
            pass
    return {}


def _save_cache(cache: dict) -> None:
    try:
        _CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=1))
    except OSError:
        pass


def niche_review_insights(keyword: str, n_listings: int = 6) -> dict | None:
    """Buyer-voice insights for a niche keyword, or None when there's too little
    review text to be meaningful. Cached per keyword (CACHE_TTL_DAYS)."""
    key = keyword.strip().lower()
    cache = _load_cache()
    hit = cache.get(key)
    if hit and time.time() - hit.get("ts", 0) < CACHE_TTL_DAYS * 86400:
        return hit.get("insights")

    try:
        data = ec.app_request(
            "GET",
            f"/listings/active?keywords={quote(keyword)}&limit={n_listings}"
            "&sort_on=score",
        )
    except Exception as e:
        print(f"[reviews] search '{keyword}' failed: {e}")
        return None

    texts: list[str] = []
    for r in data.get("results", []) or []:
        for rev in listing_reviews(int(r["listing_id"])):
            texts.append(f"[{rev['rating']}/5] {rev['review'][:300]}")
            if len(texts) >= MAX_REVIEW_TEXTS:
                break
        if len(texts) >= MAX_REVIEW_TEXTS:
            break

    insights = None
    if len(texts) >= MIN_REVIEW_TEXTS:
        from ..llm import complete_json
        try:
            result = complete_json(
                SYSTEM,
                json.dumps({"niche_keyword": keyword, "reviews": texts},
                           ensure_ascii=False),
            )
            if isinstance(result, list):  # tolerate list-wrapped JSON
                result = next((x for x in result if isinstance(x, dict)), None)
            insights = result if isinstance(result, dict) else None
        except Exception as e:
            print(f"[reviews] summarize '{keyword}' failed: {e}")
    else:
        print(f"[reviews] '{keyword}': only {len(texts)} review texts — skipping")

    # Cache even a None result: a reviewless niche stays reviewless for a while,
    # and re-scanning it every run wastes dozens of API calls.
    cache[key] = {"ts": time.time(), "insights": insights}
    _save_cache(cache)
    return insights
