"""Canonical content-bearing audio-route inventory for Desktop readback."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AudioRouteError(Exception):
    """A classified failure while interpreting audio-route readback."""

    code: str
    detail: str


@dataclass(frozen=True)
class StandaloneLocation:
    """One standalone clip and its current containing audio track."""

    clip: dict
    track: dict
    track_index: int


def _fail(code: str, detail: str) -> None:
    raise AudioRouteError(code, detail)


def tracks(timeline: dict) -> list[dict]:
    """Return complete track rows or fail closed."""
    value = timeline.get("tracks")
    if not isinstance(value, list) \
            or any(not isinstance(row, dict) for row in value):
        _fail("malformed-audio-readback", "timeline tracks are incomplete")
    return value


def track_clips(track: dict) -> list[dict]:
    """Return structural clips from one track."""
    value = track.get("clips", [])
    if value is None:
        return []
    if not isinstance(value, list) \
            or any(not isinstance(row, dict) for row in value):
        _fail("malformed-audio-readback", "track clips are incomplete")
    return value


def track_kind(track: dict) -> str:
    """Normalize the declared Palmier track type."""
    return str(track.get("type", track.get("trackType", ""))).lower()


def track_readback_id(track: dict) -> str | None:
    """Return an optional observed ID; absence is valid Palmier vocabulary."""
    value = track.get("id")
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        _fail("malformed-audio-readback", "track id is malformed")
    return value


def _record_link(clip: dict, count: int,
                 linked: dict[int, list[dict]]) -> None:
    audio = clip.get("audio")
    if not isinstance(audio, dict):
        return
    index = audio.get("track")
    if isinstance(index, bool) or not isinstance(index, int) \
            or not 0 <= index < count:
        _fail("malformed-audio-readback", "linked audio has no valid track")
    if not isinstance(audio.get("id"), str) or not audio["id"]:
        _fail("malformed-audio-readback", "linked audio has no stable id")
    linked.setdefault(index, []).append({
        "clipId": clip.get("id"), "audioClipId": audio["id"],
        "mediaRef": clip.get("mediaRef"),
    })


def _linked_audio(rows: list[dict]) -> dict[int, list[dict]]:
    linked: dict[int, list[dict]] = {}
    for track in rows:
        for clip in track_clips(track):
            _record_link(clip, len(rows), linked)
    return linked


def _is_audio(track: dict, linked: list[dict]) -> bool:
    clips = track_clips(track)
    kind = track_kind(track)
    if not kind and (clips or linked):
        _fail(
            "routing-readback-unsupported",
            "a populated track exposes no audio/video type")
    if "audio" in kind and "video" not in kind:
        return True
    audio_only = any(
        "audio" in str(row.get(
            "mediaType", row.get("sourceClipType", ""))).lower()
        and "video" not in str(row.get(
            "mediaType", row.get("sourceClipType", ""))).lower()
        for row in clips)
    if "video" in kind and "audio" not in kind:
        if audio_only or linked:
            _fail(
                "malformed-audio-readback",
                "video track contains audio-route content")
        return False
    if clips or linked:
        _fail(
            "routing-readback-unsupported",
            "populated track exposes an unknown audio/video type")
    return False


def _validate_flags(track: dict) -> None:
    for key in ("hidden", "muted", "syncLocked"):
        value = track.get(key)
        if value is not None and not isinstance(value, bool):
            _fail(
                "malformed-audio-readback",
                f"audio track {key} flag is not boolean")


def _validate_link_count(track: dict, linked: list[dict]) -> None:
    declared = track.get("linkedClips")
    if declared is None:
        return
    if isinstance(declared, bool) or not isinstance(declared, int) \
            or declared < 0 or declared != len(linked):
        _fail(
            "malformed-audio-readback",
            "audio track linkedClips disagrees with linked clip readback")


def route_rows(timeline: dict) -> list[dict]:
    """Inventory only content-bearing audio routes; ignore empty tracks."""
    rows = tracks(timeline)
    links = _linked_audio(rows)
    result = []
    for index, track in enumerate(rows):
        linked = links.get(index, [])
        if not _is_audio(track, linked):
            continue
        clips = track_clips(track)
        if not linked and not clips:
            continue
        _validate_link_count(track, linked)
        _validate_flags(track)
        result.append({
            "trackId": track_readback_id(track), "trackIndex": index,
            "muted": track.get("muted") is True,
            "syncLocked": track.get("syncLocked") is True,
            "linkedAudio": linked,
            "standaloneClips": [{
                "clipId": clip.get("id"), "mediaRef": clip.get("mediaRef"),
                "frames": clip.get("frames"),
            } for clip in clips],
        })
    return result


def locate_standalone(timeline: dict, clip_id: object) -> StandaloneLocation:
    """Resolve one standalone clip by ID and derive its current track."""
    if not isinstance(clip_id, str) or not clip_id:
        _fail("missing-master-binding", "standalone master has no clip id")
    matches = []
    for index, track in enumerate(tracks(timeline)):
        for clip in track_clips(track):
            if clip.get("id") == clip_id:
                matches.append(StandaloneLocation(clip, track, index))
    if len(matches) != 1:
        _fail(
            "foreign-master-binding",
            "standalone master clip is absent or duplicated")
    location = matches[0]
    if "audio" not in track_kind(location.track):
        _fail(
            "foreign-master-binding",
            "standalone master clip is not on an audio track")
    return location


def standalone_track_identity(location: StandaloneLocation) -> dict:
    """Persist observed identity without pretending index or ID is stable."""
    return {
        "id": track_readback_id(location.track),
        "indexAtBinding": location.track_index,
    }
