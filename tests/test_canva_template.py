"""Canva-editable template line — build_html + copy (no network)."""
from etsy_engine.generate import canva_template as ct


def test_build_html_has_craft_and_spec_content():
    spec = ct.CanvaSpec()
    doc = ct.build_html(spec, "https://example.com/arch.png")
    # spec content rendered
    assert "Welcome" in doc
    assert "YOUR STAY" in doc
    assert "WI-FI" in doc and "LOCAL FAVORITES" in doc
    assert "Network: YourNetwork" in doc
    assert "https://example.com/arch.png" in doc
    # craft: fonts (non-reflex-reject serif), contain-fit, matched cream, english lang
    assert "Bodoni Moda" in doc and "Jost" in doc
    assert "object-fit:contain" in doc
    assert ct.PAGE_CREAM in doc
    assert 'lang="en"' in doc
    assert "data-document-role=\"page\"" in doc


def test_no_em_dashes_even_if_spec_has_them():
    spec = ct.CanvaSpec(
        title="Welcome",
        note=["A warm welcome — enjoy your stay"],
        sections=[ct.InfoSection("WI-FI", ["Network — MyNet"])],
        footer_lines=["Call us -- anytime"],
    )
    doc = ct.build_html(spec, "https://example.com/a.png")
    assert "—" not in doc  # em dash
    assert "–" not in doc  # en dash
    assert " -- " not in doc


def test_labels_are_literal_uppercase_no_text_transform():
    # avoids the Turkish-locale i->İ casing bug: uppercase in the markup, not via CSS
    doc = ct.build_html(ct.CanvaSpec(), "https://example.com/a.png")
    assert "text-transform" not in doc
    assert "WI-FI" in doc  # literal ASCII I, not İ


def test_listing_copy_is_honest_and_complete():
    c = ct.listing_copy("Airbnb Guest Welcome")
    assert len(c["tags"]) == 13
    assert "editable" in c["title"].lower()
    assert "canva" in c["description"].lower()
    assert "editable" in " ".join(c["tags"]).lower()


def test_listing_title_no_double_editable():
    """The architect sometimes puts 'editable' in product_kind; the title must not double it."""
    c = ct.listing_copy("editable christmas gift tag set", niche="christmas gift tags")
    assert c["title"].lower().count("editable") == 1 and c["title"].startswith("Editable ")
    # a kind without 'editable' still gets the prefix
    assert ct.listing_copy("Wedding Welcome Sign")["title"].startswith("Editable Wedding")


def test_listing_copy_tags_respect_etsy_20_char_limit():
    """Etsy rejects any tag > 20 chars. Regression: a wedding draft 400'd on /tags."""
    cases = [("Wedding Welcome Sign Set", "wedding welcome sign"),
             ("World Travel Checklist Tracker Printable Set",
              "world travel checklist tracker printable"),  # long niche must be dropped, not sent
             ("Welcome Template", "")]
    for kind, niche in cases:
        c = ct.listing_copy(kind, niche=niche)
        assert c["tags"], (kind, niche)
        assert len(c["tags"]) <= 13
        too_long = [t for t in c["tags"] if len(t) > 20]
        assert not too_long, too_long
        assert len(c["tags"]) == len({t.lower() for t in c["tags"]}), "tags must be de-duped"


def test_default_spec_uses_colons_not_em_dashes():
    doc = ct.build_html(ct.CanvaSpec(), "https://example.com/a.png")
    assert "Network: YourNetwork" in doc
    assert "Check-in: from 3 PM" in doc
