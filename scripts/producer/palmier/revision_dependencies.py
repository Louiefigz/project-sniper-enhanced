"""Dependency and dirty-window analysis for incremental Palmier revisions."""
from __future__ import annotations

from dataclasses import dataclass

GLOBAL_LANES = {
    "target", "reframe", "baselineLook", "faceBBoxNorm", "audioEnhance",
    "audioAuthorityMode",
}
RIPPLE_LANES = {"cutTrack"}
NEIGHBOR_LANES = {"transitions", "sfxTrack"}
TIMED_LANES = {
    "graphicsTrack", "punchIns", "titleCards", "brollTrack", "audioGain",
    "treatmentMap", "captions", "chapters", "music",
}


@dataclass(frozen=True)
class DependencyInput:
    """Facts required to compute a revision dependency closure."""

    operations: list[dict]
    changed_lanes: list[str]
    duration_s: float


def _window(value: object) -> tuple[float, float] | None:
    if not isinstance(value, dict):
        return None
    start, end = value.get("outStart"), value.get("outEnd")
    if not isinstance(start, (int, float)) or isinstance(start, bool):
        return None
    if not isinstance(end, (int, float)) or isinstance(end, bool):
        return None
    return (max(0.0, float(start)), max(0.0, float(end)))


def _operation_windows(operation: dict) -> list[tuple[float, float]]:
    rows = [_window(operation.get(key)) for key in ("before", "after")]
    return [row for row in rows if row is not None and row[1] > row[0]]


def merge_windows(windows: list[tuple[float, float]],
                  padding_s: float = 0.25) -> list[list[float]]:
    """Merge overlapping review windows with a small seam handle."""
    expanded = sorted((max(0.0, start - padding_s), end + padding_s)
                      for start, end in windows if end > start)
    result: list[list[float]] = []
    for start, end in expanded:
        if not result or start > result[-1][1]:
            result.append([round(start, 3), round(end, 3)])
            continue
        result[-1][1] = round(max(result[-1][1], end), 3)
    return result


def _dependent_lanes(changed: set[str]) -> set[str]:
    result = set(changed)
    if changed & RIPPLE_LANES:
        result.update(TIMED_LANES | NEIGHBOR_LANES)
    if changed & NEIGHBOR_LANES:
        result.update({"cutTrack", "audioGain"})
    if "graphicsTrack" in changed:
        result.update({"punchIns", "treatmentMap"})
    return result


def dependency_closure(context: DependencyInput) -> dict:
    """Return fail-closed routing and exact changed-window coverage."""
    changed = set(context.changed_lanes)
    windows = [window for operation in context.operations
               for window in _operation_windows(operation)]
    global_change = bool(changed & GLOBAL_LANES)
    ripple_change = bool(changed & RIPPLE_LANES)
    if global_change or ripple_change:
        windows = [(0.0, max(0.0, context.duration_s))]
    dirty = merge_windows(windows)
    dirty_s = sum(end - start for start, end in dirty)
    coverage = dirty_s / context.duration_s if context.duration_s > 0 else 1.0
    return {
        "changedLanes": sorted(changed),
        "dependentLanes": sorted(_dependent_lanes(changed)),
        "dirtyWindows": dirty,
        "dirtyCoverage": round(min(1.0, coverage), 4),
        "requiresFullRebuild": global_change or ripple_change,
        "reason": ("global plan property changed" if global_change else
                   "cutTrack changed and shifted the output timebase"
                   if ripple_change else None),
    }
