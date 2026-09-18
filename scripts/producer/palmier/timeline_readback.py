"""Complete, bounded Palmier timeline readback through frame windows."""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any

from palmier.mcp_client import PalmierError
from palmier.timeline_readback_coverage import (
    CAPTION_DETAIL_CAP, default_timeline_coverage)

MAX_WINDOW_REQUESTS = 4096
_RUNTIME_ROOT_KEYS = {"canGenerate", "currentFrame", "timelines"}


@dataclass(frozen=True)
class CaptionGroup:
    """Stable identity and expected cardinality for one caption group."""

    track_index: int
    group_index: int
    group_id: str
    clip_count: int


@dataclass(frozen=True)
class CompleteTimelineReadback:
    """Merged timeline plus evidence that every caption row was observed."""

    timeline: dict
    coverage: dict


def _canonical(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PalmierError(f"Palmier timeline is not canonical JSON: {exc}") from exc


def _timeline(value: object) -> dict:
    if not isinstance(value, dict):
        raise PalmierError("get_timeline did not return an object")
    total, tracks = value.get("totalFrames"), value.get("tracks")
    if not isinstance(value.get("id"), str) or not value["id"]:
        raise PalmierError("get_timeline did not return a timeline id")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise PalmierError("get_timeline did not return valid totalFrames")
    if not isinstance(tracks, list):
        raise PalmierError("get_timeline did not return tracks")
    _require_complete_regular_clips(tracks)
    return value


def _require_complete_regular_clips(tracks: list) -> None:
    """Fail closed if Palmier truncates ordinary clip rows."""
    for track in tracks:
        if not isinstance(track, dict):
            continue
        total = track.get("totalClips")
        clips = track.get("clips")
        if total is None:
            continue
        valid = (isinstance(total, int) and not isinstance(total, bool)
                 and total >= 0 and isinstance(clips, list))
        if not valid or len(clips) != total:
            raise PalmierError(
                "Palmier regular clip readback is incomplete: "
                f"expected {total!r}, read "
                f"{len(clips) if isinstance(clips, list) else 'malformed'}")


def _caption_groups(timeline: dict) -> list[CaptionGroup]:
    found: list[CaptionGroup] = []
    for track_index, track in enumerate(timeline["tracks"]):
        if not isinstance(track, dict):
            raise PalmierError("get_timeline returned a malformed track")
        groups = track.get("captionGroups") or []
        if not isinstance(groups, list):
            raise PalmierError("get_timeline returned malformed caption groups")
        for group_index, group in enumerate(groups):
            found.append(_caption_group(group, track_index, group_index))
    return found


def _caption_group(value: object, track: int, index: int) -> CaptionGroup:
    if not isinstance(value, dict):
        raise PalmierError("get_timeline returned a malformed caption group")
    count, group_id = value.get("clipCount"), value.get("captionGroupId")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise PalmierError("caption group has no trustworthy clipCount")
    if count and (not isinstance(group_id, str) or not group_id):
        raise PalmierError("populated caption group has no stable id")
    stable_id = group_id if isinstance(group_id, str) else f"empty:{track}:{index}"
    return CaptionGroup(track, index, stable_id, count)


def _without_runtime(value: dict) -> dict:
    return {key: item for key, item in value.items()
            if key not in _RUNTIME_ROOT_KEYS}


def _compact_projection(value: dict) -> dict:
    projected = copy.deepcopy(_without_runtime(value))
    for track in projected.get("tracks", []):
        if not isinstance(track, dict):
            continue
        track.pop("totalClips", None)
        for group in track.get("captionGroups") or []:
            if isinstance(group, dict):
                group.pop("clips", None)
    return projected


def _track_identities(value: dict) -> list[tuple[object, object, object]]:
    identities = []
    for index, track in enumerate(value["tracks"]):
        if not isinstance(track, dict):
            raise PalmierError("get_timeline returned a malformed track")
        identities.append((track.get("id"), track.get("index", index),
                           track.get("type", track.get("trackType"))))
    return identities


def _validate_page(base: dict, page: object,
                   window: tuple[int, int]) -> dict:
    checked = _timeline(page)
    if checked["id"] != base["id"]:
        raise PalmierError("Palmier timeline id drifted during paged readback")
    if checked["totalFrames"] != base["totalFrames"]:
        raise PalmierError("Palmier duration drifted during paged readback")
    if _track_identities(checked) != _track_identities(base):
        raise PalmierError("Palmier track identity drifted during paged readback")
    start, end = window
    if start < 0 or end <= start or end > base["totalFrames"]:
        raise PalmierError("Palmier readback requested an invalid frame window")
    return checked


def _caption_row(value: object, window: tuple[int, int]) -> list:
    if not isinstance(value, list) or len(value) != 4:
        raise PalmierError("Palmier returned a malformed caption detail row")
    clip_id, start, end, text = value
    valid = (isinstance(clip_id, str) and bool(clip_id)
             and isinstance(start, int) and not isinstance(start, bool)
             and isinstance(end, int) and not isinstance(end, bool)
             and 0 <= start < end and isinstance(text, str))
    if not valid:
        raise PalmierError("Palmier returned an invalid caption detail row")
    if start >= window[1] or end <= window[0]:
        raise PalmierError("Palmier returned caption detail outside its frame window")
    return value


def _page_rows(page: dict, specs: list[CaptionGroup],
               window: tuple[int, int]) -> dict[tuple[int, str], list[list]]:
    known = {(row.track_index, row.group_id): row for row in specs}
    rows: dict[tuple[int, str], list[list]] = {}
    for track_index, track in enumerate(page["tracks"]):
        for group in track.get("captionGroups") or []:
            group_id = group.get("captionGroupId") if isinstance(group, dict) else None
            key = (track_index, group_id)
            if key not in known:
                raise PalmierError("Palmier caption-group identity drifted during readback")
            details = group.get("clips")
            if not isinstance(details, list):
                raise PalmierError("Palmier omitted requested caption detail")
            rows[key] = [_caption_row(item, window) for item in details]
    return rows


def _needs_split(rows: dict[tuple[int, str], list[list]],
                 specs: list[CaptionGroup], width: int) -> bool:
    expected = {(row.track_index, row.group_id): row.clip_count for row in specs}
    return width > 1 and any(
        expected[key] > CAPTION_DETAIL_CAP
        and len(details) >= CAPTION_DETAIL_CAP
        for key, details in rows.items())


def _merge_rows(merged: dict, owners: dict,
                rows: dict[tuple[int, str], list[list]]) -> None:
    for key, details in rows.items():
        bucket = merged.setdefault(key, {})
        for row in details:
            clip_id = row[0]
            if clip_id in owners and owners[clip_id] != key:
                raise PalmierError("Palmier caption id moved between groups")
            if clip_id in bucket and _canonical(bucket[clip_id]) != _canonical(row):
                raise PalmierError("Palmier caption overlap returned inconsistent rows")
            owners[clip_id], bucket[clip_id] = key, row


def _prove_partition(windows: list[tuple[int, int]], total: int) -> list[list[int]]:
    ordered = sorted(windows)
    cursor = 0
    for start, end in ordered:
        if start != cursor or end <= start:
            raise PalmierError("Palmier caption windows have a gap or overlap")
        cursor = end
    if cursor != total:
        raise PalmierError("Palmier caption windows do not cover the timeline")
    return [[start, end] for start, end in ordered]


def _merge_timeline(base: dict, specs: list[CaptionGroup],
                    rows: dict) -> dict:
    merged = copy.deepcopy(base)
    for spec in specs:
        details = list(rows.get((spec.track_index, spec.group_id), {}).values())
        if len(details) != spec.clip_count:
            raise PalmierError(
                f"Palmier caption detail incomplete for {spec.group_id!r}: "
                f"expected {spec.clip_count}, read {len(details)}")
        details.sort(key=lambda row: (row[1], row[2], row[0]))
        group = merged["tracks"][spec.track_index]["captionGroups"][spec.group_index]
        group["clips"] = details
    return merged


def _coverage(specs: list[CaptionGroup], rows: dict, windows: list[list[int]],
              requests: int) -> dict:
    groups = [{
        "trackIndex": spec.track_index, "captionGroupId": spec.group_id,
        "expectedClipCount": spec.clip_count,
        "readClipCount": len(rows.get((spec.track_index, spec.group_id), {})),
    } for spec in specs]
    capped = [{
        "trackIndex": spec.track_index,
        "captionGroupId": spec.group_id,
        "expectedClipCount": spec.clip_count,
    } for spec in specs if spec.clip_count > CAPTION_DETAIL_CAP]
    return {
        "scope": "mcp-readable-timeline",
        "captionDetailRequested": True,
        "strategy": "bounded-frame-windows",
        "complete": True, "limitations": [], "cappedCaptionGroups": capped,
        "windowCount": len(windows), "requestCount": requests,
        "closingCompactRead": len(windows) > 1,
        "frameCoverage": windows, "captionGroups": groups,
    }


def _read_caption_windows(client: Any, base: dict,
                          specs: list[CaptionGroup]) -> CompleteTimelineReadback:
    total, requests = base["totalFrames"], 0
    pending, leaves = [(0, total)], []
    merged: dict = {}
    owners: dict[str, tuple[int, str]] = {}
    while pending:
        if requests >= MAX_WINDOW_REQUESTS:
            raise PalmierError("Palmier caption readback exceeded its request bound")
        window = pending.pop()
        page = _validate_page(base, client.call_json("get_timeline", {
            "startFrame": window[0], "endFrame": window[1],
            "captionDetail": True}), window)
        requests += 1
        rows = _page_rows(page, specs, window)
        if requests == 1 and _canonical(_compact_projection(page)) \
                != _canonical(_compact_projection(base)):
            raise PalmierError("Palmier changed during caption readback")
        if _needs_split(rows, specs, window[1] - window[0]):
            middle = (window[0] + window[1]) // 2
            pending.extend([(middle, window[1]), (window[0], middle)])
            continue
        _merge_rows(merged, owners, rows)
        leaves.append(window)
    windows = _prove_partition(leaves, total)
    if requests > 1:
        if requests >= MAX_WINDOW_REQUESTS:
            raise PalmierError("Palmier caption readback exceeded its request bound")
        final = _timeline(client.call_json("get_timeline", {}))
        if _canonical(_without_runtime(final)) != _canonical(_without_runtime(base)):
            raise PalmierError("Palmier changed during paged caption readback")
        requests += 1
    timeline = _merge_timeline(base, specs, merged)
    return CompleteTimelineReadback(
        timeline, _coverage(specs, merged, windows, requests))


def read_complete_timeline(client: Any) -> CompleteTimelineReadback:
    """Read all MCP-visible edit state, recursively paging capped captions."""
    base = copy.deepcopy(_timeline(client.call_json("get_timeline", {})))
    specs = _caption_groups(base)
    if not any(spec.clip_count for spec in specs):
        coverage = {
            "scope": "mcp-readable-timeline",
            "captionDetailRequested": False,
            "strategy": "compact-no-caption-rows",
            "complete": True, "limitations": [], "cappedCaptionGroups": [],
            "windowCount": 0, "requestCount": 1, "frameCoverage": [],
            "captionGroups": [], "closingCompactRead": False,
        }
        return CompleteTimelineReadback(base, coverage)
    if base["totalFrames"] < 1:
        raise PalmierError("populated captions cannot exist on an empty timeline")
    return _read_caption_windows(client, base, specs)
