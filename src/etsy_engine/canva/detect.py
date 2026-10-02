"""Auto-detect which trends suit the Canva-editable line, and route them to it.

TWO axes decide the Canva line. A trend must pass BOTH to route here.

  1. PERSONALIZATION — edit vs use:
     * Canva-editable ONLY when the buyer swaps in their OWN unique data — a name, date, event,
       venue, brand or prices (signs, invitations, weddings, showers, classroom, host/guest,
       announcements, certificates, menus). There an editable template beats a flat PDF.
     * NOT Canva — products the buyer merely FILLS IN or TICKS OFF over time (trackers, checklists,
       planners, logs, journals, bucket lists). Print-and-write (a pen) or an interactive doc;
       opening Canva to tick a box is friction, not value. These stay on the PDF line, exactly like
       pure-image products (coloring, clipart, SVG, patterns).

  2. FORM — single artifact vs cut-apart sheet:
     * This pipeline renders ONE dominant, full-page editable artifact per page. It FITS products
       whose unit-of-use is a full page or larger: signs, invitations, announcements, certificates,
       menus, programs, seating charts, posters, single greeting cards.
     * NOT a fit — "multi-up cut-apart" products: one printed sheet holding MANY small items the
       buyer cuts into pieces (gift/favor tags, place/escort/tent cards, table numbers, stickers,
       labels, cupcake toppers, envelope seals, business cards, bookmarks). Laying out a grid of
       many small, individually-editable items is a capability this one-artifact-per-page pipeline
       lacks, so route them off the Canva line (same spirit as fill-in products going to PDF). A big
       "seating chart" SIGN fits; "seating chart cards" (the small per-guest cards) do not.

Reads the SAME ranked opportunities the PDF architect uses (`db.top_opportunities`).
ADDITIVE: detection only, it never changes the PDF pipeline, and producing a hit still goes
through the human-in-the-loop Canva flow.
"""
from __future__ import annotations

import datetime
import re
from collections import defaultdict

# Seasonal niches peak in one month; everything else is evergreen. A product listed too far ahead
# of its season is dead inventory (a Valentine's set surfaced in July is 7 months early), so scan()
# deprioritizes off-season hits. Sellers front-load ~1-5 months out (Christmas-in-July is the classic
# case), so a season within 5 months keeps full weight; further out (or just-passed) sinks.
_SEASON_MONTH = {
    "valentine": 2, "st patrick": 3, "easter": 4, "mother's day": 5, "mothers day": 5,
    "graduation": 5, "father's day": 6, "fathers day": 6, "fourth of july": 7, "4th of july": 7,
    "back to school": 8, "halloween": 10, "thanksgiving": 11, "christmas": 12, "xmas": 12,
    "hanukkah": 12, "new year": 1,
}


def _season_weight(term: str, month: int | None = None) -> float:
    """1.0 for evergreen or a season within the ~5-month front-load window; 0.2 for off-season."""
    month = month or datetime.date.today().month
    t = " " + (term or "").lower() + " "
    for kw, peak in _SEASON_MONTH.items():
        if kw in t:
            return 1.0 if (peak - month) % 12 <= 5 else 0.2
    return 1.0

# kind -> signal phrases (things buyers edit). Multiword phrases score stronger. Kept deliberately
# BROAD across the whole single-focus editable market (signs, weddings, showers, invitations,
# announcements, menus/programs, certificates, greeting cards, seating charts, business/home signs,
# classroom, wall art) so the line ranges over the market instead of circling a few welcome-signs.
SIGNALS: dict[str, list[str]] = {
    "welcome_sign": ["welcome sign", "welcome poster", "airbnb", "vrbo", "guest welcome",
                     "vacation rental", "house guide", "check out", "wifi", "host", "rental"],
    "wedding": ["wedding", "bridal", "bachelorette", "wedding menu", "wedding program",
                "order of service", "wedding itinerary", "unplugged ceremony", "bar menu",
                "welcome to our wedding", "in loving memory"],
    "seating_chart": ["seating chart", "seating plan", "table plan", "find your seat"],
    "shower_party": ["baby shower", "bridal shower", "birthday party", "party sign", "gender reveal",
                     "party menu", "first birthday", "photo booth sign", "milestone birthday"],
    "invitation": ["invitation", "invite", "rsvp", "save the date", "evite"],
    "announcement": ["birth announcement", "pregnancy announcement", "graduation announcement",
                     "engagement announcement", "moving announcement", "grad announcement",
                     "adoption announcement", "we are expecting"],
    "menu_program": ["menu template", "party menu", "drink menu", "cocktail menu", "dinner menu",
                     "event program", "order of events", "brunch menu",
                     # memorial / celebration-of-life: a large, evergreen, premium editable niche
                     # (8-page Canva funeral programs). Full phrases only — bare "memorial" would
                     # trip on "memorial day".
                     "funeral program", "celebration of life", "memorial program",
                     "memorial service", "in loving memory"],
    "certificate": ["gift certificate", "award certificate", "certificate template",
                    "achievement certificate", "completion certificate"],
    "greeting_card": ["greeting card", "thank you card", "holiday card", "christmas card",
                      "note card", "birthday card"],
    "classroom": ["classroom", "teacher", "bulletin board", "school sign", "student", "class rules"],
    "wall_art_text": ["quote print", "affirmation", "name sign", "family name sign",
                      "typography print", "family established", "nursery print"],
    "sign_business": ["small business", "pricing guide", "menu board", "salon sign", "business sign",
                      "price list", "address sign", "house rules", "flyer", "event poster"],
}

# pure-image / no editable text -> belongs to the PDF line, never route here
EXCLUDE = ["coloring", "clip art", "clipart", "svg", "sublimation", "png bundle", "seamless",
           "digital paper", "pattern", "wallpaper", "background", "sticker sheet", "mockup", "font",
           # flat printable ACTIVITIES belong to the PDF line, not editable Canva templates
           "game", "word search", "bingo", "trivia", "scavenger hunt", "quiz", "puzzle", "activity",
           # USE-personalized: the buyer FILLS IN / TICKS OFF (not swap-my-name) -> PDF, never Canva.
           # This also overrides a co-occurring personalize niche ("baby shower checklist" -> PDF).
           # Keep every entry a FULL phrase, never bare "list"/"chart" — "price list" and "seating
           # chart" are real Canva templates and must survive.
           "tracker", "checklist", "check list", "planner", "journal", "to do list", "to-do list",
           "meal plan", "bucket list", "reading list", "reading log", "chore chart", "reward chart",
           "log book", "logbook", "questionnaire", "fill in the blank", "fill-in-the-blank"]

# FORM axis (see module docstring): multi-up sheets of many small items the buyer cuts apart. A
# one-artifact-per-page renderer can't lay these out, so they leave the Canva line no matter how
# personalizable they are. Matched WHOLE-PHRASE (plural-tolerant) so a substring never trips it
# (e.g. "vintage" must not match "tag"). A big "seating chart" sign survives; its "... cards" do not.
CUT_APART_SHEET = ["gift tag", "favor tag", "hang tag", "thank you tag", "name tag",
                   "place card", "escort card", "tent card", "table number", "table card",
                   "seating card", "seating chart card", "business card", "loyalty card", "punch card",
                   "sticker", "label", "cupcake topper", "envelope seal", "envelope liner",
                   "candy wrapper", "chocolate wrapper", "water bottle label", "address label",
                   "return address", "bookmark", "napkin ring"]

_WORD = re.compile(r"[a-z0-9]+")


def _has(t: str, phrase: str) -> bool:
    """Whole-phrase match, tolerant of a simple trailing plural (SIGNALS are singular but
    Etsy terms are often plural: 'gift tags', 'welcome signs', 'place cards', 'invitations')."""
    return (" " + phrase + " ") in t or (" " + phrase + "s ") in t


def canva_suitability(term: str) -> dict | None:
    """Classify a trend term. Returns {suitable, score, kind, reason} or None if not Canva-line."""
    t = " " + " ".join(_WORD.findall((term or "").lower())) + " "
    if any((" " + x + " ") in t or x in t for x in EXCLUDE):     # axis 1: fill-in / pure-image -> PDF
        return None
    if any(_has(t, p) for p in CUT_APART_SHEET):                 # axis 2: cut-apart sheet -> not a fit
        return None
    best_kind, best, matched = None, 0.0, []
    for kind, phrases in SIGNALS.items():
        hits = [p for p in phrases if _has(t, p)]
        if hits:
            w = sum(2.0 if " " in p else 1.0 for p in hits)
            matched += hits
            if w > best:
                best_kind, best = kind, w
    if not best_kind:
        return None
    return {"suitable": best >= 1.0, "score": round(best, 1), "kind": best_kind,
            "reason": ", ".join(sorted(set(matched))[:4])}


def scan(limit: int = 200, per_kind: int = 2) -> list[dict]:
    """Canva-suitable trends among the current top opportunities, DIVERSIFIED across product kinds.

    Returns the best hit of each kind first, then the second-best of each, and so on (capped at
    `per_kind` per kind). This spreads the shortlist across categories instead of returning eight of
    the same niche, so the operator ranges over the market rather than circling 2-3 products.
    """
    from .. import db

    hits: list[dict] = []
    for o in db.top_opportunities(limit=limit):
        s = canva_suitability(o.get("term", ""))
        if s and s["suitable"]:                # suitability is a GATE, not the rank
            sw = _season_weight(o["term"])
            rank = float(o.get("rank_score") or 0)
            hits.append({**s, "term": o["term"], "rank_score": rank, "season_weight": sw,
                         "eff": round(rank * sw, 4)})
    # Rank by the REAL, season-adjusted TREND strength (rank_score from the opportunity scorer),
    # NOT the canva-suitability keyword-match weight. Otherwise a term whose NAME matches a product
    # type strongly (a "greeting card set" = 2.0 suitability) outranks a genuinely hotter niche, and
    # an off-season niche (Valentine's in July) floats up on name alone. Suitability score is only a
    # tiebreaker now.
    _key = lambda h: (h["eff"], h["score"])  # noqa: E731
    hits.sort(key=_key, reverse=True)

    by_kind: dict[str, list[dict]] = defaultdict(list)     # insertion order = best-first per kind
    for h in hits:
        if len(by_kind[h["kind"]]) < per_kind:
            by_kind[h["kind"]].append(h)
    out: list[dict] = []
    for r in range(max((len(v) for v in by_kind.values()), default=0)):
        tier = [v[r] for v in by_kind.values() if r < len(v)]  # one kind's r-th best across kinds
        tier.sort(key=_key, reverse=True)
        out.extend(tier)
    return out
