"""Twitter/X source — DISABLED until API access is sorted.

X's free tier is insufficient for trend reading and Basic is ~$100/mo. This stub
keeps the interface ready: once you have a bearer token, implement fetch() with
the v2 recent-search / trends endpoint and add "twitter" to ENABLED_SOURCES in
sources/__init__.py. No other code needs to change.
"""
from __future__ import annotations

from ..models import Trend
from .base import BaseSource


class TwitterSource(BaseSource):
    name = "twitter"

    def fetch(self, limit: int) -> list[Trend]:
        raise NotImplementedError(
            "Twitter/X source not enabled yet — resolve API access, then implement."
        )
