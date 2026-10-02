"""Full-design poster generation for the Canva line (v3: image -> Magic Layers).

The image model renders the WHOLE finished design (composition, typography, motifs,
icons) as one flat, full-bleed image. The owner then runs Canva Magic Layers on it to
get an editable template. This is where AI genuinely excels, and Magic Layers converts
flat / high-contrast / distinct-element art best, so build_prompt enforces exactly that
(design.MAGIC_LAYERS_RULES). ADDITIVE: reuses the engine's image client + hosting and
touches nothing in the primary print-at-home PDF pipeline.
"""
from __future__ import annotations

from pathlib import Path

from ..config import OUTPUT_DIR
from . import design as D

# Composition directive used when the design system has none (the fixed/forced-aesthetic and
# art-director-soft-fail path): the presets carry no `composition` key, so without this the prompt
# would ship an empty LAYOUT directive (review finding #7).
_DEFAULT_COMPOSITION = ("a clean editorial grid: ONE dominant focal element, a clear 3-step size "
                        "hierarchy (large title, medium headers, small body), wide consistent margins, "
                        "generous balanced negative space")


def _footer(content: dict) -> str:
    f = content.get("footer") or content.get("footer_title")
    return f'\n- A small footer line reading: "{f}".' if f else ""


def _join(lines: list[str], content: dict) -> str:
    return "\n".join(lines) + _footer(content)


def _content_brief(content: dict, layout: str | None = None) -> str:
    """Turn a plan's content into a compact 'render exactly this text' brief. The COMPOSITION
    varies by layout (checklist boxes vs timeline vs stats vs sign-in lines...) so products differ
    in structure, not just palette."""
    lines: list[str] = []
    statement = str(content.get("statement", "")).strip()
    if layout == "statement" or (statement and not content.get("title")):   # quote / wall-art page
        lines.append(f'- One large centered quote, the whole focus, reading exactly: "{statement}".')
        sub = str(content.get("sub", "")).strip()
        if sub:
            lines.append(f'- A small line beneath it reading: "{sub}".')
        return "\n".join(lines)

    title = str(content.get("title", "")).strip()
    if title:
        lines.append(f'- A large elegant title reading exactly: "{title}".')
    for s in (content.get("intro") or []):
        lines.append(f'- A short intro line reading: "{s}".')

    if layout == "checklist":
        lines.append("- A vertical CHECKLIST: each item on its own row with an empty square "
                     "checkbox on the left for the buyer to tick, comfortably spaced:")
        for it in (content.get("items") or [])[:12]:
            lines.append(f'    - empty checkbox then "{it}"')
        return _join(lines, content)

    if layout == "two_column":
        left, right = content.get("left") or {}, content.get("right") or {}
        lines.append("- TWO columns side by side, a vertical divider between them, each with a bold "
                     "header and a short list beneath:")
        lines.append(f'    - LEFT header "{left.get("header", "")}": '
                     + "; ".join(str(x) for x in (left.get("items") or [])))
        lines.append(f'    - RIGHT header "{right.get("header", "")}": '
                     + "; ".join(str(x) for x in (right.get("items") or [])))
        return _join(lines, content)

    if layout == "timeline":
        lines.append("- A vertical TIMELINE connected by a thin line down the middle, each step a "
                     "time, then a bold label and one short detail:")
        for s in (content.get("steps") or [])[:6]:
            lines.append(f'    - "{s.get("time", "")}" : "{s.get("label", "")}" : "{s.get("detail", "")}"')
        return _join(lines, content)

    if layout == "stat":
        lines.append("- A few BIG bold numbers evenly spaced, each with a small label beneath it:")
        for s in (content.get("stats") or [])[:4]:
            lines.append(f'    - big number "{s.get("number", "")}", label "{s.get("label", "")}"')
        return _join(lines, content)

    if layout == "table":
        cols = [str(c) for c in (content.get("columns") or [])]
        lines.append(f'- A simple clean TABLE with header row ({", ".join(cols)}) and ruled rows:')
        for row in (content.get("rows") or [])[:8]:
            cells = " | ".join(str(c) for c in row) if isinstance(row, list) else str(row)
            lines.append(f"    - {cells}")
        return _join(lines, content)

    if layout == "signin":
        n = int(content.get("lines") or 8)
        prompt = str(content.get("prompt", "")).strip()
        if prompt:
            lines.append(f'- A short prompt line reading: "{prompt}".')
        lines.append(f"- Then {n} generous, evenly spaced blank RULED horizontal lines filling the "
                     "rest of the page for guests to hand-write on. Leave the lines completely EMPTY.")
        return _join(lines, content)

    # default: welcome / sheet (title + subtitle + icon-row sections)
    sub = content.get("subtitle") or content.get("note")
    if isinstance(sub, list):
        sub = " ".join(str(s) for s in sub)
    if sub:
        lines.append(f'- A short subtitle below it reading: "{str(sub).strip()}".')
    header = content.get("section_header")
    if header:
        lines.append(f'- A small section header reading: "{header}".')
    sections = content.get("sections") or content.get("groups") or []
    if sections:
        lines.append(f"- A tidy block of {min(len(sections), 4)} items, each with a small relevant "
                     "icon, a bold label and one short supporting line:")
        for s in sections[:4]:
            label = s.get("label") or s.get("header") or ""
            body = s.get("lines") or s.get("items") or []
            body = " ".join(str(b) for b in body) if isinstance(body, list) else str(body)
            icon = s.get("icon", "a simple relevant line icon")
            lines.append(f'    - {icon}, label "{label}", line "{body}".')
    return _join(lines, content)


def expected_texts(content: dict) -> list[str]:
    """Every text string this page should render (any layout) — used by text QC to catch garble.
    Recursive so it covers checklist items, timeline steps, table rows, sign-in prompts, etc."""
    out: list[str] = []

    def walk(v):
        if isinstance(v, str):
            if v.strip():
                out.append(v.strip())
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, dict):
            for k, x in v.items():
                if k not in ("product_kind", "kind", "icon", "layout"):
                    walk(x)

    walk(content)
    return out


def build_prompt(content: dict, aesthetic: str | None = None,
                 style_brief: str | None = None, direction: dict | None = None,
                 layout: str | None = None, spine: str | None = None) -> str:
    """Compose the image prompt for a finished, Magic-Layers-ready design.

    The look is DESIGN-SYSTEM-DRIVEN (palette + type + framing all come from the design system),
    so different products render genuinely differently — nothing is hardcoded to serif/botanical.
    `direction` (preferred) is a BESPOKE, aesthetic-shaped design system written per product by the
    shared art director (`design.art_director.art_direction`, grounded in niche research); when
    absent we fall back to a fixed named `aesthetic`. `style_brief` (optional) is the raw niche
    design brief, injected only in the fixed-aesthetic fallback path.
    """
    aes = direction if isinstance(direction, dict) and direction.get("palette") else D.aesthetic(aesthetic)
    kind = content.get("product_kind") or content.get("kind") or "printable poster"
    brief = _content_brief(content, layout)
    pal = aes["palette"]
    palette = (f"Strictly use this palette: background {pal['bg']}, main text {pal['ink']}, "
               f"primary accent {pal['accent']}, secondary accent {pal['accent2']}.")
    market = f"Match what sells in this niche: {style_brief.strip()} " if style_brief else ""
    composition = (aes.get("composition") if isinstance(aes, dict) else "") or _DEFAULT_COMPOSITION
    spine_txt = (spine or "").strip().replace("—", "-").replace("–", "-")
    spine_rule = (f"SHARED SPINE (obey EXACTLY, identical on every page of this set: same names, "
                  f"dates, colors and scheme, never contradicting it): {spine_txt}. "
                  if spine_txt else "")
    return (
        f"A beautiful, complete, print-ready {kind}, portrait orientation, designed to a "
        f"professional boutique Etsy standard. Visual style: {aes['art_style']}. "
        f"Typography: {aes['type_prompt']}, with a clear size hierarchy (large title, medium "
        f"section headers, small body). Decoration: {aes['frame_prompt']}. {palette} "
        f"{market}"
        f"LAYOUT (follow this EXACT composition so every page of the set matches): {composition}. "
        "Built on intentional NEGATIVE SPACE: calm open areas and generous consistent margins around "
        "ONE clear focal hierarchy, never cluttered, never crammed edge to edge, but never plain or "
        "generic either: richly crafted, premium, distinctive, decoration framing the content. "
        f"{spine_rule}"
        "Compose the WHOLE finished design and render exactly this content:\n"
        f"{brief}\n\n"
        + D.MAGIC_LAYERS_RULES
        + (D.PHOTO_PLACEHOLDER_RULE if content.get("needs_photo") else "")
        + "\nABSOLUTELY NO extra or misspelled words, no lorem ipsum, no watermark, no signature."
    )


def generate(content: dict, aesthetic: str | None = None, out_dir: str | Path | None = None,
             host: bool = True, filename: str = "design.png", style_brief: str | None = None,
             direction: dict | None = None, layout: str | None = None,
             spine: str | None = None) -> dict:
    """Generate the finished design image (and optionally return its public URL).

    Returns {prompt, image_path, url}. The owner takes image_path/url into Canva and runs
    Magic Layers on it. Place it on a page sized to the image's 3:4 ratio to avoid white gaps.
    `direction` (bespoke art-directed design system) is preferred over a fixed `aesthetic`;
    `style_brief` steers the fixed-aesthetic fallback toward the niche's real top-seller style.
    """
    prompt = build_prompt(content, aesthetic, style_brief=style_brief, direction=direction,
                          layout=layout, spine=spine)
    from ..generate.image_client import get_image_client
    img = get_image_client().generate(prompt, size=D.POSTER_SIZE)

    out = Path(out_dir or (OUTPUT_DIR / "canva"))
    out.mkdir(parents=True, exist_ok=True)
    image_path = out / filename
    image_path.write_bytes(img)

    url = None
    if host:
        from ..generate import hosting
        url = hosting.public_url(str(image_path))
    return {"prompt": prompt, "image_path": str(image_path), "url": url}
