"""Keyword pulse — TRUE current demand velocity from view deltas.

Why: `market_intel.avg_daily_views` divides a listing's LIFETIME views by its
age — an old bestseller reads hot even if it's dead today, and single-snapshot
medians swing with sample composition (observed: world cup 7.2 → 17.6 → 12.8
within hours). The fix is a time series: snapshot the top listings' raw view
counters daily, then diff the SAME listing across snapshots:

    current_daily_views(listing) = (views_t2 - views_t1) / days_between

The median of those per-listing deltas is the keyword's real current pulse —
a signal even paid tools don't expose. Needs ≥2 snapshots ≥6h apart; the daily
automation run builds history automatically.

Tracked set = own listings' primary keywords + top validated candidates +
data/keyword_watchlist.json (manual adds). Bounded (~1 API call/keyword/day).
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime
from urllib.parse import quote

from .. import db
from ..config import DATA_DIR
from ..publish import etsy_client as ec

WATCHLIST_FILE = DATA_DIR / "keyword_watchlist.json"
TOP_LISTINGS = 20
MAX_TRACKED = 40          # hard cap on daily API spend
MIN_HOURS_BETWEEN = 6.0   # deltas over shorter gaps are noise


def tracked_keywords() -> list[str]:
    """Own primary keywords + top validated candidates + manual watchlist."""
    out: list[str] = []
    seen: set[str] = set()

    def add(k: str) -> None:
        k = (k or "").strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(k)

    if WATCHLIST_FILE.exists():
        try:
            for k in json.loads(WATCHLIST_FILE.read_text()):
                add(k)
        except (ValueError, OSError):
            pass
    for r in db.all_listing_keywords():
        if r.get("is_primary"):
            add(r["keyword"])
    for o in db.top_opportunities(limit=15):
        add(o["term"])
    return out[:MAX_TRACKED]


def snapshot(keywords: list[str] | None = None) -> int:
    """Record today's view/fav counters for each keyword's top listings."""
    keywords = keywords or tracked_keywords()
    done = 0
    for kw in keywords:
        try:
            data = ec.app_request(
                "GET",
                f"/listings/active?keywords={quote(kw)}&limit={TOP_LISTINGS}"
                "&sort_on=score")
        except Exception as e:
            print(f"[pulse] '{kw}' failed: {e}")
            continue
        rows = [
            (int(r["listing_id"]), int(r.get("views") or 0),
             int(r.get("num_favorers") or 0))
            for r in (data.get("results") or [])
        ]
        if rows:
            db.insert_pulse_rows(kw, rows)
            done += 1
    print(f"[pulse] snapshotted {done}/{len(keywords)} keywords")
    return done


def velocity(keyword: str) -> dict | None:
    """Current demand velocity for a keyword from its last two snapshots.
    Returns None until two snapshots ≥MIN_HOURS_BETWEEN apart exist."""
    batches = db.pulse_snapshots(keyword, last_n_captures=2)
    if len(batches) < 2:
        return None
    t1 = datetime.fromisoformat(batches[0][0]["captured_at"])
    t2 = datetime.fromisoformat(batches[1][0]["captured_at"])
    hours = (t2 - t1).total_seconds() / 3600
    if hours < MIN_HOURS_BETWEEN:
        return None
    days = hours / 24
    prev = {r["listing_id"]: r for r in batches[0]}
    deltas_v, deltas_f = [], []
    for r in batches[1]:
        p = prev.get(r["listing_id"])
        if not p:
            continue  # listing entered the top set between snapshots
        deltas_v.append(max(0, r["views"] - p["views"]) / days)
        deltas_f.append(max(0, r["favorites"] - p["favorites"]) / days)
    if not deltas_v:
        return None
    return {
        "keyword": keyword,
        "matched_listings": len(deltas_v),
        "hours_span": round(hours, 1),
        "median_daily_views_now": round(statistics.median(deltas_v), 2),
        "total_daily_views_now": round(sum(deltas_v), 1),
        "median_daily_favs_now": round(statistics.median(deltas_f), 3),
    }


def report() -> list[dict]:
    """Velocity for every keyword with enough history, hottest first."""
    out = []
    for kw in db.pulse_keywords():
        v = velocity(kw)
        if v:
            out.append(v)
    out.sort(key=lambda r: r["total_daily_views_now"], reverse=True)
    for r in out:
        print(f"[pulse] {r['keyword'][:34]:34} now~{r['median_daily_views_now']:>7} "
              f"views/day/listing  total~{r['total_daily_views_now']:>8}/day "
              f"({r['matched_listings']} listings, {r['hours_span']}h span)")
    if not out:
        print("[pulse] need two snapshots >=6h apart — run `keyword-track` daily")
    return out
