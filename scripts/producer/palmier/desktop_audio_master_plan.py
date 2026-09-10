"""Compile mastered-stereo into an exact Desktop worklist."""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from typing import Any

from fingerprints import file_sha256
from palmier.desktop_audio_declaration import MASTERED_STEREO
from palmier.desktop_audio_master_contract import \
    validate_mastered_stereo_assets
from palmier.desktop_audio_master_media import (
    MasteredStereoAsset, MasteredStereoRequest, asset_dict,
    prepare_mastered_stereo_asset)
from palmier.desktop_audio_master_route import ROUTE_KEYS
from palmier.desktop_audio_master_types import (
    ELEMENT_ID, LANE, MEDIA_KEY, PLACEMENT_OP, ROUTE_OP)
from palmier.mcp_client import PalmierError

_SHA = re.compile(r"^[0-9a-f]{64}$")
_PRESERVATION_KEYS = {
    "schemaVersion", "mode", "basisFingerprint",
    "previousOperations", "route", "routeHash",
}


@dataclass(frozen=True)
class MasteredStereoPlanRequest:
    """All authority needed to compile or preserve the audio route."""

    plan: dict
    inputs: Any
    authority: Any
    project: dict
    target_frames: int
    cache_dir: str


def _mode(plan: dict) -> str:
    return str(plan.get("audioAuthorityMode", "editable-stems"))


def _digest(value: object) -> str:
    try:
        blob = json.dumps(
            value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PalmierError(
            "mastered-stereo route is not canonical JSON") from exc
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _route(project: dict) -> dict | None:
    authority = project.get("audioAuthority")
    value = authority.get("masterRoute") \
        if isinstance(authority, dict) else None
    if value is None:
        return None
    valid = authority.get("mode") == MASTERED_STEREO \
        and isinstance(value, dict) and set(value) == ROUTE_KEYS \
        and value.get("routeKind") == "standalone-audio"
    if not valid:
        raise PalmierError("existing mastered-stereo route is malformed")
    return value


def _existing(project: dict, target_frames: int) -> MasteredStereoAsset | None:
    route = _route(project)
    if route is None:
        return None
    validate_mastered_stereo_assets(route)
    fps = (project.get("projectSettings") or {}).get("fps")
    expected_rate = f"{int(fps)}/1" if isinstance(fps, (int, float)) \
        and not isinstance(fps, bool) and float(fps).is_integer() else None
    if route.get("startFrame") != 0 \
            or route.get("endFrame") != target_frames \
            or route.get("projectFrameRate") != expected_rate:
        raise PalmierError(
            "existing mastered-stereo route differs from current project timing")
    return MasteredStereoAsset(
        route["assetPath"], route["assetHash"],
        route["sourceFinalPath"], route["sourceFinalHash"],
        route["derivationProofPath"], route["derivationProofHash"],
        route["pcm"], route["projectFrameRate"], route["endFrame"])


def _prior_operations(project: dict) -> tuple[dict, dict]:
    receipt = project.get("operations")
    path = receipt.get("path") if isinstance(receipt, dict) else None
    digest = receipt.get("hash") if isinstance(receipt, dict) else None
    valid = isinstance(receipt, dict) \
        and set(receipt) == {"path", "hash"} \
        and isinstance(path, str) and os.path.isabs(path) \
        and os.path.isfile(path) and not os.path.islink(path) \
        and isinstance(digest, str) and _SHA.fullmatch(digest) \
        and file_sha256(path) == digest
    if not valid:
        raise PalmierError(
            "existing mastered-stereo route has no immutable prior worklist")
    try:
        with open(path, encoding="utf-8") as handle:
            content = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise PalmierError(
            f"existing mastered-stereo worklist is unreadable: {exc}") from exc
    if not isinstance(content, dict):
        raise PalmierError("existing mastered-stereo worklist is malformed")
    return {"path": path, "hash": digest}, content


def _placement_matches(route: dict, content: dict) -> bool:
    rows = [row for row in content.get("steps") or []
            if isinstance(row, dict) and row.get("op") == PLACEMENT_OP]
    if len(rows) != 1:
        return False
    row = rows[0]
    keys = (
        "assetPath", "assetHash", "sourceFinalPath", "sourceFinalHash",
        "derivationProofPath", "derivationProofHash", "pcm",
        "projectFrameRate", "startFrame", "endFrame",
    )
    return all(row.get(key) == route.get(key) for key in keys)


def _preservation_matches(route: dict, content: dict) -> bool:
    capability = content.get("capability")
    prior = capability.get("preservedMasteredStereoAuthority") \
        if isinstance(capability, dict) else None
    return preserved_mastered_stereo_ready(prior) \
        and prior.get("routeHash") == _digest(route)


def _declares_mastered_stereo(content: dict) -> bool:
    capability = content.get("capability")
    audio = capability.get("audioAuthority") \
        if isinstance(capability, dict) else None
    return isinstance(audio, dict) \
        and audio.get("mode") == MASTERED_STEREO \
        and audio.get("status") == "ready" \
        and audio.get("blockerCode") is None


def _preserved_route_ready(route: object) -> bool:
    if not isinstance(route, dict) or set(route) != ROUTE_KEYS \
            or route.get("routeKind") != "standalone-audio" \
            or route.get("startFrame") != 0:
        return False
    try:
        validate_mastered_stereo_assets(route)
    except (KeyError, TypeError, PalmierError):
        return False
    return True


def preserved_mastered_stereo_ready(value: object) -> bool:
    """Validate the immutable proof embedded in a later-stage worklist."""
    if not isinstance(value, dict) or set(value) != _PRESERVATION_KEYS:
        return False
    route, previous = value.get("route"), value.get("previousOperations")
    valid_previous = isinstance(previous, dict) \
        and set(previous) == {"path", "hash"} \
        and isinstance(previous.get("path"), str) \
        and os.path.isabs(previous["path"]) \
        and os.path.isfile(previous["path"]) \
        and not os.path.islink(previous["path"]) \
        and isinstance(previous.get("hash"), str) \
        and _SHA.fullmatch(previous["hash"]) \
        and file_sha256(previous["path"]) == previous["hash"]
    return value.get("schemaVersion") == 1 \
        and value.get("mode") == MASTERED_STEREO \
        and isinstance(value.get("basisFingerprint"), str) \
        and _SHA.fullmatch(value["basisFingerprint"]) \
        and valid_previous and _preserved_route_ready(route) \
        and value.get("routeHash") == _digest(route)


def preserved_mastered_stereo_authority(
        request: MasteredStereoPlanRequest) -> dict | None:
    """Hash-bind the exact verified route retained by repair/revision."""
    if _mode(request.plan) != MASTERED_STEREO:
        return None
    if _existing(request.project, request.target_frames) is None:
        return None
    route = _route(request.project)
    fingerprint = request.project.get("expectedFingerprint")
    if not isinstance(fingerprint, str) or not _SHA.fullmatch(fingerprint):
        raise PalmierError(
            "existing mastered-stereo route has no candidate fingerprint")
    receipt, content = _prior_operations(request.project)
    if not _declares_mastered_stereo(content) or not (
            _placement_matches(route, content)
            or _preservation_matches(route, content)):
        raise PalmierError(
            "existing mastered-stereo route differs from prior worklist authority")
    return {
        "schemaVersion": 1, "mode": MASTERED_STEREO,
        "basisFingerprint": fingerprint, "previousOperations": receipt,
        "route": route, "routeHash": _digest(route),
    }


def _asset(request: MasteredStereoPlanRequest) -> MasteredStereoAsset:
    existing = _existing(request.project, request.target_frames)
    if existing is not None:
        return existing
    return prepare_mastered_stereo_asset(MasteredStereoRequest(
        request.inputs, request.authority, request.project,
        request.target_frames, request.cache_dir))


def preserves_mastered_stereo(
        request: MasteredStereoPlanRequest) -> bool:
    """Whether a later stage can retain the already-verified exact route."""
    return _mode(request.plan) == MASTERED_STEREO \
        and _existing(request.project, request.target_frames) is not None


def _steps(asset: MasteredStereoAsset) -> list[dict]:
    facts = asset_dict(asset)
    placement = {
        "op": PLACEMENT_OP, "lane": LANE, "key": MEDIA_KEY,
        "elementId": ELEMENT_ID, "path": asset.path,
        "fileHash": asset.sha256,
        "importName": f"Sniper · mastered stereo · {asset.sha256[:8]}",
        "startFrame": 0, **facts,
        "trackPolicy": "auto-create-dedicated-standalone-audio",
        "requiredNextOp": ROUTE_OP,
    }
    route = {
        "op": ROUTE_OP, "lane": LANE, "elementId": ELEMENT_ID,
        "mediaKey": MEDIA_KEY, "requiredPriorOp": PLACEMENT_OP,
        "trackPolicy": "fresh-content-bearing-audio-readback",
        "masterTrackFlags": {"muted": False, "syncLocked": True},
        "otherContentAudioFlags": {"muted": True},
        "preserveExactMasterReference": True,
    }
    return [placement, route]


def prepare_mastered_stereo_steps(
        request: MasteredStereoPlanRequest) -> list[dict]:
    """Return no steps for editable stems, or a complete governed lane."""
    if _mode(request.plan) != MASTERED_STEREO:
        return []
    if preserves_mastered_stereo(request):
        return []
    return _steps(_asset(request))


def extend_mastered_stereo_worklist(
        steps: list[dict], request: MasteredStereoPlanRequest) -> list[dict]:
    """Append the audio authority lane after all picture/music placement."""
    return [*steps, *prepare_mastered_stereo_steps(request)]
