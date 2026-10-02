"""Append-only product history — survives DB resets, prevents duplicates.

Every produced product is recorded as one JSON line in data/product_history.jsonl
with full detail (trend, scores, market, listing). Future runs check this history
(by theme tokens) so we never make a near-duplicate of something we've already
made — even if the SQLite DB was reset.

NEVER delete this file.
"""
from __future__ import annotations

import json
import re
import unicodedata

from .config import DATA_DIR
from .models import now

HISTORY_FILE = DATA_DIR / "product_history.jsonl"

# Words ignored when comparing product themes for duplicate detection.
STOP = {
    "the", "a", "an", "for", "and", "to", "of", "near", "me", "your", "with",
    "best", "ideas", "idea", "template", "templates", "printable", "printables",
    "editable", "customizable", "instant",
    "kit", "planner", "system", "2026", "2025", "digital", "download", "pro",
    "free", "that", "arent", "lame", "set", "pack", "bundle", "google", "sheets",
    "how", "make", "edition", "not", "day",
    # Product-format/audience words identify the archetype, not the subject.
    "activity", "activities", "book", "books", "coloring", "colouring",
    "game", "games", "journal", "tracker", "worksheet", "worksheets",
    "page", "pages", "kids", "children", "adult", "adults",
    # Generic category / style words — too broad for dedup (block every product)
    "art", "print", "prints", "wall", "decor", "poster", "room", "nursery",
    "watercolor", "vintage", "minimalist", "botanical", "floral", "retro",
    "boho", "modern", "abstract", "geometric", "line", "post",
}


# Cross-language canonicalization: the same theme in two languages (e.g. "world cup" vs
# "copa do mundo") used to slip past token dedup and ship a duplicate (the #23 bug). We strip
# accents and map common non-English trend phrases to an English canonical BEFORE tokenizing, so
# they collide. Keys are accent-stripped + lowercase (matched as substrings); extend as needed.
CANONICAL_PHRASES = {
    "copa do mundo": "world cup", "copa mundial": "world cup", "coupe du monde": "world cup",
    "weltmeisterschaft": "world cup", "mundial de futbol": "world cup", "mondiali": "world cup",
    "feliz navidad": "merry christmas", "navidad": "christmas", "noel": "christmas",
    "weihnachten": "christmas", "natale": "christmas", "joyeux noel": "merry christmas",
    "pascua": "easter", "paques": "easter", "ostern": "easter",
    "san valentin": "valentines", "saint valentin": "valentines",
    "dia de los muertos": "day of the dead", "dia de muertos": "day of the dead",
    "boda": "wedding", "mariage": "wedding", "hochzeit": "wedding", "casamento": "wedding",
    "cumpleanos": "birthday", "anniversaire": "birthday", "geburtstag": "birthday",
    "aniversario": "birthday", "accion de gracias": "thanksgiving",
}


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _normalize(text: str) -> str:
    """Lowercase, strip accents, and canonicalize known cross-language phrases to English."""
    t = _strip_accents((text or "").lower())
    for foreign, english in CANONICAL_PHRASES.items():
        if foreign in t:
            t = t.replace(foreign, english)
    return t


def theme_tokens(*texts: str) -> set[str]:
    out: set[str] = set()
    for t in texts:
        out |= {w for w in re.findall(r"[a-z0-9]+", _normalize(t))
                if w not in STOP and len(w) >= 2}  # keep short/alnum like "f1"
    return out


def record(entry: dict) -> None:
    entry = {"recorded_at": now(), **entry}
    with HISTORY_FILE.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def record_product(product_id: int) -> None:
    """Snapshot a product's full provenance into the append-only history."""
    from . import db

    p = db.provenance(product_id)
    if not p:
        return
    etsy = db.get_etsy_listing(product_id)
    product_intel = db.get_product_intel(product_id) or {}
    intel = product_intel.get("intel") or {}
    entry = {
        "product_id": product_id,
        "bundle_type": p.get("bundle_type"),
        "title_concept": p.get("title_concept"),
        "trend_term": p.get("term"),
        "source": p.get("source"),
        "tier": p.get("tier"),
        "scores": {k: p.get(k) for k in ("virality", "purchase_intent",
                   "productization", "competition", "longevity", "ip_risk", "composite")},
        "market": {"listing_count": p.get("listing_count"),
                   "demand": p.get("mkt_demand"), "competition": p.get("mkt_competition"),
                   "adjusted_score": p.get("adjusted_score")},
        "etsy_listing_id": etsy.get("etsy_listing_id") if etsy else None,
        "url": etsy.get("url") if etsy else None,
        "idea_archetype": intel.get("idea_archetype"),
        "theme_tokens": sorted(theme_tokens(p.get("bundle_type", ""), p.get("term", ""))),
    }
    record(entry)


def load() -> list[dict]:
    if not HISTORY_FILE.exists():
        return []
    out = []
    for line in HISTORY_FILE.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def known_theme_tokens() -> set[str]:
    """Union of theme tokens across all previously-made products."""
    tokens: set[str] = set()
    for e in load():
        tokens |= set(e.get("theme_tokens") or [])
    return tokens


def _token_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def theme_similarity(left: str, right: str) -> float:
    """Containment similarity suited to short product-theme phrases."""
    score = _token_similarity(theme_tokens(left), theme_tokens(right))
    left_words = [w for w in re.findall(r"[a-z0-9]+", _normalize(left)) if w not in STOP]
    right_words = [w for w in re.findall(r"[a-z0-9]+", _normalize(right)) if w not in STOP]
    left_pairs = set(zip(left_words, left_words[1:]))
    right_pairs = set(zip(right_words, right_words[1:]))
    if left_pairs & right_pairs:
        score = max(score, 0.75)
    return score


def _jaccard(a: set[str], b: set[str]) -> float:
    """Overlap by UNION denominator. Unlike _token_similarity's min() denominator, this does NOT let a
    single-token theme match every longer term that merely contains it (that over-excludes distinct
    products: {welcome,sign} vs {wedding,welcome,sign} would score 1.0 under min(), 0.67 under jaccard)."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def collides_with_token_sets(cand: set[str], taken_sigs: list[set[str]],
                             threshold: float = 0.6) -> bool:
    """Near-duplicate check of a candidate's theme tokens against PRECOMPUTED taken token-sets (so the
    architect tokenizes the in-flight terms once, not once per candidate)."""
    return bool(cand) and any(_jaccard(cand, sig) >= threshold for sig in taken_sigs if sig)


def collides_with_any(term: str, taken_terms: list[str], threshold: float = 0.6) -> bool:
    """True if `term`'s theme (Jaccard) matches any of `taken_terms` — a near-duplicate check for
    IN-FLIGHT products (planned/routed/queued), which are not yet in the produced-history that
    `is_duplicate` reads. Catches e.g. "funeral program template" against an already-routed "funeral
    program" (both reduce to {funeral, program}; "template" is a format stopword), WITHOUT the
    single-token over-exclusion that min()-denominator similarity caused."""
    return collides_with_token_sets(theme_tokens(term),
                                    [theme_tokens(t) for t in taken_terms], threshold)


def is_duplicate(term: str, threshold: float = 0.6) -> bool:
    """Compare against each product, not the global union of all theme words."""
    candidate = theme_tokens(term)
    for entry in load():
        existing = set(entry.get("theme_tokens") or [])
        if _token_similarity(candidate, existing) >= threshold:
            return True
        prior_text = " ".join(str(entry.get(k) or "") for k in
                              ("trend_term", "bundle_type", "title_concept"))
        if prior_text.strip() and theme_similarity(term, prior_text) >= threshold:
            return True
    return False


def record_optimization(product_id: int, optimized: dict) -> None:
    """Append-only audit of title/tag rewrites for a live listing."""
    entry = {
        "product_id": product_id,
        "etsy_listing_id": optimized.get("etsy_listing_id"),
        "keyword": optimized.get("keyword"),
        "old_title": optimized.get("old_title"),
        "new_title": optimized.get("new_title"),
        "old_tags": optimized.get("old_tags"),
        "new_tags": optimized.get("new_tags"),
        "event": "seo_optimization",
        "theme_tokens": sorted(theme_tokens(
            optimized.get("new_title", ""), optimized.get("keyword", "")
        )),
    }
    record(entry)
