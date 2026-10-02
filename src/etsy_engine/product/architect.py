"""Product + Bundle Architect (Agents 3 & 4).

Turns a scored opportunity into a named bundle ("Kit") plus its component list,
following the spec's philosophy: sell a SYSTEM, not a single PNG.
Example: trend "Camping" -> "Family Camping Planner Bundle" with 6-10 items.

A critic pass then judges the plan against the niche's top sellers: a plan with
no stated unique angle gets one forced revision before any image credit is spent.
"""
from __future__ import annotations

import json
import re
import statistics

from ..llm import complete_json
from ..models import BundleItem, Product

SYSTEM = """You are an Etsy product architect for digital/printable downloads.
Given a trend, design ONE cohesive product BUNDLE (a "Kit") that solves a real
need — never a single sheet. Follow this philosophy: the customer buys a complete
system, not one image.

Rules:
- 6 to 10 components, each a printable/digital asset.
- Each component has a clear asset_type: poster, worksheet, tracker, log,
  certificate, checklist, planner, flashcards, sticker_sheet, bookmark, label, card.
- Read the trend for what it IS, then design the product form that best FITS it —
  do not force one template. Examples of the mapping (illustrative, not limiting):
  a rising aesthetic/style -> wall art or decor set in that style; a hobby/activity
  surge -> planner/tracker/log kit; a season/holiday -> seasonal printable bundle;
  an entertainment or cultural moment / event -> watch-party planner, bracket,
  prediction/score sheets, countdown, themed decor; a meme/catchphrase -> poster/
  sticker/card set. Design the bundle a fan of THIS specific trend would buy.
- Don't "print the literal term" — make the DERIVATIVE product that rides it.
- HONESTY: these are flat, write-in-by-hand printables — NOT editable/Canva files.
  Never name a component a "Template/Templates", "Editable", "Customizable",
  "Fillable", or "Personalized" anything. Use accurate names (Checklist, Log,
  Tracker, Card, Sign, Poster, Planner, Certificate, Worksheet).
- PRINT-SCALE RULE: one component = ONE page, and everything on that page must
  be usable AT ITS PRINTED SIZE. A game board gets a FULL page (or half page
  max 2/page). Playing/question cards: 4-6 per page, each at least 2.5x3.5in.
  Photo-booth props / hand-held signs: 1-2 per page (they must be face-sized).
  NEVER spec "12 boards", "40 cards" or "8 props" as one component/page —
  split into multiple one-page components (e.g. "Bingo Board 1", "Bingo Board
  2", ...) or honestly reduce the count to what fits usable.
- BANNED PRODUCT FORMS: NO free-form/AI-drawn banners or garlands, NO bunting,
  NO multi-piece string-together decor drawn as a flat page, NO glue-assembly
  templates (envelopes, boxes, gift wallets). These ship as unusable junk.
- LETTER BANNERS — the ONE allowed banner form, only for DECOR products
  (classroom, party, birthday, baby shower, nursery, holiday decor): include AT
  MOST ONE component with "asset_type":"letter_banner". Do NOT describe how to
  draw it — our compositor builds it deterministically (one themed pennant +
  stamped letters, one usable flag per page). Its "spec" MUST embed a JSON
  directive naming the content, e.g.
  {"banner":{"segments":[{"kind":"word","text":"WELCOME"},{"kind":"alphabet","numbers":true}]}}
  kinds: "word" (text), "alphabet" (optional numbers), "months", "words" (list),
  "blanks" (count). For non-decor products, use single-sheet signs/posters instead.
- Avoid any trademarked brand/character/celebrity; for branded things make a
  GENERIC, logo-free version (no official emblem/logo/mascot/wordmark).
- Bundle name should be search-friendly and concrete (and must not contain a
  trademarked name).
- If "top_selling_titles" are provided, study what those best-ranking competitors
  include — common components, bundle scope, and positioning — then design an
  ORIGINAL bundle that is at least as complete and clearly differentiated. NEVER
  copy their wording, names, or phrasing; use them only as market signal.
- If "buyer_insights" are provided (mined from real reviews of top listings):
  the bundle MUST deliver everything in "praises" (that's the niche's price of
  entry) and should directly FIX at least one item from "complaints" — that fix
  is your differentiation. Reflect it in the component list, not just words.
- If "market_scope" is provided (typical content volume + median price among
  top sellers), plan a bundle whose scope is COMPETITIVE for that market — do
  not bring an 8-page kit to a 50-page fight; stay within the component limit
  by making each component denser (e.g. a 4-week tracker, a 12-recipe sheet).
- If "previous_plan" and "required_fixes" are provided, output a REVISED plan
  that applies EVERY fix while keeping what already worked.

Respond with JSON only:
{"bundle_type": "Family Camping Planner Bundle",
 "title_concept": "short hook describing the product",
 "items": [{"name": "Trip Planner", "asset_type": "planner",
            "spec": "what's on the page / its purpose"}]}"""


PRINT_SYSTEM = """You are an Etsy product architect for digital WALL ART / PRINTABLE
ART downloads. The market for this trend is won by a single, striking decorative
print (poster / wall art / illustration) — NOT a multi-page planner kit.

Design ONE original wall-art print that a fan of this trend would buy to print and
frame. Read what buyers of this keyword actually want (see top_selling_titles +
top_tags) and match that intent.

Rules:
- Default: exactly ONE component, asset_type MUST be "wall_art".
- EXCEPTION — sets: if the market clearly sells SETS (top_selling_titles say
  "set of", "trio", "gallery wall", "pair"), you MAY design 2-4 wall_art
  components. Each component is then a SEPARATE, complete, frameable print
  (delivered as its own file) — never cram multiple panels into one sheet.
- If "buyer_insights" are provided (mined from real reviews of top listings),
  match what buyers praise (colors, mood, print quality expectations) and avoid
  what they complain about.
- If "previous_plan" and "required_fixes" are provided, output a REVISED design
  that applies EVERY fix while keeping what already worked.
- It is a finished, frameable decorative design — bold focal artwork, poster-style
  composition. NOT a worksheet, tracker, checklist, or form. Minimal or NO blank
  fields; at most a tasteful title/typographic treatment.
- Avoid trademarked brands/characters/logos/emblems/mascots/team crests — make a
  GENERIC, original, logo-free design that rides the theme.
- The product/title name must be search-friendly, concrete, and trademark-free.

Respond with JSON only:
{"bundle_type": "World Cup 2026 Soccer Wall Art Print",
 "title_concept": "short hook describing the print",
 "items": [{"name": "World Cup 2026 Celebration Wall Art", "asset_type": "wall_art",
            "spec": "what the artwork depicts, style, mood, focal subject"}]}"""


CRITIC_SYSTEM = """You are a ruthless Etsy market critic. You get a PLANNED
digital-printable product and the titles of the niche's current top sellers
(plus optional buyer_insights mined from their reviews). Judge ONE thing: if
this plan went live tomorrow, would a buyer scanning search results see a
REASON to pick it over the incumbents — or is it another me-too?

THE HARD CONSTRAINT (read first): the plan is already committed to the head
trend, and that trend is WHERE THE DEMAND IS. A good angle differentiates
WITHOUT walking away from that demand — it must still be the obvious pick for
the SAME mainstream buyer who typed the head term. Differentiation is a
tie-breaker for the head-term buyer, never a swap to a different buyer.

Generic markers: same scope as everyone, no named angle, interchangeable
title concept, components every competitor already has, nothing that fixes a
known complaint.

A real angle is CONCRETE and stays inside the head trend's demand. It comes
ONLY from one of these three GROUNDED sources — never invented from thin air:
  1. STYLE/THEME: the niche's winning visual look executed better, or a fresh
     but clearly on-trend theme a mainstream buyer instantly recognizes as
     theirs (evidenced by the top-seller titles/tags).
  2. COMPLETENESS: a more complete coordinated bundle — distinct, genuinely
     useful pieces the incumbents omit but this same buyer wants together.
  3. REAL COMPLAINT: a specific complaint REAL buyers of this niche voice
     (from buyer_insights), fixed. No buyer_insights => do not invent one.

BANNED, this is the #1 failure: narrowing to a rare, invented, or niche
AUDIENCE or LIFE-SITUATION that has little or no search demand ("gender reveal
invitation" -> "ADOPTION gender reveal"; "birthday invitation" -> "left-handed
twins' birthday"). "An audience nobody serves" is almost always an audience
nobody SEARCHES for — narrowing there throws away the demand you were handed.
If you narrow the audience at all, the top-seller titles must show that
audience is actually a live, served sub-market. When unsure, differentiate on
STYLE/THEME or COMPLETENESS and keep the audience the full mainstream one.
A distinct verdict is fine and common — do not force a narrowing to earn it.

The angle must NOT change who the product is for. Placeholder names, dates,
and wording stay ordinary and universal (a generic couple/host/child), never
a specific rare scenario, because that copy is rendered INTO the artwork and
shown in the listing photos.

Respond with JSON only:
{"verdict": "distinct" | "generic",
 "unique_angle": "one concrete sentence, grounded in style/completeness/a real
                  complaint, keeping the mainstream head-term buyer (empty if generic)",
 "fixes": ["if generic: 2-4 concrete changes grounded in style/theme,
            bundle completeness, or a real reviewed complaint — NEVER 'narrow to
            a niche audience/use-context' unless the titles prove that sub-market
            sells"]}"""


# "300 pages", "set of 12", "20 prints" etc. in competitor titles -> scope hint.
_SCOPE_RE = re.compile(
    r"(\d{1,4})\s*(?:pages?|prints?|sheets?|cards?|designs?|posters?|worksheets?)",
    re.IGNORECASE)


def market_scope(titles: list[str], median_price: float | None = None) -> dict | None:
    """Competitor scope signal: what content volume tops this niche, at what
    price. Keeps the architect from planning an 8-page kit into a market where
    winners ship 50 pages (or over-building where one print wins)."""
    counts = []
    for t in titles or []:
        counts += [int(m) for m in _SCOPE_RE.findall(t) if 0 < int(m) <= 1000]
    if not counts and median_price is None:
        return None
    scope: dict = {}
    if counts:
        scope["typical_page_count"] = int(statistics.median(counts))
        scope["max_page_count_seen"] = max(counts)
    if median_price is not None:
        scope["median_price_usd"] = median_price
    return scope


def critique_bundle(design: dict, top_selling_titles: list[str],
                    buyer_insights: dict | None = None) -> dict:
    """One critic pass over a planned bundle. Returns the critic JSON
    (verdict/unique_angle/fixes); fails soft to 'distinct' upstream."""
    payload = {
        "planned_product": {
            "bundle_type": design.get("bundle_type"),
            "title_concept": design.get("title_concept"),
            "items": [{"name": i.get("name"), "asset_type": i.get("asset_type")}
                      for i in design.get("items", [])],
        },
        "top_selling_titles": top_selling_titles,
    }
    if buyer_insights:
        payload["buyer_insights"] = buyer_insights
    return complete_json(CRITIC_SYSTEM, json.dumps(payload, ensure_ascii=False))


# Free-form/AI-drawn multi-piece cut-out & glue-assembly forms are BANNED (owner,
# 2026-07-02): flat AI pages can't deliver working banners or dielines and several
# shipped as junk (#113, #118, coupon wallet). The ONE sanctioned exception is a
# deterministic LETTER BANNER (asset_type "letter_banner"): not AI-drawn but built
# by generate/banner.py (one themed pennant + stamped glyphs), allowed only in a
# decor context (see _is_decor_context). Everything else here stays banned.
BANNED_FORM_WORDS = ("banner", "garland", "bunting", "pennant", "envelope",
                     "gift wallet", "gift box", "paper box", "papel picado")
LETTER_BANNER = "letter_banner"

# A decor context (theme or archetype) is the only place a letter_banner may appear.
DECOR_TERMS = ("classroom", "nursery", "playroom", "teacher", "party", "birthday",
               "baby shower", "bridal shower", "shower", "wedding", "graduation",
               "holiday", "christmas", "halloween", "easter", "thanksgiving",
               "decor", "banner", "bunting", "garland", "pennant", "nursery")


def _is_letter_banner(item) -> bool:
    return getattr(item, "asset_type", "") == LETTER_BANNER


def _is_decor_context(term: str, idea_arch: str | None) -> bool:
    t = (term or "").lower()
    return idea_arch == "banner_decor" or any(w in t for w in DECOR_TERMS)


def _is_banned_form(item) -> bool:
    if _is_letter_banner(item):   # sanctioned deterministic form — never banned here
        return False
    hay = f"{item.asset_type} {item.name}".lower()
    return any(w in hay for w in BANNED_FORM_WORDS)


def _load_archetype_system(idea_arch: str | None, market_arch: str) -> str:
    """Build the system prompt, enriched by product_ideas archetype guidance."""
    base = PRINT_SYSTEM if market_arch == "print" else SYSTEM

    if idea_arch:
        try:
            from ..product_ideas import archetype_system_hint, archetype_format
            hint = archetype_system_hint(idea_arch)
            fmt = archetype_format(idea_arch)
        except Exception:
            hint, fmt = "", ""

        if hint:
            extra = f"\n\nPRODUCT FORMAT GUIDANCE (override where needed): {hint}"
            if fmt:
                extra += f"\nFormat detail: {fmt}"
            base = base + extra

    return base


def design_bundle(term: str, rationale: str = "",
                  top_selling_titles: list[str] | None = None,
                  top_tags: list[str] | None = None,
                  archetype: str = "planner",
                  idea_archetype: str | None = None,
                  buyer_insights: dict | None = None,
                  scope: dict | None = None,
                  previous_plan: dict | None = None,
                  required_fixes: list[str] | None = None) -> dict:
    payload = {"trend": term, "why_it_scored_well": rationale}
    if top_selling_titles:
        payload["top_selling_titles"] = top_selling_titles
    if top_tags:
        payload["top_tags"] = top_tags
    if buyer_insights:
        payload["buyer_insights"] = buyer_insights
    if scope:
        payload["market_scope"] = scope
    if previous_plan:
        payload["previous_plan"] = previous_plan
        payload["required_fixes"] = required_fixes or []
    system = _load_archetype_system(idea_archetype, archetype)
    return complete_json(system, json.dumps(payload, ensure_ascii=False))


def build_product(trend_id: int, term: str,
                  rationale: str = "") -> tuple[Product, list[BundleItem], dict]:
    """Returns an unsaved Product + its BundleItems + a market-intel dict.

    Reads real Etsy market intelligence for the term to (a) pick the ARCHETYPE
    (a cheap single 'print' vs a multi-page 'planner' kit) from what actually
    sells in the niche, and (b) feed top-seller titles + real winning tags into
    the design. The intel dict is persisted by the caller after the product insert.

    Also consults product_ideas.json for archetype hints (questionnaire, coupon_book,
    party_games, etc.) to enrich the system prompt with format guidance.
    """
    intel = {}
    archetype, titles, top_tags = "planner", [], []
    idea_arch = None

    try:
        from ..scoring.etsy_market import market_intel, top_listing_titles
        mi = market_intel(term)
        if mi:
            intel = mi
            archetype = mi.get("archetype", "planner")
            top_tags = mi.get("top_tags", [])
        titles = top_listing_titles(term)
    except Exception as e:
        print(f"[architect] market intel skipped: {e}")

    # Buyer voice: what real reviews of the niche's top listings praise/complain
    # about. The bundle must match the praises and fix a complaint.
    buyer_insights = None
    try:
        from ..scoring.reviews import niche_review_insights
        buyer_insights = niche_review_insights(term)
        if buyer_insights:
            intel["buyer_insights"] = buyer_insights
    except Exception as e:
        print(f"[architect] review mining skipped: {e}")

    # Consult product_ideas.json for archetype hints
    try:
        from ..product_ideas import match_archetype
        idea_arch = match_archetype(term)
        if idea_arch:
            print(f"[architect] product_ideas match: '{term}' -> {idea_arch}")
            # Multi-page archetypes must produce multiple items, not single prints.
            # Force planner archetype so the generate pipeline creates all pages.
            MULTI_PAGE_ARCHETYPES = {
                "coloring_page", "coupon_book", "party_games", "planner_kit",
                "checklist_tracker", "sticker_sheet", "questionnaire", "banner_decor",
            }
            if idea_arch in MULTI_PAGE_ARCHETYPES and archetype == "print":
                print("[architect] overridden archetype: print -> planner (multi-page bundle)")
                archetype = "planner"
    except Exception:
        pass

    scope = market_scope(titles, intel.get("median_price"))
    design = design_bundle(term, rationale, top_selling_titles=titles,
                           top_tags=top_tags, archetype=archetype,
                           idea_archetype=idea_arch, buyer_insights=buyer_insights,
                           scope=scope)

    # Critic pass: no plan spends image credits without a stated unique angle.
    # One revision round — a generic verdict feeds concrete fixes back into a
    # redesign; the (possibly revised) plan and the critique are archived in intel.
    if titles:
        try:
            crit = critique_bundle(design, titles, buyer_insights)
            intel["critic"] = crit
            if crit.get("verdict") == "generic" and crit.get("fixes"):
                print(f"[architect] critic: generic — revising "
                      f"({'; '.join(crit['fixes'])[:90]})")
                design = design_bundle(
                    term, rationale, top_selling_titles=titles,
                    top_tags=top_tags, archetype=archetype,
                    idea_archetype=idea_arch, buyer_insights=buyer_insights,
                    scope=scope, previous_plan=design,
                    required_fixes=crit["fixes"])
                intel["critic_revised"] = True
            else:
                print(f"[architect] critic: distinct — "
                      f"{crit.get('unique_angle', '')[:90]}")
        except Exception as e:
            print(f"[architect] critic skipped: {e}")

    product = Product(
        trend_id=trend_id,
        title_concept=design.get("title_concept", term),
        bundle_type=design.get("bundle_type", f"{term} Bundle"),
        status="planned",
    )
    items = [
        BundleItem(
            product_id=-1,  # set after product insert
            name=it.get("name", ""),
            asset_type=it.get("asset_type", "printable"),
            spec=it.get("spec", ""),
        )
        for it in design.get("items", [])
    ]
    # Hard enforcement of the form rules (belt to the prompt's suspenders):
    #  - banned cut-out/assembly forms are dropped everywhere;
    #  - the sanctioned "letter_banner" is kept ONLY in a decor context, and at
    #    most once per bundle (it renders to a whole print-and-cut set on its own).
    allow_banner = _is_decor_context(term, idea_arch)
    kept, seen_banner = [], False
    for it in items:
        if _is_letter_banner(it):
            if not allow_banner:
                print(f"[architect] dropped letter_banner (non-decor context): {it.name}")
                continue
            if seen_banner:
                print(f"[architect] dropped extra letter_banner (one per bundle): {it.name}")
                continue
            seen_banner = True
            kept.append(it)
            continue
        if _is_banned_form(it):
            print(f"[architect] dropped banned cut-out form: {it.name}")
            continue
        kept.append(it)
    items = kept
    # Print archetype: one print by default, but a SET of 2-4 separate prints
    # is legitimate when the market sells sets (each becomes its own file —
    # never multiple panels crammed into one sheet, see #122 lesson).
    if archetype == "print" and len(items) > 4:
        items = items[:4]
    intel["archetype"] = archetype
    intel["idea_archetype"] = idea_arch
    return product, items, intel
