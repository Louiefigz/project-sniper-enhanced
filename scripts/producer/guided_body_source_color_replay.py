"""Closed body replay references and original metadata joins, never live authority.

The server authenticates the selected/stopped/final-cleanup lineage. This module
only validates its separately hash-bound control data. No source, tool, runtime,
process, clock, observation replay or ownership object is acquired here.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from color.grade_contract import closed, integer
from cut_preview_io import MAX_JSON, digest
from guided_opening_claim import _KEYS, _identity as claim_identity
from guided_source_color_observation_rows import same_observation_data as same
from guided_source_color_staging_contract import (
    _hash, _literal, _path, _reference, _uuid, validate_source_color_staging,
)

SCOPE = "original-opening-source-color-replay-not-execution-or-approval"
HASHES = {"selectionHash", "claimHash", "cleanupHash", "inputSha256", "executionInputHash", "mediaResultSha256", "receiptHash"}
KEYS = {"schemaVersion", "kind", "scope", "opening", "sourceColorHash", "input", "reservationArchive",
        "executable", "bodyApproved", "deliveryApproved"}


def validate_body_source_color_replay(value: object) -> dict:
    """Mirror the detached TS schema2 shape without treating valid hashes as proof."""
    row = closed(value, KEYS, "body source-color replay references")
    _literal(row, {"schemaVersion": 2, "kind": "guided-body-source-color-replay-references", "scope": SCOPE,
                   "executable": False, "bodyApproved": False, "deliveryApproved": False})
    opening = closed(row["opening"], HASHES | {"executionId"}, "body replay original opening")
    for key in HASHES:
        _hash(opening[key])
    execution_id = _uuid(opening["executionId"], True)
    _hash(row["sourceColorHash"])
    source, archive = _reference(row["input"]), _reference(row["reservationArchive"])
    suffix = f"/executions/{execution_id}/source-color/input.json"
    if not source["path"].endswith(suffix):
        raise ValueError("body replay input differs from its opening execution")
    execution = _path(source["path"]).parent.parent
    target = _path(archive["path"])
    if target != execution / "cleanup-attempts" / target.parent.name / "reservation.json":
        raise ValueError("body replay archive differs from its opening execution root/role")
    _uuid(target.parent.name, True)
    return deepcopy(row)


def body_source_color_control_refs(replay: dict, original: dict) -> dict:
    """Only three explicit bounded metadata files; no active marker or job discovery."""
    row = validate_body_source_color_replay(replay)
    execution = _path(row["input"]["path"]).parent.parent
    expected = {"claimPath": execution / "execution-claim.json", "inputPath": execution / "media-input/input.json",
                "outputRoot": execution / "media-output"}
    if any(_path(original[key]) != path for key, path in expected.items()):
        raise ValueError("body source-color original opening path roles differ")
    return {"openingSourceColorInput": row["input"], "openingSourceColorArchive": row["reservationArchive"],
            "openingExecutionClaim": {"path": str(_path(original["claimPath"])), "sha256": _hash(original["claimSha256"])}}


def _original_claim(documents: dict, original: dict) -> dict:
    """Keep raw claim SHA separate from its semantic digest and never admit old runtime."""
    claim = closed(documents["openingExecutionClaim"], _KEYS, "body original opening claim")
    claim_identity(claim, documents["openingInput"],
                   (Path(original["inputPath"]), original["inputSha256"], Path(original["outputRoot"])))
    if claim["requestId"] != Path(original["claimPath"]).parents[2].name:
        raise ValueError("body original opening claim request differs from its path")
    return claim


def _opening(replay: dict, documents: dict, original: dict) -> dict:
    """Join the existing approved parent, original receipt and separately read claim."""
    held = documents["heldInput"]["input"]
    claim = _original_claim(documents, original)
    same(replay["opening"], {"selectionHash": held["selectionHash"], "claimHash": digest(claim),
        "cleanupHash": documents["approvedSnapshot"]["guidedHandoffV2"]["openingCleanupHash"],
        "executionId": claim["executionId"], "inputSha256": original["inputSha256"],
        "executionInputHash": original["executionInputHash"], "mediaResultSha256": original["resultSha256"],
        "receiptHash": documents["openingResult"]["receiptHash"]})
    same(held["origin"], {"clockHash": claim["clockHash"], "startedAt": claim["generationStartedAt"]})
    return claim


def _result(record: dict, original: dict) -> None:
    """A source2 control cannot downgrade its source2 receipt or omit its evidence ref."""
    _literal(record, {"schemaVersion": 2, "kind": "guided-opening-media-result", "status": "complete",
                      "openingApproved": False, "deliveryApproved": False})
    ref = closed(record["sourceColorEvidence"], {"path", "sha256", "sizeBytes", "receiptHash"}, "body opening source-color evidence")
    if _path(ref["path"]) != _path(original["outputRoot"]) / "source-color-evidence.json":
        raise ValueError("body opening source-color evidence escaped original output")
    _hash(ref["sha256"])
    _hash(ref["receiptHash"])
    integer(ref["sizeBytes"], 1, MAX_JSON)


def join_body_source_color_controls(replay: dict, documents: dict, original: dict, producer: Path) -> None:
    """Cross-bind actual read control metadata, not decoded sources or cleanup authority."""
    replay = validate_body_source_color_replay(replay)
    same(replay, documents["heldInput"]["input"]["sourceColorReplay"])
    claim = _opening(replay, documents, original)
    _result(documents["openingResult"], original)
    archive = documents["openingSourceColorArchive"]
    sidecar = validate_source_color_staging(documents["openingSourceColorInput"], archive)
    expected = {"claimPath": original["claimPath"], "claimSha256": original["claimSha256"],
        **{key: claim[key] for key in ("inputPath", "inputSha256", "executionId", "executionInputHash",
                                     "clockHash", "generationStartedAt", "budgetAdmissionHash", "beforeJournalHash")}}
    same(sidecar["opening"], expected)
    same(sidecar["producerDir"], str(producer))
    same(archive["runtime"], claim["runtime"])
    same(replay["sourceColorHash"], archive["sourceColorHash"])
    same(replay["input"]["path"], archive["sidecarPath"])
    same(replay["reservationArchive"], {**sidecar["reservation"], "path": replay["reservationArchive"]["path"]})
    same(sidecar["expected"]["manifestSha256"], documents["openingInput"]["documents"]["manifest"]["sha256"])
