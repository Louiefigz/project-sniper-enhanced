"""Self-consistent exact 44-row genesis R1 authority fixture."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from _approved_parent_loader_documents import AuthorityDocuments
from _approved_parent_loader_values import canonical
from _genesis_r1_fixture_build import GenesisFixtureParts, finish_genesis_fixture
from headless.artifact_contract import ArtifactRefV1
from headless.genesis_approved_card import parse_genesis_approved_card_v2
from headless.genesis_authority_types import GenesisAuthorityInputsV2
from headless.genesis_execution_policy import (
    current_initialization_execution_policy_v2,
)
from headless.operation_contract import parse_headless_mp4_operation_v1
from headless.operation_wire import initialization_snapshot_id
from headless.origin_receipt import parse_initialization_origin_receipt_v1


@dataclass(frozen=True)
class GenesisR1Fixture:
    """Parsed inputs plus mutable document builders for adversarial tests."""

    inputs: GenesisAuthorityInputsV2
    files: dict[str, bytes]
    classes: dict[str, str]


def decoded(raw: bytes) -> dict:
    """Return one disposable decoded canonical document."""
    return json.loads(raw)


def changed(raw: bytes, path: tuple, value: object) -> bytes:
    """Change one nested field and restore canonical encoding."""
    document = decoded(raw)
    target = document
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return canonical(document)


def _artifact(path: str, marker: str) -> ArtifactRefV1:
    return ArtifactRefV1(path, marker * 64, 100)


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


def _snapshot_document() -> dict:
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


def _operation(identity: dict, policy_id: str) -> tuple[dict, object]:
    document = {
        "schemaVersion": 1,
        "operation": "initialize",
        "realizationKind": "deterministic-mp4",
        "unitId": identity["unitId"],
        "expectedParent": None,
        "executionPolicyId": policy_id,
        "initialBaseBuild": "from-presealed-snapshot",
        "writerRebuildAllowed": False,
        "fallbackPolicy": "none",
        "initializationSnapshot": _snapshot_document(),
    }
    return document, parse_headless_mp4_operation_v1(canonical(document))


def _remove_r0_authorities(files: dict[str, bytes], classes: dict[str, str]) -> None:
    removed = {
        "approved-parent-v1",
        "generation-verification-v1",
        "execution-policy-v1",
        "assembly-receipt-v1",
    }
    paths = tuple(path for path, name in classes.items() if name in removed)
    for path in paths:
        del files[path]
        del classes[path]


def _origin_document(
    descriptor: dict, operation_bundle: tuple, build_refs: tuple[dict, dict]
) -> dict:
    operation, operation_raw, snapshot_raw = operation_bundle
    render_build, compositor_build = build_refs
    output = descriptor["output"]
    policies = descriptor["policies"]
    return {
        "schemaVersion": 1,
        "status": "complete-private-initialization-origin",
        "realizationKind": "deterministic-mp4",
        "expectedParent": None,
        "identity": descriptor["identity"],
        "policies": {
            "initializationExecutionPolicyId": operation.execution_policy_id,
            "repairPolicyId": policies["repairPolicyId"],
            "qualityPolicyId": policies["qualityPolicyId"],
            "fallbackPolicyId": policies["fallbackPolicyId"],
        },
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
            "renderBuildReceipt": render_build,
            "compositorBuildReceipt": compositor_build,
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


def _card_document(descriptor: dict, origin: object, policy_ref: dict) -> dict:
    provenance = dict(descriptor["provenance"])
    provenance["executionPolicy"] = policy_ref
    policies = dict(descriptor["policies"])
    policies["executionPolicyId"] = origin.policies.initialization_execution_policy_id
    output = descriptor["output"]
    return {
        "schemaVersion": 2,
        "status": "approved-private-genesis-generation",
        "realizationKind": "deterministic-mp4",
        "expectedParent": None,
        "identity": descriptor["identity"],
        "policies": policies,
        "provenance": provenance,
        "origin": {
            "receipt": _raw_ref(
                "origin/initialization-origin.json", origin.document_json
            ),
            "operation": _artifact_document(origin.operation.artifact),
            "operationDigest": origin.operation.digest,
            "snapshotAuthority": _artifact_document(
                origin.operation.snapshot_authority
            ),
            "snapshotId": origin.operation.snapshot_id,
        },
        "plan": descriptor["plan"],
        "base": descriptor["base"],
        "graphics": descriptor["graphics"],
        "output": {
            "final": output["final"],
            "cover": output["cover"],
            "coverProof": output["coverProof"],
            "proxyDisposition": output["proxyDisposition"],
        },
        "quality": descriptor["quality"],
    }


def genesis_r1_fixture() -> GenesisR1Fixture:
    """Build the exact disjoint R1 authority graph without touching R0 fixtures."""
    r0 = AuthorityDocuments()
    files, classes = dict(r0.files), dict(r0.classes)
    descriptor = decoded(r0.files[r0.commit.approved_parent_path])
    _remove_r0_authorities(files, classes)
    policy = current_initialization_execution_policy_v2()
    operation_document, operation = _operation(descriptor["identity"], policy.policy_id)
    operation_raw = operation.document_json
    snapshot_raw = canonical(operation_document["initializationSnapshot"])
    build_refs = (
        r0.ref("render-build-receipt-v1"),
        r0.ref("compositor-build-receipt-v1"),
    )
    origin_raw = canonical(
        _origin_document(
            descriptor,
            (operation, operation_raw, snapshot_raw),
            build_refs,
        )
    )
    origin = parse_initialization_origin_receipt_v1(origin_raw)
    policy_path = "policies/initialization-execution-policy-v2.json"
    policy_ref = _raw_ref(policy_path, policy.document_json)
    card_raw = canonical(_card_document(descriptor, origin, policy_ref))
    card = parse_genesis_approved_card_v2(card_raw)
    parts = GenesisFixtureParts(
        files, classes, card, origin, operation, policy, snapshot_raw
    )
    inputs = finish_genesis_fixture(parts)
    return GenesisR1Fixture(inputs, files, classes)
