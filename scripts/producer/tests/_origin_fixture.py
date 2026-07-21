"""Self-consistent current-R0 fixture for initialization-origin tests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from _approved_parent_loader_documents import AuthorityDocuments
from _approved_parent_loader_values import artifact_path, canonical
from headless.approved_parent_schema import parse_approved_parent_descriptor
from headless.artifact_contract import ArtifactRefV1
from headless.operation_contract import parse_headless_mp4_operation_v1
from headless.operation_wire import initialization_snapshot_id
from headless.origin_receipt import parse_initialization_origin_receipt_v1


@dataclass(frozen=True)
class OriginFixture:
    descriptor: object
    commit: object
    receipt: object
    operation: object


def decoded(raw: bytes) -> dict:
    """Return a disposable decoded document."""
    return json.loads(raw)


def changed(raw: bytes, path: tuple, value: object) -> bytes:
    """Change one fixture field and restore exact canonical encoding."""
    document = decoded(raw)
    target = document
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return canonical(document)


def _artifact(path: str, marker: str, size: int = 100) -> ArtifactRefV1:
    return ArtifactRefV1(path, marker * 64, size)


def _artifact_document(value: ArtifactRefV1) -> dict:
    return {
        "path": value.relative_path,
        "sha256": value.sha256,
        "sizeBytes": value.size_bytes,
    }


def _raw_ref(path: str, raw: bytes) -> dict:
    return {
        "path": path,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "sizeBytes": len(raw),
    }


def _snapshot() -> dict:
    archive = _artifact("snapshot/input.tar", "a")
    manifest = _artifact("snapshot/manifest.json", "b")
    seal = _artifact("snapshot/seal-receipt.json", "c")
    return {
        "authorityKind": "presealed-immutable-snapshot-v1",
        "snapshotId": initialization_snapshot_id(archive, manifest, seal),
        "archive": _artifact_document(archive),
        "manifest": _artifact_document(manifest),
        "sealReceipt": _artifact_document(seal),
    }


def _operation(descriptor: dict) -> tuple[dict, object]:
    document = {
        "schemaVersion": 1,
        "operation": "initialize",
        "realizationKind": "deterministic-mp4",
        "unitId": descriptor["identity"]["unitId"],
        "expectedParent": None,
        "executionPolicyId": descriptor["policies"]["executionPolicyId"],
        "initialBaseBuild": "from-presealed-snapshot",
        "writerRebuildAllowed": False,
        "fallbackPolicy": "none",
        "initializationSnapshot": _snapshot(),
    }
    return document, parse_headless_mp4_operation_v1(canonical(document))


def _policies(descriptor: dict) -> dict:
    policies = descriptor["policies"]
    return {
        "initializationExecutionPolicyId": policies["executionPolicyId"],
        "repairPolicyId": policies["repairPolicyId"],
        "qualityPolicyId": policies["qualityPolicyId"],
        "fallbackPolicyId": policies["fallbackPolicyId"],
    }


def _origin_document(
    descriptor: dict,
    documents: AuthorityDocuments,
    operation_document: dict,
    operation: object,
) -> dict:
    operation_raw = operation.document_json
    snapshot_raw = canonical(operation_document["initializationSnapshot"])
    output = descriptor["output"]
    return {
        "schemaVersion": 1,
        "status": "complete-private-initialization-origin",
        "realizationKind": "deterministic-mp4",
        "expectedParent": None,
        "identity": descriptor["identity"],
        "policies": _policies(descriptor),
        "operation": {
            "kind": "initialize",
            "artifact": _raw_ref("origin/headless-operation.json", operation_raw),
            "digest": operation.operation_digest,
            "snapshotAuthority": _raw_ref(
                "origin/initialization-snapshot.json", snapshot_raw
            ),
            "snapshotId": operation.snapshot.snapshot_id,
        },
        "plan": descriptor["plan"],
        "base": descriptor["base"],
        "graphics": descriptor["graphics"],
        "buildRuntime": {
            "renderBuildReceipt": documents.ref("render-build-receipt-v1"),
            "compositorBuildReceipt": documents.ref("compositor-build-receipt-v1"),
            "runtimeCapabilityManifest": descriptor["provenance"][
                "runtimeCapabilityManifest"
            ],
        },
        "output": {
            "final": output["final"],
            "cover": output["cover"],
            "coverProof": output["coverProof"],
            "proxyDisposition": output["proxyDisposition"],
        },
        "quality": descriptor["quality"],
    }


def origin_fixture() -> OriginFixture:
    """Build an exact origin receipt beside a fixed profile that cannot carry it."""
    documents = AuthorityDocuments()
    descriptor_raw = documents.files[artifact_path("approved-parent-v1")]
    descriptor_document = decoded(descriptor_raw)
    operation_document, operation = _operation(descriptor_document)
    origin_document = _origin_document(
        descriptor_document, documents, operation_document, operation
    )
    return OriginFixture(
        parse_approved_parent_descriptor(descriptor_raw),
        documents.commit,
        parse_initialization_origin_receipt_v1(canonical(origin_document)),
        operation,
    )
