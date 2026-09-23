"""Shared plan fixture for final-provenance tests."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RenderOptions:
    skip_graphics: bool = False
    fail_master: bool = False
    audio_order: list[str] | None = None


def plan() -> dict:
    """Return full-plan content with render-irrelevant addressing."""
    return {
        "planVersion": 4,
        "_selection": {"graphicId": "g-1"},
        "target": {"mode": "longform"},
        "cutTrack": [{"sourceId": "raw", "start": 0.0, "end": 2.0}],
        "graphicsTrack": [{"id": "g-1", "kind": "line-swap",
                           "outStart": 0.0, "outEnd": 1.0}],
        "audioEnhance": {"preset": "voice"},
        "music": {"enabled": False},
    }
