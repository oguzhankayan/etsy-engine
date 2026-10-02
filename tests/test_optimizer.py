"""Tests for seo/optimizer.py"""
from __future__ import annotations


from etsy_engine.seo import optimizer as opt


def test_is_buried():
    assert opt.is_buried(50, min_rank=20) is True
    assert opt.is_buried(21, min_rank=20) is True
    assert opt.is_buried(20, min_rank=20) is False
    assert opt.is_buried(1, min_rank=20) is False
    assert opt.is_buried(None, min_rank=20) is True


def test_build_keyword_research_shapes_tags():
    """Keyword research dict contains real top tags as long-tail."""
    product = {"id": 1, "bundle_type": "Family Camping Planner Bundle"}
    intel = {
        "archetype": "planner",
        "top_tags": ["camping checklist", "trip planner", "family camping"],
    }
    research = opt._build_keyword_research(product, "family camping", intel)
    assert research["primary_keyword"] == "family camping"
    assert "camping checklist" in research["long_tail"]
    assert research["formats"] == ["instant download", "pdf printable", "print at home"]


def test_find_buried_listings(monkeypatch, tmp_path):
    """Only listings that are buried AND have demand are returned."""
    fake_ranks = [
        {
            "product_id": 1,
            "etsy_listing_id": 111,
            "bundle_type": "A",
            "keyword": "family camping",
            "rank": 45,
            "total_results": 2000,
        },
        {
            "product_id": 2,
            "etsy_listing_id": 222,
            "bundle_type": "B",
            "keyword": "shark coloring",
            "rank": 5,
            "total_results": 900,
        },
        {
            "product_id": 3,
            "etsy_listing_id": 333,
            "bundle_type": "C",
            "keyword": "dead niche",
            "rank": 60,
            "total_results": 30,
        },
    ]
    monkeypatch.setattr(opt.db, "latest_ranks", lambda: fake_ranks)

    def fake_market_intel(keyword, sample=100):
        if keyword == "family camping":
            return {"demand_score": 0.45, "count": 2000, "avg_daily_views": 12}
        if keyword == "dead niche":
            return {"demand_score": 0.02, "count": 30, "avg_daily_views": 0.1}
        return None

    monkeypatch.setattr(opt, "market_intel", fake_market_intel)
    candidates = opt.find_buried_listings(min_rank=20, min_demand=0.1, min_results=20)
    assert len(candidates) == 1
    assert candidates[0]["product_id"] == 1
    assert candidates[0]["demand_score"] == 0.45
