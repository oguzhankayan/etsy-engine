"""The owner-approval gate between routing (architect) and production.

`etsy-engine run` routes trends (PDF -> planned, Canva -> routed) but produces nothing; the owner sees
them via `review` and produces only what they `approve`. These pin: the pending-approval list, that
approving a PDF finalizes it to a draft, that the EV gate still guards approved products (no bypass),
and that approving a Canva product builds its design set.
"""
import pytest

from etsy_engine import db, pipeline
from etsy_engine.config import settings
from etsy_engine.models import BundleItem, Product, Score, Trend


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "appr.db"))
    db.init_db()
    return tmp_path


def _planned_pdf(term, *, demand=0.6, price=8.0, composite=0.6):
    tid = db.upsert_trend(Trend(source="test", term=term))
    db.upsert_score(Score(trend_id=tid, virality=0.5, purchase_intent=0.5, productization=0.5,
                          competition=0.5, longevity=0.5, ip_risk=0.0, composite=composite))
    db.upsert_market_signal(tid, {"count": 1000, "avg_favorites": 5.0, "competition_score": 0.5,
                                  "demand_score": demand, "emerging_niche": 0.0, "emerging_shops": 0},
                            adjusted_score=demand)
    pid = db.insert_product(Product(trend_id=tid, title_concept=term, bundle_type=term.title(),
                                    format="pdf", status="planned"))
    db.insert_bundle_item(BundleItem(product_id=pid, name="Page 1", asset_type="poster"))
    db.upsert_product_intel(pid, "planner", price, [], {})
    return pid


def _routed_canva(term):
    tid = db.upsert_trend(Trend(source="test", term=term))
    return db.route_to_canva(tid, term)


def test_pending_approval_lists_planned_pdf_and_routed_canva(fresh):
    p1 = _planned_pdf("budget planner")
    c1 = _routed_canva("wedding welcome sign")
    by_id = {p["id"]: p for p in db.pending_approval()}
    assert set(by_id) == {p1, c1}
    assert by_id[p1]["format"] == "pdf" and by_id[p1]["pieces"] == 1
    assert by_id[c1]["format"] == "canva" and by_id[c1]["term"] == "wedding welcome sign"


def test_approve_pdf_finalizes_to_draft(fresh, monkeypatch):
    pid = _planned_pdf("budget planner", demand=0.6, price=8.0)          # positive EV -> passes gate
    calls = []
    monkeypatch.setattr(pipeline, "generate_product", lambda pd, **k: calls.append(("gen", pd["id"])))
    monkeypatch.setattr(pipeline, "generate_mockups", lambda pd, **k: calls.append(("mock", pd["id"])))
    monkeypatch.setattr(db, "assets_for_product", lambda _pid: [1])      # completeness ok (1 item)
    monkeypatch.setattr(db, "upsert_listing", lambda listing: calls.append(("listing",)))
    from etsy_engine.publish import publisher
    from etsy_engine.seo import writer
    monkeypatch.setattr(writer, "write_listing", lambda pd: object())
    monkeypatch.setattr(publisher, "publish_product",
                        lambda _pid: calls.append(("publish", _pid)) or {"listing_id": 1})

    res = pipeline.produce_approved([pid])
    assert res["pdf_drafted"] == [pid]
    assert ("gen", pid) in calls and ("mock", pid) in calls and ("publish", pid) in calls


def test_approve_pdf_still_passes_through_ev_gate(fresh, monkeypatch):
    """Approval does NOT bypass the EV gate: a projected-loss product is blocked, never generated."""
    pid = _planned_pdf("dead niche", demand=0.02, price=3.0)
    monkeypatch.setattr(settings, "ev_gate_min", 5.0)
    gen = []
    monkeypatch.setattr(pipeline, "generate_product", lambda pd, **k: gen.append(pd["id"]))

    res = pipeline.produce_approved([pid])
    assert res["blocked"] == [pid] and gen == []
    assert db.product(pid)["status"] == "ev_blocked"


def test_approve_canva_builds_design_set(fresh, monkeypatch):
    cid = _routed_canva("funeral program")
    from etsy_engine.canva import produce as cprod
    seen = []
    monkeypatch.setattr(cprod, "prepare", lambda term, **k: seen.append((term, k.get("product_id"))))

    res = pipeline.produce_approved([cid])
    assert res["canva_prepared"] == [cid]
    assert seen == [("funeral program", cid)]                            # term + product_id threaded


def test_only_approved_products_are_produced(fresh, monkeypatch):
    keep = _planned_pdf("keep me", demand=0.6, price=8.0)
    skip = _planned_pdf("skip me", demand=0.6, price=8.0)
    made = []
    monkeypatch.setattr(pipeline, "generate_product", lambda pd, **k: made.append(pd["id"]))
    monkeypatch.setattr(pipeline, "generate_mockups", lambda pd, **k: None)
    monkeypatch.setattr(db, "assets_for_product", lambda _pid: [1])
    monkeypatch.setattr(db, "upsert_listing", lambda listing: None)
    from etsy_engine.publish import publisher
    from etsy_engine.seo import writer
    monkeypatch.setattr(writer, "write_listing", lambda pd: object())
    monkeypatch.setattr(publisher, "publish_product", lambda _pid: {"listing_id": 1})

    pipeline.produce_approved([keep])                                    # approve only `keep`
    assert made == [keep]                                              # `skip` never produced
    assert skip in {p["id"] for p in db.pending_approval()}            # still awaiting approval
