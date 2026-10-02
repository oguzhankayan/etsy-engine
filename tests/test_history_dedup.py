from __future__ import annotations

from etsy_engine import history


def test_cross_language_dedup(monkeypatch):
    """The same theme in another language must collide (the #23 world-cup dup bug)."""
    assert history.theme_tokens("world cup") == history.theme_tokens("copa do mundo")
    assert history.theme_similarity("world cup 2026", "copa do mundo 2026") >= 0.6
    assert history.theme_tokens("navidad") == history.theme_tokens("christmas")   # accents + map
    assert history.theme_tokens("boda") == history.theme_tokens("wedding")
    monkeypatch.setattr(history, "load",
                        lambda: [{"theme_tokens": sorted(history.theme_tokens("world cup"))}])
    assert history.is_duplicate("copa do mundo 2026") is True


def test_duplicate_is_compared_per_product(monkeypatch):
    monkeypatch.setattr(history, "load", lambda: [
        {"theme_tokens": ["home", "buyer", "mortgage"]},
        {"theme_tokens": ["habit", "tracker"]},
    ])

    assert history.is_duplicate("first home buyer mortgage planner") is True
    assert history.is_duplicate("blind box collection tracker") is False


def test_similarity_requires_meaningful_overlap():
    assert history.theme_similarity("summer dinosaur coloring", "dinosaur coloring book") >= 0.6
    assert history.theme_similarity("blind box tracker", "habit tracker") < 0.6


def test_duplicate_detects_shared_multiword_theme(monkeypatch):
    monkeypatch.setattr(history, "load", lambda: [{
        "trend_term": "baby shower games",
        "bundle_type": "Modern Baby Shower Party Pack",
        "theme_tokens": ["baby", "shower", "party"],
    }])

    assert history.is_duplicate("baby shower games for men and women") is True
