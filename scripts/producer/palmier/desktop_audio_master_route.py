"""Durable standalone-audio route contract for mastered-stereo."""
from __future__ import annotations

from palmier.desktop_audio_master_contract import \
    validate_mastered_stereo_assets
from palmier.desktop_audio_master_types import ELEMENT_ID
from palmier.desktop_audio_routes import (
    AudioRouteError, StandaloneLocation, locate_standalone, route_rows,
    track_clips, track_kind, track_readback_id, tracks)
from palmier.mcp_client import PalmierError

ROUTE_KEYS = {
    "routeKind", "elementId", "assetHash", "assetPath",
    "sourceFinalPath", "sourceFinalHash", "derivationProofPath",
    "derivationProofHash", "pcm", "projectFrameRate", "mediaRef",
    "clipId", "startFrame", "endFrame", "trackIdentity",
}
TRACK_IDENTITY_KEYS = {"id", "indexAtBinding"}
_TRACK_KEYS = {
    "id", "index", "label", "type", "trackType", "clips",
    "captionGroups", "linkedClips", "hidden", "muted", "syncLocked",
}
_CLIP_KEYS = {
    "id", "mediaRef", "mediaType", "sourceClipType", "frames",
    "trimStartFrame", "trimEndFrame", "volume", "speed",
}


def _location(timeline: dict, route: dict) -> StandaloneLocation:
    try:
        return locate_standalone(timeline, route.get("clipId"))
    except AudioRouteError as exc:
        raise PalmierError(exc.detail) from exc


def _schema(route: dict) -> None:
    identity = route.get("trackIdentity")
    valid_identity = isinstance(identity, dict) \
        and set(identity) == TRACK_IDENTITY_KEYS \
        and (identity.get("id") is None
             or isinstance(identity.get("id"), str)
             and bool(identity["id"])) \
        and isinstance(identity.get("indexAtBinding"), int) \
        and not isinstance(identity.get("indexAtBinding"), bool) \
        and identity["indexAtBinding"] >= 0
    if set(route) != ROUTE_KEYS or route.get("routeKind") != "standalone-audio" \
            or route.get("elementId") != ELEMENT_ID or not valid_identity:
        raise PalmierError("mastered-stereo standalone route schema is malformed")


def _clip(route: dict, location: StandaloneLocation) -> None:
    clip = location.clip
    declared_type = str(clip.get(
        "mediaType", clip.get("sourceClipType", ""))).lower()
    valid_type = not declared_type or "audio" in declared_type
    duration = route["endFrame"] - route["startFrame"]
    valid = not (set(clip) - _CLIP_KEYS) \
        and clip.get("mediaRef") == route.get("mediaRef") \
        and clip.get("frames") == [
            route.get("startFrame"), route.get("endFrame")] \
        and not isinstance(clip.get("audio"), dict) and valid_type \
        and clip.get("volume") in (None, 1, 1.0) \
        and clip.get("speed") in (None, 1, 1.0) \
        and clip.get("trimStartFrame") in (None, 0) \
        and clip.get("trimEndFrame") in (None, duration)
    if not valid:
        raise PalmierError(
            "mastered-stereo clip differs from its full-length unity binding")


def _track(route: dict, location: StandaloneLocation) -> None:
    track, identity = location.track, route["trackIdentity"]
    valid_id = identity["id"] is None \
        or track_readback_id(track) == identity["id"]
    clean = not (set(track) - _TRACK_KEYS) \
        and track_clips(track) == [location.clip] \
        and not (track.get("captionGroups") or []) \
        and track.get("linkedClips") in (None, 0) \
        and "audio" in track_kind(track) \
        and (track.get("hidden") is None or track.get("hidden") is False) \
        and (track.get("muted") is None or track.get("muted") is False) \
        and track.get("syncLocked") is True and valid_id
    if not clean:
        raise PalmierError(
            "mastered-stereo clip is not the sole locked audible track content")


def _unique_media(timeline: dict, route: dict) -> None:
    occurrences = [
        clip for track in tracks(timeline) for clip in track_clips(track)
        if clip.get("mediaRef") == route.get("mediaRef")]
    if occurrences != [_location(timeline, route).clip]:
        raise PalmierError("mastered-stereo media is absent or multiply stacked")


def _isolated(timeline: dict, location: StandaloneLocation) -> None:
    try:
        routes = route_rows(timeline)
    except AudioRouteError as exc:
        raise PalmierError(exc.detail) from exc
    audible = [row for row in routes if not row["muted"]]
    if len(audible) != 1 \
            or audible[0]["trackIndex"] != location.track_index:
        raise PalmierError(
            "mastered-stereo is not the sole audible content-bearing route")
    expected = [{
        "clipId": location.clip.get("id"),
        "mediaRef": location.clip.get("mediaRef"),
        "frames": location.clip.get("frames"),
    }]
    if audible[0]["linkedAudio"] or audible[0]["standaloneClips"] != expected:
        raise PalmierError(
            "mastered-stereo clip is not the sole locked audible track content")


def _integer_fps(value: object) -> int:
    if not isinstance(value, str) or not value.endswith("/1"):
        raise PalmierError("mastered-stereo route frame rate is malformed")
    try:
        fps = int(value[:-2])
    except ValueError as exc:
        raise PalmierError(
            "mastered-stereo route frame rate is malformed") from exc
    if fps <= 0 or value != f"{fps}/1":
        raise PalmierError("mastered-stereo route frame rate is malformed")
    return fps


def assert_standalone_route(route: dict, timeline: dict) -> StandaloneLocation:
    """Reprove bytes, timing, dedicated placement, and route isolation."""
    _schema(route)
    validate_mastered_stereo_assets(route)
    fps = _integer_fps(route.get("projectFrameRate"))
    if timeline.get("fps") != fps \
            or timeline.get("totalFrames") != route.get("endFrame") \
            or route.get("startFrame") != 0:
        raise PalmierError("mastered-stereo route differs from project timing")
    location = _location(timeline, route)
    _clip(route, location)
    _track(route, location)
    _unique_media(timeline, route)
    _isolated(timeline, location)
    return location
