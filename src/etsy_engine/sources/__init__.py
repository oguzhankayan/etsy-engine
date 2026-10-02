"""Trend sources (Agent 1 — Trend Hunter).

Each source implements BaseSource.fetch() and returns Trend objects. Add a new
source by subclassing BaseSource and registering it in ENABLED_SOURCES.
"""
from __future__ import annotations

from .base import BaseSource
from .etsy_suggest import EtsySuggestSource
from .etsy_velocity import EtsyVelocitySource
from .events import EventCalendarSource
from .google_trends import GoogleTrendsSource
from .product_ideas import ProductIdeasSource
from .reddit import RedditSource
from .x_trends import XTrendsSource

# Twitter/X is implemented but disabled until API access is sorted (see twitter.py).
ENABLED_SOURCES: dict[str, type[BaseSource]] = {
    "reddit": RedditSource,
    "etsy": EtsySuggestSource,
    "google": GoogleTrendsSource,
    "ideas": ProductIdeasSource,
    # Our own Etsy bestseller radar: real rising-demand seeds (favorites/views
    # velocity) — replaces guessing with what's actually climbing right now.
    "velocity": EtsyVelocitySource,
    # Scheduled cultural/sports moments, emitted during the buyer prep window.
    # Born from the data: the World Cup bundle is the shop's top performer.
    "events": EventCalendarSource,
    # X (Twitter) via Grok's native x_search through OpenRouter — real-time social demand.
    # Additive Line-A source; its trends run the SAME funnel + EV gate as every other source.
    "x": XTrendsSource,
}

__all__ = ["ENABLED_SOURCES", "BaseSource"]
