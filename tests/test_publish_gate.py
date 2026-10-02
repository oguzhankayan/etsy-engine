"""The single pre-publish gate: sanitize a listing to Etsy's hard rules, flag dishonest claims."""
from etsy_engine.publish import gate


def test_sanitize_tags_enforces_etsy_rules():
    tags = ["editable canva template", "editable canva template", "ok tag", "x" * 25, "", "  ",
            "canva template"] + [f"tag number {i}" for i in range(20)]
    out = gate.sanitize_tags(tags)
    assert all(len(t) <= 20 for t in out)                 # none over 20 chars
    assert len(out) <= 13                                  # Etsy cap
    assert len(out) == len({t.lower() for t in out})       # de-duped
    assert "editable canva template" not in out            # 23 chars -> dropped


def test_sanitize_title_amp_once_and_cap():
    t = gate.sanitize_title("A & B & C " + "x" * 200)
    assert t.count("&") == 1 and "and" in t and len(t) <= 140


def test_pdf_line_flags_dishonest_claim():
    _, v = gate.check_listing({"title": "Editable Canva Planner", "tags": ["diy planner"]}, line="pdf")
    assert any("dishonest" in m for m in v)


def test_canva_line_allows_editable_canva():
    clean, v = gate.check_listing({"title": "Editable Wedding Set", "tags": ["canva template"]},
                                  line="canva")
    assert not any("dishonest" in m for m in v)
    assert clean["tags"] == ["canva template"]


def test_gate_drops_oversize_tag_and_reports():
    clean, v = gate.check_listing({"title": "X", "tags": ["instant download template"]},
                                  line="canva")
    assert clean["tags"] == []                             # 25-char tag dropped
    assert v                                                # surfaced (no valid tags)
