#!/usr/bin/env python3
"""Publish immutable, non-authoritative Palmier checkpoints during Auto Edit."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from palmier.checkpoint_inputs import (                                # noqa: E402
    CheckpointAuthority as Authority, CheckpointInput,
    authority_current as _authority_current,
    checkpoint_inputs as _inputs, checkpoint_label as _label,
    input_authority as _authority, read_json as _json)
from palmier.checkpoint_asset_authority import checkpoint_assets_current  # noqa: E402
from palmier.mcp_client import (PalmierClient, PalmierError,            # noqa: E402
                                PalmierWaiting, emit)
from palmier.media import MediaLibrary                                  # noqa: E402
from palmier.shadow import ShadowSession, SyncRequest, prior_timelines  # noqa: E402
from palmier.sync import (_apply_all, load_sidecar, parse_steps,        # noqa: E402
                          sidecar_path)
from palmier.timeline_authority import (atomic_write_record,            # noqa: E402
                                        authority_path, compare_authority,
                                        load_authority, read_active,
                                        record_authority)
from palmier.timeline_guard import guard_sniper_baseline                # noqa: E402
from palmier.verify import verify_generated_timeline                    # noqa: E402


class ManualCheckpointConflict(PalmierError):
    """The operator changed the live Palmier head during publication."""


def _checkpoint_state(state: dict, session: ShadowSession, bindings,
                      authority: Authority, label: str, capability: dict,
                      verification: dict, parent: dict, records: list[dict]) -> dict:
    if session.target is None or session.build_id is None:
        raise PalmierError("checkpoint target identity disappeared")
    readback = load_authority(session.request.out_dir) or {}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    current = {**records[0], "name": label, "status": "working-checkpoint",
               "stage": session.request.parity["stage"]}
    return {**state, "schemaVersion": 4, "ownership": "sniper",
            "workspaceMode": "managed-draft", "mirrorMode": None,
            "projectId": session.target.project_id,
            "projectName": session.target.name, "projectPath": session.target.path,
            "projectSettings": {key: session.lanes["project"][key]
                                for key in ("fps", "width", "height")},
            "latestTimelineId": session.build_id,
            "mediaMap": bindings.media_map,
            "timelineIds": [current, *records[1:]],
            "workingCheckpoint": {
                "schemaVersion": 1, "key": authority.checkpoint_key,
                "stage": session.request.parity["stage"], "round": session.request.parity["round"],
                "label": label, "planHash": authority.plan_hash,
                "manifestHash": authority.manifest_hash,
                "mediaHash": authority.media_hash, "createdAt": now,
                "authoritative": False, "capability": capability,
                "verification": verification,
                "parent": {key: parent.get(key) for key in
                           ("projectId", "timelineId", "fingerprint")},
                "readback": {key: readback.get(key) for key in
                             ("projectId", "timelineId", "fingerprint",
                              "semanticFingerprint")},
            }}


def _write_state(out_dir: str, value: dict) -> None:
    atomic_write_record(sidecar_path(out_dir), value)


def _restore_parent_record(out_dir: str, parent: dict) -> None:
    atomic_write_record(authority_path(out_dir), parent)


def _superseded_checkpoint(out_dir: str, authority: Authority,
                           reason: str) -> dict:
    """Report an adopted Palmier head as a successful authority handoff.

    A plan checkpoint cannot be merged losslessly into a newer manual Palmier
    timeline.  The safe result is not a failed job: reconciliation has already
    persisted that complete readback as the next working authority, so the
    legacy checkpoint is superseded and later governed native edits can start
    from it.
    """
    saved = load_authority(out_dir) or {}
    working_value = saved.get("workingHead")
    working = working_value if isinstance(working_value, dict) else {}
    return {
        "status": "checkpoint_superseded",
        "reason": reason,
        "checkpointKey": authority.checkpoint_key,
        "authority": "palmier",
        "origin": saved.get("origin"),
        "timelineId": working.get("timelineId", saved.get("timelineId")),
        "fingerprint": working.get("fingerprint", saved.get("fingerprint")),
        "workingHead": {
            key: working.get(key, saved.get(key))
            for key in ("projectId", "timelineId", "fingerprint",
                        "semanticFingerprint")
        },
    }


def _same_checkpoint(state: dict, authority: Authority,
                     capability: dict) -> bool:
    current = state.get("workingCheckpoint") or {}
    current_assets = (current.get("capability") or {}).get(
        "graphicsAssetAuthority")
    next_assets = capability.get("graphicsAssetAuthority")
    return current.get("key") == authority.checkpoint_key \
        and current_assets == next_assets \
        and current.get("readback", {}).get("timelineId") == state.get("latestTimelineId")


def _require_assets_current(capability: dict) -> None:
    if not checkpoint_assets_current(capability):
        raise PalmierError(
            "checkpoint graphics changed outside their placement receipts")


def _workspace_state(out_dir: str) -> dict:
    state = load_sidecar(out_dir)
    if not state or state.get("workspaceMode") != "managed-draft":
        raise PalmierError(
            "live checkpoints require an open managed Palmier source view")
    if state.get("ownership", "sniper") != "sniper":
        raise PalmierError(
            "Palmier owns this working head; live Sniper checkpoints are paused")
    return state


def _required_parent(out_dir: str) -> dict:
    parent = load_authority(out_dir)
    if not parent:
        raise PalmierError(
            "managed Palmier source view has no readback authority")
    return parent


def _media_bindings(client: PalmierClient, request: SyncRequest,
                    session: ShadowSession, lanes: dict, state: dict):
    library = MediaLibrary(client, request.source_hash, session.assert_project)
    return library.ensure(lanes["imports"], state.get("mediaMap", {}))


def _manual_head(out_dir: str, found, parent: dict, reason: str) -> None:
    record_authority(out_dir, found, "palmier-manual", parent)
    raise ManualCheckpointConflict(reason)


def _assert_parent_cas(client: PalmierClient, out_dir: str,
                       parent: dict) -> None:
    found = read_active(client, str(parent.get("projectId")))
    change = compare_authority(parent, found)
    if change != "unchanged":
        _manual_head(out_dir, found, parent,
                     f"Palmier parent {change} during checkpoint build")


def _assert_generated_cas(client: PalmierClient, out_dir: str, parent: dict,
                          expected, label: str) -> None:
    found = read_active(client, expected.project_id)
    unchanged = (found.project_id == expected.project_id
                 and found.timeline_id == expected.timeline_id
                 and found.semantic_fingerprint == expected.semantic_fingerprint
                 and found.timeline.get("name") == label)
    if not unchanged:
        _manual_head(out_dir, found, parent,
                     "Palmier checkpoint changed before commit")


def _verified_build(client: PalmierClient, out_dir: str, parent: dict,
                    session: ShadowSession, lanes: dict, executor):
    """Bind structural verification to one stable generated readback."""
    if session.target is None or session.build_id is None:
        raise PalmierError("checkpoint target identity disappeared")
    before = read_active(client, session.target.project_id)
    verification = verify_generated_timeline(
        client, session.build_id, lanes, executor)
    after = read_active(client, session.target.project_id)
    stable = (before.timeline_id == after.timeline_id
              and before.fingerprint == after.fingerprint)
    if not stable:
        _manual_head(out_dir, after, parent,
                     "Palmier checkpoint changed during verification")
    return verification, after


def _finalize_checkpoint(session: ShadowSession, state: dict,
                         authority: Authority, label: str) -> list[dict]:
    _name, records = session.finalize(prior_timelines(state))
    session.client.call("organize_media", {"renames": [{
        "item": session.build_id, "name": label}]})
    session.build_name = label
    return records


def _commit_checkpoint(session: ShadowSession, spec: CheckpointInput,
                       state: dict, bindings, authority: Authority,
                       capability: dict, verification: dict, parent: dict,
                       built) -> dict:
    session.restore_human(strict=True)
    _assert_parent_cas(session.client, spec.out_dir, parent)
    label = _label(spec, authority)
    records = _finalize_checkpoint(session, state, authority, label)
    session.activate_generated()
    _assert_generated_cas(session.client, spec.out_dir, parent, built, label)
    current = read_active(session.client, built.project_id)
    record_authority(spec.out_dir, current, "sniper-bootstrap")
    if not _authority_current(spec, authority):
        raise PalmierError("checkpoint inputs changed before checkpoint commit")
    saved = _checkpoint_state(state, session, bindings, authority, label,
                              capability, verification, parent, records)
    _write_state(spec.out_dir, saved)
    return {"status": "checkpoint_ready", "reused": False,
            "timelineId": session.build_id, "timelineName": label,
            "checkpointKey": authority.checkpoint_key,
            "omissions": capability.get("omissions", []),
            "limitations": capability.get("limitations", []),
            "fidelityFindings": capability.get("fidelityFindings", [])}


def publish_checkpoint(client: PalmierClient, spec: CheckpointInput) -> dict:
    """Build, read back, CAS-activate, and checkpoint one immutable timeline."""
    state = _workspace_state(spec.out_dir)
    authority, steps, capability = _inputs(spec, state)
    lanes = parse_steps(steps)
    request = SyncRequest(spec.out_dir, authority.media_hash or authority.manifest_hash,
                          authority.checkpoint_key,
                          {"stage": spec.stage, "round": spec.round})
    session = ShadowSession(client, request, lanes, state)
    session.ensure_project()
    verdict = guard_sniper_baseline(client, spec.out_dir, state)
    if verdict.get("ok") is not True:
        return _superseded_checkpoint(
            spec.out_dir, authority, str(verdict.get("error")))
    _require_assets_current(capability)
    if _same_checkpoint(state, authority, capability):
        session.activate_generated(state["latestTimelineId"], require_human=False)
        return {"status": "checkpoint_ready", "reused": True,
                "timelineId": state["latestTimelineId"],
                "checkpointKey": authority.checkpoint_key}
    parent = _required_parent(spec.out_dir)
    if not _authority_current(spec, authority):
        raise PalmierError("checkpoint inputs changed before Palmier build")
    bindings = _media_bindings(client, request, session, lanes, state)
    complete = False
    try:
        session.create_shadow()
        executor = _apply_all(session, lanes, bindings)
        verification, built = _verified_build(
            client, spec.out_dir, parent, session, lanes, executor)
        _require_assets_current(capability)
        if not _authority_current(spec, authority):
            raise PalmierError("checkpoint inputs changed during Palmier build")
        result = _commit_checkpoint(
            session, spec, state, bindings, authority, capability,
            verification, parent, built)
        complete = True
        return result
    except ManualCheckpointConflict as exc:
        complete = True
        return _superseded_checkpoint(spec.out_dir, authority, str(exc))
    except Exception:
        session.restore_human(strict=False)
        try:
            _restore_parent_record(spec.out_dir, parent)
        except Exception as exc:
            emit(status="checkpoint_rollback_warning", warning=str(exc))
        session.mark_failed()
        raise
    finally:
        if not complete:
            session.restore_human(strict=False)
