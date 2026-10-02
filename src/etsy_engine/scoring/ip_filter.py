"""IP risk gate (Risk Yönetimi). Two tiers, applied before any paid generation.

Philosophy: the risk is in the *artwork* (official logos), not always the topic.
- HARD_BLOCK  -> distinctive copyrighted/trademarked entities where ANY product
  infringes (characters, franchises, fashion/product brands, teams, celebrities).
  These are rejected outright (ip_risk = 1.0).
- RESTRICTED  -> big topical EVENTS with huge generic Etsy markets (World Cup,
  Olympics, Super Bowl...). NOT rejected — sold as original, logo-free themed
  products. We just flag them so generation avoids official marks.

This lets us ride viral trends (e.g. World Cup soccer printables) safely instead
of throwing them away.
"""
from __future__ import annotations

import re

# Distinctive IP — reject outright. Any product referencing these infringes.
BLOCKLIST = [
    "disney", "marvel", "nintendo", "pokemon", "pokémon", "netflix",
    "star wars", "harry potter", "barbie", "lego", "minecraft", "fortnite",
    "mickey", "spider-man", "spiderman", "frozen", "elsa", "bluey",
    "taylor swift", "nike", "adidas", "gucci", "louis vuitton", "coca cola",
    "real madrid", "barcelona", "lakers",  # specific teams (crest/name = the IP)
    "sanrio", "hello kitty", "stitch", "stranger things", "squid game",
]

# Topical events sellable as GENERIC, logo-free themes — allowed, but generation
# must avoid official logos/emblems/wordmarks/trophies/mascots.
RESTRICTED = [
    "world cup", "olympics", "olympic", "super bowl", "champions league",
    "wimbledon", "eurovision", "met gala", "fifa", "nba", "nfl",
]

_BLOCK_RE = re.compile(
    r"\b(" + "|".join(re.escape(b) for b in BLOCKLIST) + r")\b", re.IGNORECASE
)
_RESTRICTED_RE = re.compile(
    r"\b(" + "|".join(re.escape(r) for r in RESTRICTED) + r")\b", re.IGNORECASE
)


def blocklist_hit(term: str) -> str | None:
    """Return the matched hard-blocked phrase, or None."""
    m = _BLOCK_RE.search(term or "")
    return m.group(1) if m else None


def restricted_hit(term: str) -> str | None:
    """Return the matched restricted topic (allowed, art-constrained), or None."""
    m = _RESTRICTED_RE.search(term or "")
    return m.group(1) if m else None


def quick_ip_risk(term: str) -> float:
    """Cheap IP risk in [0,1]. 1.0 only for a hard-block hit; else 0.0.

    No blunt proper-noun heuristic — it over-flagged legitimate themes (e.g.
    "World Cup", "Mother's Day"). The LLM scorer handles the nuanced middle.
    """
    return 1.0 if blocklist_hit(term) else 0.0
