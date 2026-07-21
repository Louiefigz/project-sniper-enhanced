"""Exact semantic wire records for the approved-parent quality chain."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from . import quality_receipt_json as wire

ArtifactRefV1 = wire.ArtifactRefV1
QualityReceiptSchemaError = wire.QualityReceiptSchemaError

_COVER_KEYS = frozenset(
    "cover frameIndex method schemaVersion sourceFinalSha256".split()
)
_QC_KEYS = frozenset(
    "assemblyReceiptSha256 audit effectProof finalSha256 fullDecode "
    "planDigest qualityPolicyId schemaVersion verdict".split()
)
_CRITIC_KEYS = frozenset(
    "candidateSha256 evidenceDigest lens schemaVersion verdict".split()
)
_FINAL_KEYS = frozenset(
    "assemblyReceiptSha256 attemptId authorityId candidateDisposition critics "
    "fallbackPolicy finalSha256 generationId planDigest publicationClaim "
    "qcReceipt qualityPolicyId requestDigest schemaVersion unitId verdict".split()
)
_FINAL_CRITIC_KEYS = frozenset("artifact lens".split())
_LENSES = ("composition", "editorial")


@dataclass(frozen=True)
class CoverProofV1:
    """Frame-zero PNG proof emitted by the prebound compositor."""

    source_final_sha256: str
    cover: ArtifactRefV1
    document_json: bytes


@dataclass(frozen=True)
class QcReceiptWireV1:
    """Passing deterministic QC closure for one candidate."""

    plan_digest: str
    final_sha256: str
    assembly_receipt_sha256: str
    quality_policy_id: str
    audit: ArtifactRefV1
    full_decode: ArtifactRefV1
    effect_proof: ArtifactRefV1
    document_json: bytes


@dataclass(frozen=True)
class CriticReceiptWireV1:
    """Passing rendered-lens receipt bound to immutable QC evidence."""

    lens: str
    candidate_sha256: str
    evidence_digest: str
    document_json: bytes


@dataclass(frozen=True)
class FinalCriticRefV1:
    """One ordered rendered-critic artifact referenced by final approval."""

    lens: str
    artifact: ArtifactRefV1


@dataclass(frozen=True)
class FinalApprovalV3:
    """Acyclic approval of one private, never-published counterfactual."""

    authority_id: str
    generation_id: str
    attempt_id: str
    unit_id: str
    request_digest: str
    plan_digest: str
    final_sha256: str
    assembly_receipt_sha256: str
    qc_receipt: ArtifactRefV1
    critics: tuple[FinalCriticRefV1, ...]
    quality_policy_id: str
    document_json: bytes


@dataclass(frozen=True)
class ApprovedParentQualityRecordsV1:
    """All canonical records needed to validate the private quality chain."""

    cover_proof: CoverProofV1
    qc_receipt: QcReceiptWireV1
    critics: tuple[CriticReceiptWireV1, ...]
    final_approval: FinalApprovalV3


def _envelope(document: dict, keys: frozenset[str], version: int, label: str) -> None:
    row = wire.exact(document, keys, label)
    valid = type(row.get("schemaVersion")) is int and row["schemaVersion"] == version
    if not valid:
        raise QualityReceiptSchemaError(f"{label} schema version is invalid")


def parse_cover_proof_v1(raw: object) -> CoverProofV1:
    """Parse the exact frame-zero proof produced by ``make_cover``."""
    document = wire.canonical_document(raw, "cover proof")
    _envelope(document, _COVER_KEYS, 1, "cover proof")
    valid = (
        type(document["frameIndex"]),
        document["frameIndex"],
        document["method"],
    ) == (
        int,
        0,
        "ffmpeg-select-frame-zero-png",
    )
    if not valid:
        raise QualityReceiptSchemaError("cover proof method is invalid")
    return CoverProofV1(
        wire.digest(document["sourceFinalSha256"], "cover source digest"),
        wire.artifact(document["cover"]),
        raw,
    )


def parse_qc_receipt_v1(raw: object) -> QcReceiptWireV1:
    """Parse exact passing Audit-B/full-decode/effect evidence."""
    document = wire.canonical_document(raw, "QC receipt")
    _envelope(document, _QC_KEYS, 1, "QC receipt")
    if document["verdict"] != "pass":
        raise QualityReceiptSchemaError("QC receipt verdict is invalid")
    evidence = (
        wire.artifact(document["audit"]),
        wire.artifact(document["fullDecode"]),
        wire.artifact(document["effectProof"]),
    )
    if len({item.relative_path for item in evidence}) != len(evidence):
        raise QualityReceiptSchemaError("QC evidence artifact paths alias")
    if len({item.sha256 for item in evidence}) != len(evidence):
        raise QualityReceiptSchemaError("QC evidence artifact bytes alias")
    return QcReceiptWireV1(
        wire.digest(document["planDigest"], "QC plan digest"),
        wire.digest(document["finalSha256"], "QC final digest"),
        wire.digest(document["assemblyReceiptSha256"], "QC assembly digest"),
        wire.digest(document["qualityPolicyId"], "QC quality policy ID"),
        evidence[0],
        evidence[1],
        evidence[2],
        raw,
    )


def parse_critic_receipt_v1(raw: object) -> CriticReceiptWireV1:
    """Parse one exact passing composition or editorial critic receipt."""
    document = wire.canonical_document(raw, "critic receipt")
    _envelope(document, _CRITIC_KEYS, 1, "critic receipt")
    valid = document["lens"] in _LENSES and document["verdict"] == "pass"
    if not valid:
        raise QualityReceiptSchemaError("critic receipt verdict or lens is invalid")
    return CriticReceiptWireV1(
        document["lens"],
        wire.digest(document["candidateSha256"], "critic candidate digest"),
        wire.digest(document["evidenceDigest"], "critic evidence digest"),
        raw,
    )


def _final_critics(value: object) -> tuple[FinalCriticRefV1, ...]:
    if type(value) is not list or len(value) != 2:
        raise QualityReceiptSchemaError("final approval needs two critic refs")
    rows = tuple(
        wire.exact(item, _FINAL_CRITIC_KEYS, "final critic reference") for item in value
    )
    critics = tuple(
        FinalCriticRefV1(row["lens"], wire.artifact(row["artifact"])) for row in rows
    )
    if tuple(item.lens for item in critics) != _LENSES:
        raise QualityReceiptSchemaError("final critic reference order is invalid")
    if critics[0].artifact.relative_path == critics[1].artifact.relative_path:
        raise QualityReceiptSchemaError("final critic artifact paths alias")
    return critics


def _validate_final_constants(document: dict) -> None:
    actual = (
        document["verdict"],
        document["candidateDisposition"],
        document["fallbackPolicy"],
        type(document["publicationClaim"]),
        document["publicationClaim"],
    )
    expected = (
        "pass",
        "private-counterfactual",
        "none",
        bool,
        False,
    )
    if actual != expected:
        raise QualityReceiptSchemaError("final approval disposition is invalid")


def parse_final_approval_v3(raw: object) -> FinalApprovalV3:
    """Parse the exact acyclic private-counterfactual final approval."""
    document = wire.canonical_document(raw, "final approval")
    _envelope(document, _FINAL_KEYS, 3, "final approval")
    _validate_final_constants(document)
    return FinalApprovalV3(
        wire.authority(document["authorityId"]),
        wire.canonical_uuid(document["generationId"], "generation ID"),
        wire.canonical_uuid(document["attemptId"], "attempt ID"),
        wire.canonical_uuid(document["unitId"], "unit ID"),
        wire.digest(document["requestDigest"], "request digest"),
        wire.digest(document["planDigest"], "approval plan digest"),
        wire.digest(document["finalSha256"], "approval final digest"),
        wire.digest(document["assemblyReceiptSha256"], "approval assembly digest"),
        wire.artifact(document["qcReceipt"]),
        _final_critics(document["critics"]),
        wire.digest(document["qualityPolicyId"], "approval quality policy ID"),
        raw,
    )


def _validate_instance(
    value: object,
    expected: type,
    parser: Callable[[object], object],
    label: str,
) -> None:
    if type(value) is not expected or type(value.document_json) is not bytes:
        raise QualityReceiptSchemaError(f"{label} instance is invalid")
    if not wire.same_typed_value(value, parser(value.document_json)):
        raise QualityReceiptSchemaError(f"{label} direct construction is invalid")


def validate_cover_proof_v1(value: object) -> None:
    _validate_instance(value, CoverProofV1, parse_cover_proof_v1, "cover proof")


def validate_qc_receipt_v1(value: object) -> None:
    _validate_instance(value, QcReceiptWireV1, parse_qc_receipt_v1, "QC receipt")


def validate_critic_receipt_v1(value: object) -> None:
    _validate_instance(value, CriticReceiptWireV1, parse_critic_receipt_v1, "critic")


def validate_final_approval_v3(value: object) -> None:
    _validate_instance(value, FinalApprovalV3, parse_final_approval_v3, "approval")
