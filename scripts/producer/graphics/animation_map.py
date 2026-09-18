"""Animation-map parsing and deterministic filmstrip checkpoints."""
from __future__ import annotations

import hashlib
import json
import re

from graphics.scene_contract import SceneContractError, canonical_json, validate_scene

_MAP = re.compile(
    r"window\.__sniperAnimationMap\s*=\s*(\[[\s\S]*?\])\s*;",
    re.MULTILINE,
)
_EVENT_KEYS = {
    "eventId", "unitId", "elementId", "property", "startFrame",
    "endFrameExclusive", "easing",
}
_PROPERTIES = {
    "opacity", "transform", "position", "scale", "rotation", "blur", "mask",
    "color", "text", "particles",
}
_EASING = {
    "linear", "power1.in", "power1.out", "power1.inOut", "power2.in",
    "power2.out", "power2.inOut", "power3.in", "power3.out",
    "power3.inOut", "back.out", "steps",
}
_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")


def parse_animation_map(html: str) -> list[dict]:
    """Read the JSON-only animation declaration embedded in a bundle entry."""
    if not isinstance(html, str):
        raise SceneContractError("animation-map source must be text")
    match = _MAP.search(html)
    if match is None:
        raise SceneContractError("bundle entry has no animation map")
    try:
        value = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise SceneContractError("animation map must be literal JSON") from exc
    if not isinstance(value, list):
        raise SceneContractError("animation map must be an array")
    return value


def _event(value: object, index: int, duration_frames: int) -> dict:
    label = f"animationMap[{index}]"
    if not isinstance(value, dict) or set(value) != _EVENT_KEYS:
        raise SceneContractError(f"{label} has an invalid field set")
    for key in ("eventId", "unitId", "elementId"):
        if not isinstance(value[key], str) or not _ID.fullmatch(value[key]):
            raise SceneContractError(f"{label}.{key} must be a stable id")
    if value["property"] not in _PROPERTIES:
        raise SceneContractError(f"{label}.property is unsupported")
    start, end = value["startFrame"], value["endFrameExclusive"]
    if type(start) is not int or type(end) is not int \
            or not 0 <= start < end <= duration_frames:
        raise SceneContractError(f"{label} has an invalid half-open frame range")
    if value["easing"] not in _EASING:
        raise SceneContractError(f"{label}.easing is unsupported")
    return value


def validate_animation_map(scene_value: object, value: object) -> list[dict]:
    """Bind events to the scene's stable unit/element identities and duration."""
    scene = validate_scene(scene_value)
    if not isinstance(value, list):
        raise SceneContractError("animation map must be an array")
    duration = (scene["timing"]["endFrameExclusive"]
                - scene["timing"]["startFrame"])
    events = [_event(item, index, duration)
              for index, item in enumerate(value)]
    event_ids = [item["eventId"] for item in events]
    if len(set(event_ids)) != len(event_ids):
        raise SceneContractError("animation event ids must be unique")
    units = {row["unitId"]: set(row["elementIds"])
             for row in scene["renderUnits"]}
    for event in events:
        if event["unitId"] not in units \
                or event["elementId"] not in units[event["unitId"]]:
            raise SceneContractError(
                f"animation event {event['eventId']} has a foreign target")
    ordered = sorted(events, key=lambda row: (
        row["startFrame"], row["endFrameExclusive"], row["eventId"]))
    if ordered != events:
        raise SceneContractError("animation map must use deterministic frame order")
    return events


def animation_map_digest(scene: dict, events: list[dict]) -> str:
    """Content identity used by scene render and Palmier receipts."""
    valid = validate_animation_map(scene, events)
    payload = {"sceneId": scene["sceneId"], "events": valid}
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def filmstrip_frames(scene_value: object, events: list[dict]) -> tuple[int, ...]:
    """Entrance, lands, extrema, middle, exit, and after-window checkpoints."""
    scene = validate_scene(scene_value)
    valid = validate_animation_map(scene, events)
    duration = (scene["timing"]["endFrameExclusive"]
                - scene["timing"]["startFrame"])
    frames = {0, duration // 2, duration - 1, duration}
    for event in valid:
        start, end = event["startFrame"], event["endFrameExclusive"]
        frames.update({start, min(start + 1, duration), (start + end - 1) // 2,
                       max(start, end - 1), min(end, duration)})
    return tuple(sorted(frame for frame in frames if 0 <= frame <= duration))
