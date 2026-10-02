"""X (Twitter) trend source via Grok's native x_search, through OpenRouter.

Additive Line-A collector. Like every other source it emits `Trend` records that flow into the
normal funnel unchanged — collect -> score (stage 02 LLM triage) -> validate -> architect -> the EV
gate -> generate (stage 05). It neither bypasses nor modifies any downstream stage: an X-surfaced
trend still has to clear the EV gate before a cent of image spend, exactly like an etsy/google trend.

Mechanism: OpenRouter's OpenAI-compatible chat-completions endpoint with the `openrouter:web_search`
SERVER TOOL at engine "native". On an xAI Grok 4+ model (default x-ai/grok-4.3 — grok-4.1-fast was
deprecated) native search includes x_search, so Grok searches X directly. The deprecated
`plugins:[{id:"web"}]` / ":online" forms are intentionally NOT used (server tools let the model
decide when/how often to search).

Fails SOFT per the BaseSource contract: any missing key, network error, or unparseable reply returns
[] so one flaky source never kills a collect run.
"""
from __future__ import annotations

import json
import re

import requests

from ..config import settings
from ..models import Tier, Trend
from .base import BaseSource

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

_SYSTEM = (
    "You surface EMERGING consumer trends on X (Twitter) that can become Etsy digital-download "
    "products: printables, editable Canva templates, wall art. Search X for what people are excited "
    "about right now — parties, weddings, showers, classroom, hobbies, fandoms, seasonal moments. "
    "Return ONLY specific, productizable Etsy SEARCH PHRASES a buyer would actually type. No brand, "
    "team, or character names (trademark); phrase them generically."
)
_USER = (
    "Search X for {n} topics trending in the last ~2 weeks that each map to a sellable Etsy digital "
    "printable or editable template. Reply with STRICT JSON only: a list of objects "
    '{{"term": "<etsy search phrase>", "why": "<one short line: the X trend behind it>"}}.'
)


class XTrendsSource(BaseSource):
    name = "x"

    def fetch(self, limit: int) -> list[Trend]:
        key = settings.openrouter_api_key
        if not key:
            print("[x] skipped: OPENROUTER_API_KEY not set")
            return []
        body = {
            "model": settings.openrouter_model,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": _USER.format(n=max(limit, 8))},
            ],
            # Server tool: native engine -> on a Grok model this turns on x_search (X search).
            "tools": [{"type": "openrouter:web_search", "parameters": {"engine": "native"}}],
        }
        try:
            resp = requests.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    # OpenRouter attribution headers (optional but recommended).
                    "HTTP-Referer": "https://github.com/oguzhankayan/etsy-engine",
                    "X-Title": "etsy-trend-engine",
                },
                json=body, timeout=120,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        except Exception as e:  # noqa: BLE001 — never raise: BaseSource contract
            print(f"[x] fetch failed: {e}")
            return []

        trends: list[Trend] = []
        seen: set[str] = set()
        for it in _parse_items(content):
            term = (it.get("term") or "").strip()
            k = term.lower()
            if not term or k in seen:
                continue
            seen.add(k)
            payload = json.dumps({"kind": "x", "why": (it.get("why") or "")[:200]})
            trends.append(Trend(source=self.name, term=term, raw_payload=payload, tier=Tier.VIRAL))
        return trends[:limit]


def _parse_items(content: str | None) -> list[dict]:
    """Parse the model's JSON list of {term, why} from possibly fenced/wrapped text. Fails soft to []."""
    if not content:
        return []
    text = content.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    try:
        data = json.loads(text)
    except (ValueError, json.JSONDecodeError):
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except (ValueError, json.JSONDecodeError):
            return []
    if isinstance(data, dict):                      # tolerate {"trends":[...]} or a single object
        for v in data.values():
            if isinstance(v, list):
                return [d for d in v if isinstance(d, dict)]
        return [data]
    return [d for d in data if isinstance(d, dict)]
