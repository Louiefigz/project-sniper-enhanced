"""Canonical decode, effect, and terminal-audit payloads for loader tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from _approved_parent_loader_values import (
    QUALITY,
    REPAIR,
    REQUEST,
    artifact_path,
    canonical,
)
from headless.approved_parent_quality_evidence import quality_evidence_set_digest
from headless.artifact_contract import ArtifactRefV1
from headless.quality_pass_contract import graphic_render_intent_digest
from headless.repair_intent import approved_plan_digest

EvidenceMutator = Callable[[str, dict], None]


class EvidenceFixtureBuilder(Protocol):
    """Small fixture surface needed to stage exact evidence bytes."""

    scenario: str
    plan: dict
    files: dict[str, bytes]

    def ref(self, artifact_class: str, ordinal: int = 0) -> dict:
        """Return the current reference for one staged artifact."""


def _full_decode(builder: EvidenceFixtureBuilder) -> dict:
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


def _effect_observations() -> dict:
    return {
        "decodedColor": {
            "requestedRgb": [5, 75, 201],
            "observedRgb": [6, 75, 199],
            "maximumDeltaEMilli": 5_000,
            "observedDeltaEMilli": 2_236,
            "sampledFrames": 75,
            "matchingFrames": 75,
            "method": "calibrated-rgb-euclidean-milli-v1",
        },
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


def _effect(builder: EvidenceFixtureBuilder) -> dict:
    row = builder.plan["graphicsTrack"][0]
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
        "target": {
            "graphicId": row["id"],
            "relativePointer": "/spec/accent",
            "requestedValue": "#054BC9",
            "brandPolicyId": REPAIR,
            "brandMembership": "pass",
        },
        "preEncode": {
            "graphicMedia": builder.ref("graphic-media-v1"),
            "renderIntentDigest": graphic_render_intent_digest(row),
            "rasterRgb": [5, 75, 201],
            "matchingPixels": 240,
            "method": "lossless-overlay-token-raster-v1",
        },
        **_effect_observations(),
        **_effect_safety(),
    }


def _ref(value: dict) -> ArtifactRefV1:
    return ArtifactRefV1(value["path"], value["sha256"], value["sizeBytes"])


def _audit(builder: EvidenceFixtureBuilder) -> dict:
    full_decode = _ref(builder.ref("full-decode-proof-v1"))
    effect_proof = _ref(builder.ref("effect-proof-v1"))
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
    domains = [
        {"name": name, "verdict": "pass", "checkCount": 1, "warningCount": 0}
        for name in names
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


def _scenario(builder: EvidenceFixtureBuilder, stage: str, document: dict) -> None:
    if builder.scenario == "evidence-decode-binding" and stage == "full-decode":
        for key in document["video"]:
            document["video"][key] = 121
    if builder.scenario == "evidence-effect-binding" and stage == "effect-proof":
        document["requestDigest"] = "0" * 64
    if builder.scenario == "evidence-audit-binding" and stage == "audit-b":
        document["qualityPolicyId"] = "0" * 64


def set_evidence_payloads(
    builder: EvidenceFixtureBuilder, mutator: EvidenceMutator | None = None
) -> None:
    """Stage independent evidence before terminal Audit-B in causal order."""
    stages = (
        ("full-decode", "full-decode-proof-v1", _full_decode),
        ("effect-proof", "effect-proof-v1", _effect),
    )
    for stage, artifact_class, factory in stages:
        document = factory(builder)
        _scenario(builder, stage, document)
        if mutator is not None:
            mutator(stage, document)
        builder.files[artifact_path(artifact_class)] = canonical(document)
    audit = _audit(builder)
    _scenario(builder, "audit-b", audit)
    if mutator is not None:
        mutator("audit-b", audit)
    builder.files[artifact_path("audit-b-receipt-v1")] = canonical(audit)
