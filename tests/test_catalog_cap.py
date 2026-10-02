"""The catalog cap refuses new Etsy drafts once the shop is at/above a configurable active-listing
count — the guard against the over-built catalog (the profitability audit's #1 leak). The cap is
off by default (0), so it changes no existing behavior until configured.
"""
import pytest

from etsy_engine.config import settings
from etsy_engine.publish import etsy_client as ec, publisher


@pytest.fixture
def no_network(monkeypatch):
    """Fixed shop id + a spy over every Etsy request, so nothing hits the API and we can assert
    exactly which calls were (not) made."""
    monkeypatch.setattr(settings, "etsy_api_key", "k")
    monkeypatch.setattr(settings, "etsy_shop_id", "1")
    calls: list[tuple[str, str]] = []

    def spy(method, path, **kw):
        calls.append((method, path))
        return {"listing_id": 999, "url": "http://x", "listing_active_count": 0}

    monkeypatch.setattr(ec, "request", spy)
    return calls


def test_enforce_raises_at_cap(no_network, monkeypatch):
    monkeypatch.setattr(settings, "catalog_active_cap", 5)
    monkeypatch.setattr(publisher, "active_listing_count", lambda: 5)   # exactly at the cap
    with pytest.raises(publisher.CatalogCapReached):
        publisher.enforce_catalog_cap()


def test_enforce_raises_above_cap(no_network, monkeypatch):
    monkeypatch.setattr(settings, "catalog_active_cap", 5)
    monkeypatch.setattr(publisher, "active_listing_count", lambda: 12)
    with pytest.raises(publisher.CatalogCapReached):
        publisher.enforce_catalog_cap()


def test_enforce_allows_under_cap(no_network, monkeypatch):
    monkeypatch.setattr(settings, "catalog_active_cap", 5)
    monkeypatch.setattr(publisher, "active_listing_count", lambda: 4)
    publisher.enforce_catalog_cap()          # under the cap -> does not raise


def test_default_cap_is_disabled(no_network, monkeypatch):
    """Default 0 disables the gate, so a shop far past any real size still never raises."""
    monkeypatch.setattr(settings, "catalog_active_cap", 0)
    monkeypatch.setattr(publisher, "active_listing_count", lambda: 10_000)
    publisher.enforce_catalog_cap()          # 0 == off -> never raises


def test_publish_product_refuses_at_cap_and_never_posts(no_network, monkeypatch):
    """Integration: publish_product raises at the cap and NEVER POSTs a listing to Etsy."""
    monkeypatch.setattr(settings, "catalog_active_cap", 5)
    monkeypatch.setattr(publisher, "active_listing_count", lambda: 5)

    with pytest.raises(publisher.CatalogCapReached):
        publisher.publish_product(1)

    assert not any(m == "POST" and p.endswith("/listings") for m, p in no_network)


def test_active_count_reads_live_shop_then_falls_back(monkeypatch):
    """active_listing_count prefers the live Etsy shop count; on failure it falls back to the DB."""
    monkeypatch.setattr(settings, "etsy_shop_id", "1")
    monkeypatch.setattr(ec, "request", lambda *a, **k: {"listing_active_count": 42})
    assert publisher.active_listing_count() == 42

    def boom(*a, **k):
        raise ec.EtsyError("shop call down")

    monkeypatch.setattr(ec, "request", boom)
    monkeypatch.setattr(publisher.db, "products_with_listings",
                        lambda: [{"state": "active"}, {"state": "active"}, {"state": "draft"}])
    assert publisher.active_listing_count() == 2      # DB fallback counts only active
