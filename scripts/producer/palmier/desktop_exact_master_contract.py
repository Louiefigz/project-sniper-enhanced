"""Durable invariant for one hidden and muted exact-master reference."""
from __future__ import annotations

from dataclasses import dataclass

from palmier.desktop_exact_master_plan import (ADD_OP, DISABLE_OP,
                                               ELEMENT_ID)
from palmier.desktop_state import read_record
from palmier.mcp_client import PalmierError

_TRACK_KEYS = {
    "id", "index", "label", "type", "trackType", "clips",
    "captionGroups", "linkedClips", "hidden", "muted", "syncLocked",
}
_CLIP_KEYS = {
    "id", "mediaRef", "mediaType", "sourceClipType", "frames", "audio",
    "trimStartFrame", "trimEndFrame",
}
_AUDIO_KEYS = {"id", "track", "trimStartFrame", "trimEndFrame"}


@dataclass(frozen=True)
class ReferenceLocation:
    """Current exact-master clip and its dedicated linked track pair."""

    clip: dict
    video_track: dict
    audio_track: dict
    video_index: int
    audio_index: int
    audio_clip_id: str


def _steps(state: dict) -> list[dict]:
    operations = state.get("operations")
    path = operations.get("path") if isinstance(operations, dict) else None
    if not isinstance(path, str):
        return []
    value = read_record(path, "operation manifest")
    rows = value.get("steps") if isinstance(value, dict) else None
    return [row for row in rows or [] if isinstance(row, dict)]


def exact_master_step(state: dict, op: str) -> dict | None:
    """Return the unique exact-master worklist step."""
    matches = [row for row in _steps(state) if row.get("op") == op]
    if len(matches) > 1:
        raise PalmierError(f"Desktop worklist repeats {op}")
    return matches[0] if matches else None


def exact_master_declared(state: dict) -> bool:
    """Whether the active worklist requires the exact-master reference."""
    return exact_master_step(state, ADD_OP) is not None


def _track_type(track: dict) -> str:
    return str(track.get("type", track.get("trackType", ""))).lower()


def _locate(timeline: dict, record: dict) -> ReferenceLocation:
    tracks = timeline.get("tracks")
    if not isinstance(tracks, list):
        raise PalmierError("exact-master readback has no tracks")
    matches = []
    for index, track in enumerate(tracks):
        if not isinstance(track, dict):
            continue
        for clip in track.get("clips") or []:
            if isinstance(clip, dict) and clip.get("id") == record.get("clipId"):
                matches.append((index, track, clip))
    if len(matches) != 1:
        raise PalmierError("exact-master reference clip is absent or duplicated")
    video_index, video_track, clip = matches[0]
    audio = clip.get("audio")
    audio_index = audio.get("track") if isinstance(audio, dict) else None
    audio_id = audio.get("id") if isinstance(audio, dict) else None
    valid = isinstance(audio_index, int) and not isinstance(audio_index, bool) \
        and 0 <= audio_index < len(tracks) and isinstance(audio_id, str)
    if not valid or not isinstance(tracks[audio_index], dict):
        raise PalmierError("exact-master linked audio is absent from readback")
    return ReferenceLocation(
        clip, video_track, tracks[audio_index], video_index, audio_index,
        audio_id)


def _assert_clip(record: dict, location: ReferenceLocation) -> None:
    clip, audio = location.clip, location.clip.get("audio")
    expected = (record.get("mediaRef"),
                [record.get("startFrame"), record.get("endFrame")])
    if (clip.get("mediaRef"), clip.get("frames")) != expected:
        raise PalmierError("exact-master clip differs from its media/window binding")
    if set(clip) - _CLIP_KEYS or not isinstance(audio, dict) \
            or set(audio) - _AUDIO_KEYS:
        raise PalmierError("exact-master clip exposes unapproved edit properties")
    if record.get("audioClipId") != location.audio_clip_id:
        raise PalmierError("exact-master linked audio identity changed")


def _assert_tracks(timeline: dict, location: ReferenceLocation) -> None:
    video, audio = location.video_track, location.audio_track
    if set(video) - _TRACK_KEYS or set(audio) - _TRACK_KEYS:
        raise PalmierError("exact-master track exposes an unknown property")
    video_clips = video.get("clips") or []
    clean = len(video_clips) == 1 and video_clips[0] == location.clip \
        and not (video.get("captionGroups") or [])
    if not clean or "video" not in _track_type(video):
        raise PalmierError("exact-master reference is stacked on a shared track")
    audio_clean = not (audio.get("clips") or []) \
        and not (audio.get("captionGroups") or []) \
        and audio.get("linkedClips") == 1
    if not audio_clean or "audio" not in _track_type(audio):
        raise PalmierError("exact-master audio is not on a dedicated linked track")
    if video.get("hidden") is not True or video.get("syncLocked") is not True:
        raise PalmierError("exact-master video reference is visible or unlocked")
    if audio.get("muted") is not True or audio.get("syncLocked") is not True:
        raise PalmierError("exact-master audio reference is audible or unlocked")
    refs = [clip for track in timeline.get("tracks") or []
            if isinstance(track, dict) for clip in track.get("clips") or []
            if isinstance(clip, dict)
            and clip.get("mediaRef") == location.clip.get("mediaRef")]
    if refs != [location.clip]:
        raise PalmierError("exact-master media is visibly or multiply stacked")


def assert_reference_record(record: dict, timeline: dict,
                            coverage: dict | None) -> ReferenceLocation:
    """Prove one exact reference from a fresh, complete timeline readback."""
    if not isinstance(coverage, dict) or coverage.get("complete") is not True:
        raise PalmierError("exact-master reference readback is incomplete")
    if record.get("status") != "ready":
        raise PalmierError("exact-master reference still requires disable readback")
    fps = record.get("fps")
    valid_rate = isinstance(fps, int) and not isinstance(fps, bool) and fps > 0
    if not valid_rate or timeline.get("fps") != fps \
            or record.get("frameRate") != f"{fps}/1":
        raise PalmierError("exact-master reference project timebase changed")
    location = _locate(timeline, record)
    _assert_clip(record, location)
    _assert_tracks(timeline, location)
    return location


def _refresh_indices(state: dict, location: ReferenceLocation) -> None:
    record = state["exactMasterReference"]
    record.update({"videoTrackIndex": location.video_index,
                   "audioTrackIndex": location.audio_index})
    elements = (state.get("elementLedger") or {}).get("elements") or {}
    row = elements.get(ELEMENT_ID)
    if isinstance(row, dict):
        row.update({"trackIndex": location.video_index,
                    "audioTrackIndex": location.audio_index})


def assert_reference_ready(state: dict, timeline: dict,
                           coverage: dict | None) -> None:
    """Keep a previously verified reference hidden through later mutations."""
    record = state.get("exactMasterReference")
    if not isinstance(record, dict) or record.get("status") != "ready":
        return
    _refresh_indices(state, assert_reference_record(record, timeline, coverage))


def require_exact_master_ready(state: dict, timeline: dict,
                               coverage: dict | None) -> None:
    """Block stage advance/QC until a declared reference is safely disabled."""
    record = state.get("exactMasterReference")
    if exact_master_declared(state) and not isinstance(record, dict):
        raise PalmierError("exact-master reference has not been placed")
    if isinstance(record, dict) and record.get("status") != "ready":
        raise PalmierError("exact-master reference disable step is incomplete")
    assert_reference_ready(state, timeline, coverage)


def _touched_track_indices(args: dict) -> set[int]:
    result = {value for value in args.get("remove") or []
              if isinstance(value, int) and not isinstance(value, bool)}
    for row in args.get("set") or []:
        if isinstance(row, dict) and isinstance(row.get("index"), int) \
                and not isinstance(row["index"], bool):
            result.add(row["index"])
    for key in ("trackIndex", "toTrack", "fromTrack"):
        value = args.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            result.add(value)
    for key in ("entries", "moves", "splits"):
        for row in args.get(key) or []:
            if isinstance(row, dict):
                result.update(_touched_track_indices(row))
    return result


def _contains_identity(value: object, identities: set[str]) -> bool:
    if isinstance(value, str):
        return value in identities
    if isinstance(value, list):
        return any(_contains_identity(item, identities) for item in value)
    if isinstance(value, dict):
        return any(_contains_identity(item, identities)
                   for item in value.values())
    return False


def assert_reference_mutation_allowed(tool: str, args: dict,
                                      state: dict) -> None:
    """Reserve the disable operation and protect a ready reference's flags."""
    record = state.get("exactMasterReference")
    if not isinstance(record, dict):
        return
    status = record.get("status")
    if status == "disable-required":
        if tool != "manage_tracks":
            raise PalmierError(
                "exact-master reference must be hidden/muted before more edits")
        return
    if status != "ready":
        raise PalmierError("exact-master reference state is malformed")
    identities = {value for value in (
        record.get("clipId"), record.get("audioClipId"),
        record.get("mediaRef")) if isinstance(value, str)}
    if _contains_identity(args, identities):
        raise PalmierError("exact-master reference identities are immutable")
    protected = {value for value in (
        record.get("videoTrackIndex"), record.get("audioTrackIndex"))
        if isinstance(value, int) and not isinstance(value, bool)}
    if protected & _touched_track_indices(args):
        raise PalmierError("exact-master reference tracks are immutable")
