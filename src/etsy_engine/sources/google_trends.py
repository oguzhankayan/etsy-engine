"""Google Trends source (pytrends, unofficial). Rising searches.

pytrends has no official support and is rate-limited; we keep requests small and
fail soft. We pull 'rising' related queries for a few broad seeds plus daily
trending searches.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import requests

from ..models import Tier, Trend
from .base import BaseSource
from .seeds import discovery_seeds

# pytrends is slow + rate-limited, so we sample a capped number of seeds per run.
# Seasonal + dynamic seeds rotate the coverage over time; daily RSS adds breadth.
MAX_SEEDS_PER_RUN = 14

# Modern replacement for the dead pytrends.trending_searches: the Google Trends
# daily RSS feed (still live). Carries an approx_traffic signal per term.
RSS_URL = "https://trends.google.com/trending/rss"
HT_NS = "{https://trends.google.com/trending/rss}"


class GoogleTrendsSource(BaseSource):
    name = "google"

    def __init__(self, seeds: list[str] | None = None, geo: str = "US"):
        # None -> dynamic (evergreen + seasonal + learned), resolved at fetch time.
        self.seeds = seeds
        self.geo = geo

    def _daily_trending(self) -> list[Trend]:
        """Today's trending searches from the Google Trends RSS feed, across geos
        (catches global/regional viral events, not just US)."""
        from ..config import settings

        geos = [g.strip() for g in (settings.trend_geos or self.geo).split(",") if g.strip()]
        out: list[Trend] = []
        seen: set[str] = set()
        for geo in geos:
            try:
                resp = requests.get(
                    RSS_URL, params={"geo": geo},
                    headers={"User-Agent": "Mozilla/5.0"}, timeout=15,
                )
                resp.raise_for_status()
                root = ET.fromstring(resp.content)
            except Exception as e:
                print(f"[google] daily RSS {geo} failed: {e}")
                continue
            for item in root.iter("item"):
                title = (item.findtext("title") or "").strip()
                if not title or title.lower() in seen:
                    continue
                seen.add(title.lower())
                traffic = item.findtext(f"{HT_NS}approx_traffic") or ""
                out.append(Trend(
                    source=self.name, term=title,
                    raw_payload=json.dumps({
                        "kind": "daily", "approx_traffic": traffic, "geo": geo}),
                    tier=Tier.VIRAL,
                ))
        return out

    def fetch(self, limit: int) -> list[Trend]:
        from pytrends.request import TrendReq  # local import

        pytrends = TrendReq(hl="en-US", tz=0)
        trends: list[Trend] = []
        seen: set[str] = set()

        # 1) Daily trending searches via the live RSS feed (broad, viral)
        for t in self._daily_trending():
            if t.term not in seen:
                seen.add(t.term)
                trends.append(t)

        # 2) Rising related queries for each seed (captures the rise % = velocity)
        seeds = self.seeds or discovery_seeds(MAX_SEEDS_PER_RUN)
        for seed in seeds:
            try:
                pytrends.build_payload([seed], timeframe="now 7-d", geo=self.geo)
                rising = pytrends.related_queries().get(seed, {}).get("rising")
                if rising is None:
                    continue
                for _, row in rising.iterrows():
                    term = str(row["query"]).strip()
                    if term and term not in seen:
                        seen.add(term)
                        trends.append(Trend(
                            source=self.name, term=term,
                            raw_payload=json.dumps({
                                "seed": seed, "kind": "rising",
                                "rise_value": str(row.get("value", "")),  # %% or "Breakout"
                            }),
                            tier=Tier.SEASONAL,
                        ))
            except Exception as e:
                print(f"[google] seed '{seed}' failed: {e}")

        return trends[:limit]
