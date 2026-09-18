"""Manifest and verification assembly for the quality-pass V2 fixture."""

from __future__ import annotations

import dataclasses
import hashlib
import json

from _approved_parent_loader_values import canonical
from headless.artifact_contract import ArtifactRefV1
from headless.generation_schema import parse_generation_commit
from headless.operation_wire import parent_document
from headless.versioned_parent_authority import parent_authority_document
from headless.versioned_quality_pass_verification import (
    quality_pass_payload_manifest_digest,
    parse_quality_pass_generation_verification_v2,
)

_PROVENANCE_CLASSES = (
    "request-identity-v1 execution-policy-v1 admission-inputs-v1 "
    "realization-inputs-v1 generation-inputs-v1 source-snapshot-manifest-v1 "
    "base-fingerprint-v1 operator-intent-v1 cut-approval-v1 asset-closure-v1 "
    "runtime-capability-manifest-v1 repair-state-v1 realization-v1 "
    "template-usage-approval-v1 refit-disposition-v1 proxy-disposition-v1"
).split()


def _decoded(raw: bytes) -> dict:
    return json.loads(raw)


def _artifact_document(ref: ArtifactRefV1) -> dict:
    return {
        "path": ref.relative_path,
        "sha256": ref.sha256,
        "sizeBytes": ref.size_bytes,
    }


def _raw_ref(path: str, raw: bytes) -> dict:
    return {
        "path": path,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "sizeBytes": len(raw),
    }


def _replace_ref(rows: list[dict], artifact_class: str, ref: object) -> None:
    matches = [row for row in rows if row["artifactClass"] == artifact_class]
    refs = ref if type(ref) is tuple else (ref,)
    if len(matches) != len(refs):
        raise AssertionError(f"fixture class cardinality differs: {artifact_class}")
    for row, value in zip(sorted(matches, key=lambda item: item["path"]), refs):
        row.update(_artifact_document(value))


def _card_roles(card: object) -> tuple:
    provenance = tuple(
        zip(
            (
                getattr(card.provenance, field.name)
                for field in dataclasses.fields(card.provenance)
            ),
            _PROVENANCE_CLASSES,
        )
    )
    products = (
        (card.plan.artifact, "plan-v1"),
        (card.base.media.artifact, "base-media-v1"),
        (card.base.plan_artifact, "base-plan-v1"),
        (card.base.receipt, "base-receipt-v1"),
        (card.base.timeline_map, "timeline-map-v1"),
        (card.graphics.prebound_clips, "prebound-clips-v1"),
        (card.output.final.artifact, "final-media-v1"),
        (card.output.cover, "cover-image-v1"),
        (card.output.cover_proof, "cover-proof-v1"),
        (card.quality.audit, "audit-b-receipt-v1"),
        (card.quality.full_decode, "full-decode-proof-v1"),
        (card.quality.effect_proof, "effect-proof-v1"),
        (card.quality.qc_receipt, "qc-receipt-v1"),
        (card.quality.final_approval, "final-approval-v3"),
    )
    graphics = tuple(
        (asset.media.artifact, "graphic-media-v1") for asset in card.graphics.assets
    ) + tuple(
        (asset.receipt, "graphic-render-receipt-v1") for asset in card.graphics.assets
    )
    critics = tuple(
        (critic.artifact, "critic-receipt-v1") for critic in card.quality.critics
    )
    return provenance + products + graphics + critics


def _apply_card_roles(rows: list[dict], card: object) -> None:
    grouped: dict[str, list[ArtifactRefV1]] = {}
    for ref, artifact_class in _card_roles(card):
        grouped.setdefault(artifact_class, []).append(ref)
    for artifact_class, refs in grouped.items():
        _replace_ref(rows, artifact_class, tuple(refs))


def _provisional_document(initial: object, card: object, receipt: object) -> dict:
    document = _decoded(initial.commit.document_json)
    document.update(_decoded(card.document_json)["identity"])
    document["expectedParent"] = parent_document(card.expected_parent)
    replacements = {
        "approved-parent-v1": "quality-pass-approved-card-v2",
        "assembly-receipt-v1": "assembly-receipt-v2",
        "generation-verification-v1": "quality-pass-generation-verification-v2",
    }
    for row in document["files"]:
        row["artifactClass"] = replacements.get(
            row["artifactClass"], row["artifactClass"]
        )
    card_row = next(
        row
        for row in document["files"]
        if row["artifactClass"] == "quality-pass-approved-card-v2"
    )
    card_row.update(_raw_ref(card_row["path"], card.document_json))
    assembly_row = next(
        row
        for row in document["files"]
        if row["artifactClass"] == "assembly-receipt-v2"
    )
    assembly_row.update(_raw_ref(assembly_row["path"], receipt.document_json))
    _apply_card_roles(document["files"], card)
    document["approvedParentPath"] = card_row["path"]
    document["files"] = sorted(document["files"], key=lambda row: row["path"])
    return document


def _verification_document(commit: object, card: object, receipt: object) -> dict:
    payload = tuple(
        row
        for row in commit.files
        if row.artifact_class != "quality-pass-generation-verification-v2"
    )
    card_document = _decoded(card.document_json)
    return {
        "schemaVersion": 2,
        "status": "structural-pass-runtime-unverified",
        "profile": "deterministic-mp4-quality-pass-r1-v2",
        "expectedParent": card_document["expectedParent"],
        "identity": card_document["identity"],
        "policies": card_document["policies"],
        "approvedCard": _raw_ref(commit.approved_parent_path, card.document_json),
        "assemblyReceipt": _artifact_document(card.output.assembly_receipt),
        "parentAuthority": parent_authority_document(receipt.parent_authority),
        "payloadManifestDigest": quality_pass_payload_manifest_digest(payload),
    }


def finish_quality_pass_v2_fixture(
    initial: object, card: object, receipt: object
) -> tuple[object, object]:
    """Close the child commit and exact structural verification V2."""
    document = _provisional_document(initial, card, receipt)
    provisional = parse_generation_commit(canonical(document))
    verification_raw = canonical(_verification_document(provisional, card, receipt))
    verify_row = next(
        row
        for row in document["files"]
        if row["artifactClass"] == "quality-pass-generation-verification-v2"
    )
    verify_row.update(_raw_ref(verify_row["path"], verification_raw))
    document["files"] = sorted(document["files"], key=lambda row: row["path"])
    commit = parse_generation_commit(canonical(document))
    verification = parse_quality_pass_generation_verification_v2(verification_raw)
    return commit, verification
