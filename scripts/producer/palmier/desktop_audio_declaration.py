"""Immutable worklist declaration for Desktop Palmier audio authority."""
from __future__ import annotations

import json
import os
import re

from fingerprints import file_sha256
from palmier.desktop_audio_master_types import (ELEMENT_ID, MEDIA_KEY,
                                                PLACEMENT_OP, ROUTE_OP)
from palmier.mcp_client import PalmierError

EDITABLE_STEMS = "editable-stems"
MASTERED_STEREO = "mastered-stereo"
MODES = {EDITABLE_STEMS, MASTERED_STEREO}
_KEYS = {"schemaVersion", "mode", "status", "blockerCode"}
_SHA = re.compile(r"^[0-9a-f]{64}$")
_PLACEMENT_KEYS = {
    "op", "lane", "key", "elementId", "path", "fileHash", "importName",
    "startFrame", "assetPath", "assetHash", "sourceFinalPath",
    "sourceFinalHash", "derivationProofPath", "derivationProofHash", "pcm",
    "projectFrameRate", "endFrame", "trackPolicy", "requiredNextOp",
}
_ROUTE_KEYS = {
    "op", "lane", "elementId", "mediaKey", "requiredPriorOp",
    "trackPolicy", "masterTrackFlags", "otherContentAudioFlags",
    "preserveExactMasterReference",
}
_PCM_KEYS = {
    "codec", "sampleFormat", "sampleRate", "channels", "channelLayout",
    "decodedSamples",
}


def _placement_ready(row: dict) -> bool:
    hashes = [
        row.get("assetHash"), row.get("fileHash"),
        row.get("sourceFinalHash"), row.get("derivationProofHash"),
    ]
    rate = row.get("projectFrameRate")
    match = re.fullmatch(r"([1-9][0-9]*)/1", str(rate))
    frames, pcm = row.get("endFrame"), row.get("pcm")
    fps = int(match.group(1)) if match else 0
    samples = pcm.get("decodedSamples") if isinstance(pcm, dict) else None
    exact_samples = isinstance(frames, int) and not isinstance(frames, bool) \
        and frames > 0 and frames * 48_000 % fps == 0 \
        and samples == frames * 48_000 // fps if fps else False
    return set(row) == _PLACEMENT_KEYS \
        and row.get("op") == PLACEMENT_OP and row.get("lane") == "audio-master" \
        and row.get("elementId") == ELEMENT_ID and row.get("key") == MEDIA_KEY \
        and row.get("startFrame") == 0 and exact_samples \
        and all(isinstance(value, str) and _SHA.fullmatch(value)
                for value in hashes) \
        and row.get("assetHash") == row.get("fileHash") \
        and row.get("path") == row.get("assetPath") \
        and all(isinstance(row.get(key), str) and os.path.isabs(row[key])
                for key in ("path", "sourceFinalPath", "derivationProofPath")) \
        and isinstance(row.get("importName"), str) and bool(row["importName"]) \
        and isinstance(pcm, dict) and set(pcm) == _PCM_KEYS \
        and pcm.get("codec") == "pcm_s32le" \
        and pcm.get("sampleFormat") == "s32" \
        and pcm.get("sampleRate") == 48_000 and pcm.get("channels") == 2 \
        and pcm.get("channelLayout") == "stereo" \
        and row.get("trackPolicy") \
        == "auto-create-dedicated-standalone-audio" \
        and row.get("requiredNextOp") == ROUTE_OP


def _route_ready(row: dict) -> bool:
    return set(row) == _ROUTE_KEYS and row.get("op") == ROUTE_OP \
        and row.get("lane") == "audio-master" \
        and row.get("elementId") == ELEMENT_ID \
        and row.get("mediaKey") == MEDIA_KEY \
        and row.get("requiredPriorOp") == PLACEMENT_OP \
        and row.get("trackPolicy") \
        == "fresh-content-bearing-audio-readback" \
        and row.get("masterTrackFlags") == {
            "muted": False, "syncLocked": True} \
        and row.get("otherContentAudioFlags") == {"muted": True} \
        and row.get("preserveExactMasterReference") is True


def _master_worklist_ready(steps: list[dict] | None) -> bool:
    rows = [row for row in steps or [] if isinstance(row, dict)]
    placements = [row for row in rows if row.get("op") == PLACEMENT_OP]
    routes = [row for row in rows if row.get("op") == ROUTE_OP]
    if len(placements) != 1 or len(routes) != 1:
        return False
    return _placement_ready(placements[0]) and _route_ready(routes[0])


def manifest_audio_authority(
        plan_path: str, steps: list[dict] | None = None,
        preserved_mastered_stereo: object = None) -> dict:
    """Compile the currently supported audio mode into the bound worklist."""
    try:
        with open(plan_path, encoding="utf-8") as handle:
            plan = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise PalmierError(
            f"cannot compile Desktop audio authority: {exc}") from exc
    mode = plan.get("audioAuthorityMode", EDITABLE_STEMS) \
        if isinstance(plan, dict) else None
    if mode not in MODES:
        raise PalmierError(
            "audioAuthorityMode must be editable-stems or mastered-stereo")
    from palmier.desktop_audio_master_plan import \
        preserved_mastered_stereo_ready
    preserved = preserved_mastered_stereo_ready(
        preserved_mastered_stereo)
    if mode == MASTERED_STEREO and (
            _master_worklist_ready(steps) or preserved):
        return {
            "schemaVersion": 1, "mode": mode, "status": "ready",
            "blockerCode": None,
        }
    code = "routing-readback-unsupported" if mode == EDITABLE_STEMS \
        else "master-route-worklist-incomplete"
    return {
        "schemaVersion": 1, "mode": mode, "status": "blocked",
        "blockerCode": code,
    }


def read_audio_authority_declaration(state: dict) -> dict:
    """Re-read the hash-bound worklist audio declaration."""
    reference = state.get("operations")
    path = reference.get("path") if isinstance(reference, dict) else None
    digest = reference.get("hash") if isinstance(reference, dict) else None
    valid = isinstance(path, str) and isinstance(digest, str) \
        and os.path.isfile(path) and not os.path.islink(path) \
        and file_sha256(path) == digest
    if not valid:
        raise PalmierError(
            "audio mode has no immutable operation-manifest authority")
    try:
        with open(path, encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise PalmierError(
            f"audio operation-manifest authority is unreadable: {exc}") from exc
    capability = manifest.get("capability") \
        if isinstance(manifest, dict) else None
    declaration = capability.get("audioAuthority") \
        if isinstance(capability, dict) else None
    valid = isinstance(declaration, dict) and set(declaration) == _KEYS \
        and declaration.get("schemaVersion") == 1 \
        and declaration.get("mode") in MODES \
        and declaration.get("status") in {"ready", "blocked"}
    if not valid:
        raise PalmierError(
            "operation manifest has no valid audioAuthority declaration")
    if manifest.get("stage") in {"repair", "revision"} \
            and declaration.get("mode") == MASTERED_STEREO \
            and declaration.get("status") == "ready" \
            and not _master_worklist_ready(manifest.get("steps")):
        from palmier.desktop_audio_master_plan import \
            preserved_mastered_stereo_ready
        preserved = capability.get("preservedMasteredStereoAuthority")
        if not preserved_mastered_stereo_ready(preserved):
            raise PalmierError(
                "preserved mastered-stereo worklist authority changed")
    return declaration
