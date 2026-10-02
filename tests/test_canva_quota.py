"""The Canva PRODUCTION quota. Editable markets (weddings, invitations, funeral programs) are huge but
saturated, so the winnability-weighted score ranks them below niche PDF trends and the Canva line
starves. `_select_for_production` reserves a slot per run for the top Canva-suitable candidate.
"""
from etsy_engine import pipeline, product_ideas


def _cand(tid, term):
    return {"trend_id": tid, "term": term}


def test_reserves_a_slot_for_the_top_canva_candidate(monkeypatch):
    # rank-ordered: winnable PDF niches on top, the Canva niche buried lower
    candidates = [
        _cand(1, "world cup party printable"),   # pdf
        _cand(2, "printable planner"),            # pdf (planner excluded)
        _cand(3, "bold easy coloring book"),      # pdf (coloring excluded)
        _cand(4, "funeral program template"),     # CANVA (menu_program) — lower rank
    ]
    monkeypatch.setattr(product_ideas, "select_diverse", lambda cands, limit: cands[:limit])

    opps = pipeline._select_for_production(candidates, n=3, canva_quota=1)
    terms = [o["term"] for o in opps]
    assert terms[0] == "funeral program template"   # the buried Canva candidate was RESERVED first
    assert len(opps) == 3                            # still fills the run
    assert "world cup party printable" in terms      # plus the top PDF niches


def test_no_double_pick_of_the_reserved_candidate(monkeypatch):
    candidates = [_cand(1, "funeral program template"), _cand(2, "world cup printable")]
    monkeypatch.setattr(product_ideas, "select_diverse", lambda cands, limit: cands[:limit])
    opps = pipeline._select_for_production(candidates, n=2, canva_quota=1)
    ids = [o["trend_id"] for o in opps]
    assert ids == [1, 2] and len(set(ids)) == 2      # reserved once, not duplicated by select_diverse


def test_quota_zero_is_pure_rank_order(monkeypatch):
    candidates = [_cand(1, "world cup printable"), _cand(2, "funeral program template")]
    monkeypatch.setattr(product_ideas, "select_diverse", lambda cands, limit: cands[:limit])
    opps = pipeline._select_for_production(candidates, n=1, canva_quota=0)
    assert [o["term"] for o in opps] == ["world cup printable"]   # no reservation -> top rank wins
