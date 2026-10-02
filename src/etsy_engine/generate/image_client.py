"""Image-engine selection. Raywake is the engine; callers use `get_image_client()` and
the `.generate(prompt, size=..., image_urls=...) -> bytes` surface, so swapping the
engine means changing only this function."""
from __future__ import annotations

from .raywake import RaywakeClient


def get_image_client() -> RaywakeClient:
    return RaywakeClient()
