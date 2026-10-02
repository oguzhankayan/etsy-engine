"""Event-calendar source — scheduled cultural/sports moments as trend seeds.

The shop's all-time top performer (World Cup 2026 bundle) was caught by luck
from the daily RSS feed; this source makes that systematic. Big scheduled
events are the ONE trend category we can see coming months ahead, so we emit
their seed phrases during the buyer prep window (Etsy shoppers buy ~4-6 weeks
early) and keep them flowing through the event itself.

Scope: one-off / date-anchored events only. Annual retail holidays (Halloween,
Christmas, Mother's Day, back to school...) are owned by seeds.SEASONAL — do
not duplicate them here.

All seed phrases are generic and trademark-free (no official event names in
product copy beyond nominative use in search terms; downstream IP gate + prompt
guidance keep the designs logo-free).

Curated list — extend it as new years' calendars firm up.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, UTC

from ..models import Tier, Trend
from .base import BaseSource

DEFAULT_LEAD_WEEKS = 6

# Each event: start/end (the event window; end = start for one-day events),
# lead_weeks (how early buyers start shopping), seeds (Etsy search phrases).
EVENTS: list[dict] = [
    {
        "name": "world cup 2026",
        "start": "2026-06-11", "end": "2026-07-19", "lead_weeks": 6,
        "seeds": [
            "world cup party printable", "soccer bracket printable",
            "world cup final watch party games", "soccer coloring pages kids",
            "country flag wall art print", "football party decorations printable",
        ],
    },
    {
        "name": "total solar eclipse europe",
        "start": "2026-08-12", "end": "2026-08-12", "lead_weeks": 6,
        "seeds": [
            "solar eclipse party printable", "eclipse viewing party kit",
            "solar eclipse wall art", "eclipse countdown printable",
            "eclipse activity pages kids",
        ],
    },
    {
        "name": "us midterm elections 2026",
        "start": "2026-11-03", "end": "2026-11-03", "lead_weeks": 6,
        "seeds": [
            "election night party printable", "election watch party games",
            "patriotic wall art print", "voting sticker printable",
        ],
    },
    {
        "name": "dia de los muertos 2026",
        "start": "2026-11-01", "end": "2026-11-02", "lead_weeks": 6,
        "seeds": [
            "day of the dead printable decor", "sugar skull coloring pages",
            "dia de los muertos party printable", "day of the dead table signs",
        ],
    },
    {
        "name": "lunar new year 2027",
        "start": "2027-02-17", "end": "2027-02-17", "lead_weeks": 5,
        "seeds": [
            "lunar new year printable decor", "year of the goat wall art",
            "chinese new year party printable", "red envelope printable",
        ],
    },
    {
        "name": "big game football 2027",  # Super Bowl LXI — generic phrasing
        "start": "2027-02-14", "end": "2027-02-14", "lead_weeks": 5,
        "seeds": [
            "football party printable", "game day squares printable",
            "football watch party games", "game day food labels printable",
        ],
    },
    {
        "name": "march madness 2027",  # college basketball tournament — generic
        "start": "2027-03-16", "end": "2027-04-05", "lead_weeks": 4,
        "seeds": [
            "basketball bracket printable", "basketball party printable",
            "march bracket party games",
        ],
    },
    {
        "name": "kentucky derby 2027",
        "start": "2027-05-01", "end": "2027-05-01", "lead_weeks": 5,
        "seeds": [
            "derby party printable", "horse race party games printable",
            "derby hat party decor",
        ],
    },
    {
        "name": "eurovision 2027",
        "start": "2027-05-11", "end": "2027-05-15", "lead_weeks": 5,
        "seeds": [
            "eurovision party printable", "song contest scorecard printable",
            "eurovision bingo printable",
        ],
    },
    {
        "name": "womens world cup 2027",
        "start": "2027-06-24", "end": "2027-07-25", "lead_weeks": 6,
        "seeds": [
            "womens soccer party printable", "soccer bracket printable",
            "girls soccer wall art print",
        ],
    },
]


def _today() -> date:
    return datetime.now(UTC).date()


def _parse(d: str) -> date:
    return date.fromisoformat(d)


def active_events(today: date | None = None) -> list[dict]:
    """Events whose buyer window [start - lead_weeks, end] contains today."""
    today = today or _today()
    out = []
    for ev in EVENTS:
        start, end = _parse(ev["start"]), _parse(ev["end"])
        lead = timedelta(weeks=ev.get("lead_weeks", DEFAULT_LEAD_WEEKS))
        if start - lead <= today <= end:
            out.append(ev)
    return out


def days_to_peak(ev: dict, today: date | None = None) -> int:
    """Days until the event starts (0 while the event is running)."""
    today = today or _today()
    return max(0, (_parse(ev["start"]) - today).days)


class EventCalendarSource(BaseSource):
    name = "events"

    def fetch(self, limit: int) -> list[Trend]:
        today = _today()
        trends: list[Trend] = []
        for ev in active_events(today):
            dtp = days_to_peak(ev, today)
            for seed in ev["seeds"]:
                payload = json.dumps({
                    "kind": "event", "event": ev["name"],
                    "days_to_peak": dtp,
                    "event_start": ev["start"], "event_end": ev["end"],
                })
                # During/near the event it's a viral moment; earlier it's seasonal prep.
                tier = Tier.VIRAL if dtp <= 14 else Tier.SEASONAL
                trends.append(Trend(source=self.name, term=seed,
                                    raw_payload=payload, tier=tier))
        return trends[:limit]
