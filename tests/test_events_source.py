"""Event-calendar source: buyer-window activation + virality floor."""
from __future__ import annotations

import json
from datetime import date

from etsy_engine.models import Tier
from etsy_engine.scoring.scorer import _virality_floor
from etsy_engine.sources import events


def test_active_events_respects_buyer_window():
    active = {e["name"] for e in events.active_events(date(2026, 7, 2))}
    assert "world cup 2026" in active            # event running now
    assert "total solar eclipse europe" in active  # 6-week prep window open
    assert "eurovision 2027" not in active        # far future

    # After the event ends it must drop out.
    after = {e["name"] for e in events.active_events(date(2026, 7, 25))}
    assert "world cup 2026" not in after


def test_fetch_emits_seeds_with_event_payload(monkeypatch):
    monkeypatch.setattr(events, "_today", lambda: date(2026, 7, 2))
    trends = events.EventCalendarSource().fetch(50)
    assert trends, "world cup + eclipse windows are open on 2026-07-02"
    wc = [t for t in trends if json.loads(t.raw_payload)["event"] == "world cup 2026"]
    assert wc and all(t.tier == Tier.VIRAL for t in wc)  # running => viral tier
    assert json.loads(wc[0].raw_payload)["days_to_peak"] == 0


def test_event_proximity_floors_virality():
    running = json.dumps({"kind": "event", "days_to_peak": 0})
    soon = json.dumps({"kind": "event", "days_to_peak": 20})
    far = json.dumps({"kind": "event", "days_to_peak": 40})
    too_far = json.dumps({"kind": "event", "days_to_peak": 90})
    assert _virality_floor(running) >= 0.85
    assert _virality_floor(soon) >= 0.7
    assert _virality_floor(far) >= 0.55
    assert _virality_floor(too_far) == 0.0
