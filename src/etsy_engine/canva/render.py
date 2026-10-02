"""Render core v2 — FLOW layouts.

Content sits in a flex-column region inside the art's clean zone, so blocks stack
and can NEVER overlap regardless of how long the LLM's copy is (the bug that made
v1 unsellable). Each page also carries its own art treatment (`arch` cover frame /
`garland` interior / `none`), so a set is cohesive without being one repeated
background. ADDITIVE: independent of the primary PDF pipeline.
"""
from __future__ import annotations

import html
import re

from . import design as D

_DASH = re.compile(r"\s*[—–]\s*|\s--\s")


def _t(s) -> str:
    return html.escape(_DASH.sub(": ", str(s)), quote=True)


def _lines(seq) -> str:
    return "<br/>".join(_t(x) for x in (seq or []))


# clean-zone content region per art kind: (top, left, width, height, vertical-justify)
_REGION = {
    "arch": (168, 168, 458, 800, "center"),
    "garland": (244, 104, 586, 760, "center"),
    "none": (120, 104, 586, 900, "center"),
}


def _rule(color: str, w: int = 46, my: int = 16) -> str:
    return f'<div style="width:{w}px;height:1px;background:{color};margin:{my}px auto"></div>'


# --- flow blocks (each a flex item; NO absolute positioning) -----------------

def _hero(c, aes) -> str:
    p, f = aes["palette"], aes["fonts"]
    note = _lines(c.get("note", []))
    return (
        '<div style="text-align:center;max-width:430px">'
        f'<div style="font-family:{f["display"]};font-size:{D.TYPE["hero"]}px;font-weight:600;'
        f'color:{p["accent"]};line-height:1.08;text-wrap:balance">{_t(c.get("title", ""))}</div>'
        f'{_rule(p["gold"])}'
        + (f'<div style="font-family:{f["display"]};font-size:{D.TYPE["lead"]}px;font-style:italic;'
           f'color:{p["ink_soft"]};line-height:1.5">{note}</div>' if note else "")
        + "</div>"
    )


def _title_block(c, aes) -> str:
    p, f = aes["palette"], aes["fonts"]
    intro = _lines(c.get("intro", []))
    return (
        '<div style="text-align:center;max-width:520px">'
        f'<div style="font-family:{f["display"]};font-size:{D.TYPE["title"]}px;font-weight:600;'
        f'color:{p["accent"]};line-height:1.12;text-wrap:balance">{_t(c.get("title", ""))}</div>'
        f'{_rule(p["gold"], 40, 14)}'
        + (f'<div style="font-family:{f["body"]};font-size:{D.TYPE["body"]}px;color:{p["ink_soft"]};'
           f'line-height:1.55">{intro}</div>' if intro else "")
        + "</div>"
    )


def _label(text, aes) -> str:
    p, f = aes["palette"], aes["fonts"]
    return (f'<div style="font-family:{f["body"]};font-size:{D.TYPE["label"]}px;font-weight:600;'
            f'letter-spacing:2.5px;color:{p["accent"]}">{_t(str(text).upper())}</div>')


def _group(g, aes, checklist=False) -> str:
    """A labelled list: LABEL, hairline, then left-aligned items. Never overlaps."""
    p, f = aes["palette"], aes["fonts"]
    mark = "○&nbsp;&nbsp;" if checklist else ""
    items = "".join(
        f'<div style="font-family:{f["body"]};font-size:{D.TYPE["body"]}px;color:{p["ink"]};'
        f'line-height:1.6;margin-top:7px">{mark}{_t(str(it))}</div>'
        for it in (g.get("items") or [])[:8])
    return (
        '<div style="width:360px;max-width:100%;text-align:left">'
        + _label(g.get("header", ""), aes)
        + f'<div style="width:100%;height:1px;background:{p["rule"]};margin:9px 0 4px"></div>'
        + items + "</div>"
    )


def _value_grid(sections, aes) -> str:
    """2xN grid of small label + lines (for a welcome 'what we value' block)."""
    p, f = aes["palette"], aes["fonts"]
    cells = "".join(
        '<div style="text-align:center">' + _label(s.get("label", ""), aes)
        + f'<div style="font-family:{f["body"]};font-size:{D.TYPE["body"]}px;color:{p["ink"]};'
        f'line-height:1.7;margin-top:8px">{_lines(s.get("lines", []))}</div></div>'
        for s in (sections or [])[:4])
    return (f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:26px 40px;'
            f'width:100%;max-width:420px">{cells}</div>')


def _section_header(text, aes) -> str:
    p, f = aes["palette"], aes["fonts"]
    return ('<div style="text-align:center">'
            f'<div style="font-family:{f["display"]};font-size:{D.TYPE["section"]}px;'
            f'letter-spacing:6px;color:{p["accent"]}">{_t(str(text).upper())}</div>'
            f'{_rule(p["rule"], 28, 12)}</div>')


def _statement(c, aes) -> str:
    p, f = aes["palette"], aes["fonts"]
    sub = _t(str(c.get("sub", "")).upper())
    return (
        '<div style="text-align:center;max-width:480px">'
        f'<div style="font-family:{f["display"]};font-size:{D.TYPE["statement"]}px;font-weight:600;'
        f'letter-spacing:-0.01em;color:{p["accent"]};line-height:1.04">{_t(c.get("statement", ""))}</div>'
        f'{_rule(p["gold"], 56, 26)}'
        + (f'<div style="font-family:{f["body"]};font-size:{D.TYPE["small"]}px;letter-spacing:3px;'
           f'color:{p["ink_soft"]}">{sub}</div>' if sub else "")
        + "</div>"
    )


def _footer(c, aes) -> str:
    p, f = aes["palette"], aes["fonts"]
    title = _t(c.get("footer_title", ""))
    lines = _lines(c.get("footer_lines", []))
    if not title and not lines:
        return ""
    return (
        '<div style="text-align:center;max-width:460px">'
        + (f'<div style="font-family:{f["display"]};font-size:{D.TYPE["section"]}px;'
           f'color:{p["accent"]}">{title}</div>' if title else "")
        + (f'<div style="font-family:{f["body"]};font-size:{D.TYPE["small"]}px;color:{p["ink_soft"]};'
           f'line-height:1.7;margin-top:8px">{lines}</div>' if lines else "")
        + "</div>"
    )


# --- layouts: (content, aes) -> (art_kind, [flow blocks]) --------------------

def welcome(c, aes):
    blocks = [_hero(c, aes)]
    if c.get("section_header"):
        blocks.append(_section_header(c["section_header"], aes))
    if c.get("sections"):
        blocks.append(_value_grid(c["sections"], aes))
    blocks.append(_footer(c, aes))
    return "arch", [b for b in blocks if b]


def sheet(c, aes):
    blocks = [_title_block(c, aes)]
    chk = bool(c.get("checklist"))
    for g in (c.get("groups") or [])[:4]:
        blocks.append(_group(g, aes, checklist=chk))
    blocks.append(_footer(c, aes))
    return "garland", [b for b in blocks if b]


def statement(c, aes):
    return "arch", [_statement(c, aes)]


LAYOUTS = {"welcome": welcome, "sheet": sheet, "statement": statement}
# which art treatment each layout uses (so a set has cover vs interior variety)
LAYOUT_ART = {"welcome": "arch", "statement": "arch", "sheet": "garland"}


def _page(art_kind, blocks, aes, arts) -> str:
    p, f = aes["palette"], aes["fonts"]
    top, left, width, height, justify = _REGION.get(art_kind, _REGION["none"])
    art = ""
    url = (arts or {}).get(art_kind)
    if url:
        art = (f'<img src="{html.escape(url, quote=True)}" alt="decorative frame" '
               f'style="position:absolute;top:0;left:0;width:{D.PAGE_W}px;height:{D.PAGE_H}px;'
               f'object-fit:contain;object-position:center"/>')
    region = (f'position:absolute;top:{top}px;left:{left}px;width:{width}px;height:{height}px;'
              f'display:flex;flex-direction:column;align-items:center;justify-content:{justify};'
              f'gap:{D.SPACE["lg"]}px;text-align:center')
    return (
        f'<div data-document-role="page" data-label="Page" lang="en" '
        f'style="width:{D.PAGE_W}px;height:{D.PAGE_H}px;position:relative;background:{p["bg"]};'
        f'font-family:{f["body"]};color:{p["ink"]};overflow:hidden">'
        f'{art}<div style="{region}">{"".join(blocks)}</div></div>'
    )


def render_pages(pages, aes_name=None, arts=None) -> str:
    """pages: list of {"layout": name, "content": {...}}.
    arts: {"arch": url, "garland": url} (per-page treatment). Returns one multi-page HTML."""
    aes = D.aesthetic(aes_name)
    if isinstance(arts, str):            # back-compat: a single url = the arch frame
        arts = {"arch": arts, "garland": arts}
    body = ""
    for pg in pages:
        fn = LAYOUTS.get(pg.get("layout", "sheet"), sheet)
        art_kind, blocks = fn(pg.get("content", {}), aes)
        body += _page(art_kind, blocks, aes, arts or {})
    return ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8"></head>'
            '<body style="margin:0">' + body + "</body></html>\n")
