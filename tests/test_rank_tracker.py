"""Tests for learning/rank_tracker.py"""
from __future__ import annotations


from etsy_engine.learning import rank_tracker as rt


def test_search_rank_finds_listing(monkeypatch):
    """Our listing appears at position 5 in the search results."""
    def fake_app_request(method, path):
        assert "keywords=camping" in path
        return {
            "count": 1234,
            "results": [
                {"listing_id": i + 1000} for i in range(4)
            ] + [{"listing_id": 5555}] + [
                {"listing_id": i + 2000} for i in range(95)
            ],
        }

    monkeypatch.setattr(rt.ec, "app_request", fake_app_request)
    result = rt.search_rank("camping", 5555, sample=100)
    assert result["rank"] == 5
    assert result["found"] is True
    assert result["total_results"] == 1234


def test_search_rank_not_found(monkeypatch):
    """Our listing is not in the first 100 results."""
    def fake_app_request(method, path):
        return {
            "count": 5000,
            "results": [{"listing_id": i + 1} for i in range(100)],
        }

    monkeypatch.setattr(rt.ec, "app_request", fake_app_request)
    result = rt.search_rank("camping", 9999, sample=100)
    assert result["rank"] is None
    assert result["found"] is False
    assert result["total_results"] == 5000


def test_derive_keyword_from_title(monkeypatch):
    """Keyword comes from the clean title fragment before the pipe."""
    class FakeRow:
        def __init__(self, d):
            self._d = d
        def __getitem__(self, k):
            return self._d.get(k)
        def get(self, k, default=None):
            return self._d.get(k, default)

    monkeypatch.setattr(
        rt.db, "get_listing",
        lambda pid: FakeRow({"title": "Family Camping Planner Kit | Printable PDF | Instant Download"})
    )
    # 'planner' and 'kit' are stripped as generic category words.
    assert rt.derive_keyword(1) == "family camping"


def test_derive_keyword_no_stopwords(monkeypatch):
    """Generic words like 'printable' and 'kit' are stripped."""
    class FakeRow:
        def __init__(self, d):
            self._d = d
        def __getitem__(self, k):
            return self._d.get(k)
        def get(self, k, default=None):
            return self._d.get(k, default)

    monkeypatch.setattr(
        rt.db, "get_listing",
        lambda pid: FakeRow({"title": "Summer Reading Challenge Kit | Printable PDF"})
    )
    # 'kit' and 'printable' are stripped as generic words.
    assert rt.derive_keyword(1) == "summer reading challenge"
