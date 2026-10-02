"""Seed management for trend discovery (Faz: detection upgrades B + D).

Seed pools feed discovery (Google + product ideas):
- EVERGREEN: always-on niches with steady printable demand.
- PERSONALIZABLE: the swap-my-name editable market the CANVA line serves (signs, invitations,
  weddings, showers, announcements, menus, memorials) — kept separate so the funnel can't starve
  the Canva line the way it did when every pool was fill-in/print PDF.
- OCCUPATIONS / PINTEREST: high-intent work niches + the annual Pinterest Predicts forecast.
- SEASONAL: holiday/event seeds, activated by the calendar with BUYER LEAD TIME
  (Etsy shoppers buy ~4-6 weeks early, so we prep ahead of the peak month).
- DYNAMIC: winners from past runs, fed back as new seeds (self-learning).

`active_seeds()` returns the union for the current month.
"""
from __future__ import annotations

import json
from datetime import datetime, UTC

from ..config import DATA_DIR

DYNAMIC_SEEDS_FILE = DATA_DIR / "seeds.json"
SEED_ROTATION_FILE = DATA_DIR / "seed_rotation.json"
MAX_DYNAMIC = 60

EVERGREEN = [
    "printable planner", "budget planner", "meal planner", "cleaning checklist",
    "habit tracker", "reading log", "chore chart", "kids activities",
    "homeschool worksheets", "teacher resources", "classroom decor",
    "wall art printable", "wedding printables", "baby shower games",
    "gardening planner", "camping", "fitness planner", "self care",
    "adhd planner", "gratitude journal",
]

# Pinterest Predicts 2026 — the annual "not-yet-trending" forecast. Etsy buyers ≈
# Pinterest users, so these are early trend signals. CURATED by hand (annual list,
# no scraping): only the digital-printable-productizable trends are kept, mapped to
# Etsy search phrases. Source: Pinterest Predicts 2026 trend report.
# Refresh once a year when the new report drops. Growth %s are from the report.
PINTEREST_PREDICTS_2026 = [
    # Neo Deco (Home) — Art Deco modern revival: chevrons, fan arches, brass/glam
    "art deco wall art", "neo deco print", "geometric deco poster",
    # Afrohemian Decor (Home) — African + boho fusion (+220%)
    "african boho wall art", "afro chic home decor print", "ethiopian art print",
    # FunHaus (Home) — circus-inspired decor (circus interior +150%)
    "vintage circus wall art", "circus nursery art",
    # Extra Celestial (Home/Beauty) — iridescent celestial
    "celestial wall art", "iridescent moon print",
    # Vamp Romantic (Beauty→aesthetic) — dark gothic romance
    "gothic romantic wall art", "dark romantic decor print",
    # Opera Aesthetic (Celebrations) — baroque, dramatic, maximalist
    "baroque wall art", "opera theatre poster",
    # Mystic Outlands (Travel→moody nature)
    "misty forest wall art", "foggy woodland print",
    # Cool Blue (cross-category color story)
    "cool blue abstract wall art",
    # Poetcore (Hobbies) — poetry / literary
    "poetry wall art", "literary quote print",
    # Pen Pals (Hobbies/Wellbeing) — letter writing / stationery (very Etsy)
    "printable stationery set", "letter writing kit printable",
    # Cabbage Crush (Food→cottagecore veg)
    "cottagecore vegetable print", "kitchen veggie wall art",
    # Khaki Coded (neutral earthy palette)
    "earthy neutral wall art",
    # Throwback Kid (Parenting) — nostalgic retro kids
    "retro kids room art", "nostalgic nursery print",
]

# Occupation niches — the shop's #2 all-time performer (Sunflower Classroom
# Decor, 84 views / 5 favs) is an occupation product, and the cleaning-business
# kit also drew early favorites. People buying FOR THEIR WORK have concrete
# needs, search specific phrases, and face thinner competition than "planner".
OCCUPATIONS = [
    "teacher classroom decor", "substitute teacher binder", "teacher planner printable",
    "nurse planner printable", "nurse appreciation printable",
    "therapist office decor", "counselor worksheets printable",
    "speech therapy printable", "social worker printable",
    "cleaning business forms", "housekeeper checklist printable",
    "real estate agent printable", "realtor open house printable",
    "babysitter info sheet", "daycare forms printable", "preschool teacher printable",
    "pet sitter forms printable", "dog walker log printable",
    "photographer client forms", "hair stylist price list printable",
    "coach practice planner", "tutor planner printable",
    "wedding planner printable business", "small business order forms printable",
]

# PERSONALIZABLE ("swap-my-name") — the editable-template market the CANVA LINE exists to serve
# (signs, invitations, weddings, showers, announcements, menus/programs, memorials, certificates).
# This pool was the missing piece: EVERGREEN/OCCUPATIONS/PINTEREST/product_ideas are ~95% fill-in or
# pure-print PDF, so the discovery funnel never fed the Canva line and the architect had almost
# nothing personalizable to route (a live top-40 scan surfaced 0 Canva-suitable trends). Terms AND
# their order are Etsy-API-validated against the live "canva" market (scoring.etsy_market, 2026-07-07)
# + the owner's market screenshots: lead with the proven premium openings — wedding welcome signs
# (~$33 median, small shops still climbing) and family name signs (~$46) — then weddings, showers,
# first/milestone & seasonal birthday invitations, funeral/celebration-of-life programs (a large,
# evergreen, premium niche: 8-page Canva funeral programs), announcements, menus, certificates and
# single-page business collateral. EVERY entry routes CANVA via canva.detect (verified by test).
PERSONALIZABLE = [
    # signs — highest demand-per-listing and the top prices in the scan
    "wedding welcome sign", "family name sign", "custom name sign", "welcome sign template",
    "birthday party sign", "milestone birthday sign",
    # weddings — the single biggest block on the live "canva newest" page
    "wedding program template", "wedding menu template", "wedding seating chart sign",
    "wedding itinerary template", "bachelorette itinerary template", "save the date template",
    # showers & birthday invitations (first-birthday and adult-milestone both sell hard)
    "bridal shower invitation", "baby shower invitation", "gender reveal invitation",
    "first birthday invitation", "milestone birthday invitation", "kids birthday invitation",
    # celebration-of-life / memorial — evergreen, premium, emotionally durable (funeral programs)
    "funeral program template", "celebration of life template", "memorial program template",
    # announcements
    "pregnancy announcement template", "birth announcement template", "graduation announcement",
    # menus / certificates / single-page business collateral
    "party menu template", "gift certificate template", "price list template", "real estate flyer",
]

# Each event: prep months include lead time (peak month minus ~1-2). Month = 1-12.
SEASONAL = [
    {"name": "new year resolutions", "months": [12, 1],
     "seeds": ["new year resolution", "2026 goal planner", "vision board kit"]},
    {"name": "valentines", "months": [1, 2],
     "seeds": ["valentines printable", "valentine cards kids", "galentines"]},
    {"name": "easter", "months": [2, 3, 4],
     "seeds": ["easter printable", "easter egg hunt", "easter basket tags"]},
    {"name": "mothers day", "months": [4, 5],
     "seeds": ["mothers day printable", "mom coupon book", "mothers day card"]},
    {"name": "graduation", "months": [4, 5, 6],
     "seeds": ["graduation party", "graduation printable", "grad announcement",
               "graduation invitation", "graduation party sign"]},
    {"name": "fathers day", "months": [5, 6],
     "seeds": ["fathers day printable", "dad coupon book", "fathers day card"]},
    {"name": "summer", "months": [5, 6, 7],
     "seeds": ["summer bucket list", "summer reading", "kids summer activities",
               "road trip games", "summer camp"]},
    {"name": "back to school", "months": [6, 7, 8],
     "seeds": ["back to school", "teacher planner", "student planner",
               "classroom labels", "homework chart",
               "teacher welcome sign", "meet the teacher template"]},
    # Q4 is the year's biggest window; Etsy shops that list early accrue search /
    # sales history before the peak (operator insight, Berkay). We deliberately
    # widen the Q4 prep months so Halloween/Thanksgiving/Christmas seeds start
    # flowing in late summer rather than the peak month itself.
    {"name": "halloween", "months": [7, 8, 9, 10],
     "seeds": ["halloween printable", "halloween party games", "trick or treat",
               "halloween party invitation", "trunk or treat invitation"]},
    {"name": "thanksgiving", "months": [8, 9, 10, 11],
     "seeds": ["thanksgiving printable", "gratitude printable", "fall planner",
               "thanksgiving menu template", "friendsgiving invitation"]},
    {"name": "christmas", "months": [8, 9, 10, 11, 12],
     "seeds": ["christmas planner", "elf printables", "christmas games",
               "holiday gift tags", "advent calendar",
               "christmas party invitation", "holiday party menu"]},
]


def _now_month() -> int:
    return datetime.now(UTC).month


# Words too generic to identify a season on their own — they recur across events
# or across the whole catalog, so matching on them causes false positives (a garden
# "calendar" is not Christmas; a "coupon" book is not inherently Mother's Day).
_SEASON_STOPWORDS = {
    # cross-catalog product/format words
    "printable", "printables", "card", "cards", "kit", "planner", "book",
    "log", "tracker", "chart", "list", "bundle", "poster", "print", "wall",
    "decor", "organizer", "journal", "template", "set", "pack", "digital",
    "download", "sheet", "sheets",
    # generic occasion/filler words shared by many seasons
    "kids", "kid", "day", "party", "games", "game", "gift", "gifts", "tags",
    "2026", "new", "year", "goal", "trip", "calendar", "coupon", "reading",
    "activity", "activities", "vision", "board",
    # generic party/stationery words: they name a FORMAT or generic occasion, not a
    # calendar season, so matching on them mis-tags any invite/announcement/sign
    # (a "gender reveal invitation" is NOT graduation just because grads mail invitations).
    "invitation", "invitations", "invite", "invites", "announcement", "announcements",
    "sign", "signs", "welcome", "banner", "banners", "favor", "favors",
    "reveal", "shower", "showers", "menu",
}


def _season_keywords() -> dict[str, set[str]]:
    """DISTINCTIVE keyword set per season, drawn from event names + seeds.

    A word only identifies a season if it is UNIQUE to that season: any word that appears in
    two or more seasons' seeds (e.g. 'invitation', 'menu') is generic and dropped, so a term
    can never be mis-tagged by a word many seasons share. This complements _SEASON_STOPWORDS
    (which pre-drops catalog/format words) and auto-handles future overlaps without a hand-list."""
    raw: dict[str, set[str]] = {}
    counts: dict[str, int] = {}
    for event in SEASONAL:
        words: set[str] = set()
        for phrase in [event["name"], *event["seeds"]]:
            for w in phrase.lower().split():
                if len(w) > 2 and w not in _SEASON_STOPWORDS:
                    words.add(w)
        raw[event["name"]] = words
        for w in words:
            counts[w] = counts.get(w, 0) + 1
    # Keep only words unique to a single season (drop cross-season generics).
    return {name: {w for w in words if counts[w] == 1} for name, words in raw.items()}


def season_for(term: str) -> str:
    """Return the season name a term belongs to (e.g. 'christmas'), or '' if none.

    Used at publish time to tag seasonal listings for the keep-alive registry, so
    they are renewed and never deleted (they accrue search/sales history all year).
    """
    tokens = {w for w in term.lower().split() if len(w) > 2}
    if not tokens:
        return ""
    for name, keywords in _season_keywords().items():
        if tokens & keywords:
            return name
    return ""


def upcoming_seasons(month: int | None = None, lookahead: int = 2) -> set[str]:
    """Seasons whose peak/prep window falls within the next `lookahead` months
    (inclusive of the current month). Drives the Q4 front-loading priority boost."""
    month = month or _now_month()
    window = {((month - 1 + i) % 12) + 1 for i in range(lookahead + 1)}
    return {e["name"] for e in SEASONAL if window & set(e["months"])}


def seasonal_seeds(month: int | None = None) -> list[str]:
    month = month or _now_month()
    out: list[str] = []
    for event in SEASONAL:
        if month in event["months"]:
            out.extend(event["seeds"])
    return out


def load_dynamic_seeds() -> list[str]:
    if DYNAMIC_SEEDS_FILE.exists():
        try:
            return json.loads(DYNAMIC_SEEDS_FILE.read_text())
        except Exception:
            return []
    return []


def add_dynamic_seeds(terms: list[str]) -> None:
    """Feed winning trend terms back as future seeds (most-recent-first, capped)."""
    existing = load_dynamic_seeds()
    seen = {t.lower() for t in existing}
    fresh = [t.strip() for t in terms if t.strip() and t.strip().lower() not in seen]
    combined = (fresh + existing)[:MAX_DYNAMIC]
    DYNAMIC_SEEDS_FILE.write_text(json.dumps(combined, indent=2))


# A listing must EARN its way into the seed pool: these floors define a relative
# winner in a shop where the median listing sits at ~2 views. Selection-time
# feedback (the old behavior) let 1-view duds seed future discovery runs.
SEED_MIN_VIEWS = 20
SEED_MIN_FAVORITES = 2


def feedback_winning_seeds(min_views: int = SEED_MIN_VIEWS,
                           min_favorites: int = SEED_MIN_FAVORITES) -> list[str]:
    """Performance-gated self-learning: only trend terms whose LISTINGS proved
    real buyer interest (views/favorites) become future discovery seeds.
    Called after a metrics pull. Returns the terms that qualified."""
    from .. import db  # local import — seeds.py stays importable without a DB

    winners: list[str] = []
    for r in db.latest_metrics():
        term = (r.get("term") or "").strip()
        if not term:
            continue
        if int(r.get("views") or 0) >= min_views or \
           int(r.get("favorites") or 0) >= min_favorites:
            winners.append(term)
    if winners:
        add_dynamic_seeds(winners)
    return winners


def product_ideas_seeds() -> list[str]:
    """Seeds from data/product_ideas.json — all archetype discovery terms."""
    try:
        from ..product_ideas import archetype_seeds
        return archetype_seeds()
    except Exception:
        return []


def pinterest_predicts_seeds() -> list[str]:
    """The curated Pinterest Predicts trend seeds (early, cross-platform signal)."""
    return list(PINTEREST_PREDICTS_2026)


def active_seeds(month: int | None = None) -> list[str]:
    """Evergreen + in-season + product-ideas archetypes + learned dynamic seeds,
    de-duplicated."""
    out: list[str] = []
    seen: set[str] = set()
    for s in (EVERGREEN + OCCUPATIONS + PERSONALIZABLE + seasonal_seeds(month)
              + pinterest_predicts_seeds()
              + product_ideas_seeds() + load_dynamic_seeds()):
        k = s.lower().strip()
        if k and k not in seen:
            seen.add(k)
            out.append(s)
    return out


def _rotation_state() -> dict[str, int]:
    if SEED_ROTATION_FILE.exists():
        try:
            return {k: int(v) for k, v in json.loads(SEED_ROTATION_FILE.read_text()).items()}
        except (ValueError, OSError, TypeError):
            pass
    return {}


def _rotating_selection(pools: dict[str, list[str]], pattern: tuple[str, ...],
                        limit: int) -> list[str]:
    """Take a balanced, persistent round-robin sample from named seed pools."""
    state = _rotation_state()
    consumed = {name: 0 for name in pools}
    out: list[str] = []
    seen: set[str] = set()

    while len(out) < limit:
        progressed = False
        for name in pattern:
            pool = pools.get(name, [])
            if not pool or consumed[name] >= len(pool):
                continue
            while consumed[name] < len(pool):
                index = (state.get(name, 0) + consumed[name]) % len(pool)
                consumed[name] += 1
                seed = pool[index].strip()
                key = seed.lower()
                if seed and key not in seen:
                    seen.add(key)
                    out.append(seed)
                    progressed = True
                    break
            if len(out) >= limit:
                break
        if not progressed:
            break

    for name, count in consumed.items():
        pool = pools.get(name, [])
        if pool and count:
            state[name] = (state.get(name, 0) + count) % len(pool)
    SEED_ROTATION_FILE.write_text(json.dumps(state, indent=2))
    return out


def discovery_seeds(limit: int = 14, month: int | None = None) -> list[str]:
    """Balanced seeds for Google discovery.

    Product archetypes receive the largest share, while evergreen, seasonal and
    learned pools are guaranteed coverage and rotate between runs.
    """
    pools = {
        "ideas": product_ideas_seeds(),
        "personalizable": PERSONALIZABLE,
        "seasonal": seasonal_seeds(month),
        "evergreen": EVERGREEN,
        "occupations": OCCUPATIONS,
        "pinterest": pinterest_predicts_seeds(),
        "learned": load_dynamic_seeds(),
    }
    # PERSONALIZABLE earns 3 of 12 slots — equal weight to product-idea archetypes. Without a
    # guaranteed share the funnel stayed ~95% fill-in/print PDF and the Canva line starved (it had
    # zero of the wedding/shower/invitation/memorial trends it exists to serve). Occupations keep 2
    # (the shop's #2 all-time performer is an occupation product); the rest rotate for coverage.
    pattern = ("ideas", "personalizable", "seasonal", "occupations", "evergreen",
               "ideas", "personalizable", "pinterest", "learned", "occupations",
               "ideas", "personalizable")
    return _rotating_selection(pools, pattern, limit)


def idea_discovery_seeds(limit: int = 25) -> list[str]:
    """Rotate directly through the product-archetype catalog."""
    return _rotating_selection(
        {"ideas_direct": product_ideas_seeds()}, ("ideas_direct",), limit)
