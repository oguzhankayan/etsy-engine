"""No redundant pages, PRODUCT-AGNOSTIC. The owner's point: a set must never tell the same thing
twice in a new layout, and this must hold for EVERY product, not be a funeral-specific patch.
architect.normalize now (1) caps 'statement'/quote pages to one, (2) drops any page whose function
(its `use` + title) near-duplicates an earlier page's, (3) keeps the deceased's photo off quote pages.
"""
from etsy_engine.canva import architect


def test_duplicate_function_pages_dropped_wedding():
    """A wedding set with two identical welcome-sign pages keeps one; distinct pieces survive."""
    spec = architect.normalize({"product_kind": "wedding welcome sign set", "pages": [
        {"layout": "welcome", "use": "hang the welcome sign", "content": {"title": "Welcome to Our Wedding"}},
        {"layout": "welcome", "use": "hang the welcome sign", "content": {"title": "Welcome to Our Wedding"}},
        {"layout": "timeline", "use": "follow the day-of timeline", "content": {"title": "Order of Events"}},
        {"layout": "sheet", "use": "find your table seat", "content": {"title": "Seating Chart"}},
    ]})
    uses = [p["use"] for p in spec["pages"]]
    assert uses.count("hang the welcome sign") == 1          # the duplicate welcome sign is dropped
    assert len(spec["pages"]) == 3                            # the 3 genuinely distinct pieces survive


def test_distinct_pages_are_never_over_dropped():
    """Genuinely different pieces (different job each) must all survive."""
    spec = architect.normalize({"product_kind": "baby shower party kit", "pages": [
        {"layout": "invitation", "use": "mail the invitation", "content": {"title": "You Are Invited"}},
        {"layout": "sheet", "use": "play the shower games", "content": {"title": "Shower Games"}},
        {"layout": "welcome", "use": "hang the welcome sign", "content": {"title": "Welcome Baby"}},
        {"layout": "checklist", "use": "tick off the gift log", "content": {"title": "Gift Log"}},
    ]})
    assert len(spec["pages"]) == 4                            # all four distinct pieces kept


def test_statement_pages_capped_to_one_any_product():
    spec = architect.normalize({"product_kind": "funeral program", "pages": [
        {"layout": "welcome", "use": "cover", "needs_photo": True, "content": {"title": "In Loving Memory"}},
        {"layout": "sheet", "use": "follow the order of service", "content": {"title": "Order of Service"}},
        {"layout": "statement", "use": "read the tribute quote", "needs_photo": True,
         "content": {"statement": "Her love was quiet and endless"}},
        {"layout": "statement", "use": "read another quote", "needs_photo": True,
         "content": {"statement": "Forever in our hearts"}},
    ]})
    assert [p["layout"] for p in spec["pages"]].count("statement") == 1   # extra quote page dropped
    stmt = next(p for p in spec["pages"] if p["layout"] == "statement")
    assert not stmt["content"].get("needs_photo")            # portrait is the cover's job, not the quote's
    assert spec["pages"][0]["content"].get("needs_photo")    # cover keeps its photo placeholder
