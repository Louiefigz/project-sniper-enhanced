"""Self-consistent exact R0 quality-evidence generation fixture."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from _approved_parent_loader_documents import AuthorityDocuments
from _approved_parent_loader_quality import set_quality_payloads
from _approved_parent_loader_values import (
    QUALITY,
    REPAIR,
    REQUEST,
    artifact_path,
    canonical,
)
from headless.approved_parent_quality_evidence import (
    parse_approved_parent_quality_evidence_v1,
    quality_evidence_set_digest,
)
from headless.approved_parent_quality_evidence_binding import (
    ApprovedParentQualityEvidenceBindingV1,
)
from headless.approved_parent_quality_receipts import parse_qc_receipt_v1
from headless.approved_parent_schema import parse_approved_parent_descriptor
from headless.artifact_contract import ArtifactRefV1
from headless.generation_schema import parse_generation_commit
from headless.repair_intent import approved_plan_digest

DocumentMutator = Callable[[str, dict], None]


@dataclass(frozen=True)
class QualityEvidenceFixture:
    binding: ApprovedParentQualityEvidenceBindingV1
    documents: AuthorityDocuments


def _full_decode(builder: AuthorityDocuments) -> dict:
    return {
        "schemaVersion": 1,
        "verdict": "pass",
        "method": "ffmpeg-xerror-full-av-v1",
        "plan": builder.ref("plan-v1"),
        "approvedPlanDigest": approved_plan_digest(builder.plan),
        "final": builder.ref("final-media-v1"),
        "assemblyReceipt": builder.ref("assembly-receipt-v1"),
        "qualityPolicyId": QUALITY,
        "runtimeCapabilityManifest": builder.ref("runtime-capability-manifest-v1"),
        "tools": {"ffmpegSha256": "a" * 64, "ffprobeSha256": "b" * 64},
        "execution": {
            "errorPolicy": "xerror",
            "exitCode": 0,
            "videoSink": "null",
            "audioSink": "null",
        },
        "streams": {
            "expectedVideo": 1,
            "decodedVideo": 1,
            "expectedAudio": 1,
            "decodedAudio": 1,
        },
        "video": {
            "expectedFrames": 120,
            "decodedFrames": 120,
            "expectedPackets": 120,
            "decodedPackets": 120,
        },
        "audio": {
            "channels": 2,
            "sampleRateHz": 48_000,
            "expectedSamplesPerChannel": 192_000,
            "decodedSamplesPerChannel": 192_000,
            "expectedPackets": 188,
            "decodedPackets": 188,
        },
    }


def _effect_color(builder: AuthorityDocuments) -> dict:
    asset = builder._graphic(
        builder.plan["graphicsTrack"][0],
        builder._media("graphic-media-v1", True),
        builder.ref("graphic-render-receipt-v1"),
    )
    return {
        "target": {
            "graphicId": "g-00000001",
            "relativePointer": "/spec/accent",
            "requestedValue": "#054BC9",
            "brandPolicyId": REPAIR,
            "brandMembership": "pass",
        },
        "preEncode": {
            "graphicMedia": builder.ref("graphic-media-v1"),
            "renderIntentDigest": asset["renderIntentDigest"],
            "rasterRgb": [5, 75, 201],
            "matchingPixels": 240,
            "method": "lossless-overlay-token-raster-v1",
        },
        "decodedColor": {
            "requestedRgb": [5, 75, 201],
            "observedRgb": [6, 75, 199],
            "maximumDeltaEMilli": 5_000,
            "observedDeltaEMilli": 2_236,
            "sampledFrames": 75,
            "matchingFrames": 75,
            "method": "calibrated-rgb-euclidean-milli-v1",
        },
    }


def _effect_window() -> dict:
    return {
        "timing": {
            "outStart": 1.0,
            "outEnd": 3.5,
            "expectedFirstFrame": 30,
            "expectedLastFrame": 104,
            "observedFirstFrame": 30,
            "observedLastFrame": 104,
            "boundaryToleranceFrames": 1,
            "sampledFrames": 75,
        },
        "placement": {
            "anchor": "free-band",
            "expectedX": 50,
            "expectedY": 100,
            "observedX": 50,
            "observedY": 100,
            "maxOriginErrorPixels": 1,
            "deliveryWidth": 1080,
            "deliveryHeight": 1920,
            "graphicWidth": 240,
            "graphicHeight": 120,
            "method": "decoded-overlay-origin-v1",
        },
    }


def _effect_safety() -> dict:
    return {
        "contrast": {
            "requiredMinimumMilliRatio": 3_000,
            "observedMinimumMilliRatio": 4_500,
            "sampledFrames": 75,
            "passingFrames": 75,
            "method": "decoded-moving-window-wcag-v1",
        },
        "protectedRegions": {
            "regionKinds": ["caption", "title"],
            "sampledFrames": 75,
            "collisionFrames": 0,
            "maximumOverlapPixels": 0,
            "method": "decoded-region-intersection-v1",
        },
        "locality": {
            "preencodeChangedPixels": 240,
            "preencodeOutsideRoiChangedPixels": 0,
            "decodedOutsideRoiMaterialPixels": 0,
            "materialityThresholdMilli": 3_000,
            "observedMaxOutsideRoiDeltaMilli": 500,
            "method": "lossless-locality-calibrated-codec-spill-v1",
        },
    }


def _effect(builder: AuthorityDocuments) -> dict:
    return {
        "schemaVersion": 1,
        "verdict": "pass",
        "effectClass": "SECTION_MARKER_ACCENT_V1",
        "requestDigest": REQUEST,
        "plan": builder.ref("plan-v1"),
        "approvedPlanDigest": approved_plan_digest(builder.plan),
        "final": builder.ref("final-media-v1"),
        "assemblyReceipt": builder.ref("assembly-receipt-v1"),
        "qualityPolicyId": QUALITY,
        "runtimeCapabilityManifest": builder.ref("runtime-capability-manifest-v1"),
        **_effect_color(builder),
        **_effect_window(),
        **_effect_safety(),
    }


def _ref(value: dict) -> ArtifactRefV1:
    return ArtifactRefV1(value["path"], value["sha256"], value["sizeBytes"])


def _audit(builder: AuthorityDocuments) -> dict:
    full_decode = _ref(builder.ref("full-decode-proof-v1"))
    effect_proof = _ref(builder.ref("effect-proof-v1"))
    domains = [
        {
            "name": name,
            "verdict": "pass",
            "checkCount": 1,
            "warningCount": 0,
        }
        for name in (
            "audio",
            "composite-visual",
            "cover",
            "format-duration-budget",
            "frames-safe-zone",
            "glitch",
            "motion",
            "placement",
        )
    ]
    return {
        "schemaVersion": 1,
        "verdict": "pass",
        "auditProfile": "B",
        "terminalStage": "after-full-decode-and-effect-proof",
        "plan": builder.ref("plan-v1"),
        "approvedPlanDigest": approved_plan_digest(builder.plan),
        "final": builder.ref("final-media-v1"),
        "assemblyReceipt": builder.ref("assembly-receipt-v1"),
        "qualityPolicyId": QUALITY,
        "runtimeCapabilityManifest": builder.ref("runtime-capability-manifest-v1"),
        "evidence": {
            "fullDecode": builder.ref("full-decode-proof-v1"),
            "effectProof": builder.ref("effect-proof-v1"),
            "evidenceSetDigest": quality_evidence_set_digest(full_decode, effect_proof),
        },
        "domains": domains,
        "summary": {"checkCount": 8, "passed": 8, "warnings": 0, "failed": 0},
    }


def _restage(builder: AuthorityDocuments, mutator: DocumentMutator | None) -> None:
    full_decode = _full_decode(builder)
    if mutator is not None:
        mutator("full-decode", full_decode)
    builder.files[artifact_path("full-decode-proof-v1")] = canonical(full_decode)
    effect = _effect(builder)
    if mutator is not None:
        mutator("effect-proof", effect)
    builder.files[artifact_path("effect-proof-v1")] = canonical(effect)
    audit = _audit(builder)
    if mutator is not None:
        mutator("audit-b", audit)
    builder.files[artifact_path("audit-b-receipt-v1")] = canonical(audit)
    set_quality_payloads(builder, stage_evidence=False)
    builder._set_descriptor()
    provisional = parse_generation_commit(builder.commit_document())
    builder._set_verification(provisional)
    builder.commit_raw = canonical(builder.commit_document())
    builder.commit = parse_generation_commit(builder.commit_raw)


def quality_evidence_fixture(
    mutator: DocumentMutator | None = None,
) -> QualityEvidenceFixture:
    """Build one exact 42-row generation with canonical evidence wires."""
    documents = AuthorityDocuments()
    _restage(documents, mutator)
    descriptor_raw = documents.files[artifact_path("approved-parent-v1")]
    descriptor = parse_approved_parent_descriptor(descriptor_raw)
    qc_raw = documents.files[artifact_path("qc-receipt-v1")]
    evidence = parse_approved_parent_quality_evidence_v1(
        documents.files[artifact_path("full-decode-proof-v1")],
        documents.files[artifact_path("effect-proof-v1")],
        documents.files[artifact_path("audit-b-receipt-v1")],
    )
    binding = ApprovedParentQualityEvidenceBindingV1(
        descriptor,
        documents.commit,
        parse_qc_receipt_v1(qc_raw),
        documents.files[artifact_path("plan-v1")],
        evidence,
    )
    return QualityEvidenceFixture(binding, documents)
