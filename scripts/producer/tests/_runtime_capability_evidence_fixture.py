"""Canonical quality documents for the runtime-capability fixture."""

from __future__ import annotations

from dataclasses import dataclass

from _assembly_receipt_fixture import REQUEST, _artifact_dict
from _quality_evidence_fixture import _effect_safety, _effect_window
from headless.approved_parent_quality_evidence import quality_evidence_set_digest
from headless.artifact_contract import ArtifactRefV1
from headless.repair_intent import approved_plan_digest


@dataclass(frozen=True)
class RuntimeEvidenceContext:
    """References shared by one full-decode/effect/Audit-B evidence set."""

    builder: object
    descriptor: dict
    runtime_manifest: ArtifactRefV1


def _common(context: RuntimeEvidenceContext) -> dict:
    builder = context.builder
    return {
        "plan": _artifact_dict(builder.plan_ref),
        "approvedPlanDigest": approved_plan_digest(builder.plan),
        "final": _artifact_dict(builder.final.artifact),
        "assemblyReceipt": context.descriptor["output"]["assemblyReceipt"],
        "qualityPolicyId": context.descriptor["policies"]["qualityPolicyId"],
        "runtimeCapabilityManifest": _artifact_dict(context.runtime_manifest),
    }


def full_decode_document(context: RuntimeEvidenceContext) -> dict:
    """Build exact passing full audio/video decode evidence."""
    builder = context.builder
    return {
        "schemaVersion": 1,
        "verdict": "pass",
        "method": "ffmpeg-xerror-full-av-v1",
        **_common(context),
        "tools": {
            "ffmpegSha256": builder.ffmpeg,
            "ffprobeSha256": builder.ffprobe,
        },
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


def _effect_color(context: RuntimeEvidenceContext) -> dict:
    builder = context.builder
    return {
        "target": {
            "graphicId": builder.asset.graphic_id,
            "relativePointer": "/spec/accent",
            "requestedValue": "#FFD400",
            "brandPolicyId": context.descriptor["policies"]["repairPolicyId"],
            "brandMembership": "pass",
        },
        "preEncode": {
            "graphicMedia": _artifact_dict(builder.asset.media.artifact),
            "renderIntentDigest": builder.asset.render_intent_digest,
            "rasterRgb": [255, 212, 0],
            "matchingPixels": 240,
            "method": "lossless-overlay-token-raster-v1",
        },
        "decodedColor": {
            "requestedRgb": [255, 212, 0],
            "observedRgb": [255, 212, 0],
            "maximumDeltaEMilli": 5_000,
            "observedDeltaEMilli": 0,
            "sampledFrames": 75,
            "matchingFrames": 75,
            "method": "calibrated-rgb-euclidean-milli-v1",
        },
    }


def effect_document(context: RuntimeEvidenceContext) -> dict:
    """Build exact passing requested-effect evidence."""
    return {
        "schemaVersion": 1,
        "verdict": "pass",
        "effectClass": "SECTION_MARKER_ACCENT_V1",
        "requestDigest": REQUEST,
        **_common(context),
        **_effect_color(context),
        **_effect_window(),
        **_effect_safety(),
    }


def _audit_domains() -> list[dict]:
    names = (
        "audio",
        "composite-visual",
        "cover",
        "format-duration-budget",
        "frames-safe-zone",
        "glitch",
        "motion",
        "placement",
    )
    return [
        {"name": name, "verdict": "pass", "checkCount": 1, "warningCount": 0}
        for name in names
    ]


def audit_document(
    context: RuntimeEvidenceContext,
    full_decode: ArtifactRefV1,
    effect_proof: ArtifactRefV1,
) -> dict:
    """Build exact terminal Audit-B evidence over both independent proofs."""
    return {
        "schemaVersion": 1,
        "verdict": "pass",
        "auditProfile": "B",
        "terminalStage": "after-full-decode-and-effect-proof",
        **_common(context),
        "evidence": {
            "fullDecode": _artifact_dict(full_decode),
            "effectProof": _artifact_dict(effect_proof),
            "evidenceSetDigest": quality_evidence_set_digest(full_decode, effect_proof),
        },
        "domains": _audit_domains(),
        "summary": {"checkCount": 8, "passed": 8, "warnings": 0, "failed": 0},
    }
