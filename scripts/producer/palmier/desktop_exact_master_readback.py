"""Strict add/disable readback for the Desktop exact-master reference."""
from __future__ import annotations

import copy
from typing import Any

from palmier.desktop_element_types import ElementObservation
from palmier.desktop_exact_master_binding import ADD_KIND, DISABLE_KIND
from palmier.desktop_exact_master_contract import assert_reference_record
from palmier.desktop_ledger import clip_inventory
from palmier.desktop_state import now
from palmier.mcp_client import PalmierError

_RUNTIME_ROOT_KEYS = {"canGenerate", "currentFrame", "timelines"}
_TRACK_KEYS = {
    "id", "index", "label", "type", "trackType", "clips",
    "captionGroups", "linkedClips", "hidden", "muted", "syncLocked",
}
_CLIP_KEYS = {
    "id", "mediaRef", "mediaType", "sourceClipType", "frames", "audio",
    "trimStartFrame", "trimEndFrame",
}
_AUDIO_KEYS = {"id", "track", "trimStartFrame", "trimEndFrame"}


def _edit_root(timeline: dict) -> dict:
    return {key: value for key, value in timeline.items()
            if key != "tracks" and key not in _RUNTIME_ROOT_KEYS}


def _stable(value: Any, parent: str | None = None) -> Any:
    if isinstance(value, list):
        return [_stable(item, parent) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key in {"index", "label"} or (parent == "audio" and key == "track"):
            continue
        result[key] = _stable(item, key)
    return result


def _tracks(timeline: dict) -> list[dict]:
    rows = timeline.get("tracks")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise PalmierError("exact-master readback has malformed tracks")
    return rows


def _assert_root_unchanged(before: dict, after: dict) -> None:
    if _edit_root(before) != _edit_root(after):
        raise PalmierError("exact-master mutation changed unrelated timeline state")


def _reference_clip(after: dict, binding: dict,
                    added: set[str]) -> tuple[int, dict]:
    matches = []
    for index, track in enumerate(_tracks(after)):
        for clip in track.get("clips") or []:
            if isinstance(clip, dict) and clip.get("id") in added \
                    and clip.get("mediaRef") == binding["mediaRef"] \
                    and clip.get("frames") == [
                        binding["startFrame"], binding["endFrame"]]:
                matches.append((index, clip))
    if len(matches) != 1:
        raise PalmierError("exact-master add readback is absent or ambiguous")
    return matches[0]


def _assert_provisional_track(after: dict, video_index: int,
                              clip: dict) -> tuple[int, str]:
    tracks, audio = _tracks(after), clip.get("audio")
    if set(clip) - _CLIP_KEYS or not isinstance(audio, dict) \
            or set(audio) - _AUDIO_KEYS:
        raise PalmierError("exact-master add exposed unknown clip properties")
    audio_index, audio_id = audio.get("track"), audio.get("id")
    if not isinstance(audio_index, int) or isinstance(audio_index, bool) \
            or not isinstance(audio_id, str) or not 0 <= audio_index < len(tracks):
        raise PalmierError("exact-master add has no linked audio identity")
    video, audio_track = tracks[video_index], tracks[audio_index]
    if set(video) - _TRACK_KEYS or set(audio_track) - _TRACK_KEYS:
        raise PalmierError("exact-master add exposed unknown track properties")
    video_clean = (video.get("clips") or []) == [clip] \
        and not (video.get("captionGroups") or []) \
        and "video" in str(video.get("type", video.get("trackType", ""))).lower()
    audio_clean = not (audio_track.get("clips") or []) \
        and not (audio_track.get("captionGroups") or []) \
        and audio_track.get("linkedClips") == 1 \
        and "audio" in str(audio_track.get(
            "type", audio_track.get("trackType", ""))).lower()
    defaults = not any(track.get(flag) is True for track, flag in (
        (video, "hidden"), (video, "syncLocked"),
        (audio_track, "muted"), (audio_track, "syncLocked")))
    if not video_clean or not audio_clean or not defaults:
        raise PalmierError(
            "exact-master add did not create one provisional dedicated pair")
    return audio_index, audio_id


def _assert_retained_tracks(before: dict, after: dict,
                            removed_indices: set[int]) -> None:
    old = [_stable(track) for track in _tracks(before)]
    retained = [_stable(track) for index, track in enumerate(_tracks(after))
                if index not in removed_indices]
    if old != retained:
        raise PalmierError("exact-master add drifted unrelated tracks or clips")


def _assert_add_delta(observation: ElementObservation,
                      binding: dict) -> tuple[int, int, dict, str]:
    before, after = observation.before, observation.after
    _assert_root_unchanged(before, after)
    old, new = clip_inventory(before), clip_inventory(after)
    removed, added = set(old) - set(new), set(new) - set(old)
    if removed or len(added) != 1:
        raise PalmierError("exact-master add changed unrelated clip identities")
    video_index, clip = _reference_clip(after, binding, added)
    audio_index, audio_id = _assert_provisional_track(
        after, video_index, clip)
    if video_index == audio_index or len(_tracks(after)) != len(_tracks(before)) + 2:
        raise PalmierError("exact-master add did not create exactly two tracks")
    _assert_retained_tracks(before, after, {video_index, audio_index})
    occurrences = [row for row in new.values()
                   if row.get("mediaRef") == binding["mediaRef"]]
    if occurrences != [{**clip, "_trackIndex": video_index}]:
        raise PalmierError("exact-master media was multiply stacked")
    return video_index, audio_index, clip, audio_id


def _record_add(state: dict, binding: dict, location: tuple) -> None:
    video_index, audio_index, clip, audio_id = location
    record = {
        "schemaVersion": 1, "status": "disable-required",
        "elementId": binding["elementId"], "assetHash": binding["assetHash"],
        "assetPath": binding["assetPath"], "mediaRef": binding["mediaRef"],
        "clipId": clip["id"], "audioClipId": audio_id,
        "startFrame": binding["startFrame"], "endFrame": binding["endFrame"],
        "fps": binding["fps"], "frameRate": binding["frameRate"],
        "videoTrackIndex": video_index, "audioTrackIndex": audio_index,
        "addedAt": now(),
    }
    ledger = state.setdefault("elementLedger", {
        "schemaVersion": 2, "elements": {}, "tombstones": {}})
    elements = ledger.setdefault("elements", {})
    if binding["elementId"] in elements:
        raise PalmierError("exact-master element identity already exists")
    elements[binding["elementId"]] = {
        "status": "disable-required", "lane": "exact-master-reference",
        "clipId": clip["id"], "audioClipId": audio_id,
        "mediaRef": binding["mediaRef"], "assetHash": binding["assetHash"],
        "assetPath": binding["assetPath"],
        "startFrame": binding["startFrame"], "endFrame": binding["endFrame"],
        "fps": binding["fps"], "frameRate": binding["frameRate"],
        "trackIndex": video_index, "audioTrackIndex": audio_index,
        "version": 1, "generation": 1, "updatedAt": now(),
    }
    ledger["updatedAt"] = now()
    state["exactMasterReference"] = record


def _expected_disabled(before: dict, binding: dict) -> dict:
    expected = copy.deepcopy(before)
    tracks = _tracks(expected)
    video, audio = binding["videoTrackIndex"], binding["audioTrackIndex"]
    if any(index < 0 or index >= len(tracks) for index in (video, audio)):
        raise PalmierError("exact-master disable track index is stale")
    tracks[video].update({"hidden": True, "syncLocked": True})
    tracks[audio].update({"muted": True, "syncLocked": True})
    return expected


def _observe_disable(observation: ElementObservation, binding: dict) -> None:
    state, record = observation.state, observation.state.get(
        "exactMasterReference")
    if not isinstance(record, dict) or record.get("status") != "disable-required":
        raise PalmierError("exact-master disable has no provisional reference")
    expected = _expected_disabled(observation.before, binding)
    expected_edit = {key: value for key, value in expected.items()
                     if key not in _RUNTIME_ROOT_KEYS}
    actual_edit = {key: value for key, value in observation.after.items()
                   if key not in _RUNTIME_ROOT_KEYS}
    if actual_edit != expected_edit:
        raise PalmierError(
            "exact-master disable changed unrelated state or left a route active")
    ready = {**record, "status": "ready", "hidden": True, "muted": True,
             "syncLocked": True, "verifiedAt": now()}
    assert_reference_record(ready, observation.after, observation.coverage)
    state["exactMasterReference"] = ready
    row = ((state.get("elementLedger") or {}).get("elements") or {}).get(
        binding["elementId"])
    if not isinstance(row, dict):
        raise PalmierError("exact-master disable lost its element ledger")
    row.update({"status": "current", "hidden": True, "muted": True,
                "syncLocked": True, "updatedAt": now()})
    state["elementLedger"]["updatedAt"] = now()


def observe_exact_master_operation(observation: ElementObservation) -> bool:
    """Consume an exact-master binding, returning whether it was handled."""
    binding = observation.pending.get("binding")
    if not isinstance(binding, dict):
        return False
    if binding.get("kind") == ADD_KIND:
        if not isinstance(observation.coverage, dict) \
                or observation.coverage.get("complete") is not True:
            raise PalmierError("exact-master add readback is incomplete")
        _record_add(
            observation.state, binding, _assert_add_delta(observation, binding))
        return True
    if binding.get("kind") == DISABLE_KIND:
        _observe_disable(observation, binding)
        return True
    return False
