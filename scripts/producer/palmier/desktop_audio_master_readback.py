"""Exact add/isolate readback for the standalone mastered-stereo route."""
from __future__ import annotations

import copy
from typing import Any

from palmier.desktop_audio_master_binding import ADD_KIND, ROUTE_KIND
from palmier.desktop_audio_master_contract import \
    validate_mastered_stereo_assets
from palmier.desktop_audio_master_route import (
    ROUTE_KEYS, assert_standalone_route)
from palmier.desktop_audio_master_types import ELEMENT_ID
from palmier.desktop_audio_routes import (
    AudioRouteError, locate_standalone, standalone_track_identity,
    track_clips, track_kind, tracks)
from palmier.desktop_element_types import ElementObservation
from palmier.desktop_ledger import clip_inventory
from palmier.desktop_state import now
from palmier.mcp_client import PalmierError

_RUNTIME_ROOT_KEYS = {"canGenerate", "currentFrame", "timelines"}
_TRACK_KEYS = {
    "id", "index", "label", "type", "trackType", "clips",
    "captionGroups", "linkedClips", "hidden", "muted", "syncLocked",
}
_CLIP_KEYS = {
    "id", "mediaRef", "mediaType", "sourceClipType", "frames",
    "trimStartFrame", "trimEndFrame", "volume", "speed",
}


def _edit_root(timeline: dict) -> dict:
    return {key: value for key, value in timeline.items()
            if key != "tracks" and key not in _RUNTIME_ROOT_KEYS}


def _stable(value: Any, parent: str | None = None) -> Any:
    if isinstance(value, list):
        return [_stable(item, parent) for item in value]
    if not isinstance(value, dict):
        return value
    return {key: _stable(item, key) for key, item in value.items()
            if key not in {"index", "label"}
            and not (parent == "audio" and key == "track")}


def _coverage(observation: ElementObservation, label: str) -> None:
    if not isinstance(observation.coverage, dict) \
            or observation.coverage.get("complete") is not True:
        raise PalmierError(f"mastered-stereo {label} readback is incomplete")


def _added_location(observation: ElementObservation,
                    binding: dict) -> tuple[dict, int]:
    before, after = observation.before, observation.after
    if _edit_root(before) != _edit_root(after):
        raise PalmierError("mastered-stereo add changed unrelated timeline state")
    old, new = clip_inventory(before), clip_inventory(after)
    removed, added = set(old) - set(new), set(new) - set(old)
    if removed or len(added) != 1:
        raise PalmierError("mastered-stereo add changed unrelated clip identities")
    try:
        location = locate_standalone(after, next(iter(added)))
    except AudioRouteError as exc:
        raise PalmierError(exc.detail) from exc
    clip, track = location.clip, location.track
    duration = binding["endFrame"] - binding["startFrame"]
    clean_clip = not (set(clip) - _CLIP_KEYS) \
        and clip.get("mediaRef") == binding["mediaRef"] \
        and clip.get("frames") == [
            binding["startFrame"], binding["endFrame"]] \
        and clip.get("volume") in (None, 1, 1.0) \
        and clip.get("speed") in (None, 1, 1.0) \
        and clip.get("trimStartFrame") in (None, 0) \
        and clip.get("trimEndFrame") in (None, duration)
    clean_track = not (set(track) - _TRACK_KEYS) \
        and track_clips(track) == [clip] \
        and not (track.get("captionGroups") or []) \
        and track.get("linkedClips") in (None, 0) \
        and "audio" in track_kind(track) \
        and all(track.get(key) is None or track.get(key) is False
                for key in ("hidden", "muted", "syncLocked"))
    if not clean_clip or not clean_track:
        raise PalmierError(
            "mastered-stereo add did not create one clean dedicated audio track")
    if len(tracks(after)) != len(tracks(before)) + 1:
        raise PalmierError("mastered-stereo add did not create exactly one track")
    retained = [_stable(row) for index, row in enumerate(tracks(after))
                if index != location.track_index]
    if retained != [_stable(row) for row in tracks(before)]:
        raise PalmierError("mastered-stereo add drifted unrelated tracks")
    return clip, location.track_index


def _route(binding: dict, clip: dict, track_index: int, after: dict) -> dict:
    try:
        location = locate_standalone(after, clip["id"])
    except AudioRouteError as exc:
        raise PalmierError(exc.detail) from exc
    route = {
        "routeKind": "standalone-audio", "elementId": ELEMENT_ID,
        "assetHash": binding["assetHash"],
        "assetPath": binding["assetPath"],
        "sourceFinalPath": binding["sourceFinalPath"],
        "sourceFinalHash": binding["sourceFinalHash"],
        "derivationProofPath": binding["derivationProofPath"],
        "derivationProofHash": binding["derivationProofHash"],
        "pcm": binding["pcm"],
        "projectFrameRate": binding["projectFrameRate"],
        "mediaRef": binding["mediaRef"], "clipId": clip["id"],
        "startFrame": binding["startFrame"],
        "endFrame": binding["endFrame"],
        "trackIdentity": standalone_track_identity(location),
    }
    if route["trackIdentity"]["indexAtBinding"] != track_index:
        raise PalmierError("mastered-stereo track identity changed during readback")
    return route


def _record_add(observation: ElementObservation, binding: dict) -> None:
    validate_mastered_stereo_assets(binding)
    clip, track_index = _added_location(observation, binding)
    route = _route(binding, clip, track_index, observation.after)
    state = observation.state
    state["audioMasterRoute"] = {
        "schemaVersion": 1, "status": "routing-required",
        **route, "addedAt": now(),
    }
    ledger = state.setdefault("elementLedger", {
        "schemaVersion": 2, "elements": {}, "tombstones": {}})
    elements = ledger.setdefault("elements", {})
    if ELEMENT_ID in elements:
        raise PalmierError("mastered-stereo element identity already exists")
    elements[ELEMENT_ID] = {
        "status": "routing-required", "lane": "audio-master",
        "clipId": clip["id"], "mediaRef": binding["mediaRef"],
        "assetHash": binding["assetHash"], "assetPath": binding["assetPath"],
        "startFrame": binding["startFrame"], "endFrame": binding["endFrame"],
        "trackIndex": track_index, "version": 1, "generation": 1,
        "updatedAt": now(),
    }
    ledger["updatedAt"] = now()


def _normalize(value: Any) -> Any:
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {key: _normalize(item) for key, item in value.items()
            if not (key in {"hidden", "muted", "syncLocked"}
                    and item is False)}


def _expected_route(before: dict, args: dict) -> dict:
    expected = copy.deepcopy(before)
    rows = args.get("set")
    if not isinstance(rows, list) or not rows:
        raise PalmierError("mastered-stereo route binding has no track changes")
    seen = set()
    for row in rows:
        allowed = {"index", "muted", "syncLocked"}
        index = row.get("index") if isinstance(row, dict) else None
        if not isinstance(row, dict) or set(row) - allowed \
                or isinstance(index, bool) or not isinstance(index, int) \
                or index in seen or not 0 <= index < len(tracks(expected)):
            raise PalmierError("mastered-stereo route binding is malformed")
        if "audio" not in track_kind(tracks(expected)[index]):
            raise PalmierError("mastered-stereo routing targeted a video track")
        seen.add(index)
        for flag in ("muted", "syncLocked"):
            if flag not in row:
                continue
            if not isinstance(row[flag], bool):
                raise PalmierError("mastered-stereo route flag is not boolean")
            if row[flag]:
                tracks(expected)[index][flag] = True
            else:
                tracks(expected)[index].pop(flag, None)
    return expected


def _record_route(observation: ElementObservation, binding: dict) -> None:
    _coverage(observation, "route")
    expected = _expected_route(observation.before, binding["expectedArgs"])
    if _normalize(expected) != _normalize(observation.after):
        raise PalmierError(
            "mastered-stereo routing changed unrelated state or flags")
    provisional = observation.state.get("audioMasterRoute")
    if not isinstance(provisional, dict) \
            or provisional.get("status") != "routing-required":
        raise PalmierError("mastered-stereo routing lost its provisional route")
    route = {key: provisional[key] for key in ROUTE_KEYS}
    assert_standalone_route(route, observation.after)
    observation.state["audioAuthority"] = {
        "schemaVersion": 1, "mode": "mastered-stereo",
        "masterRoute": route,
    }
    observation.state.pop("audioMasterRoute", None)
    row = ((observation.state.get("elementLedger") or {})
           .get("elements") or {}).get(ELEMENT_ID)
    if not isinstance(row, dict):
        raise PalmierError("mastered-stereo routing lost its element ledger")
    row.update({"status": "current", "muted": False, "syncLocked": True,
                "updatedAt": now()})
    observation.state["elementLedger"]["updatedAt"] = now()


def observe_mastered_stereo_operation(
        observation: ElementObservation) -> bool:
    """Consume a mastered-stereo binding and return whether it was handled."""
    binding = observation.pending.get("binding")
    if not isinstance(binding, dict):
        return False
    if binding.get("kind") == ADD_KIND:
        _coverage(observation, "add")
        _record_add(observation, binding)
        return True
    if binding.get("kind") == ROUTE_KIND:
        _record_route(observation, binding)
        return True
    return False
