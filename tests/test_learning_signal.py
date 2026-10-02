"""The learning loop tunes scoring weights from FAVORITE-PER-VIEW (a dense signal) as the primary
driver — not raw sales, which are far too sparse (~8-16 lifetime) to tune five weights on. A prior
cap bounds how far any single run/outcome can move a weight, so one added sale barely moves them.

Locked here: (1) weights RESPOND to favorite-per-view; (2) one added sale moves every weight by less
than epsilon. The seed-feedback mechanism (sources.seeds.feedback_winning_seeds) is a different code
path and is not touched by these changes.
"""
from etsy_engine.config import ScoringWeights
from etsy_engine.learning import feedback

PRIOR = ScoringWeights()   # the default prior we tune away from


def _row(virality, purchase_intent, productization, competition, longevity,
         *, views, favorites, sales=0):
    return {"virality": virality, "purchase_intent": purchase_intent,
            "productization": productization, "competition": competition,
            "longevity": longevity, "views": views, "favorites": favorites, "sales": sales}


def test_weights_respond_to_favorite_per_view():
    """A factor that tracks favorite-per-view gains weight; an inversely-related one loses it."""
    rows = [                                                  # virality up, longevity down w/ fav/view
        _row(0.9, 0.5, 0.5, 0.5, 0.1, views=100, favorites=30),   # fav/view 0.30
        _row(0.7, 0.5, 0.5, 0.5, 0.3, views=100, favorites=20),   # 0.20
        _row(0.5, 0.5, 0.5, 0.5, 0.5, views=100, favorites=10),   # 0.10
        _row(0.2, 0.5, 0.5, 0.5, 0.8, views=100, favorites=2),    # 0.02
    ]
    w = feedback.tune_weights(rows, prior=PRIOR)
    assert w["virality"] > PRIOR.virality       # correlated with fav/view -> up
    assert w["longevity"] < PRIOR.longevity     # anti-correlated -> down


def test_favorite_per_view_is_what_moves_the_weights():
    """Raise favorites (holding everything else fixed) and the weights shift toward the tracking factor."""
    flat = [
        _row(0.9, 0.5, 0.5, 0.5, 0.5, views=100, favorites=5),
        _row(0.5, 0.5, 0.5, 0.5, 0.5, views=100, favorites=5),
        _row(0.1, 0.5, 0.5, 0.5, 0.5, views=100, favorites=5),
    ]
    faved = [
        _row(0.9, 0.5, 0.5, 0.5, 0.5, views=100, favorites=40),
        _row(0.5, 0.5, 0.5, 0.5, 0.5, views=100, favorites=15),
        _row(0.1, 0.5, 0.5, 0.5, 0.5, views=100, favorites=2),
    ]
    w_flat = feedback.tune_weights(flat, prior=PRIOR)
    w_faved = feedback.tune_weights(faved, prior=PRIOR)
    assert w_faved["virality"] > w_flat["virality"]


def test_one_added_sale_moves_every_weight_under_epsilon():
    """A single new sale must move every weight by less than EPSILON: sales is secondary AND capped."""
    EPSILON = 0.02
    rows = [
        _row(0.9, 0.4, 0.6, 0.5, 0.2, views=80, favorites=20, sales=0),
        _row(0.6, 0.5, 0.5, 0.5, 0.4, views=80, favorites=12, sales=0),
        _row(0.4, 0.6, 0.4, 0.5, 0.6, views=80, favorites=6,  sales=0),
        _row(0.2, 0.7, 0.3, 0.5, 0.8, views=80, favorites=2,  sales=0),
    ]
    before = feedback.tune_weights(rows, prior=PRIOR)
    rows[0]["sales"] += 1                                     # one new sale on one listing
    after = feedback.tune_weights(rows, prior=PRIOR)
    assert max(abs(after[f] - before[f]) for f in feedback.FACTORS) < EPSILON


def test_prior_cap_keeps_a_single_run_bounded():
    """Even on a perfect correlation, no weight jumps far from its prior — the cap holds the anchor."""
    rows = [
        _row(1.0, 0.0, 0.0, 0.0, 0.0, views=100, favorites=50),
        _row(0.0, 0.0, 0.0, 0.0, 0.0, views=100, favorites=0),
    ]
    w = feedback.tune_weights(rows, prior=PRIOR)
    for f in feedback.FACTORS:
        assert abs(w[f] - getattr(PRIOR, f)) < feedback.MAX_WEIGHT_STEP + 0.02
