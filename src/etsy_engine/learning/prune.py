"""Prune analysis — surface active listings that never earned buyer interest and MARK them for
deactivation (a DB flag; a human deactivates on Etsy). This is the catalog-hygiene counterpart to
the catalog cap: the cap stops NEW dead inventory, prune identifies EXISTING dead inventory.

A listing is "unproven" by the same floors the seed-feedback loop uses (a relative winner in a shop
whose median listing sits at ~2 views): fewer than 20 views AND fewer than 2 favorites. Only
listings at least 30 days old are considered, so a newborn still ramping isn't mistaken for dead —
the shop's apparent "dead" listings were newborns (median 3 days) at the 2026-07-04 audit, which is
exactly why the standing policy was "no prune yet" (§B7). The age floor encodes that lesson.

NON-DESTRUCTIVE by contract: this module never calls the Etsy API. It reads metrics and sets a DB
flag. Nothing is deactivated automatically — the flag is a to-do list for a human.
"""
from __future__ import annotations

import datetime

from .. import db

PRUNE_MIN_VIEWS = 20
PRUNE_MIN_FAVORITES = 2
PRUNE_MIN_AGE_DAYS = 30


def _age_days(created_at: str | None, *, ref: datetime.datetime | None = None) -> float | None:
    """Days since a listing was recorded (its age proxy). None if the timestamp can't be parsed."""
    if not created_at:
        return None
    try:
        dt = datetime.datetime.fromisoformat(created_at)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.UTC)
    ref = ref or datetime.datetime.now(datetime.UTC)
    return (ref - dt).total_seconds() / 86400.0


def find_prunable(min_views: int = PRUNE_MIN_VIEWS, min_favorites: int = PRUNE_MIN_FAVORITES,
                  min_age_days: int = PRUNE_MIN_AGE_DAYS) -> list[dict]:
    """Active listings older than `min_age_days` with fewer than `min_views` views AND fewer than
    `min_favorites` favorites. Each returned row carries its computed `age_days`. Pure read — no
    writes, no API calls."""
    out: list[dict] = []
    for r in db.active_listings_with_metrics():
        age = _age_days(r.get("created_at"))
        if age is None or age < min_age_days:
            continue
        if int(r.get("views") or 0) < min_views and int(r.get("favorites") or 0) < min_favorites:
            out.append({**r, "age_days": round(age, 1)})
    return out


def mark_for_deactivation(listings: list[dict]) -> int:
    """Flag each listing for deactivation in the DB (never touches Etsy). Returns how many were marked."""
    for r in listings:
        db.mark_listing_for_deactivation(r["etsy_listing_id"])
    return len(listings)
