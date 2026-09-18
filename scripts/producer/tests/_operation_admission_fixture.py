"""Self-consistent initialize and quality-pass V3 admission fixtures."""

from __future__ import annotations

import json

from headless.artifact_contract import ArtifactRefV1
from headless.generation_policy_documents import current_execution_policy
from headless.genesis_execution_policy import (
    current_initialization_execution_policy_v2,
)
from headless.operation_admission_binding import build_operation_admission_v3
from headless.operation_admission_schema import (
    OperationAdmissionV3,
    request_identity_digest_v3,
)
from headless.operation_admission_types import OperationAdmissionProposalV3
from headless.operation_contract import (
    HeadlessMp4OperationV1,
    parse_headless_mp4_operation_v1,
)
from headless.operation_wire import canonical, initialization_snapshot_id
from headless.quality_policy import current_deterministic_quality_policy
from headless.repair_intent import approved_plan_digest, current_accent_policy

UNIT = "11111111-1111-4111-8111-111111111111"
PARENT_GENERATION = "22222222-2222-4222-8222-222222222222"
REPAIR_REQUEST = "33333333-3333-4333-8333-333333333333"
IDEMPOTENCY = "44444444-4444-4444-8444-444444444444"
ATTEMPT = "55555555-5555-4555-8555-555555555555"
CHILD = "66666666-6666-4666-8666-666666666666"
OTHER = "77777777-7777-4777-8777-777777777777"
AUTHORITY = "authority-mp4-v1"
TIMESTAMP = "2026-07-19T12:34:56Z"


def _artifact(path: str, marker: str) -> ArtifactRefV1:
    return ArtifactRefV1(path, marker * 64, 101)


def _artifact_document(value: ArtifactRefV1) -> dict:
    return {
        "path": value.relative_path,
        "sha256": value.sha256,
        "sizeBytes": value.size_bytes,
    }


def parent_document() -> dict:
    """Return one exact selected approved-parent reference."""
    return {
        "authorityId": AUTHORITY,
        "publicationSeq": 7,
        "generationId": PARENT_GENERATION,
        "commitDigest": "d" * 64,
        "planDigest": approved_plan_digest(
            {"planVersion": 3, "graphicsTrack": []}
        ),
    }


def _snapshot() -> dict:
    archive = _artifact("snapshot/input.tar", "a")
    manifest = _artifact("snapshot/manifest.json", "b")
    receipt = _artifact("snapshot/seal.json", "c")
    return {
        "authorityKind": "presealed-immutable-snapshot-v1",
        "snapshotId": initialization_snapshot_id(archive, manifest, receipt),
        "archive": _artifact_document(archive),
        "manifest": _artifact_document(manifest),
        "sealReceipt": _artifact_document(receipt),
    }


def initialize_operation() -> HeadlessMp4OperationV1:
    """Parse one exact initialization operation."""
    document = {
        "schemaVersion": 1,
        "operation": "initialize",
        "realizationKind": "deterministic-mp4",
        "unitId": UNIT,
        "expectedParent": None,
        "executionPolicyId": current_initialization_execution_policy_v2().policy_id,
        "initialBaseBuild": "from-presealed-snapshot",
        "writerRebuildAllowed": False,
        "fallbackPolicy": "none",
        "initializationSnapshot": _snapshot(),
    }
    return parse_headless_mp4_operation_v1(canonical(document))


def quality_operation(unit_id: str = UNIT) -> HeadlessMp4OperationV1:
    """Parse one exact quality-pass operation."""
    parent = parent_document()
    quality = {
        "schemaVersion": 1,
        "operation": "quality-pass",
        "realizationKind": "deterministic-mp4",
        "fallbackPolicy": "none",
        "repairPolicyId": current_accent_policy().policy_id,
        "qualityPolicyId": current_deterministic_quality_policy().policy_id,
        "repairIntent": {
            "schemaVersion": 1,
            "effectClass": "SECTION_MARKER_ACCENT_V1",
            "realizationKind": "deterministic-mp4",
            "expectedParent": parent,
            "requestId": REPAIR_REQUEST,
            "target": {"lane": "graphicsTrack", "id": "g-00000001"},
            "op": "replace",
            "relativePointer": "/spec/accent",
            "expectedOld": "#054BC9",
            "value": "#FFD400",
        },
    }
    document = {
        "schemaVersion": 1,
        "operation": "quality-pass",
        "realizationKind": "deterministic-mp4",
        "unitId": unit_id,
        "expectedParent": parent,
        "executionPolicyId": current_execution_policy().policy_id,
        "baseRebuildAllowed": False,
        "writerRebuildAllowed": False,
        "fallbackPolicy": "none",
        "qualityPass": quality,
    }
    return parse_headless_mp4_operation_v1(canonical(document))


def proposal(
    operation: HeadlessMp4OperationV1,
) -> OperationAdmissionProposalV3:
    """Return exact controller identities for the operation."""
    return OperationAdmissionProposalV3(
        AUTHORITY,
        IDEMPOTENCY,
        ATTEMPT,
        CHILD,
        operation.unit_id,
        operation.expected_parent,
        TIMESTAMP,
        "release-headless-v3",
        "build-headless-v3",
        operation.execution_policy_id,
    )


def admission(
    operation: HeadlessMp4OperationV1,
    proposed: OperationAdmissionProposalV3 | None = None,
) -> OperationAdmissionV3:
    """Build one exact structural V3 admission."""
    return build_operation_admission_v3(
        operation,
        proposed or proposal(operation),
        "operations/headless-mp4-operation.json",
    )


def decoded(raw: bytes) -> dict:
    """Decode test bytes to a disposable document."""
    return json.loads(raw)


def resigned(document: dict) -> bytes:
    """Recompute request identity after an adversarial document mutation."""
    document = decoded(canonical(document))
    document.pop("requestIdentityDigest", None)
    document["requestIdentityDigest"] = request_identity_digest_v3(document)
    return canonical(document)
