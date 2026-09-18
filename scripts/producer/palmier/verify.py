"""Structural verification for a generated Palmier shadow timeline."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from palmier.keyframe_readback import verify_keyframes
from palmier.mcp_client import PalmierError
from palmier.verify_properties import (cut_properties, verify_properties,
                                       verify_text)

# Permit one adjacent source-cut frame when 23.976 footage is conformed to 24.
_TIMELINE_FRAME_TOLERANCE = 1


@dataclass(frozen=True)
class ExpectedClip:
    """One translated clip and the exact Palmier timeline range it must occupy."""

    lane: str
    clip_id: str
    start: int
    end: int
    media_ref: str | None = None
    text: str | None = None
    properties: dict | None = None


def _frame(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PalmierError(f"timeline verification: {label} is not a frame number")
    integer = int(value)
    if float(value) != integer:
        raise PalmierError(f"timeline verification: {label} is not an integer frame")
    return integer


def _clip_frames(clip: dict) -> tuple[int, int]:
    frames = clip.get("frames")
    if isinstance(frames, (list, tuple)) and len(frames) == 2:
        return _frame(frames[0], "clip start"), _frame(frames[1], "clip end")
    if isinstance(frames, dict):
        start = frames.get("startFrame", frames.get("start"))
        end = frames.get("endFrame", frames.get("end"))
        if start is not None and end is not None:
            return _frame(start, "clip start"), _frame(end, "clip end")
    start, end = clip.get("startFrame"), clip.get("endFrame")
    if start is not None and end is not None:
        return _frame(start, "clip start"), _frame(end, "clip end")
    duration = clip.get("durationFrames")
    if start is not None and duration is not None:
        first = _frame(start, "clip start")
        return first, first + _frame(duration, "clip duration")
    raise PalmierError(
        f"timeline verification: clip {clip.get('id')!r} exposes no frame range")


def _clip_index(timeline: dict) -> dict[str, dict]:
    index: dict[str, dict] = {}
    tracks = timeline.get("tracks")
    if not isinstance(tracks, list):
        raise PalmierError("timeline verification: get_timeline has no tracks array")
    for track in tracks:
        if not isinstance(track, dict):
            raise PalmierError("timeline verification: malformed track entry")
        clips = track.get("clips") or []
        if not isinstance(clips, list):
            raise PalmierError("timeline verification: track clips is not an array")
        for clip in clips:
            if not isinstance(clip, dict) or not isinstance(clip.get("id"), str):
                raise PalmierError("timeline verification: clip is missing its id")
            clip_id = clip["id"]
            if clip_id in index:
                raise PalmierError(f"timeline verification: duplicate clip id {clip_id}")
            index[clip_id] = clip
    return index


def _cut_clips(lanes: dict, executor: Any) -> list[ExpectedClip]:
    entries = (lanes.get("cuts") or {}).get("entries") or []
    ids = list(executor.cut_clip_ids)
    if len(ids) != len(entries):
        raise PalmierError(
            f"timeline verification: expected {len(entries)} cut ids, got {len(ids)}")
    clips = []
    transform = (lanes.get("baseline") or {}).get("transform")
    for clip_id, entry in zip(ids, entries, strict=True):
        start = int(entry["startFrame"])
        # Expected range is the translator's tiled [startFrame, endFrame); a
        # source-derived length would re-round and drift a frame at the seam.
        end = int(entry["endFrame"])
        media_ref = executor.media[entry["mediaKey"]]
        properties = cut_properties(
            {**entry, "mediaKey": media_ref},
            executor.media_s[entry["mediaKey"]], executor.project_fps,
            transform)
        clips.append(ExpectedClip("cuts", clip_id, start, end,
                                  media_ref, properties=properties))
    return clips


def _mirror_clips(lanes: dict, executor: Any) -> list[ExpectedClip]:
    step = lanes.get("mirror")
    if not step:
        return []
    ids = list(executor.mirror_clip_ids)
    if len(ids) != 1:
        raise PalmierError(
            f"timeline verification: expected one mirror clip id, got {len(ids)}")
    entry = step["entry"]
    return [ExpectedClip(
        "mirror", ids[0], 0, int(entry["endFrame"]),
        media_ref=executor.media[entry["mediaKey"]])]


def _overlay_clips(lanes: dict, executor: Any) -> list[ExpectedClip]:
    entries = (lanes.get("overlays") or {}).get("entries") or []
    ids = list(executor.overlay_clip_ids)
    if len(ids) != len(entries):
        raise PalmierError(
            f"timeline verification: expected {len(entries)} overlay ids, got {len(ids)}")
    clips = []
    for clip_id, entry in zip(ids, entries, strict=True):
        start, end = int(entry["startFrame"]), int(entry["endFrame"])
        available = int(executor.media_s[entry["mediaKey"]] * executor.project_fps)
        end = min(end, start + available)
        media_ref = executor.media[entry["mediaKey"]]
        properties = ({"mediaRef": media_ref,
                       "transform": entry["transform"]}
                      if entry.get("transform") else None)
        clips.append(ExpectedClip("overlays", clip_id, start, end,
                                  media_ref, properties=properties))
    return clips


def _text_clips(lanes: dict, executor: Any) -> list[ExpectedClip]:
    entries, ids = lanes.get("texts") or [], list(executor.text_clip_ids)
    if len(ids) != len(entries):
        raise PalmierError(
            f"timeline verification: expected {len(entries)} text ids, got {len(ids)}")
    return [ExpectedClip("texts", clip_id, int(entry["startFrame"]),
                         int(entry["endFrame"]), text=entry["content"])
            for clip_id, entry in zip(ids, entries, strict=True)]


def _expected_clips(lanes: dict, executor: Any) -> list[ExpectedClip]:
    clips = (_mirror_clips(lanes, executor) if lanes.get("mirror") else
             [*_cut_clips(lanes, executor), *_overlay_clips(lanes, executor),
              *_text_clips(lanes, executor)])
    ids = [clip.clip_id for clip in clips]
    if len(ids) != len(set(ids)):
        raise PalmierError("timeline verification: executor returned duplicate clip ids")
    return clips


def _verify_one(expected: ExpectedClip, actual: dict) -> tuple[int, int]:
    frames = _clip_frames(actual)
    tolerance = _TIMELINE_FRAME_TOLERANCE if expected.lane == "cuts" else 0
    wanted = (expected.start, expected.end)
    if any(abs(found - target) > tolerance
           for found, target in zip(frames, wanted, strict=True)):
        raise PalmierError(
            f"timeline verification: {expected.lane} clip {expected.clip_id} "
            f"occupies {frames}, expected {wanted}")
    label = f"{expected.lane} clip {expected.clip_id}"
    if expected.properties is not None:
        verify_properties(actual, expected.properties, label)
    elif expected.media_ref is not None and actual.get("mediaRef") != expected.media_ref:
        raise PalmierError(f"timeline verification: {label} references wrong media")
    if expected.text is not None:
        verify_text(actual, expected.text, label)
    return frames


def _verify_cut_seams(expected: list[ExpectedClip], actual: dict,
                      total: int) -> None:
    cuts = sorted((clip for clip in expected if clip.lane == "cuts"),
                  key=lambda clip: clip.start)
    cursor = 0
    for cut in cuts:
        start, end = actual[cut.clip_id]
        if start != cursor or end <= start:
            raise PalmierError("timeline verification: conformed cuts have a gap or overlap")
        cursor = end
    if cuts and cursor != total:
        raise PalmierError("timeline verification: conformed cuts do not fill the timeline")


def _proof(timeline_id: str, lanes: dict, executor: Any,
           index: dict, expected_clips: list[ExpectedClip],
           actual_ranges: dict, actual_total: int) -> dict:
    count_lanes = (("mirror",) if lanes.get("mirror") else
                   ("cuts", "overlays", "texts"))
    expected_counts = {lane: sum(clip.lane == lane for clip in expected_clips)
                       for lane in count_lanes}
    actual_counts = {lane: sum(clip.lane == lane and clip.clip_id in index
                               for clip in expected_clips)
                     for lane in count_lanes}
    timing = {clip.clip_id: [clip.start, clip.end] for clip in expected_clips}
    actual_timing = {clip_id: list(frames) for clip_id, frames in actual_ranges.items()}
    proof = {
        "ok": True,
        "verifiedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "timelineId": timeline_id,
        "expected": {"totalFrames": executor.expected_end_frame,
                     "counts": expected_counts, "timing": timing},
        "actual": {"totalFrames": actual_total, "counts": actual_counts,
                   "timing": actual_timing},
        "keyframes": verify_keyframes(lanes, executor, index),
    }
    if lanes.get("mirror"):
        entry = lanes["mirror"]["entry"]
        proof["visualMaster"] = {
            "mediaRef": executor.media[entry["mediaKey"]],
            "masterHash": entry["masterHash"],
            "singleVisibleClip": True,
        }
    return proof


def verify_generated_timeline(client: Any, timeline_id: str,
                              lanes: dict, executor: Any) -> dict:
    """Read back the active shadow and fail unless its structure is exact."""
    timeline = client.call_json("get_timeline", {})
    if timeline.get("id") != timeline_id:
        raise PalmierError(
            f"timeline verification: active id {timeline.get('id')!r} is not {timeline_id!r}")
    index = _clip_index(timeline)
    if lanes.get("mirror"):
        index = {clip_id: clip for clip_id, clip in index.items()
                 if clip.get("mediaType") != "audio"
                 and "audio" not in str(clip.get("trackType", "video"))}
    expected_clips = _expected_clips(lanes, executor)
    accepted = {clip.clip_id for clip in expected_clips}
    accepted.update(executor.music_clip_ids)
    extras = sorted(set(index) - accepted)
    if extras:
        raise PalmierError(f"timeline verification: unexpected clips {extras}")
    actual_ranges = {}
    for expected in expected_clips:
        if expected.clip_id not in index:
            raise PalmierError(
                f"timeline verification: missing {expected.lane} clip {expected.clip_id}")
        actual_ranges[expected.clip_id] = _verify_one(expected, index[expected.clip_id])
    for clip_id in executor.music_clip_ids:
        if clip_id not in index:
            raise PalmierError(f"timeline verification: missing music clip {clip_id}")
    actual_total = _frame(timeline.get("totalFrames"), "totalFrames")
    if actual_total != executor.expected_end_frame:
        raise PalmierError(
            f"timeline verification: totalFrames {actual_total}, expected "
            f"{executor.expected_end_frame}")
    _verify_cut_seams(expected_clips, actual_ranges, actual_total)
    return _proof(timeline_id, lanes, executor, index, expected_clips,
                  actual_ranges, actual_total)
