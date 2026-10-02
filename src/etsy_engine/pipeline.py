"""Pipeline orchestrator. Faz 1: collect -> score -> select -> architect.

Implements the daily funnel from the spec:
  inspect (100) -> filter (20) -> opportunities (10) -> products (3)
Each stage writes durable rows to SQLite so it can be re-run independently.
"""
from __future__ import annotations

import dataclasses

from . import db
from .config import settings
from .generate.generator import generate_product
from .mockups.generator import generate_mockups
from .product.architect import build_product
from .scoring.ip_filter import blocklist_hit
from .scoring.scorer import score_trends
from .seo.writer import write_listing
from .sources import ENABLED_SOURCES


def _is_proven_listing(row: dict) -> bool:
    """Use the same buyer-interest floors as performance-gated seed feedback."""
    from .sources.seeds import SEED_MIN_FAVORITES, SEED_MIN_VIEWS

    return (
        int(row.get("sales") or 0) > 0
        or int(row.get("views") or 0) >= SEED_MIN_VIEWS
        or int(row.get("favorites") or 0) >= SEED_MIN_FAVORITES
    )


def collect(sources: list[str] | None = None, limit: int | None = None) -> int:
    """Stage 1 — Trend Hunter. Fetch from sources, drop blocklisted, store."""
    db.init_db()
    sources = sources or list(ENABLED_SOURCES)
    limit = limit or settings.funnel_inspect
    per_source = max(1, limit // len(sources))

    stored = 0
    for key in sources:
        cls = ENABLED_SOURCES.get(key)
        if not cls:
            print(f"[collect] unknown source '{key}', skipping")
            continue
        try:
            trends = cls().fetch(per_source)
        except Exception as e:
            print(f"[collect] source '{key}' failed: {e}")
            continue
        for t in trends:
            if blocklist_hit(t.term):  # cheapest possible IP gate
                continue
            db.upsert_trend(t)
            stored += 1
        print(f"[collect] {key}: {len(trends)} fetched")
    print(f"[collect] stored {stored} trends total")
    return stored


def score() -> int:
    """Stage 2 — Opportunity Scorer. Score everything not yet scored."""
    pending = db.unscored_trends()
    print(f"[score] scoring {len(pending)} trends...")
    scores = score_trends(pending)
    for s in scores:
        db.upsert_score(s)
    print(f"[score] wrote {len(scores)} scores")
    return len(scores)


def validate(top_k: int | None = None) -> int:
    """Stage 2.5 — validate top candidates with REAL Etsy market data (A).

    Reads competition (listing count) + demand (top-listing favorites) for the
    leading opportunities and blends them with the LLM composite into an
    adjusted_score that drives final ranking.
    """
    from .scoring.etsy_market import market_intel, market_signal

    top_k = top_k or max(settings.funnel_opportunities * 3, 35)
    opps = db.top_opportunities(limit=top_k)
    print(f"[validate] checking Etsy market for {len(opps)} candidates...")

    # Competitive-intelligence enrichment (context.dev) — ON by default (set context_dev_enabled=False
    # to disable). Bounded by a per-run candidate cap. It attaches a market_intel block (saturation +
    # buyer gaps) to high-scoring candidates before ranking; it never bypasses the EV gate downstream.
    enricher = None
    if settings.context_dev_enabled:
        from .scoring.competitive_intel import CompetitiveEnricher
        enricher = CompetitiveEnricher()
        print(f"[validate] context.dev enrichment ON (cap {enricher.cap}, "
              f"score>={enricher.min_score})")

    checked = 0
    for o in opps:
        # NEW FUNNEL: rank on REAL Etsy demand + winnability, not the LLM guess.
        mi = market_intel(o["term"], sample=60)
        if mi and mi.get("analyzed"):
            emerging = mi.get("emerging_niche", 0.0)
            sig = {"count": mi["count"], "avg_favorites": mi["avg_favorites"],
                   "competition_score": mi["competition_score"],
                   "demand_score": mi["demand_score"],
                   "emerging_niche": emerging,
                   "emerging_shops": mi.get("emerging_shops", 0)}
            beat = mi.get("beatability", 0.0)
            # Demand-first: real demand + winnability dominate; LLM composite a prior.
            # A niche where small shops are climbing gets a bounded winnability bonus.
            # Weights sum to 1.0 so adjusted stays comparable across formulas.
            adjusted = round(0.35 * o["composite"] + 0.30 * mi["demand_score"]
                             + 0.25 * beat + 0.10 * emerging, 4)
            note = (f"daily~{mi['avg_daily_views']:>5} beat={beat:.2f} "
                    f"emrg={emerging:.2f} [{mi['archetype']}]")
        else:
            sig = market_signal(o["term"])
            if not sig:
                continue
            adjusted = round(0.6 * o["composite"] + 0.2 * sig["competition_score"]
                             + 0.2 * sig["demand_score"], 4)
            note = ""
        db.upsert_market_signal(o["trend_id"], sig, adjusted)
        checked += 1
        print(f"[validate] {o['term'][:34]:34} listings={sig['count']:>6} "
              f"{note} adj={adjusted:.3f}")
        # Paid enrichment ONLY for candidates that cleared stage-02 scoring above the threshold
        # (cheap discovery first, paid validation second). enrich() re-checks the gate + cap + cache.
        if enricher is not None:
            block = enricher.enrich(o["term"], float(o.get("composite") or 0),
                                    market_intel=mi if (mi and mi.get("analyzed")) else None)
            if block:
                db.upsert_competitive_intel(o["trend_id"], block)
                print(f"[validate][ctx] '{o['term'][:28]}' gaps={block.get('gap_analysis')}")
    print(f"[validate] validated {checked} candidates")
    return checked


def _select_for_production(candidates: list[dict], n: int, canva_quota: int) -> list[dict]:
    """Pick n opportunities to build this run, RESERVING up to `canva_quota` slots for the highest-
    ranked Canva-suitable candidates before filling the rest with archetype-diverse selection.

    `candidates` is already rank-ordered. Without this, the big-but-saturated editable markets
    (weddings, invitations, funeral programs) rank below winnable PDF niches, so with only a few
    products per run the Canva line starves; the reservation guarantees the best available Canva
    candidate is built each run.
    """
    from .canva import detect as canva_detect
    from .product_ideas import select_diverse

    picks: list[dict] = []
    if canva_quota > 0:
        for o in candidates:
            sig = canva_detect.canva_suitability(o["term"])
            if sig and sig["suitable"]:
                picks.append(o)
                if len(picks) >= canva_quota:
                    break
    picked_ids = {o["trend_id"] for o in picks}
    remaining = [o for o in candidates if o["trend_id"] not in picked_ids]
    return picks + select_diverse(remaining, max(0, n - len(picks)))


def architect(n: int | None = None, route_canva: bool = True) -> int:
    """Stage 3 — Product/Bundle Architect on the top (market-ranked) opportunities.

    Per-trend FORMAT ROUTING (the decision lives here, in the main flow, driven by the
    trend): a trend whose product is IDENTITY/EVENT-personalized — the buyer swaps in their
    OWN name/date/event/brand/prices (signs, invitations, weddings, host/guest, classroom,
    gift tags) — routes to the Canva-editable line (queued for a design set + Magic Layers).
    Everything the buyer merely FILLS IN or TICKS OFF (trackers, checklists, planners, logs)
    and every pure-print product builds a print-at-home PDF exactly as before. The rule lives
    in `canva.detect.canva_suitability`; `route_canva=False` forces pure-PDF.
    """
    from .canva import detect as canva_detect

    from . import history

    n = n or settings.funnel_products
    # In-flight products, EXCLUDING ev_blocked/deleted so a trend retired by a transient EV projection
    # (or a deleted dup) can be reconsidered on a later run instead of being excluded forever.
    inflight = [p for p in db.product_terms() if p.get("status") not in ("ev_blocked", "deleted")]
    existing_trends = {p["trend_id"] for p in inflight}
    # Canva-routed-but-not-yet-produced trends live in the DB now (status='routed'); skip re-routing.
    queued_terms = {r["term"] for r in db.pending_canva_products()} if route_canva else set()
    # Theme-dedup vs in-flight products + the Canva queue (a DIFFERENT trend with the SAME theme, e.g.
    # "funeral program template" vs a routed "funeral program", must not be re-queued across runs).
    # Tokenize the taken terms ONCE (not once per candidate).
    taken_sigs = [s for s in (history.theme_tokens(t)
                              for t in ([p["term"] for p in inflight] + list(queued_terms))) if s]
    all_candidates = [
        o for o in db.top_opportunities(limit=max(500, n * 30))
        if o["trend_id"] not in existing_trends and o["term"] not in queued_terms
        and not history.collides_with_token_sets(history.theme_tokens(o["term"]), taken_sigs)
    ]
    # Never let an unvalidated LLM prior outrank a candidate whose score was
    # reduced by real Etsy evidence. Fall back only for a brand-new empty DB.
    validated = [o for o in all_candidates if o.get("adjusted_score") is not None]
    candidates = validated or all_candidates
    # Reserve a Canva slot so the saturated-but-huge editable markets aren't perpetually buried.
    opps = _select_for_production(candidates, n,
                                  canva_quota=min(settings.canva_min_per_run, n) if route_canva else 0)
    print(f"[architect] routing {len(opps)} opportunities (PDF vs Canva per trend)...")
    built = 0
    for o in opps:
        if route_canva:
            sig = canva_detect.canva_suitability(o["term"])
            if sig and sig["suitable"]:
                db.route_to_canva(o["trend_id"], o["term"])
                print(f"[architect] [canva:{sig['kind']}] {o['term']} -> Canva line "
                      "(routed as DB product; `canva produce-queue`, then Magic Layers)")
                built += 1
                continue
        product, items, intel = build_product(o["trend_id"], o["term"], o.get("rationale", ""))
        pid = db.insert_product(product)
        for it in items:
            db.insert_bundle_item(dataclasses.replace(it, product_id=pid))
        db.upsert_product_intel(pid, intel.get("archetype", "planner"),
                                intel.get("median_price"), intel.get("top_tags", []), intel)
        built += 1
        print(f"[architect] [pdf:{intel.get('archetype','planner')}] {product.bundle_type} "
              f"({len(items)} items)")
    # Seed feedback happens at METRICS time (performance-gated), not here:
    # feeding back merely-selected terms let 1-view duds seed future discovery.
    return built


def generate(variations: int = 2, ev_min: float | None = None) -> int:
    """Stage 4/Faz 2 (== stage 05, image generation) — generate assets for every 'planned' product.

    An EXPECTED-VALUE GATE runs first (the cost circuit-breaker): each planned product is projected
    from its stored market signals, and any whose EV is below the floor (`ev_min`, else
    `settings.ev_gate_min`) is marked 'ev_blocked' and NEVER reaches image generation, so no credits
    are spent on it. The gate is deterministic — no API/LLM call — and fails open on missing data, so
    a blocked run records zero new spend and stages 01-04 are untouched.
    """
    from .scoring import ev_gate

    planned = db.products_by_status("planned")
    passed, blocked = ev_gate.screen(planned, ev_min)
    for p in blocked:
        db.set_product_status(p["id"], "ev_blocked")
        print(f"[ev-gate] BLOCKED #{p['id']} {p['bundle_type']} — {p['_ev']['reason']}; no image spend")
    print(f"[generate] generating assets for {len(passed)} products"
          + (f" ({len(blocked)} blocked by EV gate)" if blocked else "") + "...")
    total = 0
    for p in passed:
        print(f"[generate] {p['bundle_type']}")
        total += generate_product(p, variations=variations)
    print(f"[generate] produced {total} assets")
    return total


def mockups(statuses: tuple[str, ...] = ("generated", "qc_passed")) -> int:
    """Stage 5 (Faz 3) — generate Etsy listing images for ready products."""
    total = 0
    for status in statuses:
        for p in db.products_by_status(status):
            print(f"[mockups] {p['bundle_type']}")
            total += generate_mockups(p)
            db.set_product_status(p["id"], "mockups_done")
    print(f"[mockups] produced {total} mockups")
    return total


def seo() -> int:
    """Stage 6 (Faz 3) — write Etsy SEO copy for products with mockups."""
    products = db.products_by_status("mockups_done")
    print(f"[seo] writing listings for {len(products)} products...")
    for p in products:
        listing = write_listing(p)
        db.upsert_listing(listing)
        db.set_product_status(p["id"], "seo_done")
        print(f"[seo] {p['bundle_type']}: \"{listing.title[:60]}...\"")
    return len(products)


def produce_one(opp: dict, lane: str, variations: int = 1) -> int | None:
    """Full pipeline for one opportunity: bundle -> assets -> mockups -> seo ->
    draft. Records the lane. Returns the product id (or None on failure)."""
    from .publish.publisher import publish_product
    from . import lanes

    product, items, intel = build_product(opp["trend_id"], opp["term"], opp.get("rationale", ""))
    pid = db.insert_product(product)
    for it in items:
        db.insert_bundle_item(dataclasses.replace(it, product_id=pid))
    db.upsert_product_intel(pid, intel.get("archetype", "planner"),
                            intel.get("median_price"), intel.get("top_tags", []), intel)
    pd = next(p for p in db.products_with_items() if p["id"] == pid)
    arch = intel.get("archetype", "planner")
    print(f"[produce/{lane}] #{pid} [{arch}] {product.bundle_type}  (from '{opp['term']}')")
    # EV gate (same cost circuit-breaker as the batch generate stage): don't spend image credits on a
    # product whose projected value is below the floor. The bundle plan (stage 04) already ran; we
    # simply stop before stage 05 image generation. Fails open on thin data.
    from .scoring import ev_gate
    verdict = ev_gate.evaluate(pid)
    if not verdict["passes"]:
        db.set_product_status(pid, "ev_blocked")
        print(f"[produce/{lane}] #{pid} BLOCKED by EV gate — {verdict['reason']}; no image spend")
        return None
    from .publish.publisher import enforce_catalog_cap
    enforce_catalog_cap()   # refuse at the cap BEFORE image spend, not after at the publish step
    generate_product(pd, variations=variations)
    # Completeness guard: never ship a bundle that is short a page.
    n_items, n_assets = len(db.bundle_items_for(pid)), len(db.assets_for_product(pid))
    if n_assets < n_items:
        raise RuntimeError(
            f"#{pid} incomplete: {n_assets}/{n_items} pages generated — not publishing")
    generate_mockups(pd)
    db.upsert_listing(write_listing(pd))
    publish_product(pid)
    lanes.set_last_lane(lane)
    print(f"[produce/{lane}] #{pid} DONE -> draft")

    # Self-improving product ideas: record what archetype was produced
    try:
        from .product_ideas import feedback_from_product
        idea_arch = intel.get("idea_archetype") or intel.get("archetype")
        feedback_from_product(opp["term"], archetype=idea_arch)
    except Exception:
        pass

    return pid


def demo(term: str, max_pages: int = 4, variations: int = 1) -> dict:
    """No-Etsy-account demo: one niche -> a finished, sellable product on disk.

    Runs the real production stages (architect -> generate -> mockups -> SEO) for `term`
    and writes the listing copy next to the images. Etsy market data is used when Etsy keys
    are configured and skipped gracefully otherwise. Nothing is published. `max_pages` caps
    the bundle so a first run stays cheap (0 = the architect's full plan).
    Needs ANTHROPIC_API_KEY + RAYWAKE_API_KEY.
    """
    import json

    from .config import OUTPUT_DIR
    from .models import Tier, Trend

    from .generate.raywake import require_key, total_spend

    require_key()
    settings.require("anthropic_api_key")
    db.init_db()
    spent_before = total_spend()
    trend_id = db.upsert_trend(Trend(source="demo", term=term, tier=Tier.EVERGREEN))
    product, items, intel = build_product(trend_id, term, "demo run")
    if max_pages and len(items) > max_pages:
        items = items[:max_pages]
    pid = db.insert_product(product)
    for it in items:
        db.insert_bundle_item(dataclasses.replace(it, product_id=pid))
    db.upsert_product_intel(pid, intel.get("archetype", "planner"),
                            intel.get("median_price"), intel.get("top_tags", []), intel)
    pd = next(p for p in db.products_with_items() if p["id"] == pid)
    print(f"[demo] #{pid} {product.bundle_type} — {len(items)} page(s)")

    generate_product(pd, variations=variations)   # sets generated/qc_passed
    generate_mockups(pd)
    db.set_product_status(pid, "mockups_done")
    listing = write_listing(pd)
    db.upsert_listing(listing)
    db.set_product_status(pid, "seo_done")

    out = OUTPUT_DIR / str(pid)
    out.mkdir(parents=True, exist_ok=True)
    tags = json.loads(listing.tags or "[]")
    (out / "listing.md").write_text(
        f"# {listing.title}\n\n**Tags:** {', '.join(tags)}\n\n{listing.description}\n",
        encoding="utf-8")
    spent = total_spend()
    print(f"[demo] done -> {out}  (pages, mockups/, listing.md)")
    return {"product_id": pid, "dir": str(out), "title": listing.title, "tags": tags,
            "images": spent["images"] - spent_before["images"],
            "credits": round(spent["credits"] - spent_before["credits"], 2)}


def finalize_product(pid: int, variations: int = 1) -> int | None:
    """Produce an already-PLANNED PDF product end to end: EV gate -> assets -> mockups -> SEO ->
    Etsy DRAFT. This is the owner-approval path (`etsy-engine approve`). It reuses the exact stages;
    the EV gate still guards image spend, so approval does NOT bypass it."""
    from .publish.publisher import enforce_catalog_cap, publish_product
    from .scoring import ev_gate
    from .seo.writer import write_listing

    pd = next((p for p in db.products_with_items() if p["id"] == pid), None)
    if not pd:
        raise RuntimeError(f"product #{pid} not found or has no items")
    verdict = ev_gate.evaluate(pid)
    if not verdict["passes"]:
        db.set_product_status(pid, "ev_blocked")
        print(f"[approve] #{pid} BLOCKED by EV gate — {verdict['reason']}; no image spend")
        return None
    enforce_catalog_cap()   # refuse at the cap BEFORE spending image/mockup/SEO credits, not after
    print(f"[approve] #{pid} {pd['bundle_type']} — producing (PDF)...")
    generate_product(pd, variations=variations)
    n_items, n_assets = len(db.bundle_items_for(pid)), len(db.assets_for_product(pid))
    if n_assets < n_items:
        raise RuntimeError(f"#{pid} incomplete: {n_assets}/{n_items} pages — not publishing")
    generate_mockups(pd)
    db.upsert_listing(write_listing(pd))
    publish_product(pid)
    # Feed the self-learning product-ideas loop, exactly like produce_one (approval must not skip it).
    try:
        from .product_ideas import feedback_from_product
        pintel = db.get_product_intel(pid) or {}
        idea_arch = (pintel.get("intel") or {}).get("idea_archetype") or pintel.get("archetype")
        feedback_from_product(db.provenance(pid).get("term") or pd["bundle_type"], archetype=idea_arch)
    except Exception:  # noqa: BLE001
        pass
    print(f"[approve] #{pid} DONE -> Etsy draft")
    return pid


def produce_approved(product_ids: list[int]) -> dict:
    """Produce the owner-approved routed products. PDF -> finalize to an Etsy draft; Canva -> build the
    design set (the owner then runs Magic Layers, `canva publish`). Only approved products are made."""
    result: dict[str, list[int]] = {"pdf_drafted": [], "canva_prepared": [], "blocked": [], "skipped": []}
    for pid in product_ids:
        p = db.product(pid)
        if not p:
            result["skipped"].append(pid)
            continue
        if p["format"] == "pdf" and p["status"] == "planned":
            try:
                done = finalize_product(pid)
                (result["pdf_drafted"] if done else result["blocked"]).append(pid)
            except Exception as e:  # noqa: BLE001 — one product's failure must not stop the batch
                print(f"[approve] #{pid} failed: {e}")
                result["skipped"].append(pid)
        elif p["format"] == "canva" and p["status"] == "routed":
            try:
                from .canva import produce as cprod
                from .publish.publisher import enforce_catalog_cap
                from .scoring import ev_gate
                # The Canva design set is the most expensive build, so it must clear the EV gate + the
                # catalog cap BEFORE any image spend, exactly like the PDF path (review finding #1/#2).
                verdict = ev_gate.evaluate(pid)
                if not verdict["passes"]:
                    db.set_product_status(pid, "ev_blocked")
                    print(f"[approve] canva #{pid} BLOCKED by EV gate — {verdict['reason']}; no spend")
                    result["blocked"].append(pid)
                    continue
                enforce_catalog_cap()
                term = db.provenance(pid).get("term") or p["title_concept"]
                cprod.prepare(term, product_id=pid)
                result["canva_prepared"].append(pid)
            except Exception as e:  # noqa: BLE001
                print(f"[approve] canva #{pid} failed: {e}")
                result["skipped"].append(pid)
        else:
            result["skipped"].append(pid)
    return result


def produce(n: int, lane: str | None = None) -> list[int]:
    """Produce n products alternating EVERGREEN/VIRAL lanes (3+3 for n=6),
    starting opposite the last product's lane. Deduped vs durable history."""
    from . import lanes

    seq = lanes.lane_sequence(n, lane)
    used: set[str] = set()
    ev = lanes.evergreen_picks(seq.count("evergreen"), used)
    vi = lanes.viral_picks(seq.count("viral"), used)
    pools = {"evergreen": iter(ev), "viral": iter(vi)}

    plan = []
    for L in seq:
        nxt = next(pools[L], None)
        if nxt:
            plan.append((L, nxt))
    print(f"[produce] plan ({len(plan)}/{n}): "
          + ", ".join(f"{L}:{o['term'][:28]}" for L, o in plan))

    made = []
    for L, o in plan:
        try:
            pid = produce_one(o, L)
            if pid:
                made.append(pid)
        except Exception as e:
            print(f"[produce] '{o['term']}' failed: {e}")
    return made


def run(sources: list[str] | None = None, with_assets: bool = False,
        full: bool = False, route_canva: bool = True) -> None:
    """Funnel: collect -> score -> validate -> architect (+ Faz 2/3 with flags).

    architect decides PDF vs Canva PER TREND; Canva-routed trends are queued for the
    Canva line (produce-queue -> Magic Layers). `route_canva=False` forces pure-PDF.
    """
    # Same stages, same order — now each records a run_log row (stage, status, timestamp) for
    # post-hoc failure visibility. Logging is best-effort and never alters stage behavior.
    stages: list[tuple[str, callable]] = [
        ("collect", lambda: collect(sources)), ("score", score),
        ("validate", validate), ("architect", lambda: architect(route_canva=route_canva)),
    ]
    if with_assets or full:
        stages.append(("generate", generate))
    if full:
        stages += [("mockups", mockups), ("seo", seo)]
    for name, fn in stages:
        try:
            fn()
        except Exception as e:
            db.log_run(name, "failed", str(e)[:200])
            raise
        db.log_run(name, "ok")

    # Present the routed products for the owner's approval — nothing is produced until approved.
    if not (with_assets or full):
        pending = db.pending_approval()
        n_pdf = sum(1 for p in pending if p["format"] == "pdf")
        n_canva = sum(1 for p in pending if p["format"] == "canva")
        print(f"[run] complete — {len(pending)} product(s) awaiting your approval "
              f"({n_pdf} PDF, {n_canva} Canva); nothing produced yet.")
        print("[run] Review them:  etsy-engine review   →   approve:  etsy-engine approve --id <N> | --all")


def reprice_prints(dry_run: bool = False) -> int:
    """Re-price every listing to its niche median, clamped to its archetype band
    (prints: print band; bundles: bundle band, never below the flat floor). Run
    after a price-band change or market shift. Returns the number (re)priced."""
    from .config import settings
    from .publish.publisher import set_listing_price

    n = 0
    for p in db.products_with_items():
        el = db.get_etsy_listing(p["id"])
        if not el:
            continue
        pintel = db.get_product_intel(p["id"]) or {}
        if pintel.get("archetype") == "print":
            med = pintel.get("median_price")
            price = round(min(settings.print_price_max,
                              max(settings.print_price_min,
                                  float(med or settings.print_price_max))), 2)
        else:
            from .publish.publisher import bundle_price
            price = bundle_price(len(db.bundle_items_for(p["id"])))
        lid = el["etsy_listing_id"]
        if dry_run:
            print(f"[reprice] would set #{p['id']} listing {lid} -> ${price} "
                  f"({pintel.get('archetype','planner')}, median {med})")
            n += 1
            continue
        try:
            set_listing_price(lid, price)
            print(f"[reprice] #{p['id']} listing {lid} -> ${price} "
                  f"({pintel.get('archetype', 'planner')})")
            n += 1
        except Exception as e:
            print(f"[reprice] #{p['id']} listing {lid} failed: {e}")
    print(f"[reprice] {'would reprice' if dry_run else 'repriced'} {n} listing(s)")
    return n


def renew_listings(dry_run: bool = False, report_only: bool = False) -> int:
    """Keep-alive enforcement (Berkay's rule): make sure evergreen + seasonal
    listings never expire, so they accrue search/sales history year-round.

    For every live listing we ensure Etsy `should_auto_renew` is on (a one-off
    viral item may legitimately be left to lapse, but those are the exception).
    A seasonal listing that lacks auto-renew is the dangerous case — renewing it
    is what stops next season from starting from zero. Returns the number of
    listings that were (or would be) renewed.
    """
    from .publish import etsy_client as ec
    from .publish.publisher import resolve_shop_id
    from .sources.seeds import season_for

    listings = db.products_with_listings()

    # Backfill: listings published before seasonal tagging existed get tagged now
    # by inferring the season from their SEO title, so the current live inventory
    # is protected too (not just future publishes).
    already = {r["etsy_listing_id"] for r in db.seasonal_listings()}
    for r in listings:
        if r["etsy_listing_id"] in already:
            continue
        season = season_for(r.get("listing_title", "") or "")
        if season:
            db.upsert_etsy_listing(r["product_id"], r["etsy_listing_id"],
                                   r.get("url", ""), state=r.get("state", "draft"),
                                   is_seasonal=True, season=season)

    seasonal_ids = {r["etsy_listing_id"] for r in db.seasonal_listings()}
    metrics = {r["etsy_listing_id"]: r for r in db.latest_metrics()}
    proven_ids = {
        lid for lid, row in metrics.items()
        if _is_proven_listing(row)
    }
    if report_only:
        print(f"[renew] {len(listings)} listings, {len(seasonal_ids)} seasonal (keep-alive):")
        for r in listings:
            lid = r["etsy_listing_id"]
            flag = f"seasonal:{[s['season'] for s in db.seasonal_listings() if s['etsy_listing_id'] == lid]}" if lid in seasonal_ids else "standard"
            print(f"  #{r['product_id']} listing {lid} [{r['state']}] {flag} — {r.get('listing_title', '')[:60]}")
        return 0

    from .models import Tier
    shop_id = resolve_shop_id()
    renewed = 0
    for r in listings:
        lid = r["etsy_listing_id"]
        if r.get("state") != "active":
            continue
        is_seasonal = lid in seasonal_ids
        # Mirror the publish-time policy: keep evergreen + seasonal alive; only a
        # genuine one-off viral moment with no proven interest is left to lapse.
        prov = db.provenance(r["product_id"])
        is_proven = lid in proven_ids
        is_oneoff_viral = (
            int(prov.get("tier", Tier.VIRAL)) == int(Tier.VIRAL)
            and not is_seasonal
            and not is_proven
        )
        if is_oneoff_viral:
            continue
        if dry_run:
            reason = "seasonal" if is_seasonal else "proven" if is_proven else "evergreen"
            print(f"[renew] would ensure auto-renew on listing {lid} ({reason})")
            renewed += 1
            continue
        try:
            ec.request("PATCH", f"/shops/{shop_id}/listings/{lid}",
                       json={"should_auto_renew": True})
            db.mark_listing_renewed(lid)
            renewed += 1
            reason = "seasonal" if is_seasonal else "proven" if is_proven else "evergreen"
            print(f"[renew] auto-renew ensured on listing {lid} ({reason})")
        except Exception as e:
            print(f"[renew] listing {lid} failed: {e}")
    print(f"[renew] {'would renew' if dry_run else 'renewed'} {renewed} listing(s)")
    return renewed
