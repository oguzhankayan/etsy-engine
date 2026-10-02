"""Trend -> template spec. The LLM chooses the product type, page layouts and real
editable copy, INFORMED BY THE MARKET: it reads the niche's top-seller titles + scope so it
designs the page STRUCTURE a product of THIS kind actually needs (a guest book = cover +
sign-in + memory prompts; a birthday set = invite + signs + favor tags), not a generic
welcome/info kit. A critic pass then forces one revision on a me-too plan before any image
credit is spent. Reuses `product.architect.market_scope` + `critique_bundle` (no duplication).
"""
from __future__ import annotations

import json
import re

from . import design as D

# The layout vocabulary the image path can compose. More structures = products that differ in
# COMPOSITION, not just palette (the critique's #1 remaining slop tell). poster._content_brief
# renders each of these differently; architect.normalize() gates page layouts against this set.
LAYOUTS = {"welcome", "sheet", "checklist", "two_column", "timeline", "stat", "table",
           "signin", "statement"}

_LAYOUTS_DOC = (
    "welcome: a host/guest welcome sign. content={title, note:[1-2 short lines], section_header, "
    "sections:[4 x {label, lines:[1-3 short]}], footer_title, footer_lines:[1-2]}\n"
    "sheet: a titled info sheet (guide, tips, list). content={title, intro:[0-2 short], "
    "groups:[1-4 x {header, items:[2-8 short strings]}], footer_title, footer_lines:[0-2]}\n"
    "checklist: a checklist the buyer TICKS OFF (each item gets an empty checkbox). "
    "content={title, intro:[0-1 short], items:[5-12 short strings], footer_title}\n"
    "two_column: a side-by-side split or comparison. content={title, left:{header, "
    "items:[2-6]}, right:{header, items:[2-6]}, footer_title}\n"
    "timeline: a schedule / agenda / day-of timeline. content={title, steps:[3-6 x {time, "
    "label, detail}], footer_title}\n"
    "stat: a few BIG numbers. content={title, stats:[2-4 x {number, label}], footer_title}\n"
    "table: a simple grid. content={title, columns:[2-4 headers], rows:[3-8 x [cells...]], footer_title}\n"
    "signin: a sign-in / memory / advice page, MOSTLY BLANK to write on. content={title, "
    "prompt:'one short line', lines: 6-12 (how many ruled blank write-lines)}\n"
    "statement: a single wall-art / quote page (use SPARINGLY, only when it earns its place). "
    "content={statement:'short punchy line', sub:'small line'}"
)


def _system() -> str:
    aes = "\n".join(f"- {k}: {v['label']}" for k, v in D.AESTHETICS.items())
    return (
        "You are the product architect for an Etsy shop selling editable Canva templates. Your ONE "
        "job: decide the exact pages of the FILE the buyer downloads. That file contains ONLY "
        "finished, ready-to-use artifacts: the actual things the buyer prints, displays, writes on, "
        "or edits and sends. Nothing else goes inside it.\n\n"
        "Each page is ONE full-page artifact the buyer uses whole: a sign, a chart, a certificate, a "
        "single card, a menu. It is NEVER a sheet of many small items to cut apart (place cards, gift "
        "tags, stickers, labels, table-number cards): this pipeline bakes ONE design per page, so a "
        "grid of little items renders as a mislabeled table, not real cards. A chart the buyer extends "
        "row by row is one artifact and fine; a sheet of separate little cards is not, and belongs to "
        "a different product line.\n\n"
        "THE TEST, applied to EVERY page you consider: 'what does the buyer physically DO with this "
        "page?' The answer must be a concrete USE (hang it up, tie it onto a gift, sign it, fill it "
        "in, edit the text and send it, frame it, follow it on the day). If the honest answer is "
        "instead 'they read about the product', 'they see what is included', 'they learn how to use "
        "or edit it', or 'it introduces / advertises / indexes the set', then that page does NOT "
        "belong in the file. Everything ABOUT the product (what's inside, how-to, feature or benefit "
        "lists, sample/example tables, a cover-of-contents, 'edit in Canva' captions) lives in the "
        "Etsy LISTING PHOTOS, NEVER in the download. The buyer already paid and knows what they "
        "bought: do not sell to them inside their own file, and never pad the page count with a page "
        "that is ABOUT the product instead of BEING the product.\n\n"
        "For each page you output you MUST state a `use`: the one concrete physical thing the buyer "
        "does with that page. If you cannot name a real use, the page must not exist.\n\n"
        "ONE COHERENT PRODUCT (this is where sets fail): the pages are NOT independent designs, they "
        "are one product a single buyer uses together. FIRST fix a shared SPINE the whole product "
        "obeys: the ONE scenario, and every piece of data that recurs (names, dates, table/seat "
        "assignments, prices, a color or naming scheme). Then EVERY page draws from that SAME spine "
        "and never contradicts it: a guest seated at table 3 is at table 3 on every page; one date "
        "everywhere; a scheme that holds on all pages or on none. Cross-page contradiction is the #1 "
        "failure.\n\n"
        "COMPLETE, coordinated SET (deliver a real bundle, not a thin subset): give every genuinely "
        "DISTINCT piece a buyer of THIS product needs together, coordinated in one aesthetic and one "
        "spine, the way a real matching bundle does. Study what the market's bundles actually include "
        "and match that SCOPE. A coordinated suite is the FULL set of different pieces (a wedding "
        "day-of set: welcome sign, seating chart, table numbers, menu, bar sign, program; an "
        "invitation suite: save the date, invitation, RSVP, details, menu, thank you). Two opposite "
        "failures, both banned: (a) padding ONE artifact into near-identical variants (five versions "
        "of the same seating chart), and (b) under-delivering a bare 1-3 pages where the market sells "
        "a fuller suite. Each piece is DIFFERENT, pulls its weight, and shares the spine (same names, "
        "date, colors). A truly standalone product (one welcome sign) is genuinely one page.\n\n"
        "NO REDUNDANT PAGES (applies to EVERY product, the owner's #1 complaint): each page must do a "
        "DIFFERENT JOB. If you cannot name a DISTINCT concrete `use` for a page that no other page "
        "already covers, it does not belong. Two pages that carry the same information in a new layout "
        "are redundant filler, not a coordinated set: the same sign reworded, the same details "
        "restyled, one subject shown again under a different quote. Use AT MOST ONE short "
        "quote/'statement' page in the whole product. The buyer must never think 'I already saw "
        "this'.\n\n"
        "REALITY CHECK each page against a real buyer using it at THEIR scale with THEIR own data: "
        "never invent a gimmick that doesn't scale (naming 100 tables after 100 towns the buyer would "
        "have to invent), and never write a claim the layout can't hold (a '100+ guests' title over an "
        "8-row table). Placeholder content stays realistic and small enough that swapping in real data "
        "is obvious.\n\n"
        "SCALABLE by the buyer (they edit and DUPLICATE in Canva, but only with what you give them): "
        "never build a scheme that needs bespoke per-item art you ship a FIXED number of. Eight "
        "uniquely-illustrated herb table icons leave a buyer with 12 tables no matching 9th icon, "
        "stuck. Repeating units (tables, seats, days, courses) MUST use plainly extendable "
        "placeholders the buyer can duplicate and renumber themselves (plain numbers, typed text) so "
        "ANY count works. Default to the version that scales; a bespoke motif is decoration around it, "
        "never the load-bearing structure. When a piece is ONE-PER-UNIT (a table number, a place "
        "card, a favor tag), design ONE clean unit per page, a SINGLE large number or name the buyer "
        "duplicates the page and changes, NEVER a page showing several example units side by side (a "
        "'Please Be Seated 1 2 3' poster is not a table number; one card that reads 'Table 1' is).\n\n"
        "Read the trend for what a buyer of THIS product actually receives and uses, and design "
        "exactly those artifacts, varied and complete. If 'top_selling_titles' are provided, learn "
        "what USABLE pieces the best products in this niche deliver (not how they market themselves), "
        "then design an original set of those. NEVER copy their wording. If 'market_scope' is "
        "provided, keep the count and density competitive. If 'previous_plan' and 'required_fixes' "
        "are provided, output a REVISED plan applying EVERY fix.\n\n"
        f"Pick ONE aesthetic that genuinely fits the trend:\n{aes}\n\n"
        "Use exactly as many pages as there are genuinely distinct pieces in the REAL product: one "
        "for a standalone artifact, the full coordinated set (often 6 to 10 pieces) for a suite. "
        "Never pad, never under-deliver. Pick the layout that best fits each piece, varying them so "
        f"no two pages share a look:\n{_LAYOUTS_DOC}\n\n"
        f"{D.CRAFT_RULES}\n\n"
        "PHOTOS (do not miss this): some products are built AROUND a photo of a person and are "
        "UNUSABLE without one — a funeral / memorial / celebration-of-life program (the deceased's "
        "portrait is the centerpiece), a milestone or kids' birthday invitation, a birth / graduation "
        "/ baby announcement. For these, the cover and any tribute or gallery page MUST be built "
        "around a PROMINENT photo so the buyer drops in their loved one's. Mark EVERY such page with "
        '"needs_photo": true and leave clear room for the portrait; the renderer draws an editable '
        "photo placeholder there. If the product has nothing to do with a personal photo, omit the "
        "flag.\n\n"
        "MAINSTREAM PLACEHOLDER SCENARIO (the owner's hard rule): the sample copy you write is "
        "rendered INTO the finished artwork and shown in the listing's preview photos, so it must "
        "depict the SINGLE MOST COMMON, default use of this product — the scenario the typical buyer "
        "of this exact trend has. Use ordinary, universal placeholders (a generic couple, host, or "
        "child; plain names, a plain date, plain wording). NEVER a rare, invented, or edge-case "
        "life-situation to look 'unique' (e.g. an ADOPTION gender reveal, a left-handed-twins party): "
        "that narrows a mass-market design to a near-empty niche and tells the majority of buyers "
        "'this is not for me'. Differentiate through the DESIGN (theme, palette, craft, a fuller "
        "set), never by swapping the mainstream buyer for a niche one in the copy. If the trend "
        "itself names a specific audience, serve THAT audience's common case; otherwise stay generic.\n\n"
        "Content rules: write real, specific placeholder copy a buyer will edit (never lorem); "
        "keep every line short; labels/headers as normal words (the renderer uppercases them); "
        "no em dashes.\n\n"
        'Return JSON ONLY: {"aesthetic":"<name>","product_kind":"<short>","spine":"the one scenario '
        'plus the shared data/scheme every page must obey","pages":[{"layout":"...","use":"the '
        'concrete thing the buyer does with this page","needs_photo":true|false,"content":{...}}]}'
    )


# Products built AROUND a person's photo — unusable without an editable photo placeholder.
_PHOTO_CENTRIC = ("funeral", "memorial", "celebration of life", "in loving memory", "obituary",
                  "birthday invitation", "birthday invite", "first birthday", "kids birthday",
                  "birth announcement", "pregnancy announcement", "graduation announcement",
                  "baby announcement")


def _is_photo_centric(kind: str) -> bool:
    return any(t in (kind or "").lower() for t in _PHOTO_CENTRIC)


# Generic, PRODUCT-AGNOSTIC page de-duplication: a coordinated set is DISTINCT pieces, never the same
# job twice in a new layout. Each page's function is derived from its stated `use` + title/statement;
# a page whose function near-duplicates an earlier one is dropped. No product-specific rules -- this is
# the root fix (holds for weddings, parties, classroom kits, memorials alike), not a funeral patch.
_PAGE_STOP = {"the", "a", "an", "and", "or", "to", "of", "for", "with", "your", "you", "this", "that",
              "page", "on", "in", "it", "read", "fill", "write", "hang", "display", "show", "use",
              "give", "print", "edit", "one", "each", "them", "our", "their", "put", "set", "add"}


def _page_sig(pg: dict) -> set[str]:
    c = pg.get("content") or {}
    text = " ".join(str(x) for x in (pg.get("use"), c.get("title"), c.get("statement"),
                                     c.get("section_header")) if x).lower()
    return {w for w in re.findall(r"[a-z0-9]+", text) if len(w) > 2 and w not in _PAGE_STOP}


def _dedup_pages(pages: list[dict]) -> list[dict]:
    """Drop any page whose FUNCTION near-duplicates an earlier page's (Jaccard of use+title tokens
    >= 0.7). Two pages doing the same job are redundant whatever the product."""
    kept: list[dict] = []
    sigs: list[set[str]] = []
    for p in pages:
        s = _page_sig(p)
        if s and any(len(s & t) / len(s | t) >= 0.7 for t in sigs):
            continue
        if s:
            sigs.append(s)
        kept.append(p)
    return kept


def normalize(spec: dict) -> dict:
    """Validate + default an LLM spec so render.py always gets something it can draw."""
    aes = spec.get("aesthetic")
    if aes not in D.AESTHETICS:
        aes = D.DEFAULT_AESTHETIC
    pages = []
    statements = 0
    for pg in (spec.get("pages") or [])[:10]:      # a full coordinated suite can run ~6-10 pieces
        pg = pg if isinstance(pg, dict) else {}
        layout = pg.get("layout")
        if layout not in LAYOUTS:
            layout = "sheet"
        # AT MOST ONE sentiment/quote page: emotional products (funeral/memorial) tempt the LLM into
        # several near-identical statement pages that just repeat the cover's portrait + name with a
        # different line -- redundant filler, not distinct artifacts (owner-caught). Drop the extras.
        if layout == "statement":
            statements += 1
            if statements > 1:
                continue
        content = dict(pg.get("content") or {})
        # A quote/statement page does NOT get the deceased's portrait (that is the COVER's job);
        # forcing the photo onto it just reproduces the cover with a new line.
        if (pg.get("needs_photo") or content.get("needs_photo")) and layout != "statement":
            content["needs_photo"] = True          # carry the photo-slot flag into the page content
        else:
            content.pop("needs_photo", None)
        pages.append({"layout": layout, "use": str(pg.get("use") or ""), "content": content})
    pages = _dedup_pages(pages)                    # drop pages that repeat an earlier page's function
    if not pages:
        pages = [{"layout": "sheet", "use": "", "content": {"title": spec.get("product_kind") or "Template"}}]
    # Fallback: a photo-centric product (funeral/memorial, invitation, announcement) with no page
    # flagged still gets a photo placeholder on its cover — no photo slot = unusable product.
    kind = spec.get("product_kind", "")
    if _is_photo_centric(kind) and not any(p["content"].get("needs_photo") for p in pages):
        pages[0]["content"]["needs_photo"] = True
    return {"aesthetic": aes, "product_kind": kind,
            "spine": str(spec.get("spine") or ""), "pages": pages}


def market_signal(term: str) -> dict:
    """The niche's competitor signal for structure + pricing: top-seller titles, real tags,
    median price, and a scope hint (typical page count/price). All Etsy-API (no LLM); fails soft."""
    from ..scoring.etsy_market import market_intel, top_listing_titles
    from ..product.architect import market_scope
    titles: list[str] = []
    top_tags: list[str] = []
    median = None
    try:
        titles = top_listing_titles(term)
    except Exception as e:  # noqa: BLE001
        print(f"[canva-architect] titles skipped: {e}")
    try:
        mi = market_intel(term)
        if mi:
            top_tags = mi.get("top_tags", []) or []
            median = mi.get("median_price")
    except Exception as e:  # noqa: BLE001
        print(f"[canva-architect] market intel skipped: {e}")
    return {"titles": titles, "top_tags": top_tags, "median_price": median,
            "scope": market_scope(titles, median)}


def _page_name(pg: dict) -> str:
    c = pg.get("content") or {}
    return str(c.get("title") or c.get("statement") or pg.get("layout") or "page")


def _plan_once(term: str, archetype: str | None, n_pages: int | None, market: dict,
               previous: dict | None = None, fixes: list[str] | None = None) -> dict:
    from ..llm import complete_json
    payload: dict = {"trend": term, "archetype": archetype,
                     "target_pages": n_pages or "3-6 (a complete set)"}
    if market.get("titles"):
        payload["top_selling_titles"] = market["titles"]
    if market.get("top_tags"):
        payload["top_tags"] = market["top_tags"][:12]
    if market.get("scope"):
        payload["market_scope"] = market["scope"]
    if previous:
        payload["previous_plan"] = previous
        payload["required_fixes"] = fixes or []
    user = json.dumps(payload, ensure_ascii=False)
    last = ""
    for _ in range(2):                       # the plan JSON is large + nested; a parse miss is
        try:                                 # retryable, and must never crash prepare
            # a full coordinated suite (6-10 pieces, each with content) is big; too few tokens
            # truncates the JSON -> parse failure -> minimal 1-page fallback (a broken product).
            raw = complete_json(_system(), user, max_tokens=8000)
            if isinstance(raw, list):
                raw = raw[0] if raw else {}
            if isinstance(raw, dict) and raw.get("pages"):
                return normalize(raw)
            last = "no pages in response"
        except Exception as e:  # noqa: BLE001
            last = str(e)[:120]
    print(f"[canva-architect] plan parse failed ({last}); minimal fallback")
    return normalize({"product_kind": term})


def plan(term: str, archetype: str | None = None, n_pages: int | None = None,
         market: dict | None = None) -> dict:
    """Market-informed template spec for a trend (normalized). Reads the niche's top sellers so
    the page STRUCTURE fits the product type, then a critic pass forces one revision on a me-too
    plan. The market signal is attached as spec['_market'] so the caller can reuse it (pricing)."""
    market = market if market is not None else market_signal(term)
    spec = _plan_once(term, archetype, n_pages, market)

    if market.get("titles"):
        try:
            from ..product.architect import critique_bundle
            crit_design = {
                "bundle_type": spec.get("product_kind"),
                "title_concept": spec.get("product_kind"),
                "items": [{"name": _page_name(pg), "asset_type": pg.get("layout")}
                          for pg in spec.get("pages", [])],
            }
            crit = critique_bundle(crit_design, market["titles"])
            spec["_critic"] = crit
            if isinstance(crit, dict) and crit.get("verdict") == "generic" and crit.get("fixes"):
                print(f"[canva-architect] critic: generic — revising "
                      f"({'; '.join(crit['fixes'])[:90]})")
                spec = _plan_once(term, archetype, n_pages, market,
                                  previous=crit_design, fixes=crit["fixes"])
                spec["_critic"] = crit
                spec["_critic_revised"] = True
            else:
                angle = crit.get("unique_angle", "") if isinstance(crit, dict) else ""
                print(f"[canva-architect] critic: distinct — {angle[:80]}")
        except Exception as e:  # noqa: BLE001 - critic is best-effort
            print(f"[canva-architect] critic skipped: {e}")

    spec["_market"] = market
    return spec
