"""Exact private PCM excerpts of one already-qualified full-program master.

This is audio-only evidence. It creates no browser video, independent loudness
target, fade, opening approval, delivered final, or active render graph.
"""
from __future__ import annotations

import os
import stat
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from audio.program_audio_clock import exact_float_audio_clock
from audio.program_master_selection import HeldMasterSelection, revalidate_master_selection
from audio.render_audio_authority import run_audio
from cut_preview_io import bound_json, digest, file_hash, real_directory, write_new
from render_effect_discovery import local_python_import_closure

SAMPLE_CLOCK_POLICY = "absolute-frame-ties-even-48000-v1"
SCOPE = "full-program-master-excerpt-not-opening-or-delivery-approval"


@dataclass(frozen=True)
class ExcerptRanges:
    """Server-bound absolute half-open frames, never rounded local durations."""

    core: tuple[int, int]
    review: tuple[int, int]
    execution_input_hash: str


def sample_range(frames: tuple[int, int], clock: tuple[str, int]) -> dict:
    """Round each absolute Fraction endpoint ties-to-even before subtracting."""
    frame_rate, total_frames = clock
    if type(frames) is not tuple or len(frames) != 2 \
            or any(type(value) is not int for value in frames) \
            or type(total_frames) is not int or not 0 <= frames[0] < frames[1] <= total_frames:
        raise ValueError("opening audio frames are not a bounded half-open range")
    try:
        rate = Fraction(frame_rate) if type(frame_rate) is str else Fraction(0)
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError("opening audio frame rate is malformed") from error
    if rate <= 0:
        raise ValueError("opening audio frame rate must be positive")
    start, end = (round(Fraction(frame * 48000, 1) / rate) for frame in frames)
    if end <= start:
        raise ValueError("opening audio range contains no presented sample")
    return {"startFrame": frames[0], "endFrameExclusive": frames[1],
        "startSample": start, "endSampleExclusive": end, "samples": end - start}


def excerpt_implementation() -> list[dict]:
    """Bind the actual extraction/selection/CLI source closure."""
    root = Path(__file__).resolve().parents[1]
    paths = local_python_import_closure([Path(__file__), root / "guided_opening_audio.py"])
    return [{"path": str(path), "sha256": file_hash(path)} for path in sorted(set(paths))]


def _owned_directory(path: Path) -> None:
    """Refuse a linked/shared directory both before creation and later readback."""
    real_directory(path)
    info = path.lstat()
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise RuntimeError("opening audio requires a private owned directory")


def _directory(path: Path) -> None:
    """Refuse to overwrite existing artifacts, even in a previously private run."""
    _owned_directory(path)
    if list(path.iterdir()):
        raise RuntimeError("opening audio requires a new empty private owned directory")


def _trim(span: dict) -> str:
    """Select exact PCM samples and reset transport PTS without changing content."""
    return (f"atrim=start_sample={span['startSample']}:end_sample={span['endSampleExclusive']},"
            "asetpts=N/SR/TB")


def _pcm_hash(path: str, context: tuple[str, dict | None]) -> str:
    """Strictly decode all selected PCM to prove exact sample content."""
    ffmpeg, span = context
    command = [ffmpeg, "-nostdin", "-v", "error", "-xerror", "-err_detect", "explode", "-i", path,
               "-map", "0:a:0"]
    if span is not None:
        command += ["-af", _trim(span)]
    raw = run_audio(command + ["-c:a", "pcm_f32le", "-f", "hash", "-hash", "sha256", "-"])
    value = raw.decode("ascii").strip()
    if not value.startswith("SHA256=") or len(value) != 71:
        raise RuntimeError("opening audio PCM hash was not fully observed")
    return value[7:]


def _extract(selection: HeldMasterSelection, target: Path, span: dict) -> dict:
    """Execute the real float sample trim; no loudnorm, gain, resample or fades."""
    master = selection.master
    tools = master.source_bus.admission.tools
    ffmpeg = tools["ffmpeg"]["path"]
    run_audio([ffmpeg, "-nostdin", "-v", "error", "-xerror", "-err_detect", "explode", "-n",
        "-i", master.path, "-map", "0:a:0", "-af", _trim(span), "-c:a", "pcm_f32le", str(target)])
    before = file_hash(target)
    clock = exact_float_audio_clock(str(target), tools["ffprobe"]["path"], span["samples"])
    expected = _pcm_hash(master.path, (ffmpeg, span))
    observed = _pcm_hash(str(target), (ffmpeg, None))
    if observed != expected or file_hash(target) != before:
        raise RuntimeError("opening audio excerpt differs from exact full-master sample range")
    return {**span, "path": str(target), "sha256": before, "sizeBytes": target.stat().st_size,
        "pcmSha256": observed, "sourceRangePcmSha256": expected, **clock,
        "audioDecodeSucceeded": True, "exactFullMasterPcm": True}


def _ranges(selection: HeldMasterSelection, ranges: ExcerptRanges, directory: Path,
            guard: Callable[[], None]) -> dict:
    """Core/review may reuse identical proved bytes, never approximate subsets."""
    if type(ranges.execution_input_hash) is not str or len(ranges.execution_input_hash) != 64 \
            or any(char not in "abcdef0123456789" for char in ranges.execution_input_hash):
        raise ValueError("opening audio input hash is invalid")
    bus = selection.master.source_bus
    core = sample_range(ranges.core, (bus.frame_rate, bus.frames))
    review = sample_range(ranges.review, (bus.frame_rate, bus.frames))
    if ranges.review[0] > ranges.core[0] or ranges.review[1] < ranges.core[1]:
        raise ValueError("opening review range must contain its core")
    guard()
    result = {"core": _extract(selection, directory / "core.wav", core)}
    guard()
    result["review"] = (dict(result["core"]) if core == review
                        else _extract(selection, directory / "review.wav", review))
    guard()
    return result


def _unchanged(spans: dict) -> None:
    """Require the exact extracted bytes through receipt publication."""
    for span in spans.values():
        path = Path(span["path"])
        if file_hash(path) != span["sha256"] or path.stat().st_size != span["sizeBytes"]:
            raise RuntimeError("opening audio bytes changed before receipt publication")


def _failed(directory: Path, error: Exception) -> None:
    """Retain failure without hiding the original cause if persistence also fails."""
    try:
        write_new(directory / "audio-failed.json", {"schemaVersion": 1,
            "kind": "guided-opening-audio-failed", "scope": SCOPE, "status": "failed",
            "error": str(error), "cleanupScope": "synchronous-audio-child-only",
            "outerProcessGroupCleanup": "requires-owned-runner-observation",
            "openingApproved": False, "deliveryApproved": False})
    except (OSError, RuntimeError) as persistence_error:
        error.add_note(f"Could not persist private audio failure: {persistence_error}")


def extract_master_audio(selection: HeldMasterSelection, ranges: ExcerptRanges,
                         directory: Path, guard: Callable[[], None]) -> dict:
    """Publish only a private exact-range receipt after rechecking global inputs."""
    _directory(directory)
    try:
        guard()
        revalidate_master_selection(selection)
        implementation = excerpt_implementation()
        spans = _ranges(selection, ranges, directory, guard)
        if implementation != excerpt_implementation():
            raise RuntimeError("opening audio implementation changed during extraction")
        master = selection.master
        body = {"schemaVersion": 1, "kind": "guided-opening-audio-result", "scope": SCOPE,
            "status": "complete", "executionInputHash": ranges.execution_input_hash,
            "selectionEventPath": str(selection.context.event_path), "selectionEventHash": selection.event_sha256,
            "programMasterReceiptHash": master.receipt["receiptHash"],
            "audioProgramInputHash": master.receipt["audioProgramInputHash"],
            "sourceBusReceiptHash": master.source_bus.receipt["receiptHash"],
            "sampleClockPolicy": SAMPLE_CLOCK_POLICY, "frameRate": master.source_bus.frame_rate,
            "totalFrames": master.source_bus.frames, "implementation": implementation,
            "tools": master.source_bus.admission.tools, "core": spans["core"], "review": spans["review"],
            "normalizationApplied": False, "fadesApplied": False,
            "browserMedia": False, "openingApproved": False, "deliveryApproved": False}
        guard()
        revalidate_master_selection(selection)
        _unchanged(spans)
        record = {**body, "receiptHash": digest(body)}
        write_new(directory / "audio-result.json", record)
        guard()
        _unchanged(spans)
        return record
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        _failed(directory, error)
        raise


def _read_identity(record: dict, selection: HeldMasterSelection) -> None:
    """Bind current whole-program selection and exact role, not a loose media path."""
    master = selection.master
    expected = {"schemaVersion": 1, "kind": "guided-opening-audio-result", "scope": SCOPE,
        "status": "complete", "selectionEventPath": str(selection.context.event_path),
        "selectionEventHash": selection.event_sha256, "programMasterReceiptHash": master.receipt["receiptHash"],
        "audioProgramInputHash": master.receipt["audioProgramInputHash"],
        "sourceBusReceiptHash": master.source_bus.receipt["receiptHash"],
        "sampleClockPolicy": SAMPLE_CLOCK_POLICY, "frameRate": master.source_bus.frame_rate,
        "totalFrames": master.source_bus.frames, "implementation": excerpt_implementation(),
        "tools": master.source_bus.admission.tools, "normalizationApplied": False, "fadesApplied": False,
        "browserMedia": False, "openingApproved": False, "deliveryApproved": False}
    if set(record) != set(expected) | {"executionInputHash", "core", "review", "receiptHash"} \
            or any(type(record[key]) is not type(value) or record[key] != value for key, value in expected.items()):
        raise RuntimeError("opening audio result role, current selection or implementation differs")
    value = record["executionInputHash"]
    if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise RuntimeError("opening audio execution input hash is malformed")


def _read_span(span: dict, context: tuple[Path, HeldMasterSelection]) -> None:
    """Observe held exact float bytes/clock without remastering or a second trim."""
    directory, selection = context
    if type(span) is not dict or type(span.get("path")) is not str:
        raise RuntimeError("opening audio span is malformed")
    path = Path(span["path"])
    if path.parent != directory or path.name not in {"core.wav", "review.wav"}:
        raise RuntimeError("opening audio span escaped its private directory")
    if file_hash(path) != span.get("sha256"):
        raise RuntimeError("opening audio span bytes changed before decoder readback")
    bus = selection.master.source_bus
    frames = sample_range((span.get("startFrame"), span.get("endFrameExclusive")), (bus.frame_rate, bus.frames))
    clock = exact_float_audio_clock(str(path), bus.admission.tools["ffprobe"]["path"], frames["samples"])
    expected = {**frames, **clock, "audioDecodeSucceeded": True, "exactFullMasterPcm": True}
    if set(span) != set(expected) | {"path", "sha256", "sizeBytes", "pcmSha256", "sourceRangePcmSha256"} \
            or any(type(span[key]) is not type(value) or span[key] != value for key, value in expected.items()) \
            or span["pcmSha256"] != span["sourceRangePcmSha256"]:
        raise RuntimeError("opening audio span is not its exact observed full-master range")
    _unchanged({"span": span})


def read_master_audio(directory: Path, expected_hash: str, selection: HeldMasterSelection) -> dict:
    """Require separately held successful return; failed or self-selected files cannot qualify.

The expected hash must come from the successful owned invocation, not this file.
Recheck again under the caller's actual current project/source lease before use.
"""
    _owned_directory(directory)
    if os.path.lexists(directory / "audio-failed.json"):
        raise RuntimeError("opening audio attempt failed; on-disk result is not successful execution")
    path = directory / "audio-result.json"
    before = file_hash(path)
    record = bound_json(path, before)
    body = {key: value for key, value in record.items() if key != "receiptHash"}
    if record.get("receiptHash") != expected_hash or digest(body) != expected_hash:
        raise RuntimeError("opening audio result differs from held successful execution")
    revalidate_master_selection(selection)
    _read_identity(record, selection)
    _read_span(record["core"], (directory, selection))
    if record["review"] != record["core"]:
        _read_span(record["review"], (directory, selection))
    core, review = record["core"], record["review"]
    if review["startFrame"] > core["startFrame"] or review["endFrameExclusive"] < core["endFrameExclusive"]:
        raise RuntimeError("opening audio review does not contain the core")
    if file_hash(path) != before or os.path.lexists(directory / "audio-failed.json"):
        raise RuntimeError("opening audio execution changed during readback")
    return record
