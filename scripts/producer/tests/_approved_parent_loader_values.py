"""Stable wire values shared by the approved-parent disk fixture."""

from __future__ import annotations

import json

from headless.generation_policy_documents import (
    current_execution_policy,
    current_fallback_policy,
)
from headless.quality_policy import current_deterministic_quality_policy
from headless.repair_intent import current_accent_policy

AUTHORITY = "authority-mp4-v1"
GENERATION = "11111111-1111-4111-8111-111111111111"
ATTEMPT = "22222222-2222-4222-8222-222222222222"
UNIT = "33333333-3333-4333-8333-333333333333"
REQUEST = "1" * 64
EXECUTION = current_execution_policy().policy_id
REPAIR = current_accent_policy().policy_id
QUALITY = current_deterministic_quality_policy().policy_id
FALLBACK = current_fallback_policy().policy_id
COMMIT_DOMAIN = b"sniper-mp4-generation-commit-v1\0"
PAYLOAD_DOMAIN = b"sniper-generation-payload-manifest-v1\0"

SPECIAL_PATHS = {
    "approved-parent-v1": "authority/approved-parent.json",
    "generation-verification-v1": "authority/generation-verification.json",
    "plan-v1": "plan/edit-plan.json",
    "base-media-v1": "base/base.mp4",
    "prebound-clips-v1": "graphics/prebound-clips.json",
    "graphic-media-v1": "graphics/g-00000001.mov",
    "graphic-render-receipt-v1": "graphics/g-00000001.receipt.json",
    "final-media-v1": "output/final.mp4",
}
PROVENANCE = {
    "requestIdentity": "request-identity-v1",
    "executionPolicy": "execution-policy-v1",
    "admissionInputs": "admission-inputs-v1",
    "realizationInputs": "realization-inputs-v1",
    "generationInputs": "generation-inputs-v1",
    "sourceSnapshotManifest": "source-snapshot-manifest-v1",
    "baseFingerprint": "base-fingerprint-v1",
    "operatorIntent": "operator-intent-v1",
    "cutApproval": "cut-approval-v1",
    "assetClosure": "asset-closure-v1",
    "runtimeCapabilityManifest": "runtime-capability-manifest-v1",
    "repairState": "repair-state-v1",
    "realization": "realization-v1",
    "templateUsageApproval": "template-usage-approval-v1",
    "refitDisposition": "refit-disposition-v1",
    "proxyDisposition": "proxy-disposition-v1",
}


def canonical(value: object) -> bytes:
    """Encode exact ASCII canonical JSON used by every authority record."""
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("ascii")


def policy_payloads() -> dict[str, bytes]:
    """Return the four exact current policy documents used by the loader."""
    repair = current_accent_policy()
    repair_raw = canonical(
        {
            "schemaVersion": 1,
            "effectClass": "SECTION_MARKER_ACCENT_V1",
            "allowedValues": list(repair.allowed_values),
        }
    )
    return {
        "execution-policy-v1": current_execution_policy().document_json,
        "repair-policy-v1": repair_raw,
        "quality-policy-v1": current_deterministic_quality_policy().document_json,
        "fallback-policy-v1": current_fallback_policy().document_json,
    }


def artifact_path(artifact_class: str, ordinal: int = 0) -> str:
    """Give every versioned manifest row one stable, non-aliasing path."""
    if ordinal == 0 and artifact_class in SPECIAL_PATHS:
        return SPECIAL_PATHS[artifact_class]
    suffix = f"-{ordinal}" if ordinal else ""
    return f"artifacts/{artifact_class}{suffix}.json"


def plan() -> dict:
    """Return the single-graphic canonical R0 edit plan."""
    row = {
        "id": "g-00000001",
        "kind": "section-marker",
        "outStart": 1.0,
        "outEnd": 3.5,
        "anchor": "free-band",
        "placement": {"x": 50, "y": 100},
        "spec": {
            "num": "One",
            "line1": "Exact",
            "line2": "Authority",
            "side": "left",
            "accent": "#054BC9",
        },
    }
    return {
        "planVersion": 3,
        "target": {"mode": "short"},
        "graphicsTrack": [row],
        "captions": {"enabled": True},
    }


def clips(plan_value: dict, media: dict, receipt: dict) -> list[dict]:
    """Bind the exact graphic bytes and placement without paths."""
    row = plan_value["graphicsTrack"][0]
    return [
        {
            "graphicId": row["id"],
            "outStart": row["outStart"],
            "outEnd": row["outEnd"],
            "anchor": row["anchor"],
            "x": row["placement"]["x"],
            "y": row["placement"]["y"],
            "mediaSha256": media["sha256"],
            "renderReceiptSha256": receipt["sha256"],
        }
    ]
