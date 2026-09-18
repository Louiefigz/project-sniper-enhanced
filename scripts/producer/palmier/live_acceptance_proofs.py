"""Delta, QC, and manual-preservation proofs for live Palmier acceptance."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from palmier.candidate_receipt import load_candidate
from palmier.desktop_hook import authorize_pre
from palmier.desktop_ledger import clip_inventory
from palmier.desktop_state import load_state
from palmier.mcp_client import PalmierError
from palmier.live_acceptance_timeline_delta import \
    canonical_non_target_equal
from palmier.timeline_authority import (
    atomic_write_record, fork_candidate, read_active)
from palmier.timeline_guard import reconcile_working_authority

SENTINEL_OPACITY = 0.99


@dataclass(frozen=True)
class RepairProofInput:
    """All immutable facts needed to prove one scoped repair."""

    before: dict
    after: dict
    state: dict
    element_id: str
    files_before: dict
    prior: dict


@dataclass(frozen=True)
class ManualProofInput:
    """Authority and identity inputs for the manual-preservation proof."""

    client: Any
    repo: str
    out_dir: str
    project: dict
    element_id: str


@dataclass(frozen=True)
class GovernedBlockInput:
    """One forbidden governed mutation and its expected unchanged state."""

    client: Any
    repo: str
    out_dir: str
    clip_id: str
    fingerprint: str


def final_mtimes(root: str) -> dict[str, int]:
    """Snapshot full-render mtimes; a card repair must not touch them."""
    return {str(path): path.stat().st_mtime_ns
            for path in Path(root).rglob("final*.mp4") if path.is_file()}


def repair_scope(
        path: str, expected_element_id: str | None = None
) -> tuple[dict, str]:
    """Require one import plus the preflight-bound graphic replacement."""
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    steps = value.get("steps") if isinstance(value, dict) else None
    ops = [row.get("op") for row in steps or [] if isinstance(row, dict)]
    replacements = [row for row in steps or []
                    if isinstance(row, dict) and row.get("op") == "replace-overlay"]
    if ops != ["import", "replace-overlay"] or len(replacements) != 1:
        raise PalmierError(
            f"scoped card repair must be import+replace only, got {ops}")
    ident = replacements[0].get("elementId")
    if not isinstance(ident, str):
        raise PalmierError("scoped repair has no stable element id")
    if expected_element_id is not None and ident != expected_element_id:
        raise PalmierError(
            "scoped repair worklist targets a different graphic than preflight")
    return value, ident


def repair_delta(proof: RepairProofInput) -> dict:
    """Prove one clip-local exit without claiming post-repair full parity."""
    before, after = proof.before, proof.after
    state, prior, ident = proof.state, proof.prior, proof.element_id
    old, new = clip_inventory(before), clip_inventory(after)
    removed, added = sorted(set(old) - set(new)), sorted(set(new) - set(old))
    drift = sorted(key for key in set(old) & set(new) if old[key] != new[key])
    current = ((state.get("elementLedger") or {}).get("elements") or {}).get(ident)
    new_clip = new.get(current.get("clipId")) \
        if isinstance(current, dict) else None
    checks = {
        "oneClipRemoved": removed == [prior.get("clipId")],
        "oneClipAdded": isinstance(current, dict)
        and added == [current.get("clipId")],
        "unrelatedClipsStable": drift == [],
        "elementCurrent": isinstance(current, dict)
        and current.get("status") == "current",
        "windowStable": isinstance(current, dict)
        and [current.get("startFrame"), current.get("endFrame")]
        == [prior.get("startFrame"), prior.get("endFrame")]
        and isinstance(new_clip, dict)
        and new_clip.get("frames") == [
            current.get("startFrame"), current.get("endFrame")],
        "trackStable": isinstance(current, dict)
        and current.get("trackIndex") == prior.get("trackIndex")
        and isinstance(new_clip, dict)
        and new_clip.get("_trackIndex") == current.get("trackIndex"),
        "assetChanged": isinstance(current, dict)
        and current.get("assetHash") != prior.get("assetHash"),
        "timelineStable": all(before.get(key) == after.get(key)
                              for key in (
                                  "fps", "width", "height", "totalFrames")),
        "canonicalNonTargetTimelineStable": isinstance(current, dict)
        and isinstance(prior.get("clipId"), str)
        and isinstance(current.get("clipId"), str)
        and canonical_non_target_equal(
            before, after, prior["clipId"], current["clipId"]),
        "noFullRenderTouched": (
            proof.files_before == final_mtimes(state["outDir"])),
    }
    if not all(checks.values()):
        raise PalmierError(f"scoped card repair delta failed: {checks}")
    return {
        "proofClass": "exit-9-scoped-card-repair",
        "postRepairFullMasterParity": {"claimed": False, "reason":
                                      "clip-local repair does not rebuild final"},
        "checks": checks, "elementId": ident,
        "clipDelta": {"removed": removed, "added": added, "drift": drift},
    }


def _sentinel_count(timeline: dict) -> int:
    return sum(clip.get("opacity") == SENTINEL_OPACITY
               for clip in clip_inventory(timeline).values())


def _prove_governed_block(proof: GovernedBlockInput) -> dict:
    event = {"tool_name": "mcp__palmier-pro__set_clip_properties",
             "tool_input": {
                 "clipIds": [proof.clip_id], "opacity": 0.98}}
    try:
        authorize_pre(
            event, proof.repo, client_factory=lambda: proof.client)
    except PalmierError as exc:
        expected = "Palmier candidate changed outside verified Desktop ancestry"
        if str(exc) != expected:
            raise PalmierError(
                "governed drift proof did not return the exact ancestry block"
            ) from exc
        after = read_active(
            proof.client, load_state(proof.out_dir)["projectId"])
        if after.fingerprint != proof.fingerprint:
            raise PalmierError("governed drift block changed the manual edit") from exc
        return {"blocked": True, "error": str(exc),
                "manualFingerprintPreserved": True}
    raise PalmierError("governed hook accepted an out-of-band manual drift")


def _write_sidecar(out_dir: str, project: dict) -> None:
    atomic_write_record(os.path.join(out_dir, "palmier.sync.json"), {
        "schemaVersion": 4, "projectId": project["id"],
        "ownership": "sniper", "workspaceMode": "managed-draft"})


def _candidate_summary(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    keys = (
        "status", "origin", "projectId", "timelineId",
        "fingerprint", "semanticFingerprint",
    )
    return {key: value.get(key) for key in keys if value.get(key) is not None}


def prove_manual_preservation(proof: ManualProofInput) -> dict:
    """Land a harmless manual sentinel, block overwrite, adopt, then fork."""
    client, out_dir = proof.client, proof.out_dir
    project, ident = proof.project, proof.element_id
    state = load_state(out_dir)
    element = ((state.get("elementLedger") or {}).get("elements") or {}).get(ident)
    if not isinstance(element, dict) or not isinstance(element.get("clipId"), str):
        raise PalmierError("manual-edit target is absent from the element ledger")
    clip_id = element["clipId"]
    before = read_active(client, project["id"])
    client.call("set_clip_properties", {
        "clipIds": [clip_id], "opacity": SENTINEL_OPACITY})
    manual = read_active(client, project["id"])
    if manual.fingerprint == before.fingerprint \
            or _sentinel_count(manual.timeline) != 1:
        raise PalmierError("manual sentinel edit was not uniquely observable")
    blocked = _prove_governed_block(GovernedBlockInput(
        client, proof.repo, out_dir, clip_id, manual.fingerprint))
    _write_sidecar(out_dir, project)
    prior_candidate = load_candidate(out_dir)
    adopted, change = reconcile_working_authority(
        client, out_dir, {"projectId": project["id"]})
    superseded = load_candidate(out_dir)
    forked = fork_candidate(
        client, out_dir, adopted, "Sniper · manual-preserving fork")
    copied = read_active(client, project["id"])
    valid = (change == "candidate-manual"
             and adopted.get("origin") == "palmier-manual"
             and isinstance(superseded, dict)
             and superseded.get("status") == "superseded-manual"
             and copied.semantic_fingerprint == manual.semantic_fingerprint
             and _sentinel_count(copied.timeline) == 1)
    if not valid:
        raise PalmierError("manual edit was not safely adopted and forked")
    return {
        "targetElementId": ident, "targetClipId": clip_id,
        "sentinelOpacity": SENTINEL_OPACITY, "governedBlock": blocked,
        "manualFingerprint": manual.fingerprint, "adoptionChange": change,
        "candidateTransition": {
            "before": _candidate_summary(prior_candidate),
            "superseded": _candidate_summary(superseded),
        },
        "manualPreservingFork": {key: forked.get(key) for key in (
            "timelineId", "fingerprint", "semanticFingerprint")},
    }
