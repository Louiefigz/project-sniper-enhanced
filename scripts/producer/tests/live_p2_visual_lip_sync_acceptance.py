#!/usr/bin/env python3
"""Emit repeatable real-media acceptance evidence for P2 visual lip sync."""
from __future__ import annotations

import json
from pathlib import Path

from edit.cut_repair_context_sources import digest
from edit.cut_repair_visual_lip_sync import qualify_visual_lip_sync
from edit.cut_repair_visual_lip_sync_types import (
    RegionPpm,
    VisualLipSyncBlocker,
)
from tests._p2_visual_lip_sync_fixture import (
    VisualLipSyncFixture,
    file_hash,
)

ROOT = Path(__file__).resolve().parents[3]
SOURCE_FILES = (
    "scripts/producer/contracts/cut-repair-visual-lip-sync-policy-v1.json",
    "scripts/producer/cross_runtime_canonical_json.py",
    "scripts/producer/edit/cut_repair_candidate_qc.py",
    "scripts/producer/edit/cut_repair_candidate_qc_bundle.py",
    "scripts/producer/edit/cut_repair_candidate_qc_contract.py",
    "scripts/producer/edit/cut_repair_candidate_qc_pin.py",
    "scripts/producer/edit/cut_repair_candidate_qc_receipts.py",
    "scripts/producer/edit/cut_repair_candidate_qc_tools.py",
    "scripts/producer/edit/cut_repair_candidate_qc_types.py",
    "scripts/producer/edit/cut_repair_candidate_qc_visual.py",
    "scripts/producer/edit/cut_repair_context_sources.py",
    "scripts/producer/edit/cut_repair_promotion_candidate.py",
    "scripts/producer/edit/cut_repair_promotion_gate.py",
    "scripts/producer/edit/cut_repair_visual_lip_sync.py",
    "scripts/producer/edit/cut_repair_visual_lip_sync_contract.py",
    "scripts/producer/edit/cut_repair_visual_lip_sync_media.py",
    "scripts/producer/edit/cut_repair_visual_lip_sync_receipt.py",
    "scripts/producer/edit/cut_repair_visual_lip_sync_types.py",
    "schemas/producer/cut-repair-qc-tool-manifest-v1.schema.json",
    "src/lib/server/producer-cut-repair-promotion-evidence.ts",
    "src/lib/server/producer-cut-repair-visual-evidence.ts",
    "scripts/producer/tests/_p2_visual_lip_sync_fixture.py",
    "scripts/producer/tests/live_p2_visual_lip_sync_acceptance.py",
)


def _blocked(
    fixture: VisualLipSyncFixture,
    mode: str,
    region: RegionPpm | None = None,
) -> str:
    try:
        qualify_visual_lip_sync(fixture.request(mode, region))
    except VisualLipSyncBlocker as blocker:
        return blocker.code
    raise AssertionError(f"{mode} unexpectedly passed visual lip-sync QC")


def _source_closure() -> dict[str, str]:
    return {
        relative: file_hash(ROOT / relative)
        for relative in SOURCE_FILES
    }


def _media(fixture: VisualLipSyncFixture) -> dict:
    return {
        "selectedSourceSha256": file_hash(fixture.source),
        "alignedCandidateSha256":
            file_hash(fixture.candidates["aligned"]),
        "delayedCandidateSha256":
            file_hash(fixture.candidates["delayed"]),
        "occludedCandidateSha256":
            file_hash(fixture.candidates["occluded"]),
        "periodicSourceSha256": file_hash(fixture.periodic_source),
        "periodicCandidateSha256":
            file_hash(fixture.candidates["periodic"]),
        "positiveCandidateConstruction": {
            "video": "trim-selected-source-frames-0-through-60",
            "audio": "trim-selected-source-samples-0-through-96000",
            "reencodedFromSelectedSourceBytes": True,
        },
    }


def build_artifact() -> dict:
    """Run positive and adversarial real-media cases and seal their result."""
    fixture = VisualLipSyncFixture()
    try:
        receipt = qualify_visual_lip_sync(fixture.request("aligned"))
        closure = _source_closure()
        core = {
            "schemaVersion": 1,
            "kind": "p2-visual-lip-sync-controlled-media-acceptance",
            "status": "measured-pass",
            "protocol": "deterministic-selected-source-av-offset-v1",
            "evidenceSemantics":
                "caller-supplied-roi-source-av-temporal-mapping-"
                "not-face-mouth-or-phoneme-proof",
            "media": _media(fixture),
            "positiveReceipt": receipt,
            "negativeCases": {
                "threeFrameAudioDelay":
                    _blocked(fixture, "delayed"),
                "solidVisualOcclusion":
                    _blocked(fixture, "occluded"),
                "staticUnmeasurableRegion": _blocked(
                    fixture, "aligned",
                    RegionPpm(0, 0, 200_000, 200_000)),
                "periodicAmbiguousMapping":
                    _blocked(fixture, "periodic"),
            },
            "sourceClosure": closure,
            "sourceClosureHash": digest(closure),
            "nonClaims": [
                "not-phoneme-inference-or-lip-reading",
                "not-face-or-mouth-detection-roi-is-caller-supplied",
                "visual-code-closure-excludes-audio-seam-qc-orchestration-"
                "storage-promotion-and-python-os-dylibs",
                "not-a-production-picture-prepare-render-proof",
                "not-a-Palmier-or-NLE-round-trip-proof",
                "does-not-close-P2-row-10-without-picture-projection",
            ],
        }
        return {**core, "acceptanceHash": digest(core)}
    finally:
        fixture.clean()


def main() -> int:
    print(json.dumps(
        build_artifact(), ensure_ascii=False,
        indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
