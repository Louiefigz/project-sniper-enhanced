#!/usr/bin/env python3
"""Pure sync fingerprints plus the Palmier shadow-build transaction."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass

from fingerprints import file_sha256, json_canon, plan_content_hash
from palmier.executor import Executor
from palmier.mcp_client import PalmierClient, PalmierError, emit
from palmier.media import content_key
from palmier.mirror import (ensure_mirror_bindings, publish_master,
                            sidecar_ownership, validate_master_binding,
                            validate_mirror_request)
from palmier.shadow import ShadowSession, SyncRequest, prior_timelines
from palmier.timeline_authority import record_active_authority
from palmier.timeline_guard import assert_sniper_baseline
from palmier.verify import verify_generated_timeline

SIDECAR_NAME = "palmier.sync.json"
META_NAME = "final.palmier.meta.json"
FINAL_NAME = "final.palmier.mp4"
LANES = ("cuts", "motion", "gfx", "music", "texts")


@dataclass(frozen=True)
class StatePayload:
    """Verified inputs written to the persistent Palmier sync sidecar."""

    lane_fp: dict[str, str]
    records: list[dict]
    verification: dict


def _canon_hash(obj: object) -> str:
    """SHA-1 of canonical, key-sorted JSON for compact lane fingerprints."""
    blob = json.dumps(json_canon(obj), sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(blob.encode()).hexdigest()


def sidecar_path(out_dir: str) -> str:
    return os.path.join(out_dir, SIDECAR_NAME)


def _read_json(path: str) -> dict | None:
    if not os.path.exists(path):
        return None
    try:
        with open(path) as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise PalmierError(f"cannot read Palmier state {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PalmierError(f"Palmier state {path} is not a JSON object")
    return value


def _write_json_atomic(path: str, value: dict) -> None:
    temp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(temp, "w") as handle:
            json.dump(value, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.remove(temp)


def load_sidecar(out_dir: str) -> dict | None:
    return _read_json(sidecar_path(out_dir))


def parse_steps(steps: list[dict]) -> dict:
    """Group the translator's ordered steps into complete-build lanes."""
    lanes: dict = {"imports": {}, "cuts": None, "baseline": None,
                   "keyframes": [], "overlays": None, "music": None,
                   "texts": [], "warns": [], "export": None,
                   "project": None, "mirror": None, "components": {}}
    for step in steps:
        op = step["op"]
        if op == "import":
            lanes["imports"][step["key"]] = step["path"]
        elif op == "component_import":
            lanes["components"][step["key"]] = step["path"]
        elif op == "warn":
            lanes["warns"].append(step)
        elif op == "keyframes":
            lanes["keyframes"].append(step)
        elif op == "text":
            lanes["texts"].append(step)
        elif op in ("cuts", "baseline", "overlays", "music", "export",
                    "project", "mirror"):
            lanes[op] = step
        else:
            raise PalmierError(f"unknown step op {op!r}")
    if not lanes["project"] or not (lanes["mirror"] or lanes["cuts"]):
        raise PalmierError("translated steps lack project and visual placement")
    return lanes


def lane_fingerprints(lanes: dict, source_hash: str) -> dict[str, str]:
    """Per-lane hashes retained for translator/staleness diagnostics."""
    if lanes.get("mirror"):
        return {
            "visual": _canon_hash([lanes["project"], lanes["mirror"],
                                   f"master:{source_hash}"]),
            "components": _canon_hash(sorted(lanes["components"].items())),
        }
    imports = lanes["imports"]
    gfx_entries = (lanes["overlays"] or {}).get("entries", [])
    return {
        "cuts": _canon_hash([lanes["cuts"], lanes["project"].get("fps"),
                             f"src:{source_hash}"]),
        "motion": _canon_hash([lanes["baseline"], lanes["keyframes"]]),
        "gfx": _canon_hash([[entry | {"content": content_key(
            entry["mediaKey"], imports[entry["mediaKey"]], source_hash)}
                             for entry in gfx_entries]]),
        "music": _canon_hash([lanes["music"], imports.get("music") and
                              content_key("music", imports["music"],
                                          source_hash)]),
        "texts": _canon_hash(lanes["texts"]),
    }


def _is_current(request: SyncRequest, lane_fp: dict,
                sidecar: dict | None) -> bool:
    if sidecar_ownership(sidecar) != "sniper":
        return False
    if not sidecar or sidecar.get("lastPushPlanHash") != request.plan_hash:
        return False
    if sidecar.get("laneFp") != lane_fp:
        return False
    if sidecar.get("parity") != request.parity:
        return False
    timeline_id = sidecar.get("latestTimelineId")
    verification = sidecar.get("verification")
    if not isinstance(timeline_id, str) or not isinstance(verification, dict):
        return False
    if (verification.get("ok") is not True
            or verification.get("timelineId") != timeline_id):
        return False
    visual = verification.get("visualMaster") or {}
    if visual.get("masterHash") != request.master_hash:
        return False
    if not request.publish:
        return True
    meta = _read_json(os.path.join(request.out_dir, META_NAME))
    final = os.path.join(request.out_dir, FINAL_NAME)
    return bool(meta and request.master_hash
                and meta.get("authorityHash") == request.master_hash
                and meta.get("visualMasterHash") == request.master_hash
                and meta.get("publishedHash") == request.master_hash
                and meta.get("planHash") == request.plan_hash
                and meta.get("exportVerified") is True
                and meta.get("visualVerified") is True
                and meta.get("audioVerified") is True
                and os.path.isfile(final)
                and file_sha256(final) == request.master_hash)


def _apply_all(session: ShadowSession, lanes: dict,
               bindings) -> Executor:
    executor = Executor(session.client, session.assert_build)
    executor.project_fps = lanes["project"]["fps"]
    executor.media = bindings.refs
    executor.media_s = bindings.seconds
    if lanes.get("mirror"):
        executor.run(lanes["mirror"])
        for step in lanes["warns"]:
            executor.run(step)
        return executor
    executor.run(lanes["cuts"])
    if lanes["baseline"]:
        executor.run(lanes["baseline"])
    for step in lanes["keyframes"]:
        executor.run(step)
    for key in ("overlays", "music"):
        if lanes[key]:
            executor.run(lanes[key])
    for step in lanes["texts"]:
        executor.run(step)
    for step in lanes["warns"]:
        executor.run(step)
    return executor


def _state_record(session: ShadowSession, bindings,
                  payload: StatePayload) -> dict:
    target = session.target
    if target is None:
        raise PalmierError("target project identity disappeared")
    mirror = payload.verification.get("visualMaster")
    return {"schemaVersion": 4, "ownership": "sniper",
            "workspaceMode": "verified-mirror",
            "mirrorMode": "visual-master", "mirror": mirror,
            "projectId": target.project_id,
            "projectName": target.name, "projectPath": target.path,
            "projectSettings": {"fps": session.lanes["project"]["fps"],
                                "width": session.lanes["project"]["width"],
                                "height": session.lanes["project"]["height"]},
            "mediaMap": bindings.media_map, "laneFp": payload.lane_fp,
            "componentPreservation": bindings.component_status,
            "lastPushPlanHash": session.request.plan_hash,
            "latestTimelineId": session.build_id,
            "timelineIds": payload.records,
            "parity": session.request.parity,
            "verification": {**payload.verification,
                             "planHash": session.request.plan_hash}}


def _activate_current(client: PalmierClient, request: SyncRequest,
                      lanes: dict, sidecar: dict) -> None:
    """Make an already-verified generated fork the user's visible timeline."""
    session = ShadowSession(client, request, lanes, sidecar)
    session.ensure_project()
    try:
        session.activate_generated(sidecar["latestTimelineId"],
                                   require_human=False)
    except Exception:
        session.restore_human(strict=False)
        raise
    emit(status="up_to_date", planHash=request.plan_hash,
         timelineId=sidecar["latestTimelineId"])


def run_sync(client: PalmierClient, steps: list[dict],
             request: SyncRequest) -> None:
    """Build, verify, and checkpoint one shadow timeline transaction."""
    if request.parity.get("mirrorReady") is not True:
        raise PalmierError("Palmier visual mirror requires a safe parity checkpoint")
    if not request.master_hash or not request.master_path:
        raise PalmierError("Palmier visual mirror requires an approved final master")
    lanes = parse_steps(steps)
    if not lanes.get("mirror") or lanes.get("cuts"):
        raise PalmierError("supported sync must contain one visual-master mirror lane")
    validate_mirror_request(request, lanes)
    lane_fp = lane_fingerprints(lanes, request.master_hash)
    sidecar = load_sidecar(request.out_dir)
    if sidecar_ownership(sidecar) == "palmier":
        raise PalmierError(
            "Palmier owns this handoff; explicitly reclaim Sniper ownership "
            "before creating a fresh mirror")
    assert_sniper_baseline(client, request.out_dir, sidecar)
    if _is_current(request, lane_fp, sidecar):
        _activate_current(client, request, lanes, sidecar or {})
        return
    session = ShadowSession(client, request, lanes, sidecar)
    session.ensure_project()
    bindings = ensure_mirror_bindings(session, lanes, sidecar)
    validate_master_binding(request, bindings)
    completed = False
    state: dict = {}
    try:
        session.create_shadow()
        executor = _apply_all(session, lanes, bindings)
        verification = verify_generated_timeline(
            client, session.build_id or "", lanes, executor)
        session.restore_human(strict=True)
        if lanes["export"]:
            session.assert_human("shadow export")
            publish_master(request, FINAL_NAME, META_NAME)
        _name, records = session.finalize(prior_timelines(sidecar or {}))
        session.activate_generated()
        payload = StatePayload(lane_fp, records, verification)
        state = _state_record(session, bindings, payload)
        target = session.target
        if target is None:
            raise PalmierError("target project identity disappeared before authority capture")
        record_active_authority(client, request.out_dir, target.project_id,
                                "sniper-bootstrap")
        _write_json_atomic(sidecar_path(request.out_dir), state)
        completed = True
    except Exception:
        session.restore_human(strict=False)
        session.mark_failed()
        raise
    finally:
        if not completed:
            session.restore_human(strict=False)
    emit(status="sync_done", project=state["projectName"],
         timelineId=state["latestTimelineId"], planHash=request.plan_hash)
