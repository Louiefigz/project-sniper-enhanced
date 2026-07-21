"""Canonical quality-chain fixtures with self-consistent byte references."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from _approved_parent_schema_fixture import _canonical, _descriptor
from headless.approved_parent_quality_receipts import (
    ApprovedParentQualityRecordsV1,
    parse_cover_proof_v1,
    parse_critic_receipt_v1,
    parse_final_approval_v3,
    parse_qc_receipt_v1,
)
from headless.approved_parent_schema import parse_approved_parent_descriptor
from headless.generation_profile import R0_GENERATION_ARTIFACT_CLASS_COUNTS
from headless.generation_schema import parse_generation_commit


@dataclass(frozen=True)
class QualityChainFixture:
    descriptor: object
    commit: object
    records: ApprovedParentQualityRecordsV1


def _ref(path: str, raw: bytes) -> dict:
    return {
        "path": path,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "sizeBytes": len(raw),
    }


def _cover_document(descriptor: dict) -> dict:
    return {
        "schemaVersion": 1,
        "frameIndex": 0,
        "method": "ffmpeg-select-frame-zero-png",
        "sourceFinalSha256": descriptor["output"]["final"]["artifact"]["sha256"],
        "cover": descriptor["output"]["cover"],
    }


def _qc_document(descriptor: dict) -> dict:
    return {
        "schemaVersion": 1,
        "verdict": "pass",
        "planDigest": descriptor["plan"]["approvedPlanDigest"],
        "finalSha256": descriptor["output"]["final"]["artifact"]["sha256"],
        "assemblyReceiptSha256": descriptor["output"]["assemblyReceipt"]["sha256"],
        "qualityPolicyId": descriptor["policies"]["qualityPolicyId"],
        "audit": descriptor["quality"]["audit"],
        "fullDecode": descriptor["quality"]["fullDecode"],
        "effectProof": descriptor["quality"]["effectProof"],
    }


def _critic_document(lens: str, descriptor: dict, qc_ref: dict) -> dict:
    return {
        "schemaVersion": 1,
        "lens": lens,
        "verdict": "pass",
        "candidateSha256": descriptor["output"]["final"]["artifact"]["sha256"],
        "evidenceDigest": qc_ref["sha256"],
    }


def _approval_document(descriptor: dict) -> dict:
    identity = descriptor["identity"]
    return {
        "schemaVersion": 3,
        "verdict": "pass",
        "candidateDisposition": "private-counterfactual",
        "authorityId": identity["authorityId"],
        "generationId": identity["generationId"],
        "attemptId": identity["attemptId"],
        "unitId": identity["unitId"],
        "requestDigest": identity["requestDigest"],
        "planDigest": descriptor["plan"]["approvedPlanDigest"],
        "finalSha256": descriptor["output"]["final"]["artifact"]["sha256"],
        "assemblyReceiptSha256": descriptor["output"]["assemblyReceipt"]["sha256"],
        "qcReceipt": descriptor["quality"]["qcReceipt"],
        "critics": descriptor["quality"]["critics"],
        "qualityPolicyId": descriptor["policies"]["qualityPolicyId"],
        "fallbackPolicy": "none",
        "publicationClaim": False,
    }


def _change(document: dict, change: tuple[str, object] | None) -> None:
    if change is not None:
        document[change[0]] = change[1]


def _raw_records(
    descriptor: dict,
    cover_change: tuple[str, object] | None,
    qc_change: tuple[str, object] | None,
    critic_change: tuple[str, object] | None,
) -> tuple[bytes, bytes, tuple[bytes, ...]]:
    cover = _cover_document(descriptor)
    _change(cover, cover_change)
    qc = _qc_document(descriptor)
    _change(qc, qc_change)
    cover_raw = _canonical(cover)
    qc_raw = _canonical(qc)
    qc_ref = _ref("quality/qc-receipt.json", qc_raw)
    critics = tuple(
        _critic_document(lens, descriptor, qc_ref)
        for lens in ("composition", "editorial")
    )
    if critic_change is not None:
        critics[0][critic_change[0]] = critic_change[1]
    return cover_raw, qc_raw, tuple(_canonical(item) for item in critics)


def _bind_raw_refs(
    descriptor: dict, cover_raw: bytes, qc_raw: bytes, critic_raw: tuple[bytes, ...]
) -> None:
    descriptor["output"]["coverProof"] = _ref("output/cover-proof.json", cover_raw)
    descriptor["quality"]["qcReceipt"] = _ref("quality/qc-receipt.json", qc_raw)
    for index, raw in enumerate(critic_raw):
        descriptor["quality"]["critics"][index]["artifact"] = _ref(
            f"quality/critic-{index}.json", raw
        )


def _relevant_refs(descriptor: dict, descriptor_raw: bytes) -> dict[str, list[dict]]:
    quality = descriptor["quality"]
    return {
        "approved-parent-v1": [_ref("authority/approved-parent.json", descriptor_raw)],
        "plan-v1": [descriptor["plan"]["artifact"]],
        "final-media-v1": [descriptor["output"]["final"]["artifact"]],
        "assembly-receipt-v1": [descriptor["output"]["assemblyReceipt"]],
        "cover-image-v1": [descriptor["output"]["cover"]],
        "cover-proof-v1": [descriptor["output"]["coverProof"]],
        "audit-b-receipt-v1": [quality["audit"]],
        "full-decode-proof-v1": [quality["fullDecode"]],
        "effect-proof-v1": [quality["effectProof"]],
        "qc-receipt-v1": [quality["qcReceipt"]],
        "critic-receipt-v1": [item["artifact"] for item in quality["critics"]],
        "final-approval-v3": [quality["finalApproval"]],
    }


def _placeholder(artifact_class: str, ordinal: int) -> dict:
    identity = f"{artifact_class}-{ordinal}".encode("ascii")
    return {
        "path": f"manifest/{artifact_class}-{ordinal}.bin",
        "sha256": hashlib.sha256(identity).hexdigest(),
        "sizeBytes": len(identity),
    }


def _manifest(descriptor: dict, descriptor_raw: bytes) -> list[dict]:
    relevant = _relevant_refs(descriptor, descriptor_raw)
    rows = []
    for artifact_class, count in R0_GENERATION_ARTIFACT_CLASS_COUNTS.items():
        refs = relevant.get(artifact_class)
        selected = refs or [
            _placeholder(artifact_class, index) for index in range(count)
        ]
        rows.extend({"artifactClass": artifact_class, **ref} for ref in selected)
    return sorted(rows, key=lambda row: row["path"])


def _commit(descriptor: dict, descriptor_raw: bytes) -> object:
    identity = descriptor["identity"]
    policies = descriptor["policies"]
    document = {
        "schemaVersion": 1,
        "authorityId": identity["authorityId"],
        "generationId": identity["generationId"],
        "attemptId": identity["attemptId"],
        "unitId": identity["unitId"],
        "requestDigest": identity["requestDigest"],
        "expectedParent": None,
        "executionPolicyId": policies["executionPolicyId"],
        "repairPolicyId": policies["repairPolicyId"],
        "qualityPolicyId": policies["qualityPolicyId"],
        "fallbackPolicyId": policies["fallbackPolicyId"],
        "approvedParentPath": "authority/approved-parent.json",
        "files": _manifest(descriptor, descriptor_raw),
    }
    return parse_generation_commit(_canonical(document))


def quality_chain_fixture(
    cover_change: tuple[str, object] | None = None,
    qc_change: tuple[str, object] | None = None,
    critic_change: tuple[str, object] | None = None,
    approval_change: tuple[str, object] | None = None,
) -> QualityChainFixture:
    descriptor = _descriptor()
    descriptor["graphics"]["assets"] = descriptor["graphics"]["assets"][:1]
    cover_raw, qc_raw, critic_raw = _raw_records(
        descriptor, cover_change, qc_change, critic_change
    )
    _bind_raw_refs(descriptor, cover_raw, qc_raw, critic_raw)
    approval = _approval_document(descriptor)
    _change(approval, approval_change)
    approval_raw = _canonical(approval)
    descriptor["quality"]["finalApproval"] = _ref(
        "quality/final-approval.json", approval_raw
    )
    descriptor_raw = _canonical(descriptor)
    records = ApprovedParentQualityRecordsV1(
        parse_cover_proof_v1(cover_raw),
        parse_qc_receipt_v1(qc_raw),
        tuple(parse_critic_receipt_v1(raw) for raw in critic_raw),
        parse_final_approval_v3(approval_raw),
    )
    return QualityChainFixture(
        parse_approved_parent_descriptor(descriptor_raw),
        _commit(descriptor, descriptor_raw),
        records,
    )


def decoded(raw: bytes) -> dict:
    return json.loads(raw)
