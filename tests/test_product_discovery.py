from __future__ import annotations

import json

from etsy_engine import product_ideas
from etsy_engine.sources import seeds


def test_discovery_seeds_include_every_pool(monkeypatch, tmp_path):
    rotation = tmp_path / "rotation.json"
    monkeypatch.setattr(seeds, "SEED_ROTATION_FILE", rotation)
    monkeypatch.setattr(seeds, "EVERGREEN", [f"evergreen {i}" for i in range(10)])
    monkeypatch.setattr(seeds, "seasonal_seeds", lambda month=None: [f"seasonal {i}" for i in range(10)])
    monkeypatch.setattr(seeds, "product_ideas_seeds", lambda: [f"idea {i}" for i in range(10)])
    monkeypatch.setattr(seeds, "load_dynamic_seeds", lambda: [f"learned {i}" for i in range(10)])

    selected = seeds.discovery_seeds(limit=14)

    assert len(selected) == 14
    assert any(s.startswith("evergreen") for s in selected)
    assert any(s.startswith("seasonal") for s in selected)
    assert any(s.startswith("idea") for s in selected)
    assert any(s.startswith("learned") for s in selected)


def test_discovery_seeds_rotate(monkeypatch, tmp_path):
    monkeypatch.setattr(seeds, "SEED_ROTATION_FILE", tmp_path / "rotation.json")
    monkeypatch.setattr(seeds, "EVERGREEN", [f"evergreen {i}" for i in range(12)])
    monkeypatch.setattr(seeds, "seasonal_seeds", lambda month=None: [])
    monkeypatch.setattr(seeds, "product_ideas_seeds", lambda: [])
    monkeypatch.setattr(seeds, "load_dynamic_seeds", lambda: [])

    first = seeds.discovery_seeds(limit=4)
    second = seeds.discovery_seeds(limit=4)

    assert first != second
    assert set(first).isdisjoint(second)


def test_feedback_from_product_prefers_specific_archetype(monkeypatch, tmp_path):
    ideas_file = tmp_path / "product_ideas.json"
    ideas_file.write_text(json.dumps({
        "coloring_page": {
            "triggers": ["coloring"],
            "seeds": [],
            "formats": [],
            "example_themes": [],
        },
        "planner_kit": {
            "triggers": ["planner"],
            "seeds": [],
            "formats": [],
            "example_themes": [],
        },
    }))
    monkeypatch.setattr(product_ideas, "IDEAS_FILE", ideas_file)

    product_ideas.feedback_from_product("dinosaur coloring book", archetype="planner")
    data = json.loads(ideas_file.read_text())

    assert data["coloring_page"]["_learned"]["performance"]["products"] == 1
    assert "planner" not in data


def test_market_feedback_learns_emerging_niche(monkeypatch, tmp_path):
    ideas_file = tmp_path / "product_ideas.json"
    ideas_file.write_text(json.dumps({
        "checklist_tracker": {
            "triggers": ["tracker"],
            "seeds": [],
            "formats": [],
            "example_themes": [],
        }
    }))
    monkeypatch.setattr(product_ideas, "IDEAS_FILE", ideas_file)

    product_ideas.feedback_from_intel("blind box tracker", {
        "avg_daily_views": 0.57,
        "beatability": 0.75,
        "count": 6,
        "archetype": "planner",
    })
    data = json.loads(ideas_file.read_text())

    assert "blind box tracker" in data["checklist_tracker"]["_learned"]["seeds"]


def test_select_diverse_penalizes_repeating_archetype(monkeypatch):
    monkeypatch.setattr(product_ideas, "diversity_adjustment", lambda term: 0.0)
    monkeypatch.setattr("etsy_engine.history.is_duplicate", lambda term: False)
    candidates = [
        {"term": "budget planner", "rank_score": 0.90},
        {"term": "meal planner", "rank_score": 0.89},
        {"term": "kawaii coloring book", "rank_score": 0.80},
    ]

    selected = product_ideas.select_diverse(candidates, 2)

    assert [c["term"] for c in selected] == ["budget planner", "kawaii coloring book"]


def test_expanded_seeds_cross_theme_with_product_format(monkeypatch, tmp_path):
    ideas_file = tmp_path / "product_ideas.json"
    ideas_file.write_text(json.dumps({
        "coloring_page": {
            "triggers": ["coloring"],
            "seeds": ["coloring book"],
            "formats": ["multi-page"],
            "example_themes": ["woodland"],
        }
    }))
    monkeypatch.setattr(product_ideas, "IDEAS_FILE", ideas_file)
    monkeypatch.setattr(product_ideas, "CATALOG_FILE", tmp_path / "missing.json")

    assert "woodland coloring book printable" in product_ideas.archetype_seeds()


def test_trigger_matching_does_not_treat_printable_as_print(monkeypatch, tmp_path):
    ideas_file = tmp_path / "product_ideas.json"
    ideas_file.write_text(json.dumps({
        "greeting_card": {"triggers": ["card"], "formats": ["card"]},
        "wall_art_poster": {"triggers": ["print"], "formats": ["art"]},
    }))
    monkeypatch.setattr(product_ideas, "IDEAS_FILE", ideas_file)
    monkeypatch.setattr(product_ideas, "CATALOG_FILE", tmp_path / "missing.json")

    assert product_ideas.match_archetype("handmade card printable") == "greeting_card"
