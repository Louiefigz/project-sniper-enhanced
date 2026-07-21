"""Disjoint exact initialize and quality-pass contracts for headless MP4."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from . import operation_wire as wire
from .quality_pass_input import QualityPassInputV1, parse_quality_pass_input
from .quality_receipt_json import (
    canonical_document,
    canonical_uuid,
    digest,
    exact,
    same_typed_value,
)
from .repair_intent import ParentRefV1

OperationContractError = wire.OperationWireError
_OPERATION_DOMAIN = b"sniper-headless-mp4-operation-v1\0"
_INITIALIZE_KEYS = frozenset(
    "executionPolicyId expectedParent fallbackPolicy initialBaseBuild "
    "initializationSnapshot operation realizationKind schemaVersion unitId "
    "writerRebuildAllowed".split()
)
_QUALITY_PASS_KEYS = frozenset(
    "baseRebuildAllowed executionPolicyId expectedParent fallbackPolicy operation "
    "qualityPass realizationKind schemaVersion unitId writerRebuildAllowed".split()
)


@dataclass(frozen=True)
class InitializeOperationV1:
    """Genesis-only operation rooted in one presealed immutable snapshot."""

    unit_id: str
    execution_policy_id: str
    expected_parent: None
    snapshot: wire.InitializationSnapshotAuthorityV1
    initial_base_build: str
    writer_rebuild_allowed: bool
    fallback_policy: str
    document_json: bytes
    operation_digest: str


@dataclass(frozen=True)
class QualityPassOperationV1:
    """Non-genesis no-rebuild/no-fallback operation over one exact parent."""

    unit_id: str
    execution_policy_id: str
    expected_parent: ParentRefV1
    quality_pass: QualityPassInputV1
    base_rebuild_allowed: bool
    writer_rebuild_allowed: bool
    fallback_policy: str
    document_json: bytes
    operation_digest: str


HeadlessMp4OperationV1 = InitializeOperationV1 | QualityPassOperationV1


def _operation_digest(raw: bytes) -> str:
    return hashlib.sha256(_OPERATION_DOMAIN + raw).hexdigest()


def _envelope(document: dict, keys: frozenset[str], label: str) -> tuple[str, str]:
    row = exact(document, keys, label)
    valid = (
        type(row["schemaVersion"]) is int
        and row["schemaVersion"] == 1
        and row["realizationKind"] == "deterministic-mp4"
        and row["fallbackPolicy"] == "none"
    )
    if not valid:
        raise OperationContractError(f"{label} envelope is invalid")
    unit_id = canonical_uuid(row["unitId"], "operation unit ID")
    policy_id = digest(row["executionPolicyId"], "operation execution policy")
    return unit_id, policy_id


def _parse_initialize(document: dict, raw: bytes) -> InitializeOperationV1:
    unit_id, policy_id = _envelope(document, _INITIALIZE_KEYS, "initialize operation")
    valid = (
        document["operation"] == "initialize"
        and document["expectedParent"] is None
        and document["initialBaseBuild"] == "from-presealed-snapshot"
        and type(document["writerRebuildAllowed"]) is bool
        and document["writerRebuildAllowed"] is False
    )
    if not valid:
        raise OperationContractError("initialize operation is invalid")
    snapshot = wire.parse_initialization_snapshot(document["initializationSnapshot"])
    return InitializeOperationV1(
        unit_id,
        policy_id,
        None,
        snapshot,
        document["initialBaseBuild"],
        False,
        "none",
        raw,
        _operation_digest(raw),
    )


def _parse_quality_pass(document: dict, raw: bytes) -> QualityPassOperationV1:
    unit_id, policy_id = _envelope(
        document, _QUALITY_PASS_KEYS, "quality-pass operation"
    )
    flags = (
        type(document["baseRebuildAllowed"]),
        document["baseRebuildAllowed"],
        type(document["writerRebuildAllowed"]),
        document["writerRebuildAllowed"],
    )
    if document["operation"] != "quality-pass" or flags != (bool, False, bool, False):
        raise OperationContractError("quality-pass rebuild contract is invalid")
    parent = wire.parse_parent(document["expectedParent"])
    try:
        quality_pass = parse_quality_pass_input(document["qualityPass"])
    except RuntimeError as exc:
        raise OperationContractError("nested quality-pass request is invalid") from exc
    if not same_typed_value(parent, quality_pass.repair.expected_parent):
        raise OperationContractError("quality-pass expected parent is stale")
    return QualityPassOperationV1(
        unit_id,
        policy_id,
        parent,
        quality_pass,
        False,
        False,
        "none",
        raw,
        _operation_digest(raw),
    )


def parse_headless_mp4_operation_v1(raw: object) -> HeadlessMp4OperationV1:
    """Parse one exact operation without cross-operation fallback or inference."""
    document = canonical_document(raw, "headless MP4 operation")
    operation = document.get("operation")
    if operation == "initialize":
        return _parse_initialize(document, raw)
    if operation == "quality-pass":
        return _parse_quality_pass(document, raw)
    raise OperationContractError("headless MP4 operation is unsupported")


def validate_headless_mp4_operation_v1(value: object) -> None:
    """Reject direct construction or mutation outside canonical operation bytes."""
    if type(value) not in {InitializeOperationV1, QualityPassOperationV1}:
        raise OperationContractError("headless MP4 operation instance is invalid")
    if type(value.document_json) is not bytes:
        raise OperationContractError("headless MP4 operation bytes are invalid")
    parsed = parse_headless_mp4_operation_v1(value.document_json)
    if not same_typed_value(value, parsed):
        raise OperationContractError("headless MP4 operation identity is invalid")
