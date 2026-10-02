"""Self-improving product archetype catalog.

Loads data/product_ideas.json and wires it into trend discovery (seeds),
archetype routing, architect format guidance, and continuous feedback loops.

Feedback flows that keep the file improving:
1. Market intel   → winning niches become learned seeds + themes
2. Product publish → archetype usage is tracked
3. Etsy metrics   → views/favorites/sales update performance per archetype
4. Prune          → low-signal learned entries are periodically cleaned
"""
from __future__ import annotations

import json
import re
from datetime import datetime, UTC
from pathlib import Path

from .config import DATA_DIR

IDEAS_FILE = DATA_DIR / "product_ideas.json"
CATALOG_FILE = Path(__file__).with_name("product_ideas_catalog.json")

# Minimum signals for market intel feedback to trigger learning
MIN_LEARN_DAILY_VIEWS = 1.0    # established niche threshold
MIN_LEARN_BEATABILITY = 0.3    # niche is winnable
MIN_LEARN_LISTINGS = 20        # enough market to matter
MIN_EMERGING_DAILY_VIEWS = 0.35
MIN_EMERGING_BEATABILITY = 0.45
MIN_EMERGING_LISTINGS = 5
MAX_LEARNED_SEEDS_PER_ARCH = 15
MAX_LEARNED_THEMES_PER_ARCH = 20
MAX_LEARNED_SEEDS_TOTAL = 60


# ── read / write ────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(UTC).isoformat()


def _load_raw() -> dict:
    """Load the file without caching — always fresh for self-improving reads."""
    try:
        catalog = json.loads(CATALOG_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        catalog = {}
    if IDEAS_FILE.exists():
        try:
            learned = json.loads(IDEAS_FILE.read_text())
            merged = dict(catalog)
            for name, value in learned.items():
                if name.startswith("_"):
                    merged[name] = value
                else:
                    merged[name] = {**catalog.get(name, {}), **value}
            return merged
        except (json.JSONDecodeError, OSError):
            pass
    return catalog


def _save(data: dict) -> None:
    data.setdefault("_meta", {})
    data["_meta"]["last_updated"] = _now()
    data["_meta"]["version"] = data["_meta"].get("version", 2)
    IDEAS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def _ensure_learned(arch: dict) -> dict:
    """Ensure the _learned sub-dict exists on an archetype."""
    if "_learned" not in arch:
        arch["_learned"] = {"seeds": [], "themes": [],
                            "performance": {"products": 0, "views": 0,
                                            "favorites": 0, "sales": 0}}
    arch["_learned"].setdefault("seeds", [])
    arch["_learned"].setdefault("themes", [])
    arch["_learned"].setdefault("performance",
                                {"products": 0, "views": 0, "favorites": 0, "sales": 0})
    return arch["_learned"]


# ── curated access (unchanging) ─────────────────────────────────────────────

def get_archetypes() -> dict:
    """Return all archetype definitions keyed by name (curated fields only)."""
    data = _load_raw()
    return {
        k: v for k, v in data.items()
        if not k.startswith("_") and (v.get("triggers") or v.get("formats"))
    }


def archetype_seeds() -> list[str]:
    """All seeds (curated + learned) from all archetypes — feeds Google Trends."""
    out: list[str] = []
    seen: set[str] = set()
    data = _load_raw()
    for name, arch in data.items():
        if name.startswith("_"):
            continue
        for seed in arch.get("seeds", []):
            k = seed.lower().strip()
            if k and k not in seen:
                seen.add(k)
                out.append(seed)
        for seed in arch.get("_learned", {}).get("seeds", []):
            k = seed.lower().strip()
            if k and k not in seen:
                seen.add(k)
                out.append(seed)
    for seed in expanded_archetype_seeds():
        k = seed.lower().strip()
        if k and k not in seen:
            seen.add(k)
            out.append(seed)
    return out


def expanded_archetype_seeds() -> list[str]:
    """Create concrete theme × format searches from the evolving catalog."""
    generic_themes = {
        "activity", "book", "bundle", "coloring", "digital", "easy", "kids",
        "page", "pages", "printable", "planner", "tracker",
    }
    patterns = {
        "questionnaire": "{theme} questionnaire printable",
        "coupon_book": "{theme} coupon book printable",
        "party_games": "{theme} party games printable",
        "greeting_card": "{theme} greeting card printable",
        "coloring_page": "{theme} coloring book printable",
        "wall_art_poster": "{theme} wall art printable",
        "banner_decor": "{theme} banner printable",
        "planner_kit": "{theme} planner kit printable",
        "checklist_tracker": "{theme} checklist tracker printable",
        "sticker_sheet": "{theme} sticker sheet printable",
    }
    out: list[str] = []
    for name in get_archetypes():
        pattern = patterns.get(name)
        if not pattern:
            continue
        for theme in archetype_themes(name):
            if theme.lower().strip() in generic_themes:
                continue
            value = pattern.format(theme=theme).strip()
            if value:
                out.append(value)
    return out


def match_archetype(term: str) -> str | None:
    """Return the archetype name whose triggers match `term`, or None.

    Longer trigger matches win (more specific)."""
    t = term.lower()
    best_name, best_score = None, 0
    for name, arch in get_archetypes().items():
        for trigger in arch.get("triggers", []):
            if re.search(r"(?<!\w)" + re.escape(trigger.lower()) + r"(?!\w)", t):
                score = len(trigger)
                if score > best_score:
                    best_name, best_score = name, score
    return best_name


def resolve_archetype(term: str, market_archetype: str | None = None) -> str:
    """Resolve binary market formats into the richer product-idea taxonomy."""
    specific = match_archetype(term)
    if specific:
        return specific
    if market_archetype in get_archetypes():
        return str(market_archetype)
    if market_archetype == "print":
        return "wall_art_poster"
    return "planner_kit"


def archetype_format(name: str) -> str:
    arch = get_archetypes().get(name, {})
    fmts = arch.get("formats", [])
    return "; ".join(fmts) if fmts else ""


def archetype_themes(name: str) -> list[str]:
    """Curated + learned example themes for an archetype."""
    arch = get_archetypes().get(name, {})
    curated = arch.get("example_themes", [])
    learned = arch.get("_learned", {}).get("themes", [])
    seen = {t.lower() for t in curated}
    out = list(curated)
    for t in learned:
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


def cross_ideas(theme: str) -> list[dict]:
    """Given a theme word (e.g. 'dad', 'birthday'), find all archetypes whose
    themes include it. Returns concrete product ideas to produce."""
    t = theme.lower().strip()
    ideas: list[dict] = []
    for name, arch in get_archetypes().items():
        all_themes = [e.lower() for e in archetype_themes(name)]
        if t in all_themes:
            trig_match = any(trig.lower() in t
                           for trig in arch.get("triggers", []))
            if trig_match:
                continue
            ideas.append({
                "archetype": name,
                "theme": theme,
                "seeds": arch.get("seeds", []),
                "format": "; ".join(arch.get("formats", [])),
            })
    return ideas


def archetype_system_hint(name: str) -> str:
    """Format guidance hint for the architect system prompt."""
    hints = {
        "questionnaire": (
            "This is a QUESTIONNAIRE / FILL-IN product — a single page or short "
            "pack of pre-designed question sheets the buyer prints and fills by hand. "
            "Focus: beautiful layout with clear question fields, decorative header, "
            "recipient-personalised theme. Asset type: worksheet or card."
        ),
        "coupon_book": (
            "This is a COUPON BOOK / VOUCHER product — a multi-page booklet of "
            "pre-designed redeemable coupons (e.g. 'Good for One Hug'). "
            "Focus: tear-off style, themed illustrations per coupon, recipient name "
            "space. Asset types: card, certificate, sticker_sheet."
        ),
        "party_games": (
            "This is a PARTY GAME PACK — a multi-page printable activity set for "
            "a specific party theme. Focus: fun, social, laugh-out-loud games; clear "
            "instructions; themed decorative elements. Asset types: worksheet, card, "
            "checklist, poster."
        ),
        "greeting_card": (
            "This is a GREETING CARD — a single foldable card (or small card pack) "
            "with a punny/heartfelt message and themed illustration. "
            "Focus: print-and-fold format, front + inside design. Asset type: card."
        ),
        "coloring_page": (
            "This is a COLORING BOOK — a multi-page PDF of bold-and-easy line-art "
            "coloring sheets. Design 10-20 INDIVIDUAL coloring pages — EVERY item "
            "is exactly ONE full-page coloring sheet with a SINGLE main subject. "
            "NEVER group multiple pages into one item (no '4 Pages' items). "
            "Each item = one coloring sheet = one generated image. "
            "EVERY item MUST have asset_type='coloring_page' (NOT poster, NOT worksheet). "
            "Each spec describes ONE simple coloring subject in detail "
            "(e.g. 'A smiling dinosaur holding an ice cream cone, bold thick outlines, "
            "simple shapes, no shading, kawaii style'). "
            "The cover page can be a decorative title page with the book name. "
            "NO write-in fields, NO checkboxes, NO forms, NO grids — these are pure "
            "coloring sheets. Style: 'Bold & Easy' thick-line, kawaii, cozy, relaxing."
        ),
        "wall_art_poster": (
            "This is a WALL ART / POSTER print — a single decorative, frameable "
            "design. Focus: bold composition, striking focal subject, gallery-wall "
            "aesthetic. Asset type: wall_art."
        ),
        "banner_decor": (
            "This is a DECOR bundle whose centerpiece is a LETTER BANNER. Include "
            "exactly ONE component with asset_type 'letter_banner' — our compositor "
            "builds it deterministically (one themed pennant + stamped letters, one "
            "usable flag per page); do NOT describe drawing it. Its spec MUST embed a "
            "JSON directive, e.g. {\"banner\":{\"segments\":[{\"kind\":\"word\","
            "\"text\":\"WELCOME\"},{\"kind\":\"alphabet\",\"numbers\":true},{\"kind\":"
            "\"months\"}]}} (kinds: word, alphabet, months, words, blanks). Surround "
            "it with single-sheet decor (signs, posters, toppers, place cards)."
        ),
        "planner_kit": (
            "This is a PLANNER KIT / ORGANIZER BUNDLE — a 6–10 page system that "
            "solves a specific planning need. Focus: cohesive pages, clean layout, "
            "write-in fields. Asset types: planner, tracker, checklist, log."
        ),
        "checklist_tracker": (
            "This is a CHECKLIST / TRACKER — a focused single-page or short pack for "
            "logging/tracking a specific habit/task/process. Focus: clean grid/table "
            "layout, clear column headers. Asset types: tracker, checklist, log, chart."
        ),
        "sticker_sheet": (
            "This is a STICKER SHEET / LABEL SET — pre-designed cut-out stickers or "
            "labels for a theme. Focus: coordinated designs on one sheet, cut lines, "
            "themed illustrations. Asset types: sticker_sheet, label."
        ),
    }
    return hints.get(name, "")


# ── self-improvement: feedback loops ────────────────────────────────────────

def _extract_themes(term: str) -> set[str]:
    """Extract meaningful theme words from a search term (like dedup but only nouns)."""
    from .history import theme_tokens
    return theme_tokens(term)


def feedback_from_intel(keyword: str, intel: dict) -> None:
    """Feed market intel signals back into product_ideas.

    If a niche has strong demand + winnability, its keyword becomes a learned
    seed and its theme words become learned themes for the matching archetype.
    """
    daily_views = (intel.get("avg_daily_views", 0)
                   or intel.get("daily_views", 0) or 0)
    beatability = intel.get("beatability", 0) or 0
    count = intel.get("count", 0) or 0

    established = (
        daily_views >= MIN_LEARN_DAILY_VIEWS
        and beatability >= MIN_LEARN_BEATABILITY
        and count >= MIN_LEARN_LISTINGS
    )
    emerging = (
        daily_views >= MIN_EMERGING_DAILY_VIEWS
        and beatability >= MIN_EMERGING_BEATABILITY
        and count >= MIN_EMERGING_LISTINGS
    )
    if not (established or emerging):
        return

    arch_name = resolve_archetype(keyword, intel.get("archetype"))

    data = _load_raw()
    arch = data.setdefault(arch_name, {})
    learned = _ensure_learned(arch)

    # Add keyword as learned seed
    seed_lower = keyword.lower().strip()
    existing_seeds = [s.lower() for s in
                      arch.get("seeds", []) + learned.get("seeds", [])]
    if seed_lower not in existing_seeds:
        learned["seeds"].append(keyword)
        # Cap
        if len(learned["seeds"]) > MAX_LEARNED_SEEDS_PER_ARCH:
            learned["seeds"] = learned["seeds"][-MAX_LEARNED_SEEDS_PER_ARCH:]

    # Add theme words
    themes = _extract_themes(keyword)
    existing_themes = [t.lower() for t in
                       arch.get("example_themes", []) + learned.get("themes", [])]
    for theme in themes:
        if theme.lower() not in existing_themes:
            learned["themes"].append(theme)
    if len(learned["themes"]) > MAX_LEARNED_THEMES_PER_ARCH:
        learned["themes"] = learned["themes"][-MAX_LEARNED_THEMES_PER_ARCH:]

    _save(data)


def feedback_from_product(term: str, archetype: str | None = None) -> None:
    """Record that a product was produced for a given term + archetype.

    Increments the product counter so we know which archetypes are being used."""
    arch_name = resolve_archetype(term, archetype)

    data = _load_raw()
    arch = data.setdefault(arch_name, {})
    learned = _ensure_learned(arch)
    learned["performance"]["products"] = learned["performance"].get("products", 0) + 1
    _save(data)


def feedback_from_metrics(archetype: str, views: int = 0,
                          favorites: int = 0, sales: int = 0) -> None:
    """Add Etsy metrics to an archetype's performance counters."""
    data = _load_raw()
    arch = data.setdefault(archetype, {})
    learned = _ensure_learned(arch)
    perf = learned["performance"]
    perf["views"] = perf.get("views", 0) + views
    perf["favorites"] = perf.get("favorites", 0) + favorites
    perf["sales"] = perf.get("sales", 0) + sales
    _save(data)


def sync_metric_performance(rows: list[dict]) -> None:
    """Replace metric totals from the latest Etsy snapshot; safe to re-run."""
    data = _load_raw()
    for name, arch in data.items():
        if name.startswith("_") or not (arch.get("triggers") or arch.get("formats")):
            continue
        perf = _ensure_learned(arch)["performance"]
        perf["views"] = 0
        perf["favorites"] = 0
        perf["sales"] = 0

    for row in rows:
        name = resolve_archetype(row.get("term", ""), row.get("archetype"))
        arch = data.get(name)
        if not arch:
            continue
        perf = _ensure_learned(arch)["performance"]
        perf["views"] += int(row.get("views") or 0)
        perf["favorites"] += int(row.get("favorites") or 0)
        perf["sales"] += int(row.get("sales") or 0)
    _save(data)


def diversity_adjustment(term: str, recent_entries: list[dict] | None = None) -> float:
    """Small explore/exploit adjustment used when choosing the next products."""
    if recent_entries is None:
        from .history import load
        recent_entries = load()[-24:]
    target = resolve_archetype(term)
    recent_count = sum(
        resolve_archetype(e.get("trend_term", "")) == target
        for e in recent_entries if e.get("event") != "seo_optimization"
    )
    exploration = 0.12 if recent_count == 0 else -min(0.16, recent_count * 0.04)

    arch = get_archetypes().get(target, {})
    perf = arch.get("_learned", {}).get("performance", {})
    views = max(int(perf.get("views") or 0), 1)
    evidence = min(0.04, (int(perf.get("sales") or 0) * 10
                          + int(perf.get("favorites") or 0)) / views * 0.04)
    return round(exploration + evidence + seasonal_boost(term), 4)


def seasonal_boost(term: str) -> float:
    """Tilt selection toward products whose season peaks in the next ~2 months, so
    we prep the wave (esp. Q4) early enough to accrue history before the peak."""
    try:
        from .sources.seeds import season_for, upcoming_seasons
    except Exception:
        return 0.0
    season = season_for(term)
    return 0.10 if season and season in upcoming_seasons() else 0.0


def select_diverse(candidates: list[dict], limit: int) -> list[dict]:
    """Choose high-quality candidates without collapsing into one product form."""
    from .history import is_duplicate, theme_similarity, theme_tokens

    remaining = [
        c for c in candidates
        if theme_tokens(c.get("term", "")) and not is_duplicate(c.get("term", ""))
    ]
    selected: list[dict] = []
    arch_counts: dict[str, int] = {}
    while remaining and len(selected) < limit:
        eligible = [
            c for c in remaining
            if not any(theme_similarity(c.get("term", ""), s.get("term", "")) >= 0.6
                       for s in selected)
        ]
        if not eligible:
            break

        def priority(candidate: dict) -> float:
            term = candidate.get("term", "")
            base = float(candidate.get("rank_score")
                         or candidate.get("adjusted_score")
                         or candidate.get("composite") or 0)
            arch = resolve_archetype(term)
            return (base + diversity_adjustment(term)
                    - arch_counts.get(arch, 0) * 0.18)

        winner = max(eligible, key=priority)
        selected.append(winner)
        remaining.remove(winner)
        arch = resolve_archetype(winner.get("term", ""))
        arch_counts[arch] = arch_counts.get(arch, 0) + 1
    return selected


def performance_report() -> list[dict]:
    """Return performance stats per archetype, sorted by products made."""
    rows = []
    for name, arch in get_archetypes().items():
        perf = arch.get("_learned", {}).get("performance",
                    {"products": 0, "views": 0, "favorites": 0, "sales": 0})
        rows.append({"archetype": name, **perf})
    rows.sort(key=lambda r: r["products"], reverse=True)
    return rows


def prune() -> dict:
    """Remove low-signal learned seeds/themes. Returns summary of changes."""
    data = _load_raw()
    removed_seeds, removed_themes = 0, 0

    for name, arch in data.items():
        if name.startswith("_"):
            continue
        learned = arch.get("_learned", {})
        perf = learned.get("performance", {})

        # Keep learning entries for archetypes that have produced products
        if perf.get("products", 0) > 0 and perf.get("views", 0) > 0:
            continue

        # Prune: keep only the most recent learned seeds
        seeds = learned.get("seeds", [])
        if len(seeds) > MAX_LEARNED_SEEDS_PER_ARCH // 2:
            removed_seeds += len(seeds) - MAX_LEARNED_SEEDS_PER_ARCH // 2
            learned["seeds"] = seeds[-(MAX_LEARNED_SEEDS_PER_ARCH // 2):]

        # Prune: keep only the most recent themes
        themes = learned.get("themes", [])
        if len(themes) > MAX_LEARNED_THEMES_PER_ARCH // 2:
            removed_themes += len(themes) - MAX_LEARNED_THEMES_PER_ARCH // 2
            learned["themes"] = themes[-(MAX_LEARNED_THEMES_PER_ARCH // 2):]

    _save(data)
    return {"removed_seeds": removed_seeds, "removed_themes": removed_themes}


def top_archetypes_for_theme(theme: str, n: int = 5) -> list[dict]:
    """Given a theme, return the top N archetypes ranked by performance
    that include this theme. Used to decide WHAT to make for a trend."""
    ideas = cross_ideas(theme)
    if not ideas:
        return []
    perf_map = {r["archetype"]: r for r in performance_report()}
    for idea in ideas:
        p = perf_map.get(idea["archetype"], {})
        idea["products"] = p.get("products", 0)
        idea["views"] = p.get("views", 0)
        idea["sales"] = p.get("sales", 0)
    ideas.sort(key=lambda i: (i["sales"], i["views"], i["products"]), reverse=True)
    return ideas[:n]


def stats() -> dict:
    """Quick summary of the self-improving state."""
    data = _load_raw()
    meta = data.get("_meta", {})
    archetypes = get_archetypes()
    total_learned_seeds = sum(
        len(a.get("_learned", {}).get("seeds", [])) for a in archetypes.values())
    total_learned_themes = sum(
        len(a.get("_learned", {}).get("themes", [])) for a in archetypes.values())
    total_products = sum(
        a.get("_learned", {}).get("performance", {}).get("products", 0)
        for a in archetypes.values())
    return {
        "version": meta.get("version", 2),
        "last_updated": meta.get("last_updated", ""),
        "archetypes": len(archetypes),
        "curated_seeds": sum(len(a.get("seeds", [])) for a in archetypes.values()),
        "learned_seeds": total_learned_seeds,
        "learned_themes": total_learned_themes,
        "total_products_tracked": total_products,
        "file": str(IDEAS_FILE),
    }
