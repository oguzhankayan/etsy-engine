"""SEO Writer (Agent 10). Research-driven, Etsy-2026 listing copy.

Two-step: keyword_research.py produces an intent-segmented keyword set; this
module assembles the listing. Tags are built deterministically from the research
to guarantee the rules (>=8 long-tail, all <=20 chars, 13 distinct, no mid-word
truncation). Title/description/alt/FAQ are written by Claude under strict rules
and then hard-clamped. See docs/etsy-seo.md.
"""
from __future__ import annotations

import json

from .. import db
from ..llm import complete_json
from ..models import Listing
from .keyword_research import research

TITLE_MAX = 140
TAG_MAX_LEN = 20
TAG_MAX_COUNT = 13
MIN_LONG_TAIL = 8

# Etsy AI policy: the UI radio ("How is this digital content created? -> With an
# AI generator") is NOT in the API, so it must be selected manually per listing.
# The API-controllable half is an explicit description disclosure — appended here
# to every listing so it is always present and consistent.
AI_DISCLOSURE = (
    "\n\n— — —\n"
    "Please note: The artwork in this listing was created with the help of AI "
    "image-generation tools, then reviewed, designed, arranged, and curated by me. "
    "Disclosed in line with Etsy's policy on AI-assisted content."
)


# Substrings that misrepresent our product (flat printable digital downloads).
# Mined competitor tags often include formats/materials we do NOT offer — using
# them is dishonest (Etsy mislabeling) and wastes tag slots. Drop any tag containing
# one of these.
TAG_DENY = (
    # editable / vector / cut-file formats we don't provide
    "canva", "svg", "png", "eps", "dxf", "pdf editable", "cricut", "silhouette",
    "vinyl", "sublimation", "editable", "customizable", "customisable", "fillable",
    "editable template",
    # personalization we don't do (flat, write-in by hand)
    "custom", "personalized", "personalised", "monogram",
    # physical products we don't sell
    "shirt", "tshirt", "t-shirt", " tee", "hoodie", "sweatshirt", "mug", "tumbler",
    "pillow", "blanket", "canvas", "keychain", "magnet", "earring", "necklace",
    "bracelet", "framed", "frame ", "phone case", "sticker pack",
    # banned product forms (owner 2026-07-02): multi-piece cut-out assemblies we
    # no longer make — promising them in copy is a promise-mismatch defect
    "banner", "garland", "bunting", "pennant",
)


# Words in TAG_DENY that describe the sanctioned letter-banner form — allowed ONLY
# when the bundle actually contains a letter_banner component (else promise-mismatch).
_BANNER_WORDS = ("banner", "pennant")


def _honest_tag(t: str, allow_banner: bool = False, deny: tuple = TAG_DENY) -> bool:
    """False if the tag claims a format/material/personalization we don't offer.
    When allow_banner is set (bundle has a real letter_banner), 'banner'/'pennant'
    stop being disallowed (garland/bunting stay banned — we don't make those).
    `deny` is overridable: the Canva line passes its OWN list (editable/canva are honest
    there, so they aren't denied; only formats/materials we don't ship are)."""
    d = deny if not allow_banner else tuple(w for w in deny if w not in _BANNER_WORDS)
    low = f" {t.lower()} "
    return not any(bad in low or bad in t.lower() for bad in d)


def _norm_tag(t: str) -> str | None:
    """Lowercase, trim, fit <=20 chars at a word boundary; drop if impossible."""
    t = " ".join(str(t).lower().split())
    if not t:
        return None
    if len(t) <= TAG_MAX_LEN:
        return t
    # try trimming whole words off the end until it fits (no mid-word cuts)
    words = t.split()
    while words:
        words.pop()
        cand = " ".join(words)
        if 0 < len(cand) <= TAG_MAX_LEN:
            return cand
    return None


def build_tags(kw: dict, real_tags: list[str] | None = None,
               has_banner: bool = False, deny: tuple = TAG_DENY) -> list[str]:
    """Assemble 13 diverse tags from the keyword research.

    Precedence: the research's PRIMARY keyword FIRST (Etsy's single biggest exact-match lever, so
    it can never be crowded out of the 13), then REAL top-seller tags (proven winners mined from the
    live Etsy market), then research long-tail, the title phrases, and other angles. All are
    de-duplicated, near-duplicate-root filtered, honesty-filtered, and <=20 chars. At least
    MIN_LONG_TAIL slots are reserved for multi-word long-tail (single broad words rarely rank), as
    long as that many long-tail candidates exist.
    """
    kw = kw if isinstance(kw, dict) else {}  # tolerate a malformed cache/LLM shape
    primary = [kw["primary_keyword"]] if kw.get("primary_keyword") else []
    long_tail = [t for t in (kw.get("long_tail") or []) if " " in str(t)]
    title_kw = list(kw.get("title_keywords") or [])
    other = (
        (kw.get("recipients") or []) + (kw.get("occasions") or [])
        + (kw.get("solutions") or []) + (kw.get("styles") or [])
        + (kw.get("formats") or []) + (kw.get("product_type_terms") or [])
    )
    real = [t for t in (real_tags or []) if t]
    real_multi = [t for t in real if " " in str(t)]      # multi-word proven winners (long-tail)
    real_single = [t for t in real if " " not in str(t)]  # broad single-word winners

    # 1) Normalize + filter (honesty, <=20 chars, near-dup roots) into ONE ordered candidate list.
    #    Multi-word phrases lead so the near-dup filter drops the REDUNDANT broad single word
    #    ('invite') rather than the specific long-tail phrase ('teddy bear invite') that contains it.
    ordered: list[str] = []
    seen: set[str] = set()
    word_sets: list[set[str]] = []
    for raw in primary + real_multi + long_tail + title_kw + real_single + other:
        n = _norm_tag(raw)
        if not n or n in seen or not _honest_tag(n, allow_banner=has_banner, deny=deny):
            continue
        words = set(n.split())
        if any(words <= ws or ws <= words for ws in word_sets):  # near-duplicate root
            continue
        seen.add(n)
        word_sets.append(words)
        ordered.append(n)

    # 2) Select 13, reserving MIN_LONG_TAIL slots for multi-word long-tail so single broad words
    #    can't crowd them out. Backfill held singles if long-tail runs short (never ship < 13).
    n_multi = sum(1 for t in ordered if " " in t)
    max_single = TAG_MAX_COUNT - min(MIN_LONG_TAIL, n_multi)
    tags: list[str] = []
    singles = 0
    for t in ordered:
        if len(tags) >= TAG_MAX_COUNT:
            break
        if " " not in t:
            if singles >= max_single:
                continue                     # hold this slot for a long-tail tag
            singles += 1
        tags.append(t)
    if len(tags) < TAG_MAX_COUNT:
        for t in ordered:
            if len(tags) >= TAG_MAX_COUNT:
                break
            if t not in tags:
                tags.append(t)
    return tags[:TAG_MAX_COUNT]


def ensure_keyword_in_title(title: str, keyword: str | None, max_len: int = TITLE_MAX) -> str:
    """Guarantee the primary search phrase is present in the title (Etsy's exact-match lever). If it
    is missing, front-load it and clamp to max_len at a word boundary (the keyword survives because
    it leads). Returns the title unchanged when the keyword is already present or empty."""
    title = " ".join((title or "").split())
    kw = " ".join((keyword or "").split())
    if not kw or kw.lower() in title.lower():
        return title[:max_len]
    combined = f"{kw} | {title}" if title else kw
    if len(combined) <= max_len:
        return combined
    words = combined.split()
    while words and len(" ".join(words)) > max_len:
        words.pop()
    return " ".join(words).rstrip(" |")


COPY_SYSTEM = f"""You are an expert Etsy copywriter for digital printables, applying
2026 Etsy SEO. Using the provided keyword research, write listing copy.

TITLE rules (per Etsy's official guidance):
- SHORT, CLEAR, descriptive — a buyer scanning a busy results page (esp. mobile)
  must instantly understand what it is. Aim ~70-100 chars, hard max {TITLE_MAX}.
- LEAD with what the item IS (the core product), since that is what shoppers see
  first. Keyword POSITION does NOT affect ranking, so optimize for human clarity.
- Use a couple of phrases separated by | or :, NOT a long keyword dump.
- Do NOT repeat any word more than once. Keep buyers in mind, not a computer.
  Good example shape: "Family Camping Checklist & Trip Planner Kit | Printable PDF"

DESCRIPTION rules (descriptions DO factor into ranking):
- the FIRST 1-2 sentences must read naturally AND weave in a few top keywords
  (don't copy the title verbatim or list keywords).
- then: what's included (bullet the items), who it's for, instant digital download
  delivery, printing notes (US Letter + A4, 300 DPI, print at home)

HONESTY (Etsy mislabeling rule): the files are FLAT printable images (JPG, plus a
PDF assembled from them) — meant to be printed and written on BY HAND. They are
NOT editable/customizable/fillable and NOT Canva templates. NEVER claim "editable",
"customizable", "fillable", "Canva", or "digital planner you can type in". Use
accurate words: printable, instant download, print at home, write-in by hand.

Also write one concise alt_text per provided image kind, and a 3-4 pair FAQ
(delivery, printing, sizes, personal use).

Respond with JSON only:
{{"title": "...", "description": "...", "alt_texts": ["..."],
  "faq": "Q: ...\\nA: ...\\n\\nQ: ...\\nA: ..."}}"""


def write_listing(product: dict) -> Listing:
    # Step 1 — keyword research (cache in DB)
    kw = db.get_keyword_set(product["id"]) or research(product)
    db.upsert_keyword_set(product["id"], kw)

    # Market intelligence: real winning tags + archetype (planner vs wall-art print).
    pintel = db.get_product_intel(product["id"]) or {}
    archetype = pintel.get("archetype", "planner")

    # A sanctioned letter_banner in the bundle makes "banner"/"pennant" honest copy.
    bundle_items = db.bundle_items_for(product["id"])
    has_banner = any(b.asset_type == "letter_banner" for b in bundle_items)

    # Step 2a — deterministic, rule-guaranteed tags (real winners first)
    tags = build_tags(kw, real_tags=pintel.get("top_tags"), has_banner=has_banner)

    # Step 2b — Claude writes the prose copy from the research
    items = [b.name for b in bundle_items]
    mockup_kinds = [m["kind"] for m in db.mockups_for_product(product["id"])]
    payload = {
        "bundle_type": product["bundle_type"],
        "included_items": items,
        "keyword_research": kw,
        "image_kinds_needing_alt_text": mockup_kinds,
    }
    if archetype == "print":
        payload["product_format"] = (
            "This is a single DIGITAL WALL ART PRINT (instant download). Write copy to "
            "PRINT AND FRAME it: mention it's a high-resolution printable, multiple "
            "standard frame sizes included (PDF) plus a PNG, print at home or at a print "
            "shop. Do NOT describe it as a planner/worksheet and do NOT say 'write-in', "
            "'editable', 'customizable', or 'Canva'."
        )
    user = json.dumps(payload, ensure_ascii=False)
    copy = complete_json(COPY_SYSTEM, user)

    title = (copy.get("title") or "").strip()[:TITLE_MAX]
    # Banned-form words in the TITLE are a promise-mismatch defect — swap for honest
    # single-sheet wording. When the bundle HAS a real letter_banner, "Banner"/
    # "Pennant" are honest and kept; garland/bunting are always swapped.
    swaps = [("Garlands", "Signs"), ("Garland", "Sign"), ("Bunting", "Decor")]
    if not has_banner:
        swaps += [("Banners", "Posters"), ("Banner", "Poster"),
                  ("Pennants", "Signs"), ("Pennant", "Sign")]
    for bad, good in swaps:
        title = title.replace(bad, good).replace(bad.lower(), good.lower())
    # Guarantee the primary search phrase is actually in the title (Etsy exact-match lever) — the
    # LLM is asked to include it but not forced; this makes it deterministic.
    title = ensure_keyword_in_title(title, kw.get("primary_keyword"))
    description = (copy.get("description", "") or "").rstrip() + AI_DISCLOSURE
    return Listing(
        product_id=product["id"],
        title=title,
        tags=json.dumps(tags),
        description=description,
        alt_texts=json.dumps(copy.get("alt_texts", [])),
        faq=copy.get("faq", ""),
    )
