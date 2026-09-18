"""Changed-window review frames for one incremental Palmier revision."""
from __future__ import annotations

from audit.audit_frames import FrameRef


def _ref(label: str, timestamp: float, duration: float, note: str) -> FrameRef:
    upper = max(0.0, duration - 0.1)
    return FrameRef(label, "revision-window",
                    round(min(max(0.0, timestamp), upper), 3), "", note)


def revision_frame_refs(authority: dict, duration: float) -> list[FrameRef]:
    """Sample before/entrance/middle/exit/after for every dirty island."""
    revision = authority.get("revisionSet")
    dependencies = revision.get("dependencies") if isinstance(revision, dict) else None
    windows = dependencies.get("dirtyWindows") \
        if isinstance(dependencies, dict) else None
    refs: list[FrameRef] = []
    for index, pair in enumerate(windows or []):
        if not isinstance(pair, list) or len(pair) != 2:
            continue
        start, end = float(pair[0]), float(pair[1])
        if end <= start:
            continue
        points = (("before", start - 0.05), ("entrance", start + 0.05),
                  ("middle", (start + end) / 2.0), ("exit", end - 0.05),
                  ("after", end + 0.05))
        refs.extend(_ref(f"revision{index}_{phase}", at, duration,
                         f"Inspect changed revision window ({phase})")
                    for phase, at in points)
    return refs
