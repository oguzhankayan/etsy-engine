"""In-flight theme dedup: the architect must not queue a near-duplicate of a product already in
flight (planned/routed) but not yet in the produced-history. The reported gap was "funeral program"
(routed run 1) then "funeral program template" (run 2) queued as two separate Canva products —
identical theme {funeral, program} once the format words are stripped.
"""
from etsy_engine import history


def test_format_variants_collide_with_the_base_theme():
    for variant in ("funeral program template", "editable funeral program",
                    "funeral program printable", "customizable funeral program"):
        assert history.collides_with_any(variant, ["funeral program"]), variant
    assert history.collides_with_any("funeral program", ["funeral program template"])


def test_distinct_themes_do_not_collide():
    assert not history.collides_with_any("wedding welcome sign", ["funeral program"])
    assert not history.collides_with_any("baby shower invitation", ["funeral program", "world cup"])


def test_empty_inputs_are_safe():
    assert not history.collides_with_any("funeral program", [])
    assert not history.collides_with_any("", ["funeral program"])


def test_format_words_are_stripped_from_theme():
    assert history.theme_tokens("funeral program template") == history.theme_tokens("funeral program")
    assert history.theme_tokens("editable funeral program") == history.theme_tokens("funeral program")
