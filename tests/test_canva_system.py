"""General Canva system — design/render/architect (no network)."""
from etsy_engine.canva import architect as A
from etsy_engine.canva import design as D
from etsy_engine.canva import render as R


def test_render_multipage_and_lint_clean():
    pages = [
        {"layout": "welcome", "content": {
            "title": "Welcome", "note": ["Make yourself at home"], "section_header": "Your Stay",
            "sections": [{"label": "WI-FI", "lines": ["Network: X"]}],
            "footer_title": "Enjoy", "footer_lines": ["See you soon"]}},
        {"layout": "sheet", "content": {
            "title": "House Guide", "intro": ["Everything you need"],
            "groups": [{"header": "Rules", "items": ["No smoking", "Shoes off"]}], "checklist": True}},
        {"layout": "statement", "content": {"statement": "Home Sweet Home", "sub": "Est 2026"}},
    ]
    doc = R.render_pages(pages, "botanical", "https://example.com/a.png")
    assert doc.count('data-document-role="page"') == 3
    assert D.lint(doc) == []
    assert "Home Sweet Home" in doc and "House Guide" in doc and "WI-FI" in doc


def test_every_aesthetic_renders_clean():
    for name, a in D.AESTHETICS.items():
        doc = R.render_pages([{"layout": "statement", "content": {"statement": "Hi"}}], name, None)
        assert a["palette"]["bg"] in doc
        assert D.lint(doc) == [], f"{name} failed lint"


def test_lint_catches_violations():
    bad = ('<div data-document-role="page">A — B '
           '<img style="object-fit:cover"><span style="text-transform:uppercase">x</span></div>')
    v = D.lint(bad)
    assert any("dash" in x for x in v)
    assert any("cover" in x for x in v)
    assert any("text-transform" in x for x in v)
    assert any("lang" in x for x in v)


def test_render_strips_em_dashes_from_content():
    doc = R.render_pages([{"layout": "sheet", "content": {
        "title": "A — B", "groups": [{"header": "H", "items": ["x -- y"]}]}}], "modern_minimal", None)
    assert "—" not in doc and " -- " not in doc


def test_architect_normalize_defaults_and_validates():
    n0 = A.normalize({})
    assert n0["aesthetic"] == D.DEFAULT_AESTHETIC
    assert n0["pages"][0]["layout"] == "sheet"
    n1 = A.normalize({"aesthetic": "nope", "pages": [{"layout": "bogus", "content": {"title": "T"}}]})
    assert n1["aesthetic"] == D.DEFAULT_AESTHETIC
    assert n1["pages"][0]["layout"] == "sheet"


def test_backward_compat_shim_still_works():
    from etsy_engine.generate import canva_template as ct
    doc = ct.build_html(ct.CanvaSpec(), "https://example.com/a.png")
    assert "Welcome" in doc and "WI-FI" in doc and "object-fit:contain" in doc
    assert D.lint(doc) == []
