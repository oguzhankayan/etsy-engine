"""Keyword pulse: true current-velocity from per-listing view deltas."""
from __future__ import annotations

from etsy_engine.learning import keyword_pulse as kp
from etsy_engine.sources.etsy_velocity import _clean_term


def _batch(ts, rows):
    return [{"listing_id": lid, "views": v, "favorites": f, "captured_at": ts}
            for lid, v, f in rows]


def test_velocity_diffs_same_listing_across_snapshots(monkeypatch):
    day1 = _batch("2026-07-01T08:00:00+00:00",
                  [(1, 1000, 50), (2, 200, 10), (3, 40, 1)])
    # 24h later: listing 1 +120 views, listing 2 +24, listing 3 dropped out,
    # listing 4 is new (no baseline — must be ignored, not treated as +5000).
    day2 = _batch("2026-07-02T08:00:00+00:00",
                  [(1, 1120, 56), (2, 224, 12), (4, 5000, 300)])
    monkeypatch.setattr(kp.db, "pulse_snapshots", lambda kw, last_n_captures=2: [day1, day2])

    v = kp.velocity("world cup")
    assert v["matched_listings"] == 2
    assert v["median_daily_views_now"] == 72.0   # median(120, 24)
    assert v["total_daily_views_now"] == 144.0
    assert v["median_daily_favs_now"] == 4.0     # median(6, 2)


def test_velocity_needs_two_spaced_snapshots(monkeypatch):
    one = _batch("2026-07-01T08:00:00+00:00", [(1, 10, 0)])
    monkeypatch.setattr(kp.db, "pulse_snapshots", lambda kw, last_n_captures=2: [one])
    assert kp.velocity("x") is None

    close = _batch("2026-07-01T09:00:00+00:00", [(1, 12, 0)])  # only 1h apart
    monkeypatch.setattr(kp.db, "pulse_snapshots", lambda kw, last_n_captures=2: [one, close])
    assert kp.velocity("x") is None


def test_clean_term_keeps_ordinals():
    assert _clean_term("4th of July Banner Printable | Party Decor") \
        == "4th of july banner"
    # the original quantity-noise cases must still strip
    assert _clean_term("300 pages! Mega Coloring Book") == "mega coloring book"
    assert _clean_term("Set of 12 Boho Prints") == "boho prints"
