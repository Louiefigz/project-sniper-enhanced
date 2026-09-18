"""Bind exact-master Desktop calls to immutable worklist and ledger facts."""
from __future__ import annotations

import os

from fingerprints import file_sha256
from palmier.desktop_exact_master_contract import exact_master_step
from palmier.desktop_exact_master_plan import ADD_OP, DISABLE_OP
from palmier.mcp_client import PalmierError

ADD_KIND = "exact-master-reference-added"
DISABLE_KIND = "exact-master-reference-disabled"


def _media_record(state: dict, step: dict) -> dict | None:
    digest = step.get("assetHash")
    row = (state.get("mediaLedger") or {}).get(digest)
    return row if isinstance(row, dict) else None


def _verify_asset(step: dict) -> None:
    path, digest = step.get("assetPath"), step.get("assetHash")
    valid = isinstance(path, str) and isinstance(digest, str) \
        and os.path.isfile(path) and file_sha256(path) == digest
    if not valid:
        raise PalmierError(
            "exact-master bytes changed after operation-manifest binding")


def _expected_add(state: dict, step: dict) -> dict | None:
    media = _media_record(state, step)
    media_ref = media.get("mediaRef") if isinstance(media, dict) else None
    if not isinstance(media_ref, str):
        return None
    return {"entries": [{
        "mediaRef": media_ref, "startFrame": step["startFrame"],
        "endFrame": step["endFrame"],
    }]}


def _bind_add(args: dict, state: dict, step: dict) -> dict | None:
    expected = _expected_add(state, step)
    if expected is None:
        return None
    entries = args.get("entries")
    targets_master = isinstance(entries, list) and any(
        isinstance(row, dict)
        and row.get("mediaRef") == expected["entries"][0]["mediaRef"]
        for row in entries)
    if not targets_master:
        return None
    if state.get("exactMasterReference") is not None:
        raise PalmierError("exact-master reference cannot be placed twice")
    if args != expected:
        raise PalmierError(
            "exact-master add_clips differs from the bound dedicated placement")
    _verify_asset(step)
    entry = expected["entries"][0]
    return {
        "kind": ADD_KIND, "elementId": step["elementId"],
        "assetHash": step["assetHash"], "assetPath": step["assetPath"],
        "mediaRef": entry["mediaRef"], "startFrame": entry["startFrame"],
        "endFrame": entry["endFrame"], "fps": step["fps"],
        "frameRate": step["frameRate"],
    }


def expected_disable_args(state: dict) -> dict:
    """Resolve exact dynamic track indices after dedicated pair creation."""
    record = state.get("exactMasterReference")
    step = exact_master_step(state, DISABLE_OP)
    if not isinstance(record, dict) or not isinstance(step, dict):
        raise PalmierError("exact-master disable has no bound reference/step")
    video, audio = record.get("videoTrackIndex"), record.get("audioTrackIndex")
    if any(isinstance(value, bool) or not isinstance(value, int)
           for value in (video, audio)):
        raise PalmierError("exact-master disable has no current track indices")
    return {"set": [
        {"index": video, **step["videoFlags"]},
        {"index": audio, **step["audioFlags"]},
    ]}


def _bind_disable(args: dict, state: dict) -> dict | None:
    record = state.get("exactMasterReference")
    if not isinstance(record, dict) \
            or record.get("status") != "disable-required":
        return None
    expected = expected_disable_args(state)
    if args != expected:
        raise PalmierError(
            "manage_tracks must hide/mute the exact bound reference pair")
    return {
        "kind": DISABLE_KIND, "elementId": record["elementId"],
        "clipId": record["clipId"], "audioClipId": record["audioClipId"],
        "videoTrackIndex": record["videoTrackIndex"],
        "audioTrackIndex": record["audioTrackIndex"],
    }


def bind_exact_master_operation(tool: str, args: dict,
                                state: dict) -> dict | None:
    """Return an exact-master binding when this call targets that lane."""
    add = exact_master_step(state, ADD_OP)
    if tool == "add_clips" and isinstance(add, dict):
        return _bind_add(args, state, add)
    if tool == "manage_tracks":
        return _bind_disable(args, state)
    return None
