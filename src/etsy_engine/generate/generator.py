"""Asset Generator orchestration (Agent 7 + 8 wired together).

Per product: build the design system, then for each bundle item generate N
variations with GPT-Image-2, QC each, and keep the best. Budget is unlimited, so
generate-many / pick-best is the default quality lever.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from .. import db
from ..config import OUTPUT_DIR, ROOT
from ..design.art_director import design_system_for
from ..design.prompt_builder import build_prompt
from ..models import Asset
from . import banner
from .qc import assess
from .image_client import get_image_client
from .raywake import DEFAULT_SIZE, RaywakeError


# Concurrent Raywake/QC requests per product (I/O-bound). Tune if rate-limited.
MAX_WORKERS = 8


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "asset"


def _store_path(path) -> str:
    """Persist paths repo-relative so they survive the repo being moved/renamed
    (db.resolve_output_path re-absolutizes on read)."""
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def _to_jpeg(img: bytes, quality: int = 90) -> bytes:
    """Normalize any engine output to a print-quality 300-DPI JPEG. Large PNGs would blow
    the assembled bundle.pdf / pages.zip past Etsy's per-file size limit. Falls back to
    raw bytes on error."""
    try:
        import io

        from PIL import Image
        im = Image.open(io.BytesIO(img))
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=quality, dpi=(300, 300))
        return buf.getvalue()
    except Exception:
        return img


def _best_variation(client, item, ds, variations: int, size: str):
    """Generate N variations for ONE item + QC each, return (prompt, best) where best is
    (score, img_bytes, qc_dict) or None if every variation failed. Thread-safe (no DB writes)."""
    prompt = build_prompt(item, ds)
    best = None
    for n in range(variations):
        try:
            img = client.generate(prompt, size=size)
        except RaywakeError as e:
            print(f"[generate] {item.name} v{n + 1} failed: {e}")
            continue
        qc = assess(img, item.name, item.spec)
        if best is None or qc["score"] > best[0]:
            best = (qc["score"], img, qc)
    return prompt, best


def _persist_asset(out_dir, item, prompt: str, best, variations: int):
    """Write the best variation to disk (JPEG) + upsert the Asset row. Returns (path, qc)."""
    score, img, qc = best
    path = out_dir / f"{item.id}_{_slug(item.name)}.jpg"
    path.write_bytes(_to_jpeg(img))
    db.upsert_asset(Asset(
        bundle_item_id=item.id, prompt=prompt, file_path=_store_path(path),
        qc_status=qc["status"], qc_score=score, qc_notes=qc["notes"], variations=variations,
    ))
    return path, qc


def regenerate_item(item_id: int, variations: int = 2, size: str = DEFAULT_SIZE,
                    only_if_better: bool = False) -> dict:
    """Surgically regenerate ONE bundle item's asset (generate-N + QC + pick-best) and replace it
    in place — NO re-rolling the whole bundle (the repair-day whack-a-mole fix). Returns the QC
    dict. With only_if_better=True, keeps the existing asset unless the new best QC score beats it.
    """
    item = db.bundle_item(item_id)
    if item is None:
        raise ValueError(f"no bundle item {item_id}")
    prod = db.product(item.product_id)
    if prod is None:
        raise ValueError(f"no product {item.product_id} for item {item_id}")
    ds = db.get_design_system(item.product_id) or design_system_for(prod)
    out_dir = OUTPUT_DIR / str(item.product_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    prompt, best = _best_variation(get_image_client(), item, ds, variations, size)
    if best is None:
        print(f"[regen] {item.name}: all variations failed — kept existing")
        return {"status": "failed", "score": 0.0, "notes": "all variations failed"}
    if only_if_better:
        prev = next((a for a in db.assets_for_product(item.product_id)
                     if a["bundle_item_id"] == item_id), None)
        if prev and (prev.get("qc_score") or 0) >= best[0]:
            print(f"[regen] {item.name}: new {best[0]:.2f} not better than {prev.get('qc_score')} — kept")
            return {"status": "kept", "score": prev.get("qc_score"), "notes": "existing was better"}
    path, qc = _persist_asset(out_dir, item, prompt, best, variations)
    print(f"[regen] {item.name}: score={best[0]:.2f} ({qc['status']}) -> {path.name}")
    return qc


def generate_product(product: dict, variations: int = 2, size: str = DEFAULT_SIZE) -> int:
    """Generate all assets for one product. Returns count of assets produced."""
    # 1. Design system (reuse if already built)
    ds = db.get_design_system(product["id"])
    if ds is None:
        ds = design_system_for(product)
        db.upsert_design_system(ds)
        print(f"[generate] design system: {ds.aesthetic}")

    out_dir = OUTPUT_DIR / str(product["id"])
    out_dir.mkdir(parents=True, exist_ok=True)
    client = get_image_client()

    items = db.bundle_items_for(product["id"])

    # Letter banners are produced deterministically (not via the AI image path):
    # one themed pennant + stamped glyphs -> a multi-page PDF asset. Handle them
    # first and up front so a pennant failure surfaces loudly.
    banner_items = [it for it in items if banner.is_banner(it)]
    items = [it for it in items if not banner.is_banner(it)]
    produced_banners = 0
    for it in banner_items:
        res = banner.render_banner(it, ds, product)
        db.upsert_asset(Asset(
            bundle_item_id=it.id, prompt=f"deterministic letter_banner: {it.spec}",
            file_path=_store_path(res["pdf"]),
            qc_status="passed" if res["count"] else "failed", qc_score=1.0,
            qc_notes=f"deterministic banner, {res['count']} usable pennant pages",
            variations=1,
        ))
        produced_banners += 1
        print(f"[generate] banner: {it.name} -> {res['count']} pages ({res['pdf'].name})")

    def work(item):
        """Generate N variations + QC for one item, return (item, prompt, best). Thread-safe."""
        prompt, best = _best_variation(client, item, ds, variations, size)
        return item, prompt, best

    # Generate all items concurrently (HTTP + QC are I/O-bound); write in main thread.
    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for fut in as_completed([ex.submit(work, it) for it in items]):
            results.append(fut.result())

    produced = produced_banners
    all_passed = True
    for item, prompt, best in results:
        if best is None:
            print(f"[generate] {item.name}: all variations failed, skipping")
            all_passed = False
            continue
        path, qc = _persist_asset(out_dir, item, prompt, best, variations)
        if qc["status"] == "failed":
            all_passed = False
        produced += 1
        print(f"[generate] {item.name}: score={best[0]:.2f} ({qc['status']}) -> {path.name}")

    # Completeness self-heal: retry (sequentially) any item that still has no asset,
    # so a transient failure never silently leaves the bundle short a page.
    have = {a["bundle_item_id"] for a in db.assets_for_product(product["id"])}
    for item in items:
        if item.id in have:
            continue
        print(f"[generate] self-heal retry: {item.name}")
        _, prompt, best = work(item)
        if best is None:
            print(f"[generate] WARNING: {item.name} still failed — bundle incomplete")
            all_passed = False
            continue
        path, _ = _persist_asset(out_dir, item, prompt, best, variations)
        produced += 1
        print(f"[generate] self-heal ok: {item.name} -> {path.name}")

    db.set_product_status(product["id"], "qc_passed" if all_passed else "generated")
    return produced
