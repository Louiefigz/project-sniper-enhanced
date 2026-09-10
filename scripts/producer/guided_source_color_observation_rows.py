"""Pure per-source observation-section joins, not authenticated frame replay.

All hashes and decoded facts remain supplied data. The caller's later raw-file
reader must validate original worker/parent/admission evidence and every frame.
No file, source, callback, clock, renderer or live owner is opened or created.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import PurePosixPath

from color.grade_bt709_identity import Bt709IdentityMetadata
from color.grade_contract import closed, integer, parse_source_binding
from color.grade_observation_geometry import chroma_location
from color.grade_observation_profile import V1, frame_budget, observation_declaration
from color.grade_source_class import _CLOCK_LIMIT, _time_base
from graphics.render_rate import normalize_render_rate
from guided_presenter_read_fingerprint import hold_read_metadata, same_read_metadata
from guided_source_color_staging_contract import _hash, _literal, _path

_SOURCE = {"sourceId", "jobId", "selection", "source", "binding", "artifacts", "records", "bt709Identity", "timing"}
_ARTIFACTS = {"input": ("input.json", 128 * 1024), "implementation": ("implementation.json", 8 * 1024 ** 2),
    "launchClaim": ("launch-claim.json", 128 * 1024), "parents": ("parents.json", 16 * 1024 ** 2),
    "execution": ("execution/execution.json", 16 * 1024 ** 2), "probe": ("execution/result/probe.json", 64 * 1024),
    "frames": ("execution/result/frames.ffprobe", 128 * 1024 ** 2), "observation": ("observation.json", 16 * 1024 ** 2)}
_RECORDS = {"policy", "sha256", "decodedFrames", "firstPts", "timeBase", "stepTicks", "width", "height"}


def same_observation_data(value: object, expected: object) -> None:
    """Compare exact JSON scalar types, not Python bool/int/float equality."""
    if not same_read_metadata(value, hold_read_metadata(expected)):
        raise ValueError("source color observation data differs from its original metadata")


def observation_reference(value: object, path: PurePosixPath, maximum: int) -> dict:
    """Validate an exact bounded raw-ref spelling without authenticating its bytes."""
    row = closed(value, {"path", "sha256", "sizeBytes"}, "observation raw reference")
    if _path(row["path"]) != path:
        raise ValueError("source color observation artifact path differs")
    _hash(row["sha256"])
    integer(row["sizeBytes"], 1, maximum)
    return row


def _artifacts(value: object, job: dict) -> None:
    """Join staged refs exactly; newly emitted refs remain assertions for later IO."""
    row = closed(value, set(_ARTIFACTS), "observation artifacts")
    directory = _path(job["directory"])
    for key, (name, maximum) in _ARTIFACTS.items():
        observation_reference(row[key], directory / name, maximum)
    for key in ("input", "implementation", "launchClaim"):
        same_observation_data(row[key], job[key])


def _source(row: dict, admission: tuple) -> object:
    """Join original manifest/capture metadata, never derive admission from a hash."""
    manifest, entry, snapshot = admission
    source = closed(row["source"], {"path", "sha256", "sizeBytes"}, "observation source")
    integer(source["sizeBytes"], 1, V1.max_source_bytes)
    same_observation_data(source, {"path": snapshot.path, "sha256": snapshot.sha256, "sizeBytes": snapshot.size_bytes})
    binding = parse_source_binding(row["binding"])
    if binding.source_id != row["sourceId"] or binding.source_sha256 != entry["sha256"] \
            or binding.admission_receipt_sha256 != entry["admissionReceiptSha256"] \
            or str(binding.fps) != normalize_render_rate(manifest["frameRate"]).token:
        raise ValueError("source color observation binding differs from original source admission/rate")
    selected = closed(row["selection"], {"profile", "declaration"}, "observation selection")
    if selected["profile"] is not None:
        raise ValueError("source color observation section supports only explicit known V1 identity")
    observation_declaration(selected["declaration"], binding, V1)
    return binding


def _records(value: object, binding: object) -> int:
    """Validate reported exact cadence/count/bounds; full frame replay is still required."""
    row = closed(value, _RECORDS, "observation normalized records")
    _literal(row, {"policy": "sniper-private-grade-frame-records-v2"})
    _hash(row["sha256"])
    count = integer(row["decodedFrames"], 1, V1.max_frames)
    if count != binding.frame_count:
        raise ValueError("source color observation record count differs from its binding")
    raw = row["timeBase"]
    if type(raw) is not str or len(raw) > 19:
        raise ValueError("source color observation timebase is malformed")
    base = _time_base(raw if "/" in raw else raw + "/1")
    if str(base) != raw:
        raise ValueError("source color observation timebase is not its normalized projection")
    step = integer(row["stepTicks"], 1, _CLOCK_LIMIT)
    if binding.fps * base * step != 1:
        raise ValueError("source color observation cadence differs from its original rate")
    first = integer(row["firstPts"], -_CLOCK_LIMIT, _CLOCK_LIMIT)
    integer(first + count * step, -_CLOCK_LIMIT, _CLOCK_LIMIT)
    frame_budget(row["width"], row["height"], count, V1)
    if row["width"] * row["height"] > 33_177_600:
        raise ValueError("source color observation dimensions exceed the original record class")
    return count


def _identity(value: object, count: int) -> None:
    """Validate the separate supplied V1 identity metadata without fabricating V2."""
    row = closed(value, set(Bt709IdentityMetadata.__dataclass_fields__), "observation BT709 identity")
    chroma = chroma_location(row["chroma_location"])
    if chroma == "unavailable":
        raise ValueError("source color observation identity cannot infer missing chroma")
    expected = asdict(Bt709IdentityMetadata("h264", chroma, "1:1", count))
    same_observation_data(row, expected)


def _timing(value: object, source_id: str, elapsed_ms: int) -> tuple[int, int]:
    """Bound reported milliseconds only, not a current work/cleanup allowance."""
    row = closed(value, {"sourceId", "startedMs", "elapsedMs", "status", "cleanupVerified"}, "observation timing")
    _literal(row, {"sourceId": source_id, "status": "complete", "cleanupVerified": True})
    start = integer(row["startedMs"], 0, elapsed_ms)
    duration = integer(row["elapsedMs"], 0, elapsed_ms)
    # The producer rounds offset and duration independently; this is not new time.
    if start + duration > elapsed_ms + 1:
        raise ValueError("source color observation job timing exceeds total elapsed")
    return start, start + duration


def validate_observation_source(value: object, staged: tuple, admission: tuple,
                                elapsed_ms: int) -> tuple[int, int]:
    """Validate one ordered source row, returning only its reported timing interval."""
    row = closed(value, _SOURCE, "source color observation source")
    job, selection = staged
    _literal(row, {"sourceId": job["sourceId"], "jobId": job["jobId"]})
    same_observation_data(row["selection"], selection)
    binding = _source(row, admission)
    _artifacts(row["artifacts"], job)
    _identity(row["bt709Identity"], _records(row["records"], binding))
    return _timing(row["timing"], row["sourceId"], elapsed_ms)
