"""Storefront lifecycle, renewal, and profile regression coverage."""
from __future__ import annotations

from etsy_engine import db, pipeline
from etsy_engine.publish import shop_profile


def test_listing_state_maps_out_of_generation_queues():
    assert db.product_status_for_listing_state("active", "generated") == "published"
    assert db.product_status_for_listing_state("edit", "qc_passed") == "drafted"
    assert db.product_status_for_listing_state("draft", "planned") == "drafted"


def test_deleted_draft_stays_deleted():
    assert db.product_status_for_listing_state("edit", "deleted") is None
    assert db.product_status_for_listing_state("inactive", "generated") is None


def test_proven_listing_thresholds_include_sales_views_or_favorites():
    assert pipeline._is_proven_listing({"sales": 1, "views": 1, "favorites": 0})
    assert pipeline._is_proven_listing({"sales": 0, "views": 20, "favorites": 0})
    assert pipeline._is_proven_listing({"sales": 0, "views": 1, "favorites": 2})
    assert not pipeline._is_proven_listing({"sales": 0, "views": 19, "favorites": 1})


def test_shop_profile_preview_and_apply(monkeypatch):
    calls = []

    def fake_request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "GET":
            return {key: "old" for key in shop_profile.PROFILE}
        return {}

    monkeypatch.setattr(shop_profile.settings, "etsy_shop_id", "123")
    monkeypatch.setattr(shop_profile.ec, "request", fake_request)

    preview = shop_profile.update_shop_profile(dry_run=True)
    assert set(preview["changes"]) == set(shop_profile.PROFILE)
    assert [call[0] for call in calls] == ["GET"]

    applied = shop_profile.update_shop_profile(dry_run=False)
    assert set(applied["changes"]) == set(shop_profile.PROFILE)
    assert calls[-1] == ("PUT", "/shops/123", {"data": shop_profile.PROFILE})
