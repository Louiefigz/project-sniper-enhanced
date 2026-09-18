"""Closed scalar validation for full external-media decode observations."""
from __future__ import annotations

import math

_FACT_KEYS = {
    "mediaKind", "durationSeconds", "sizeBytes", "width", "height",
    "videoStreams", "audioStreams", "streamCount", "declaredFrames",
}
_INTEGER_KEYS = {
    "sizeBytes", "videoStreams", "audioStreams",
    "streamCount", "declaredFrames",
}
_MEDIA_KINDS = {"timed-media", "still-image", "font", "svg"}


def _probe_facts(value: object) -> tuple[dict, dict]:
    if type(value) is not dict or set(value) != {
            "schemaVersion", "ok", "decoded", "facts"}:
        raise RuntimeError("external-media probe result is malformed")
    facts = value.get("facts")
    valid = (
        value.get("schemaVersion") == 1
        and value.get("ok") is True
        and value.get("decoded") is True
        and type(facts) is dict
        and set(facts) == _FACT_KEYS
    )
    if not valid:
        raise RuntimeError("external-media probe did not prove a full decode")
    return value, facts


def _validate_scalars(facts: dict) -> None:
    numbers = [facts[key] for key in _FACT_KEYS if key != "mediaKind"]
    numeric = (
        all(type(item) in (int, float) for item in numbers)
        and all(math.isfinite(item) for item in numbers)
    )
    if not numeric:
        raise RuntimeError("external-media probe facts are not numeric")
    if facts["mediaKind"] not in _MEDIA_KINDS:
        raise RuntimeError("external-media probe kind is unsupported")
    if any(type(facts[key]) is not int for key in _INTEGER_KEYS):
        raise RuntimeError("external-media probe count facts are not integers")


def _validate_limits(facts: dict, limits: object) -> None:
    timed = facts["mediaKind"] == "timed-media"
    valid = (
        (not timed or 0 < facts["durationSeconds"]
         <= limits.max_duration_seconds)
        and (timed or facts["durationSeconds"] == 0)
        and 0 < facts["sizeBytes"] <= limits.max_bytes
        and 0 <= facts["width"] <= limits.max_width
        and 0 <= facts["height"] <= limits.max_height
        and 1 <= facts["streamCount"] <= limits.max_streams
        and 0 <= facts["declaredFrames"] <= limits.max_frames
    )
    if not valid:
        raise RuntimeError("external-media probe facts exceed admission limits")


def _kind_is_consistent(facts: dict) -> bool:
    kind = facts["mediaKind"]
    video, audio = facts["videoStreams"], facts["audioStreams"]
    width, height = facts["width"], facts["height"]
    frames, streams = facts["declaredFrames"], facts["streamCount"]
    if video < 0 or audio < 0 or video + audio > streams:
        return False
    if kind == "timed-media":
        video_valid = video > 0 and width > 0 and height > 0 and frames > 0
        audio_only = video == 0 and width == height == frames == 0
        return video + audio > 0 and (video_valid or audio_only)
    if kind == "still-image":
        return video > 0 and audio == 0 and width > 0 \
            and height > 0 and frames > 0
    if kind == "svg":
        return (video, audio, streams, frames) == (1, 0, 1, 1) \
            and width > 0 and height > 0
    return (video, audio, streams, frames, width, height) \
        == (0, 0, 1, 0, 0, 0)


def validate_probe_document(value: object, limits: object) -> dict:
    """Accept only a bounded full-decode result with exact scalar facts."""
    document, facts = _probe_facts(value)
    _validate_scalars(facts)
    _validate_limits(facts, limits)
    if not _kind_is_consistent(facts):
        raise RuntimeError("external-media probe kind facts are inconsistent")
    return document
