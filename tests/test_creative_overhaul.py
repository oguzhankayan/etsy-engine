"""Creative-agent overhaul (owner request): a real Creative Director craft/consistency gate, the
art director's composition spec, and the shared SPINE injected into every page prompt. Mocked vision;
no image generation here.
"""
from etsy_engine.canva import creative_director as cd, poster, produce
from etsy_engine.config import settings
from etsy_engine.design import art_director
from etsy_engine.generate import qc


def test_creative_director_fails_on_weak_composition(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "k")
    monkeypatch.setattr(cd, "vision_json", lambda *a, **k: {
        "composition": 0.3, "system_adherence": 0.8, "craft": 0.5, "score": 0.45, "fix": "declutter"})
    r = cd.assess_page(b"img", direction={"palette": {"bg": "#fff"}}, kind="funeral program")
    assert r["status"] == "failed"                       # composition < 0.5 is a hard fail


def test_creative_director_ships_good_craft(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "k")
    monkeypatch.setattr(cd, "vision_json", lambda *a, **k: {
        "composition": 0.85, "system_adherence": 0.9, "craft": 0.82, "score": 0.85, "fix": "ship"})
    assert cd.assess_page(b"img", direction={}, kind="x")["status"] == "passed"


def test_creative_director_fails_soft_without_key(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    assert cd.assess_page(b"img")["status"] == "skipped"


def test_build_prompt_injects_composition_and_shared_spine():
    direction = {"palette": {"bg": "#FBFAF8", "ink": "#20242A", "accent": "#2F6E63", "accent2": "#20242A"},
                 "art_style": "flat editorial", "type_prompt": "serif display", "frame_prompt": "clean",
                 "composition": "single-column editorial grid, one focal title, wide margins"}
    p = poster.build_prompt({"title": "In Loving Memory", "product_kind": "funeral program"},
                            direction=direction, spine="Robert Hensley, service June 14, navy and gold")
    assert "single-column editorial grid" in p           # art-director composition spec is injected
    assert "SHARED SPINE" in p and "Robert Hensley" in p  # spine anchors every page identically
    assert "—" not in p and "–" not in p                  # no em/en dashes


def test_art_director_carries_composition():
    d = art_director._normalize_direction(
        {"vibe": "bold retro", "art_style": "x", "composition": "tight modular grid, strong hierarchy"},
        fallback=art_director._NEUTRAL_DIRECTION)
    assert d["composition"] and "grid" in d["composition"]


def test_gen_page_regenerates_when_creative_director_fails(monkeypatch, tmp_path):
    """First render fails craft, the retry passes -> the better (retry) is promoted."""
    monkeypatch.setattr(settings, "anthropic_api_key", "k")

    def fake_generate(content, aesthetic, out_dir, filename, **k):
        p = tmp_path / filename
        p.write_bytes(b"bytes-" + filename.encode())
        return {"image_path": str(p), "url": "http://" + filename}

    monkeypatch.setattr(produce.poster, "generate", fake_generate)
    monkeypatch.setattr(produce.poster, "expected_texts", lambda c: ["x"])
    monkeypatch.setattr(qc, "assess_text", lambda *a, **k: {"status": "passed", "score": 0.9})

    craft = iter([0.3, 0.85])   # first gen weak craft (fail), retry strong (pass)

    def fake_cd(b, **k):
        s = next(craft)
        return {"status": "failed" if s < 0.6 else "passed", "score": s,
                "composition": s, "system_adherence": 0.9, "fix": "tighten"}

    monkeypatch.setattr(cd, "assess_page", fake_cd)
    out = produce._gen_page_qc({"product_kind": "x"}, "editorial", {"palette": {}}, tmp_path, 1, None)
    assert "retry" in out["image_url"]                    # the stronger retry was promoted
