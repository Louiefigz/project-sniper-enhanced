"""Governed candidate lifecycle for a retained skilled-agent Palmier build."""
from __future__ import annotations

import json
import os
import glob
from datetime import datetime, timezone
from typing import Any

from fingerprints import file_sha256
from palmier.candidate_receipt import load_candidate, save_candidate
from palmier.mcp_client import PalmierError
from palmier.native_candidate_lifecycle import assert_candidate_slot_available
from palmier.native_qc_archive import archive_rejected_candidate
from palmier.native_qc_authority import activate_and_read, identity
from palmier.native_qc_contract import load_qc, qc_path
from palmier.timeline_authority import (TimelineConflict, compare_authority,
                                        fork_candidate, load_authority,
                                        read_active, record_candidate)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _records(out_dir: str) -> tuple[dict, dict]:
    parent, candidate = load_authority(out_dir), load_candidate(out_dir)
    if parent is None or candidate is None:
        raise PalmierError("Palmier live build requires saved parent and candidate records")
    if candidate.get("base") != identity(parent):
        raise TimelineConflict("Palmier live-build candidate parent is stale")
    if candidate.get("status") not in {"staged", "edited"}:
        raise PalmierError("Palmier live-build candidate is not resumable")
    return parent, candidate


def fork_live_candidate(client: Any, out_dir: str, name: str) -> dict:
    """Fork the exact canonical parent and keep the candidate visible."""
    parent = load_authority(out_dir)
    if parent is None:
        raise PalmierError("Palmier live build has no canonical working authority")
    assert_candidate_slot_available(out_dir)
    candidate = fork_candidate(client, out_dir, parent, name)
    candidate["builder"] = {"kind": "skilled-live-build", "status": "running",
                            "startedAt": _now()}
    candidate["qc"] = {"status": "pending", "approved": False}
    return save_candidate(out_dir, candidate)


def _candidate_and_parent(client: Any, parent: dict,
                          candidate: dict) -> tuple[Any, Any]:
    project_id = str(parent.get("projectId"))
    visible = read_active(client, project_id)
    if visible.timeline_id not in {parent.get("timelineId"),
                                   candidate.get("timelineId")}:
        raise TimelineConflict("Palmier is showing another timeline; live build stopped")
    if visible.timeline_id == parent.get("timelineId") \
            and compare_authority(parent, visible) != "unchanged":
        raise TimelineConflict("Palmier canonical parent changed before live build")
    candidate_now = visible if visible.timeline_id == candidate.get("timelineId") \
        else activate_and_read(client, project_id, str(candidate.get("timelineId")))
    parent_now = visible if visible.timeline_id == parent.get("timelineId") \
        else activate_and_read(client, project_id, str(parent.get("timelineId")))
    if compare_authority(parent, parent_now) != "unchanged":
        raise TimelineConflict("Palmier canonical parent changed during live build")
    active = activate_and_read(client, project_id, candidate_now.timeline_id)
    if active.fingerprint != candidate_now.fingerprint:
        raise TimelineConflict("Palmier candidate changed while restoring visibility")
    if active.coverage.get("complete") is not True:
        raise TimelineConflict("Palmier candidate readback is incomplete")
    return parent_now, active


def _observed_candidate(candidate: dict, found: Any) -> dict:
    observed = dict(candidate)
    observed.update({
        "projectId": found.project_id,
        "timelineId": found.timeline_id,
        "fingerprint": found.fingerprint,
        "semanticFingerprint": found.semantic_fingerprint,
        "timeline": found.timeline,
        "readbackCoverage": found.coverage,
    })
    return observed


def observe_live_candidate(client: Any, out_dir: str) -> dict:
    """Read the exact candidate without refreshing its retained receipt."""
    parent, candidate = _records(out_dir)
    _parent_now, found = _candidate_and_parent(client, parent, candidate)
    return _observed_candidate(candidate, found)


def resume_live_candidate(client: Any, out_dir: str,
                          expected_fingerprint: str | None = None) -> dict:
    """Adopt the visible partial candidate while preserving the parent authority."""
    parent, candidate = _records(out_dir)
    _parent_now, found = _candidate_and_parent(client, parent, candidate)
    if expected_fingerprint is not None \
            and found.fingerprint != expected_fingerprint:
        raise TimelineConflict(
            "Palmier candidate changed after resume reconciliation")
    refreshed = record_candidate(out_dir, found, parent)
    refreshed.update({key: value for key, value in candidate.items()
                      if key not in refreshed})
    refreshed.update({"status": "edited", "fingerprint": found.fingerprint,
                      "semanticFingerprint": found.semantic_fingerprint,
                      "timeline": found.timeline,
                      "readbackCoverage": found.coverage})
    builder = dict(refreshed.get("builder") or {})
    builder.update({"kind": "skilled-live-build", "status": "running",
                    "resumedAt": _now()})
    refreshed["builder"] = builder
    return save_candidate(out_dir, refreshed)


def _authority(path: str, out_dir: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise PalmierError(f"cannot read Palmier live-build authority: {exc}") from exc
    if not isinstance(value, dict) or value.get("schemaVersion") != 1 \
            or value.get("kind") != "palmier-live-build-qc-authority":
        raise PalmierError("Palmier live-build authority envelope is malformed")
    ctx, live_input = value.get("ctx"), value.get("liveInput")
    if not isinstance(ctx, dict) or not isinstance(live_input, dict) \
            or os.path.realpath(str(ctx.get("dir"))) != os.path.realpath(out_dir):
        raise PalmierError("Palmier live-build authority targets another project")
    input_path, digest = live_input.get("path"), live_input.get("hash")
    if not isinstance(input_path, str) or not os.path.isfile(input_path) \
            or file_sha256(input_path) != digest:
        raise PalmierError("Palmier live-build input artifact changed")
    return value


def _archive_prior_qc(out_dir: str, candidate: dict,
                      authority: dict) -> list[str]:
    prior = candidate.get("liveBuildAuthority") or {}
    if not isinstance(prior, dict) or prior.get("captureId") == authority.get("captureId") \
            or not os.path.isfile(qc_path(out_dir)):
        return list(candidate.get("qcHistory") or [])
    receipt = load_qc(out_dir)
    review_dir = os.path.join(out_dir, ".sniper-learning", "runs",
                              str(prior.get("captureId")), "candidate-qc")
    reviews = sorted(glob.glob(os.path.join(review_dir, "*.json")))
    reason = {"schemaVersion": 1, "reason": "retained-session-scoped-repair",
              "reviewArtifacts": reviews, "archivedAt": _now()}
    archive = archive_rejected_candidate(out_dir, candidate, receipt, reason)
    return [*list(candidate.get("qcHistory") or []), archive]


def checkpoint_live_candidate(
    client: Any,
    out_dir: str,
    authority_path: str,
    expected_fingerprint: str | None = None,
) -> dict:
    """Bind fresh candidate readback to immutable plan/journal QC authority."""
    parent, candidate = _records(out_dir)
    authority = _authority(authority_path, out_dir)
    _parent_now, found = _candidate_and_parent(client, parent, candidate)
    if expected_fingerprint is not None \
            and found.fingerprint != expected_fingerprint:
        raise TimelineConflict(
            "Palmier candidate changed after journal closure")
    parent_semantic = parent.get("semanticFingerprint")
    if not isinstance(parent_semantic, str) \
            or not isinstance(found.semantic_fingerprint, str):
        raise PalmierError("Palmier live build semantic readback is incomplete")
    if found.semantic_fingerprint == parent_semantic:
        raise PalmierError("Palmier live build made no observable candidate change")
    live_input = authority["liveInput"]
    if live_input.get("parent") != identity(parent):
        raise TimelineConflict("Palmier live-build input names a stale parent")
    history = _archive_prior_qc(out_dir, candidate, authority)
    staged = record_candidate(out_dir, found, parent)
    staged.update({
        "status": "edited", "requestHash": authority.get("requestHash"),
        "lanes": live_input.get("lanes"),
        "operations": {"count": live_input.get("operationCount"),
                       "journalHash": live_input.get("journalHash"),
                       "lifecycleDigest":
                       live_input.get("journalLifecycleDigest"),
                       "headFingerprint": live_input.get("headFingerprint")},
        "liveBuildAuthority": authority,
        "builder": {"kind": "skilled-live-build", "status": "built",
                    "sessionId": live_input.get("sessionId"),
                    "completedAt": _now()},
        "qc": {"status": "pending", "approved": False},
        "qcHistory": history,
        "parentRestoration": {"status": "deferred-until-qc",
                              "error": None, "at": _now()},
    })
    return save_candidate(out_dir, staged)
