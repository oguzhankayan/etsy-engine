"""Full-shop consistency audit — the four defect classes the owner caught by eye.

For every product with an Etsy listing, vision-inspects a sample of its REAL
deliverable pages (and the hero mockup for prints) and flags:
  B. advertisement/infographic pages instead of the usable artifact
  C. pre-filled write-in fields ('$0.00', sample values, [Name] placeholders)
  D. cut-out/fold templates whose dieline geometry cannot work
  A. (prints) hero mockup depicting the wrong orientation vs the actual file
  E. promise-vs-delivery: title/desc promises ('set of 3', 'trio', 'N sizes',
     'N pages') vs the actual delivered file/page count (deterministic).

Output: reports/audit-YYYYMMDD.md + .json, worst first. ~1-2 vision calls per
product (downscaled), so a full ~100-listing sweep costs on the order of $1-2.

Usage: .venv/bin/python scripts/audit_listings.py [--limit N]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from etsy_engine import db  # noqa: E402
from etsy_engine.config import ROOT  # noqa: E402
from etsy_engine.generate.qc import _prep_for_qc  # noqa: E402
from etsy_engine.llm import vision_json  # noqa: E402

REPORT_DIR = ROOT / "reports"

PAGE_SYSTEM = """You audit Etsy printable products for defects buyers complain
about. You see ONE page of the actual delivered file, plus the listing title.
Respond with JSON only:
{"is_advertisement": true/false,  // page is a poster/infographic ABOUT the
     // product (size charts, hanging diagrams, feature lists, marketing copy)
     // instead of the usable artifact itself
 "prefilled_fields": true/false,  // write-in fields contain printed values
     // ('$0.00', sample names/dates) or bracket placeholders ('[Name]','[###]')
 "broken_template": true/false,   // it's a cut-out/fold template whose
     // geometry could not actually be assembled (asymmetric dieline, missing
     // or misplaced tabs, front/back that can't align)
 "unusable_scale": true/false,    // elements are far too small to use at
     // printed size (e.g. 12 bingo boards or 40 cards crammed on one sheet)
 "severity": "none"|"minor"|"major",  // how badly would a buyer feel misled
 "notes": "one short sentence naming the specific problem, or 'ok'"}"""

HERO_SYSTEM = """You audit an Etsy HERO listing image for honesty. The actual
delivered artwork file is {orient} (aspect {w}:{h}). Respond with JSON only:
{{"depicted_orientation": "portrait"|"landscape"|"square"|"multiple",
  "orientation_mismatch": true/false, // frame(s) shown contradict {orient}
  "notes": "one short sentence"}}"""

PROMISE_RE = re.compile(
    r"\b(?:set of (\d+)|(\d+)\s*(?:sizes|prints|posters)|trio|gallery wall)\b",
    re.IGNORECASE)


def promised_count(text: str) -> int | None:
    best = None
    for m in PROMISE_RE.finditer(text or ""):
        digits = m.group(1) or m.group(2)
        if digits:
            best = max(best or 0, int(digits))
        elif m.group(0).lower() == "trio":
            best = max(best or 0, 3)
        # "gallery wall" alone promises a set but no count — ignore here;
        # the vision pass judges the actual pages anyway.
    return best


def audit_product(p: dict) -> dict | None:
    pid = p["id"]
    assets = [a for a in db.assets_for_product(pid) if Path(a["file_path"]).exists()]
    if not assets:
        return None
    listing = db.get_listing(pid) or {}
    el = db.get_etsy_listing(pid) or {}
    title = listing.get("title") or p["bundle_type"]
    findings: list[str] = []
    severity = "none"

    # E. promise vs delivery (deterministic)
    promised = promised_count(f"{title} {listing.get('description','')[:400]}")
    if promised and promised > 1 and len(assets) < promised and len(assets) <= 2:
        findings.append(f"E promise-mismatch: copy promises {promised}, "
                        f"delivers {len(assets)} file(s)")
        severity = "major"

    # B/C/D via vision on up to 2 sample pages
    for a in assets[:2]:
        try:
            img, _ = _prep_for_qc(Path(a["file_path"]).read_bytes())
            r = vision_json(PAGE_SYSTEM, f"Listing title: {title}", img)
        except Exception as e:
            findings.append(f"vision-error: {e}")
            continue
        page = Path(a["file_path"]).name
        if r.get("is_advertisement"):
            findings.append(f"B ad-not-artifact [{page}]: {r.get('notes','')}")
        if r.get("prefilled_fields"):
            findings.append(f"C prefilled-fields [{page}]: {r.get('notes','')}")
        if r.get("broken_template"):
            findings.append(f"D broken-template [{page}]: {r.get('notes','')}")
        if r.get("unusable_scale"):
            findings.append(f"F unusable-scale [{page}]: {r.get('notes','')}")
        sev = r.get("severity", "none")
        order = {"none": 0, "minor": 1, "major": 2}
        if order.get(sev, 0) > order.get(severity, 0):
            severity = sev

    # A. hero orientation for prints
    pintel = db.get_product_intel(pid) or {}
    if pintel.get("archetype") == "print":
        hero = next((m for m in db.mockups_for_product(pid)
                     if m["kind"] == "hero" and Path(m["file_path"]).exists()), None)
        if hero:
            try:
                from PIL import Image
                with Image.open(assets[0]["file_path"]) as im0:
                    w, h = im0.size
                orient = "portrait" if h > w else "landscape" if w > h else "square"
                img, _ = _prep_for_qc(Path(hero["file_path"]).read_bytes())
                r = vision_json(
                    HERO_SYSTEM.format(orient=orient.upper(), w=w, h=h),
                    "Judge the hero image.", img)
                if r.get("orientation_mismatch"):
                    findings.append(f"A orientation-mismatch: hero shows "
                                    f"{r.get('depicted_orientation')} but file is "
                                    f"{orient} — {r.get('notes','')}")
                    if severity == "none":
                        severity = "major"
            except Exception as e:
                findings.append(f"hero-vision-error: {e}")

    if not findings:
        return None
    return {"product_id": pid, "listing_id": el.get("etsy_listing_id"),
            "url": el.get("url", ""), "title": title[:80],
            "severity": severity, "findings": findings}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--match", default="", help="regex filter on bundle/item names")
    ap.add_argument("--suffix", default="", help="report filename suffix")
    args = ap.parse_args()

    REPORT_DIR.mkdir(exist_ok=True)
    products = [p for p in db.products_with_items()
                if db.get_etsy_listing(p["id"])]
    if args.match:
        rx = re.compile(args.match, re.IGNORECASE)
        products = [p for p in products
                    if rx.search(p["bundle_type"] + " " + " ".join(
                        i["name"] for i in p.get("items", [])))]
    if args.limit:
        products = products[-args.limit:]
    print(f"[audit] auditing {len(products)} listed products...", flush=True)

    results = []
    for p in products:
        r = audit_product(p)
        tag = f"{r['severity'].upper()}: {len(r['findings'])} finding(s)" if r else "clean"
        print(f"[audit] #{p['id']:>3} {p['bundle_type'][:42]:42} {tag}", flush=True)
        if r:
            results.append(r)

    order = {"major": 0, "minor": 1, "none": 2}
    results.sort(key=lambda r: order.get(r["severity"], 3))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d") + (
        f"-{args.suffix}" if args.suffix else "")
    (REPORT_DIR / f"audit-{stamp}.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1))
    lines = [f"# Listing audit — {stamp}",
             f"\n{len(results)} of {len(products)} listed products flagged.\n"]
    for r in results:
        lines.append(f"\n## #{r['product_id']} [{r['severity'].upper()}] "
                     f"{r['title']}\n{r['url']}")
        for f in r["findings"]:
            lines.append(f"- {f}")
    (REPORT_DIR / f"audit-{stamp}.md").write_text("\n".join(lines))
    print(f"\n[audit] {len(results)} flagged -> reports/audit-{stamp}.md", flush=True)


if __name__ == "__main__":
    main()
