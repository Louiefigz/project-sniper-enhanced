#!/usr/bin/env python3
"""Build a retained three-pair codec-floor control cohort."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from audio.master import MasterSpec, master
from current_render_calibration_source import retain_source, verify_source_record
from current_render_graph_contract import file_hash, object_hash
from current_render_oracle import (
    CODEC_FLOOR_POLICY,
    _tool_facts,
    _write,
    prove,
)
from producer_config import AUDIO, ENCODE

SCRIPT_DIR = Path(__file__).resolve().parent
MINIMUM_PAIRS = 3


def _source_files() -> dict:
    paths = [
        SCRIPT_DIR / "audio" / "master.py",
        SCRIPT_DIR / "current_render_calibration_source.py",
        SCRIPT_DIR / "current_render_oracle.py",
        Path(__file__).resolve(),
    ]
    return {
        str(path.resolve()): file_hash(path.resolve(strict=True))
        for path in paths
    }


def _master_policy() -> dict:
    policy = {"audio": AUDIO, "encode": ENCODE}
    return json.loads(json.dumps(policy, allow_nan=False))


def _runtime_facts() -> dict:
    facts = _tool_facts()
    python = Path(os.path.realpath(sys.executable))
    facts["python"] = {"path": str(python), "sha256": file_hash(python)}
    result = os.popen("ffmpeg -version").read()
    facts["ffmpegVersionOutputSha256"] = object_hash({
        "stdout": result,
    })
    return facts


def _encode(source: Path, output: Path) -> tuple[dict, float]:
    spec = MasterSpec(
        src=str(source), out=str(output), fps=30, fps_exact="30/1",
        duration=45.0, frame_count=1350)
    started = time.monotonic()
    result = master(spec)
    elapsed = time.monotonic() - started
    if result.get("status") != "done" or not output.is_file():
        raise RuntimeError(f"canonical master calibration failed: {result}")
    return result, elapsed


def _one_pair(source: Path, work: Path, index: int) -> dict:
    left = work / f"pair-{index:02d}-a.mp4"
    right = work / f"pair-{index:02d}-b.mp4"
    left_result, left_s = _encode(source, left)
    right_result, right_s = _encode(source, right)
    pair_receipt = prove(left, right, work / f"pair-{index:02d}.json")
    row = {
        "pair": index,
        "left": {
            "sha256": file_hash(left), "sizeBytes": left.stat().st_size,
            "wallSeconds": round(left_s, 3), "masterResult": left_result,
        },
        "right": {
            "sha256": file_hash(right), "sizeBytes": right.stat().st_size,
            "wallSeconds": round(right_s, 3), "masterResult": right_result,
        },
        "pictureComparison": pair_receipt["pictureComparison"],
        "decodedAudioMatch": pair_receipt["decodedAudioMatch"],
        "streamFactsMatch": pair_receipt["streamFactsMatch"],
        "oracleReceiptHash": pair_receipt["receiptHash"],
        "passed": pair_receipt["passed"],
    }
    left.unlink()
    right.unlink()
    return row


def calibrate(source: Path, output: Path, pair_count: int) -> dict:
    """Run independent canonical master pairs and retain bounded evidence."""
    if pair_count < MINIMUM_PAIRS:
        raise RuntimeError(f"codec-floor calibration requires {MINIMUM_PAIRS} pairs")
    source_facts = retain_source(source)
    source_files, tools = _source_files(), _runtime_facts()
    master_policy = _master_policy()
    with tempfile.TemporaryDirectory(prefix="sniper-codec-floor-") as tmp:
        rows = [
            _one_pair(Path(source_facts["path"]), Path(tmp), index)
            for index in range(1, pair_count + 1)
        ]
    if source_files != _source_files() or tools != _runtime_facts() \
            or master_policy != _master_policy() \
            or verify_source_record(source_facts) != source_facts:
        raise RuntimeError("codec-floor toolchain changed during calibration")
    measured = [
        row["pictureComparison"]["metrics"] for row in rows
        if row["pictureComparison"]["metrics"] is not None
    ]
    receipt = {
        "schemaVersion": 1,
        "kind": "current-render-codec-floor-calibration",
        "classification": "local-current-master-control-cohort",
        "source": source_facts,
        "masterSpec": {
            "fps": 30, "fpsExact": "30/1",
            "durationSeconds": 45.0, "frameCount": 1350,
        },
        "tools": tools, "sourceFiles": source_files,
        "masterPolicy": master_policy,
        "masterPolicyHash": object_hash(master_policy),
        "policy": CODEC_FLOOR_POLICY,
        "policyHash": object_hash(CODEC_FLOOR_POLICY),
        "pairs": rows,
        "observed": {
            "pairCount": len(rows),
            "lowestMeanSsim": min(
                row["meanSsim"] for row in measured) if measured else 1.0,
            "lowestFrameSsim": min(
                row["minimumFrameSsim"] for row in measured) if measured else 1.0,
        },
        "passed": all(row["passed"] for row in rows),
    }
    receipt["receiptHash"] = object_hash(receipt)
    _write(output, receipt)
    if not receipt["passed"]:
        raise RuntimeError("codec-floor control cohort did not pass pinned policy")
    return receipt


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--pairs", type=int, default=MINIMUM_PAIRS)
    args = parser.parse_args()
    try:
        result = calibrate(args.source, args.output, args.pairs)
        print(json.dumps({
            "status": "calibration_passed",
            "receiptHash": result["receiptHash"],
            "observed": result["observed"],
        }))
        return 0
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
