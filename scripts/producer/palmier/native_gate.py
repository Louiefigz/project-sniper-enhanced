"""Pre-critic deterministic gate for Palmier-native mutation plans."""
from __future__ import annotations

import hashlib
import math
from typing import Any

from palmier.mcp_client import PalmierError
from palmier.native_content_gate import validate_native_content
from palmier.native_plan import validate_native_plan

_CONTROL = {chr(value) for value in range(32)} - {"\n", "\t"}
_TIMING = {"durationFrames", "trimStartFrame", "trimEndFrame", "speed"}
_VISUAL = {"opacity", "transform", "blendMode"}


def _text(value: object, label: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit \
            or any(char in value for char in _CONTROL):
        raise PalmierError(f"native gate {label} is empty, unsafe, or too long")
    return value


def _clip_classes(timeline: dict) -> dict[str, set[str]]:
    found = {"visual": set(), "audio": set(), "text": set()}
    for track in timeline.get("tracks") or []:
        if not isinstance(track, dict):
            continue
        kind = str(track.get("type") or "video").lower()
        for clip in track.get("clips") or []:
            if not isinstance(clip, dict):
                continue
            clip_id = clip.get("id")
            if isinstance(clip_id, str):
                bucket = "audio" if kind == "audio" else \
                    "text" if kind in ("text", "captions") else "visual"
                found[bucket].add(clip_id)
            audio = clip.get("audio")
            if isinstance(audio, dict) and isinstance(audio.get("id"), str):
                found["audio"].add(audio["id"])
    return found


def _ids(args: dict) -> list[str]:
    value = args.get("clipIds")
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return [args["clipId"]] if isinstance(args.get("clipId"), str) else []


def _require_targets(ids: list[str], allowed: set[str], label: str) -> None:
    if ids and any(item not in allowed for item in ids):
        raise PalmierError(f"native gate {label} targets the wrong linked A/V lane")


def _track_is_picture(timeline: dict, index: object) -> bool:
    tracks = timeline.get("tracks") or []
    if not isinstance(index, int) or isinstance(index, bool) \
            or not 0 <= index < len(tracks) or not isinstance(tracks[index], dict):
        return False
    return str(tracks[index].get("type") or "video").lower() \
        not in ("audio", "text", "captions")


def _linked_av(tool: str, args: dict, classes: dict[str, set[str]],
               timeline: dict) -> None:
    targets = _ids(args)
    if tool == "denoise_audio" or (tool == "set_keyframes" and args.get("property") == "volume"):
        _require_targets(targets, classes["audio"], tool)
    elif tool == "set_keyframes":
        _require_targets(targets, classes["visual"] | classes["text"], tool)
    elif tool == "set_clip_properties":
        keys = set(args) - {"clipIds"}
        if "volume" in keys and keys - {"volume"}:
            raise PalmierError("native gate separates audio volume from picture properties")
        allowed = classes["audio"] if "volume" in keys else classes["visual"] | classes["text"]
        _require_targets(targets, allowed, tool)
    elif tool == "update_text":
        _require_targets(targets, classes["text"], tool)
    elif tool == "ripple_delete_ranges" and "clipId" in args:
        _require_targets(targets, classes["visual"], tool)
    elif tool == "split_clips" and args.get("splits"):
        split_ids = [row["clipId"] for row in args["splits"]]
        _require_targets(split_ids, classes["visual"], tool)
    if tool == "ripple_delete_ranges" and args.get("ignoreSyncLockedTracks") is True:
        raise PalmierError("native gate may not bypass sync-locked linked A/V tracks")
    if tool in ("ripple_delete_ranges", "split_clips") and "trackIndex" in args \
            and not _track_is_picture(timeline, args["trackIndex"]):
        raise PalmierError(f"native gate {tool} track is not a picture lane")


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(value)


def _transform(value: object) -> None:
    if not isinstance(value, dict):
        raise PalmierError("native gate transform must be an object")
    allowed = {"width", "height", "centerX", "centerY", "scale",
               "rotation", "position", "crop"}
    if set(value) - allowed:
        raise PalmierError("native gate transform contains an unknown property")
    for key in ("width", "height", "scale"):
        if key in value and (not _finite(value[key]) or not 0.1 <= value[key] <= 4):
            raise PalmierError(f"native gate transform.{key} must be 0.1-4")
    for key in ("centerX", "centerY"):
        if key in value and (not _finite(value[key]) or not 0 <= value[key] <= 1):
            raise PalmierError(f"native gate transform.{key} must be normalized")
    if "rotation" in value and (not _finite(value["rotation"]) or not -180 <= value["rotation"] <= 180):
        raise PalmierError("native gate transform.rotation is out of bounds")
    for key, length in (("position", 2), ("crop", 4)):
        row = value.get(key)
        if row is not None and (not isinstance(row, list) or len(row) != length
                                or any(not _finite(item) for item in row)):
            raise PalmierError(f"native gate transform.{key} is malformed")
    position, crop = value.get("position"), value.get("crop")
    if position is not None and any(not -2 <= item <= 2 for item in position):
        raise PalmierError("native gate transform.position is out of bounds")
    if crop is not None and (any(not 0 <= item <= 1 for item in crop)
                             or crop[0] + crop[2] > 1 or crop[1] + crop[3] > 1
                             or crop[2] <= 0 or crop[3] <= 0):
        raise PalmierError("native gate transform.crop must be a valid normalized rectangle")


def _properties(tool: str, args: dict, total: int) -> None:
    if tool != "set_clip_properties":
        return
    if "speed" in args and not 0.25 <= args["speed"] <= 4:
        raise PalmierError("native gate speed must stay within 0.25-4x")
    if "durationFrames" in args and not 1 <= args["durationFrames"] <= total:
        raise PalmierError("native gate durationFrames is out of bounds")
    if "trimStartFrame" in args and "trimEndFrame" in args \
            and args["trimEndFrame"] <= args["trimStartFrame"]:
        raise PalmierError("native gate trim range is unordered")
    if "transform" in args:
        _transform(args["transform"])
    if "blendMode" in args:
        _text(args["blendMode"], "blendMode", 40)


def _range_envelope(tool: str, args: dict, timeline: dict) -> None:
    if tool == "remove_words":
        words = args.get("words") or args.get("matches") or []
        if len(words) > 32 or any(len(item) > 80 or any(c in item for c in _CONTROL)
                                  for item in words):
            raise PalmierError("native gate remove_words selection is too broad")
    if tool == "split_clips":
        rows = args.get("splits") or args.get("frames") or []
        if len(rows) > 24:
            raise PalmierError("native gate split request is too broad")
    if tool != "ripple_delete_ranges":
        return
    ranges = args["ranges"]
    if len(ranges) > 12 or any(ranges[i][0] < ranges[i - 1][1]
                               for i in range(1, len(ranges))):
        raise PalmierError("native gate ripple ranges must be sorted and non-overlapping")
    removed = sum(end - start for start, end in ranges)
    fps = timeline.get("fps") if _finite(timeline.get("fps")) else 24
    if removed > max(0, timeline["totalFrames"] - fps):
        raise PalmierError("native gate refuses to remove the entire working timeline")


def _keyframes(args: dict) -> None:
    if args.get("property") is None:
        return
    rows, prop = args["keyframes"], args["property"]
    frames = [row[0] for row in rows]
    if len(rows) < 2 or any(frames[i] <= frames[i - 1] for i in range(1, len(frames))):
        raise PalmierError("native gate keyframes must have two strictly increasing rows")
    values = [row[1] for row in rows]
    bounds = {"volume": (0, 1), "opacity": (0, 1),
              "scale": (0.5, 2), "rotation": (-45, 45)}
    if prop in bounds:
        low, high = bounds[prop]
        if any(not _finite(value) or not low <= value <= high for value in values):
            raise PalmierError(f"native gate {prop} keyframes are out of bounds")
    elif prop == "position":
        if any(not isinstance(value, list) or len(value) != 2
               or any(not _finite(item) or not -2 <= item <= 2 for item in value)
               for value in values):
            raise PalmierError("native gate position keyframes are malformed")
    elif prop == "crop":
        if any(not isinstance(value, list) or len(value) != 4
               or any(not _finite(item) or not 0 <= item <= 1 for item in value)
               for value in values):
            raise PalmierError("native gate crop keyframes must be normalized")
    _smooth_keyframes(prop, rows)


def _distance(left: object, right: object) -> float:
    if _finite(left) and _finite(right):
        return abs(float(right) - float(left))
    if isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
        return max(abs(float(b) - float(a)) for a, b in zip(left, right))
    return math.inf


def _smooth_keyframes(prop: str, rows: list) -> None:
    thresholds = {"volume": 0.15, "opacity": 0.2, "scale": 0.03,
                  "rotation": 3, "position": 0.03, "crop": 0.03}
    threshold = thresholds[prop]
    for previous, current in zip(rows, rows[1:]):
        if current[0] - previous[0] < 3 \
                and _distance(previous[1], current[1]) > threshold:
            raise PalmierError(
                f"native gate {prop} motion changes materially in fewer than 3 frames")


def _caption_and_text(tool: str, args: dict, fps: float) -> None:
    if tool == "add_texts":
        minimum = max(3, round(fps * 0.25))
        for entry in args["entries"]:
            _text(entry.get("content"), "text content", 500)
            if entry["endFrame"] - entry["startFrame"] < minimum:
                raise PalmierError("native gate text is too brief to read")
    if tool == "update_text" and "content" in args:
        _text(args["content"], "updated text", 500)
    if tool not in ("update_text", "add_captions"):
        return
    if "fontSize" in args and (not _finite(args["fontSize"])
                               or not 12 <= args["fontSize"] <= 220):
        raise PalmierError("native gate caption fontSize must be 12-220")
    if "maxWords" in args and (not isinstance(args["maxWords"], int)
                               or isinstance(args["maxWords"], bool)
                               or not 1 <= args["maxWords"] <= 8):
        raise PalmierError("native gate captions require 1-8 words per group")
    for key in ("isBold", "isItalic", "censorProfanity"):
        if key in args and not isinstance(args[key], bool):
            raise PalmierError(f"native gate {key} must be boolean")
    for key in ("fontName", "color", "borderColor", "backgroundColor",
                "highlightColor", "alignment", "animation"):
        if key in args:
            _text(args[key], key, 120)
    if "transform" in args:
        _transform(args["transform"])


def _audio(tool: str, args: dict) -> None:
    if tool == "denoise_audio" and "enabled" in args \
            and not isinstance(args["enabled"], bool):
        raise PalmierError("native gate denoise enabled must be boolean")


def _layout(tool: str, args: dict, classes: dict[str, set[str]]) -> None:
    if tool != "apply_layout":
        return
    _text(args.get("layout"), "layout", 80)
    used: list[str] = []
    for slot in args["slots"]:
        used.extend(slot["clipIds"])
    _require_targets(used, classes["visual"] | classes["text"], tool)
    if len(used) != len(set(used)):
        raise PalmierError("native gate layout assigns one clip to multiple slots")
    if "fit" in args and args["fit"] not in ("cover", "contain", "fill"):
        raise PalmierError("native gate layout fit is unsupported")


def validate_native_gate(plan: object, authority: dict, request: str,
                         expected_lanes: list[str]) -> dict:
    """Validate native vocabulary, request binding, and lane craft rules."""
    validated = validate_native_plan(plan, authority)
    _text(request, "operator request", 4_000)
    if hashlib.sha256(request.encode("utf-8")).hexdigest() != validated["requestHash"]:
        raise PalmierError("native gate request hash does not match the operator request")
    if validated["lanes"] != expected_lanes:
        raise PalmierError("native gate lane ownership differs from controller scope")
    timeline = authority["timeline"]
    validate_native_content(validated, timeline, request)
    classes = _clip_classes(timeline)
    for operation in validated["operations"]:
        tool, args = operation["tool"], operation["args"]
        _linked_av(tool, args, classes, timeline)
        _properties(tool, args, timeline["totalFrames"])
        _range_envelope(tool, args, timeline)
        if tool == "set_keyframes":
            _keyframes(args)
        _caption_and_text(tool, args, float(timeline.get("fps") or 24))
        _audio(tool, args)
        _layout(tool, args, classes)
    return validated
