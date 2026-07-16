"""Visual-master publication, component preservation, and explicit ownership."""
from __future__ import annotations

import os
import shutil
import json
from datetime import datetime, timezone
from typing import Any

from fingerprints import file_sha256
from palmier.export import _promote
from palmier.mcp_client import PalmierError, emit
from palmier.media import MediaBindings, MediaLibrary

OWNERS = ("sniper", "palmier")


def sidecar_ownership(sidecar: dict | None) -> str:
    """Pure owner read; legacy sidecars remain Sniper-owned."""
    owner = (sidecar or {}).get("ownership", "sniper")
    if owner not in OWNERS:
        raise PalmierError(f"unknown Palmier sidecar ownership {owner!r}")
    return owner


def handoff_to_palmier(sidecar: dict) -> dict:
    """Pure explicit handoff; automatic Sniper mirrors must then stop."""
    sidecar_ownership(sidecar)
    return {**sidecar, "ownership": "palmier"}


def reclaim_for_sniper(sidecar: dict) -> dict:
    """Pure explicit reclaim that forces the next sync to build a fresh fork."""
    sidecar_ownership(sidecar)
    reclaimed = {**sidecar, "ownership": "sniper"}
    for key in ("lastPushPlanHash", "laneFp", "verification", "mirror"):
        reclaimed.pop(key, None)
    return reclaimed


def invalidate_for_ai_edit(sidecar: dict) -> dict:
    """Preserve ownership/project history while revoking every A/B proof."""
    owner = sidecar_ownership(sidecar)
    invalidated = {**sidecar, "ownership": owner}
    for key in ("lastPushPlanHash", "laneFp", "verification", "mirror"):
        invalidated.pop(key, None)
    return invalidated


def validate_mirror_request(request: Any, lanes: dict) -> None:
    """Bind translator steps to the exact approved master and its media facts."""
    required = (request.master_path, request.master_hash,
                request.master_duration_s, request.master_fps,
                request.master_width, request.master_height,
                request.master_end_frame)
    if any(value is None for value in required):
        raise PalmierError("visual mirror request is missing approved-master facts")
    if not os.path.isfile(request.master_path):
        raise PalmierError("approved visual master disappeared before Palmier sync")
    if file_sha256(request.master_path) != request.master_hash:
        raise PalmierError("approved visual master changed before Palmier sync")
    project, entry = lanes["project"], lanes["mirror"]["entry"]
    expected_project = (round(request.master_fps), request.master_width,
                        request.master_height, request.master_hash)
    actual_project = (project.get("fps"), project.get("width"),
                      project.get("height"), project.get("masterHash"))
    expected_entry = ("master", 0, request.master_end_frame, 1.0,
                      request.master_hash)
    actual_entry = (entry.get("mediaKey"), entry.get("startFrame"),
                    entry.get("endFrame"), entry.get("speed"),
                    entry.get("masterHash"))
    source = entry.get("source")
    source_ok = (isinstance(source, list) and len(source) == 2
                 and source[0] == 0.0
                 and source[1] == request.master_duration_s)
    import_path = lanes["imports"].get("master")
    if (actual_project != expected_project or actual_entry != expected_entry
            or not source_ok or len(lanes["imports"]) != 1
            or os.path.realpath(import_path or "")
            != os.path.realpath(request.master_path)):
        raise PalmierError(
            "visual mirror steps do not exactly match the approved master")


def ensure_mirror_bindings(session: Any, lanes: dict,
                           sidecar: dict | None) -> MediaBindings:
    """Import the master mandatorily and components as non-visible best effort."""
    request = session.request
    identity = request.master_hash or request.source_hash
    library = MediaLibrary(session.client, identity, session.assert_project)
    prior = (sidecar or {}).get("mediaMap", {})
    required = library.ensure(lanes["imports"], prior)
    refs, seconds, media_map = (dict(required.refs), dict(required.seconds),
                                dict(required.media_map))
    status: dict[str, dict] = {}
    for key, path in sorted(lanes.get("components", {}).items()):
        try:
            optional = library.ensure({key: path}, media_map)
        except PalmierError as exc:
            status[key] = _component_record(path, False, str(exc))
            emit(status="warning", warning=(
                f"component {key} preservation skipped: {exc}"))
            continue
        refs.update(optional.refs)
        seconds.update(optional.seconds)
        media_map.update(optional.media_map)
        status[key] = _component_record(path, True, None)
    return MediaBindings(refs, seconds, media_map, status)


def validate_master_binding(request: Any, bindings: MediaBindings) -> None:
    """Require Palmier's imported master to expose the approved frame count."""
    media_ref = bindings.refs.get("master")
    seconds = bindings.seconds.get("master")
    if not isinstance(media_ref, str) or not media_ref:
        raise PalmierError("Palmier master import returned no stable media reference")
    if not isinstance(seconds, (int, float)) or seconds <= 0:
        raise PalmierError("Palmier master import returned no positive duration")
    actual_frames = round(float(seconds) * round(float(request.master_fps)))
    if actual_frames != request.master_end_frame:
        raise PalmierError(
            f"Palmier master import reports {actual_frames} frames, expected "
            f"{request.master_end_frame}")


def _component_record(path: str, preserved: bool,
                      reason: str | None) -> dict:
    """Describe a non-visible library asset without claiming native editability."""
    return {"path": path, "preserved": preserved, "visible": False,
            "editableOnTimeline": False,
            "capability": "library-media-only" if preserved else "unsupported",
            "reason": reason}


def _ownership_path(out_dir: str) -> str:
    return os.path.join(out_dir, "palmier.sync.json")


def _persist_ownership(out_dir: str, transform) -> dict:
    """Atomically persist an explicit owner transition on an existing sidecar."""
    path = _ownership_path(out_dir)
    try:
        with open(path, encoding="utf-8") as handle:
            sidecar = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise PalmierError(f"cannot change Palmier ownership: {exc}") from exc
    if not isinstance(sidecar, dict):
        raise PalmierError("cannot change Palmier ownership: sidecar is not an object")
    updated = transform(sidecar)
    temp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(updated, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.remove(temp)
    return updated


def persist_handoff_to_palmier(out_dir: str) -> dict:
    """Atomically hand an existing generated project to Palmier ownership."""
    return _persist_ownership(out_dir, handoff_to_palmier)


def persist_reclaim_for_sniper(out_dir: str) -> dict:
    """Atomically reclaim ownership and invalidate all prior mirror proofs."""
    return _persist_ownership(out_dir, reclaim_for_sniper)


def persist_ai_edit_invalidation(out_dir: str) -> dict:
    """Atomically revoke stale A/B authority without changing handoff owner."""
    return _persist_ownership(out_dir, invalidate_for_ai_edit)


def publish_master(request: Any, final_name: str, meta_name: str) -> None:
    """Publish Palmier delivery as an exact byte copy of the approved master."""
    if not request.master_path or not request.master_hash:
        raise PalmierError("visual mirror publication has no approved master")
    if file_sha256(request.master_path) != request.master_hash:
        raise PalmierError("approved visual master changed before publication")
    temp = os.path.join(request.out_dir, f".{final_name}.{os.getpid()}.tmp")
    final = os.path.join(request.out_dir, final_name)
    meta = os.path.join(request.out_dir, meta_name)
    try:
        shutil.copyfile(request.master_path, temp)
        if file_sha256(temp) != request.master_hash:
            raise PalmierError("visual mirror copy hash differs from approved master")
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        payload = {
            "planHash": request.plan_hash,
            "authorityHash": request.master_hash,
            "visualMasterHash": request.master_hash,
            "publishedHash": request.master_hash,
            "mirrorMode": "visual-master",
            "proof": "byte-identical-approved-master",
            "pushedAt": now,
            "exportVerified": True,
            "visualVerified": True,
            "audioVerified": True,
            "audioProof": "byte-identical-approved-master",
        }
        _promote(temp, final, meta, payload)
    finally:
        if os.path.exists(temp):
            os.remove(temp)
    emit(status="exported", outputPath=final, bytes=os.path.getsize(final),
         publishedHash=request.master_hash, visualVerified=True,
         audioVerified=True)
