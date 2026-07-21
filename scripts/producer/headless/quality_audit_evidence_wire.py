"""Exact terminal Audit-B wire downstream of independent quality evidence."""

from __future__ import annotations

import hashlib
import json

from . import quality_receipt_json as wire
from .artifact_contract import ArtifactRefV1
from .quality_evidence_types import AuditBReceiptV1, AuditDomainV1, AuditSummaryV1
from .quality_evidence_wire import (
    QualityEvidenceSchemaError,
    distinct_artifacts,
    integer,
)

_AUDIT_KEYS = frozenset(
    "approvedPlanDigest assemblyReceipt auditProfile domains evidence final plan "
    "qualityPolicyId runtimeCapabilityManifest schemaVersion summary terminalStage "
    "verdict".split()
)
_EVIDENCE_KEYS = frozenset("effectProof evidenceSetDigest fullDecode".split())
_DOMAIN_KEYS = frozenset("checkCount name verdict warningCount".split())
_SUMMARY_KEYS = frozenset("checkCount failed passed warnings".split())
_DOMAIN_NAMES = (
    "audio",
    "composite-visual",
    "cover",
    "format-duration-budget",
    "frames-safe-zone",
    "glitch",
    "motion",
    "placement",
)
_EVIDENCE_DOMAIN = b"sniper-audit-b-independent-evidence-v1\0"


def _artifact_document(value: ArtifactRefV1) -> dict:
    return {
        "path": value.relative_path,
        "sha256": value.sha256,
        "sizeBytes": value.size_bytes,
    }


def quality_evidence_set_digest(
    full_decode: ArtifactRefV1, effect_proof: ArtifactRefV1
) -> str:
    """Hash exact independent evidence refs consumed by terminal Audit-B."""
    document = {
        "effectProof": _artifact_document(effect_proof),
        "fullDecode": _artifact_document(full_decode),
    }
    raw = json.dumps(
        document,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(_EVIDENCE_DOMAIN + raw).hexdigest()


def _domain(value: object) -> AuditDomainV1:
    row = wire.exact(value, _DOMAIN_KEYS, "Audit-B domain")
    check_count = integer(row["checkCount"], "Audit-B domain check count", 1)
    warning_count = integer(row["warningCount"], "Audit-B warning count", 0)
    expected_verdict = "pass-with-warnings" if warning_count else "pass"
    valid = warning_count <= check_count and row["verdict"] == expected_verdict
    if not valid:
        raise QualityEvidenceSchemaError("Audit-B domain result is invalid")
    return AuditDomainV1(
        row["name"], row["verdict"], check_count, warning_count
    )


def _audit_domains(value: object) -> tuple[AuditDomainV1, ...]:
    if type(value) is not list or len(value) != len(_DOMAIN_NAMES):
        raise QualityEvidenceSchemaError("Audit-B domains are incomplete")
    domains = tuple(_domain(row) for row in value)
    if tuple(row.name for row in domains) != _DOMAIN_NAMES:
        raise QualityEvidenceSchemaError("Audit-B domain order is invalid")
    return domains


def _audit_summary(value: object, domains: tuple[AuditDomainV1, ...]) -> AuditSummaryV1:
    row = wire.exact(value, _SUMMARY_KEYS, "Audit-B summary")
    for key in _SUMMARY_KEYS:
        integer(row[key], f"Audit-B {key}", 0)
    summary = AuditSummaryV1(
        row["checkCount"], row["passed"], row["warnings"], row["failed"]
    )
    checks = sum(item.check_count for item in domains)
    warnings = sum(item.warning_count for item in domains)
    valid = summary.failed == 0 and summary.passed > 0
    valid = valid and summary.check_count == checks
    valid = valid and summary.warnings == warnings
    valid = valid and summary.passed + summary.warnings == checks
    if not valid:
        raise QualityEvidenceSchemaError("Audit-B summary is inconsistent")
    return summary


def _envelope(document: dict) -> None:
    row = wire.exact(document, _AUDIT_KEYS, "Audit-B receipt")
    actual = (
        type(row.get("schemaVersion")),
        row.get("schemaVersion"),
        row.get("verdict"),
        row.get("auditProfile"),
        row.get("terminalStage"),
    )
    expected = (
        int,
        1,
        "pass",
        "B",
        "after-full-decode-and-effect-proof",
    )
    if actual != expected:
        raise QualityEvidenceSchemaError("Audit-B terminal envelope is invalid")


def parse_audit_b_receipt_v1(raw: object) -> AuditBReceiptV1:
    """Parse terminal Audit-B bytes with causal independent-evidence refs."""
    document = wire.canonical_document(raw, "Audit-B receipt")
    _envelope(document)
    evidence = wire.exact(document["evidence"], _EVIDENCE_KEYS, "Audit-B evidence")
    full_decode = wire.artifact(evidence["fullDecode"])
    effect_proof = wire.artifact(evidence["effectProof"])
    refs = tuple(
        wire.artifact(document[key])
        for key in ("plan", "final", "assemblyReceipt", "runtimeCapabilityManifest")
    )
    distinct_artifacts(refs + (full_decode, effect_proof), "Audit-B")
    expected_digest = quality_evidence_set_digest(full_decode, effect_proof)
    actual_digest = wire.digest(evidence["evidenceSetDigest"], "evidence set digest")
    if actual_digest != expected_digest:
        raise QualityEvidenceSchemaError("Audit-B evidence set digest is invalid")
    domains = _audit_domains(document["domains"])
    return AuditBReceiptV1(
        refs[0],
        wire.digest(document["approvedPlanDigest"], "audit plan digest"),
        refs[1],
        refs[2],
        wire.digest(document["qualityPolicyId"], "audit quality policy ID"),
        refs[3],
        full_decode,
        effect_proof,
        actual_digest,
        domains,
        _audit_summary(document["summary"], domains),
        raw,
    )
