"""Etsy search-suggestions source. Direct purchase intent ("what buyers type").

REVIVED 2026-07-02: the old suggestions_ajax.php endpoint is DataDome-captcha'd,
but the site frontend's public autosuggest API returns clean JSON with no auth:
GET https://www.etsy.com/api/v3/ajax/public/search/autosuggest?query=<stem>
-> [{"query": "teacher shirt"}, ...]. If it ever regresses to 403, fetch()
fails soft and returns nothing — we do NOT substitute another site's data.
"""
from __future__ import annotations

import json

import requests

from ..models import Tier, Trend
from .base import BaseSource

SUGGEST_URL = "https://www.etsy.com/api/v3/ajax/public/search/autosuggest"

# Purchase-intent seed stems. Autosuggest expands each into real buyer queries, so the STEMS decide
# which market we hear. The originals are almost all fill-in/print PDF (planner/checklist/tracker/
# worksheet/coloring...) — that PDF bias is one reason the Canva line starved on the reliable source
# (google, which carries the personalizable pool, is frequently 429'd). The second group seeds the
# swap-my-name editable market (weddings/showers/invitations/signs/memorials) through THIS source too.
DEFAULT_SEEDS = [
    "printable", "planner", "checklist", "reward chart", "wall art bundle",
    "worksheet", "tracker", "certificate", "flashcards", "coloring",
    # personalizable (Canva-line) stems
    "wedding invitation", "baby shower invitation", "birthday invitation",
    "welcome sign", "funeral program", "wedding menu", "save the date", "gender reveal",
]


class EtsySuggestSource(BaseSource):
    name = "etsy"

    def __init__(self, seeds: list[str] | None = None):
        self.seeds = seeds or DEFAULT_SEEDS

    def fetch(self, limit: int) -> list[Trend]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
        }
        trends: list[Trend] = []
        seen: set[str] = set()
        for seed in self.seeds:
            try:
                resp = requests.get(
                    SUGGEST_URL, params={"query": seed},
                    headers=headers, timeout=10,
                )
                resp.raise_for_status()
                for item in self._parse(resp):
                    key = item.lower().strip()
                    if key and key not in seen:
                        seen.add(key)
                        trends.append(Trend(
                            source=self.name, term=item,
                            raw_payload=json.dumps({"seed": seed}),
                            tier=Tier.EVERGREEN,
                        ))
            except Exception as e:
                print(f"[etsy] seed '{seed}' failed: {e}")
        return trends[:limit]

    @staticmethod
    def _parse(resp: requests.Response) -> list[str]:
        try:
            data = resp.json()
        except ValueError:
            return []
        out = []
        for el in data if isinstance(data, list) else []:
            if isinstance(el, str):
                out.append(el)
            elif isinstance(el, dict):
                out.append(el.get("query") or el.get("value") or "")
        return [x for x in out if x]
