"""Batch-schedule Pinterest pins for products with Etsy listings.

Reads products with Etsy listings, takes their hero mockup image, and creates
Postiz-scheduled Pinterest pins linking to the Etsy listing.

By default only schedules NEW products (not previously pinned). Tracks scheduled
product IDs in data/pinterest_scheduled.json.

Usage:
    python scripts/batch_pinterest.py              # new-only (default)
    python scripts/batch_pinterest.py --dry         # preview only
    python scripts/batch_pinterest.py --all         # reschedule all
    python scripts/batch_pinterest.py --start-id N  # from specific product
    python scripts/batch_pinterest.py --per-day 1   # 1 pin per day
"""
import sys, re, json
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, "src")

from etsy_engine import db, config
from etsy_engine.marketing.postiz import PostizClient, PostizError

OUTPUT_DIR = Path("output")
TRACKING_FILE = Path("data") / "pinterest_scheduled.json"
BOARD_NAME = "Digital Prints & Printables"
PINS_PER_DAY = 2
START_HOUR_UTC = 10
HOURS_BETWEEN = 6
PIN_TITLE_MAX = 100
PIN_DESC_MAX = 500


def _load_tracking() -> set[int]:
    if TRACKING_FILE.exists():
        try:
            return set(json.loads(TRACKING_FILE.read_text()))
        except (json.JSONDecodeError, OSError):
            pass
    return set()


def _save_tracking(ids: set[int]) -> None:
    TRACKING_FILE.write_text(json.dumps(sorted(list(ids))))


def _find_hero(product_id: int) -> str | None:
    mockup_dir = OUTPUT_DIR / str(product_id) / "mockups"
    if not mockup_dir.exists():
        return None
    for fname in ["hero.jpg", "hero.png", "hero.jpeg"]:
        p = mockup_dir / fname
        if p.exists():
            return str(p)
    imgs = sorted(mockup_dir.glob("*.jpg")) + sorted(mockup_dir.glob("*.png"))
    return str(imgs[0]) if imgs else None


def _pin_title(listing_title: str) -> str:
    t = listing_title.replace("—", "-").replace("–", "-").replace("|", "·")
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) <= PIN_TITLE_MAX:
        return t
    t = t[:PIN_TITLE_MAX].rsplit(" ", 1)[0]
    return t.strip()


def _pin_description(listing_desc: str, listing_url: str) -> str:
    desc = (listing_desc or "").replace("\n", " ").strip()
    desc = re.sub(r"AI Disclosure.*$", "", desc, flags=re.DOTALL).strip()
    desc = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", desc)
    footer = f"\n\n{listing_url}\n#etsy #printable #digitaldownload"
    max_body = PIN_DESC_MAX - len(footer) - 5
    if len(desc) > max_body:
        desc = desc[:max_body].rsplit(" ", 1)[0]
    return desc + footer


def _publish_at(day_offset: int, slot: int, per_day: int = PINS_PER_DAY) -> str:
    tz = timezone.utc
    d = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    d += timedelta(days=day_offset + 1)
    # Spread pins during waking hours (avoid very early morning failures).
    # Use START_HOUR_UTC / HOURS_BETWEEN so times are predictable.
    if per_day <= 1:
        hour, minute = START_HOUR_UTC, 0
    else:
        hour = START_HOUR_UTC + (slot * HOURS_BETWEEN)
        minute = 0
    d = d.replace(hour=min(hour, 21), minute=minute)
    if d <= datetime.now(tz):
        d += timedelta(minutes=30)
    return d.isoformat()


def main(dry: bool = False, start_id: int = 0, per_day: int = PINS_PER_DAY,
         reschedule_all: bool = False):
    # Load tracking
    already = _load_tracking() if not reschedule_all else set()

    # Gather products
    rows = db.products_with_listings()
    products = [dict(r) for r in rows if r["product_id"] >= start_id]
    products.sort(key=lambda p: p["product_id"])

    if not products:
        print("[pinterest] no products with Etsy listings found")
        return

    total = len(products)
    new_count = sum(1 for p in products if p["product_id"] not in already)
    print(f"[pinterest] {total} products total, {new_count} new (not yet pinned)")

    # Prepare pin payloads (new only)
    pins = []
    skipped = 0
    for p in products:
        pid = p["product_id"]
        if pid in already:
            continue

        hero = _find_hero(pid)
        if not hero:
            print(f"  #{pid} SKIP: no hero image")
            skipped += 1
            continue

        url = p.get("url") or p.get("listing_url") or ""
        if not url:
            print(f"  #{pid} SKIP: no Etsy URL")
            skipped += 1
            continue

        title = _pin_title(p.get("listing_title") or p.get("title_concept") or f"Product #{pid}")
        desc = _pin_description(p.get("description") or "", url)

        pins.append({
            "product_id": pid,
            "image_path": hero,
            "title": title,
            "description": desc,
            "link": url,
        })

    if not pins:
        print("[pinterest] nothing new to schedule")
        return

    print(f"[pinterest] {len(pins)} new pins ready ({skipped} skipped)")

    if dry:
        for i, p in enumerate(pins):
            day = i // per_day
            slot = i % per_day
            ts = _publish_at(day, slot, per_day)
            print(f"  [{ts}] #{p['product_id']} -> {p['title'][:60]}...")
        print(f"\n[dry] would schedule {len(pins)} pins across {len(pins)//per_day + 1} days")
        return

    # Schedule via Postiz
    client = PostizClient()
    scheduled, failed = 0, 0
    for i, p in enumerate(pins):
        day = i // per_day
        slot = i % per_day
        ts = _publish_at(day, slot, per_day)

        try:
            result = client.schedule_image_pin(
                image_path=p["image_path"],
                title=p["title"],
                description=p["description"],
                link=p["link"],
                board=BOARD_NAME,
                publish_at=ts,
                alt_text=p["title"],
            )
            post_id = result.get("post_id") or "?"
            print(f"  [{ts}] #{p['product_id']} OK post_id={post_id}  {p['title'][:50]}...")
            already.add(p["product_id"])
            _save_tracking(already)
            scheduled += 1
        except PostizError as e:
            print(f"  [{ts}] #{p['product_id']} FAIL: {e}")
            failed += 1

    print(f"\n[pinterest] done: {scheduled} scheduled, {failed} failed, {skipped} skipped")


if __name__ == "__main__":
    dry = "--dry" in sys.argv
    reschedule_all = "--all" in sys.argv
    start_id = 0
    per_day = PINS_PER_DAY
    for i, arg in enumerate(sys.argv):
        if arg == "--start-id" and i + 1 < len(sys.argv):
            start_id = int(sys.argv[i + 1])
        if arg == "--per-day" and i + 1 < len(sys.argv):
            per_day = int(sys.argv[i + 1])
    main(dry=dry, start_id=start_id, per_day=per_day, reschedule_all=reschedule_all)
