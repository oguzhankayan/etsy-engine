"""Canva auto-detection: personalizable trends route to the Canva line; pure-print stays PDF."""
from etsy_engine.canva import detect


def test_detects_personalizable_niches():
    for term in ["Airbnb Welcome Sign", "wedding seating chart", "baby shower invitation",
                 "classroom welcome poster", "guest house guide", "birthday party menu"]:
        s = detect.canva_suitability(term)
        assert s and s["suitable"], term


def test_excludes_pure_print_products():
    for term in ["dinosaur coloring pages", "floral clipart bundle", "svg cut files",
                 "seamless pattern paper", "sublimation png bundle",
                 "baby shower games", "printable word search", "party bingo game"]:
        assert detect.canva_suitability(term) is None, term


def test_returns_kind_score_reason():
    s = detect.canva_suitability("Airbnb guest welcome sign with wifi")
    assert s["kind"] == "welcome_sign"
    assert s["score"] >= 1.0 and s["reason"]


def test_fill_in_products_stay_pdf():
    """USE-personalized (buyer ticks/fills, not swap-my-name) -> PDF line, never Canva.

    Regression: 'world checklist tracker printable' was mis-routed to Canva at score 2.0
    ('checklist' + 'tracker') and produced a set no buyer would open Canva to tick off.
    """
    for term in ["world checklist tracker printable", "habit tracker printable",
                 "weekly meal planner", "budget planner", "reading log printable",
                 "daily to do list", "chore chart for kids", "travel bucket list",
                 "teacher questionnaire printable", "all about dad fill in the blank"]:
        assert detect.canva_suitability(term) is None, term


def test_fill_in_word_overrides_personalize_niche():
    """A fill-in/tick-off product routes to PDF even inside a real Canva niche."""
    for term in ["wedding planner printable", "baby shower checklist",
                 "classroom behavior tracker"]:
        assert detect.canva_suitability(term) is None, term


def test_personalize_niches_with_list_or_chart_still_canva():
    """The fill-in excludes must NOT catch identity/event templates that say list/chart."""
    for term in ["wedding seating chart", "salon price list", "birthday party menu"]:
        s = detect.canva_suitability(term)
        assert s and s["suitable"], term


def test_plural_terms_route_like_singular():
    """Etsy terms are usually plural; a plural product must route like its singular signal."""
    for term in ["wedding welcome signs", "baby shower invitations", "graduation announcements",
                 "wedding seating charts"]:
        s = detect.canva_suitability(term)
        assert s and s["suitable"], term


def test_cut_apart_sheets_route_off_canva():
    """FORM axis: a printed sheet the buyer cuts into many small items is not a fit for a
    one-artifact-per-page renderer, so it leaves the Canva line however personalizable it is.

    Regression: 'christmas gift tags' rendered as one big tag + a message table, never a real
    cuttable tag sheet — the pipeline can't lay out a multi-up grid.
    """
    for term in ["christmas gift tags", "wedding favor tags", "wedding place cards",
                 "escort cards template", "table numbers 1-30", "cupcake toppers printable",
                 "business card template", "planner stickers", "water bottle labels",
                 "envelope seals", "wedding bookmarks", "seating chart cards"]:
        assert detect.canva_suitability(term) is None, term


def test_variety_spans_single_focus_categories():
    """The line must range across the whole single-focus editable market, not a few welcome-signs.
    Each of these distinct product types routes to the Canva line with the expected kind."""
    cases = {
        "graduation announcement template": "announcement",
        "gift certificate template": "certificate",
        "cocktail drink menu template": "menu_program",
        "editable christmas card": "greeting_card",
        "wedding seating chart": "seating_chart",
        "salon price list sign": "sign_business",
    }
    for term, kind in cases.items():
        s = detect.canva_suitability(term)
        assert s and s["suitable"], term
        assert s["kind"] == kind, (term, s["kind"])


def test_scan_diversifies_across_kinds(monkeypatch):
    """scan() must spread its shortlist across product kinds, not return N of the same niche."""
    from etsy_engine import db as dbmod
    # five welcome-signs would dominate a naive sort; two other kinds should still surface at the top
    opps = [{"term": f"airbnb welcome sign {i}", "rank_score": 100 - i} for i in range(5)]
    opps += [{"term": "wedding seating chart", "rank_score": 40},
             {"term": "graduation announcement", "rank_score": 30}]
    monkeypatch.setattr(dbmod, "top_opportunities", lambda limit=200: opps)
    out = detect.scan(per_kind=2)
    kinds_top3 = {h["kind"] for h in out[:3]}
    assert len(kinds_top3) == 3, [h["term"] for h in out]          # top of list is diverse
    assert sum(1 for h in out if h["kind"] == "welcome_sign") == 2  # capped per kind


def test_canva_queue_is_db_backed_route_and_drain(tmp_path, monkeypatch):
    """Phase 5: the Canva queue IS the DB (no parallel JSONL). architect routes a trend to a
    'routed' product; producing it (save_canva_product with that product_id) flips it to 'planned',
    draining the queue. Routing is deduped by trend."""
    from etsy_engine import db
    from etsy_engine.config import settings
    from etsy_engine.models import Trend
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "t.db"))
    db.init_db()
    tid = db.upsert_trend(Trend(source="test", term="wedding welcome sign"))
    pid = db.route_to_canva(tid, "wedding welcome sign")
    assert db.route_to_canva(tid, "wedding welcome sign") == pid       # deduped by trend
    pending = db.pending_canva_products()
    assert len(pending) == 1 and pending[0]["term"] == "wedding welcome sign"
    db.save_canva_product("wedding welcome sign", "welcome sign",  # produce -> fills + drains
                          [{"name": "Sign", "use": "display"}],
                          {"title": "t", "tags": [], "description": "", "alt_texts": []},
                          product_id=pid)
    assert db.pending_canva_products() == []
