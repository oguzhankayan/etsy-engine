"""Tests for seo/writer.py tag + title guarantees (the findability levers)."""
from __future__ import annotations

from etsy_engine.seo.writer import (MIN_LONG_TAIL, TAG_MAX_COUNT, TITLE_MAX,
                                     build_tags, ensure_keyword_in_title)


def test_primary_keyword_is_guaranteed_a_tag_slot():
    """The single best search phrase must land in the 13, even when many broad single-word winners
    would otherwise fill every slot first (Etsy's biggest exact-match lever)."""
    kw = {"primary_keyword": "teddy bear reveal",
          "long_tail": ["boy or girl card", "baby reveal set"]}
    real = ["party", "baby", "invite", "decor", "reveal", "card", "sign",
            "tag", "print", "kids", "shower", "sign", "wedding"]  # all broad single words
    tags = build_tags(kw, real_tags=real)
    assert "teddy bear reveal" in tags
    assert len(tags) <= TAG_MAX_COUNT
    assert all(len(t) <= 20 for t in tags)


def test_long_tail_floor_is_enforced():
    """At least MIN_LONG_TAIL slots go to multi-word long-tail when that many candidates exist,
    instead of being crowded out by single-word winners."""
    kw = {"long_tail": ["teddy bear invite", "boy or girl card", "baby reveal set",
                        "pink blue invite", "woodland baby shower", "storybook bear party",
                        "cub reveal invite", "he or she card"],
          "styles": ["cute", "pastel"]}
    real = ["wedding", "party", "baby", "invite", "decor", "shower", "reveal", "card"]
    tags = build_tags(kw, real_tags=real)
    assert sum(1 for t in tags if " " in t) >= MIN_LONG_TAIL


def test_redundant_single_word_yields_to_the_phrase_that_contains_it():
    """'invite' is redundant next to 'teddy bear invite' (Etsy matches the words in the phrase); the
    specific long-tail phrase is kept and the broad single word dropped, not the reverse."""
    kw = {"long_tail": ["teddy bear invite"]}
    tags = build_tags(kw, real_tags=["invite"])
    assert "teddy bear invite" in tags
    assert "invite" not in tags


def test_ensure_keyword_in_title_front_loads_when_missing():
    assert ensure_keyword_in_title("Storybook Bear Suite | Cute", "gender reveal invitation") == (
        "gender reveal invitation | Storybook Bear Suite | Cute")


def test_ensure_keyword_in_title_is_a_noop_when_present():
    t = "Gender Reveal Invitation | Teddy Bear"
    assert ensure_keyword_in_title(t, "gender reveal invitation") == t  # case-insensitive match


def test_ensure_keyword_in_title_clamps_to_max_len_keeping_the_keyword():
    out = ensure_keyword_in_title("word " * 60, "gender reveal invitation")
    assert len(out) <= TITLE_MAX
    assert out.lower().startswith("gender reveal invitation")
