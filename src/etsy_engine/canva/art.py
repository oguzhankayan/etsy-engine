"""Clean-zone background art per aesthetic + frame kind. The art ALWAYS leaves an
empty region for text (the single biggest quality lever) and never bakes in words.
Different kinds give a set cover-vs-interior variety instead of one repeated frame.
"""
from __future__ import annotations

ART_SIZE = "1536x2048"

_KIND = {
    "arch": ("botanicals trace a tall arch OUTLINE up the two side margins and meet in a light "
             "garland across the top along a thin gold line, like a doorway framed with foliage; "
             "the ENTIRE arch interior stays completely empty, clean cream"),
    "garland": ("a graceful botanical garland runs ACROSS THE VERY TOP of the page and a lighter, "
                "smaller matching sprig ACROSS THE VERY BOTTOM; the entire MIDDLE of the page "
                "(the central two thirds, top to bottom) stays completely empty, clean cream"),
    "corner": ("a small delicate arrangement in the TOP-LEFT and BOTTOM-RIGHT corners only; the "
               "whole center stays empty, clean cream"),
}


def art_prompt(aes: dict, kind: str = "arch") -> str | None:
    """Build the clean-zone art prompt for an aesthetic + frame kind, or None."""
    instr = _KIND.get(kind or aes.get("art_frame", "arch"))
    if not instr:
        return None
    return (
        "An elegant printable background for a premium editable template, portrait A4. "
        f"Style: {aes['art_style']}. Composition: {instr}. Refined, editorial, lots of "
        "negative space. ABSOLUTELY NO text, NO words, NO letters, NO numbers anywhere."
    )
