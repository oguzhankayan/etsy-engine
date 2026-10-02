"""Opportunity Scorer (Agent 2). Claude scores trends on the 6-factor rubric.

Trends are scored in batches to save API calls. The composite is a weighted sum
(see config.ScoringWeights); ip_risk is reported but enforced as a gate in db/ip_filter.
"""
from __future__ import annotations

import json
import re

from ..config import current_weights
from ..llm import complete_json
from ..models import Score, Trend
from .ip_filter import quick_ip_risk

SYSTEM = """You are an expert Etsy digital-product market analyst. You score
trends for their potential as PRINTABLE / DIGITAL DOWNLOAD products (planners,
worksheets, wall art, trackers, etc.). Respond with JSON only, no prose.

For each trend, score every factor from 0.0 to 1.0:
- virality: how fast is this growing / how much momentum right now. If a
  "momentum_0_to_1" value is given (derived from real search traffic / growth
  velocity), treat it as a strong virality signal and don't score below it.
- purchase_intent: will people actually PAY for a digital product about this
- productization: think like an Etsy seller — can a digital/printable product
  RIDE this trend, even if the literal term isn't itself a printable? This applies
  to ANY kind of trend, not one category: a rising aesthetic or style, a hobby or
  activity surge, a season or holiday, an entertainment/cultural moment (a movie,
  show, game, event), a meme or catchphrase, a life situation. Score HIGH whenever
  there's a clear product hook (themed wall art/decor, planners/trackers, party or
  watch kits, templates, cards/stickers). Score LOW only when there is genuinely
  no angle: pure navigational queries (youtube, gmail, weather), a bare person's
  name with no hook, tragedies, or hyper-specific one-offs with no lasting identity.
- competition: how WINNABLE the niche is. 1.0 = real buyers with room to rank, 0.0 = saturated by
  entrenched giants. Higher is better, BUT a wide-open niche with NO buyer demand is DEAD, not
  winnable: do not score it high just because few listings exist. Reward PROVEN demand with beatable
  competition; a shop that out-executes wins a moderately competitive niche over an empty one.
- longevity: 1.0 = evergreen, 0.0 = dies in days
- ip_risk: how legally risky is selling a product about this. IMPORTANT nuance:
    * HIGH (0.7-1.0): the term names a DISTINCTIVE copyrighted character,
      entertainment franchise, specific brand, sports team, or a named celebrity
      (e.g. Pikachu, Marvel, Nike, Real Madrid, Taylor Swift).
    * LOW (0.0-0.2): generic topics, holidays, hobbies, activities, and even big
      EVENTS (World Cup, Olympics, Super Bowl) — these are sold legally as
      ORIGINAL, logo-free themed designs (generic soccer, sports, country flags).
      Do not penalize a topic just because an official brand also exists around it.

Return a JSON array, one object per input trend, in the same order:
[{"term": "...", "virality": 0.0, "purchase_intent": 0.0, "productization": 0.0,
  "competition": 0.0, "longevity": 0.0, "ip_risk": 0.0, "rationale": "one sentence"}]"""


def _virality_floor(payload: str) -> float:
    """Floor the virality from real momentum signals carried in raw_payload:
    daily approx_traffic (absolute searches) and/or rising rise_value (% growth,
    or 'Breakout'). Returns the strongest signal, 0.0 if none.
    """
    try:
        d = json.loads(payload or "{}")
    except (ValueError, TypeError):
        return 0.0
    floor = 0.0
    # Daily trends: absolute search volume.
    m = re.search(r"(\d[\d,]*)", str(d.get("approx_traffic", "")))
    if m:
        n = int(m.group(1).replace(",", ""))
        for th, f in [(5000, 0.9), (2000, 0.8), (1000, 0.7), (500, 0.6), (200, 0.5)]:
            if n >= th:
                floor = max(floor, f)
                break
    # Rising queries: relative growth (velocity).
    rv = str(d.get("rise_value", "")).lower()
    if "breakout" in rv:
        floor = max(floor, 0.9)
    else:
        m2 = re.search(r"(\d[\d,]*)", rv)
        if m2:
            n = int(m2.group(1).replace(",", ""))
            for th, f in [(1000, 0.85), (300, 0.75), (100, 0.6), (1, 0.5)]:
                if n >= th:
                    floor = max(floor, f)
                    break
    # Etsy velocity radar: real demand velocity on live listings. Favorites/day
    # is the strongest public purchase-intent proxy; views/day is a weaker backup.
    try:
        fpd = float(d.get("favs_per_day", 0) or 0)
    except (ValueError, TypeError):
        fpd = 0.0
    for th, f in [(20, 0.9), (10, 0.85), (5, 0.8), (2, 0.7), (1, 0.6), (0.3, 0.5)]:
        if fpd >= th:
            floor = max(floor, f)
            break
    try:
        vpd = float(d.get("views_per_day", 0) or 0)
    except (ValueError, TypeError):
        vpd = 0.0
    for th, f in [(200, 0.85), (100, 0.75), (50, 0.65), (20, 0.55)]:
        if vpd >= th:
            floor = max(floor, f)
            break
    # Event calendar: proximity to a scheduled mass event IS momentum — buyer
    # searches ramp predictably into the date (days_to_peak=0 while it runs).
    if d.get("kind") == "event":
        try:
            dtp = int(d.get("days_to_peak", 999))
        except (ValueError, TypeError):
            dtp = 999
        for th, f in [(7, 0.85), (21, 0.7), (45, 0.55)]:
            if dtp <= th:
                floor = max(floor, f)
                break
    return floor


def _composite(d: dict) -> float:
    w = current_weights()
    return round(
        d["virality"] * w.virality
        + d["purchase_intent"] * w.purchase_intent
        + d["productization"] * w.productization
        + d["competition"] * w.competition
        + d["longevity"] * w.longevity,
        4,
    )


def score_trends(trends: list[Trend], batch_size: int = 20) -> list[Score]:
    scores: list[Score] = []
    for i in range(0, len(trends), batch_size):
        batch = trends[i : i + batch_size]
        payload = []
        for t in batch:
            entry = {"term": t.term}
            floor = _virality_floor(t.raw_payload)
            if floor:  # surface real momentum (traffic/velocity) as a virality hint
                entry["momentum_0_to_1"] = floor
            payload.append(entry)
        user = "Score these trends:\n" + json.dumps(payload, ensure_ascii=False)
        try:
            results = complete_json(SYSTEM, user)
        except Exception as e:
            print(f"[scorer] batch {i // batch_size} failed: {e}")
            continue

        by_term = {r.get("term", "").strip().lower(): r for r in results}
        for t in batch:
            r = by_term.get(t.term.strip().lower())
            if not r:
                continue
            # Virality: take the higher of the model's score and the momentum floor.
            r["virality"] = max(float(r.get("virality", 0)), _virality_floor(t.raw_payload))
            # IP risk: worst of model's assessment and the hard-block heuristic.
            ip_risk = max(float(r.get("ip_risk", 0.0)), quick_ip_risk(t.term))
            scores.append(Score(
                trend_id=t.id,
                virality=r["virality"],
                purchase_intent=float(r.get("purchase_intent", 0)),
                productization=float(r.get("productization", 0)),
                competition=float(r.get("competition", 0)),
                longevity=float(r.get("longevity", 0)),
                ip_risk=ip_risk,
                composite=_composite(r),
                rationale=r.get("rationale", ""),
            ))
    return scores
