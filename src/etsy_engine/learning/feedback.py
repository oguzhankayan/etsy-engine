"""Learning loop (Faz 5). Turns real performance into better scoring.

Two outputs:
1. Learnings — which trend sources / aesthetics / tiers actually convert, so the
   operator sees what's working.
2. Auto-tuned weights — correlate each scoring factor with realized performance
   and nudge the scoring weights toward factors that predict winners.

Performance signal per listing: FAVORITE-PER-VIEW is primary (a dense, low-noise signal — favorites
accrue with roughly every ~20 views); raw sales are only a small secondary nudge because the shop's
~8-16 lifetime sales are far too sparse to tune five weights on. A prior cap bounds how far any one
learning run can move a weight, so a single noisy outcome can't swing the model. Needs a few
published listings with metrics before it learns.
"""
from __future__ import annotations

from collections import defaultdict

from .. import db
from ..config import current_weights, save_weights

FACTORS = ["virality", "purchase_intent", "productization", "competition", "longevity"]
MIN_ROWS = 3        # need at least this many listings to tune weights
LEARNING_RATE = 0.10
# Prior cap (regularization): no single learning run may move a weight more than this far from its
# current value. On a thin dataset this anchors each weight to its prior so one noisy outcome — a
# lone sale, a fluke favorite — can only nudge it, never swing it. This is the "prior" that bounds
# how far any single outcome moves any weight.
MAX_WEIGHT_STEP = 0.05
# Favorite-per-view is the PRIMARY signal. A sale still counts, but only as a small secondary nudge
# (SALES_COEF): raw sales are too sparse (~8-16 lifetime) to drive five weights, so we down-weight
# them so heavily that one added sale moves the tuned weights by less than an epsilon (locked by test).
SALES_COEF = 0.2


def _performance(row: dict) -> float:
    """Realized performance per listing. PRIMARY = favorite-per-view; sales only a small secondary nudge."""
    views = max(int(row.get("views") or 0), 1)
    favs = int(row.get("favorites") or 0)
    sales = int(row.get("sales") or 0)
    return favs / views + SALES_COEF * (sales / views)


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs) ** 0.5
    vy = sum((y - my) ** 2 for y in ys) ** 0.5
    if vx == 0 or vy == 0:
        return 0.0
    return cov / (vx * vy)


def _group_perf(rows: list[dict], key: str) -> list[tuple[str, float, int]]:
    agg: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        agg[str(r.get(key) or "?")].append(_performance(r))
    out = [(k, sum(v) / len(v), len(v)) for k, v in agg.items()]
    return sorted(out, key=lambda x: x[1], reverse=True)


def tune_weights(rows: list[dict], prior=None) -> dict:
    """Nudge scoring weights toward the factors that correlate with FAVORITE-PER-VIEW performance,
    each move bounded by the prior cap (`MAX_WEIGHT_STEP`), then renormalized to sum to 1.

    Pure: no DB, no IO — takes metric rows + a prior weight set and returns the new weight dict. This
    is the whole learning signal, isolated so it can be exercised directly (tests/test_learning_signal).
    """
    prior = prior or current_weights()
    perf = [_performance(r) for r in rows]
    new: dict[str, float] = {}
    for f in FACTORS:
        scores = [float(r.get(f) or 0) for r in rows]
        corr = _pearson(scores, perf)
        step = LEARNING_RATE * corr
        step = max(-MAX_WEIGHT_STEP, min(MAX_WEIGHT_STEP, step))   # prior cap: bounded per-run move
        new[f] = max(0.02, getattr(prior, f) + step)
    total = sum(new.values())
    return {f: round(v / total, 4) for f, v in new.items()}


def learn(apply_weights: bool = True) -> dict:
    rows = db.latest_metrics()
    if not rows:
        print("[learn] no metrics yet — publish listings and run `metrics` first")
        return {}

    # Self-improving product ideas: feed metrics per archetype
    try:
        from ..product_ideas import prune, sync_metric_performance
        sync_metric_performance(rows)
        prune()
    except Exception as e:
        print(f"[learn] product_ideas feedback skipped: {e}")

    learnings = {
        "by_source": _group_perf(rows, "trend_source"),
        "by_aesthetic": _group_perf(rows, "aesthetic"),
        "by_tier": _group_perf(rows, "tier"),
    }
    for label, data in learnings.items():
        print(f"[learn] {label}:")
        for name, perf, n in data:
            print(f"          {name:<24} perf={perf:.3f}  (n={n})")

    if len(rows) < MIN_ROWS:
        print(f"[learn] need >={MIN_ROWS} listings to tune weights (have {len(rows)})")
        return learnings

    w = current_weights()
    new = tune_weights(rows, prior=w)     # favorite-per-view signal, prior-capped (see tune_weights)
    for f in FACTORS:
        print(f"[learn] {f}: weight {getattr(w, f):.3f} -> {new[f]:.3f}")
    if apply_weights:
        save_weights(current_weights().model_copy(update=new))
        print(f"[learn] saved tuned weights: {new}")
    learnings["weights"] = new
    return learnings
