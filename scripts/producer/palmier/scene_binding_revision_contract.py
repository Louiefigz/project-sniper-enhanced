"""Strict embedded-binding validation for Desktop scene revisions."""
from __future__ import annotations

import hashlib
import os

from graphics.scene_contract import SceneContractError, canonical_json
from palmier.mcp_client import PalmierError

_DIGITS = frozenset("0123456789abcdef")
_ENTRY_KEYS = {
    "bindingId", "unitId", "elementIds", "zIndex", "compositeMode",
    "timing", "media", "regeneration", "bindingHash",
}
_MEDIA_KEYS = (
    {"path", "sha256", "renderKey", "animationMapHash"},
    {"path", "sha256", "renderKey", "catalogSourceHash",
     "motionContractHash"},
)


def digest(value: object, label: str) -> str:
    """Require a canonical lowercase SHA-256 string."""
    if not isinstance(value, str) or len(value) != 64 \
            or any(char not in _DIGITS for char in value):
        raise PalmierError(f"{label} must be a lowercase SHA-256")
    return value


def _delivery_format(before: dict, after: dict) -> None:
    old = os.path.splitext(before["media"]["path"])[1].lower()
    new = os.path.splitext(after["media"]["path"])[1].lower()
    if not old or old != new:
        raise PalmierError("scene replacement changed its delivery format")


def _media(value: object) -> dict:
    if not isinstance(value, dict) or set(value) not in _MEDIA_KEYS \
            or not isinstance(value.get("path"), str):
        raise PalmierError("scene replacement media authority is malformed")
    for key, item in value.items():
        if key != "path":
            digest(item, f"scene replacement media {key}")
    return value


def _regeneration(value: object) -> dict:
    keys = {"kind", "sceneHash", "sceneVersion", "unitId"}
    if not isinstance(value, dict) or set(value) != keys:
        raise PalmierError("scene replacement regeneration is malformed")
    if value.get("kind") not in {"scene-render-unit", "scene-render-full"}:
        raise PalmierError("scene replacement regeneration kind is unsupported")
    digest(value.get("sceneHash"), "scene replacement scene hash")
    version = value.get("sceneVersion")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise PalmierError("scene replacement scene version is malformed")
    return value


def _entry(value: object, ident: str) -> dict:
    if not isinstance(value, dict) or set(value) != _ENTRY_KEYS \
            or value.get("bindingId") != ident:
        raise PalmierError("scene replacement binding entry is malformed")
    _media(value.get("media"))
    _regeneration(value.get("regeneration"))
    timing = value.get("timing")
    if not isinstance(timing, dict) or set(timing) != {
            "startFrame", "endFrameExclusive", "fps", "timelineMapHash"}:
        raise PalmierError("scene replacement timing is malformed")
    digest(value.get("bindingHash"), "scene replacement binding hash")
    body = {key: item for key, item in value.items()
            if key != "bindingHash"}
    try:
        actual = hashlib.sha256(canonical_json(body)).hexdigest()
    except SceneContractError as exc:
        raise PalmierError("scene replacement binding is not canonical") from exc
    if actual != value["bindingHash"]:
        raise PalmierError("scene replacement binding hash changed")
    return value


def validate_binding_pair(
    before_value: object,
    after_value: object,
    ident: str,
) -> tuple[dict, dict]:
    """Require a media-only change on one stable binding and frame window."""
    before = _entry(before_value, ident)
    after = _entry(after_value, ident)
    stable = ("unitId", "elementIds", "zIndex", "compositeMode", "timing")
    if any(before[key] != after[key] for key in stable):
        raise PalmierError("scene replacement changed placement or timing")
    old_regen = before["regeneration"]
    new_regen = after["regeneration"]
    same_regen = all(old_regen[key] == new_regen[key]
                     for key in ("kind", "unitId"))
    if not same_regen \
            or new_regen["sceneVersion"] != old_regen["sceneVersion"] + 1 \
            or new_regen["sceneHash"] == old_regen["sceneHash"]:
        raise PalmierError("scene replacement regeneration is not sequential")
    if before["media"] == after["media"]:
        raise PalmierError("scene replacement did not change media")
    _delivery_format(before, after)
    return before, after
