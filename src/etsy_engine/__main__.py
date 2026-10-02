"""CLI entrypoint: `etsy-engine <command>` (or `python -m etsy_engine`)."""
from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from . import db, pipeline
from .config import settings

console = Console()


@click.group()
def cli() -> None:
    """Etsy Trend Response Engine — Faz 1 CLI."""


@cli.command()
@click.option("--sources", default=None, help="Comma list: ideas,reddit,etsy,google,velocity")
def collect(sources: str | None) -> None:
    """Stage 1 — fetch trends from sources."""
    pipeline.collect(sources.split(",") if sources else None)


@cli.command()
def score() -> None:
    """Stage 2 — score all unscored trends with Claude."""
    pipeline.score()


@cli.command()
@click.option("--top-k", default=None, type=int, help="How many candidates to validate")
def validate(top_k: int | None) -> None:
    """Stage 2.5 — validate top candidates with real Etsy market data."""
    pipeline.validate(top_k)


@cli.command()
@click.option("-n", default=None, type=int, help="How many products to design")
@click.option("--no-canva", is_flag=True, help="Force pure-PDF (skip per-trend Canva routing)")
def architect(n: int | None, no_canva: bool) -> None:
    """Stage 3 — route each top trend to PDF or the Canva line, then build the PDF ones."""
    pipeline.architect(n, route_canva=not no_canva)


@cli.command()
@click.option("--variations", default=2, type=int, help="Images per asset (pick best)")
def generate(variations: int) -> None:
    """Stage 4 (Faz 2) — generate GPT-Image-2 assets for planned products."""
    pipeline.generate(variations=variations)


@cli.command(name="regen-item")
@click.option("--item-id", required=True, type=int, help="bundle_item id to regenerate")
@click.option("--variations", default=2, type=int, help="images to try (pick best)")
@click.option("--only-if-better", is_flag=True, help="keep the existing asset unless the new one scores higher")
def regen_item(item_id: int, variations: int, only_if_better: bool) -> None:
    """Surgically regenerate ONE bundle item's asset (no re-rolling the whole bundle)."""
    from .generate.generator import regenerate_item
    r = regenerate_item(item_id, variations=variations, only_if_better=only_if_better)
    console.print(f"[green]regen[/] item {item_id}: {r.get('status')} score={r.get('score')}")


@cli.command()
def mockups() -> None:
    """Stage 5 (Faz 3) — generate Etsy listing images for ready products."""
    pipeline.mockups()


@cli.command()
def seo() -> None:
    """Stage 6 (Faz 3) — write Etsy SEO copy (title/tags/description/alt/FAQ)."""
    pipeline.seo()


@cli.command()
@click.option("--sources", default=None, help="Comma list: ideas,reddit,etsy,google,velocity")
@click.option("--with-assets", is_flag=True, help="Continue into Faz 2 generation")
@click.option("--full", is_flag=True, help="Run Faz 1+2+3 (assets, mockups, SEO)")
@click.option("--no-canva", is_flag=True, help="Force pure-PDF (skip per-trend Canva routing)")
def run(sources: str | None, with_assets: bool, full: bool, no_canva: bool) -> None:
    """Run collect -> score -> validate -> architect (+ asset stages via flags).

    architect routes each trend to PDF or the Canva line per the trend itself.
    """
    pipeline.run(sources.split(",") if sources else None,
                 with_assets=with_assets, full=full, route_canva=not no_canva)


@cli.command()
def review() -> None:
    """Show the products the engine routed and is holding for your approval (nothing produced yet).

    PDF products are ready to generate; Canva products are ready for a design set + Magic Layers.
    Each shows its format decision, piece count, source term, and any context.dev buyer-gap analysis.
    """
    from . import db

    db.init_db()
    pending = db.pending_approval()
    if not pending:
        click.echo("No products awaiting approval. Run `etsy-engine run` first.")
        return
    n_pdf = sum(1 for p in pending if p["format"] == "pdf")
    n_canva = sum(1 for p in pending if p["format"] == "canva")
    click.echo(f"{len(pending)} product(s) awaiting approval — {n_pdf} PDF, {n_canva} Canva:\n")
    for p in pending:
        tag = "PDF " if p["format"] == "pdf" else "CANVA"
        click.echo(f"  #{p['id']:>4} [{tag}] {p['bundle_type']}  ({p['pieces']} pcs)  "
                   f"<- {p['term'][:42]}")
        for g in (p.get("gap_analysis") or [])[:3]:
            click.echo(f"          gap: {g}")
    click.echo("\nApprove:  etsy-engine approve --id <N> [--id <M> ...]   |   etsy-engine approve --all")


@cli.command()
@click.option("--id", "ids", multiple=True, type=int, help="Product id(s) to approve; repeatable")
@click.option("--all", "approve_all", is_flag=True, default=False, help="Approve every pending product")
def approve(ids: tuple[int, ...], approve_all: bool) -> None:
    """Approve routed products and START producing them.

    PDF -> assets + mockups + SEO + Etsy DRAFT (still through the EV gate). Canva -> a design set you
    then finish with Magic Layers + `canva publish`. Only the products you approve are produced.
    """
    from . import db, pipeline

    db.init_db()
    pending = {p["id"]: p for p in db.pending_approval()}
    if approve_all:
        chosen = list(pending)
    else:
        chosen = [i for i in ids if i in pending]
        for missing in [i for i in ids if i not in pending]:
            click.echo(f"  #{missing} is not awaiting approval — skipping")
    if not chosen:
        click.echo("Nothing to approve. See `etsy-engine review`.")
        return
    res = pipeline.produce_approved(chosen)
    click.echo(f"\nApproved {len(chosen)}: {len(res['pdf_drafted'])} PDF drafted, "
               f"{len(res['canva_prepared'])} Canva design-set(s) prepared, "
               f"{len(res['blocked'])} EV-blocked, {len(res['skipped'])} skipped.")
    if res["canva_prepared"]:
        click.echo("Canva next: import each set + run Magic Layers, then `canva publish`.")


@cli.command()
@click.argument("term")
@click.option("--max-pages", default=4, show_default=True,
              help="Cap the bundle size for a cheap first run (0 = full plan)")
@click.option("--variations", default=1, show_default=True,
              help="Images per page; the QC picks the best (more = better, costlier)")
def demo(term: str, max_pages: int, variations: int) -> None:
    """Make ONE finished product for a niche — no Etsy account needed.

    Example: etsy-engine demo "teacher appreciation week"
    """
    r = pipeline.demo(term, max_pages=max_pages, variations=variations)
    console.print(f"[green]Product #{r['product_id']}:[/] {r['title']}")
    console.print(f"Files: {r['dir']}")
    console.print("To sell it: connect Etsy (docs/SETUP.md) and run "
                  f"`etsy-engine publish --product-id {r['product_id']}`")


@cli.command()
def credits() -> None:
    """Show the Raywake credit balance + local image spend ledger."""
    from .generate.raywake import RaywakeClient, total_spend

    console.print("Raywake wallet:", RaywakeClient().credits())
    ws = total_spend()
    console.print(f"Spent locally: {ws['credits']} credits over {ws['images']} image(s) "
                  f"(ledger: data/raywake_spend.jsonl)")


@cli.group()
def canva() -> None:
    """Canva editable-template line (image model -> Magic Layers -> editable). Additive."""


@canva.command("prepare")
@click.argument("niche")
@click.option("--aesthetic", default=None, help="botanical/editorial/modern_minimal/playful/retro")
@click.option("--out", default=None, help="Output dir (default output/canva)")
def canva_prepare(niche: str, aesthetic: str | None, out: str | None) -> None:
    """Generate a multi-page design SET + delivery + honest listing for a niche.

    Then (an agent session with the Canva MCP): import the set to Canva, run Magic Layers on each page, Share ->
    Template link. Finally: `etsy-engine canva publish --dir <out> --link <link>`.
    """
    from .canva import produce

    r = produce.prepare(niche, aesthetic=aesthetic, out_dir=out)
    console.print(f"[green]Prepared {len(r['pages'])} page(s)[/] in {out or 'output/canva'}")
    console.print(f"  manifest: {r['manifest']}")
    console.print(f"  set html (import to Canva): {r.get('set_html')}")
    console.print("[yellow]Next (human-in-the-loop):[/] import the set to Canva in an agent "
                  "session, run Magic Layers on each page, Share -> Template link, then run "
                  "`etsy-engine canva publish --dir <out> --link <template_link>`.")


@canva.command("publish")
@click.option("--dir", "out_dir", required=True, help="The prepare output dir (has manifest.json)")
@click.option("--link", required=True, help="Canva template link (after Magic Layers + Share)")
@click.option("--price", default=None, type=float, help="Override price (default: market-driven from manifest)")
def canva_publish(out_dir: str, link: str, price: float | None) -> None:
    """Build i2i mockups + the delivery PDF (with the link) and create the Etsy DRAFT."""
    import json
    from pathlib import Path

    from .canva import delivery, mockups, publish as cpub
    from .generate import hosting

    m = json.loads((Path(out_dir) / "manifest.json").read_text())
    if not m.get("canva_final"):        # mockups must show the owner's FINAL Canva design, not pre-edit renders
        console.print("[yellow]⚠  Mockups will use PRE-EDIT page renders. Export the owner's final "
                      "Canva design and run `canva refresh --dir <dir> --url <page-urls...>` first "
                      "so listing images match what the buyer downloads.[/]")
    price = price if price is not None else m.get("price")   # market-driven price from prepare
    urls = [hosting.upload(p) for p in m["image_paths"] if Path(p).exists()]  # model-readable refs
    imgs = mockups.build_all(urls, m["image_paths"], m["product_kind"], out_dir, m["aesthetic"],
                             product_id=m.get("product_id"), style_brief=m.get("style_brief"))
    dp = delivery.build_pdf(m["listing"]["title"], link=link, out_dir=out_dir, aesthetic=m["aesthetic"])
    r = cpub.create_draft(m["listing"], imgs, dp, template_link=link, price=price,
                          product_id=m.get("product_id"),
                          page_images=[p for p in m["image_paths"] if Path(p).exists()])
    console.print(f"[green]Etsy DRAFT:[/] {r['url']}")
    console.print("[yellow]Owner:[/] tick 'made with an AI generator' in the draft, then publish.")


@canva.command("refresh")
@click.option("--dir", "out_dir", required=True, help="The prepare output dir (has manifest.json)")
@click.option("--url", "urls", multiple=True, required=True,
              help="Canva-exported page PNG URLs, in page order (agent runs export-design first)")
def canva_refresh(out_dir: str, urls: tuple[str, ...]) -> None:
    """Refresh the local page renders with the owner's FINAL Canva export (so mockups match)."""
    from .canva import publish as cpub
    paths = cpub.refresh_design_images(out_dir, list(urls))
    console.print(f"[green]Refreshed {len(paths)} page(s) from the final Canva design.[/] "
                  "Mockups + listing will now use the owner's edited version.")


@canva.command("scan")
@click.option("--limit", default=200, help="How many top trends to scan")
@click.option("--produce", default=0, type=int, help="Auto-prepare the top N hits into design sets")
def canva_scan(limit: int, produce: int) -> None:
    """Auto-detect Canva-suitable trends among the current top opportunities (auto-routing).

    Reads the same ranked trends the PDF architect uses and flags the personalizable ones
    (signs, invitations, weddings, host/guest, classroom, ...). `--produce N` prepares the
    top N into design sets, ready for the Canva import + the owner's Magic Layers.
    """
    import re as _re

    from .canva import detect, produce as cprod
    from .config import OUTPUT_DIR

    hits = detect.scan(limit=limit)
    if not hits:
        console.print("[yellow]No Canva-suitable trends in the current top opportunities. "
                      "Run the trend stages first (collect/score/validate).[/]")
        return
    table = Table(title=f"Canva-suitable trends ({len(hits)})")
    table.add_column("score", justify="right")
    table.add_column("kind")
    table.add_column("term")
    for h in hits[:30]:
        table.add_row(str(h["score"]), h["kind"], h["term"])
    console.print(table)
    for h in hits[:produce]:
        slug = _re.sub(r"[^a-z0-9]+", "-", h["term"].lower()).strip("-")[:40] or "set"
        out = OUTPUT_DIR / "canva" / slug
        r = cprod.prepare(h["term"], out_dir=out)
        console.print(f"[green]prepared[/] '{h['term']}' -> {out} ({len(r['pages'])} pages)")
    if produce:
        console.print("[yellow]Next (human-in-the-loop):[/] import each set to Canva in an agent "
                      "session, run Magic Layers, then `canva publish --dir <out> --link <link>`.")


@canva.command("queue")
def canva_queue() -> None:
    """Show Canva-routed trends waiting to be produced (from the pipeline's per-trend routing)."""
    from .canva import produce as cprod

    pending = cprod.queue_pending()
    if not pending:
        console.print("[yellow]Canva queue empty.[/] Run `architect`/`run` to route trends per format.")
        return
    table = Table(title=f"Canva queue ({len(pending)} routed, awaiting production)")
    table.add_column("product", justify="right")
    table.add_column("term")
    for r in pending:
        table.add_row(str(r.get("product_id", "")), r["term"])
    console.print(table)


@canva.command("produce-queue")
@click.option("--limit", default=5, type=int, help="How many queued trends to prepare")
def canva_produce_queue(limit: int) -> None:
    """Prepare design sets for queued Canva trends (then import + Magic Layers + publish)."""
    import re as _re

    from .canva import produce as cprod
    from .config import OUTPUT_DIR

    pending = cprod.queue_pending()[:limit]
    if not pending:
        console.print("[yellow]Canva queue empty.[/]")
        return
    for r in pending:
        slug = _re.sub(r"[^a-z0-9]+", "-", r["term"].lower()).strip("-")[:40] or "set"
        out = OUTPUT_DIR / "canva" / slug
        # fills the routed product in place + flips status 'routed'->'planned' (drains the queue)
        res = cprod.prepare(r["term"], out_dir=out, product_id=r.get("product_id"))
        console.print(f"[green]prepared[/] '{r['term']}' -> {out} ({len(res['pages'])} pages)")
    console.print("[yellow]Next:[/] import each to Canva (agent session with the Canva MCP), Magic Layers, then "
                  "`canva publish --dir <out> --link <link>`.")


@cli.command(name="etsy-auth")
def etsy_auth() -> None:
    """Authorize the app with Etsy (OAuth2). Opens a browser; tokens saved to disk."""
    from .publish import etsy_client as ec

    ec.authorize()
    console.print("[green]Authorized.[/green] Tokens saved. Verifying...")
    console.print(ec.me())


@cli.command(name="etsy-shop")
def etsy_shop() -> None:
    """Show your Etsy user + shop id (set ETSY_SHOP_ID from this)."""
    from .publish import etsy_client as ec

    console.print(ec.me())


@cli.command(name="etsy-shop-profile")
@click.option("--apply", "apply_changes", is_flag=True, default=False,
              help="Apply the canonical title and buyer messages; default is preview")
def etsy_shop_profile(apply_changes: bool) -> None:
    """Preview or update Etsy storefront title and buyer-facing messages."""
    from .publish.shop_profile import update_shop_profile

    result = update_shop_profile(dry_run=not apply_changes)
    if not result["changes"]:
        console.print("[green]Shop profile already matches the canonical copy.[/green]")
        return
    for field, change in result["changes"].items():
        console.print(f"[bold]{field}[/bold]\n  from: {change['from'] or '(empty)'}\n"
                      f"  to:   {change['to']}")
    if not apply_changes:
        console.print("\n[dim]Apply with: etsy-engine etsy-shop-profile --apply[/dim]")
    else:
        console.print("[green]Shop profile updated.[/green]")


@cli.command(name="etsy-taxonomy")
@click.argument("query")
def etsy_taxonomy(query: str) -> None:
    """Search Etsy seller taxonomy for a category id (set ETSY_TAXONOMY_ID)."""
    from .publish.publisher import search_taxonomy

    for hit in search_taxonomy(query)[:25]:
        console.print(f"  {hit['id']:>8}  {hit['path']}")


@cli.command()
@click.option("--product-id", type=int, required=True, help="Product id to publish")
def publish(product_id: int) -> None:
    """Stage 7 (Faz 4) — create a DRAFT Etsy listing (human publishes)."""
    from .publish.publisher import publish_product

    publish_product(product_id)


@cli.command(name="product-report")
@click.option("--product-id", type=int, required=True)
def product_report(product_id: int) -> None:
    """Write the decision-provenance report to output/<id>/PRODUCT_REPORT.md."""
    from .reporting import write_product_report

    write_product_report(product_id)


@cli.command()
def metrics() -> None:
    """Stage 8 (Faz 5) — snapshot views/favorites/sales from Etsy."""
    from .learning.metrics import pull_metrics

    pull_metrics()


@cli.command()
def smoke() -> None:
    """Live-API smoke test: create ONE throwaway Etsy draft and delete it, to verify the publish path
    (auth, taxonomy, POST, DELETE) works end to end. Prints the created-then-deleted draft id and
    records the outcome in the run_log. Never touches real listings."""
    from . import db
    from .publish.publisher import smoke_draft

    db.init_db()
    try:
        lid = smoke_draft()
    except Exception as e:
        db.log_run("smoke", "failed", str(e)[:200])
        click.echo(f"smoke failed: {e}")
        raise SystemExit(1)
    db.log_run("smoke", "ok", f"created+deleted {lid}")
    click.echo(f"smoke ok: created then deleted draft {lid}")


@cli.command()
@click.option("--min-views", default=20, type=int, help="Views floor; below this = unproven")
@click.option("--min-favorites", default=2, type=int, help="Favorites floor; below this = unproven")
@click.option("--min-age-days", default=30, type=int, help="Only consider listings at least this old")
@click.option("--dry-run", is_flag=True, default=False,
              help="List + count only; do NOT set the deactivation flag")
def prune(min_views: int, min_favorites: int, min_age_days: int, dry_run: bool) -> None:
    """List active listings STILL unproven after N days (< min-views AND < min-favorites), mark them
    for deactivation, and print the count.

    Marking is a DB flag only — this NEVER deactivates anything on Etsy; a human acts on the flag.
    The age floor (default 30d) is deliberate: the shop's 'dead' listings were newborns still ramping
    (§B7), so nothing younger is ever flagged.
    """
    from . import db
    from .learning import prune as pr

    db.init_db()   # idempotent; ensures the marked_for_deactivation column exists on older DBs
    listings = pr.find_prunable(min_views, min_favorites, min_age_days)
    for r in listings:
        click.echo(f"  #{r['product_id']} listing {r['etsy_listing_id']} "
                   f"[{r['age_days']:.0f}d {r['views']}v/{r['favorites']}f] {(r['title'] or '')[:52]}")
    n = len(listings) if dry_run else pr.mark_for_deactivation(listings)
    verb = "would mark" if dry_run else "marked"
    click.echo(f"{n} active listing(s) {verb} for deactivation "
               f"(unproven >={min_age_days}d: <{min_views} views & <{min_favorites} favorites)")


@cli.command()
@click.option("--dry-run", is_flag=True, default=False, help="Show what would renew, change nothing")
@click.option("--report", "report_only", is_flag=True, default=False,
              help="List listings + seasonal keep-alive flags, no API calls")
def renew(dry_run: bool, report_only: bool) -> None:
    """Keep-alive: ensure evergreen + seasonal listings never expire (auto-renew).

    Seasonal listings accrue search/sales history all year; letting them lapse
    resets that. Run periodically (and before Q4 peaks) so nothing drops out.
    """
    from . import pipeline

    pipeline.renew_listings(dry_run=dry_run, report_only=report_only)


@cli.command()
@click.option("--dry-run", is_flag=True, default=False, help="Show new prices, change nothing")
def reprice(dry_run: bool) -> None:
    """Re-price print listings to the niche median (uses the current price band)."""
    from . import pipeline

    pipeline.reprice_prints(dry_run=dry_run)


@cli.command(name="rank-track")
@click.option("--product-id", type=int, default=None, help="Track one product; default all")
@click.option("--keyword", default=None, help="Override target keyword")
def rank_track(product_id: int | None, keyword: str | None) -> None:
    """Snapshot where our live listings rank for target keywords."""
    from .learning import rank_tracker as rt

    if product_id:
        el = db.get_etsy_listing(product_id)
        if not el:
            console.print(f"[red]product {product_id} has no Etsy listing[/red]")
            return
        rt.track_listing(product_id, el["etsy_listing_id"], keyword)
    else:
        rt.track_all()


@cli.command(name="rank-report")
@click.option("--limit", default=50, type=int, help="Max rows to show")
def rank_report(limit: int) -> None:
    """Show latest rank snapshot per listing/keyword with trend arrow."""

    rows = db.latest_ranks()[:limit]
    table = Table(title="Latest Etsy Search Ranks")
    table.add_column("product")
    table.add_column("listing_id")
    table.add_column("keyword")
    table.add_column("rank")
    table.add_column("trend")
    table.add_column("results")
    for r in rows:
        lid = r["etsy_listing_id"]
        kw = r["keyword"]
        prev = db.previous_rank_snapshot(lid, kw)
        rank = r.get("rank")
        rank_str = f"#{rank}" if rank else ">100"
        trend = "-"
        if prev:
            pr = prev.get("rank")
            if rank and pr:
                if rank < pr:
                    trend = f"↑{pr - rank}"
                elif rank > pr:
                    trend = f"↓{rank - pr}"
                else:
                    trend = "→"
            elif rank and not pr:
                trend = "↑found"
            elif not rank and pr:
                trend = "↓lost"
        table.add_row(
            r.get("bundle_type", "")[:34],
            str(lid),
            kw[:30],
            rank_str,
            trend,
            str(r.get("total_results", 0)),
        )
    console.print(table)


@cli.command()
@click.option("--dry-run", is_flag=True, default=True,
              help="Show suggestions without applying (default True)")
@click.option("--product-id", type=int, default=None, help="Optimize one product")
@click.option("--keyword", default=None, help="Override target keyword")
@click.option("--min-rank", default=20, type=int, help="Rank worse than this = buried")
@click.option("--min-demand", default=0.1, type=float, help="Minimum demand_score")
def optimize(dry_run: bool, product_id: int | None, keyword: str | None,
             min_rank: int, min_demand: float) -> None:
    """Find buried live listings and suggest (or apply) SEO rewrites."""
    from .seo import optimizer as opt

    if product_id:
        opt.optimize_product(product_id, dry_run=dry_run, keyword=keyword)
        return

    candidates = opt.suggest(min_rank=min_rank, min_demand=min_demand)
    if not candidates:
        console.print("[green]No buried listings match the criteria.[/green]")
        return

    table = Table(title=f"Buried Listings (rank > {min_rank}, demand ≥ {min_demand})")
    table.add_column("product_id")
    table.add_column("listing_id")
    table.add_column("keyword")
    table.add_column("rank")
    table.add_column("demand")
    table.add_column("daily views")
    for c in candidates:
        rank = c.get("rank")
        table.add_row(
            str(c["product_id"]),
            str(c["etsy_listing_id"]),
            c["keyword"][:30],
            f"#{rank}" if rank else ">100",
            f"{c['demand_score']:.2f}",
            str(c.get("avg_daily_views", 0)),
        )
    console.print(table)

    if dry_run:
        console.print("\n[dim]Run with --no-dry-run or etsy-engine optimize-apply --product-id N[/dim]")
        return

    applied = 0
    for c in candidates:
        try:
            opt.optimize_product(c["product_id"], dry_run=False, keyword=c["keyword"])
            applied += 1
        except Exception as e:
            console.print(f"[red]optimize {c['product_id']} failed: {e}[/red]")
    console.print(f"[green]Applied optimizations to {applied}/{len(candidates)} listings.[/green]")


@cli.command(name="optimize-apply")
@click.option("--product-id", type=int, required=True, help="Product id to optimize")
@click.option("--keyword", default=None, help="Override target keyword")
def optimize_apply(product_id: int, keyword: str | None) -> None:
    """Apply a freshly generated SEO rewrite to a live Etsy listing."""
    from .seo import optimizer as opt

    opt.optimize_product(product_id, dry_run=False, keyword=keyword)


@cli.command()
def learn() -> None:
    """Stage 9 (Faz 5) — analyze performance and auto-tune scoring weights."""
    from .learning.feedback import learn as run_learn

    run_learn()


@cli.command()
@click.option("-n", default=1, type=int, help="How many products to produce")
@click.option("--lane", type=click.Choice(["evergreen", "viral"]), default=None,
              help="Force starting lane (default: opposite of last product)")
def produce(n: int, lane: str | None) -> None:
    """Produce N products, alternating EVERGREEN/VIRAL lanes (e.g. 6 -> 3+3)."""
    pipeline.produce(n, lane)


@cli.command()
def report() -> None:
    """Show top opportunities and designed products."""
    db.init_db()

    opps = db.top_opportunities(limit=settings.funnel_opportunities)
    t = Table(title="Top Opportunities (IP-safe, market-ranked)")
    for col in ("term", "src", "comp", "viral", "buy", "ip", "etsy#", "adj"):
        t.add_column(col)
    for o in opps:
        listings = o.get("listing_count")
        adj = o.get("adjusted_score")
        t.add_row(
            o["term"][:42], o["source"],
            f"{o['composite']:.2f}", f"{o['virality']:.2f}",
            f"{o['purchase_intent']:.2f}", f"{o['ip_risk']:.2f}",
            str(listings) if listings is not None else "-",
            f"{adj:.2f}" if adj else "-",
        )
    console.print(t)

    for p in db.products_with_items():
        console.print(f"\n[bold]{p['bundle_type']}[/bold] — {p['title_concept']}")
        console.print(f"  status: {p['status']}")
        assets = {a["bundle_item_id"]: a for a in db.assets_for_product(p["id"])}
        for it in p["items"]:
            a = assets.get(it["id"])
            if a:
                console.print(
                    f"   • {it['name']} [dim]({it['asset_type']})[/dim] "
                    f"→ qc={a['qc_status']} {a['qc_score']:.2f} [dim]{a['file_path']}[/dim]"
                )
            else:
                console.print(f"   • {it['name']} [dim]({it['asset_type']})[/dim]")

        mocks = db.mockups_for_product(p["id"])
        if mocks:
            console.print(f"  [cyan]mockups[/cyan]: {', '.join(m['kind'] for m in mocks)}")
        listing = db.get_listing(p["id"])
        if listing:
            import json as _json
            tags = _json.loads(listing["tags"] or "[]")
            console.print(f"  [green]SEO[/green]: {listing['title']}")
            console.print(f"       tags: {', '.join(tags)}")


@cli.command(name="keyword-track")
def keyword_track() -> None:
    """Snapshot tracked keywords' top-listing counters (run daily)."""
    from . import db as _db
    _db.init_db()
    from .learning.keyword_pulse import snapshot
    snapshot()


@cli.command(name="keyword-velocity")
def keyword_velocity() -> None:
    """TRUE current demand velocity per tracked keyword (needs 2+ snapshots)."""
    from .learning.keyword_pulse import report
    report()


@cli.command(name="pinterest-auth")
def pinterest_auth() -> None:
    """One-time Pinterest OAuth (needs PINTEREST_APP_ID/SECRET in .env)."""
    from .marketing import pinterest
    pinterest.authorize()
    console.print("[green]Pinterest authenticated.[/green]")


@cli.command(name="pinterest-boards")
def pinterest_boards() -> None:
    """List Pinterest boards (find the id for PINTEREST_BOARD_ID)."""
    from .marketing import pinterest
    for b in pinterest.list_boards():
        console.print(f"{b.get('id')}  {b.get('name')}")


@cli.command(name="pin-queue")
@click.option("--product-id", required=True, type=int)
@click.option("--board", default=None, help="Board id (default: PINTEREST_BOARD_ID)")
@click.option("--spacing-hours", default=6.0, type=float,
              help="Hours between this product's pins")
def pin_queue(product_id: int, board: str | None, spacing_hours: float) -> None:
    """Queue a product's mockups as time-spread Pinterest pins."""
    from .marketing import pinterest
    board = board or settings.pinterest_board_id
    if not board:
        raise click.UsageError("no board: pass --board or set PINTEREST_BOARD_ID")
    pinterest.queue_product(product_id, board, spacing_hours=spacing_hours)


@cli.command(name="pin-spread")
@click.option("--limit", default=10, type=int, help="Max pins to publish this run")
def pin_spread(limit: int) -> None:
    """Publish every queued pin whose time has come (run from the daily job)."""
    from .marketing import pinterest
    pinterest.publish_due(limit=limit)


if __name__ == "__main__":
    cli()
