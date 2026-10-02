"""Locks the /code-review high fixes (this session's harden pass): the EV gate + catalog cap now
guard the Canva path and fire before image spend, the in-flight dedup no longer over-excludes on a
single shared token, the EV cost scales with format, enrichment is bounded per run, and
assert_original no longer false-positives on shared niche vocabulary.
"""
import pytest

from etsy_engine import db, history, pipeline
from etsy_engine.canva import design as D, poster
from etsy_engine.config import settings
from etsy_engine.models import Score, Trend
from etsy_engine.scoring import competitive_intel as ci, ev_gate


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "h.db"))
    db.init_db()
    return tmp_path


def test_dedup_no_single_token_over_exclusion():
    # min()-denominator gave 1.0 (over-excluded); jaccard gives 0.5, so the distinct product survives
    assert not history.collides_with_any("graduation invitation", ["graduation printable"])
    assert not history.collides_with_any("monthly budget", ["budget planner"])
    # an identical theme still collides (the intended dedup)
    assert history.collides_with_any("funeral program template", ["funeral program"])


def test_ev_production_cost_scales_with_format():
    assert ev_gate._production_cost("pdf", 5) < ev_gate._production_cost("canva", 7)
    assert ev_gate._production_cost("canva", 0) >= 0.55 * 7 - 0.01   # routed canva estimated ~7 pages


def test_canva_approve_runs_the_ev_gate(fresh, monkeypatch):
    tid = db.upsert_trend(Trend(source="test", term="funeral program"))
    db.upsert_score(Score(trend_id=tid, virality=0.1, purchase_intent=0.1, productization=0.1,
                          competition=0.1, longevity=0.1, ip_risk=0.0, composite=0.02))
    db.upsert_market_signal(tid, {"count": 50000, "avg_favorites": 1.0, "competition_score": 0.1,
                                  "demand_score": 0.02, "emerging_niche": 0.0, "emerging_shops": 0},
                            adjusted_score=0.02)
    pid = db.route_to_canva(tid, "funeral program")
    db.upsert_product_intel(pid, "planner", 5.0, [], {})
    monkeypatch.setattr(settings, "ev_gate_min", 5.0)
    ran = []
    from etsy_engine.canva import produce as cprod
    monkeypatch.setattr(cprod, "prepare", lambda *a, **k: ran.append(1))

    res = pipeline.produce_approved([pid])
    assert res["blocked"] == [pid] and ran == []            # prepare (image spend) NEVER ran
    assert db.product(pid)["status"] == "ev_blocked"


def test_enrich_bounded_per_run(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "context_dev_enabled", True)
    monkeypatch.setattr(settings, "context_dev_api_key", "k")
    monkeypatch.setattr(ci, "CACHE_FILE", tmp_path / "cache.json")   # isolate cache (no cross-test hits)
    monkeypatch.setattr(ci, "SPEND_LOG", tmp_path / "spend.jsonl")
    searches = []
    monkeypatch.setattr(ci, "web_search", lambda *a, **k: searches.append(1) or {
        "results": [{"title": "t", "description": "d", "url": "https://www.etsy.com/listing/1/x"}],
        "credits": 1.0})
    monkeypatch.setattr(ci, "web_extract", lambda *a, **k: {"data": {"title": "t"}, "credits": 10.0})
    from etsy_engine import llm
    monkeypatch.setattr(llm, "complete_json", lambda *a, **k: ["gap"])

    e = ci.CompetitiveEnricher(max_enrich=2, cap=10, min_score=0.0)
    for term in ("a", "b", "c", "d"):
        e.enrich(term, 0.9)
    assert len(searches) == 2                               # only 2 candidates paid for; rest skipped


def test_assert_original_allows_shared_niche_vocabulary():
    block = {"competitor_sample": {
        "titles": ["Elegant Celebration of Life Program for a Beloved Grandmother"],
        "tags": ["celebration of life program"]}}
    # shares the common phrase inside a longer original description -> NOT a leak (must not raise)
    ci.assert_original({"title": "Warm Keepsake Booklet",
                        "description": "an original celebration of life program layout",
                        "tags": ["keepsake"]}, block)
    # a whole competitor tag copied verbatim still raises
    with pytest.raises(ci.OriginalityViolation):
        ci.assert_original({"title": "x", "tags": ["celebration of life program"]}, block)


def test_build_prompt_has_composition_on_preset_aesthetic():
    p = poster.build_prompt({"title": "X", "product_kind": "budget planner"},
                            aesthetic=next(iter(D.AESTHETICS)))
    assert "focal element" in p                             # default composition, not an empty directive
    assert "LAYOUT (follow this EXACT composition so every page of the set matches): ." not in p


def test_architect_dedup_excludes_ev_blocked(fresh):
    """product_terms carries status so the architect can drop ev_blocked/deleted from existing_trends
    (a transient EV block must not retire a trend forever)."""
    tid = db.upsert_trend(Trend(source="test", term="wedding welcome sign"))
    from etsy_engine.models import Product
    pid = db.insert_product(Product(trend_id=tid, title_concept="x", bundle_type="X", status="ev_blocked"))
    rows = {r["id"]: r for r in db.product_terms()}
    assert rows[pid]["status"] == "ev_blocked"              # status is exposed for the filter
    active = [r for r in db.product_terms() if r.get("status") not in ("ev_blocked", "deleted")]
    assert tid not in {r["trend_id"] for r in active}       # blocked trend is re-considerable
