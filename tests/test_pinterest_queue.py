"""Direct-Pinterest local queue: time-spread publish semantics."""
from __future__ import annotations

from datetime import datetime, timedelta, UTC

from etsy_engine.marketing import pinterest


def _row(due, title="t"):
    return {"due": due.isoformat(), "board_id": "b1", "title": title,
            "description": "d", "link": "https://etsy.com/listing/1",
            "image_path": "/tmp/x.jpg", "alt_text": ""}


def test_publish_due_only_past_pins(monkeypatch, tmp_path):
    monkeypatch.setattr(pinterest, "QUEUE_FILE", tmp_path / "q.jsonl")
    now = datetime.now(UTC)
    pinterest._write_queue([
        _row(now - timedelta(minutes=5), "past"),
        _row(now + timedelta(hours=2), "future"),
    ])
    published = []
    monkeypatch.setattr(pinterest, "create_pin",
                        lambda **kw: published.append(kw["title"]) or {"id": "p1"})

    assert pinterest.publish_due() == 1
    assert published == ["past"]
    remaining = pinterest._read_queue()
    assert [r["title"] for r in remaining] == ["future"]


def test_failed_pin_stays_queued(monkeypatch, tmp_path):
    monkeypatch.setattr(pinterest, "QUEUE_FILE", tmp_path / "q.jsonl")
    now = datetime.now(UTC)
    pinterest._write_queue([_row(now - timedelta(minutes=1), "will-fail")])

    def boom(**kw):
        raise pinterest.PinterestError("401")

    monkeypatch.setattr(pinterest, "create_pin", boom)
    assert pinterest.publish_due() == 0
    assert [r["title"] for r in pinterest._read_queue()] == ["will-fail"]


def test_publish_limit_keeps_cadence(monkeypatch, tmp_path):
    monkeypatch.setattr(pinterest, "QUEUE_FILE", tmp_path / "q.jsonl")
    now = datetime.now(UTC)
    pinterest._write_queue([_row(now - timedelta(minutes=i + 1), f"p{i}")
                            for i in range(5)])
    monkeypatch.setattr(pinterest, "create_pin", lambda **kw: {"id": "x"})

    assert pinterest.publish_due(limit=2) == 2
    assert len(pinterest._read_queue()) == 3
