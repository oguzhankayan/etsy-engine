"""Canva design system — the shared craft layer every generated template draws from.

This is what makes the Canva line GENERAL and reliable at once: the LLM decides
WHAT (product type, content, which aesthetic); this module + the layout library
guarantee HOW (palette, type hierarchy, spacing, and the hard craft rules learned
the hard way). Add an aesthetic or a layout to widen coverage; the craft floor is
enforced centrally so no future template can regress.

ADDITIVE: nothing here touches the primary print-at-home PDF pipeline.
"""
from __future__ import annotations

import re

from ..config import settings as _settings

PAGE_W, PAGE_H = 794, 1123          # A4 @ 96dpi (portrait)
MARGIN = 96                          # safe content inset (px)

# --- Aesthetics -------------------------------------------------------------
# Each is a full look: a role-based palette (all inks verified >= 4.5:1 on bg),
# a display+body font pairing on a real contrast axis (serif+geometric etc.,
# Canva-available names with graceful fallbacks), and an art-style phrase fed to
# the image model. `art_frame` = how the art occupies the page.
AESTHETICS: dict[str, dict] = {
    "botanical": {
        "label": "Boutique botanical (host, wedding, welcome, spa)",
        "palette": {"bg": "#FEF8EB", "ink": "#35322B", "ink_soft": "#6B6154",
                    "accent": "#556349", "accent2": "#B4693F", "rule": "#C3CAB0",
                    "gold": "#C29A55"},
        "fonts": {"display": "'Bodoni Moda','Prata',Georgia,serif",
                  "body": "'Jost','Futura','Century Gothic',sans-serif"},
        "art_style": ("delicate watercolor botanicals, muted sage green, soft terracotta "
                      "and dusty rose on warm cream, a thin gold line, editorial and airy"),
        "type_prompt": ("a high-contrast elegant SERIF display title (Bodoni / Didone feel) "
                        "with a clean sans-serif for supporting text"),
        "frame_prompt": ("delicate watercolor botanical sprigs and florals framing the top corners "
                         "and bottom, and a thin gold divider"),
        "art_frame": "arch",
    },
    "editorial": {
        "label": "Elegant editorial (planners, notes, minimalist gifts)",
        "palette": {"bg": "#F6F4EF", "ink": "#232019", "ink_soft": "#5C564B",
                    "accent": "#8A5A2B", "accent2": "#232019", "rule": "#D8D2C6",
                    "gold": "#8A5A2B"},
        "fonts": {"display": "'Spectral','Libre Caslon Text',Georgia,serif",
                  "body": "'Jost','Archivo','Helvetica Neue',sans-serif"},
        "art_style": ("restrained fine-line editorial illustration, single muted accent, "
                      "generous negative space, magazine typographic feel"),
        "type_prompt": ("a refined high-contrast SERIF display title with generous letter-spacing, "
                        "and a minimal sans-serif for body"),
        "frame_prompt": ("restrained fine-line illustration in the corners only, lots of negative "
                         "space, at most one hairline rule, NO dense florals"),
        "art_frame": "corner",
    },
    "modern_minimal": {
        "label": "Modern minimal (organizers, trackers, checklists)",
        "palette": {"bg": "#FBFAF8", "ink": "#20242A", "ink_soft": "#5A6068",
                    "accent": "#2F6E63", "accent2": "#20242A", "rule": "#E3E1DC",
                    "gold": "#2F6E63"},
        "fonts": {"display": "'Archivo','Jost','Helvetica Neue',sans-serif",
                  "body": "'Jost','Archivo','Helvetica Neue',sans-serif"},
        "art_style": ("minimal geometric line accents, one calm accent color, clean "
                      "grids, lots of white space, no illustration clutter"),
        "type_prompt": ("a bold modern SANS-SERIF display title in UPPERCASE (Archivo / Helvetica "
                        "feel), NO serif anywhere, light sans for body"),
        "frame_prompt": ("NO botanical or floral decoration at all; a clean minimalist grid with "
                         "lots of white space and at most one thin geometric accent line"),
        "art_frame": "none",
    },
    "playful": {
        "label": "Playful (kids activities, birthday, nursery, coloring)",
        "palette": {"bg": "#FFF9F0", "ink": "#33302E", "ink_soft": "#6E655C",
                    "accent": "#E08A3C", "accent2": "#3F8E8A", "rule": "#F0DCC4",
                    "gold": "#E08A3C"},
        "fonts": {"display": "'Fredoka','Baloo 2','Poppins',sans-serif",
                  "body": "'Poppins','Nunito','Helvetica Neue',sans-serif"},
        "art_style": ("cheerful hand-painted motifs, warm friendly palette, rounded "
                      "shapes, playful but tasteful, plenty of clear space for text"),
        "type_prompt": ("a rounded, chunky, friendly display title (Fredoka / Baloo feel), "
                        "with a rounded sans-serif body"),
        "frame_prompt": ("cheerful hand-painted rounded shapes and motifs as a playful border, "
                         "bright and warm, NOT delicate floral watercolor"),
        "art_frame": "border",
    },
    "retro": {
        "label": "Retro / groovy (fun prints, quotes, party)",
        "palette": {"bg": "#F7EAD6", "ink": "#3A2A1E", "ink_soft": "#7A5C43",
                    "accent": "#C25B34", "accent2": "#4E6B52", "rule": "#D8B98E",
                    "gold": "#C25B34"},
        "fonts": {"display": "'Poppins','Archivo','Jost',sans-serif",
                  "body": "'Jost','Poppins','Helvetica Neue',sans-serif"},
        "art_style": ("70s-inspired warm retro shapes and gradients-free flat forms, "
                      "ochre rust and avocado tones on cream, bold but clean"),
        "type_prompt": ("a bold geometric 70s-retro display title, tight and characterful, "
                        "all sans-serif"),
        "frame_prompt": ("flat 70s retro forms (arches, rainbows, simple sun and wave shapes) in "
                         "ochre, rust and avocado, and a bold color band, NO delicate florals"),
        "art_frame": "band",
    },
}
# The FALLBACK when research/art-director can't run must NOT be the reflex-reject lane
# (cream + Cormorant/Playfair). A clean neutral sans base is the safe default.
DEFAULT_AESTHETIC = "modern_minimal"


def aesthetic(name: str | None) -> dict:
    return AESTHETICS.get(name or DEFAULT_AESTHETIC, AESTHETICS[DEFAULT_AESTHETIC])


# --- Canva line v3: full-design IMAGE -> Canva Magic Layers -> editable -------
# The winning approach (validated 2026-07-05). The image model renders the WHOLE
# finished design; the owner runs Canva Magic Layers to make it editable. Magic
# Layers converts FLAT, high-contrast, distinct-element art best and struggles with
# dense/small text, so every generated design must obey MAGIC_LAYERS_RULES (baked
# into the image prompt). The old HTML layout path (render.py/art.py) is retired.
POSTER_W, POSTER_H = 1024, 1536       # 2:3 portrait (the image model's actual output ratio)
POSTER_SIZE = f"{POSTER_W}x{POSTER_H}"
# Storefront identity comes from .env (SHOP_NAME / SHOP_CONTACT_EMAIL).
CONTACT_EMAIL = _settings.shop_contact_email
BRAND_NAME = _settings.shop_name

MAGIC_LAYERS_RULES = """DESIGN FOR CANVA MAGIC LAYERS (so it converts cleanly to editable layers):
- Flat, illustrated, stylized look (watercolor / flat vector). NEVER photo-realistic.
- High contrast: ALL body and label text is the DARK ink color on a light ground (>= 4.5:1).
  Accent colors (reds, sage, terracotta, etc.) are for LARGE display headings only, never for
  small body or label text, and never a light color on a light ground.
- LARGE, well-spaced text. No dense paragraphs, no tiny fonts (Magic Layers drops or
  blurs small/dense characters). Short lines, few words per line.
- Distinct, well-separated elements with clear boundaries (icons in their own circles,
  clearly divided sections) so the AI can split them into layers.
- FULL BLEED: the background color fills ALL FOUR EDGES. No white margin or border
  around the artwork, no drop shadow behind the page.
- ONE SINGLE PAGE ONLY: render THIS one usable artifact. NEVER a grid, collage, contact
  sheet, thumbnail index, "what's inside" overview, or several pages / a booklet spread
  tiled together. That is a listing photo, not the buyer's page.
- Portrait, correctly spelled English, elegant and balanced."""


# Photo-centric products (funeral/memorial programs, milestone & kids' birthday invitations, birth/
# graduation announcements) are built AROUND a photo of the person. The design must render a clear,
# editable PHOTO PLACEHOLDER so the buyer drops in their own — a template with no photo slot is
# unusable. Injected by poster.build_prompt only when a page is flagged `needs_photo`.
PHOTO_PLACEHOLDER_RULE = (
    "\nPHOTO PLACEHOLDER (REQUIRED, the focal point): build the page around ONE large, prominent "
    "framed PORTRAIT PHOTO — a cleanly bordered rectangle or soft-arch/oval frame sized for a "
    "portrait, holding a simple, softly-rendered GENERIC placeholder portrait (a tasteful neutral "
    "silhouette or stand-in, NEVER a real, named or identifiable person). It must clearly read as a "
    "photo the buyer will swap for their own, so Canva Magic Layers converts it into an editable, "
    "replaceable image element. Leave clean space for it; do not crop it to the edge behind text."
)


# --- Type scale (px) --- clear >=1.25 steps for real hierarchy ---------------
TYPE = {
    "hero": 54, "statement": 88, "title": 34, "section": 22,
    "lead": 18, "body": 15, "label": 12, "small": 12,
}
# --- Spacing scale (px) ------------------------------------------------------
SPACE = {"xs": 8, "sm": 12, "md": 20, "lg": 32, "xl": 52, "xxl": 84}

# Craft rules — embedded in the architect's LLM prompt and enforced by lint().
CRAFT_RULES = """CRAFT RULES (non-negotiable):
- Real type hierarchy: display (serif) for the hero/title, sans for body; clear size
  steps (hero >> section >> body >> label). Never a flat scale.
- Body/label contrast >= 4.5:1 against the background. No pale gray body text.
- NO em dashes or " -- ". Use colons, periods, commas, or parentheses.
- Labels are written in LITERAL uppercase in the markup with lang="en"; never CSS
  text-transform:uppercase (it turns "i" into "İ" under a Turkish locale).
- Background art is shown with object-fit:contain on a page bg matched to the art's
  cream, never cover (which crops). The art must leave a clean, empty zone for text.
- Generous, rhythmic spacing; no floating, ungrouped blocks; cards are a last resort.
- Every promise is honest: only claim "editable/Canva" because a real template ships."""


_EM_DASH = re.compile(r"[—–]|\s--\s")


def lint(doc: str) -> list[str]:
    """Return craft violations in a generated template (empty list = clean)."""
    v: list[str] = []
    if _EM_DASH.search(doc):
        v.append("em/en dash present (use colon/period/comma)")
    if "text-transform" in doc:
        v.append("CSS text-transform used (write literal uppercase + lang=en)")
    if re.search(r"object-fit\s*:\s*cover", doc):
        v.append("object-fit:cover crops the art (use contain)")
    if 'lang="en"' not in doc:
        v.append('missing lang="en" (Turkish-locale casing bug risk)')
    if 'data-document-role="page"' not in doc:
        v.append("no data-document-role=page element (Canva import needs at least one)")
    return v
