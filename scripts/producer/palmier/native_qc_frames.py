"""Plan-aware review-frame selection for native Palmier candidate QC."""
from __future__ import annotations

from dataclasses import dataclass

from audit.audit_frames import FrameRef, plan_frames
from palmier.mcp_client import PalmierError
from palmier.revision_qc_frames import revision_frame_refs
from palmier.timeline_authority import TimelineSnapshot


@dataclass(frozen=True)
class FrameFacts:
    """Timeline facts shared by native frame-reference planners."""

    fps: float
    duration: float
    total: float
    parent: dict
    current: dict


def _at_frame(label: str, kind: str, frame: float,
              facts: FrameFacts) -> FrameRef:
    upper = max(0.0, facts.duration - 0.1)
    timestamp = min(max(0.0, float(frame) / facts.fps), upper)
    note = f"Inspect requested {kind}"
    return FrameRef(label, kind, round(timestamp, 3), "", note)


def _window_refs(prefix: str, kind: str, pair: tuple[float, float],
                 facts: FrameFacts) -> list[FrameRef]:
    start, end = pair
    inset = min(1.0, max(0.0, (end - start) / 4.0))
    phases = (("start", start + inset), ("mid", (start + end) / 2.0),
              ("end", end - inset))
    return [_at_frame(f"{prefix}_{phase}", kind, frame, facts)
            for phase, frame in phases]


def _boundary_refs(prefix: str, frame: float,
                   facts: FrameFacts) -> list[FrameRef]:
    phases = (("before", frame - 1.0), ("seam", frame),
              ("after", frame + 1.0))
    return [_at_frame(f"{prefix}_{phase}", "native-boundary", value, facts)
            for phase, value in phases]


def _clip_rows(timeline: dict) -> list[tuple[int, int, dict]]:
    return [(track_index, clip_index, clip)
            for track_index, track in enumerate(timeline.get("tracks") or [])
            if isinstance(track, dict)
            for clip_index, clip in enumerate(track.get("clips") or [])
            if isinstance(clip, dict)]


def clip_start(parent: dict, current: dict, clip_id: object) -> float:
    """Resolve one clip after mutations without trusting stale track indexes."""
    source = next((row for row in _clip_rows(parent)
                   if row[2].get("id") == clip_id), None)
    if source is None:
        raise PalmierError("native keyframe target is absent from pinned parent")
    exact = next((row for row in _clip_rows(current)
                  if row[2].get("id") == clip_id), None)
    media = source[2].get("mediaRef")
    matches = [row for row in _clip_rows(current)
               if media is not None and row[2].get("mediaRef") == media]
    positional = [row for row in matches if row[:2] == source[:2]]
    target = exact or (matches[0] if len(matches) == 1 else None) \
        or (positional[0] if len(positional) == 1 else None)
    frames = target[2].get("frames") if target else None
    if not isinstance(frames, list) or len(frames) != 2:
        raise PalmierError("native keyframe target is ambiguous in fresh readback")
    return float(frames[0])


def _operation_refs(index: int, operation: dict,
                    facts: FrameFacts) -> list[FrameRef]:
    tool, args = operation.get("tool"), operation.get("args") or {}
    prefix, refs = f"native{index}_{tool}", []
    if tool == "add_texts":
        for row_index, row in enumerate(args.get("entries") or []):
            pair = (row["startFrame"], row["endFrame"])
            refs.extend(_window_refs(
                f"{prefix}_{row_index}", "native-text", pair, facts))
    elif tool == "apply_layout":
        pair = (args.get("startFrame", 0), args.get("endFrame", facts.total))
        refs.extend(_window_refs(prefix, "native-layout", pair, facts))
    elif tool == "set_keyframes":
        start = clip_start(facts.parent, facts.current, args.get("clipId"))
        for row_index, row in enumerate(args.get("keyframes") or []):
            refs.append(_at_frame(f"{prefix}_{row_index}", "native-keyframe",
                                  start + row[0], facts))
    elif tool == "split_clips":
        points = [*(args.get("frames") or []),
                  *(row["atFrame"] for row in args.get("splits") or [])]
        for row_index, frame in enumerate(points):
            refs.extend(_boundary_refs(f"{prefix}_{row_index}", frame, facts))
    elif tool == "ripple_delete_ranges":
        for row_index, pair in enumerate(args.get("ranges") or []):
            for edge, frame in zip(("start", "end"), pair, strict=True):
                refs.extend(_boundary_refs(
                    f"{prefix}_{row_index}_{edge}", frame, facts))
    return refs


def review_frames(receipt: dict, found: TimelineSnapshot,
                  duration: float) -> list[FrameRef]:
    """Merge native-operation, revision-window, and generic plan frames."""
    authority = receipt.get("authority") or {}
    plan = authority.get("nativePlan") or {}
    parent = authority.get("nativeParent") or {}
    facts = FrameFacts(float(found.timeline["fps"]), duration,
                       float(found.timeline["totalFrames"]),
                       parent.get("timeline") or {}, found.timeline)
    native = [ref for index, operation in enumerate(plan.get("operations") or [])
              for ref in _operation_refs(index, operation, facts)]
    generic = plan_frames(authority.get("editPlan") or {}, duration)
    return _dedupe([*native, *revision_frame_refs(authority, duration), *generic])


def _dedupe(refs: list[FrameRef]) -> list[FrameRef]:
    merged: list[FrameRef] = []
    by_time: dict[float, int] = {}
    for ref in refs:
        if ref.timestamp in by_time:
            prior = merged[by_time[ref.timestamp]]
            prior.note = f"{prior.note}; {ref.note}"
            continue
        by_time[ref.timestamp] = len(merged)
        merged.append(ref)
    return merged
