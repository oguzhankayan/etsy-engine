"""The PERSONALIZABLE seed pool is what stops the discovery funnel from starving the Canva line.

These tests lock two invariants:
  1. EVERY personalizable seed actually routes to the Canva line (a seed that routes to PDF is dead
     weight — it can never reach the line it was added for).
  2. The discovery funnel (`discovery_seeds`, `active_seeds`) genuinely surfaces personalizable
     terms, so the architect has swap-my-name trends to route (before this pool it saw ~0).
"""
from etsy_engine.canva import detect
from etsy_engine.sources import seeds


def _routes_canva(term: str) -> bool:
    s = detect.canva_suitability(term)
    return bool(s and s["suitable"])


def test_every_personalizable_seed_routes_to_canva():
    """A personalizable seed that routes to PDF would never feed the Canva line it exists for."""
    non_routing = [t for t in seeds.PERSONALIZABLE if not _routes_canva(t)]
    assert non_routing == [], f"these PERSONALIZABLE seeds do not route CANVA: {non_routing}"


def test_personalizable_covers_the_core_canva_kinds():
    """The pool must span the market, not circle one kind (weddings, showers, invitations,
    signs, announcements, menus/memorials all present)."""
    kinds = {detect.canva_suitability(t)["kind"] for t in seeds.PERSONALIZABLE}
    for expected in {"welcome_sign", "wedding", "shower_party", "invitation",
                     "announcement", "menu_program", "wall_art_text"}:
        assert expected in kinds, f"PERSONALIZABLE missing kind {expected!r} (have {kinds})"


def test_discovery_seeds_surfaces_personalizable():
    """The rotation must hand the discovery source personalizable terms — otherwise the funnel is
    all fill-in/print PDF again and the Canva line has nothing to route."""
    batch = seeds.discovery_seeds(14)
    pset = {t.lower() for t in seeds.PERSONALIZABLE}
    assert any(t.lower() in pset for t in batch), batch


def test_active_seeds_includes_personalizable():
    active = {t.lower() for t in seeds.active_seeds()}
    assert {t.lower() for t in seeds.PERSONALIZABLE} <= active


def test_new_seasonal_swap_my_name_seeds_route_canva():
    """The swap-my-name seeds added to SEASONAL events (invitations, menus, signs) route Canva, so
    in-season the funnel offers the Canva line real seasonal openings (trunk-or-treat invite,
    thanksgiving menu, christmas party invite, teacher welcome sign...)."""
    for name in ("halloween", "thanksgiving", "christmas", "back to school", "graduation"):
        event = next(e for e in seeds.SEASONAL if e["name"] == name)
        assert any(_routes_canva(s) for s in event["seeds"]), \
            f"season {name!r} has no Canva-routing seed: {event['seeds']}"
