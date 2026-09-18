"""Fail-closed audible-route authority for Desktop Palmier candidates."""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from typing import Any

from fingerprints import file_sha256
from palmier.desktop_audio_declaration import (
    EDITABLE_STEMS, MODES, read_audio_authority_declaration)
from palmier.desktop_audio_master_route import (
    ROUTE_KEYS, assert_standalone_route)
from palmier.desktop_audio_routes import (
    AudioRouteError, route_rows, track_clips, track_readback_id, tracks)
from palmier.mcp_client import PalmierError
from palmier.timeline_authority import TimelineSnapshot

_SHA = re.compile(r"^[0-9a-f]{64}$")
_LEGACY_KEYS = {
    "assetHash", "mediaRef", "clipId", "audioClipId", "trackId",
}


@dataclass(frozen=True)
class _Blocked(Exception):
    code: str
    detail: str


def _digest(value: dict) -> str:
    blob = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _block(code: str, detail: str) -> None:
    raise _Blocked(code, detail)


def _routes(timeline: dict) -> list[dict]:
    try:
        return route_rows(timeline)
    except AudioRouteError as exc:
        _block(exc.code, exc.detail)


def _authority(state: dict, mode: str) -> dict:
    authority = state.get("audioAuthority")
    expected = {"schemaVersion", "mode", "masterRoute"}
    if not isinstance(authority, dict) or set(authority) != expected \
            or authority.get("schemaVersion") != 1 \
            or authority.get("mode") != mode:
        _block(
            "missing-master-binding",
            "mastered-stereo requires one exact audioAuthority declaration")
    route = authority.get("masterRoute")
    keys = ROUTE_KEYS if isinstance(route, dict) \
        and route.get("routeKind") == "standalone-audio" else _LEGACY_KEYS
    if not isinstance(route, dict) or set(route) != keys:
        _block(
            "missing-master-binding",
            "mastered-stereo masterRoute has unknown or missing fields")
    return route


def _media_binding(state: dict, route: dict) -> None:
    digest = route.get("assetHash")
    if not isinstance(digest, str) or not _SHA.fullmatch(digest):
        _block("missing-master-binding", "master route has no asset SHA-256")
    row = (state.get("mediaLedger") or {}).get(digest)
    path = row.get("path") if isinstance(row, dict) else None
    expected_path = route.get("assetPath", path)
    valid = isinstance(row, dict) \
        and row.get("mediaRef") == route.get("mediaRef") \
        and path == expected_path and isinstance(path, str) \
        and os.path.isfile(path) and not os.path.islink(path) \
        and file_sha256(path) == digest
    if not valid:
        _block(
            "foreign-master-binding",
            "master route is not bound to current immutable media bytes")


def _legacy_master_link(timeline: dict, route: dict) -> int:
    matches = []
    rows = tracks(timeline)
    for track in rows:
        for clip in track_clips(track):
            if clip.get("id") == route.get("clipId"):
                matches.append(clip)
    if len(matches) != 1:
        _block("foreign-master-binding", "master clip is absent or duplicated")
    clip, audio = matches[0], matches[0].get("audio")
    valid = clip.get("mediaRef") == route.get("mediaRef") \
        and isinstance(audio, dict) \
        and audio.get("id") == route.get("audioClipId")
    index = audio.get("track") if isinstance(audio, dict) else None
    if not valid or isinstance(index, bool) or not isinstance(index, int) \
            or not 0 <= index < len(rows):
        _block("foreign-master-binding", "master clip identity changed")
    if track_readback_id(rows[index]) != route.get("trackId"):
        _block("foreign-master-binding", "master audio track identity changed")
    return index


def _assert_exact_reference_muted(state: dict, timeline: dict) -> None:
    reference = state.get("exactMasterReference")
    if not isinstance(reference, dict):
        return
    audio_id, target = reference.get("audioClipId"), None
    rows = tracks(timeline)
    for track in rows:
        for clip in track_clips(track):
            audio = clip.get("audio")
            if isinstance(audio, dict) and audio.get("id") == audio_id:
                target = audio.get("track")
    valid = isinstance(target, int) and not isinstance(target, bool) \
        and 0 <= target < len(rows) and rows[target].get("muted") is True
    if not valid:
        _block(
            "audible-exact-reference",
            "hidden exact-master reference audio is not explicitly muted")


def _legacy_route(state: dict, found: TimelineSnapshot,
                  route: dict) -> list[dict]:
    _media_binding(state, route)
    master_index = _legacy_master_link(found.timeline, route)
    routes = _routes(found.timeline)
    audible = [row for row in routes if not row["muted"]]
    if len(audible) != 1 or audible[0]["trackIndex"] != master_index:
        _block(
            "multiple-audible-routes",
            "mastered-stereo requires its bound master and no other audible route")
    expected = {
        "clipId": route["clipId"], "audioClipId": route["audioClipId"],
        "mediaRef": route["mediaRef"],
    }
    if audible[0]["linkedAudio"] != [expected] \
            or audible[0]["standaloneClips"]:
        _block(
            "contaminated-master-route",
            "mastered-stereo route contains audio beyond its bound master")
    return routes


def _standalone_route(state: dict, found: TimelineSnapshot,
                      route: dict) -> list[dict]:
    _media_binding(state, route)
    try:
        assert_standalone_route(route, found.timeline)
    except PalmierError as exc:
        detail = str(exc)
        if "sole audible" in detail:
            _block("multiple-audible-routes", detail)
        code = "contaminated-master-route" \
            if "sole locked audible track content" in detail else \
            "foreign-master-binding"
        _block(code, detail)
    return _routes(found.timeline)


def _mastered_stereo(state: dict, found: TimelineSnapshot,
                     mode: str) -> list[dict]:
    route = _authority(state, mode)
    _assert_exact_reference_muted(state, found.timeline)
    if route.get("routeKind") == "standalone-audio":
        return _standalone_route(state, found, route)
    return _legacy_route(state, found, route)


def audio_authority_receipt(state: dict,
                            found: TimelineSnapshot) -> dict:
    """Measure one candidate's audible-route authority without guessing."""
    content: dict[str, Any] = {
        "schemaVersion": 1, "kind": "palmier-audio-authority",
        "mode": None, "candidateFingerprint": found.fingerprint,
    }
    try:
        try:
            declaration = read_audio_authority_declaration(state)
        except PalmierError as exc:
            _block("undeclared-audio-authority", str(exc))
        mode = declaration["mode"]
        content["mode"] = mode
        if found.coverage.get("complete") is not True:
            _block(
                "incomplete-readback",
                "audio authority requires a complete current timeline readback")
        if declaration["status"] != "ready":
            _block(
                str(declaration["blockerCode"]),
                "bound Desktop worklist cannot yet prove this audible route")
        if mode == EDITABLE_STEMS:
            _block(
                "routing-readback-unsupported",
                "Palmier readback exposes no bound stem role/output-bus routing")
        routes = _mastered_stereo(state, found, mode)
        content.update({"status": "pass", "routes": routes})
    except (AudioRouteError, _Blocked) as blocked:
        code = blocked.code if isinstance(blocked, _Blocked) else blocked.code
        detail = blocked.detail
        content.update({
            "status": "blocked", "blockerCode": code, "detail": detail,
        })
    return {**content, "digest": _digest(content)}


def require_audio_authority(state: dict,
                            found: TimelineSnapshot) -> dict:
    """Return exact route proof or block Desktop export/QC."""
    receipt = audio_authority_receipt(state, found)
    if receipt["status"] != "pass":
        raise PalmierError(
            "Palmier audio authority blocked "
            f"[{receipt['blockerCode']}]: {receipt['detail']}")
    return receipt


def validate_audio_authority_receipt(receipt: object,
                                     fingerprint: str) -> dict:
    """Reject stale, malformed, or non-passing stored route proof."""
    if not isinstance(receipt, dict):
        raise PalmierError("Palmier export has no audio-route authority receipt")
    content = {key: value for key, value in receipt.items() if key != "digest"}
    valid = receipt.get("schemaVersion") == 1 \
        and receipt.get("kind") == "palmier-audio-authority" \
        and receipt.get("mode") in MODES \
        and receipt.get("status") == "pass" \
        and receipt.get("candidateFingerprint") == fingerprint \
        and receipt.get("digest") == _digest(content)
    if not valid:
        raise PalmierError("Palmier export audio-route authority is stale or invalid")
    return receipt
