"""`etsy-engine demo` runs the real stages for one niche and writes listing.md — no Etsy."""
import json

from etsy_engine import pipeline
from etsy_engine.config import settings
from etsy_engine.models import BundleItem, Listing, Product


def test_demo_caps_pages_and_writes_listing(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "anthropic_api_key", "x")
    monkeypatch.setattr(settings, "raywake_api_key", "y")
    monkeypatch.setattr("etsy_engine.config.OUTPUT_DIR", tmp_path)

    def fake_build(trend_id, term, rationale):
        prod = Product(trend_id=trend_id, title_concept=f"{term} kit", bundle_type="Kit")
        items = [BundleItem(product_id=0, name=f"Page {i}", asset_type="tracker", spec="s") for i in range(7)]
        return prod, items, {"archetype": "planner"}

    seen = {}
    monkeypatch.setattr(pipeline, "build_product", fake_build)
    monkeypatch.setattr(pipeline, "generate_product",
                        lambda pd, variations=1: seen.setdefault("pages", len(pd["items"])))
    monkeypatch.setattr(pipeline, "generate_mockups", lambda pd: 3)
    monkeypatch.setattr(pipeline, "write_listing", lambda pd: Listing(
        product_id=pd["id"], title="Teacher Kit", tags=json.dumps(["teacher", "printable"]),
        description="desc"))

    r = pipeline.demo("teacher week", max_pages=4)
    assert seen["pages"] == 4
    assert r["images"] == 0 and r["credits"] == 0
    md = (tmp_path / str(r["product_id"]) / "listing.md").read_text()
    assert "Teacher Kit" in md and "teacher, printable" in md
