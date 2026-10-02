"""Competitive-intelligence enrichment (stage 03, context.dev). Mocked API — no live calls here.

Flow: web.search (etsy.com) -> top LISTING urls, then web.extract each listing page. Pins the whole
contract: extracted listings -> a correct market_intel block; saturation math; gap_analysis calls the
LLM and stores its strings; the ORIGINALITY guard (competitor text never reaches product content);
the per-run web.extract cap; the URL/query cache; credit spend logged with the `context_dev` tag; the
request shapes; and that the layer ships DARK and only enriches candidates above the score threshold.
"""
import json

import pytest

from etsy_engine import llm
from etsy_engine.config import settings
from etsy_engine.scoring import competitive_intel as ci

SEARCH_RESULTS = {
    "results": [
        {"title": "Funeral Program Template - Etsy", "description": "memorial program",
         "url": "https://www.etsy.com/listing/111/funeral-program"},
        {"title": "Celebration of Life Printable", "description": "booklet",
         "url": "https://www.etsy.com/listing/222/celebration"},
        {"title": "Modern Order of Service", "description": "foldable",
         "url": "https://www.etsy.com/listing/333/order"},
    ],
    "credits": 3.0,
}
LISTING_DATA = {
    "111": {"title": "Funeral Program Template Editable Canva", "description": "editable 5x7 memorial",
            "tags": ["funeral program", "memorial", "editable"], "price": 8.0, "num_reviews": 40},
    "222": {"title": "Celebration of Life Program Printable", "description": "8-page booklet",
            "tags": ["celebration of life", "memorial"], "price": 10.0, "num_reviews": 12},
    "333": {"title": "Modern Funeral Order of Service", "description": "foldable order",
            "tags": ["order of service", "funeral"], "price": 6.0, "num_reviews": 5},
}


@pytest.fixture
def enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "context_dev_enabled", True)
    monkeypatch.setattr(settings, "context_dev_api_key", "ctxt-test")
    monkeypatch.setattr(ci, "SPEND_LOG", tmp_path / "ctx_spend.jsonl")
    monkeypatch.setattr(ci, "CACHE_FILE", tmp_path / "ctx_cache.json")
    monkeypatch.setattr(llm, "complete_json",
                        lambda *a, **k: ["buyers want a matching keepsake card set",
                                         "no simple non-religious option"])
    return tmp_path


def _mock_apis(monkeypatch, scalls=None, ecalls=None):
    scalls = [] if scalls is None else scalls
    ecalls = [] if ecalls is None else ecalls

    def fake_search(query, *, include_domains=None, max_results=10):
        scalls.append(query)
        return {"results": list(SEARCH_RESULTS["results"]), "credits": 3.0}

    def fake_extract(url, schema, instructions=None):
        ecalls.append(url)
        lid = url.split("/listing/")[1].split("/")[0]
        return {"data": LISTING_DATA.get(lid, {"title": "x"}), "credits": 10.0}

    monkeypatch.setattr(ci, "web_search", fake_search)
    monkeypatch.setattr(ci, "web_extract", fake_extract)
    return scalls, ecalls


def test_enrich_builds_correct_market_intel_block(enabled, monkeypatch):
    _mock_apis(monkeypatch)
    block = ci.CompetitiveEnricher(min_score=0.5).enrich("funeral program", 0.8)

    assert set(block) >= {"saturation", "gap_analysis", "seo_pattern", "competitor_sample"}
    sat = block["saturation"]
    assert sat["listing_count"] is None                  # no Etsy-API market_intel passed
    assert sat["price_median"] == 8.0                    # median([8, 10, 6]) of extracted listings
    assert sat["top_tags"][0] == "memorial"              # most repeated tag across the listings
    assert block["gap_analysis"] == ["buyers want a matching keepsake card set",
                                     "no simple non-religious option"]
    assert isinstance(block["seo_pattern"]["title_len_median"], int)


def test_saturation_reuses_etsy_market_intel_when_given(enabled, monkeypatch):
    """Extends stage 03: when the free Etsy-API market_intel is supplied, saturation reuses it."""
    _mock_apis(monkeypatch)
    mi = {"count": 999, "median_price": 7.5, "top_tags": ["a", "b", "c"]}
    block = ci.CompetitiveEnricher(min_score=0.5).enrich("funeral program", 0.8, market_intel=mi)
    assert block["saturation"] == {"listing_count": 999, "price_median": 7.5,
                                   "top_tags": ["a", "b", "c"]}


def test_gap_analysis_calls_llm_with_listing_text(enabled, monkeypatch):
    _mock_apis(monkeypatch)
    seen = {}

    def fake_llm(system, user, **k):
        seen["system"], seen["user"] = system, user
        return ["gap A"]

    monkeypatch.setattr(llm, "complete_json", fake_llm)
    block = ci.CompetitiveEnricher(min_score=0.5).enrich("funeral program", 0.9)
    assert block["gap_analysis"] == ["gap A"]
    assert "gap" in seen["system"].lower() or "unmet" in seen["system"].lower()
    assert "Funeral Program Template Editable Canva" in seen["user"]   # EXTRACTED listing title is INPUT


def test_originality_guard_blocks_competitor_text():
    block = {"competitor_sample": {
        "titles": ["Funeral Program Template Editable Canva"],
        "descriptions": ["editable 5x7 memorial"], "tags": ["memorial"]}}
    with pytest.raises(ci.OriginalityViolation):                        # copied title verbatim
        ci.assert_original({"title": "Funeral Program Template Editable Canva", "tags": []}, block)
    with pytest.raises(ci.OriginalityViolation):                        # copied a tag verbatim
        ci.assert_original({"title": "orig", "tags": ["memorial"]}, block)
    ci.assert_original({"title": "Warm Keepsake Remembrance Booklet",                # fully original
                        "description": "an original design", "tags": ["keepsake booklet"]}, block)


def test_web_extract_cap_is_enforced(enabled, monkeypatch):
    scalls, ecalls = _mock_apis(monkeypatch)
    e = ci.CompetitiveEnricher(cap=2, min_score=0.0)
    for term in ("alpha", "bravo", "charlie"):
        e.enrich(term, 0.9)
    assert len(ecalls) == 2                              # 3 candidates x3 listings, only 2 paid extracts


def test_cache_prevents_duplicate_calls(enabled, monkeypatch):
    scalls, ecalls = _mock_apis(monkeypatch)
    e = ci.CompetitiveEnricher(min_score=0.0)           # cap defaults to 5 >= 3 listings
    e.enrich("same niche", 0.9)
    e.enrich("same niche", 0.9)                          # identical query + urls
    assert scalls == ["same niche"]                     # search served from cache the 2nd time
    assert len(ecalls) == 3                             # 3 listings extracted once, never re-extracted


def test_credit_spend_logged_with_source_tag(enabled, monkeypatch):
    _mock_apis(monkeypatch)
    ci.CompetitiveEnricher(min_score=0.0).enrich("funeral program", 0.9)
    entries = [json.loads(ln) for ln in ci.SPEND_LOG.read_text().splitlines()]
    assert all(e["source"] == "context_dev" for e in entries)
    kinds = {e["kind"] for e in entries}
    assert "web.search" in kinds and "web.extract" in kinds
    assert ci.total_spend()["credits"] == 3.0 + 3 * 10.0    # 1 search (3) + 3 extracts (30)


def test_ships_dark_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "context_dev_enabled", False)
    s, e = _mock_apis(monkeypatch)
    assert ci.CompetitiveEnricher(min_score=0.0).enrich("x", 1.0) is None
    assert s == [] and e == []                          # disabled -> zero calls


def test_below_score_threshold_is_not_enriched(enabled, monkeypatch):
    s, e = _mock_apis(monkeypatch)
    assert ci.CompetitiveEnricher(min_score=0.6).enrich("x", 0.3) is None
    assert s == [] and e == []                          # cheap discovery first, no spend


def test_request_shapes_match_confirmed_api(enabled, monkeypatch):
    """web.search sends includeDomains; web.extract sends {url, schema} — the confirmed contract."""
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured[url] = {"headers": headers, "json": json}

        class R:
            def raise_for_status(self):
                pass

            def json(self):
                if "search" in url:
                    return {"results": SEARCH_RESULTS["results"]}
                return {"data": LISTING_DATA["111"], "key_metadata": {"credits_consumed": 10}}
        return R()

    monkeypatch.setattr(ci.requests, "post", fake_post)
    ci.web_search("q", include_domains=["etsy.com"])
    ci.web_extract("https://www.etsy.com/listing/111/x", ci.LISTING_SCHEMA)

    assert captured[ci.SEARCH_URL]["json"]["includeDomains"] == ["etsy.com"]
    assert captured[ci.SEARCH_URL]["headers"]["Authorization"].startswith("Bearer ")
    ex = captured[ci.EXTRACT_URL]["json"]
    assert ex["url"].endswith("/listing/111/x") and ex["schema"] == ci.LISTING_SCHEMA


def test_pipeline_facing_view_omits_competitor_sample(enabled, monkeypatch, tmp_path):
    """Structural originality separation: the generation-facing read never exposes competitor text."""
    from etsy_engine import db
    from etsy_engine.models import Trend
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "ci.db"))
    db.init_db()
    tid = db.upsert_trend(Trend(source="test", term="funeral program"))
    _mock_apis(monkeypatch)
    block = ci.CompetitiveEnricher(min_score=0.0).enrich("funeral program", 0.9)
    db.upsert_competitive_intel(tid, block)

    view = db.get_competitive_intel(tid)
    assert "competitor_sample" not in view
    assert "gap_analysis" in view and "saturation" in view and "seo_pattern" in view
