"""Bind mastered-stereo import, placement, and dynamic route isolation."""
from __future__ import annotations

import os

from fingerprints import file_sha256
from palmier.desktop_audio_master_contract import \
    validate_mastered_stereo_assets
from palmier.desktop_audio_master_types import ELEMENT_ID, PLACEMENT_OP
from palmier.desktop_audio_routes import (
    AudioRouteError, locate_standalone, route_rows)
from palmier.desktop_state import read_record
from palmier.mcp_client import PalmierError

ADD_KIND = "mastered-stereo-added"
ROUTE_KIND = "mastered-stereo-isolated"


def _steps(state: dict) -> list[dict]:
    reference = state.get("operations")
    path = reference.get("path") if isinstance(reference, dict) else None
    if not isinstance(path, str):
        return []
    value = read_record(path, "operation manifest")
    rows = value.get("steps") if isinstance(value, dict) else None
    return [row for row in rows or [] if isinstance(row, dict)]


def mastered_step(state: dict, op: str) -> dict | None:
    """Return one unique mastered-stereo worklist step."""
    matches = [row for row in _steps(state) if row.get("op") == op]
    if len(matches) > 1:
        raise PalmierError(f"Desktop worklist repeats {op}")
    return matches[0] if matches else None


def _asset(step: dict) -> dict:
    path = step.get("path", step.get("assetPath"))
    value = {
        "assetPath": path,
        "assetHash": step.get("assetHash"),
        "sourceFinalPath": step.get("sourceFinalPath"),
        "sourceFinalHash": step.get("sourceFinalHash"),
        "derivationProofPath": step.get("derivationProofPath"),
        "derivationProofHash": step.get("derivationProofHash"),
        "pcm": step.get("pcm"),
        "projectFrameRate": step.get("projectFrameRate"),
        "endFrame": step.get("endFrame"),
    }
    file_hash = step.get("fileHash", step.get("assetHash"))
    if file_hash != step.get("assetHash"):
        raise PalmierError("mastered-stereo worklist WAV hash is inconsistent")
    return validate_mastered_stereo_assets(value)


def _import_path(args: dict) -> str | None:
    source = args.get("source")
    value = source.get("path") if isinstance(source, dict) else args.get("path")
    return os.path.realpath(value) if isinstance(value, str) else None


def _bind_import(args: dict, state: dict, step: dict) -> dict | None:
    if _import_path(args) != os.path.realpath(str(step.get("path"))):
        return None
    if isinstance(state.get("audioAuthority"), dict):
        raise PalmierError("mastered-stereo route is already imported and bound")
    expected = {
        "source": {"path": step["path"]}, "name": step["importName"]}
    if args != expected:
        raise PalmierError(
            "mastered-stereo import differs from the exact worklist call")
    asset = _asset(step)
    if file_sha256(step["path"]) != step["fileHash"]:
        raise PalmierError("mastered-stereo WAV changed before import")
    return {
        "kind": "resource", "path": step["path"],
        "fileHash": step["fileHash"], "mediaKey": step.get("key"),
        "elementId": ELEMENT_ID, "importName": step["importName"],
        "audioMasterAsset": asset,
    }


def _media_ref(state: dict, step: dict) -> str | None:
    row = (state.get("mediaLedger") or {}).get(step.get("assetHash"))
    return row.get("mediaRef") if isinstance(row, dict) else None


def _bind_add(args: dict, state: dict, step: dict) -> dict | None:
    media_ref = _media_ref(state, step)
    entries = args.get("entries")
    targets = isinstance(entries, list) and any(
        isinstance(row, dict) and row.get("mediaRef") == media_ref
        for row in entries) if isinstance(media_ref, str) else False
    if not targets:
        return None
    from palmier.desktop_exact_master_contract import exact_master_declared
    reference = state.get("exactMasterReference")
    if exact_master_declared(state) and (
            not isinstance(reference, dict)
            or reference.get("status") != "ready"):
        raise PalmierError(
            "mastered-stereo placement requires the disabled Exact Master first")
    if state.get("audioMasterRoute") is not None \
            or state.get("audioAuthority") is not None:
        raise PalmierError("mastered-stereo route cannot be placed twice")
    expected = {"entries": [{
        "mediaRef": media_ref, "startFrame": step["startFrame"],
        "endFrame": step["endFrame"],
    }]}
    if args != expected:
        raise PalmierError(
            "mastered-stereo add_clips differs from its dedicated placement")
    asset = _asset(step)
    return {
        "kind": ADD_KIND, "elementId": ELEMENT_ID,
        "mediaRef": media_ref, "startFrame": step["startFrame"],
        **asset,
    }


def expected_route_args(state: dict, timeline: dict) -> dict:
    """Resolve fresh route indices for the sole-audible-route mutation."""
    record = state.get("audioMasterRoute")
    if not isinstance(record, dict) \
            or record.get("status") != "routing-required":
        raise PalmierError("mastered-stereo routing has no provisional route")
    try:
        location = locate_standalone(timeline, record.get("clipId"))
        routes = route_rows(timeline)
    except AudioRouteError as exc:
        raise PalmierError(exc.detail) from exc
    rows = []
    for route in routes:
        if route["trackIndex"] == location.track_index:
            rows.append({
                "index": route["trackIndex"],
                "muted": False, "syncLocked": True,
            })
        elif not route["muted"]:
            rows.append({"index": route["trackIndex"], "muted": True})
    return {"set": rows}


def _bind_route(args: dict, state: dict, timeline: dict) -> dict | None:
    record = state.get("audioMasterRoute")
    if not isinstance(record, dict) \
            or record.get("status") != "routing-required":
        return None
    expected = expected_route_args(state, timeline)
    if args != expected:
        raise PalmierError(
            "manage_tracks differs from the exact mastered-stereo route step")
    _asset(record)
    return {
        "kind": ROUTE_KIND, "elementId": ELEMENT_ID,
        "clipId": record["clipId"], "expectedArgs": expected,
    }


def bind_mastered_stereo_operation(
        tool: str, args: dict, state: dict,
        timeline: dict | None = None) -> dict | None:
    """Bind one call when it targets the mastered-stereo lane."""
    step = mastered_step(state, PLACEMENT_OP)
    if not isinstance(step, dict):
        return None
    if tool == "import_media":
        return _bind_import(args, state, step)
    if tool == "add_clips":
        return _bind_add(args, state, step)
    if tool == "manage_tracks" and isinstance(timeline, dict):
        return _bind_route(args, state, timeline)
    return None
