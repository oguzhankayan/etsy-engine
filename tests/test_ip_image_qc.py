"""Tests for the image-level IP/trademark safety check (the only gate on the actual pixels)."""
from __future__ import annotations

from etsy_engine.config import settings
from etsy_engine.generate import qc


def test_ip_safety_flags_a_real_mark_above_confidence(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(qc, "_prep_for_qc", lambda b: (b, "image/jpeg"))
    monkeypatch.setattr(qc, "vision_json",
                        lambda s, u, b, media_type=None: {"has_ip": True,
                                                          "what": "FIFA World Cup trophy",
                                                          "confidence": 0.9})
    r = qc.assess_ip_safety(b"img", context="world cup soccer print")
    assert r["status"] == "flagged" and r["flagged"] is True
    assert "trophy" in r["what"].lower()


def test_ip_safety_ignores_low_confidence_generic_art(monkeypatch):
    """A generic bear/ball must not trip the gate (vision is noisy) — needs >=0.6 confidence."""
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(qc, "_prep_for_qc", lambda b: (b, "image/jpeg"))
    monkeypatch.setattr(qc, "vision_json",
                        lambda s, u, b, media_type=None: {"has_ip": True, "what": "maybe a bear",
                                                          "confidence": 0.3})
    r = qc.assess_ip_safety(b"img")
    assert r["flagged"] is False and r["status"] == "clean"


def test_ip_safety_fails_open_without_key(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    r = qc.assess_ip_safety(b"img", context="anything")
    assert r["status"] == "skipped" and r["flagged"] is False


def test_ip_safety_fails_open_on_vision_error(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(qc, "_prep_for_qc", lambda b: (b, "image/jpeg"))
    def boom(*a, **k):
        raise RuntimeError("vision down")
    monkeypatch.setattr(qc, "vision_json", boom)
    r = qc.assess_ip_safety(b"img")
    assert r["status"] == "skipped" and r["flagged"] is False
