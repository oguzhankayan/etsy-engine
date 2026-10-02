"""Quality Controller (Agent 8). Vision-based check on generated printables.

Claude looks at the image and rates it on the spec's QC dimensions: spelling/text
correctness, print quality, alignment, color harmony. Used both to PASS/FAIL an
asset and to PICK THE BEST among several generated variations.

If no Anthropic key is set, QC is skipped (status='skipped', neutral score) so
generation still works — the pick-best just falls back to the first variation.
"""
from __future__ import annotations


from ..config import settings
from ..llm import vision_json

PASS_THRESHOLD = 0.7

# QC vision only judges text/layout/color, not print resolution — so we send a
# downscaled JPEG. Keeps us under Anthropic's 10 MB image limit (a full 2k PNG from
# large renders can exceed it otherwise) AND cuts vision token cost.
QC_MAX_EDGE = 1400


def _prep_for_qc(image_bytes: bytes) -> tuple[bytes, str]:
    """Downscale + JPEG-compress the image for the vision call. Falls back to the
    raw bytes if PIL isn't available or the image can't be opened."""
    try:
        import io

        from PIL import Image
        im = Image.open(io.BytesIO(image_bytes))
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        im.thumbnail((QC_MAX_EDGE, QC_MAX_EDGE))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        return image_bytes, "image/jpeg"

SYSTEM = """You are a strict print-quality controller for Etsy printable products.
Look at the image and evaluate it. Respond with JSON only:
{"text_correct": 0.0-1.0,   // is all text spelled correctly and legible
 "print_quality": 0.0-1.0,  // crisp, high-res, print-ready
 "alignment": 0.0-1.0,      // elements aligned, balanced margins
 "color_harmony": 0.0-1.0,  // palette is cohesive and pleasant
 "is_usable_artifact": 0.0-1.0, // the page IS the usable product itself (form
       // with EMPTY write-in fields / cut-out pieces at real scale / finished
       // art) — NOT an advertisement, infographic, size chart or poster ABOUT
       // the product. For cut-out/fold templates: dieline geometry must be
       // plausibly assemblable (symmetric flaps, sane tabs). ALSO score low if
       // elements are too SMALL to use when printed (a bingo board must fill
       // a page/half-page; a grid of 12 mini-boards on one sheet is junk).
 "fields_empty": 0.0-1.0,   // every hand-write field is BLANK: no printed
       // '$0.00', sample entries, or '[Name]'/'[###]' placeholders. Score 1.0
       // if there are no write-in fields at all.
 "score": 0.0-1.0,          // overall; text_correct, is_usable_artifact and
       // fields_empty are HARD dimensions — any of them below 0.5 caps the
       // overall score at 0.4
 "notes": "short reason, especially misspellings, ad-instead-of-artifact,
       pre-filled fields, or broken dieline geometry"}"""


THUMB_PASS_THRESHOLD = 0.6
THUMB_EDGE = 280  # ~Etsy search-grid thumbnail size: judge what buyers SEE

THUMB_SYSTEM = """You are an Etsy conversion expert. You are shown a listing's
HERO image at the tiny size it actually renders in Etsy SEARCH RESULTS. Judge
whether a scrolling buyer would stop on it. Respond with JSON only:
{"legible_small": 0.0-1.0,   // any title/badge text still readable at this size
 "contrast_pop": 0.0-1.0,    // stands out against a white page of competitors
 "subject_clarity": 0.0-1.0, // instantly obvious WHAT the product is
 "click_appeal": 0.0-1.0,    // overall scroll-stopping quality
 "score": 0.0-1.0,           // weighted overall
 "notes": "short reason + the single highest-impact improvement"}"""


def assess_thumbnail(image_bytes: bytes, niche_style: str | None = None) -> dict:
    """Score a hero mockup AS A SEARCH THUMBNAIL (the click-through gate).
    Returns {status, score, notes}; never raises — failures => skipped.

    When `niche_style` (the niche's winning look, from canva.research) is given, pop is judged
    against the REAL competitive grid ('does this stand out FROM that look?'), not in the abstract."""
    if not settings.anthropic_api_key:
        return {"status": "skipped", "score": 0.5, "notes": "no ANTHROPIC_API_KEY"}
    try:
        import io

        from PIL import Image
        im = Image.open(io.BytesIO(image_bytes))
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        im.thumbnail((THUMB_EDGE, THUMB_EDGE))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
        small = buf.getvalue()
    except Exception:
        small, _ = _prep_for_qc(image_bytes)
    user = "Judge this search thumbnail."
    if niche_style:
        user += (f" Its competitors in this niche all look like: {niche_style}. Score contrast_pop by "
                 "whether THIS thumbnail would stand out FROM those competitors in the search grid, "
                 "not just against a white page.")
    try:
        r = vision_json(THUMB_SYSTEM, user, small)
    except Exception as e:
        return {"status": "skipped", "score": 0.5, "notes": f"thumb QC error: {e}"}
    score = float(r.get("score", 0.0))
    return {
        "status": "passed" if score >= THUMB_PASS_THRESHOLD else "failed",
        "score": score,
        "notes": r.get("notes", ""),
    }


TEXT_QC_PASS = 0.6  # lenient: only regen on GENUINELY broken text (vision QC is noisy; save credits)

TEXT_QC_SYSTEM = """You verify the TEXT in a finished, designed Etsy image (e.g. a Canva-style
template page). You are given the EXACT text strings the design should contain. Judge ONLY whether
that text rendered correctly. Placeholder names/dates/times (e.g. 'Emma & James', 'Oct 12') are
INTENDED and totally fine. Do NOT judge style, layout, or taste here.
Respond with JSON only:
{"all_present": 0.0-1.0,     // are the expected strings actually there, and complete
 "spelled_correctly": 0.0-1.0, // no misspellings
 "not_garbled": 0.0-1.0,      // no nonsense/duplicated/melted letters or invented words
 "legible_contrast": 0.0-1.0, // is every text run readable, i.e. dark-enough on its background (low = pale/low-contrast body or label text)
 "score": 0.0-1.0,            // overall; low if expected text is missing, misspelled, garbled, OR too low-contrast to read
 "notes": "list the specific missing / misspelled / garbled / low-contrast words, or 'clean'"}"""


def assess_text(image_bytes: bytes, expected_texts: list[str]) -> dict:
    """Verify the rendered TEXT matches the strings the design was asked to show (catches the
    image model's occasional garble/misspelling before Magic Layers bakes it in). Returns
    {status, score, notes}; never raises. Skipped (neutral) with no key or no expected text."""
    exp = " | ".join(t for t in (expected_texts or []) if str(t).strip())[:1600]
    if not settings.anthropic_api_key or not exp:
        return {"status": "skipped", "score": 0.7, "notes": "no key / no expected text"}
    qc_bytes, qc_media = _prep_for_qc(image_bytes)
    try:
        r = vision_json(TEXT_QC_SYSTEM,
                        f"The design should contain exactly these text strings: {exp}",
                        qc_bytes, media_type=qc_media)
    except Exception as e:  # noqa: BLE001
        return {"status": "skipped", "score": 0.7, "notes": f"text QC error: {e}"}
    score = float(r.get("score", 0.0))
    contrast = float(r.get("legible_contrast", 1.0))
    # A page whose text is too low-contrast to read FAILS even if the words are spelled right,
    # so the one gated regen fires (enforces contrast beyond the prompt-level rule).
    failed = score < TEXT_QC_PASS or contrast < 0.5
    return {"status": "failed" if failed else "passed", "score": score,
            "notes": r.get("notes", "")}


IP_SYSTEM = """You are a trademark/IP compliance checker for an Etsy shop that sells ONLY original,
logo-free designs. Look at this listing image and decide if it VISIBLY contains real, protected
intellectual property that would infringe someone's rights:
- a real company/brand LOGO or wordmark (e.g. a Nike swoosh, the Disney script),
- a recognizable trademarked/copyrighted CHARACTER (e.g. Mickey, Pikachu, Elsa, Bluey),
- a real sports TEAM crest/badge or league emblem,
- a real, identifiable CELEBRITY likeness,
- an official EVENT emblem, trophy, or mascot (e.g. the FIFA World Cup trophy, the Olympic rings).
Generic ORIGINAL artwork that merely evokes a theme (a plain soccer ball, a generic teddy bear, a
country flag, plain florals) is FINE and NOT infringing. Only flag a REAL protected mark you can
actually see. Respond with JSON only:
{"has_ip": true/false, "what": "the specific real mark you see, or ''", "confidence": 0.0-1.0}"""


def assess_ip_safety(image_bytes: bytes, context: str = "") -> dict:
    """Vision check: did the AI image accidentally render a REAL logo / trademarked character / team
    crest / celebrity / event emblem? Every OTHER IP gate is term-level and pre-generation; the shop's
    whole ban-risk lives in the artwork, and this is the only check on the actual pixels.

    Returns {status: 'flagged'|'clean'|'skipped', flagged, what, confidence, notes}; never raises.
    Fail-OPEN (status='skipped') with no key / on error, so it never blocks generation on
    infrastructure — it only ever SURFACES a positive detection for the owner's draft review."""
    if not settings.anthropic_api_key:
        return {"status": "skipped", "flagged": False, "notes": "no ANTHROPIC_API_KEY"}
    qc_bytes, qc_media = _prep_for_qc(image_bytes)
    user = "Check this Etsy listing image for real protected IP."
    if context:
        user += f" Product context: {context}."
    try:
        r = vision_json(IP_SYSTEM, user, qc_bytes, media_type=qc_media)
    except Exception as e:  # noqa: BLE001
        return {"status": "skipped", "flagged": False, "notes": f"IP QC error: {e}"}
    # Require reasonable confidence so a generic bear/ball doesn't trip it (vision is noisy).
    flagged = bool(r.get("has_ip")) and float(r.get("confidence", 0.0)) >= 0.6
    what = str(r.get("what", "") or "")
    return {"status": "flagged" if flagged else "clean", "flagged": flagged, "what": what,
            "confidence": float(r.get("confidence", 0.0)), "notes": what or "clean"}


def assess(image_bytes: bytes, item_name: str, item_spec: str) -> dict:
    """Return {status, score, notes}. Never raises — failures => skipped."""
    if not settings.anthropic_api_key:
        return {"status": "skipped", "score": 0.5, "notes": "no ANTHROPIC_API_KEY"}
    user = (
        f"This is meant to be a printable '{item_name}'. "
        f"Intended purpose: {item_spec}. Evaluate it."
    )
    qc_bytes, qc_media = _prep_for_qc(image_bytes)
    try:
        r = vision_json(SYSTEM, user, qc_bytes, media_type=qc_media)
    except Exception as e:
        return {"status": "skipped", "score": 0.5, "notes": f"QC error: {e}"}
    score = float(r.get("score", 0.0))
    return {
        "status": "passed" if score >= PASS_THRESHOLD else "failed",
        "score": score,
        "notes": r.get("notes", ""),
    }
