"""Durable proof that compiled cuts survived through the delivered media.

Pixel scene detectors cannot prove same-camera dialogue splices.  The renderer
therefore seals what it actually executed: the compiled timeline, every encoded
part's exact frame count, their concat, and the downstream base/final bytes.
Work parts may be deleted after the receipt is written; current timeline,
base, final, and assembled-authority bytes are always re-observed at audit.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from cross_runtime_canonical_json import canonical_compact_json
from cut_elementary_proof import ElementaryStream, prove_video_sequence
from fingerprint_io import file_sha256, write_json_atomic
from media_probe import probe_video_frames

MANIFESTATION_NAME = "cut_manifestation.v1.json"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MANIFEST_KEYS = {
    "schemaVersion", "kind", "planCutTrackHash", "timelineMapSha256",
    "frameRate", "parts", "concat", "durationProof", "receiptHash",
}
_PART_KEYS = {
    "index", "sourceId", "srcStart", "srcEnd", "speed", "outStart",
    "outEnd", "partSha256", "partFrames", "videoElementarySha256",
    "videoElementaryBytes",
}


@dataclass(frozen=True)
class ManifestationInputs:
    """Fresh cut-stage artifacts used to seal one manifestation receipt."""

    plan: dict
    timeline_path: str
    part_paths: list[str]
    concat_path: str
    frame_rate: str
    duration_proof: dict


def _object_hash(value: object) -> str:
    """Return a cross-runtime canonical SHA-256 for a JSON value."""
    raw = canonical_compact_json(value).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _receipt_hash(value: dict) -> str:
    """Hash a receipt while excluding its self-referential hash field."""
    return _object_hash({key: item for key, item in value.items()
                         if key != "receiptHash"})


def _read_object(path: str, label: str) -> dict:
    """Read one required JSON object or raise a typed authority error."""
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is missing or unreadable") from exc
    if type(value) is not dict:
        raise ValueError(f"{label} is not a JSON object")
    return value


def _strict(value: dict, keys: set[str], label: str) -> None:
    """Require an exact schema key set."""
    if set(value) != keys:
        raise ValueError(f"{label} has unknown or missing fields")


def _digest(value: object, label: str) -> str:
    """Require and return one lowercase SHA-256 string."""
    if type(value) is not str or not _SHA256.fullmatch(value):
        raise ValueError(f"{label} is not a lowercase SHA-256")
    return value


def _artifact(path: str) -> dict:
    """Observe exact regular-file bytes and video packet count."""
    absolute = os.path.abspath(path)
    target = Path(absolute)
    if target.is_symlink() or not target.is_file():
        raise ValueError("cut-lineage artifact is not a regular file")
    frames = probe_video_frames(absolute)
    if type(frames) is not int or frames <= 0:
        raise ValueError("cut-lineage artifact has no exact video frame count")
    return {"path": absolute, "sha256": file_sha256(absolute),
            "videoFrames": frames}


def _timeline_part(
    segment: dict,
    path: str,
    elementary: ElementaryStream,
) -> dict:
    """Bind one compiled segment to its freshly rendered part."""
    item = _artifact(path)
    return {
        "index": segment["index"], "sourceId": segment["source_id"],
        "srcStart": segment["src_start"], "srcEnd": segment["src_end"],
        "speed": segment["speed"], "outStart": segment["out_start"],
        "outEnd": segment["out_end"], "partSha256": item["sha256"],
        "partFrames": item["videoFrames"],
        "videoElementarySha256": elementary.sha256,
        "videoElementaryBytes": elementary.size_bytes,
    }


def _duration_proof(value: dict, frames: int, parts: int) -> dict:
    """Normalize and verify the cut stage's compiler-duration assertion."""
    keys = {
        "videoDuration", "expectedDuration", "videoFrames", "driftFrames",
        "toleranceFrames", "segments",
    }
    result = {key: value.get(key) for key in keys}
    if result["videoFrames"] != frames or result["segments"] != parts:
        raise ValueError("cut duration proof does not bind the concat")
    numbers = ("videoDuration", "expectedDuration", "driftFrames",
               "toleranceFrames")
    if any(not isinstance(result[key], (int, float))
           or isinstance(result[key], bool)
           or not math.isfinite(float(result[key]))
           or float(result[key]) < 0 for key in numbers) \
            or result["driftFrames"] > result["toleranceFrames"]:
        raise ValueError("cut duration proof exceeds its compiler tolerance")
    return result


def write_manifestation(inputs: ManifestationInputs) -> dict:
    """Seal fresh per-part observations and their exact concatenated output."""
    timeline = _read_object(inputs.timeline_path, "compiled timeline")
    segments = timeline.get("segments")
    if type(segments) is not list or len(segments) != len(inputs.part_paths):
        raise ValueError("compiled timeline does not cover every cut part")
    sequence = prove_video_sequence(inputs.part_paths, inputs.concat_path)
    parts = [_timeline_part(row, path, elementary)
             for row, path, elementary
             in zip(segments, inputs.part_paths, sequence.parts)]
    concat = _artifact(inputs.concat_path)
    if sum(row["partFrames"] for row in parts) != concat["videoFrames"]:
        raise ValueError("exact part frames do not sum to the concat")
    proof = _duration_proof(
        inputs.duration_proof, concat["videoFrames"], len(parts))
    record = {
        "schemaVersion": 1, "kind": "cut-manifestation-v1",
        "planCutTrackHash": _object_hash(inputs.plan.get("cutTrack") or []),
        "timelineMapSha256": file_sha256(inputs.timeline_path),
        "frameRate": inputs.frame_rate, "parts": parts,
        "concat": {"sha256": concat["sha256"],
                   "videoFrames": concat["videoFrames"],
                   "videoElementarySha256": sequence.concat.sha256,
                   "videoElementaryBytes": sequence.concat.size_bytes,
                   "orderedPartsVideoSha256": sequence.ordered_parts.sha256,
                   "orderedPartsVideoBytes": sequence.ordered_parts.size_bytes},
        "durationProof": proof,
    }
    record["receiptHash"] = _receipt_hash(record)
    directory = os.path.dirname(os.path.abspath(inputs.timeline_path))
    write_json_atomic(os.path.join(directory, MANIFESTATION_NAME), record, 2)
    return record


def _expected_part(segment: dict, observed: dict) -> dict:
    """Project a compiled segment into the strict retained part schema."""
    return {
        "index": segment["index"], "sourceId": segment["source_id"],
        "srcStart": segment["src_start"], "srcEnd": segment["src_end"],
        "speed": segment["speed"], "outStart": segment["out_start"],
        "outEnd": segment["out_end"],
        "partSha256": observed.get("partSha256"),
        "partFrames": observed.get("partFrames"),
        "videoElementarySha256": observed.get("videoElementarySha256"),
        "videoElementaryBytes": observed.get("videoElementaryBytes"),
    }


def verify_manifestation(directory: str, plan: dict) -> dict:
    """Verify a sealed receipt against the current plan and timeline bytes."""
    path = os.path.join(directory, MANIFESTATION_NAME)
    record = _read_object(path, "cut manifestation receipt")
    _strict(record, _MANIFEST_KEYS, "cut manifestation receipt")
    if record["schemaVersion"] != 1 or record["kind"] != "cut-manifestation-v1":
        raise ValueError("cut manifestation receipt version is unsupported")
    if _digest(record["receiptHash"], "manifestation receipt hash") \
            != _receipt_hash(record):
        raise ValueError("cut manifestation receipt hash is stale")
    timeline_path = os.path.join(directory, "timeline_map.json")
    timeline = _read_object(timeline_path, "compiled timeline")
    if record["timelineMapSha256"] != file_sha256(timeline_path):
        raise ValueError("cut manifestation does not bind the current timeline")
    if record["planCutTrackHash"] \
            != _object_hash(plan.get("cutTrack") or []):
        raise ValueError("cut manifestation does not bind the current cutTrack")
    _verify_manifest_parts(record, timeline)
    return record


def _verify_manifest_parts(record: dict, timeline: dict) -> None:
    """Require exact compiled-row coverage and a gap-free frame sum."""
    parts, segments = record.get("parts"), timeline.get("segments")
    if type(parts) is not list or type(segments) is not list \
            or len(parts) != len(segments) or not parts:
        raise ValueError("cut manifestation part coverage is invalid")
    for index, (part, segment) in enumerate(zip(parts, segments)):
        if type(part) is not dict:
            raise ValueError(f"cut manifestation part {index} is malformed")
        _strict(part, _PART_KEYS, f"cut manifestation part {index}")
        _digest(part["partSha256"], f"cut manifestation part {index} hash")
        _digest(
            part["videoElementarySha256"],
            f"cut manifestation part {index} elementary hash")
        if type(part["partFrames"]) is not int or part["partFrames"] <= 0 \
                or type(part["videoElementaryBytes"]) is not int \
                or part["videoElementaryBytes"] <= 0 \
                or part != _expected_part(segment, part):
            raise ValueError(f"cut manifestation part {index} is stale")
    concat = record.get("concat")
    concat_keys = {
        "sha256", "videoFrames", "videoElementarySha256",
        "videoElementaryBytes", "orderedPartsVideoSha256",
        "orderedPartsVideoBytes",
    }
    if type(concat) is not dict or set(concat) != concat_keys:
        raise ValueError("cut manifestation concat is malformed")
    _digest(concat["sha256"], "cut manifestation concat hash")
    _digest(concat["videoElementarySha256"], "concat elementary hash")
    _digest(concat["orderedPartsVideoSha256"], "ordered parts video hash")
    frames = sum(part["partFrames"] for part in parts)
    elementary_bytes = sum(part["videoElementaryBytes"] for part in parts)
    sequence_equal = (
        concat["videoElementarySha256"]
        == concat["orderedPartsVideoSha256"]
        and concat["videoElementaryBytes"] == concat["orderedPartsVideoBytes"]
        and concat["orderedPartsVideoBytes"] == elementary_bytes
    )
    if concat["videoFrames"] != frames or not sequence_equal:
        raise ValueError("cut manifestation part frames do not cover the concat")
    proof = _duration_proof(
        record.get("durationProof") or {}, frames, len(parts))
    _verify_clock(record.get("frameRate"), timeline, proof, frames)


def _verify_clock(
    raw_rate: object,
    timeline: dict,
    proof: dict,
    frames: int,
) -> None:
    """Tie rounded duration evidence to the rational frame clock."""
    try:
        rate = Fraction(str(raw_rate))
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise ValueError("cut manifestation frame rate is invalid") from exc
    expected = timeline.get("outputDuration")
    if rate <= 0 or not isinstance(expected, (int, float)) \
            or isinstance(expected, bool) \
            or not math.isfinite(float(expected)) \
            or (abs(float(proof["expectedDuration"]) - float(expected)) > 1e-6
                and proof["expectedDuration"] != round(float(expected), 4)):
        raise ValueError("cut duration proof does not bind timeline duration")
    video_s = frames / float(rate)
    drift = abs(frames - float(expected) * float(rate))
    if abs(float(proof["videoDuration"]) - video_s) > 0.00011 \
            or abs(float(proof["driftFrames"]) - drift) > 0.0011:
        raise ValueError("cut duration proof does not bind exact frame clock")


def manifestation_matches_concat(
    directory: str,
    plan: dict,
    concat_path: str,
) -> bool:
    """Whether a resumable concat is exactly the one the receipt sealed."""
    try:
        record = verify_manifestation(directory, plan)
        observed = _artifact(concat_path)
        return (record["concat"]["sha256"] == observed["sha256"]
                and record["concat"]["videoFrames"] == observed["videoFrames"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
