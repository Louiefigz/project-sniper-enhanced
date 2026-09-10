#!/usr/bin/env python3
"""Prepare a closed minimal project and fixture for current-path telemetry."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from baseline_source_ranges import (
    FrameRange,
    cut_track,
    frame_seconds,
    parse_source_frame_ranges,
    selected_ranges,
    source_entry,
    source_frame_count,
    validate_source_rate,
)
from ingest_admission_contract import verify_source_set_binding


@dataclass(frozen=True)
class BaselineSpec:
    """Exact target clock and optional half-open source-frame selection."""

    mode: str
    frames: int
    rate: tuple[str, str]
    source_frame_ranges: tuple[FrameRange, ...] | None = None

def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False)
            + "\n").encode("utf-8")


def _write(path: Path, value: object) -> None:
    payload = _canonical(value)
    descriptor, staged = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged, path)
    finally:
        try:
            os.unlink(staged)
        except FileNotFoundError:
            pass


def _plan(spec: BaselineSpec, source: dict, ranges: tuple[FrameRange, ...],
          rate: tuple[int, int]) -> dict:
    duration = frame_seconds(spec.frames, rate)
    short = spec.mode == "short"
    return {
        "planVersion": 2,
        "target": {
            "mode": spec.mode,
            "scope": "trim",
            "durationTargetS": duration,
            "platforms": ["shorts"] if short else ["youtube"],
        },
        "cutTrack": cut_track(source["id"], ranges, rate),
        "reframe": {"strategy": "center" if short else "none"},
        "titleCards": [],
        "graphicsTrack": [],
        "punchIns": [],
        "brollTrack": [],
        "transitions": [],
        "captions": {"burn": False, "style": "karaoke"},
        "music": {"enabled": False},
        "audioEnhance": {
            "preset": "voice-strong" if short else "voice-rnn",
        },
        "chapters": None,
    }


def _project(mode: str) -> dict:
    return {
        "origin": "p0-current-baseline",
        "history": [],
        "resolvedIntent": {
            "mode": mode,
            "scope": "trim",
            "lanes": {},
            "music": False,
            "audioEnhance": {
                "preset": "voice-strong" if mode == "short" else "voice-rnn",
            },
        },
    }


def _validated_rate(spec: BaselineSpec) -> tuple[int, int]:
    if spec.mode not in {"short", "longform"}:
        raise RuntimeError("baseline mode is invalid")
    if type(spec.frames) is not int or spec.frames < 1:
        raise RuntimeError("baseline frame count must be positive")
    if len(spec.rate) != 2 or any(
            not isinstance(value, str) or not value.isdigit()
            for value in spec.rate):
        raise RuntimeError("baseline FPS terms must be decimal integers")
    numerator, denominator = (int(value) for value in spec.rate)
    if numerator <= 0 or denominator <= 0:
        raise RuntimeError("baseline FPS terms must be positive")
    duration = Fraction(spec.frames * denominator, numerator)
    if spec.mode == "longform" and not Fraction(12 * 60) <= duration <= 14 * 60:
        raise RuntimeError(
            "LF-14 current baseline must be between 12 and 14 minutes")
    return numerator, denominator


def _authority(
    plan_path: Path,
    manifest_path: Path,
    manifest: dict,
    entries: list[dict],
) -> dict:
    return {
        "planPath": plan_path.name,
        "planSha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        "manifestPath": manifest_path.name,
        "manifestSha256":
            hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "sourceSetDigest": manifest["sourceSetAdmission"]["sourceSetDigest"],
        "snapshotSha256s": sorted(entry["sha256"] for entry in entries),
    }


def _fixture(spec: BaselineSpec, authority: dict) -> dict:
    return {
        "schemaVersion": 1,
        "fixtureId":
            f"p0-current-{'short' if spec.mode == 'short' else 'lf14'}",
        "evidenceClass": "current-full-path-baseline",
        "mode": spec.mode,
        "durationFrames": spec.frames,
        "fps": {"numerator": spec.rate[0], "denominator": spec.rate[1]},
        "outputPaths": ["render/final.mp4"],
        "inputAuthority": authority,
    }


def prepare(project: Path, spec: BaselineSpec) -> tuple[Path, Path]:
    """Write a frame-exact plan and closed current-path fixture."""
    rate = _validated_rate(spec)
    manifest_path = project / "asset_manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    entries = verify_source_set_binding(manifest, project)
    sources = manifest.get("sources") or []
    if len(sources) != 1:
        raise RuntimeError("current baseline requires exactly one admitted source")
    source = sources[0]
    validate_source_rate(source, rate)
    entry = source_entry(source, entries)
    ranges = selected_ranges(
        spec.source_frame_ranges,
        spec.frames,
        source_frame_count(project, entry),
    )
    plan_path = project / "edit_plan.json"
    _write(plan_path, _plan(spec, source, ranges, rate))
    _write(project / "project.json", _project(spec.mode))
    fixture_path = project / "baseline-fixture.json"
    _write(
        fixture_path,
        _fixture(spec, _authority(
            plan_path, manifest_path, manifest, entries)),
    )
    return plan_path, fixture_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=("short", "longform"))
    parser.add_argument("--frames", required=True, type=int)
    parser.add_argument("--fps-num", required=True)
    parser.add_argument("--fps-den", required=True)
    parser.add_argument(
        "--source-frame-ranges",
        help=(
            "comma-separated half-open source frame ranges, "
            "for example 1680:17580,17660:21899"
        ),
    )
    args = parser.parse_args()
    plan, fixture = prepare(
        args.project.resolve(strict=True),
        BaselineSpec(
            mode=args.mode,
            frames=args.frames,
            rate=(args.fps_num, args.fps_den),
            source_frame_ranges=parse_source_frame_ranges(
                args.source_frame_ranges),
        ),
    )
    print(json.dumps({"plan": str(plan), "fixture": str(fixture)}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc))
        raise SystemExit(2) from exc
