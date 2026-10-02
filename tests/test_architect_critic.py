"""Architect upgrades: market-scope signal + differentiation critic."""
from __future__ import annotations

from etsy_engine.product import architect


def test_market_scope_reads_page_counts_from_titles():
    titles = [
        "300 Pages Mega Coloring Book | Instant Download",
        "Cozy Coloring Book, 50 pages, Bold and Easy",
        "Halloween Coloring | 40 Pages | PDF",
        "Cute Wall Art Print",  # no count — ignored
    ]
    scope = architect.market_scope(titles, median_price=6.5)
    assert scope["typical_page_count"] == 50
    assert scope["max_page_count_seen"] == 300
    assert scope["median_price_usd"] == 6.5


def test_market_scope_none_when_no_signal():
    assert architect.market_scope(["Pretty Print"], None) is None


def test_generic_verdict_triggers_one_revision(monkeypatch):
    calls = []

    def fake_complete_json(system, user):
        calls.append(system)
        if "market critic" in system:
            return {"verdict": "generic", "unique_angle": "",
                    "fixes": ["narrow to night-shift nurses", "add a handoff log"]}
        # design_bundle call: first plain, second must carry required_fixes
        if "required_fixes" in user:
            return {"bundle_type": "Night-Shift Nurse Kit", "title_concept": "x",
                    "items": [{"name": "Handoff Log", "asset_type": "log",
                               "spec": "s"}]}
        return {"bundle_type": "Nurse Planner", "title_concept": "x",
                "items": [{"name": "Weekly Planner", "asset_type": "planner",
                           "spec": "s"}]}

    monkeypatch.setattr(architect, "complete_json", fake_complete_json)
    monkeypatch.setattr("etsy_engine.scoring.etsy_market.market_intel",
                        lambda term: {"archetype": "planner", "top_tags": [],
                                      "median_price": 5.0})
    monkeypatch.setattr("etsy_engine.scoring.etsy_market.top_listing_titles",
                        lambda term: ["Nurse Planner 40 Pages", "Nurse Kit"])
    monkeypatch.setattr("etsy_engine.scoring.reviews.niche_review_insights",
                        lambda term: None)
    monkeypatch.setattr("etsy_engine.product_ideas.match_archetype",
                        lambda term: None)

    product, items, intel = architect.build_product(1, "nurse planner")
    assert product.bundle_type == "Night-Shift Nurse Kit"   # revised plan won
    assert intel["critic"]["verdict"] == "generic"
    assert intel.get("critic_revised") is True
    # 3 LLM calls: design -> critic -> revised design
    assert len(calls) == 3


def test_distinct_verdict_keeps_plan(monkeypatch):
    def fake_complete_json(system, user):
        if "market critic" in system:
            return {"verdict": "distinct", "unique_angle": "only kit with X",
                    "fixes": []}
        return {"bundle_type": "Original Kit", "title_concept": "x",
                "items": [{"name": "A", "asset_type": "planner", "spec": "s"}]}

    monkeypatch.setattr(architect, "complete_json", fake_complete_json)
    monkeypatch.setattr("etsy_engine.scoring.etsy_market.market_intel",
                        lambda term: {"archetype": "planner", "top_tags": []})
    monkeypatch.setattr("etsy_engine.scoring.etsy_market.top_listing_titles",
                        lambda term: ["Competitor Kit"])
    monkeypatch.setattr("etsy_engine.scoring.reviews.niche_review_insights",
                        lambda term: None)
    monkeypatch.setattr("etsy_engine.product_ideas.match_archetype",
                        lambda term: None)

    product, items, intel = architect.build_product(1, "some niche")
    assert product.bundle_type == "Original Kit"
    assert intel.get("critic_revised") is None
    assert intel["critic"]["unique_angle"] == "only kit with X"


def test_banned_cutout_forms_are_dropped(monkeypatch):
    def fake_complete_json(system, user):
        if "market critic" in system:
            return {"verdict": "distinct", "unique_angle": "x", "fixes": []}
        return {"bundle_type": "Party Kit", "title_concept": "x",
                "items": [
                    {"name": "Welcome Sign", "asset_type": "poster", "spec": "s"},
                    {"name": "Happy Birthday Pennant Banner", "asset_type": "banner_decor", "spec": "s"},
                    {"name": "Coupon Gift Wallet", "asset_type": "envelope", "spec": "s"},
                    {"name": "Cupcake Topper Circles", "asset_type": "sticker_sheet", "spec": "s"},
                ]}

    monkeypatch.setattr(architect, "complete_json", fake_complete_json)
    monkeypatch.setattr("etsy_engine.scoring.etsy_market.market_intel",
                        lambda term: {"archetype": "planner", "top_tags": []})
    monkeypatch.setattr("etsy_engine.scoring.etsy_market.top_listing_titles",
                        lambda term: [])
    monkeypatch.setattr("etsy_engine.scoring.reviews.niche_review_insights",
                        lambda term: None)
    monkeypatch.setattr("etsy_engine.product_ideas.match_archetype",
                        lambda term: None)

    _, items, _ = architect.build_product(1, "birthday party")
    names = [i.name for i in items]
    assert "Welcome Sign" in names and "Cupcake Topper Circles" in names
    assert all("banner" not in n.lower() and "wallet" not in n.lower() for n in names)
