"""Render one already-verified overlay seal without reading live sources."""
from __future__ import annotations

from graphics.graphics_render import _RenderWork, _materialize_work
from headless.overlay_seal import ResolvedOverlaySeal


def render_presealed_layout(request: dict) -> dict:
    """Explicit v2 private observation; never widens the historical v1 seal."""
    from headless.render_layout_worker import execute
    return execute(request)


def render_presealed(seal: ResolvedOverlaySeal, cache_dir: str) -> dict:
    """Materialize only the parent-sealed composition, intent, and assets."""
    work = _RenderWork(
        seal.entry, seal.fmt, seal.dimensions, seal.duration, seal.key,
        seal.composition, "", seal.comp_html, seal.intent["spec"],
        seal.snapshot, False, 30.0)
    return _materialize_work(work, cache_dir, seal.extension)
