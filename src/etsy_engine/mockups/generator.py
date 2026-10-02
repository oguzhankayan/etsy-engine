"""Mockup Generator (Agent 9). Six Etsy listing images per product, via GPT-Image-2.

Per the owner's decision, mockups are model-generated (not Pillow composites).
Each kind has a prompt template that bakes in the product's design system so the
sales images match the actual printables.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .. import db
from ..config import OUTPUT_DIR
from ..models import DesignSystem, Mockup
from ..generate.image_client import get_image_client
from ..generate.generator import _store_path, _to_jpeg

# Single-item products (one print/page) don't need the 6-image bundle set — the
# grid "contents overview" and per-page shots make no sense for one design. Ship
# a focused 3: the design itself, it shown in use, and the print sizes.
SINGLE_MOCKUP_KINDS = ["hero", "lifestyle", "size_guide"]

# Bundles ship a focused 3 too (was 6) to cut image spend: a strong hero, a
# lifestyle shot, and the contents grid — the highest-value third image for a
# multi-page kit (shows everything included) and the cheapest (contents_overview
# has a pixel-exact PIL fallback, so it can render without an extra AI image).
BUNDLE_MOCKUP_KINDS = ["hero", "lifestyle", "contents_overview"]

# For single-item products the mockup MUST show the EXACT product (Etsy honesty /
# anti-ban). We pass the real artwork to the image model as a reference image
# (see generate/hosting.py) and place it into each scene, reproduced faithfully. These
# scene prompts assume a reference image is supplied.
REFERENCE_FAITHFUL = (
    " IMPORTANT: reproduce the artwork from the reference image FAITHFULLY and "
    "UNCHANGED — identical text, layout, colors and composition. Do not redraw, "
    "restyle, recolor, crop, or add/remove any elements. Copy every word EXACTLY as "
    "written on the pages: never re-spell, duplicate, drop, swap, or invent any word "
    "or letter. It must be clearly the "
    "same poster. Photorealistic, premium, trustworthy e-commerce styling. "
    "Do NOT add or write the words 'editable', 'customizable', 'customize', "
    "'fillable', 'template', 'personalize', or 'Canva' anywhere in the image — these "
    "are flat printables; only accurate badges are allowed (Printable, Instant "
    "Download, Print at Home)."
)
# The Canva line reuses this SAME engine but its products ARE editable templates, so (honesty gate,
# RULES H5) a small 'Editable Canva Template' badge is welcome instead of the flat-printable ban.
REFERENCE_FAITHFUL_EDITABLE = (
    " IMPORTANT: reproduce the design from the reference image FAITHFULLY and UNCHANGED — identical "
    "text, layout, colors and composition. Do not redraw, restyle, recolor, crop, or add/remove any "
    "elements. Copy every word EXACTLY as written: never re-spell, duplicate, drop, swap, or invent "
    "any word or letter. It must be clearly the same design. Photorealistic, premium, trustworthy e-commerce "
    "styling. A small tasteful badge reading 'Editable Canva Template' is welcome (this genuinely is "
    "an editable Canva template)."
)
REFERENCE_SCENES = {
    "hero": (
        "Front-facing Etsy hero mockup: the artwork from the reference image, printed "
        "and shown in a slim modern frame on a softly-lit styled wall whose color "
        "CONTRASTS with the artwork so the framed print POPS against Etsy's white "
        "search grid (never a white or pale-on-pale wall). Minimal tasteful decor, "
        "the framed print fills most of the image."
    ),
    "lifestyle": (
        "Cozy lifestyle mockup: the artwork from the reference image, framed and hung "
        "on a warm neutral wall in a styled room with a small plant and natural light, "
        "realistic soft shadows, aspirational interior."
    ),
    "size_guide": (
        "Clean size-guide mockup: the artwork from the reference image shown as a "
        "framed print, with simple dimension labels and measurement lines indicating "
        "US Letter (8.5x11 in) and A4 print sizes, on a tidy neutral background."
    ),
}

# Bundle (multi-page kit) reference scenes. Each places the REAL printable pages
# from the reference images into a scene, reproduced faithfully — so the mockups
# show the actual product, not invented pages. Keep refs small (<=3) for speed.
BUNDLE_REFERENCE_SCENES = {
    "hero": (
        "Eye-catching, scroll-stopping Etsy HERO listing image (the main thumbnail). "
        "Arrange the EXACT printable pages from the reference images as a bold, "
        "dynamic flat-lay with strong visual hierarchy and a few tasteful props. "
        "Set the whole arrangement on a BOLD, SATURATED background — a solid color "
        "block or a wide colored border pulled from the design's own palette — so the "
        "thumbnail has a HARD EDGE and POPS against Etsy's white search grid. Never a "
        "white, cream, or pale background that dissolves into the page. "
        "Add a clean BOLD TITLE BANNER/overlay reading \"{bundle}\" and small accurate "
        "badges (e.g. 'Printable', 'Instant Download'). Do NOT put any page-count or "
        "'N pages' number anywhere (we can't guarantee the count, so never state one). "
        "High-converting, premium, vibrant, professional. Keep the pages reproduced "
        "faithfully."
    ),
    "lifestyle": (
        "Cozy lifestyle mockup: the EXACT printable pages from the reference images "
        "shown printed and in use on a warm wooden desk in a styled home, a mug and "
        "small plant nearby, natural light, realistic shadows."
    ),
    "close_up": (
        "Close-up detail shot of the EXACT printable page from the reference image, "
        "showing crisp print quality and typography, on a clean styled surface."
    ),
    "feature_highlight": (
        "Feature-highlight mockup: the EXACT printable page from the reference image "
        "beside 3 short benefit callouts — 'Instant Download', 'Print at Home', "
        "'US Letter & A4' — clean icons, tidy layout."
    ),
    "size_guide": (
        "Size-guide mockup: the EXACT printable page from the reference image shown "
        "with simple dimension labels and measurement lines for US Letter (8.5x11 in) "
        "and A4, on a tidy neutral background."
    ),
}
# How many real-page references each bundle mockup kind gets.
_BUNDLE_REF_COUNT = {"hero": 3, "lifestyle": 2, "close_up": 1,
                     "feature_highlight": 1, "size_guide": 1}

# contents_overview: pass ALL real pages to gpt-image-2 and have it lay them out as
# one cohesive grid (looks better than a flat PIL paste). Slow (~5 min for 10 refs)
# and network-dependent, so _contents_grid (PIL, pixel-exact) is the fallback.
CONTENTS_SCENE = (
    "Etsy contents-overview image: a neat, evenly-spaced GRID of ALL the exact "
    "printable pages from the reference images shown as page thumbnails on a clean "
    "light background, with a small title 'Everything Included'. Include EVERY page "
    "from the references, omit none, keep each page faithful and legible."
)

# The 'what's included' image ships the pixel-exact PIL grid by default: it pastes the REAL page
# thumbnails, so it is guaranteed to show exactly one tile per page — no invented/blank cell, no
# re-spelled text. i2i (CONTENTS_SCENE) looks slightly more styled but redraws the pages: it pads an
# N+1 grid with a blank/invented page (the owner's #1 complaint: a decorative page that is not a
# usable artifact) and mangles small text. So i2i stays opt-in; correctness + honesty win by default.
CONTENTS_USE_I2I = False


def _contents_grid(page_paths: list[str], noun: str = "Printable Pages") -> bytes | None:
    """PIL composite: a tidy grid of ALL the REAL page thumbnails — pixel-exact,
    so the 'what's included' image is guaranteed honest (no model redraw). `noun` labels the
    pages honestly per line ('Printable Pages' for a flat PDF, 'Editable Canva Pages' for Canva)."""
    from io import BytesIO
    from PIL import Image, ImageDraw, ImageFont

    pages = [Image.open(p).convert("RGB") for p in page_paths if Path(p).exists()]
    if not pages:
        return None
    W = H = 2048
    bg = (248, 246, 242)
    canvas = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(canvas)

    def font(size, bold=True):
        for p in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf"
                  if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
                  "/System/Library/Fonts/Helvetica.ttc"):
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
        return ImageFont.load_default()

    title = f"Everything Included · {len(pages)} {noun}"
    tf = font(60)
    tw = draw.textlength(title, font=tf)
    draw.text(((W - tw) / 2, 48), title, fill=(60, 60, 60), font=tf)

    top = 160
    n = len(pages)
    cols = 4 if n > 6 else 3
    rows = (n + cols - 1) // cols
    pad = 36
    cell_w = (W - pad * (cols + 1)) / cols
    cell_h = (H - top - pad * (rows + 1)) / rows
    for i, im in enumerate(pages):
        r, c = divmod(i, cols)
        # Center a partial last row so an N that doesn't fill the grid (e.g. 5 pages in 3 cols)
        # reads as a balanced set, never an awkward empty corner that looks like a missing page.
        items_in_row = min(cols, n - r * cols)
        row_w = items_in_row * cell_w + (items_in_row - 1) * pad
        x0 = (W - row_w) / 2
        thumb = im.copy()
        thumb.thumbnail((int(cell_w), int(cell_h)), Image.LANCZOS)
        x = int(x0 + c * (cell_w + pad) + (cell_w - thumb.width) / 2)
        y = int(top + pad + r * (cell_h + pad) + (cell_h - thumb.height) / 2)
        # soft shadow + white border for a clean catalog look
        draw.rectangle([x - 6, y - 6, x + thumb.width + 8, y + thumb.height + 10],
                       fill=(225, 222, 217))
        canvas.paste(thumb, (x, y))
    out = BytesIO()
    canvas.save(out, "JPEG", quality=90)
    return out.getvalue()

# Etsy listing images render square; Etsy recommends >=2000px on the short side.
MOCKUP_SIZE = "2048x2048"

# Commercial-photography craft distilled from the awesome-gpt-image-2 prompt
# library (CC0). Appended to every mockup for a premium, editorial look.
MOCKUP_QUALITY = (
    " Premium e-commerce product-photography aesthetic: soft natural directional "
    "lighting, realistic contact shadows, shallow depth of field with gentle bokeh, "
    "crisp focus, balanced negative space, refined editorial styling, cohesive "
    "color grade, photorealistic, ultra-detailed, high-end and trustworthy. "
    "No real brand names, logos, or trademarks. "
    "Do NOT render the words 'editable', 'customizable', 'fillable', or 'Canva' "
    "anywhere (the files are flat printables, not editable templates). Any badge "
    "text must be accurate, e.g. 'Printable', 'Instant Download', 'Print at Home'."
)

# Prompt template per mockup kind. {bundle}, {aesthetic}, {palette}, {items}, {n}.
TEMPLATES = {
    "hero": (
        "Etsy hero listing image for a digital printable product called \"{bundle}\". "
        "Show the printable pages displayed attractively as a flat lay, with a bold "
        "clean title overlay reading \"{bundle}\". {aesthetic} aesthetic. "
        "Palette: {palette}. Professional, eye-catching, high-converting thumbnail."
    ),
    "lifestyle": (
        "Lifestyle product photo showing the \"{bundle}\" printables in real use "
        "in a cozy, natural home setting. {aesthetic} mood. Palette: {palette}. "
        "Warm, aspirational, realistic scene."
    ),
    "contents_overview": (
        "A neat grid overview showing all {n} pages included in the \"{bundle}\" "
        "digital bundle: {items}. Each page as a small page-preview thumbnail on a "
        "clean background — show the page artwork only, do NOT print feature words "
        "like 'editable' on the thumbnails. {aesthetic} style. Palette: {palette}."
    ),
    "close_up": (
        "Close-up detail shot of one page from the \"{bundle}\" printable, showing "
        "the crisp print quality, typography and illustrations. {aesthetic} style. "
        "Palette: {palette}."
    ),
    "feature_highlight": (
        "Feature-highlight graphic for the \"{bundle}\" listing, with 3-4 short "
        "benefit callouts (e.g. instant download, print at home, US Letter & A4). "
        "{aesthetic} style. Palette: {palette}. Clean icons and short text."
    ),
    "size_guide": (
        "Size guide image for the \"{bundle}\" printables, showing the pages in "
        "US Letter (8.5x11) and A4 formats with dimension labels. {aesthetic} "
        "style. Palette: {palette}. Informative and tidy."
    ),
}


def _claims_editable(img: bytes) -> bool:
    """Vision check: does the image visibly bake in a false 'editable' claim?
    Compliance gate so we never publish a mislabeling mockup. Fails-open (returns
    False) if QC is unavailable, so generation still works without an LLM key."""
    from ..config import settings
    if not settings.anthropic_api_key:
        return False
    from ..llm import vision_json
    sys = ("Does this image visibly contain ANY of these words as rendered text: "
           "editable, customizable, customize, fillable, template, templates, "
           "personalize, personalized, Canva? JSON only: {\"has\": true/false}")
    try:
        return bool(vision_json(sys, "check", img).get("has"))
    except Exception:
        return False


def _fill(kind: str, product: dict, ds: DesignSystem, item_names: list[str]) -> str:
    palette = ", ".join(json.loads(ds.palette or "[]")) or "cohesive colors"
    return TEMPLATES[kind].format(
        bundle=product["bundle_type"],
        aesthetic=ds.aesthetic or "clean modern",
        palette=palette,
        items=", ".join(item_names) or "the printable pages",
        n=len(item_names) or "several",
    ) + MOCKUP_QUALITY


def _orientation_note(page_paths: list[str]) -> str:
    """State the artwork's TRUE orientation so i2i never re-frames a portrait print into a landscape
    scene (#122: the model happily re-framed a 2:3 portrait into a landscape lifestyle shot). The mockup
    canvas stays square; the DEPICTED frame must match the deliverable."""
    try:
        from PIL import Image
        with Image.open(page_paths[0]) as im0:
            w0, h0 = im0.size
        if h0 > w0:
            return (f" The artwork itself is a VERTICAL PORTRAIT print (aspect {w0}:{h0}); depict it "
                    "in a PORTRAIT-oriented frame — never landscape, never square.")
        if w0 > h0:
            return (f" The artwork itself is a HORIZONTAL LANDSCAPE print (aspect {w0}:{h0}); depict "
                    "it in a LANDSCAPE-oriented frame — never portrait.")
    except Exception:  # noqa: BLE001
        pass
    return ""


def _hero_style_directive(style_brief: dict | None) -> str:
    """Turn the niche's winning-style research into a HERO-specific instruction, so the thumbnail is
    designed to out-compete the ACTUAL niche search grid (not a one-size flat-lay). The research
    already studied the niche's top-selling HEROES; this is where that intel reaches the thumbnail.
    Empty string when there is no brief (fails soft to the generic hero)."""
    if not isinstance(style_brief, dict):
        return ""
    look = " ".join(str(style_brief.get(k) or "").strip() for k in ("layout", "palette", "vibe")).strip()
    diff = str(style_brief.get("differentiator") or "").strip()
    if not look and not diff:
        return ""
    out = ""
    if look:
        out += (f" This niche's best-selling listings win the thumbnail with this visual language: "
                f"{look}. Compose the hero so a buyer instantly reads it as THIS niche.")
    if diff:
        out += (f" Then push exactly ONE axis past the incumbents so it stops the scroll: {diff}. "
                "Stay recognizably in-niche; do not restyle into a different product.")
    return out


def _niche_style_summary(style_brief: dict | None) -> str | None:
    """Short 'what wins this niche' descriptor for the thumbnail QC, so pop is judged against the real
    competitive grid ('stands out FROM this look'), not in the abstract."""
    if not isinstance(style_brief, dict):
        return None
    s = " ".join(str(style_brief.get(k) or "").strip() for k in ("vibe", "palette", "motifs")).strip()
    return s or None


def render_listing_set(title: str, ref_urls: list[str], page_paths: list[str],
                       out_dir: str | Path, *, is_single: bool = False,
                       allow_editable: bool = False, kinds: list[str] | None = None,
                       style_brief: dict | None = None
                       ) -> list[tuple[str, str, Path]]:
    """The ONE Etsy listing-image engine. BOTH product lines call this — the PDF line via
    generate_mockups and the Canva line via canva.mockups.build_all — so a Canva set gets the EXACT
    same scenes, quality, reference-faithfulness and gated hero QC as a bundle, never a parallel
    implementation.

    Reference-faithful i2i (a strong hero flat-lay + a lifestyle shot + a contents grid, with a
    pixel-exact PIL fallback for contents), generated concurrently, with a credit-bounded
    hero-thumbnail redo. `allow_editable` lets a Canva template show an 'Editable Canva Template'
    badge (a flat PDF must NOT). Writes {kind}.jpg into out_dir; returns [(kind, prompt, path)]."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    client = get_image_client()
    faithful = REFERENCE_FAITHFUL_EDITABLE if allow_editable else REFERENCE_FAITHFUL
    grid_noun = "Editable Canva Pages" if allow_editable else "Printable Pages"
    if kinds is None:
        kinds = SINGLE_MOCKUP_KINDS if is_single else BUNDLE_MOCKUP_KINDS
    orientation_note = _orientation_note(page_paths)
    hero_directive = _hero_style_directive(style_brief)   # niche-winning look -> the hero (CTR gate)
    niche_style = _niche_style_summary(style_brief)       # grid-aware pop for the hero thumbnail QC

    def work(kind):
        # contents_overview for a bundle: the pixel-exact PIL grid of ALL real pages — the FREE,
        # guaranteed-honest path (exactly one tile per page). i2i is opt-in via CONTENTS_USE_I2I.
        if kind == "contents_overview" and not is_single:
            # PIL grid is PRIMARY: exactly the real pages, one tile each, no invented/blank cell or
            # redrawn text (see CONTENTS_USE_I2I). i2i is opt-in and only when the toggle is set.
            if CONTENTS_USE_I2I:
                try:
                    img = client.generate(CONTENTS_SCENE + faithful, size=MOCKUP_SIZE,
                                          image_urls=ref_urls, timeout=420, retries=1)
                    if img:
                        return kind, "contents i2i (all real pages)", img
                except Exception as e:  # noqa: BLE001
                    print(f"[mockups] contents i2i failed ({e}); using PIL grid")
            return kind, "contents grid (PIL, exactly the real pages)", _contents_grid(page_paths, grid_noun)
        if is_single:
            prompt = REFERENCE_SCENES[kind] + faithful + orientation_note
            refs = ref_urls[:1]
        else:
            prompt = (BUNDLE_REFERENCE_SCENES[kind].format(bundle=title, n=len(page_paths))
                      + faithful + orientation_note)
            refs = ref_urls[:_BUNDLE_REF_COUNT.get(kind, 1)]
        if kind == "hero":            # steer the CTR gate to the niche's winning look + one bolder axis
            prompt += hero_directive
        # Honesty is enforced via the PROMPT (faithful forbids/permits the badge per line). We do NOT
        # gate on a vision check here: it false-positives on clean mockups and just burns credits.
        try:
            img = client.generate(prompt, size=MOCKUP_SIZE, image_urls=refs, timeout=300)
        except Exception as e:  # noqa: BLE001
            print(f"[mockups] {kind} gen failed: {e}")
            return kind, prompt, None
        return kind, prompt, img

    done: dict[str, tuple[str, Path]] = {}
    with ThreadPoolExecutor(max_workers=len(kinds)) as ex:  # all scenes concurrently
        for fut in as_completed([ex.submit(work, k) for k in kinds]):
            kind, prompt, img = fut.result()
            if img is None:
                continue
            path = out / f"{kind}.jpg"
            path.write_bytes(_to_jpeg(img))       # normalize to print JPEG
            done[kind] = (prompt, path)
            print(f"[mockups] {kind} -> {path.name}")

    # The hero IS the search thumbnail — the click-through gate, the single highest-ROI image. Score
    # it at thumbnail size and, if weak, do ONE gated redo (credit-bounded), keeping the better of the
    # two. Result saved next to the file for the human reviewer.
    if "hero" in done:
        prompt, path = done["hero"]
        from ..generate.qc import assess_thumbnail
        tqc = assess_thumbnail(path.read_bytes(), niche_style=niche_style)
        if tqc["status"] == "failed":
            print(f"[mockups] hero thumb {tqc['score']:.2f} WEAK — 1 gated redo")
            _, prompt2, img2 = work("hero")
            if img2 is not None:
                jb = _to_jpeg(img2)
                tqc2 = assess_thumbnail(jb, niche_style=niche_style)
                if tqc2.get("score", 0.0) > tqc.get("score", 0.0):
                    path.write_bytes(jb)          # promote the better hero
                    prompt, tqc = prompt2, tqc2
        (out / "hero_thumb_qc.json").write_text(json.dumps(tqc, indent=1))
        marker = "OK" if tqc["status"] == "passed" else "WEAK THUMBNAIL"
        print(f"[mockups] hero thumb-appeal {tqc['score']:.2f} [{marker}] {tqc['notes'][:100]}")
        # IP safety: the ONLY check on the actual pixels (every other IP gate is term-level and
        # pre-generation). The hero shows the real pages, so this catches a logo/character/crest the
        # image model may have hallucinated onto the art. Warn + persist for the owner's draft review;
        # fail-open so a noisy vision call never blocks generation.
        from ..generate.qc import assess_ip_safety
        ipqc = assess_ip_safety(path.read_bytes(), context=title)
        (out / "hero_ip_qc.json").write_text(json.dumps(ipqc, indent=1))
        if ipqc.get("flagged"):
            print(f"[mockups] ⚠ IP RISK on hero — possible real mark: {ipqc.get('what')!r} "
                  f"(conf {ipqc.get('confidence', 0):.2f}). REVIEW before publishing (Etsy ban risk).")
        done["hero"] = (prompt, path)

    return [(k, done[k][0], done[k][1]) for k in kinds if k in done]


def generate_mockups(product: dict, kinds: list[str] | None = None) -> int:
    """Generate the listing-image set for one PDF product (writes Mockup rows). Returns count created.
    The scene engine is SHARED with the Canva line via render_listing_set (no parallel systems)."""
    ds = db.get_design_system(product["id"])
    if ds is None:
        print(f"[mockups] no design system for product {product['id']}; run generate first")
        return 0
    item_names = [b.name for b in db.bundle_items_for(product["id"])]
    is_single = len(item_names) <= 1
    # Both bundles and single products ship a focused 3-image set (cost control).
    if kinds is None:
        kinds = SINGLE_MOCKUP_KINDS if is_single else BUNDLE_MOCKUP_KINDS
        # Full-set regeneration: purge stale rows from a previous kind set so they can't be
        # re-uploaded to Etsy (#122 stale size_guide lesson).
        dropped = db.delete_mockups_not_in(product["id"], list(kinds))
        if dropped:
            print(f"[mockups] purged {dropped} stale mockup row(s)")

    # Show the EXACT product in every mockup (Etsy honesty / anti-ban): pass the real page
    # asset(s) to the image model as reference images, so each scene reproduces the actual
    # pages, never an invented design.
    from ..generate.hosting import upload
    assets = db.assets_for_product(product["id"])
    page_paths = [a["file_path"] for a in assets]
    ref_urls = []
    for a in assets[:12]:  # all pages (scenes use a small subset; contents uses all)
        u = upload(a["file_path"])
        if u:
            ref_urls.append(u)
    if not ref_urls:
        print("[mockups] WARNING: no usable reference image — skipping so we never "
              "ship mockups that don't match the product")
        return 0

    out_dir = OUTPUT_DIR / str(product["id"]) / "mockups"
    triples = render_listing_set(product["bundle_type"], ref_urls, page_paths, out_dir,
                                 is_single=is_single, allow_editable=False, kinds=kinds)
    for kind, prompt, path in triples:
        db.upsert_mockup(Mockup(product_id=product["id"], kind=kind,
                                prompt=prompt, file_path=_store_path(path)))
    return len(triples)
