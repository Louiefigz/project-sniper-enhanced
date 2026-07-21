"""Commit and verification assembly for the isolated genesis R1 fixture."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from _approved_parent_loader_values import canonical
from headless.generation_schema import parse_generation_commit
from headless.genesis_authority_types import GenesisAuthorityInputsV2
from headless.genesis_generation_verification import (
    genesis_payload_manifest_digest,
    parse_genesis_generation_verification_v2,
)


@dataclass(frozen=True)
class GenesisFixtureParts:
    """Pre-verification authority graph and its mutable manifest payloads."""

    files: dict[str, bytes]
    classes: dict[str, str]
    card: object
    origin: object
    operation: object
    policy: object
    snapshot_raw: bytes


def _raw_ref(path: str, raw: bytes) -> dict:
    return {
        "path": path,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "sizeBytes": len(raw),
    }


def _commit_document(parts: GenesisFixtureParts) -> dict:
    identity = parts.card.identity
    policies = parts.card.policies
    rows = [
        {
            "artifactClass": parts.classes[path],
            "path": path,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "sizeBytes": len(raw),
        }
        for path, raw in sorted(parts.files.items())
    ]
    return {
        "schemaVersion": 1,
        "authorityId": identity.authority_id,
        "generationId": identity.generation_id,
        "attemptId": identity.attempt_id,
        "unitId": identity.unit_id,
        "requestDigest": identity.request_digest,
        "expectedParent": None,
        "executionPolicyId": policies.execution_policy_id,
        "repairPolicyId": policies.repair_policy_id,
        "qualityPolicyId": policies.quality_policy_id,
        "fallbackPolicyId": policies.fallback_policy_id,
        "approvedParentPath": "authority/genesis-approved-card-v2.json",
        "files": rows,
    }


def _verification_document(commit: object, parts: GenesisFixtureParts) -> dict:
    payload = tuple(
        row
        for row in commit.files
        if row.artifact_class != "generation-verification-v2"
    )
    card_document = json.loads(parts.card.document_json)
    return {
        "schemaVersion": 2,
        "status": "structural-pass-runtime-unverified",
        "profile": "deterministic-mp4-genesis-r1-v2",
        "expectedParent": None,
        "identity": card_document["identity"],
        "policies": card_document["policies"],
        "approvedCard": _raw_ref(
            "authority/genesis-approved-card-v2.json", parts.card.document_json
        ),
        "origin": card_document["origin"],
        "payloadManifestDigest": genesis_payload_manifest_digest(payload),
    }


def _add_authorities(parts: GenesisFixtureParts) -> None:
    additions = {
        "origin/headless-operation.json": (
            "headless-operation-v1",
            parts.operation.document_json,
        ),
        "origin/initialization-snapshot.json": (
            "initialization-snapshot-authority-v1",
            parts.snapshot_raw,
        ),
        "origin/initialization-origin.json": (
            "initialization-origin-receipt-v1",
            parts.origin.document_json,
        ),
        "policies/initialization-execution-policy-v2.json": (
            "initialization-execution-policy-v2",
            parts.policy.document_json,
        ),
        "authority/genesis-approved-card-v2.json": (
            "genesis-approved-card-v2",
            parts.card.document_json,
        ),
        "authority/generation-verification-v2.json": (
            "generation-verification-v2",
            b"provisional",
        ),
    }
    for path, (artifact_class, raw) in additions.items():
        parts.files[path], parts.classes[path] = raw, artifact_class


def finish_genesis_fixture(parts: GenesisFixtureParts) -> GenesisAuthorityInputsV2:
    """Add R1 authorities, close verification, and parse the final commit."""
    _add_authorities(parts)
    provisional = parse_generation_commit(_commit_document(parts))
    verification_raw = canonical(_verification_document(provisional, parts))
    parts.files["authority/generation-verification-v2.json"] = verification_raw
    commit = parse_generation_commit(canonical(_commit_document(parts)))
    verification = parse_genesis_generation_verification_v2(verification_raw)
    return GenesisAuthorityInputsV2(
        commit,
        parts.card,
        parts.origin,
        parts.operation,
        parts.policy,
        verification,
        parts.snapshot_raw,
        dict(parts.files),
    )
