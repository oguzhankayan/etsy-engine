"""Performance-gated seed feedback: only proven listings seed future discovery."""
from __future__ import annotations

import json

from etsy_engine.sources import seeds


def test_feedback_only_admits_proven_terms(monkeypatch, tmp_path):
    seed_file = tmp_path / "seeds.json"
    monkeypatch.setattr(seeds, "DYNAMIC_SEEDS_FILE", seed_file)

    rows = [
        {"term": "world cup", "views": 139, "favorites": 0},        # views winner
        {"term": "sunflower classroom decor", "views": 4, "favorites": 5},  # favs winner
        {"term": "kawaii coloring", "views": 1, "favorites": 0},    # dud
        {"term": "", "views": 999, "favorites": 9},                  # no term
        {"term": "meal planner", "views": 19, "favorites": 1},       # just below both floors
    ]
    monkeypatch.setattr("etsy_engine.db.latest_metrics", lambda: rows)

    winners = seeds.feedback_winning_seeds()
    assert winners == ["world cup", "sunflower classroom decor"]
    assert json.loads(seed_file.read_text()) == winners


def test_feedback_no_winners_writes_nothing(monkeypatch, tmp_path):
    seed_file = tmp_path / "seeds.json"
    monkeypatch.setattr(seeds, "DYNAMIC_SEEDS_FILE", seed_file)
    monkeypatch.setattr("etsy_engine.db.latest_metrics",
                        lambda: [{"term": "dud", "views": 0, "favorites": 0}])

    assert seeds.feedback_winning_seeds() == []
    assert not seed_file.exists()
