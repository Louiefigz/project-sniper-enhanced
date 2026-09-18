"""Canonical quality-chain payloads for the approved-parent disk fixture."""

from __future__ import annotations

from typing import Protocol

from _approved_parent_loader_evidence import set_evidence_payloads
from _approved_parent_loader_values import (
    ATTEMPT,
    AUTHORITY,
    GENERATION,
    QUALITY,
    REQUEST,
    UNIT,
    artifact_path,
    canonical,
)
from headless.repair_intent import approved_plan_digest


class QualityFixtureBuilder(Protocol):
    """Small surface needed to stage quality records into a fixture."""

    scenario: str
    plan: dict
    files: dict[str, bytes]

    def ref(self, artifact_class: str, ordinal: int = 0) -> dict:
        """Return the current reference for one staged artifact."""


def _cover(builder: QualityFixtureBuilder) -> dict:
    source = builder.ref("final-media-v1")["sha256"]
    if builder.scenario == "quality-cover-binding":
        source = "0" * 64
    return {
        "schemaVersion": 1,
        "sourceFinalSha256": source,
        "frameIndex": 0,
        "method": "ffmpeg-select-frame-zero-png",
        "cover": builder.ref("cover-image-v1"),
    }


def _qc(builder: QualityFixtureBuilder) -> dict:
    plan_digest = approved_plan_digest(builder.plan)
    if builder.scenario == "quality-qc-binding":
        plan_digest = "0" * 64
    return {
        "schemaVersion": 1,
        "verdict": "pass",
        "planDigest": plan_digest,
        "finalSha256": builder.ref("final-media-v1")["sha256"],
        "assemblyReceiptSha256": builder.ref("assembly-receipt-v1")["sha256"],
        "qualityPolicyId": QUALITY,
        "audit": builder.ref("audit-b-receipt-v1"),
        "fullDecode": builder.ref("full-decode-proof-v1"),
        "effectProof": builder.ref("effect-proof-v1"),
    }


def _critic(builder: QualityFixtureBuilder, lens: str) -> dict:
    evidence = builder.ref("qc-receipt-v1")["sha256"]
    if builder.scenario == "quality-critic-binding" and lens == "composition":
        evidence = "0" * 64
    return {
        "schemaVersion": 1,
        "verdict": "pass",
        "lens": lens,
        "candidateSha256": builder.ref("final-media-v1")["sha256"],
        "evidenceDigest": evidence,
    }


def _final(builder: QualityFixtureBuilder) -> dict:
    request = "0" * 64 if builder.scenario == "quality-final-binding" else REQUEST
    document = {
        "schemaVersion": 3,
        "verdict": "pass",
        "candidateDisposition": "private-counterfactual",
        "authorityId": AUTHORITY,
        "generationId": GENERATION,
        "attemptId": ATTEMPT,
        "unitId": UNIT,
        "requestDigest": request,
        "planDigest": approved_plan_digest(builder.plan),
        "finalSha256": builder.ref("final-media-v1")["sha256"],
        "assemblyReceiptSha256": builder.ref("assembly-receipt-v1")["sha256"],
        "qcReceipt": builder.ref("qc-receipt-v1"),
        "critics": [
            {"lens": "composition", "artifact": builder.ref("critic-receipt-v1")},
            {
                "lens": "editorial",
                "artifact": builder.ref("critic-receipt-v1", 1),
            },
        ],
        "qualityPolicyId": QUALITY,
        "fallbackPolicy": "none",
        "publicationClaim": False,
    }
    if builder.scenario == "quality-final-schema":
        document["unexpected"] = True
    return document


def set_quality_payloads(
    builder: QualityFixtureBuilder, stage_evidence: bool = True
) -> None:
    """Stage receipts in dependency order without a digest cycle."""
    if stage_evidence:
        set_evidence_payloads(builder)
    builder.files[artifact_path("cover-proof-v1")] = canonical(_cover(builder))
    builder.files[artifact_path("qc-receipt-v1")] = canonical(_qc(builder))
    for ordinal, lens in enumerate(("composition", "editorial")):
        path = artifact_path("critic-receipt-v1", ordinal)
        builder.files[path] = canonical(_critic(builder, lens))
    builder.files[artifact_path("final-approval-v3")] = canonical(_final(builder))
