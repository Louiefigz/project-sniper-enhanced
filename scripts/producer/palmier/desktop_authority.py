#!/usr/bin/env python3
"""Durable staged authority for Claude Code Desktop driving Palmier MCP."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from fingerprints import file_sha256
from palmier.candidate_receipt import load_candidate, save_candidate
from palmier.desktop_element_types import RecoveryObservation
from palmier.desktop_elements import recover_bound_operation
from palmier.desktop_ledger import refresh_element_ledger
from palmier.desktop_quality import qc_authority
from palmier.desktop_revision_progress import (initialize_revision_progress,
                                                record_revision_binding,
                                                revision_complete)
from palmier.desktop_state import (JOURNAL_NAME, DesktopStageInput,
                                   append_journal, load_pointer, load_state,
                                   now, read_record, save_state, state_path)
from palmier.live_build_candidate import fork_live_candidate
from palmier.mcp_client import PalmierError
from palmier.timeline_authority import read_active, record_authority
REVIEW_CHECKS = {
    "composition": {"framing", "occlusion", "typography", "contrast",
                    "color", "transitions", "blankFrames"},
    "editorial": {"spelling", "wordLock", "graphicVariety",
                  "graphicRelevance", "pacing", "audio"},
}


def _active_project(client: Any) -> dict:
    payload = client.call_json("get_projects", {})
    rows = payload.get("projects") if isinstance(payload, dict) else None
    active = [row for row in rows or [] if isinstance(row, dict)
              and row.get("isActive") is True]
    if len(active) != 1 or not isinstance(active[0].get("id"), str):
        raise PalmierError("Palmier must have exactly one active project")
    return active[0]


def _receipt(path: str, out_dir: str, label: str) -> dict:
    """Snapshot authority bytes so in-place source edits cannot stale history."""
    absolute = os.path.abspath(path)
    if not os.path.isfile(absolute) or os.path.islink(absolute):
        raise PalmierError(f"Desktop Palmier input is not a regular file: {absolute}")
    digest = file_sha256(absolute)
    root = os.path.join(out_dir, ".palmier-desktop-inputs")
    os.makedirs(root, exist_ok=True)
    target = os.path.join(root, f"{label}-{digest}.json")
    if not os.path.isfile(target):
        temp = f"{target}.{os.getpid()}.tmp"
        try:
            with open(absolute, "rb") as source, open(temp, "xb") as handle:
                handle.write(source.read())
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, target)
        finally:
            try:
                os.unlink(temp)
            except FileNotFoundError:
                pass
    if file_sha256(target) != digest:
        raise PalmierError(f"Desktop Palmier {label} snapshot is corrupt")
    return {"path": target, "hash": digest}


def _project_state(project: dict, timeline: dict) -> dict:
    return {
        "projectName": str(project.get("name") or "Palmier project"),
        "projectSettings": {"fps": timeline.get("fps"),
                            "width": timeline.get("width"),
                            "height": timeline.get("height")},
    }


def _source_bootstrap(timeline: dict) -> None:
    """Cut-first Desktop builds require one full-length source video clip."""
    videos = []
    for track in timeline.get("tracks") or []:
        if not isinstance(track, dict) or "audio" in str(
                track.get("type", track.get("trackType", ""))).lower():
            continue
        videos.extend(clip for clip in track.get("clips") or []
                      if isinstance(clip, dict)
                      and clip.get("mediaType") != "audio")
    total = timeline.get("totalFrames")
    valid = len(videos) == 1 and isinstance(total, int) and total > 0 \
        and videos[0].get("frames") == [0, total]
    if not valid:
        raise PalmierError(
            "Desktop cut stage requires one uncut full-length source clip; "
            "open the source bootstrap timeline instead of an edited timeline")


def _normalized_inputs(inputs: DesktopStageInput) -> DesktopStageInput:
    transcripts = os.path.abspath(inputs.transcripts_dir) \
        if inputs.transcripts_dir else None
    return DesktopStageInput(
        os.path.abspath(inputs.repo), os.path.abspath(inputs.out_dir),
        os.path.abspath(inputs.plan_path),
        os.path.abspath(inputs.manifest_path), inputs.stage, transcripts,
        os.path.abspath(inputs.revision_path) if inputs.revision_path else None)


def begin(client: Any, inputs: DesktopStageInput,
          hours: float = 3.0) -> dict:
    """Adopt visible truth, fork a safe candidate, and unlock one stage."""
    if hours <= 0 or hours > 12:
        raise PalmierError("Desktop Palmier lease must be within 0-12 hours")
    inputs = _normalized_inputs(inputs)
    out_dir = inputs.out_dir
    os.makedirs(out_dir, exist_ok=True)
    from palmier.desktop_gates import run_desktop_gates
    from palmier.desktop_manifest import prepare_desktop_manifest
    gates = run_desktop_gates(inputs)
    project = _active_project(client)
    visible = read_active(client, project["id"])
    if inputs.stage == "cut":
        _source_bootstrap(visible.timeline)
    parent = record_authority(out_dir, visible, "palmier-manual")
    candidate = fork_live_candidate(client, out_dir, "Sniper · Desktop candidate")
    project_state = _project_state(project, candidate["timeline"])
    prepared = prepare_desktop_manifest(inputs, project_state)
    journal = os.path.join(out_dir, JOURNAL_NAME)
    with open(journal, "x", encoding="utf-8"):
        pass
    state = {
        "schemaVersion": 1, "kind": "palmier-desktop-authority",
        "status": "active", "stage": inputs.stage, "outDir": out_dir,
        "createdAt": now(), "updatedAt": now(),
        "expiresAt": (datetime.now(timezone.utc)
                      + timedelta(hours=hours)).isoformat(timespec="seconds"),
        "projectId": project["id"], "projectPath": project.get("path"),
        "parent": {key: parent[key] for key in
                   ("projectId", "timelineId", "fingerprint")},
        "candidate": {"projectId": candidate["projectId"],
                      "timelineId": candidate["timelineId"],
                      "fingerprint": candidate["fingerprint"]},
        "expectedFingerprint": candidate["fingerprint"],
        "plan": _receipt(inputs.plan_path, out_dir, "plan"),
        "manifest": _receipt(inputs.manifest_path, out_dir, "manifest"),
        "gates": {key: gates[key] for key in ("path", "hash")},
        "operations": {key: prepared[key] for key in ("path", "hash")},
        "journalPath": journal, "operationCount": 0,
        "verifiedOperationKeys": [], "pendingOperation": None,
        **project_state,
    }
    append_journal(state, {"event": "desktop_begin", "at": now(),
                           "stage": inputs.stage,
                           "candidate": state["candidate"]})
    return save_state(os.path.abspath(inputs.repo), state)


def _assert_head(client: Any, state: dict) -> Any:
    found = read_active(client, state["projectId"])
    if found.timeline_id != state["candidate"]["timelineId"]:
        raise PalmierError("Palmier is not showing the Desktop candidate")
    if found.fingerprint != state["expectedFingerprint"]:
        raise PalmierError("Palmier candidate drifted from the last verified mutation")
    return found


def advance(client: Any, inputs: DesktopStageInput) -> dict:
    """Keep the candidate, bind new plan bytes, and unlock the next lane set."""
    _path, state = load_pointer(inputs.repo)
    found = _assert_head(client, state)
    if state.get("pendingOperation"):
        raise PalmierError("reconcile the pending Palmier operation before advancing")
    if inputs.stage in {"repair", "revision"}:
        refresh_element_ledger(state, found.timeline)
    from palmier.desktop_gates import run_desktop_gates
    from palmier.desktop_manifest import prepare_desktop_manifest
    stage_inputs = DesktopStageInput(
        inputs.repo, state["outDir"], inputs.plan_path,
        inputs.manifest_path, inputs.stage, inputs.transcripts_dir,
        inputs.revision_path)
    gates = run_desktop_gates(stage_inputs)
    prepared = prepare_desktop_manifest(stage_inputs, state)
    state.update({"stage": inputs.stage, "status": "active",
                  "updatedAt": now(),
                  "plan": _receipt(inputs.plan_path, state["outDir"], "plan"),
                  "manifest": _receipt(inputs.manifest_path, state["outDir"],
                                       "manifest"),
                  "gates": {key: gates[key] for key in ("path", "hash")},
                  "operations": {key: prepared[key]
                                 for key in ("path", "hash")}})
    state.pop("qc", None)
    state.pop("reviews", None)
    revision = prepared.get("revision")
    if isinstance(revision, dict):
        state["revision"] = {key: revision[key]
                             for key in ("revisionSetId", "path", "hash")}
        initialize_revision_progress(state, prepared["content"].get("revision"))
    else:
        state.pop("revision", None)
        initialize_revision_progress(state, None)
    append_journal(state, {"event": "desktop_advance", "at": now(),
                           "stage": inputs.stage,
                           "planHash": state["plan"]["hash"]})
    return save_state(inputs.repo, state)


def reconcile(client: Any, repo: str, media_ref: str | None = None) -> dict:
    """Recover a mutation that landed before its PostToolUse receipt did."""
    _path, state = load_pointer(repo)
    found = read_active(client, state["projectId"])
    pending = state.get("pendingOperation")
    if not pending or found.timeline_id != state["candidate"]["timelineId"]:
        raise PalmierError("Desktop Palmier has no safely reconcilable operation")
    candidate = load_candidate(state["outDir"])
    if candidate is None or not isinstance(candidate.get("timeline"), dict):
        raise PalmierError("Desktop Palmier candidate has no prior readback")
    changed = found.fingerprint != pending.get("beforeFingerprint")
    binding = pending.get("binding")
    resource_landed = isinstance(binding, dict) \
        and binding.get("kind") == "resource"
    if not changed and not resource_landed:
        state["pendingOperation"] = None
    else:
        try:
            recover_bound_operation(RecoveryObservation(
                state, pending, candidate["timeline"], found.timeline, client,
                media_ref))
        except PalmierError:
            state.update({"status": "paused", "updatedAt": now()})
            save_state(repo, state)
            raise
        state["expectedFingerprint"] = found.fingerprint
        state["candidate"]["fingerprint"] = found.fingerprint
        state["operationCount"] += 1
        state["verifiedOperationKeys"].append(pending["key"])
        record_revision_binding(state, pending.get("binding"))
        append_journal(state, {**pending, "event": "operation_reconciled",
                               "at": now(), "afterFingerprint": found.fingerprint,
                               "timelineChanged": changed})
        candidate.update({"status": "edited", "fingerprint": found.fingerprint,
                          "semanticFingerprint": found.semantic_fingerprint,
                          "timeline": found.timeline,
                          "readbackCoverage": found.coverage})
        save_candidate(state["outDir"], candidate)
        state["pendingOperation"] = None
    state.update({"status": "active", "updatedAt": now()})
    return save_state(repo, state)


def run_qc(client: Any, repo: str) -> dict:
    """Export the exact current candidate and run deterministic native Audit B."""
    _path, state = load_pointer(repo)
    found = _assert_head(client, state)
    if state.get("pendingOperation"):
        raise PalmierError("Desktop Palmier QC cannot run with a pending operation")
    if not revision_complete(state):
        raise PalmierError("Desktop Palmier revision still has unverified mutations")
    from palmier.native_qc_audit import run_native_audit
    from palmier.native_qc_export import export_candidate
    export = export_candidate(client, state["outDir"], found)
    receipt = {"outDir": state["outDir"], "export": export,
               "authority": qc_authority(state)}
    audit = run_native_audit(state["outDir"], receipt, found)
    state.update({"status": "review-required", "updatedAt": now(),
                  "qc": {"export": export, "audit": audit,
                         "reviewContract": {key: sorted(value)
                                            for key, value in REVIEW_CHECKS.items()}}})
    append_journal(state, {"event": "deterministic_qc_passed", "at": now(),
                           "auditDigest": audit["digest"]})
    return save_state(repo, state)
def approve(client: Any, repo: str, reviews_path: str) -> dict:
    """Require composition and editorial reviews bound to the exact export."""
    _path, state = load_pointer(repo)
    _assert_head(client, state)
    if state.get("status") != "review-required":
        raise PalmierError("Desktop Palmier must pass deterministic QC first")
    reviews = read_record(reviews_path, "reviews")
    rows = reviews.get("reviews") if isinstance(reviews, dict) else None
    qc = state.get("qc") or {}
    expected = {"composition", "editorial"}
    valid = reviews.get("schemaVersion") == 1 \
        and isinstance(rows, list) and len(rows) == 2 \
        and {row.get("lens") for row in rows if isinstance(row, dict)} == expected
    for row in rows or []:
        checks = row.get("checks") if isinstance(row, dict) else None
        required = REVIEW_CHECKS.get(str(row.get("lens")), set()) \
            if isinstance(row, dict) else set()
        valid = valid and row.get("verdict") == "pass" \
            and row.get("materialIssues") == [] \
            and isinstance(checks, dict) and set(checks) == required \
            and all(value == "pass" for value in checks.values()) \
            and row.get("candidateFingerprint") == state["expectedFingerprint"] \
            and row.get("exportHash") == (qc.get("export") or {}).get("hash") \
            and row.get("auditDigest") == (qc.get("audit") or {}).get("digest")
    if not valid:
        raise PalmierError("Desktop Palmier rendered reviews are stale or did not pass")
    state.update({"status": "complete", "updatedAt": now(),
                  "reviews": _receipt(reviews_path, state["outDir"], "reviews")})
    append_journal(state, {"event": "desktop_complete", "at": now(),
                           "fingerprint": state["expectedFingerprint"]})
    return save_state(repo, state)
