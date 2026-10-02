"""Review mining: buyer-voice insights with caching + graceful degradation."""
from __future__ import annotations

import json

from etsy_engine.scoring import reviews


def _wire(monkeypatch, tmp_path, review_texts, llm_result=None):
    monkeypatch.setattr(reviews, "_CACHE_FILE", tmp_path / "cache.json")

    def fake_app_request(method, path, **kwargs):
        if "/listings/active" in path:
            return {"results": [{"listing_id": 1}, {"listing_id": 2}]}
        return {"results": [{"rating": 5, "review": t} for t in review_texts]}

    monkeypatch.setattr(reviews.ec, "app_request", fake_app_request)
    calls = {"llm": 0}

    def fake_complete_json(system, user):
        calls["llm"] += 1
        return llm_result

    monkeypatch.setattr("etsy_engine.llm.complete_json", fake_complete_json)
    return calls


def test_insights_summarized_and_cached(monkeypatch, tmp_path):
    result = {"praises": ["cute art"], "complaints": ["pages too busy"],
              "buyer_words": ["bold and easy"], "summary": "simple wins"}
    calls = _wire(monkeypatch, tmp_path, ["Loved it!"] * 4, result)

    assert reviews.niche_review_insights("coloring book") == result
    # Second call must come from the disk cache — no second LLM call.
    assert reviews.niche_review_insights("coloring book") == result
    assert calls["llm"] == 1


def test_too_few_reviews_returns_none_and_caches(monkeypatch, tmp_path):
    calls = _wire(monkeypatch, tmp_path, [])  # Etsy tier returns no reviews today

    assert reviews.niche_review_insights("budget planner") is None
    assert calls["llm"] == 0
    # The None is cached too (a reviewless niche shouldn't be re-scanned).
    cached = json.loads((tmp_path / "cache.json").read_text())
    assert cached["budget planner"]["insights"] is None
