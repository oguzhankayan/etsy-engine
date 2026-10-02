"""The EV gate is the cost circuit-breaker before stage 05 (image generation).

It must guarantee two things, both pinned here:
  1. a product whose projected expected value is below the configured floor NEVER reaches
     ``generate_product`` (no image credits spent), and
  2. a blocked run records ZERO new Anthropic spend in ``anthropic_spend.jsonl``.

Positive controls prove the gate isn't just blocking everything (a strong product clears it and
generates) and that it fails OPEN on missing signal (never withhold on thin data).
"""
import json

import pytest

from etsy_engine import db, llm, pipeline
from etsy_engine.config import settings
from etsy_engine.models import Product, Score, Trend
from etsy_engine.scoring import ev_gate


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Isolated DB + isolated spend ledger, so a run's spend is measured from zero."""
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "ev.db"))
    db.init_db()
    monkeypatch.setattr(llm, "SPEND_LOG", tmp_path / "spend.jsonl")
    return tmp_path


def _planned_product(term, *, demand, competition, price, composite=0.5, emerging=0.0):
    """Insert a fully scored + market-validated PLANNED product; return its id."""
    tid = db.upsert_trend(Trend(source="test", term=term))
    db.upsert_score(Score(trend_id=tid, virality=0.5, purchase_intent=0.5, productization=0.5,
                          competition=competition, longevity=0.5, ip_risk=0.0, composite=composite))
    db.upsert_market_signal(tid, {"count": 1000, "avg_favorites": 5.0,
                                  "competition_score": competition, "demand_score": demand,
                                  "emerging_niche": emerging, "emerging_shops": 0},
                            adjusted_score=demand)
    pid = db.insert_product(Product(trend_id=tid, title_concept=term, bundle_type=term.title()))
    db.upsert_product_intel(pid, "planner", price, [], {})
    return pid


def _spy_generate(monkeypatch):
    """Replace stage-05 generation with a spy that, like the real thing, would record spend.

    Returns the list of product ids it was called with — so a blocked product leaving this empty
    proves generation was never reached.
    """
    calls: list[int] = []

    def fake_generate_product(product, **kw):
        calls.append(product["id"])
        with llm.SPEND_LOG.open("a") as fh:                       # simulate QC vision spend
            fh.write(json.dumps({"cost_usd": 0.25, "input_tokens": 100,
                                 "output_tokens": 50}) + "\n")
        return 1

    monkeypatch.setattr(pipeline, "generate_product", fake_generate_product)
    return calls


def test_below_threshold_product_never_reaches_generate(fresh_db, monkeypatch):
    calls = _spy_generate(monkeypatch)
    weak = _planned_product("world checklist tracker", demand=0.05, competition=0.1, price=4.0)
    monkeypatch.setattr(settings, "ev_gate_min", 5.0)

    pipeline.generate()

    assert calls == []                                    # generate_product NEVER invoked
    assert db.product(weak)["status"] == "ev_blocked"     # parked out of the funnel
    assert db.assets_for_product(weak) == []              # no assets were produced


def test_blocked_run_keeps_anthropic_spend_flat(fresh_db, monkeypatch):
    _spy_generate(monkeypatch)
    _planned_product("world checklist tracker", demand=0.05, competition=0.1, price=4.0)
    monkeypatch.setattr(settings, "ev_gate_min", 5.0)

    before = llm.total_spend()
    pipeline.generate()
    after = llm.total_spend()

    assert before["total_usd"] == 0.0
    assert after["total_usd"] == before["total_usd"]      # not a cent spent on a blocked run
    assert after["calls"] == before["calls"] == 0


def test_healthy_product_passes_and_generates(fresh_db, monkeypatch):
    """Positive control: a strong product clears the SAME floor and DOES reach generation + spend."""
    calls = _spy_generate(monkeypatch)
    strong = _planned_product("funeral program template", demand=0.6, competition=0.6,
                              price=9.0, emerging=0.33)
    monkeypatch.setattr(settings, "ev_gate_min", 5.0)

    pipeline.generate()

    assert calls == [strong]
    assert llm.total_spend()["total_usd"] > 0.0           # the PASSED product incurred (sim) spend
    assert db.product(strong)["status"] != "ev_blocked"


def test_gate_fails_open_on_missing_signal(fresh_db, monkeypatch):
    """No score/market row -> EV can't be projected -> the product PASSES (never withhold on thin data)."""
    tid = db.upsert_trend(Trend(source="test", term="mystery niche"))
    pid = db.insert_product(Product(trend_id=tid, title_concept="x", bundle_type="Mystery"))
    monkeypatch.setattr(settings, "ev_gate_min", 5.0)

    verdict = ev_gate.evaluate(pid)
    assert verdict["ev"] is None and verdict["passes"] is True


def test_default_floor_is_permissive(fresh_db):
    """Default floor 0.0 blocks only projected-LOSS products, so real weak-but-positive niches build."""
    pid = _planned_product("budget planner", demand=0.2, competition=0.3, price=5.0)
    verdict = ev_gate.evaluate(pid)                        # default settings.ev_gate_min == 0.0
    assert verdict["ev"] > 0 and verdict["passes"] is True
