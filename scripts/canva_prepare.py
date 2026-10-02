"""Prepare the automatable half of a Canva-editable product: a clean-interior
botanical arch (Raywake) with its public URL, plus the crafted editable HTML
template — ready for the Claude-session Canva import. See docs/canva-line.md.

Usage:
  .venv/bin/python scripts/canva_prepare.py                 # default host-welcome spec
  .venv/bin/python scripts/canva_prepare.py --art-url URL   # reuse a hosted art URL (no gen)
  .venv/bin/python scripts/canva_prepare.py --out output/<id>/canva
"""
from __future__ import annotations

import argparse
from pathlib import Path

from etsy_engine.generate import canva_template as ct


def main() -> None:
    ap = argparse.ArgumentParser(description="Prepare a Canva-editable template (art + HTML)")
    ap.add_argument("--art-url", default=None, help="Reuse a hosted art URL (skip generation)")
    ap.add_argument("--out", default=None, help="Output dir (default output/canva)")
    args = ap.parse_args()

    res = ct.prepare(ct.CanvaSpec(),
                     out_dir=Path(args.out) if args.out else None,
                     art_url=args.art_url)
    print(f"art_path : {res['art_path']}")
    print(f"art_url  : {res['art_url']}")
    print(f"html     : {res['html_path']}")
    print()
    print("Next (Claude session — the Canva Connect MCP is only reachable there):")
    print("  1. host the HTML at a public URL (e.g. a transient public gist), then")
    print("  2. import-design-from-url(raw_url, intended_design_type='a4')")
    print("  3. export-design + review; owner opens it -> Share -> Template link")
    print("  4. deliver the Template link as the Etsy digital file")
    print("     (copy in canva_template.DELIVERY_INSTRUCTIONS; honest SEO in listing_copy())")


if __name__ == "__main__":
    main()
