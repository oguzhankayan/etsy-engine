"""The run_log gives post-hoc failure visibility: every run records (stage, status, timestamp). The
`smoke` command exercises the live publish path by creating one throwaway draft and deleting it —
here we prove that create-then-delete shape with a stubbed API (no network, no real listing touched).
"""
import datetime

import pytest

from etsy_engine import db
from etsy_engine.config import settings
from etsy_engine.publish import etsy_client as ec, publisher


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "runlog.db"))
    db.init_db()
    return tmp_path


def test_run_log_records_stage_status_timestamp(fresh_db):
    db.log_run("collect", "ok")
    db.log_run("score", "ok", detail="25 scored")
    db.log_run("generate", "failed", detail="boom")

    rows = db.run_log()
    assert len(rows) == 3
    top = rows[0]                                          # newest first
    assert {"stage", "status", "created_at"} <= set(top)
    assert top["stage"] == "generate" and top["status"] == "failed" and top["detail"] == "boom"
    datetime.datetime.fromisoformat(top["created_at"])     # timestamp is real + parseable


def test_run_log_orders_newest_first(fresh_db):
    for st in ("collect", "score", "validate", "architect"):
        db.log_run(st, "ok")
    assert [r["stage"] for r in db.run_log()] == ["architect", "validate", "score", "collect"]


def test_log_run_is_best_effort_never_raises(fresh_db, monkeypatch):
    """Observability must not break the pipeline: a logging failure is swallowed."""
    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(db, "connect", boom)
    db.log_run("collect", "ok")                            # must not raise


def _stub_etsy(monkeypatch):
    monkeypatch.setattr(settings, "etsy_api_key", "k")
    monkeypatch.setattr(settings, "etsy_shop_id", "1")
    calls: list[tuple[str, str]] = []

    def spy(method, path, **kw):
        calls.append((method, path))
        return {"listing_id": 555} if method == "POST" else {}

    monkeypatch.setattr(ec, "request", spy)
    return calls


def test_smoke_draft_creates_then_deletes(monkeypatch):
    calls = _stub_etsy(monkeypatch)
    lid = publisher.smoke_draft()
    assert lid == 555
    # create is shop-scoped; Etsy's deleteListing is application-scoped (/listings/{id})
    assert calls == [("POST", "/shops/1/listings"), ("DELETE", "/listings/555")]


def test_smoke_draft_touches_no_product_or_listing_rows(fresh_db, monkeypatch):
    """The smoke draft is isolated: it writes NO product/listing row, so real listings are untouched."""
    _stub_etsy(monkeypatch)
    publisher.smoke_draft()
    with db.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM etsy_listings").fetchone()[0] == 0


def test_smoke_surfaces_id_when_delete_fails(monkeypatch):
    """If the created draft can't be deleted, the id is surfaced so a human can clean it up."""
    monkeypatch.setattr(settings, "etsy_api_key", "k")
    monkeypatch.setattr(settings, "etsy_shop_id", "1")

    def spy(method, path, **kw):
        if method == "POST":
            return {"listing_id": 777}
        raise ec.EtsyError("delete blew up")

    monkeypatch.setattr(ec, "request", spy)
    with pytest.raises(ec.EtsyError, match="777"):
        publisher.smoke_draft()
