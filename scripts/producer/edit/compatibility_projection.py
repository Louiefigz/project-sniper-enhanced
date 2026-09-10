#!/usr/bin/env python3
"""Build the P1 shadow projection of an approved compatibility cut.

This artifact is evidence, not picture-lock authority.  It binds the supplied
approved-cut plan identity to the current cut decisions and to the exact
``compile_timeline.compile_plan`` result without creating a second timing
implementation.

CLI:
    compatibility_projection.py PLAN APPROVED_CUT_PLAN_SHA256 OUT
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

_PRODUCER_DIR = Path(__file__).resolve().parents[1]
if str(_PRODUCER_DIR) not in sys.path:
    sys.path.insert(0, str(_PRODUCER_DIR))

from compile_timeline import TIMELINE_UNITS, compile_plan
from cross_runtime_canonical_json import (
    CrossRuntimeCanonicalJsonError,
    canonical_compact_json,
)

SCHEMA_VERSION = 1
KIND = "compatibility-timeline-projection"
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_COMPILER_SOURCES = (
    Path(__file__).resolve(),
    _PRODUCER_DIR / "compile_timeline.py",
    _PRODUCER_DIR / "cross_runtime_canonical_json.py",
    _PRODUCER_DIR / "producer_config.py",
)
_COMPILER_DOMAIN = b"project-sniper-compatibility-timeline-compiler-v1\0"
_TIMELINE_UNITS = TIMELINE_UNITS
_TIMELINE_FIELDS = (
    "src_start", "src_end", "speed", "out_start", "out_end", "audio_lead_s",
)


class ProjectionError(ValueError):
    """The projection input cannot produce trustworthy shadow evidence."""


def canonical_json(value: object) -> str:
    """Return the repository's compact, key-sorted canonical JSON form."""
    try:
        return canonical_compact_json(value)
    except CrossRuntimeCanonicalJsonError as exc:
        raise ProjectionError(f"value is not canonical JSON: {exc}") from exc


def stable_digest(value: object) -> str:
    """Full SHA-256 over canonical UTF-8 JSON bytes."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _bind_part(digest: Any, label: str, payload: bytes) -> None:
    """Length-frame one compiler input so concatenated parts are unambiguous."""
    label_bytes = label.encode("utf-8")
    digest.update(len(label_bytes).to_bytes(4, "big"))
    digest.update(label_bytes)
    digest.update(len(payload).to_bytes(8, "big"))
    digest.update(payload)


def compiler_hash() -> str:
    """Bind the timing kernel, all its tunables, and Python major/minor."""
    digest = hashlib.sha256(_COMPILER_DOMAIN)
    version = f"{sys.version_info.major}.{sys.version_info.minor}".encode("ascii")
    _bind_part(digest, "python-major-minor", version)
    for path in _COMPILER_SOURCES:
        try:
            source = path.read_bytes()
        except OSError as exc:
            raise ProjectionError(f"compiler source unreadable: {path}: {exc}") from exc
        _bind_part(digest, path.name, source)
    return digest.hexdigest()


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProjectionError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ProjectionError(f"{label} must be a finite number")
    return result


def _timeline_units(value: object, label: str) -> int:
    """Quantize a nonnegative map value to the V1 millionth-unit grid."""
    number = _number(value, label)
    if number < 0:
        raise ProjectionError(f"{label} must be zero or greater")
    return math.floor(number * _TIMELINE_UNITS + 0.5)


def _timeline_value(value: object, label: str) -> int | float:
    units = _timeline_units(value, label)
    return units // _TIMELINE_UNITS if units % _TIMELINE_UNITS == 0 \
        else units / _TIMELINE_UNITS


def _normalize_timeline_map(value: object) -> dict:
    """Project compiler floats onto a cross-language, loss-bounded V1 grid."""
    if not isinstance(value, dict) or not isinstance(value.get("segments"), list):
        raise ProjectionError("compiled timeline map is malformed")
    segments = []
    for position, row in enumerate(value["segments"]):
        if not isinstance(row, dict):
            raise ProjectionError(f"compiled segment {position} is malformed")
        normalized = {
            "index": row.get("index"),
            "source_id": row.get("source_id"),
            **{field: _timeline_value(
                row.get(field), f"segment {position} {field}")
               for field in _TIMELINE_FIELDS},
        }
        if normalized["index"] != position \
                or not isinstance(normalized["source_id"], str) \
                or normalized["src_end"] <= normalized["src_start"] \
                or normalized["speed"] <= 0 \
                or normalized["out_end"] <= normalized["out_start"]:
            raise ProjectionError(f"compiled segment {position} is malformed")
        segments.append(normalized)
    output_duration = _timeline_value(
        value.get("outputDuration"), "timeline outputDuration")
    if not segments or output_duration != segments[-1]["out_end"]:
        raise ProjectionError("compiled timeline duration is malformed")
    return {"outputDuration": output_duration, "segments": segments}


def timeline_hash_payload(timeline_map: dict) -> dict:
    """Integer hash view that TS and Python serialize identically."""
    return {
        "quantization": "millionths-half-up-v1",
        "outputDuration": _timeline_units(
            timeline_map["outputDuration"], "timeline outputDuration"),
        "segments": [{
            "index": row["index"],
            "source_id": row["source_id"],
            **{field: _timeline_units(
                row[field], f"segment {row['index']} {field}")
               for field in _TIMELINE_FIELDS},
        } for row in timeline_map["segments"]],
    }


def _validate_cut(index: int, cut: object) -> None:
    label = f"cutTrack[{index}]"
    if not isinstance(cut, dict):
        raise ProjectionError(f"{label} must be an object")
    source_id = cut.get("sourceId")
    if not isinstance(source_id, str) or not source_id.strip():
        raise ProjectionError(f"{label}.sourceId must be a non-empty string")
    start = _number(cut.get("start"), f"{label}.start")
    end = _number(cut.get("end"), f"{label}.end")
    speed = _number(cut.get("speed", 1), f"{label}.speed")
    if start < 0:
        raise ProjectionError(f"{label}.start must be zero or greater")
    if end <= start:
        raise ProjectionError(f"{label}.end must be greater than start")
    if speed <= 0:
        raise ProjectionError(f"{label}.speed must be greater than zero")


def _validate_plan(plan: object) -> dict:
    if not isinstance(plan, dict):
        raise ProjectionError("edit plan must be a JSON object")
    track = plan.get("cutTrack")
    if not isinstance(track, list) or not track:
        raise ProjectionError("edit plan cutTrack must be a non-empty array")
    for index, cut in enumerate(track):
        _validate_cut(index, cut)
    decisions = plan.get("cutDecisions")
    if not isinstance(decisions, dict) or decisions.get("schemaVersion") != 1:
        raise ProjectionError("cutDecisions must be a schemaVersion 1 object")
    removals = decisions.get("removals")
    if not isinstance(removals, list) or not all(
            isinstance(row, dict) for row in removals):
        raise ProjectionError("cutDecisions.removals must be an array of objects")
    canonical_json(plan)
    return plan


def build_projection(plan: object, approved_cut_plan_hash: str) -> dict:
    """Compile one deterministic, non-authorizing compatibility projection."""
    if not isinstance(approved_cut_plan_hash, str) \
            or not _SHA256.fullmatch(approved_cut_plan_hash):
        raise ProjectionError(
            "approved cut plan hash must be a lowercase 64-character SHA-256")
    valid_plan = _validate_plan(plan)
    try:
        timeline_map = _normalize_timeline_map(compile_plan(valid_plan).to_dict())
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ProjectionError(f"timeline compilation failed: {exc}") from exc
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": KIND,
        "approvedCutPlanHash": approved_cut_plan_hash,
        "cutTrackDigest": stable_digest(valid_plan["cutTrack"]),
        "cutDecisionsDigest": stable_digest(valid_plan["cutDecisions"]),
        "compilerHash": compiler_hash(),
        "timelineMap": timeline_map,
        "timelineMapHash": stable_digest(timeline_hash_payload(timeline_map)),
    }


def load_plan(path: str) -> dict:
    """Load a JSON edit plan without silently accepting unreadable input."""
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProjectionError(f"edit plan unreadable: {exc}") from exc
    return _validate_plan(value)


def write_projection(path: str, projection: dict) -> None:
    """Write exact canonical bytes; callers choose the shadow-generation path."""
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_json(projection))
            handle.write("\n")
    except OSError as exc:
        raise ProjectionError(f"projection output unwritable: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a P1 compatibility timeline projection")
    parser.add_argument("plan", help="current edit_plan.json")
    parser.add_argument("approved_cut_plan_hash",
                        help="lowercase SHA-256 from approved cut authority")
    parser.add_argument("out", help="shadow projection JSON output")
    args = parser.parse_args(argv)
    try:
        projection = build_projection(
            load_plan(args.plan), args.approved_cut_plan_hash)
        write_projection(args.out, projection)
    except ProjectionError as exc:
        print(canonical_json({"error": str(exc)}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
