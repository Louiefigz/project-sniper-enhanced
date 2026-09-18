"""Data carriers shared by closed P4 treatment handlers."""
from __future__ import annotations

from dataclasses import dataclass

from edit.exact_timing import PositiveRational


@dataclass(frozen=True)
class TreatmentState:
    """Compatibility plan, first-class scenes, and exact delivery clock."""

    plan: dict
    scenes: tuple[dict, ...]
    fps: PositiveRational
    total_frames: int


@dataclass(frozen=True)
class TreatmentResult:
    """New immutable candidate state plus exact invalidation receipt."""

    state: TreatmentState
    receipt: dict


@dataclass(frozen=True)
class TreatmentEffect:
    """Internal local mutation result."""

    state: TreatmentState
    dirty: tuple[tuple[int, int], ...]
    nodes: tuple[str, ...]
    media_reused: bool
    target_id: str
