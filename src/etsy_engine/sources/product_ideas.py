"""Rotating product-format discovery from the self-improving idea catalog."""
from __future__ import annotations

import json

from ..models import Tier, Trend
from .base import BaseSource
from .seeds import idea_discovery_seeds


class ProductIdeasSource(BaseSource):
    """Guarantee that viable product formats reach scoring and Etsy validation.

    Google Trends remains the momentum radar. This source prevents rate limits or
    news-heavy daily feeds from starving evergreen product exploration.
    """

    name = "ideas"

    def fetch(self, limit: int) -> list[Trend]:
        from ..history import is_duplicate, theme_tokens

        # Pull extra rotating candidates because mature shops will discard many
        # catalog combinations as already produced.
        candidates = idea_discovery_seeds(max(limit * 4, limit))
        return [
            Trend(
                source=self.name,
                term=term,
                raw_payload=json.dumps({"kind": "product_idea_seed"}),
                tier=Tier.EVERGREEN,
            )
            for term in candidates if theme_tokens(term) and not is_duplicate(term)
        ][:limit]
