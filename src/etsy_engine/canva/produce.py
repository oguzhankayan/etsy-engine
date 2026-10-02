"""Canva line v3 orchestrator: brief -> a multi-page SET + delivery + listing.

    architect.plan (LLM: a coherent 3-6 page set, each page's title + items)
      -> poster.generate PER PAGE  (one flat, full-bleed, Magic-Layers-ready image each -> Raywake URL)
      -> _set_html  (all page images combined into ONE multi-page HTML == one Canva design)
      -> delivery.build_pdf (branded PDF: how-to, review request, contact, template link)
      -> copy.listing_copy  (honest 'editable Canva template' title/tags/description)

Everything up to here is automated. The OWNER's final touch (their explicit workflow):
import the set to Canva, run Magic Layers on each page, share it as a template, paste the
link back, then publish. At publish, mockups + listing images are built from the owner's
FINAL Canva design (the agent exports it and runs `canva refresh` first) so the photos match
what the buyer downloads, never the pre-edit renders. ADDITIVE: never touches the PDF pipeline.
"""
from __future__ import annotations

import html
import json
from pathlib import Path

from ..config import OUTPUT_DIR
from . import architect, copy, delivery, design as D, poster

# The Canva work queue is now the DB itself (unified with the PDF line, no parallel JSONL): the main
# pipeline's architect routes each trend by format and records a Canva-routed one as a products row
# (status='routed', format='canva'); `produce-queue` reads those and produces them, which flips the
# status to 'planned'. One product store for both lines.
def queue_pending() -> list[dict]:
    """Canva-routed trends awaiting production (DB-backed): [{product_id, term}], newest first."""
    from .. import db
    return db.pending_canva_products()


def _set_html(urls: list[str]) -> str:
    """Combine full-bleed page images into one multi-page HTML (one Canva design)."""
    body = "".join(
        f'<div data-document-role="page" data-label="Page {i}" lang="en" '
        f'style="width:{D.POSTER_W}px;height:{D.POSTER_H}px;position:relative;overflow:hidden">'
        f'<img src="{html.escape(u, quote=True)}" alt="page {i}" '
        f'style="position:absolute;top:0;left:0;width:{D.POSTER_W}px;height:{D.POSTER_H}px;'
        f'object-fit:cover"/></div>'
        for i, u in enumerate(urls, 1))
    return ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8"></head>'
            '<body style="margin:0">' + body + "</body></html>\n")


def _gen_page_qc(content: dict, aesthetic: str, direction: dict | None, out: Path, i: int,
                 style_brief: str | None, layout: str | None = None, spine: str | None = None) -> dict:
    """Generate one poster page, then gate it on BOTH the text QC (spelling/legibility) AND the
    CREATIVE DIRECTOR (composition, design-system adherence, craft). Regenerate ONCE if either fails
    and keep the better of the two by a combined score. Enforcing the shared design system + spine on
    every page is what keeps the multi-page set consistent. Cost-gated: 2 vision calls/page, a second
    gen only on a real failure."""
    from ..config import settings
    from ..generate import qc
    from . import creative_director as cd

    kind = str(content.get("product_kind") or "")
    exp = poster.expected_texts(content)

    def _render(fname: str) -> dict:
        return poster.generate(content, aesthetic, out_dir=out, filename=fname,
                               style_brief=style_brief, direction=direction, layout=layout, spine=spine)

    def _judge(path: str) -> tuple[bool, float, dict, dict]:
        b = Path(path).read_bytes()
        t = qc.assess_text(b, exp)
        c = cd.assess_page(b, direction=direction, spine=spine or "", kind=kind)
        failed = t.get("status") == "failed" or c.get("status") == "failed"
        combined = 0.4 * float(t.get("score", 0.0)) + 0.6 * float(c.get("score", 0.0))
        return failed, combined, t, c

    gen = _render(f"design_{i}.png")
    if not settings.anthropic_api_key:
        return {"image_path": gen["image_path"], "image_url": gen["url"]}
    failed, combined, t, c = _judge(gen["image_path"])
    if not failed:
        return {"image_path": gen["image_path"], "image_url": gen["url"]}
    print(f"[canva] page {i} QC failed (text {t.get('score', 0):.2f}, craft {c.get('score', 0):.2f}: "
          f"{str(c.get('fix') or t.get('notes') or '')[:70]}) — regenerating once")
    retry = _render(f"design_{i}__retry.png")
    _, combined2, _, _ = _judge(retry["image_path"])
    rp = Path(retry["image_path"])
    if combined2 > combined:                           # promote the better retry into design_i.png
        Path(gen["image_path"]).write_bytes(rp.read_bytes())
        rp.unlink(missing_ok=True)
        return {"image_path": gen["image_path"], "image_url": retry["url"]}
    rp.unlink(missing_ok=True)
    return {"image_path": gen["image_path"], "image_url": gen["url"]}


def prepare(term: str, archetype: str | None = None, out_dir: str | Path | None = None,
            aesthetic: str | None = None, link: str | None = None, no_image: bool = False,
            max_pages: int = 8, product_id: int | None = None) -> dict:
    """Prepare a complete multi-page Canva-template SET for a niche.

    Returns {spec, aesthetic, pages:[{content, image_path, image_url}], set_html, listing,
    delivery_pdf}. Import set_html to Canva for one N-page design; run Magic Layers per page.
    """
    spec = architect.plan(term, archetype)
    if aesthetic and aesthetic in D.AESTHETICS:
        spec["aesthetic"] = aesthetic
    kind = (spec.get("product_kind") or term).strip()

    # DESIGN INTELLIGENCE (so we design to the market, not one preset):
    #  1. `research` distills the niche's WINNING look from real top-seller hero images.
    #  2. the SHARED art director (design.art_director) writes a BESPOKE design system for THIS
    #     product from that research — a custom palette/type/motif direction, not 1 of 5 presets.
    # A forced --aesthetic skips the art director and uses that preset (+ the raw brief). Fails soft.
    rb = style_brief = direction = None
    try:
        from . import research
        rb = research.design_brief(term)
    except Exception as e:  # noqa: BLE001 - research is optional
        print(f"[research] skipped: {e}")
    if rb:
        spec["style_research"] = rb
        if not aesthetic and rb.get("recommended_aesthetic") in D.AESTHETICS:
            spec["aesthetic"] = rb["recommended_aesthetic"]
    if not aesthetic:
        try:
            from ..design import art_director
            direction = art_director.art_direction(term, kind, research=rb,
                                                   fallback=D.aesthetic(spec["aesthetic"]))
            spec["art_direction"] = direction
            print(f"[canva] art director: {direction.get('vibe')!r} (bespoke={direction.get('bespoke')})")
        except Exception as e:  # noqa: BLE001 - art direction is best-effort
            print(f"[art-director] skipped: {e}")
    if direction is None:                    # fixed-aesthetic path: inject the raw research brief
        style_brief = (rb or {}).get("brief")

    out = Path(out_dir or (OUTPUT_DIR / "canva"))
    out.mkdir(parents=True, exist_ok=True)

    pages: list[dict] = []
    for i, pg in enumerate((spec.get("pages") or [])[:max_pages], 1):
        content = dict(pg.get("content") or {})
        content.setdefault("product_kind", kind)
        entry = {"content": content}
        if not no_image:
            g = _gen_page_qc(content, spec["aesthetic"], direction, out, i, style_brief,
                             layout=pg.get("layout"), spine=spec.get("spine"))
            try:      # size to a PRINT-READY BAND: floor >=2160 short (Etsy zoom, if a small native
                from . import mockups as _mk   # engine served it) and ceiling <=2400 short
                _mk._ensure_min_px(Path(g["image_path"]), min_short=2160)   # (trim oversized renders)
                _mk._ensure_max_px(Path(g["image_path"]), max_short=2400)
            except Exception as e:  # noqa: BLE001 - resize is best-effort
                print(f"[canva] page resize skipped: {e}")
            entry.update(image_path=g["image_path"], image_url=g["image_url"])
        pages.append(entry)

    result: dict = {"spec": spec, "aesthetic": spec["aesthetic"], "pages": pages}
    urls = [p["image_url"] for p in pages if p.get("image_url")]
    if urls:
        set_html = out / "set.html"
        set_html.write_text(_set_html(urls), encoding="utf-8")
        result["set_html"] = str(set_html)
        result["page_urls"] = urls

    # Rich, theme-aware listing (mirrors the PDF SEO writer): foregrounds the design theme +
    # the actual pieces + keyword-focused title. Falls back to the plain template copy on failure.
    try:
        from . import listing as clist
        pieces = [{"title": (pg.get("content") or {}).get("title")
                   or (pg.get("content") or {}).get("statement"), "use": pg.get("use", "")}
                  for pg in (spec.get("pages") or [])]
        result["listing"] = clist.build(term, kind, pieces, theme=direction,
                                        market=spec.get("_market"))
    except Exception as e:  # noqa: BLE001 - listing copy is best-effort; never crash prepare
        print(f"[canva] rich listing skipped ({e}); using template copy")
        result["listing"] = copy.listing_copy(kind.title(), niche=term)
    result["delivery_pdf"] = delivery.build_pdf(result["listing"]["title"], link=link,
                                                out_dir=out, aesthetic=spec["aesthetic"])

    # Market-driven price: from the niche median (captured by the architect) + page count, not flat.
    from . import publish as cpub
    median = (spec.get("_market") or {}).get("median_price")
    result["price"] = cpub.market_price(median, len(pages))
    print(f"[canva] price ${result['price']} (niche median {median}, {len(pages)} pages)")

    # Persist as a FIRST-CLASS DB product (Phase 1): a Canva suite now joins the SAME lifecycle as
    # the PDF line — a products row (format='canva') + bundle_items + a listings row — so the
    # learning loop (metrics/rank/renewal) can see it. Best-effort: never crash prepare.
    try:
        from .. import db
        db_pieces = [{"name": (pg.get("content") or {}).get("title")
                      or (pg.get("content") or {}).get("statement"), "use": pg.get("use", "")}
                     for pg in (spec.get("pages") or [])]
        # fill the architect-routed product in place if given, else create a fresh one
        product_id = db.save_canva_product(term, kind, db_pieces, result["listing"],
                                           product_id=product_id)
        result["product_id"] = product_id
        print(f"[canva] DB product #{product_id} (format=canva)")
    except Exception as e:  # noqa: BLE001
        print(f"[canva] DB persist skipped: {e}")

    # Manifest so the (later, after Magic Layers) publish step can pick up where we left off.
    manifest = {"niche": term, "aesthetic": spec["aesthetic"], "product_kind": kind,
                "product_id": product_id,
                "image_paths": [p.get("image_path") for p in pages if p.get("image_path")],
                "image_urls": urls, "listing": result["listing"], "price": result["price"],
                # The niche's winning-style research (what top-seller HEROES look like + the one axis
                # to push past their mean). Persisted so `canva publish` can steer the HERO mockup to
                # the niche instead of a generic flat-lay — the winning-style intel reaches the
                # thumbnail (the CTR gate), not just the interior pages.
                "style_brief": rb,
                "delivery_pdf": result["delivery_pdf"], "set_html": result.get("set_html")}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    result["manifest"] = str(out / "manifest.json")
    return result
