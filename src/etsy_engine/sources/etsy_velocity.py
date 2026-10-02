"""Etsy velocity radar — our own bestseller feed (no third-party dependency).

Implements the operator workflow ("find what's actually rising, make a legal
look-alike, list it") using Etsy's own public API instead of a paid tool. For
each target category we read the top-ranking active listings and rank them by
demand VELOCITY:

    favs_per_day  = num_favorers / listing_age_days
    views_per_day = views        / listing_age_days

Honest limitation: Etsy's public API exposes views + favorites, NOT competitors'
sales counts, so velocity is a purchase-intent proxy (favorites is the strongest
public signal), not literal sales. The fastest risers become scored trend seeds;
downstream `validate` still confirms competition/beatability before we spend
image credits, and `history.is_duplicate` stops us re-making a theme we sell.

App-only auth (x-api-key), no OAuth — same access path as scoring/etsy_market.
"""
from __future__ import annotations

import json
import re
import time
from urllib.parse import quote

from ..models import Tier, Trend
from ..publish import etsy_client as ec
from .base import BaseSource

# Broad queries standing in for our digital-only, high-demand categories.
# Kept generic so the RISERS inside them surface. The full pool covers more
# corners of the printable market than one run can afford to scan, so each run
# rotates through CATEGORIES_PER_RUN of them (persistent round-robin state) —
# over ~3 runs the whole pool gets swept.
CATEGORY_POOL = [
    # original core set
    "digital print wall art",
    "printable wall art",
    "printable stickers",
    "printable planner",
    "printable greeting card",
    "coloring book printable",
    # widened coverage (still all flat-printable, pipeline-compatible)
    "printable party games",
    "kids printable activities",
    "printable invitation",
    "printable journal pages",
    "junk journal printable",
    "digital collage sheet",
    "printable flashcards",
    "printable gift tags",
    "printable party signs",  # banner/garland class is BANNED (owner 2026-07-02)
    "nursery printable art",
    "teacher classroom printable",
    "printable calendar 2027",
]
CATEGORIES_PER_RUN = 6

# Backwards-compat alias (tests/docs referenced the old name).
CATEGORY_QUERIES = CATEGORY_POOL[:6]

# Noise floors: ignore listings too new/too cold to trust the velocity number.
MIN_FAVORERS = 8
MIN_AGE_DAYS = 2.0
PER_CATEGORY = 6          # top movers to keep per category
SAMPLE = 100              # listings pulled per category (Etsy caps at 100)


def _clean_term(title: str) -> str:
    """Reduce an SEO title to a short theme phrase (the product concept), so the
    architect designs an ORIGINAL look-alike rather than cloning a listing."""
    # First clause only — Etsy titles pack keywords after a pipe/comma/dash.
    head = re.split(r"[|,–—:]", title, maxsplit=1)[0]
    # Drop leading quantity/format noise ("300 pages!", "set of 12", "250 ...").
    # \b after \d+ keeps ordinals intact ("4th of July" must NOT become "th of
    # July" — that bug shipped a mangled trend term on 2026-07-02).
    head = re.sub(r"^\s*(set of\s*)?\d+\b\s*(pages?|pack|piece|pcs|designs?)?!?\s*",
                  "", head, flags=re.I)
    head = re.sub(r"\b(printable|instant download|pdf|digital download|bundle)\b",
                  "", head, flags=re.I)
    return " ".join(head.split()).strip(" -,.").lower()[:70]


class EtsyVelocitySource(BaseSource):
    name = "velocity"

    def __init__(self, categories: list[str] | None = None):
        # Explicit categories pin the scan; otherwise rotate through the pool
        # so successive runs sweep different corners of the printable market.
        if categories is None:
            from .seeds import _rotating_selection
            categories = _rotating_selection(
                {"velocity_categories": CATEGORY_POOL},
                ("velocity_categories",), CATEGORIES_PER_RUN)
        self.categories = categories

    def _movers(self, keyword: str) -> list[Trend]:
        try:
            data = ec.app_request(
                "GET",
                f"/listings/active?keywords={quote(keyword)}"
                f"&limit={SAMPLE}&sort_on=score",
            )
        except Exception as e:  # one bad category shouldn't kill the run
            print(f"[velocity] '{keyword}' failed: {e}")
            return []

        now_ts = time.time()
        scored: list[tuple[float, Trend]] = []
        for r in data.get("results", []) or []:
            favs = int(r.get("num_favorers") or 0)
            views = int(r.get("views") or 0)
            created = int(r.get("original_creation_timestamp") or 0)
            if favs < MIN_FAVORERS or not created:
                continue
            age_days = max(MIN_AGE_DAYS, (now_ts - created) / 86400)
            favs_per_day = round(favs / age_days, 3)
            views_per_day = round(views / age_days, 2)
            term = _clean_term(r.get("title", ""))
            if not term:
                continue
            payload = json.dumps({
                "kind": "velocity",
                "category": keyword,
                "favs_per_day": favs_per_day,
                "views_per_day": views_per_day,
                "favorers": favs,
                "views": views,
                "age_days": round(age_days, 1),
                "shop_id": r.get("shop_id"),
                "tags": (r.get("tags") or [])[:5],
            })
            scored.append((favs_per_day, Trend(
                source=self.name, term=term, raw_payload=payload,
                tier=Tier.VIRAL,
            )))

        scored.sort(key=lambda t: t[0], reverse=True)
        return [t for _, t in scored[:PER_CATEGORY]]

    def fetch(self, limit: int) -> list[Trend]:
        out: list[Trend] = []
        seen: set[str] = set()
        for cat in self.categories:
            for tr in self._movers(cat):
                key = tr.term.lower()
                if key and key not in seen:
                    seen.add(key)
                    out.append(tr)
        return out[:limit]
