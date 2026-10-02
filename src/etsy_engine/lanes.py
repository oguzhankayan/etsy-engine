"""Two production lanes + alternation.

- EVERGREEN: Etsy-validated, proven-demand opportunities (ranked by adjusted_score).
- VIRAL: high-momentum trending events (ranked by virality), first-mover bets —
  productizable + IP-safe, NOT gated on existing Etsy history (the point is it's new).

Production alternates lanes, starting from the OPPOSITE of the last product's lane
(persisted in data/last_lane.txt, survives DB resets). "Produce 6" -> 3 + 3.
Dedup is enforced against the durable product history (no near-duplicates ever).
"""
from __future__ import annotations

import json
import re

from . import db
from .config import DATA_DIR
from .history import is_duplicate, theme_similarity, theme_tokens
from .product_ideas import diversity_adjustment, resolve_archetype


def _is_daily(r: dict) -> bool:
    """True if the trend came from the general daily trending feed (a real event)."""
    try:
        return json.loads(r.get("raw_payload") or "{}").get("kind") == "daily"
    except (ValueError, TypeError):
        return False

LAST_LANE_FILE = DATA_DIR / "last_lane.txt"
LANES = ("evergreen", "viral")

NAV = {"youtube", "google", "gmail", "weather", "facebook", "instagram", "tiktok",
       "whatsapp", "translate", "news", "chatgpt", "gemini", "amazon", "login",
       "linkedin", "spotify", "netflix"}


def _junk(term: str) -> bool:
    t = f" {term.lower()} "
    if " near me " in t:
        return True
    if re.search(r"\b(vs|x|v)\b", term.lower()) and len(term.split()) <= 4:
        return True  # one-off match-ups: "ind vs afg", "marrocos x noruega"
    if theme_tokens(term) & NAV:
        return True
    return False


def _rows() -> list[dict]:
    with db.connect() as c:
        rows = c.execute(
            """SELECT t.term, t.id AS trend_id, t.raw_payload, s.virality,
                      s.productization, s.composite, s.ip_risk, s.rationale,
                      m.listing_count, m.demand_score, m.competition_score,
                      m.adjusted_score
               FROM trends t JOIN scores s ON s.trend_id=t.id
               LEFT JOIN market_signals m ON m.trend_id=t.id
               WHERE s.ip_risk <= 0.25"""
        ).fetchall()
    return [dict(r) for r in rows]


def _pick(rows, n, used, *, key, gate):
    candidates = []
    for r in rows:
        term = r["term"]
        if _junk(term) or (r.get("productization") or 0) < 0.7 or not gate(r):
            continue
        if not theme_tokens(term) or is_duplicate(term):
            continue
        if any(theme_similarity(term, selected) >= 0.6 for selected in used):
            continue
        candidates.append(r)

    out = []
    selected_arches: dict[str, int] = {}
    while candidates and len(out) < n:
        def rank(row):
            arch = resolve_archetype(row["term"])
            batch_penalty = selected_arches.get(arch, 0) * 0.18
            return key(row) + diversity_adjustment(row["term"]) - batch_penalty

        best = max(candidates, key=rank)
        candidates.remove(best)
        out.append(best)
        used.add(best["term"])
        arch = resolve_archetype(best["term"])
        selected_arches[arch] = selected_arches.get(arch, 0) + 1
    return out


def evergreen_picks(n: int, used: set[str]) -> list[dict]:
    """Validated, proven-demand opportunities, ranked demand-first.

    Saturation is now handled by the demand-first adjusted_score (which folds in
    beatability = competition + freshness), so we no longer hard-cap on raw listing
    count — that legacy gate rejected every popular niche (>50k listings) even when
    it was winnable. Rank by adjusted_score; the productization/junk/dedup filters
    in _pick still apply."""
    return _pick(
        _rows(), n, used,
        key=lambda r: (r.get("adjusted_score") or r.get("composite") or 0),
        gate=lambda r: r.get("adjusted_score") is not None,
    )


def viral_picks(n: int, used: set[str]) -> list[dict]:
    """High-momentum trending events; first-mover (no Etsy-history gate).
    Prefers real daily-trending events over generic high-rise rising queries."""
    return _pick(
        _rows(), n, used,
        key=lambda r: ((1.0 if _is_daily(r) else 0.0)
                       + (r.get("virality") or 0)
                       + 0.25 * (r.get("composite") or 0)),
        gate=lambda r: (r.get("virality") or 0) >= 0.7,
    )


def get_last_lane() -> str | None:
    if LAST_LANE_FILE.exists():
        v = LAST_LANE_FILE.read_text().strip()
        return v if v in LANES else None
    return None


def set_last_lane(lane: str) -> None:
    LAST_LANE_FILE.write_text(lane)


def lane_sequence(n: int, start: str | None = None) -> list[str]:
    """Alternating lanes for n products, starting opposite the last produced one."""
    if start not in LANES:
        last = get_last_lane()
        start = "viral" if last == "evergreen" else "evergreen"
    seq = []
    cur = start
    for _ in range(n):
        seq.append(cur)
        cur = "viral" if cur == "evergreen" else "evergreen"
    return seq
