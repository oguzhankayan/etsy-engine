"""Canva line v3 (image -> Magic Layers) — prompt rules, delivery PDF, honesty."""
from pathlib import Path

from etsy_engine.canva import copy, delivery, design as D, poster
from etsy_engine.config import settings


def test_poster_prompt_enforces_magic_layers_rules():
    content = {"title": "Welcome to Our Classroom", "note": ["We are so glad you are here"],
               "product_kind": "classroom welcome poster",
               "sections": [{"label": "Kindness", "lines": ["Be gentle"]},
                            {"label": "Curiosity", "lines": ["Ask questions"]}]}
    p = poster.build_prompt(content, "botanical")
    assert "Welcome to Our Classroom" in p          # renders the real title
    assert "FULL BLEED" in p                          # full-bleed rule (owner's white-gap fix)
    assert "photo-realistic" in p.lower()             # the 'never photorealistic' rule
    assert "Kindness" in p and "Curiosity" in p       # items carried into the design
    assert "—" not in p and "–" not in p              # no em/en dash


def test_aesthetics_render_distinctly_not_all_botanical():
    """Regression: build_prompt used to hardcode 'elegant serif' + 'botanical accents' so every
    aesthetic collapsed to the same cream/serif/botanical look. Each aesthetic must now drive
    its own typography + framing + palette."""
    content = {"title": "Monthly Budget", "product_kind": "budget planner"}
    prompts = {a: poster.build_prompt(content, a) for a in D.AESTHETICS}
    # nothing is hardcoded to serif/botanical anymore
    for p in prompts.values():
        assert "elegant serif display title" not in p
        assert "decorative botanical or motif accents framing" not in p
    # modern_minimal is genuinely sans + no florals; botanical is serif + florals
    assert "SANS-SERIF" in prompts["modern_minimal"] and "NO botanical" in prompts["modern_minimal"]
    assert "SERIF" in prompts["botanical"] and "botanical" in prompts["botanical"]
    # each aesthetic yields a distinct prompt, and injects its own palette bg
    assert len(set(prompts.values())) == len(prompts)
    assert D.AESTHETICS["retro"]["palette"]["bg"] in prompts["retro"]


def test_style_brief_steers_the_look():
    """A niche design brief (from canva.research) is injected so we design to what sells."""
    content = {"title": "Hello", "product_kind": "x"}
    brief = "bold neon colors, chunky rounded display font, cartoon dinosaur motifs"
    p = poster.build_prompt(content, "playful", style_brief=brief)
    assert brief in p and "Match what sells in this niche" in p
    assert brief not in poster.build_prompt(content, "playful")  # only when provided


def test_bespoke_direction_overrides_fixed_aesthetic():
    """A per-product art-directed design system (design.art_director) drives the look, so a product
    is NOT locked to one of the 5 presets."""
    direction = {"palette": {"bg": "#0E0E12", "ink": "#F5F5F5", "accent": "#FF3EA5",
                             "accent2": "#28E0C8"}, "art_style": "neon cyberpunk grid glow",
                 "type_prompt": "bold techno sans display", "frame_prompt": "glowing circuit lines"}
    p = poster.build_prompt({"title": "X", "product_kind": "gamer poster"},
                            "botanical", direction=direction)
    assert "neon cyberpunk grid glow" in p and "#FF3EA5" in p and "glowing circuit lines" in p
    assert "watercolor botanicals" not in p  # the fixed botanical preset did NOT leak through


def test_art_direction_shape_and_soft_fallback():
    """art_direction returns a poster-ready design system even without an LLM/network (fallback)."""
    from etsy_engine.design import art_director
    fb = D.aesthetic("retro")
    # force the fallback path by making the LLM call raise (no key/offline) via a bogus fallback merge
    out = art_director._normalize_direction({}, fb)          # empty LLM output -> all from fallback
    for key in ("palette", "fonts", "art_style", "type_prompt", "frame_prompt"):
        assert out.get(key)
    for c in ("bg", "ink", "accent", "accent2"):
        assert out["palette"].get(c)


def test_architect_mission_is_universal_usable_artifacts():
    """Root mentality (not per-product patches): the file is ONLY usable artifacts; anything ABOUT
    the product goes in the listing photos. Every page must declare a concrete `use`. No product-
    type carve-outs, no banned-phrase lists."""
    from etsy_engine.canva import architect
    sysp = architect._system()
    assert "what does the buyer physically DO" in sysp      # the single governing test
    assert "LISTING PHOTOS" in sysp and "ABOUT the product" in sysp
    assert '"use"' in sysp                                   # per-page use is required
    # the mentality is universal — no product-type rules baked in
    for carve_out in ("GIFT TAGS", "GUEST BOOK", "PLANNER ="):
        assert carve_out not in sysp
    # normalize carries the declared use through
    spec = architect.normalize({"pages": [{"layout": "welcome", "use": "hang by the door",
                                           "content": {"title": "X"}}]})
    assert spec["pages"][0]["use"] == "hang by the door"


def test_layouts_compose_differently():
    """Structure variety: each layout must render a genuinely different composition, not one
    icon+label+line skeleton (the critique's #1 remaining sameness tell)."""
    from etsy_engine.canva import architect
    briefs = {
        "checklist": poster._content_brief({"title": "X", "items": ["a", "b"]}, "checklist"),
        "timeline": poster._content_brief({"title": "X", "steps": [{"time": "1", "label": "y", "detail": "z"}]}, "timeline"),
        "signin": poster._content_brief({"title": "X", "prompt": "p", "lines": 8}, "signin"),
        "stat": poster._content_brief({"title": "X", "stats": [{"number": "9", "label": "n"}]}, "stat"),
        "two_column": poster._content_brief({"title": "X", "left": {"header": "L", "items": ["a"]}, "right": {"header": "R", "items": ["b"]}}, "two_column"),
    }
    assert "checkbox" in briefs["checklist"]
    assert "RULED" in briefs["signin"] and "EMPTY" in briefs["signin"]
    assert len(set(briefs.values())) == len(briefs)          # all distinct structures
    assert {"checklist", "timeline", "signin", "stat", "two_column", "table"} <= architect.LAYOUTS
    assert "varying them so no two" in architect._system()   # the architect is told to vary layouts


def test_canva_listing_is_theme_and_pieces_aware(monkeypatch):
    """Rich listing (mirrors the PDF SEO writer): theme-forward title, what's-included from the
    real pieces, keyword tags. Honesty is INVERTED vs PDF — editable/canva are kept; only formats
    we don't ship (svg cut files) are denied."""
    from etsy_engine.canva import listing as clist
    fake = {
        "keywords": {"long_tail": ["vineyard wedding invite", "italian wedding set"],
                     "styles": ["wine theme", "botanical"], "recipients": ["bride to be"]},
        "title": "Vineyard Wedding Invitation Suite | Grapevine Botanical | Editable Canva Template",
        "description": "Hand-drawn grapevines on sage and cream.\n\nThis set includes:\n- Invitation",
        "alt_texts": ["hero"], "faq": "Q: How do I edit?\nA: In Canva.",
    }
    monkeypatch.setattr("etsy_engine.canva.listing.complete_json", lambda s, u: fake)
    out = clist.build("wedding invitation suite", "wedding invitation suite",
                      [{"title": "Elena & Marco", "use": "the invitation itself"}],
                      theme={"vibe": "modern vineyard editorial"},
                      market={"top_tags": ["canva template", "svg cut file"]})
    assert out["title"].startswith("Vineyard")                       # theme-forward, not generic
    assert "This set includes" in out["description"] and "FAQ" in out["description"]
    assert "canva template" in out["tags"]                           # honest for Canva -> kept
    assert not any("svg" in t for t in out["tags"])                  # format we don't offer -> dropped
    assert out["tags"] and all(len(t) <= 20 for t in out["tags"]) and len(out["tags"]) <= 13


def test_save_canva_product_is_first_class_db_entity(tmp_path, monkeypatch):
    """Phase 1 (unify lines): a Canva suite persists as a real DB product (format='canva') with
    bundle_items + a listing, the SAME shape the PDF line uses, so the learning loop can see it."""
    from etsy_engine import db
    from etsy_engine.config import settings
    from etsy_engine.models import Product, Trend
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "t.db"))
    db.init_db()

    pid = db.save_canva_product(
        "wedding invitation suite", "vineyard wedding suite",
        [{"name": "Invitation", "use": "print and mail"}, {"name": "RSVP", "use": "guest replies"}],
        {"title": "Vineyard Wedding Suite | Editable Canva Template",
         "tags": ["wedding invite", "canva template"], "description": "A vineyard suite.",
         "alt_texts": ["hero"]})
    with db.connect() as c:
        assert c.execute("SELECT format FROM products WHERE id=?", (pid,)).fetchone()["format"] == "canva"
        assert c.execute("SELECT count(*) n FROM bundle_items WHERE product_id=?",
                         (pid,)).fetchone()["n"] == 2
        assert "Vineyard" in c.execute("SELECT title FROM listings WHERE product_id=?",
                                       (pid,)).fetchone()["title"]
    # a PDF product still defaults to 'pdf' (backward compatible)
    tid = db.upsert_trend(Trend(source="test", term="camping"))
    ppid = db.insert_product(Product(trend_id=tid, title_concept="x", bundle_type="Camping Kit"))
    with db.connect() as c:
        assert c.execute("SELECT format FROM products WHERE id=?", (ppid,)).fetchone()["format"] == "pdf"


def test_canva_publish_writes_etsy_listings_and_status(tmp_path, monkeypatch):
    """Phase 3: canva publish records the draft in etsy_listings + advances product status — the same
    table/lifecycle the PDF line and metrics/rank/renewal use, not just a JSONL ledger."""
    from etsy_engine import db
    from etsy_engine.canva import publish as cpub
    from etsy_engine.config import settings
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "t.db"))
    monkeypatch.setattr(cpub, "CANVA_LEDGER", tmp_path / "ledger.jsonl")
    db.init_db()
    pid = db.save_canva_product("wedding invitation suite", "vineyard suite",
                                [{"name": "Invitation", "use": "print"}],
                                {"title": "Vineyard Wedding Suite Editable Canva",
                                 "tags": ["wedding invite"], "description": "x", "alt_texts": []})
    monkeypatch.setattr(settings, "etsy_api_key", "k")
    monkeypatch.setattr(settings, "etsy_taxonomy_id", 1)
    monkeypatch.setattr(cpub, "resolve_shop_id", lambda: "shop1")
    monkeypatch.setattr(cpub.ec, "request", lambda method, path, **kw: {"listing_id": 4242})
    monkeypatch.setattr(cpub.ec, "upload", lambda *a, **k: {})
    pdf = tmp_path / "d.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")

    r = cpub.create_draft({"title": "Vineyard Wedding Suite Editable Canva",
                           "tags": ["wedding invite"], "description": "x"},
                          [], pdf, template_link="https://canva.link/x", price=22.99, product_id=pid)
    assert r["listing_id"] == 4242
    with db.connect() as c:
        el = c.execute("SELECT etsy_listing_id, state FROM etsy_listings WHERE product_id=?",
                       (pid,)).fetchone()
        assert el["etsy_listing_id"] == 4242 and el["state"] == "draft"
        assert c.execute("SELECT status FROM products WHERE id=?",
                         (pid,)).fetchone()["status"] == "drafted"


def test_learning_loop_covers_canva(tmp_path, monkeypatch):
    """Phase 4: the learning sources are FORMAT-AGNOSTIC (metrics reads all_etsy_listings; renewal
    reads products_with_listings), so a Canva product in products+etsy_listings is covered by metric
    ingest + seasonal auto-renew with no PDF-specific tables."""
    from etsy_engine import db
    from etsy_engine.config import settings
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "t.db"))
    db.init_db()
    pid = db.save_canva_product("christmas welcome sign", "christmas welcome sign",
                                [{"name": "Sign", "use": "display"}],
                                {"title": "Christmas Welcome Sign Editable Canva",
                                 "tags": ["christmas sign"], "description": "x", "alt_texts": []})
    db.upsert_etsy_listing(pid, 5555, "https://www.etsy.com/listing/5555", state="active",
                           is_seasonal=True, season="christmas")
    assert any(r["etsy_listing_id"] == 5555 for r in db.all_etsy_listings())      # metrics source
    assert any(r["product_id"] == pid for r in db.products_with_listings())       # renewal source
    assert any(r["etsy_listing_id"] == 5555 for r in db.seasonal_listings())      # auto-renew protected


def test_refresh_design_images_uses_final_canva_export(tmp_path, monkeypatch):
    """Mockups must show the owner's FINAL Canva export, not our pre-edit renders. refresh
    overwrites the exact files publish uploads and marks the manifest canva_final."""
    import json

    import pytest

    from etsy_engine.canva import publish as cpub
    (tmp_path / "design_1.png").write_bytes(b"old1")
    (tmp_path / "design_2.png").write_bytes(b"old2")
    (tmp_path / "manifest.json").write_text(json.dumps(
        {"image_paths": [str(tmp_path / "design_1.png"), str(tmp_path / "design_2.png")]}))

    class _Resp:
        def __init__(self, c): self.content = c
    monkeypatch.setattr("requests.get", lambda url, timeout=120: _Resp(b"final:" + url.encode()))

    cpub.refresh_design_images(tmp_path, ["http://c/1", "http://c/2"])
    assert (tmp_path / "design_1.png").read_bytes() == b"final:http://c/1"
    m = json.loads((tmp_path / "manifest.json").read_text())
    assert m["canva_final"] is True and m.get("canva_exported_at")
    with pytest.raises(ValueError):                      # never silently mis-map a wrong page count
        cpub.refresh_design_images(tmp_path, ["http://c/1"])


def test_architect_enforces_product_coherence():
    """Pages are ONE product, not independent designs. The architect must fix a shared SPINE
    (consistent data/scheme), forbid duplicate near-identical pages, and reality-check scale.

    Regression: the seating-chart set shipped 5 contradictory charts (same guest at 3 tables), a
    '100+ guests' title over an 8-row table, and a table-per-town gimmick that can't scale.
    """
    from etsy_engine.canva import architect
    sysp = architect._system()
    assert "ONE COHERENT PRODUCT" in sysp and "SPINE" in sysp     # shared spine
    assert "never contradicts" in sysp                            # cross-page consistency
    assert "near-identical" in sysp                               # no padded variants
    assert "COMPLETE, coordinated SET" in sysp                    # deliver a real bundle, not thin
    assert "SCALABLE by the buyer" in sysp                        # no bespoke-N-item locks
    assert "REALITY CHECK" in sysp                                # scale/claim sanity
    # the declared spine is carried through normalize for inspection
    spec = architect.normalize({"spine": "Elena & Marco, 12 tables", "product_kind": "seating chart",
                                "pages": [{"layout": "table", "use": "hang at entrance",
                                           "content": {"title": "Seating Chart"}}]})
    assert spec["spine"] == "Elena & Marco, 12 tables"


def test_expected_texts_extracts_render_strings():
    """Text QC needs the exact strings the page should show."""
    content = {"title": "Monthly Budget", "subtitle": "track it",
               "sections": [{"label": "Income", "lines": ["Salary", "Side income"]}]}
    ex = poster.expected_texts(content)
    for s in ("Monthly Budget", "track it", "Income", "Salary", "Side income"):
        assert s in ex


def test_assess_text_skips_cleanly_without_expected():
    """No expected text (or no key) => neutral skip, never a false failure."""
    from etsy_engine.generate import qc
    assert qc.assess_text(b"notanimage", [])["status"] == "skipped"


def test_text_qc_hard_fails_on_low_contrast(monkeypatch):
    """Correct spelling but pale/low-contrast text must FAIL so the gated regen fires."""
    from etsy_engine.generate import qc
    monkeypatch.setattr(qc.settings, "anthropic_api_key", "x", raising=False)
    monkeypatch.setattr(qc, "vision_json",
                        lambda *a, **k: {"score": 0.9, "legible_contrast": 0.2, "notes": "pale labels"})
    assert qc.assess_text(b"img", ["Hello"])["status"] == "failed"


def test_market_intel_and_titles_are_cached(monkeypatch):
    """A niche's Etsy data is fetched once per run, not re-fetched by every caller."""
    from etsy_engine.scoring import etsy_market as em
    calls = {"n": 0}
    def fake(kw, n=12):
        calls["n"] += 1
        return ["Title"]
    em._TITLES_CACHE.clear()
    monkeypatch.setattr(em, "_top_listing_titles_uncached", fake)
    em.top_listing_titles("wedding welcome sign")
    em.top_listing_titles("wedding welcome sign")   # served from cache
    assert calls["n"] == 1


def test_canva_mockups_delegate_to_the_shared_pdf_engine(tmp_path, monkeypatch):
    """No parallel Canva mockup logic: build_all calls the ONE engine (generator.render_listing_set)
    with allow_editable=True and a title-cased banner, the same engine the PDF line uses."""
    from PIL import Image
    from etsy_engine.canva import mockups
    from etsy_engine.mockups import generator
    seen = {}

    def fake_render(title, ref_urls, page_paths, out_dir, *, is_single, allow_editable, kinds=None,
                    style_brief=None):
        seen.update(title=title, allow_editable=allow_editable, is_single=is_single, n=len(page_paths))
        return [("hero", "p", tmp_path / "hero.jpg")]
    monkeypatch.setattr(generator, "render_listing_set", fake_render)
    pages = []
    for i in (1, 2):
        p = tmp_path / f"design_{i}.png"
        Image.new("RGB", (2100, 3150), "white").save(p)
        pages.append(str(p))
    (tmp_path / "hero.jpg").write_bytes((tmp_path / "design_1.png").read_bytes())

    mockups.build_all(["http://u/1", "http://u/2"], pages, "funeral program", tmp_path)
    assert seen["allow_editable"] is True          # Canva templates MAY show the 'Editable' badge
    assert seen["title"] == "Funeral Program"       # title-cased for the hero banner
    assert seen["is_single"] is False and seen["n"] == 2


def test_shared_engine_makes_three_distinct_kinds(tmp_path, monkeypatch):
    """render_listing_set (shared by both lines) yields hero + lifestyle + contents, with hero and
    lifestyle DISTINCT scenes (no near-duplicate credit burn) and the editable badge when asked."""
    from PIL import Image
    from etsy_engine.mockups import generator

    class FakeClient:
        def generate(self, prompt, size=None, image_urls=None, timeout=None, retries=None):
            from io import BytesIO
            FakeClient.prompts.append(prompt)
            b = BytesIO()
            Image.new("RGB", (2048, 2048), "white").save(b, "PNG")
            return b.getvalue()
    FakeClient.prompts = []
    monkeypatch.setattr(generator, "get_image_client", lambda: FakeClient())
    monkeypatch.setattr("etsy_engine.generate.qc.assess_thumbnail",
                        lambda b, niche_style=None: {"status": "passed", "score": 0.9, "notes": "ok"})
    monkeypatch.setattr("etsy_engine.generate.qc.assess_ip_safety",
                        lambda b, context="": {"status": "clean", "flagged": False, "notes": "clean"})
    pages = []
    for i in (1, 2, 3):
        p = tmp_path / f"p{i}.png"
        Image.new("RGB", (2100, 3150), "white").save(p)
        pages.append(str(p))

    triples = generator.render_listing_set("My Set", ["http://u/1", "http://u/2", "http://u/3"],
                                           pages, tmp_path, is_single=False, allow_editable=True)
    assert [k for k, _, _ in triples] == ["hero", "lifestyle", "contents_overview"]
    hero = next(p for k, p, _ in triples if k == "hero")
    life = next(p for k, p, _ in triples if k == "lifestyle")
    assert hero != life                             # distinct scenes, not the same image twice
    assert any("Editable Canva Template" in p for p in FakeClient.prompts)   # editable badge allowed


def test_style_brief_reaches_the_hero_prompt_only(tmp_path, monkeypatch):
    """The niche's winning-style research (canva.research) must steer the HERO (the CTR gate) and
    nothing else: its differentiator lands in the hero prompt, not the lifestyle/contents prompts."""
    from PIL import Image
    from etsy_engine.mockups import generator

    captured = {}

    class FakeClient:
        def generate(self, prompt, size=None, image_urls=None, timeout=None, retries=None):
            from io import BytesIO
            # First hero-scene call carries the banner text; record every prompt by a cheap kind guess.
            captured.setdefault("all", []).append(prompt)
            b = BytesIO()
            Image.new("RGB", (2048, 2048), "white").save(b, "PNG")
            return b.getvalue()
    monkeypatch.setattr(generator, "get_image_client", lambda: FakeClient())
    monkeypatch.setattr("etsy_engine.generate.qc.assess_thumbnail",
                        lambda b, niche_style=None: {"status": "passed", "score": 0.9, "notes": "ok"})
    monkeypatch.setattr("etsy_engine.generate.qc.assess_ip_safety",
                        lambda b, context="": {"status": "clean", "flagged": False, "notes": "clean"})
    pages = []
    for i in (1, 2, 3):
        p = tmp_path / f"p{i}.png"
        Image.new("RGB", (2100, 3150), "white").save(p)
        pages.append(str(p))

    brief = {"layout": "centered card", "palette": "blush + sky blue", "vibe": "cute pastel",
             "differentiator": "MARKER_bolder_navy_color_block"}
    generator.render_listing_set("My Set", ["http://u/1", "http://u/2", "http://u/3"], pages,
                                 tmp_path, is_single=False, allow_editable=True, style_brief=brief)
    hero_prompts = [p for p in captured["all"] if "HERO" in p]
    other_prompts = [p for p in captured["all"] if "HERO" not in p]
    assert hero_prompts and all("MARKER_bolder_navy_color_block" in p for p in hero_prompts)
    assert other_prompts and not any("MARKER_bolder_navy_color_block" in p for p in other_prompts)


def test_ensure_min_px_upscales_to_etsy_zoom(tmp_path):
    from PIL import Image
    from etsy_engine.canva import mockups
    p = tmp_path / "x.jpg"
    Image.new("RGB", (1024, 1536), "white").save(p)
    mockups._ensure_min_px(p, min_short=2000)
    assert min(Image.open(p).size) >= 2000       # short edge now meets Etsy's zoom threshold


def test_image_alt_is_descriptive_and_role_aware():
    from etsy_engine.canva import publish as cpub
    t = "Editable Wedding Welcome Sign Set"
    assert t in cpub._image_alt(t, "mock_hero.jpg", 1) and "framed" in cpub._image_alt(t, "mock_hero.jpg", 1)
    assert "page 4" in cpub._image_alt(t, "mock_page_4.jpg", 4)
    assert len(cpub._image_alt("x" * 400, "mock_hero.jpg", 1)) <= 250   # Etsy alt cap


def test_market_price_scales_and_bands():
    """Canva price comes from the niche median + page count, not a flat number."""
    from etsy_engine.canva import publish as cpub
    assert cpub.market_price(None, 5) == cpub.DEFAULT_PRICE   # no median -> fallback 11.99
    assert cpub.market_price(9.0, 5) == 12.99                 # 5-page set off $9 single median
    assert cpub.market_price(3.0, 1) == 6.99                  # floor
    assert cpub.market_price(200.0, 6) == 24.99              # cap
    assert cpub.market_price(16.75, 5) > cpub.market_price(16.75, 1)  # a set costs more than one


def test_delivery_pdf_builds_and_is_pdf(tmp_path):
    pdf = delivery.build_pdf("Editable Classroom Poster | Canva Template",
                             link="https://www.canva.com/design/DAF/view", out_dir=tmp_path)
    p = Path(pdf)
    assert p.exists() and p.read_bytes()[:4] == b"%PDF"
    assert (tmp_path / "delivery.png").exists()       # sibling preview


def test_delivery_pdf_placeholder_when_no_link(tmp_path):
    assert Path(delivery.build_pdf("X", out_dir=tmp_path)).exists()
    assert "(paste" in delivery.LINK_PLACEHOLDER


def test_brand_contact_and_no_emdash():
    assert D.CONTACT_EMAIL == settings.shop_contact_email
    steps = " ".join(delivery.STEPS)
    assert "—" not in steps and "–" not in steps
    if settings.shop_contact_email:
        assert settings.shop_contact_email in copy.DELIVERY_INSTRUCTIONS
    assert "—" not in copy.DELIVERY_INSTRUCTIONS
