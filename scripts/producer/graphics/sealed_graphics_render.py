"""Render one already-verified overlay seal without reading live sources."""
from __future__ import annotations

from graphics.graphics_render import _RenderWork, _materialize_work
from headless.overlay_seal import ResolvedOverlaySeal


def render_presealed(seal: ResolvedOverlaySeal, cache_dir: str) -> dict:
    """Materialize only the parent-sealed composition, intent, and assets."""
    work = _RenderWork(
        seal.entry, seal.fmt, seal.dimensions, seal.duration, seal.key,
        seal.composition, "", seal.comp_html, seal.intent["spec"], seal.snapshot)
    return _materialize_work(work, cache_dir, seal.extension)
