"""`prune` finds active listings still unproven after 30 days (< 20 views AND < 2 favorites) and
marks them for deactivation — a DB flag only, NEVER an Etsy call. These pin the selection criteria,
the mark + count, the non-destructive contract, and the boundaries.
"""
import datetime

import pytest

from etsy_engine import db
from etsy_engine.config import settings
from etsy_engine.learning import prune
from etsy_engine.models import Product, Trend


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "prune.db"))
    db.init_db()
    return tmp_path


def _listing(term, *, listing_id, views, favorites, age_days, state="active", sales=0):
    """Insert an active/draft listing of a given age with a latest metric snapshot."""
    tid = db.upsert_trend(Trend(source="test", term=term))
    pid = db.insert_product(Product(trend_id=tid, title_concept=term, bundle_type=term.title()))
    db.upsert_etsy_listing(pid, listing_id, "http://x", state=state)
    created = (datetime.datetime.now(datetime.UTC)
               - datetime.timedelta(days=age_days)).isoformat()
    with db.connect() as c:                       # upsert stamps created_at=now(); age it back
        c.execute("UPDATE etsy_listings SET created_at=? WHERE etsy_listing_id=?",
                  (created, listing_id))
    db.insert_metric(listing_id, views=views, favorites=favorites, sales=sales)
    return listing_id


def test_selects_only_unproven_and_old(fresh_db):
    dead = _listing("dead niche", listing_id=100, views=5, favorites=0, age_days=45)     # prune
    _listing("viewed niche", listing_id=101, views=30, favorites=0, age_days=45)         # views >= 20
    _listing("faved niche", listing_id=102, views=3, favorites=3, age_days=45)           # favs >= 2
    _listing("newborn niche", listing_id=103, views=0, favorites=0, age_days=10)         # too young
    _listing("draft niche", listing_id=104, views=0, favorites=0, age_days=45, state="draft")  # inactive

    assert [r["etsy_listing_id"] for r in prune.find_prunable()] == [dead]


def test_mark_sets_flag_and_returns_count(fresh_db):
    dead = _listing("dead niche", listing_id=200, views=1, favorites=0, age_days=60)
    n = prune.mark_for_deactivation(prune.find_prunable())
    assert n == 1
    with db.connect() as c:
        flag = c.execute(
            "SELECT marked_for_deactivation FROM etsy_listings WHERE etsy_listing_id=?",
            (dead,)).fetchone()[0]
    assert flag == 1


def test_never_calls_the_etsy_api(fresh_db, monkeypatch):
    """Non-destructive contract: prune reads metrics + sets a flag, and must NOT hit Etsy."""
    from etsy_engine.publish import etsy_client as ec

    def boom(*a, **k):
        raise AssertionError("prune must never call the Etsy API")

    monkeypatch.setattr(ec, "request", boom)
    _listing("dead niche", listing_id=300, views=0, favorites=1, age_days=90)
    assert prune.mark_for_deactivation(prune.find_prunable()) == 1   # no exception == no API call


def test_boundaries(fresh_db):
    """< 20 views AND < 2 favorites AND >= 30 days: 19v/1f at 31d prunes; 20v, 2f, or 29d do not."""
    edge = _listing("edge", listing_id=400, views=19, favorites=1, age_days=31)
    _listing("exactly-20-views", listing_id=401, views=20, favorites=0, age_days=40)
    _listing("exactly-2-favs", listing_id=402, views=0, favorites=2, age_days=40)
    _listing("just-too-young", listing_id=403, views=0, favorites=0, age_days=29)

    assert [r["etsy_listing_id"] for r in prune.find_prunable()] == [edge]
