#!/usr/bin/env python3
"""Retain the full P2 row-one rate/position real-media claim cohort."""
from __future__ import annotations

import argparse
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from current_render_graph_contract import canonical_bytes, file_hash
from edit.exact_timing import PositiveRational
from edit.picture_lock_common import content_hash
from palmier.cut_repair_projection import (
    PalmierRepairProjectionInput,
    project_cut_repair,
    verify_cut_repair_readback,
)
from tests._build_manifest_import_closure import local_import_closure
from tests._p2_repair_media_fixture import tools
from tests.p2_row1_execution_fixture import (
    POSITIONS,
    CaseSpec,
    prepare_rate_media,
    run_case,
)

REPO = Path(__file__).resolve().parents[3]
ARTIFACT_NAME = "p2-row1-claim-cohort-v1.json"
COHORT_ID = "p2-row1-24-cell-real-media-cohort-v1"
RATES = tuple(PositiveRational(*terms) for terms in (
    (24_000, 1_001), (24, 1), (25, 1), (30_000, 1_001),
    (30, 1), (50, 1), (60_000, 1_001), (60, 1),
))
RATE_TOKENS = tuple(
    f"{rate.numerator}/{rate.denominator}" for rate in RATES)
_ENTRYPOINTS = (
    "scripts/producer/tests/live_p2_row1_acceptance.py",
)
_DYNAMIC_FILES = (
    "schemas/producer/caption-repair-revalidation-v1.schema.json",
    "schemas/producer/channel-normalization-receipt-v1.schema.json",
)
CLOSURE = tuple(sorted(
    local_import_closure(_ENTRYPOINTS).union(_DYNAMIC_FILES)))


def _source_closure() -> dict:
    return {name: file_hash(REPO / name) for name in CLOSURE}


def _toolchain() -> dict:
    value = tools()
    return {
        "ffmpeg": {
            "path": value.ffmpeg_path,
            "sha256": value.ffmpeg_sha256,
        },
        "ffprobe": {
            "path": value.ffprobe_path,
            "sha256": value.ffprobe_sha256,
        },
    }


def _native_operation() -> dict:
    return {
        "schemaVersion": 1, "operation": "cut.restoreSpeech",
        "method": "extend-and-reclaim-silence",
        "speed": {"numerator": "1", "denominator": "1"},
        "sourceExtension": {
            "startSample": 48_000, "endSampleExclusive": 52_800,
        },
        "sourceSampleRate": 48_000,
        "extensionOutputSamples": 4_800,
    }


def _native_timeline(projection: dict) -> dict:
    clips = [{
        "id": f"base-{index}",
        "frames": row["frames"], "source": row["source"],
        "speed": row["speed"],
    } for index, row in enumerate(projection["expectedCuts"])]
    return {
        "totalFrames": projection["expectedTotalFrames"],
        "tracks": [
            {"clips": clips},
            {"clips": [{
                "id": "overlay-control", "frames": [30, 50],
                "textContent": "unchanged",
            }]},
        ],
    }


def _native_control() -> dict:
    operation = _native_operation()
    retime = {
        "requestedSpeed": operation["speed"],
        "sourceSampleRange": operation["sourceExtension"],
        "sourceSampleRate": 48_000,
        "normalizedSourceSampleRange": operation["sourceExtension"],
        "outputSamples": 4_800,
        "effectiveRatio": operation["speed"],
    }
    cuts = (
        {"sourceId": "source-a", "start": 0.0,
         "end": 2.0, "speed": 1.0},
        {"sourceId": "source-a", "start": 3.0,
         "end": 5.0, "speed": 1.0},
    )
    projection = project_cut_repair(PalmierRepairProjectionInput(
        operation, content_hash(operation), cuts,
        PositiveRational(30, 1), True, retime))
    timeline = _native_timeline(projection)
    readback = verify_cut_repair_readback(
        projection, timeline, timeline)
    assertions = {
        "supportedSubsetQualified":
            projection["nativeStatus"] == "frame-exact-unqualified",
        "readbackBound":
            readback["projectionHash"] == projection["projectionHash"],
        "unrelatedInventoryPreserved":
            readback["unrelatedInventoryPreserved"] is True,
        "sampleExactNotClaimed":
            projection["sampleExact"] is False
            and readback["sampleExact"] is False,
        "bakedDeliveryRetained":
            readback["deliveryDisposition"] == "baked-exact-master",
    }
    return {
        "kind": "local-structural-palmier-readback-control",
        "fps": {"numerator": "30", "denominator": "1"},
        "sourceIds": ["source-a"],
        "projectionHash": projection["projectionHash"],
        "nativeStatus": projection["nativeStatus"],
        "expectedTotalFrames": projection["expectedTotalFrames"],
        "readbackHash": readback["readbackHash"],
        "assertions": assertions, "passed": all(assertions.values()),
    }


def _coverage(cases: list[dict]) -> dict:
    by_rate = {
        token: sorted(
            row["repair"]["position"]
            for row in cases if row["rateToken"] == token)
        for token in RATE_TOKENS
    }
    expected_positions = sorted(POSITIONS)
    identities = [row["caseId"] for row in cases]
    return {
        "expectedCaseCount": len(RATES) * len(POSITIONS),
        "actualCaseCount": len(cases),
        "rateTokens": list(RATE_TOKENS),
        "positions": list(POSITIONS),
        "positionsByRate": by_rate,
        "uniqueCaseIdentities":
            len(identities) == len(set(identities)),
        "crossProductComplete":
            all(rows == expected_positions for rows in by_rate.values()),
        "allCaseAssertionsPassed":
            all(row["passed"] for row in cases),
        "normalizedVfrCaseCount": sum(
            row["assertions"]["normalizedVfr"] for row in cases),
        "captionRefitCaseCount": sum(
            row["assertions"]["captionRefit"] for row in cases),
        "generalJlCaseCount": sum(
            row["assertions"]["generalJResolved"]
            and row["assertions"]["generalLResolved"]
            for row in cases),
        "palmierFailClosedCaseCount": sum(
            row["assertions"]["palmierReadbackFailClosed"]
            for row in cases),
    }


def _run_cases(root: Path) -> list[dict]:
    cases = []
    for rate in RATES:
        token = f"{rate.numerator}-{rate.denominator}"
        rate_root = root / f"rate-{token}"
        media = prepare_rate_media(rate_root / "media", rate)
        for position in POSITIONS:
            spec = CaseSpec(rate, position)
            cases.append(run_case(
                rate_root / position, spec, media))
    return cases


def run_cohort() -> dict:
    """Execute all 24 cells and return one self-hashed retained receipt."""
    started = time.monotonic()
    with tempfile.TemporaryDirectory(
            prefix="sniper-p2-row1-") as raw:
        cases = _run_cases(Path(raw).resolve())
    coverage = _coverage(cases)
    native = _native_control()
    passed = (
        coverage["actualCaseCount"] == coverage["expectedCaseCount"]
        and coverage["uniqueCaseIdentities"]
        and coverage["crossProductComplete"]
        and coverage["allCaseAssertionsPassed"]
        and native["passed"]
    )
    value = {
        "schemaVersion": 1, "kind": "p2-row1-claim-cohort",
        "cohortId": COHORT_ID,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "execution": {
            "mode": "local-real-media",
            "candidateExecutions": len(cases),
            "connectedPalmierMutationCount": 0,
        },
        "elapsedSeconds": round(time.monotonic() - started, 3),
        "sourceClosure": _source_closure(),
        "toolchain": _toolchain(), "coverage": coverage,
        "cases": cases, "nativeSubsetControl": native,
        "nonClaims": [
            "not a connected Palmier mutation or connected readback",
            "not native sample-exact Palmier L/J support",
            "not the first-class analyze/prepare/review/approve lifecycle",
            "not plan-vocabulary picture-repair or L-edge authoring",
            "not alternate-take selection or a visual lip-sync oracle",
            "not creator-speech ASR, audibility, or semantic quality proof",
        ],
        "passed": passed,
    }
    value["receiptHash"] = content_hash(value)
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", required=True, type=Path)
    args = parser.parse_args()
    value = run_cohort()
    path = args.artifact.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value) + b"\n")
    return 0 if value["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
