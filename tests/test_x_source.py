"""The X (Twitter) trend source: Grok x_search via OpenRouter's native web_search server tool.

It is ADDITIVE and follows the same BaseSource contract as every other collector, so its trends run
the identical funnel (collect -> score -> validate -> architect -> EV gate -> generate). These tests
pin: the Trend shape, the correct server-tool schema (native engine, NOT the deprecated plugins/
:online forms), fail-soft behavior, registration, and that a fetched trend flows into `collect`.
The EV gate is source-agnostic and untouched, so an X trend cannot skip it — it only emits Trend rows.
"""
import json

from etsy_engine.config import settings
from etsy_engine.models import Tier
from etsy_engine.sources import ENABLED_SOURCES, x_trends


def _fake_resp(content, status=200):
    class R:
        def raise_for_status(self):
            if status >= 400:
                raise RuntimeError(f"HTTP {status}")

        def json(self):
            return {"choices": [{"message": {"content": content}}]}
    return R()


def test_registered_in_enabled_sources():
    assert ENABLED_SOURCES.get("x") is x_trends.XTrendsSource


def test_fetch_parses_x_trends_and_sends_native_server_tool(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "sk-or-test")
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return _fake_resp('[{"term":"trunk or treat invitation","why":"halloween hype"},'
                          '{"term":"eras tour party printable","why":"concert trend"}]')

    monkeypatch.setattr(x_trends.requests, "post", fake_post)
    trends = x_trends.XTrendsSource().fetch(5)

    assert [t.term for t in trends] == ["trunk or treat invitation", "eras tour party printable"]
    assert all(t.source == "x" for t in trends)                       # same shape as every source
    assert all(int(t.tier) == int(Tier.VIRAL) for t in trends)
    assert json.loads(trends[0].raw_payload)["why"] == "halloween hype"
    # the EXACT server-tool schema the goal requires — native engine, no deprecated forms
    assert captured["json"]["tools"] == [
        {"type": "openrouter:web_search", "parameters": {"engine": "native"}}]
    assert captured["json"]["model"] == settings.openrouter_model
    assert "plugins" not in captured["json"]
    assert captured["url"].endswith("/chat/completions")


def test_fetch_without_key_is_soft(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    assert x_trends.XTrendsSource().fetch(5) == []


def test_fetch_on_network_error_is_soft(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "k")

    def boom(*a, **k):
        raise ConnectionError("openrouter down")

    monkeypatch.setattr(x_trends.requests, "post", boom)
    assert x_trends.XTrendsSource().fetch(5) == []                    # never raises (BaseSource contract)


def test_parse_items_handles_fences_and_wrappers():
    assert x_trends._parse_items('```json\n[{"term":"a"}]\n```') == [{"term": "a"}]
    assert x_trends._parse_items('{"trends":[{"term":"b"}]}') == [{"term": "b"}]
    assert x_trends._parse_items("not json at all") == []


def test_fetch_dedups_and_limits(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "k")
    monkeypatch.setattr(x_trends.requests, "post",
                        lambda *a, **k: _fake_resp('[{"term":"X"},{"term":"x"},{"term":"Y"},{"term":"Z"}]'))
    trends = x_trends.XTrendsSource().fetch(2)
    assert [t.term for t in trends] == ["X", "Y"]                     # deduped (X/x), limited to 2


def test_x_trend_flows_into_collect(monkeypatch, tmp_path):
    """End to end into the funnel: collect() stores an X trend just like any other source's, so it
    proceeds to scoring and the EV gate downstream with no special-casing."""
    from etsy_engine import db, pipeline
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "x.db"))
    monkeypatch.setattr(settings, "openrouter_api_key", "k")
    monkeypatch.setattr(x_trends.requests, "post",
                        lambda *a, **k: _fake_resp('[{"term":"cottagecore wedding welcome sign"}]'))
    db.init_db()

    stored = pipeline.collect(sources=["x"])
    assert stored == 1
    with db.connect() as c:
        rows = c.execute("SELECT term, source FROM trends WHERE source='x'").fetchall()
    assert [dict(r)["term"] for r in rows] == ["cottagecore wedding welcome sign"]
