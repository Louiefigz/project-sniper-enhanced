"""Fail-closed reopen contract for one picture-repair surgical terminal."""
from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass
from pathlib import Path

from edit.compatibility_projection import build_projection, stable_digest
from edit.cut_repair_picture_plan_authority import (
    validate_picture_plan_authority_for_plan,
)
from edit.exact_timing import PositiveRational, ProjectClock
from edit.picture_lock_common import content_hash, require_hash
from edit.repair_fragment_contracts import validate_repair
from fingerprints import file_sha256, plan_content_hash

_PREPARED_KEYS = {
    "schemaVersion", "kind", "parentRevisionHash", "contextAuthorityHash",
    "operation", "operationHash", "selectionPolicy", "selectionPolicyHash",
    "projectSampleRate", "reviewPlan", "reviewPlanHash", "reviewProjection",
    "reviewTimelineMapHash", "fragmentReceipt", "compositeReceipt",
}
_FRAGMENT_KEYS = {
    "schemaVersion", "kind", "operationHash", "method", "edge",
    "exactOutputDurationPreserved", "dirtyFrameRange", "dirtySampleRange",
    "frameBoundaryResidualSamples", "retime", "inputs", "output", "tools",
    "unchangedPictureMappingRanges", "evidencePolicy",
}
_COMPOSITE_KEYS = {
    "schemaVersion", "kind", "operationHash", "fragmentReceiptHash", "clock",
    "dirtyFrameRange", "dirtySampleRange", "terminalExpectedSamples",
    "exactOutputDurationPreserved", "inputs", "output",
    "outsideDirtyOracle", "tools",
}
_ORACLE_KEYS = {
    "pictureScope", "parentPictureSha256", "outputPictureSha256",
    "parentPcmSha256", "outputPcmSha256", "pictureMatches", "pcmMatches",
}
_SUPPORTED_PLAN_KEYS = {
    "planVersion", "target", "cutTrack", "cutDecisions",
    "cutRepairPicturePlanAuthority",
}
_CLOCK = ProjectClock(PositiveRational(30, 1), 48_000)

class SurgicalTerminalError(RuntimeError):
    """Prepared media cannot honestly become the terminal review candidate."""

@dataclass(frozen=True)
class SurgicalTerminalAuthority:
    """Reopened exact authority consumed by the graph stager."""
    plan: dict
    parent_plan: dict
    parent_plan_content_hash: str
    manifest: dict
    prepared: dict
    operation: dict
    authority: dict
    fragment: dict
    composite: dict
    composite_path: Path
    candidate_hash: str
    dependency_partition_hash: str
    source_selection: dict

def _object(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise SurgicalTerminalError(f"{label} must be an object")
    return value

def _closed(value: object, keys: set[str], label: str) -> dict:
    row = _object(value, label)
    if set(row) != keys:
        raise SurgicalTerminalError(f"{label} has unknown or missing fields")
    return row


def _json(path: Path, label: str) -> dict:
    if not path.is_absolute() or path.resolve() != path \
            or path.is_symlink() or not path.is_file():
        raise SurgicalTerminalError(f"{label} is not a regular file")
    try:
        return _object(json.loads(path.read_text(encoding="utf-8")), label)
    except json.JSONDecodeError as exc:
        raise SurgicalTerminalError(f"{label} is not valid JSON") from exc


def _media(path_value: object, expected: object, label: str) -> Path:
    expected_hash = require_hash(expected, f"{label} hash")
    if not isinstance(path_value, str) or not os.path.isabs(path_value):
        raise SurgicalTerminalError(f"{label} path is not absolute")
    path = Path(path_value)
    if path.is_symlink() or not path.is_file() \
            or path.resolve() != path or file_sha256(str(path)) != expected_hash:
        raise SurgicalTerminalError(f"{label} bytes are stale")
    return path


def _plan(prepared: dict, plan_path: Path) -> tuple[dict, dict]:
    plan = _json(plan_path, "surgical review plan")
    supplied = _object(prepared.get("reviewPlan"), "prepared review plan")
    plan_hash = require_hash(
        prepared.get("reviewPlanHash"), "prepared review plan hash")
    if plan != supplied or stable_digest(plan) != plan_hash:
        raise SurgicalTerminalError("prepared review plan changed identity")
    unsupported = sorted(set(plan) - _SUPPORTED_PLAN_KEYS)
    if unsupported:
        raise SurgicalTerminalError(
            "SURGICAL_TERMINAL_PLAN_LANE_UNSUPPORTED:"
            + ",".join(unsupported))
    authority = validate_picture_plan_authority_for_plan(plan)
    if authority is None:
        raise SurgicalTerminalError(
            "surgical terminal has no plan-carried picture authority")
    projection = build_projection(plan, stable_digest(plan))
    if projection != prepared.get("reviewProjection") \
            or projection["timelineMapHash"] \
            != prepared.get("reviewTimelineMapHash"):
        raise SurgicalTerminalError("prepared review timeline changed identity")
    return plan, authority


def _parent_plan(plan: dict, authority: dict) -> dict:
    parent = copy.deepcopy(plan)
    parent.pop("cutRepairPicturePlanAuthority", None)
    index = authority["target"]["index"]
    parent["cutTrack"][index] = authority["parentCutRow"]
    if stable_digest(parent) != authority["parentPlanObjectHash"]:
        raise SurgicalTerminalError(
            "picture reversion does not reconstruct the exact parent plan")
    projection = build_projection(parent, stable_digest(parent))
    if projection["timelineMapHash"] != authority["parentTimelineMapHash"]:
        raise SurgicalTerminalError(
            "picture reversion does not reconstruct the parent timeline")
    return parent


def _operation(prepared: dict, authority: dict) -> dict:
    operation = _object(prepared.get("operation"), "repair operation")
    operation_hash = require_hash(
        prepared.get("operationHash"), "repair operation hash")
    policy = _object(prepared.get("selectionPolicy"), "selection policy")
    if content_hash(operation) != operation_hash \
            or content_hash(policy) != prepared.get("selectionPolicyHash"):
        raise SurgicalTerminalError("repair operation or selection is stale")
    repair = validate_repair(operation, operation_hash, _CLOCK)
    if repair.method != "extend-and-reclaim-silence" \
            or repair.quantization_residual_samples != 0 \
            or operation.get("revalidatedDependentIds") != []:
        raise SurgicalTerminalError(
            "SURGICAL_TERMINAL_DEPENDENT_OR_CLOCK_SUBSET_UNSUPPORTED")
    unchanged = operation.get("unchangedDependentIds")
    if not isinstance(unchanged, list) \
            or len(unchanged) != len(set(unchanged)) \
            or any(not isinstance(item, str) or not item for item in unchanged):
        raise SurgicalTerminalError("repair dependent partition is malformed")
    if authority["operationHash"] != operation_hash \
            or authority["parentTimelineMapHash"] \
            != operation.get("parentTimelineMapHash") \
            or authority["childTimelineMapHash"] \
            != prepared.get("reviewTimelineMapHash"):
        raise SurgicalTerminalError("picture authority binds another operation")
    return operation


def _fragment(prepared: dict, operation: dict) -> dict:
    receipt = _closed(
        prepared.get("fragmentReceipt"), _FRAGMENT_KEYS, "fragment receipt")
    output = _object(receipt.get("output"), "fragment output")
    inputs = _object(receipt.get("inputs"), "fragment inputs")
    parent = _object(inputs.get("parent"), "fragment parent")
    source = _object(inputs.get("source"), "fragment source")
    _media(output.get("path"), output.get("sha256"), "fragment output")
    for row, label in ((parent, "fragment parent"),
                       (source, "fragment source")):
        require_hash(row.get("sha256"), f"{label} hash")
    if receipt.get("schemaVersion") != 1 \
            or receipt.get("kind") != "cut-repair-fragment" \
            or receipt.get("operationHash") != content_hash(operation) \
            or receipt.get("method") != "extend-and-reclaim-silence" \
            or receipt.get("exactOutputDurationPreserved") is not True \
            or receipt.get("frameBoundaryResidualSamples") != 0 \
            or receipt.get("dirtyFrameRange") \
            != operation["pictureDirtyWindows"][0] \
            or receipt.get("dirtySampleRange") \
            != operation["audioDirtySampleRanges"][0]:
        raise SurgicalTerminalError("fragment receipt is not exact picture media")
    return receipt


def _oracle(value: object) -> dict:
    oracle = _closed(value, _ORACLE_KEYS, "outside-dirty oracle")
    hashes = (
        "parentPictureSha256", "outputPictureSha256",
        "parentPcmSha256", "outputPcmSha256",
    )
    for name in hashes:
        require_hash(oracle.get(name), f"outside-dirty {name}")
    if oracle.get("pictureScope") != "outside-dirty" \
            or oracle.get("pictureMatches") is not True \
            or oracle.get("pcmMatches") is not True \
            or oracle["parentPictureSha256"] \
            != oracle["outputPictureSha256"] \
            or oracle["parentPcmSha256"] != oracle["outputPcmSha256"]:
        raise SurgicalTerminalError(
            "composite did not preserve exact decoded media outside dirty")
    return oracle


def _composite(prepared: dict, operation: dict, fragment: dict) -> tuple[dict, Path]:
    receipt = _closed(
        prepared.get("compositeReceipt"), _COMPOSITE_KEYS,
        "composite receipt")
    output = _object(receipt.get("output"), "composite output")
    inputs = _object(receipt.get("inputs"), "composite inputs")
    fragment_inputs = _object(fragment["inputs"], "fragment inputs")
    path = _media(
        output.get("path"), output.get("sha256"), "composite output")
    _oracle(receipt.get("outsideDirtyOracle"))
    terminal = operation.get("totalOutputFramesAfter")
    if receipt.get("schemaVersion") != 1 \
            or receipt.get("kind") != "cut-repair-composite" \
            or receipt.get("operationHash") != content_hash(operation) \
            or receipt.get("fragmentReceiptHash") != content_hash(fragment) \
            or receipt.get("exactOutputDurationPreserved") is not True \
            or receipt.get("dirtyFrameRange") \
            != operation["pictureDirtyWindows"][0] \
            or receipt.get("dirtySampleRange") \
            != operation["audioDirtySampleRanges"][0] \
            or output.get("videoFrames") != terminal \
            or output.get("audioSamplesPerChannel") \
            != receipt.get("terminalExpectedSamples") \
            or inputs.get("fragmentSha256") != fragment["output"]["sha256"] \
            or inputs.get("parentSha256") \
            != fragment_inputs["parent"]["sha256"] \
            or receipt.get("tools") != fragment.get("tools"):
        raise SurgicalTerminalError("composite receipt is not terminal exact media")
    return receipt, path


def _source_selection(
    manifest: dict, operation: dict, fragment: dict,
) -> dict:
    target = _object(operation.get("target"), "repair target")
    source_id = target.get("sourceId")
    rows = [
        row for row in manifest.get("sources", [])
        if isinstance(row, dict) and row.get("id") == source_id
    ]
    if len(rows) != 1:
        raise SurgicalTerminalError("repair source is not unique in manifest")
    row = rows[0]
    observed = _object(fragment["inputs"], "fragment inputs")["source"]
    source_hash = row.get("sourceSha256", row.get("contentHash"))
    if source_hash != observed.get("sha256"):
        raise SurgicalTerminalError("fragment used a foreign source snapshot")
    return {
        "sourceId": source_id,
        "sourceMediaSha256": require_hash(
            source_hash, "selected source media hash"),
        "sourceExtension": operation["sourceExtension"],
        "sourceFrameRange": operation["sourceVideoFrameRange"],
    }


def load_surgical_terminal_authority(
    plan_path: Path,
    manifest_path: Path,
    prepared_path: Path,
) -> SurgicalTerminalAuthority:
    """Reopen every plan, receipt, source, and decoded-oracle binding."""
    prepared = _closed(
        _json(prepared_path, "prepared media"), _PREPARED_KEYS,
        "prepared media")
    if prepared.get("schemaVersion") != 1 \
            or prepared.get("kind") != "cut-repair-prepared-media" \
            or prepared.get("projectSampleRate") != 48_000:
        raise SurgicalTerminalError("prepared media version is unsupported")
    plan, authority = _plan(prepared, plan_path)
    parent_plan = _parent_plan(plan, authority)
    operation = _operation(prepared, authority)
    fragment = _fragment(prepared, operation)
    composite, composite_path = _composite(prepared, operation, fragment)
    manifest = _json(manifest_path, "render manifest")
    selection = _source_selection(manifest, operation, fragment)
    partition = {
        "revalidatedDependentIds": operation["revalidatedDependentIds"],
        "unchangedDependentIds": operation["unchangedDependentIds"],
    }
    return SurgicalTerminalAuthority(
        plan=plan, parent_plan=parent_plan,
        parent_plan_content_hash=plan_content_hash(parent_plan),
        manifest=manifest, prepared=prepared, operation=operation,
        authority=authority, fragment=fragment, composite=composite,
        composite_path=composite_path,
        candidate_hash=composite["output"]["sha256"],
        dependency_partition_hash=content_hash(partition),
        source_selection=selection)
