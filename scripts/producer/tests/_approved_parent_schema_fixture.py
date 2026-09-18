"""Canonical approved-parent documents for schema regressions."""

from __future__ import annotations

import json

GENERATION = "11111111-1111-4111-8111-111111111111"
ATTEMPT = "22222222-2222-4222-8222-222222222222"
UNIT = "33333333-3333-4333-8333-333333333333"
PROVENANCE = (
    "requestIdentity executionPolicy admissionInputs realizationInputs "
    "generationInputs sourceSnapshotManifest baseFingerprint operatorIntent "
    "cutApproval assetClosure runtimeCapabilityManifest repairState realization "
    "templateUsageApproval refitDisposition proxyDisposition"
).split()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True, allow_nan=False
    ).encode("ascii")


def _artifact(path: str, marker: str, size: int = 100) -> dict:
    return {"path": path, "sha256": marker * 64, "sizeBytes": size}


def _media(path: str, marker: str, audio: str | None = "aac") -> dict:
    return {
        "artifact": _artifact(path, marker),
        "facts": {
            "width": 1080,
            "height": 1920,
            "durationSeconds": 4.0,
            "fpsNumerator": 30,
            "fpsDenominator": 1,
            "frameCount": 120,
            "sizeBytes": 100,
            "videoCodec": "h264",
            "pixelFormat": "yuv420p",
            "profile": "High",
            "alphaMode": "none",
            "audioCodec": audio,
        },
    }


def _graphic(number: int, marker: str) -> dict:
    identity = f"g-{number:08d}"
    return {
        "graphicId": identity,
        "renderIntentDigest": marker * 64,
        "media": _media(f"graphics/{identity}.mov", marker, None),
        "receipt": _artifact(f"graphics/{identity}.receipt.json", str(number)),
        "renderArtifactDigest": marker * 64,
        "renderBuildDigest": marker * 64,
    }


def _provenance() -> dict:
    return {
        name: _artifact(f"provenance/{name}.json", f"{index % 16:x}")
        for index, name in enumerate(PROVENANCE)
    }


def _quality() -> dict:
    return {
        "audit": _artifact("quality/audit.json", "0"),
        "fullDecode": _artifact("quality/full-decode.json", "1"),
        "effectProof": _artifact("quality/effect-proof.json", "2"),
        "qcReceipt": _artifact("quality/qc-receipt.json", "3"),
        "critics": [
            {
                "lens": "composition",
                "artifact": _artifact("quality/composition.json", "4"),
            },
            {
                "lens": "editorial",
                "artifact": _artifact("quality/editorial.json", "5"),
            },
        ],
        "finalApproval": _artifact("quality/final-approval.json", "6"),
    }


def _descriptor() -> dict:
    return {
        "schemaVersion": 1,
        "status": "approved-private-generation",
        "realizationKind": "deterministic-mp4",
        "identity": {
            "authorityId": "authority-mp4-v1",
            "generationId": GENERATION,
            "attemptId": ATTEMPT,
            "unitId": UNIT,
            "requestDigest": "1" * 64,
        },
        "policies": {
            "executionPolicyId": "2" * 64,
            "repairPolicyId": "3" * 64,
            "qualityPolicyId": "4" * 64,
            "fallbackPolicyId": "5" * 64,
        },
        "provenance": _provenance(),
        "plan": {
            "artifact": _artifact("plan/edit-plan.json", "6"),
            "approvedPlanDigest": "7" * 64,
            "contentHash": "8" * 64,
            "baseProjectionDigest": "9" * 64,
        },
        "base": {
            "media": _media("base/base.mp4", "a"),
            "planArtifact": _artifact("base/plan.json", "b"),
            "receipt": _artifact("base/receipt.json", "c"),
            "timelineMap": _artifact("base/timeline-map.json", "d"),
        },
        "graphics": {
            "preboundClips": _artifact("graphics/prebound-clips.json", "e"),
            "assets": [_graphic(1, "a"), _graphic(2, "b")],
        },
        "output": {
            "final": _media("output/final.mp4", "c"),
            "assemblyReceipt": _artifact("output/assembly.json", "d"),
            "cover": _artifact("output/cover.png", "e"),
            "coverProof": _artifact("output/cover-proof.json", "f"),
            "proxyDisposition": "omitted-by-policy",
        },
        "quality": _quality(),
    }
