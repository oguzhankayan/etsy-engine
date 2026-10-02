"""Per-listing + shop P&L from the live metrics snapshot and the cost ledgers.

Joins the latest Etsy metrics (views/favorites/sales, and price once
`etsy-engine metrics` has captured it) with the production-cost ledgers
(Anthropic LLM `data/anthropic_spend.jsonl` + Raywake image `data/raywake_spend.jsonl`)
to produce a realized, to-date P&L and a per-listing margin table.

Usage:
    .venv/bin/python scripts/pnl_report.py                # print the report
    .venv/bin/python scripts/pnl_report.py --ads 20       # assume $20/mo onsite ads
    .venv/bin/python scripts/pnl_report.py --no-live      # skip live Etsy price pulls
    .venv/bin/python scripts/pnl_report.py --usd-per-credit 0.01   # price Raywake credits
    .venv/bin/python scripts/pnl_report.py --write        # append a dated section to
                                                          # docs/profitability-report.md

Prices: uses the price captured in the metrics snapshot when present; otherwise
best-effort pulls the current Etsy price per listing (falls back to the configured
default when the Etsy API is unavailable). Re-run `etsy-engine metrics` first for
the most accurate snapshot. Treat the Etsy Stats/Marketing tab as final truth.
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from rich.console import Console
from rich.table import Table

from etsy_engine import db, llm
from etsy_engine.config import settings
from etsy_engine.generate import raywake

# Etsy fee structure for a US digital shop (mirrors docs/profitability-report.md).
TRANSACTION_FEE = 0.065          # 6.5% of item price
PAYMENT_PCT = 0.03               # 3% ...
PAYMENT_FLAT = 0.25              # ... + $0.25 per order
LISTING_FEE = 0.20               # per listing per 4-month term
TERMS_PER_YEAR = 3
OFFSITE_ADS_PCT = 0.15           # mandatory <$10k/yr, worst case (all attributed)

console = Console()


def _live_prices(rows: list[dict]) -> dict[int, float]:
    """Best-effort: pull the current Etsy price for listings whose metrics row has
    no captured price. Returns {etsy_listing_id: price}; empty on any failure."""
    need = [r for r in rows if not r.get("price")]
    if not need:
        return {}
    prices: dict[int, float] = {}
    try:
        from etsy_engine.publish import etsy_client as ec
        from etsy_engine.scoring.etsy_market import _price_usd
    except Exception:
        return {}
    for r in need:
        lid = r["etsy_listing_id"]
        try:
            listing = ec.request("GET", f"/listings/{lid}")
            p = _price_usd(listing.get("price"))
            if p:
                prices[lid] = p
        except Exception:
            continue
    return prices


def main() -> None:
    ap = argparse.ArgumentParser(description="Shop + per-listing P&L")
    ap.add_argument("--ads", type=float, default=0.0,
                    help="Assumed onsite Etsy Ads spend per month (USD)")
    ap.add_argument("--no-live", action="store_true",
                    help="Do not pull live Etsy prices for rows missing a price")
    ap.add_argument("--usd-per-credit", type=float, default=0.0,
                    help="USD value of one Raywake credit (for the production-cost line)")
    ap.add_argument("--write", action="store_true",
                    help="Append a dated section to docs/profitability-report.md")
    args = ap.parse_args()

    rows = db.latest_metrics()
    if not rows:
        console.print("[yellow]No metrics yet. Run: .venv/bin/etsy-engine metrics[/]")
        return

    live = {} if args.no_live else _live_prices(rows)
    default_price = settings.etsy_default_price
    fallback_used = 0
    for r in rows:
        p = r.get("price") or live.get(r["etsy_listing_id"]) or 0.0
        if not p:
            p = default_price
            fallback_used += 1
        r["_price"] = float(p)
        r["_revenue"] = r["_price"] * int(r.get("sales") or 0)

    listing_count = len(rows)
    total_views = sum(int(r.get("views") or 0) for r in rows)
    total_favs = sum(int(r.get("favorites") or 0) for r in rows)
    total_sales = sum(int(r.get("sales") or 0) for r in rows)
    total_revenue = sum(r["_revenue"] for r in rows)
    avg_price = (sum(r["_price"] for r in rows) / listing_count) if listing_count else 0.0
    conv = (total_sales / total_views * 100) if total_views else 0.0

    # Realized, to-date costs on actual sales.
    transaction = total_revenue * TRANSACTION_FEE
    payment = total_revenue * PAYMENT_PCT + PAYMENT_FLAT * total_sales
    listing_fees_yr = listing_count * LISTING_FEE * TERMS_PER_YEAR
    offsite_worst = total_revenue * OFFSITE_ADS_PCT
    ads_yr = args.ads * 12.0

    anthropic_spend = llm.total_spend()
    image_spend = raywake.total_spend()
    image_spend["total_usd"] = image_spend["credits"] * args.usd_per_credit
    production = anthropic_spend["total_usd"] + image_spend["total_usd"]

    net_todate = total_revenue - transaction - payment - production
    net_todate_worst = net_todate - offsite_worst

    # ---- Shop snapshot ----
    snap = Table(title="Shop snapshot", show_header=False, box=None)
    snap.add_row("Active listings", f"{listing_count}")
    snap.add_row("Avg price", f"${avg_price:.2f}")
    snap.add_row("Views / Favorites / Sales", f"{total_views} / {total_favs} / {total_sales}")
    snap.add_row("Conversion (views->sales)", f"{conv:.2f}%")
    snap.add_row("Revenue (realized)", f"${total_revenue:.2f}")
    console.print(snap)

    # ---- Cost ledgers ----
    led = Table(title="Production cost ledgers")
    led.add_column("Source"); led.add_column("USD", justify="right"); led.add_column("Detail")
    led.add_row("Anthropic (LLM)", f"${anthropic_spend['total_usd']:.4f}",
                f"{anthropic_spend['calls']} calls, "
                f"{anthropic_spend['input_tokens']}in/{anthropic_spend['output_tokens']}out tok")
    led.add_row("Raywake (images)", f"${image_spend['total_usd']:.4f}",
                f"{image_spend['images']} images, {image_spend['credits']} credits"
                + ("" if args.usd_per_credit else " (pass --usd-per-credit to price them)"))
    console.print(led)

    # ---- P&L ----
    pnl = Table(title="Realized P&L (to date, on actual sales)")
    pnl.add_column("Line"); pnl.add_column("USD", justify="right"); pnl.add_column("Note")
    pnl.add_row("Revenue", f"+{total_revenue:.2f}", f"{total_sales} sales @ avg ${avg_price:.2f}")
    pnl.add_row("Transaction fee 6.5%", f"-{transaction:.2f}", "")
    pnl.add_row("Payment 3% + $0.25/sale", f"-{payment:.2f}", "")
    pnl.add_row("Production (Anthropic+Raywake)", f"-{production:.4f}", "from ledgers")
    pnl.add_row("NET to date (ex ads/offsite)", f"{net_todate:+.2f}", "", style="bold")
    pnl.add_row("Offsite Ads 15% (worst)", f"-{offsite_worst:.2f}", "if all attributed")
    pnl.add_row("NET to date (worst)", f"{net_todate_worst:+.2f}", "", style="bold")
    console.print(pnl)

    # ---- Annualized fixed/controllable lines ----
    ann = Table(title="Annualized fixed / controllable lines")
    ann.add_column("Line"); ann.add_column("USD/yr", justify="right"); ann.add_column("Note")
    ann.add_row("Listing fees", f"-{listing_fees_yr:.2f}",
                f"{listing_count} x $0.20 x {TERMS_PER_YEAR} terms")
    if ads_yr:
        ann.add_row("Onsite Etsy Ads", f"-{ads_yr:.2f}", f"${args.ads:.0f}/mo assumed")
    console.print(ann)

    # ---- Per-listing (top by sales, then views) ----
    tbl = Table(title="Per-listing (top 20 by sales, then views)")
    for c, r_align in (("Listing", "left"), ("Archetype", "left"), ("Price", "right"),
                       ("Views", "right"), ("Fav", "right"), ("Sales", "right"),
                       ("Revenue", "right")):
        tbl.add_column(c, justify=r_align)
    top = sorted(rows, key=lambda r: (int(r.get("sales") or 0), int(r.get("views") or 0)),
                 reverse=True)[:20]
    for r in top:
        name = (r.get("bundle_type") or str(r.get("etsy_listing_id")))[:34]
        tbl.add_row(name, str(r.get("archetype") or ""), f"${r['_price']:.2f}",
                    str(r.get("views") or 0), str(r.get("favorites") or 0),
                    str(r.get("sales") or 0), f"${r['_revenue']:.2f}")
    console.print(tbl)

    if fallback_used:
        console.print(f"[yellow]Note: {fallback_used}/{listing_count} listings used the "
                      f"${default_price:.2f} default price (no metrics/live price). "
                      f"Run `etsy-engine metrics` to capture live prices.[/]")

    if args.write:
        _append_report(date.today().isoformat(), listing_count, avg_price, total_views,
                       total_favs, total_sales, conv, total_revenue, net_todate,
                       net_todate_worst, anthropic_spend, image_spend)


def _append_report(day, listing_count, avg_price, views, favs, sales, conv, revenue,
                   net, net_worst, anthropic_spend, image_spend):
    p = Path(__file__).resolve().parents[1] / "docs" / "profitability-report.md"
    section = (
        f"\n\n## P&L refresh — {day} (scripts/pnl_report.py)\n\n"
        f"- {listing_count} listings, avg ${avg_price:.2f}; "
        f"{views} views / {favs} favorites / {sales} sales; conversion {conv:.2f}%.\n"
        f"- Realized revenue ${revenue:.2f}. NET to date ex ads/offsite ${net:+.2f}; "
        f"worst-case (offsite 15%) ${net_worst:+.2f}.\n"
        f"- Production ledgers: Anthropic ${anthropic_spend['total_usd']:.4f} "
        f"({anthropic_spend['calls']} calls), Raywake {image_spend['credits']} credits "
        f"({image_spend['images']} images).\n"
    )
    with p.open("a") as fh:
        fh.write(section)
    console.print(f"[green]Appended a dated section to {p}[/]")


if __name__ == "__main__":
    main()
