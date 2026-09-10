"""Honest Palmier projection/readback disposition for P2 cut repair."""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from compile_timeline import compile_plan
from edit.exact_timing import PositiveRational
from edit.picture_lock_common import content_hash
from palmier.desktop_ledger import clip_frames, clip_inventory
from palmier.mcp_client import PalmierError


@dataclass(frozen=True)
class PalmierRepairProjectionInput:
    """Inputs to the non-mutating cut-repair adapter decision."""

    operation: dict[str, object]
    operation_hash: str
    child_cut_track: tuple[dict[str, object], ...]
    fps: PositiveRational
    selected: bool
    retime: dict[str, object]


def _sample_range(value: object, label: str) -> dict[str, int]:
    if not isinstance(value, dict) or set(value) != {
            "startSample", "endSampleExclusive"}:
        raise PalmierError(f"{label} is not a closed sample range")
    start, end = value["startSample"], value["endSampleExclusive"]
    if type(start) is not int or type(end) is not int \
            or start < 0 or end <= start:
        raise PalmierError(f"{label} is not a valid sample range")
    return {"startSample": start, "endSampleExclusive": end}


def _retime(item: PalmierRepairProjectionInput) -> dict[str, object]:
    row = item.retime
    keys = {
        "requestedSpeed", "sourceSampleRange", "sourceSampleRate",
        "normalizedSourceSampleRange", "outputSamples", "effectiveRatio",
    }
    if not isinstance(row, dict) or set(row) != keys:
        raise PalmierError("Palmier repair retime is not closed")
    try:
        requested = PositiveRational.from_value(row["requestedSpeed"])
        effective = PositiveRational.from_value(row["effectiveRatio"])
        operation_speed = PositiveRational.from_value(
            item.operation.get("speed"))
    except (TypeError, ValueError) as exc:
        raise PalmierError("Palmier repair retime speed is not canonical") from exc
    source = _sample_range(row["sourceSampleRange"], "retime source range")
    normalized = _sample_range(
        row["normalizedSourceSampleRange"], "retime normalized range")
    source_rate, output = row["sourceSampleRate"], row["outputSamples"]
    if type(source_rate) is not int or source_rate < 1 \
            or type(output) is not int or output < 1 \
            or requested != operation_speed \
            or source != item.operation.get("sourceExtension") \
            or source_rate != item.operation.get("sourceSampleRate") \
            or output != item.operation.get("extensionOutputSamples") \
            or Fraction(
                normalized["endSampleExclusive"]
                - normalized["startSample"], output) != effective.fraction:
        raise PalmierError("Palmier repair retime disagrees with renderer authority")
    return {
        "requestedSpeed": requested.to_dict(),
        "sourceSampleRange": source,
        "sourceSampleRate": source_rate,
        "normalizedSourceSampleRange": normalized,
        "outputSamples": output,
        "effectiveRatio": effective.to_dict(),
    }


def _validate(item: PalmierRepairProjectionInput) -> str:
    operation = item.operation
    if operation.get("schemaVersion") != 1 \
            or operation.get("operation") != "cut.restoreSpeech" \
            or content_hash(operation) != item.operation_hash:
        raise PalmierError("Palmier cut repair operation binding is invalid")
    method = operation.get("method")
    if method not in {"audio-lj-overlap", "extend-and-reclaim-silence"}:
        raise PalmierError("Palmier cut repair method is unsupported")
    try:
        PositiveRational.from_value(operation.get("speed"))
    except (TypeError, ValueError) as exc:
        raise PalmierError("Palmier cut repair speed is not canonical") from exc
    if not item.child_cut_track:
        raise PalmierError("Palmier cut repair has no child cut track")
    _retime(item)
    return str(method)


def _expected_cuts(item: PalmierRepairProjectionInput) -> list[dict]:
    plan = {"cutTrack": list(item.child_cut_track)}
    try:
        segments = compile_plan(plan).segments
    except (KeyError, TypeError, ValueError) as exc:
        raise PalmierError(f"Palmier child cut track is invalid: {exc}") from exc
    fps = item.fps.numerator
    return [{
        "sourceId": segment.source_id,
        "source": [segment.src_start, segment.src_end],
        "frames": [
            round(segment.out_start * fps),
            round(segment.out_end * fps),
        ],
        "speed": segment.speed,
    } for segment in segments]


def _unsupported_reason(
    item: PalmierRepairProjectionInput,
    method: str,
) -> str | None:
    if method == "audio-lj-overlap":
        return "Palmier exposes no sample-exact L/J overlap plus dialogue readback"
    if item.fps.denominator != 1:
        return (
            "Palmier rounds fractional project FPS and cannot prove exact "
            "repair frames"
        )
    sources = {
        row.get("sourceId") for row in item.child_cut_track
        if isinstance(row, dict)
    }
    if len(sources) != 1:
        return (
            "current Palmier cut reconstruction does not qualify "
            "multi-source repair"
        )
    return None


def _selected_disposition(
    item: PalmierRepairProjectionInput,
    status: str,
    reason: str,
    expected: list[dict] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schemaVersion": 1,
        "kind": "palmier-cut-repair-disposition",
        "selected": True,
        "operationHash": item.operation_hash,
        "nativeStatus": status,
        "deliveryDisposition": "baked-exact-master",
        "sampleExact": False,
        "repairSpeed": item.operation["speed"],
        "repairRetime": _retime(item),
        "reason": reason,
        "requiresRepairFragmentImport": True,
    }
    if expected is not None:
        payload.update({
            "expectedCuts": expected,
            "expectedTotalFrames": expected[-1]["frames"][1],
        })
    return {**payload, "projectionHash": content_hash(payload)}


def project_cut_repair(
    item: PalmierRepairProjectionInput,
) -> dict[str, object]:
    """Return a disposition without touching Palmier when it is unselected."""
    method = _validate(item)
    if not item.selected:
        return {
            "schemaVersion": 1,
            "kind": "palmier-cut-repair-disposition",
            "selected": False,
            "operationHash": item.operation_hash,
            "nativeStatus": "skipped",
            "deliveryDisposition": "local-exact-only",
            "reason": "Palmier was not selected; zero Palmier calls are authorized",
        }
    unsupported = _unsupported_reason(item, method)
    if unsupported is not None:
        return _selected_disposition(
            item, "unsupported", unsupported)
    expected = _expected_cuts(item)
    return _selected_disposition(
        item,
        "frame-exact-unqualified",
        "picture frames are projectable; source-sample dialogue readback is absent",
        expected,
    )


def _track_zero(timeline: dict) -> list[dict]:
    tracks = timeline.get("tracks")
    if not isinstance(tracks, list) or not tracks \
            or not isinstance(tracks[0], dict):
        raise PalmierError("Palmier repair readback has no base track")
    rows = [row for row in tracks[0].get("clips") or []
            if isinstance(row, dict) and row.get("mediaType") != "audio"]
    return sorted(rows, key=lambda row: clip_frames(row) or (-1, -1))


def _assert_expected(expected: list[dict], actual: list[dict]) -> None:
    if len(expected) != len(actual):
        raise PalmierError("Palmier repair base clip count changed")
    for wanted, observed in zip(expected, actual, strict=True):
        if clip_frames(observed) != tuple(wanted["frames"]) \
                or observed.get("source") != wanted["source"] \
                or float(observed.get("speed", 1.0)) != wanted["speed"]:
            raise PalmierError("Palmier repair cut readback does not match")


def _unrelated(timeline: dict) -> dict[str, dict]:
    return {ident: {key: value for key, value in row.items()
                    if key != "_trackIndex"}
            for ident, row in clip_inventory(timeline).items()
            if row.get("_trackIndex") != 0}


def verify_cut_repair_readback(
    disposition: dict[str, object],
    before: dict,
    after: dict,
) -> dict[str, object]:
    """Prove the supported frame subset and preserve unrelated inventory."""
    if disposition.get("nativeStatus") != "frame-exact-unqualified":
        raise PalmierError("Palmier native repair is not qualified for mutation")
    if after.get("totalFrames") != disposition.get("expectedTotalFrames"):
        raise PalmierError("Palmier repair total frame readback drifted")
    expected = disposition.get("expectedCuts")
    if not isinstance(expected, list):
        raise PalmierError("Palmier repair projection lacks expected cuts")
    _assert_expected(expected, _track_zero(after))
    if _unrelated(before) != _unrelated(after):
        raise PalmierError("Palmier repair changed unrelated clip inventory")
    proof = {
        "schemaVersion": 1,
        "kind": "palmier-cut-repair-readback",
        "operationHash": disposition["operationHash"],
        "projectionHash": disposition["projectionHash"],
        "totalFrames": after["totalFrames"],
        "baseClipCount": len(expected),
        "unrelatedInventoryPreserved": True,
        "sampleExact": False,
        "deliveryDisposition": "baked-exact-master",
    }
    return {**proof, "readbackHash": content_hash(proof)}
