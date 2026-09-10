#!/usr/bin/env python3
"""Retain real-media proof that 24 overlays use one picture generation."""
from __future__ import annotations

import argparse
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from current_render_oracle import prove
from graphics.composite_core import (
    CompositeOptions,
    _composite_pass,
    composite,
    run_command,
)
from tests._build_manifest_import_closure import local_import_closure
from tests.p4_exit_media import (
    ProgramSpec,
    ffmpeg,
    make_program,
    probe,
    source_closure,
    toolchain,
    write_canonical,
)

REPO = Path(__file__).parents[3]
_ENTRYPOINTS = (
    "scripts/producer/tests/live_p5_compositor_acceptance.py",
)
CLOSURE = tuple(sorted(local_import_closure(_ENTRYPOINTS)))
_OVERLAY_COUNT = 24
_CHUNK = 8
_DIMS = (1920, 1080)


def _make_overlay(path: Path) -> None:
    source = (
        "color=black@0.0:s=1920x1080:r=30:d=0.25,format=yuva444p10le,"
        "drawbox=x=480:y=260:w=960:h=560:"
        "color=0x40ff80@0.8:t=fill:replace=1"
    )
    ffmpeg(
        "-f", "lavfi", "-i", source,
        "-c:v", "prores_ks", "-profile:v", "4",
        "-pix_fmt", "yuva444p10le", str(path),
    )


def _clips(path: Path) -> list[dict]:
    rows = []
    for index in range(_OVERLAY_COUNT):
        start = 0.1 + index * 0.15
        rows.append({
            "path": str(path), "outStart": start,
            "outEnd": start + 0.12,
        })
    return rows


def _legacy_three_pass(
    base: Path, clips: list[dict], output: Path, root: Path,
) -> int:
    options = CompositeOptions(eof_pass=True)
    source = base
    chunks = [
        clips[index:index + _CHUNK]
        for index in range(0, len(clips), _CHUNK)
    ]
    for index, chunk in enumerate(chunks):
        target = output if index == len(chunks) - 1 \
            else root / f"legacy-pass-{index}.mp4"
        _composite_pass(str(source), chunk, str(target), options)
        source = target
    return len(chunks)


def _sample(path: Path, seconds: float) -> list[float]:
    raw = ffmpeg(
        "-ss", str(seconds), "-i", str(path),
        "-vf", "crop=960:560:480:260,format=rgb24",
        "-frames:v", "1", "-f", "rawvideo", "-",
    )
    pixels = len(raw) // 3
    return [
        round(sum(raw[channel::3]) / pixels, 3)
        for channel in range(3)
    ]


def _oracle(value: dict) -> dict:
    return {
        "passed": value["passed"],
        "decodedAudioMatch": value["decodedAudioMatch"],
        "streamFactsMatch": value["streamFactsMatch"],
        "pictureComparison": value["pictureComparison"],
    }


def _passes(evidence: dict, comparison: dict) -> bool:
    sample = evidence["visibleOverlaySample"]
    return (
        evidence["overlayCount"] == _OVERLAY_COUNT
        and evidence["production"]["reportedPasses"] == 1
        and evidence["production"]["ffmpegCommandCount"] == 1
        and evidence["production"]["inputCount"] == _OVERLAY_COUNT
        and evidence["production"]["filterOverlayCount"] == _OVERLAY_COUNT
        and evidence["legacyControl"]["pictureEncodeCount"] == 3
        and comparison["passed"]
        and sample["outputRgb"][1] > sample["baseRgb"][1] + 60
    )


def run_case(root: Path) -> dict:
    base = root / "base.mp4"
    overlay = root / "overlay.mov"
    output = root / "production.mp4"
    legacy = root / "legacy-three-pass.mp4"
    make_program(base, ProgramSpec(_DIMS, 30, 4.0, "flat"))
    _make_overlay(overlay)
    clips = _clips(overlay)
    commands: list[list[str]] = []

    def observed(command: list[str]) -> None:
        commands.append(command)
        run_command(command)

    passes = composite(
        str(base), clips, str(output),
        CompositeOptions(eof_pass=True, command_runner=observed),
    )
    legacy_passes = _legacy_three_pass(base, clips, legacy, root)
    comparison = prove(output, legacy, root / "oracle.json")
    graph = commands[0][commands[0].index("-filter_complex") + 1]
    evidence = {
        "overlayCount": len(clips),
        "production": {
            "reportedPasses": passes,
            "ffmpegCommandCount": len(commands),
            "pictureEncodeCount": len(commands),
            "inputCount": commands[0].count("-i") - 1,
            "filterOverlayCount": graph.count("]overlay="),
            "decode": probe(output),
        },
        "legacyControl": {
            "pictureEncodeCount": legacy_passes,
            "decode": probe(legacy),
        },
        "legacyEquivalenceOracle": _oracle(comparison),
        "visibleOverlaySample": {
            "baseRgb": _sample(base, 0.15),
            "outputRgb": _sample(output, 0.15),
        },
    }
    evidence["passed"] = _passes(evidence, comparison)
    return evidence


def run_cohort() -> dict:
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="sniper-p5-compositor-") as raw:
        evidence = run_case(Path(raw).resolve())
    return {
        "schemaVersion": 1, "kind": "p5-24-overlay-one-pass",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "execution": {"mode": "local-real-ffmpeg-media"},
        "elapsedSeconds": round(time.monotonic() - started, 3),
        "sourceClosure": source_closure(REPO, CLOSURE),
        "toolchain": toolchain(), "evidence": evidence,
        "nonClaims": [
            "one full-duration picture encode remains for a full build",
            "not a universal 4096-overlay resource qualification",
            "not dirty-window stitching or connected Palmier evidence",
        ],
        "passed": evidence["passed"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", required=True, type=Path)
    args = parser.parse_args()
    value = run_cohort()
    write_canonical(args.artifact.resolve(), value)
    return 0 if value["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
