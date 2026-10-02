"""Expected-value gate — the cost circuit-breaker before stage 05 (image generation).

Stages 01-04 (collect / score / validate / architect) are cheap — a few LLM cents. Stage 05 (image
generation) is the cost cliff: Raywake image credits plus ~10 QC vision calls per product. This
gate sits at the mouth of stage 05, projects each planned product's expected value from signals we
ALREADY hold in the DB (real Etsy demand, competition, small-shop risers, niche median price), and
blocks anything below a configurable floor. Nothing that fails the gate reaches ``generate_product``,
so no credits are spent on a product the market data says won't earn them back — the #1 cost leak in
the profitability audit (spend happened before the specific product proved demand).

Two properties the gate guarantees by construction:
  * CHEAP — EV is arithmetic over stored provenance; it makes NO API/LLM call, so a blocked run
    records ZERO new spend (``tests/test_ev_gate.py`` asserts this against ``anthropic_spend.jsonl``).
  * FAIL-OPEN — a product with too little signal to score returns ``ev=None`` and PASSES. We only
    ever withhold generation on a positive projection of loss, never on missing data.

Threshold is ``settings.ev_gate_min`` (env ``EV_GATE_MIN``), default ``0.0`` — block only projected-
negative products. Additive: it does not touch stages 01-04, only guards the entrance to 05.
"""
from __future__ import annotations

from .. import db
from ..config import settings

# Projection constants — deliberately conservative and legible; the gate is a FLOOR, not a forecaster.
# A demand_score of 1.0 at neutral winnability projects ~4 monthly unit sales, in line with the shop's
# break-even framing (~8 sales/mo covers fixed cost), so most products sit well below that.
_UNITS_AT_FULL_DEMAND = 4.0
_DIGITAL_MARGIN = 0.9          # ~90% net after Etsy fees on a digital download
_PRODUCTION_COST_USD = 0.60    # floor: minimum cost to build one product
# Cost SCALES with format + page count: a Canva set of ~7 high-res pages (~$0.55 each, plus QC) costs
# several dollars, not the flat $0.60 a single PDF page implies. A too-low cost lets marginal
# multi-page products clear the gate (review finding #8).
_COST_PER_PIECE = {"canva": 0.55, "pdf": 0.18}
_DEFAULT_PIECES = {"canva": 7, "pdf": 5}   # estimate when a routed product has no bundle_items yet


def _production_cost(fmt: str, pieces: int) -> float:
    per = _COST_PER_PIECE.get(fmt, _COST_PER_PIECE["pdf"])
    n = pieces or _DEFAULT_PIECES.get(fmt, 5)
    return round(max(_PRODUCTION_COST_USD, per * n), 2)


def projected_ev(prov: dict, intel: dict | None, production_cost: float | None = None) -> float | None:
    """Projected monthly $ profit for a product from stored signals only; ``None`` = can't project.

    ``EV = price x est_monthly_units x margin - production_cost``, where ``est_monthly_units`` scales
    with real Etsy demand and a winnability multiplier (open competition + small-shop risers help).
    """
    raw_price = (intel or {}).get("median_price")
    price = float(raw_price) if raw_price not in (None, "") else float(settings.etsy_default_price or 0)

    # Demand: prefer the real Etsy demand_score, then the market-adjusted rank, then the LLM
    # composite. If NONE exists we cannot project -> fail open (return None).
    demand = prov.get("mkt_demand")
    if demand is None:
        demand = prov.get("adjusted_score")
    if demand is None:
        demand = prov.get("composite")
    if demand is None or price <= 0:
        return None
    demand = max(0.0, float(demand))

    win = 1.0
    comp = prov.get("mkt_competition")                                   # 0 crowded .. 1 wide open
    if comp is not None:
        # Competition is a MODEST tilt, not the driver. This shop's edge is execution speed/quality,
        # so a proven-demand niche out-executed beats a wide-open (often thin-demand) one; a 0.8..1.2
        # band keeps real demand dominant instead of a 3x swing that over-rewarded empty niches.
        win *= 0.8 + 0.4 * float(comp)                                   # 0.8x saturated, 1.2x open
    win *= 1.0 + 0.5 * float(prov.get("emerging_niche") or 0.0)          # +50% when small shops climb

    est_units = _UNITS_AT_FULL_DEMAND * demand * win
    revenue = price * est_units * _DIGITAL_MARGIN
    cost = _PRODUCTION_COST_USD if production_cost is None else production_cost
    return round(revenue - cost, 2)


def evaluate(product_id: int, threshold: float | None = None) -> dict:
    """Score ONE product against the gate.

    Returns ``{product_id, ev, threshold, passes, reason, ...}``. ``passes`` is True when the product
    clears the floor OR when EV can't be projected (fail-open).
    """
    thr = settings.ev_gate_min if threshold is None else threshold
    prov = db.provenance(product_id)
    intel = db.get_product_intel(product_id)
    prod = db.product(product_id) or {}
    cost = _production_cost(prod.get("format", "pdf"), len(db.bundle_items_for(product_id)))
    ev = projected_ev(prov, intel, production_cost=cost)
    if ev is None:                     # fail open: too little signal to justify withholding spend
        return {"product_id": product_id, "ev": None, "threshold": thr,
                "passes": True, "reason": "insufficient-signal (fail-open)"}
    passes = ev >= thr
    return {"product_id": product_id, "ev": ev, "threshold": thr, "passes": passes,
            "price": (intel or {}).get("median_price"),
            "reason": f"projected EV ${ev:.2f} {'>=' if passes else '<'} floor ${thr:.2f}"}


def screen(products: list[dict], threshold: float | None = None) -> tuple[list[dict], list[dict]]:
    """Split planned product rows into ``(passed, blocked)`` by the EV gate.

    Pure: no DB writes, no side effects — the caller decides what to do with each side. Each returned
    row carries its verdict under ``_ev`` for logging.
    """
    passed: list[dict] = []
    blocked: list[dict] = []
    for p in products:
        verdict = evaluate(p["id"], threshold)
        (passed if verdict["passes"] else blocked).append({**p, "_ev": verdict})
    return passed, blocked
