"""Tests for the velocity radar, seasonal keep-alive, and emerging-niche signal."""
from __future__ import annotations

import json
import time

from etsy_engine import product_ideas
from etsy_engine.scoring import etsy_market
from etsy_engine.scoring.scorer import _virality_floor
from etsy_engine.sources import etsy_velocity, seeds


# --- Velocity -> virality floor ---

def test_velocity_payload_floors_virality():
    hot = json.dumps({"kind": "velocity", "favs_per_day": 12.0, "views_per_day": 40})
    warm = json.dumps({"kind": "velocity", "favs_per_day": 0.4, "views_per_day": 60})
    cold = json.dumps({"kind": "velocity", "favs_per_day": 0.0, "views_per_day": 1})
    assert _virality_floor(hot) >= 0.85     # 12 favs/day is a strong signal
    assert _virality_floor(warm) >= 0.5     # weak favs, but views/day rescues it
    assert _virality_floor(cold) == 0.0     # no momentum


def test_clean_term_strips_seo_noise():
    assert etsy_velocity._clean_term("300 pages! Retro Halloween Coloring Book, kids") \
        == "retro halloween coloring book"
    assert etsy_velocity._clean_term("Cozy Coloring Book | 30 Printable Pages") \
        == "cozy coloring book"
    assert etsy_velocity._clean_term("Set of 12 Boho Wall Art Prints") \
        == "boho wall art prints"


def test_velocity_source_ranks_and_dedups(monkeypatch):
    now = time.time()

    def fake_app_request(method, path, **kwargs):
        return {"results": [
            # 100 favs over 100 days = 1.0/day
            {"title": "Slow Poster | Printable", "num_favorers": 100,
             "views": 200, "original_creation_timestamp": int(now - 100 * 86400),
             "shop_id": 1, "tags": []},
            # 60 favs over 3 days = 20/day (hottest)
            {"title": "Hot Poster | Printable", "num_favorers": 60,
             "views": 300, "original_creation_timestamp": int(now - 3 * 86400),
             "shop_id": 2, "tags": []},
            # duplicate title-concept of the hot one -> deduped
            {"title": "Hot Poster | Deluxe Edition", "num_favorers": 40,
             "views": 100, "original_creation_timestamp": int(now - 3 * 86400),
             "shop_id": 3, "tags": []},
            # below MIN_FAVORERS -> dropped
            {"title": "Ignored", "num_favorers": 2, "views": 5,
             "original_creation_timestamp": int(now - 5 * 86400), "shop_id": 4,
             "tags": []},
        ]}

    monkeypatch.setattr(etsy_velocity.ec, "app_request", fake_app_request)
    trends = etsy_velocity.EtsyVelocitySource(categories=["poster"]).fetch(limit=10)
    terms = [t.term for t in trends]

    assert terms[0] == "hot poster"          # highest favs/day ranks first
    assert terms.count("hot poster") == 1    # duplicate concept removed
    assert "ignored" not in terms            # noise floor applied


# --- Seasonal keep-alive + boost ---

def test_season_for_distinctive_only():
    assert seeds.season_for("Christmas Advent Calendar") == "christmas"
    assert seeds.season_for("Father's Day Dad Coupon Book") == "fathers day"
    # generic words must NOT trip a season (regression: garden calendar != christmas)
    assert seeds.season_for("Vegetable Garden Planner") == ""
    assert seeds.season_for("Baby First Year Memory Kit") == ""
    # a generic party/stationery word shared across seasons must not mis-tag one
    # (regression: "gender reveal INVITATION" was wrongly tagged graduation via "invitation")
    assert seeds.season_for("Gender Reveal Invitation Template") == ""
    assert seeds.season_for("Baby Announcement Template") == ""
    assert seeds.season_for("Wedding Welcome Sign") == ""
    # but a real season keyword still matches even next to those generic words
    assert seeds.season_for("Graduation Party Invitation") == "graduation"
    assert seeds.season_for("Halloween Party Invitation") == "halloween"


def test_seasonal_boost_only_in_window(monkeypatch):
    monkeypatch.setattr(seeds, "upcoming_seasons", lambda month=None: {"christmas"})
    assert product_ideas.seasonal_boost("christmas advent calendar") == 0.10
    assert product_ideas.seasonal_boost("halloween party games") == 0.0
    assert product_ideas.seasonal_boost("budget planner") == 0.0


# --- Emerging niche ---

def test_emerging_niche_counts_small_shop_risers(monkeypatch):
    now = time.time()
    # shop 1 is small + fast; shop 2 is big; shop 3 is small but stale
    sizes = {"1": 20, "2": 5000, "3": 30}
    monkeypatch.setattr(etsy_market, "_shop_active_count",
                        lambda sid: sizes.get(str(sid)))
    rows = [
        {"fpd": 3.0, "age_days": 30, "shop_id": 1},    # emerging
        {"fpd": 5.0, "age_days": 30, "shop_id": 2},    # big shop -> not emerging
        {"fpd": 2.0, "age_days": 900, "shop_id": 3},   # too old -> not emerging
    ]
    score, count = etsy_market._emerging_niche(rows, now)
    assert count == 1
    assert 0.0 < score <= 1.0


# --- SEO keyword-research shape robustness (Sonnet 5 returned [{...}]) ---

def test_keyword_research_normalizes_list_wrapped_object():
    from etsy_engine.seo.keyword_research import _as_dict
    obj = {"primary_keyword": "x", "long_tail": ["a b"]}
    assert _as_dict(obj) == obj                 # dict passes through
    assert _as_dict([obj]) == obj               # single-element list unwrapped
    assert _as_dict(["not a dict"]) == {}       # no dict inside -> empty
    assert _as_dict("garbage") == {}            # non-JSON-object -> empty


def test_build_tags_tolerates_non_dict_kw():
    from etsy_engine.seo.writer import build_tags
    # A malformed cache (a list) must not crash tag assembly.
    assert build_tags([], real_tags=["cozy planner", "budget kit"])


def test_pinterest_predicts_seeds_in_discovery(monkeypatch, tmp_path):
    """Curated Pinterest Predicts trends must be reachable as discovery seeds."""
    monkeypatch.setattr(seeds, "SEED_ROTATION_FILE", tmp_path / "rot.json")
    pool = seeds.pinterest_predicts_seeds()
    assert pool and "art deco wall art" in pool          # Neo Deco -> Etsy phrase
    assert set(pool) <= set(seeds.active_seeds())          # all reachable
    picks = seeds.discovery_seeds(limit=40)
    assert any(s in pool for s in picks)                   # surfaced in rotation
