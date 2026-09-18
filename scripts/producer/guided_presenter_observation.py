"""Owned bounded selected-picture observations, not admission or render approval."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from cut_preview_io import real_directory
from graphics.presenter_layout_contract import PresenterGeometry, presenter_identifier
from graphics.presenter_layout_geometry import revalidate_presenter_geometry
from graphics.presenter_layout_graph import PresenterGraphAsset
from guided_presenter_assets import PresenterAssetAdmission, SelectedPresenterAsset, _expected
from guided_presenter_png import PresenterPngMetadata, inspect_presenter_png, validate_presenter_png_metadata
from guided_presenter_probe_contract import (
    MAX_FRAME_BYTES, MAX_HEADER_BYTES, canonical_presenter_rate, finish_presenter_probe,
    observed_graph_asset, probe_document, read_presenter_header, validate_presenter_frames,
)
from guided_presenter_probe_identity import (
    HeldPresenterProbeFile, PresenterObservationRuntime, PresenterProbePin, _validate_reference,
    observation_remaining, probe_deadline_remaining,
)
from headless.process_runner import ProcessRequest, run_text

_ENVIRONMENT = {"LANG": "C", "LC_ALL": "C", "TZ": "UTC", "AV_LOG_FORCE_NOCOLOR": "1"}
_FRAME_FIELDS = ("media_type,stream_index,pts,best_effort_timestamp,duration,width,height,pix_fmt,"
    "sample_aspect_ratio,interlaced_frame,repeat_pict,color_range,color_space,color_primaries,color_transfer")


@dataclass(frozen=True)
class PresenterProbeEvidence:
    """Retained actual bounded stdout/commands, not serialized execution authority."""
    requested_frame_rate: str
    graph_frame_rate: str
    header_json: str
    frames_json: str
    commands: tuple[tuple[str, ...], ...]
    command_sha256: tuple[str, ...]
    png_metadata: PresenterPngMetadata | None


@dataclass(frozen=True)
class ObservedPresenterAsset:
    """One live observation; source bytes remain under the calling admission owner."""
    graph_asset: PresenterGraphAsset
    admission: PresenterAssetAdmission
    source: HeldPresenterProbeFile
    ffprobe: HeldPresenterProbeFile
    evidence: PresenterProbeEvidence
    policy: ClassVar[str] = "selected-presenter-picture-observation-v1"
    scope: ClassVar[str] = "caller-held-picture-metadata-not-admission-render-rights-or-approval"
    executable: ClassVar[bool] = False
    rights_verified: ClassVar[bool] = False


def _command_hash(command: tuple[str, ...]) -> str:
    """Bind the exact argv spelling without shell execution or path interpolation."""
    return hashlib.sha256(json.dumps(command, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


def _commands(source: str, tool: str, kind: str) -> tuple[tuple[str, ...], ...]:
    """Restrict local demuxers/protocols and preserve every decoded picture to EOF."""
    common = (tool, "-v", "warning", "-threads", "1", "-err_detect", "crccheck+explode",
        "-protocol_whitelist", "file", "-probesize", "1048576", "-analyzeduration", "1000000")
    formats = ("-f", "png_pipe") if kind == "still-image" else ("-format_whitelist", "mov,matroska")
    output = ("-show_error", "-show_streams", "-show_format", "-of", "json=compact=1")
    header = (*common, *formats, *output, source)
    frames = (*common, *formats, "-select_streams", "v:0", "-count_frames", "-show_frames",
        "-show_entries", f"frame={_FRAME_FIELDS}:frame_tags:frame_side_data:stream:format", *output, source)
    return header, frames


def _bound_admission(value: PresenterAssetAdmission, source: HeldPresenterProbeFile) -> None:
    """Never manufacture a current-path hash or accept an unrelated admitted asset."""
    if type(value) is not PresenterAssetAdmission or type(source) is not HeldPresenterProbeFile:
        raise ValueError("Presenter observation requires exact selected admission and caller-held source")
    _validate_reference(source, False)
    presenter_identifier(value.asset_id)
    if (value.lane not in ("source", "broll") or value.media_kind not in ("still-image", "timed-media")
            or (value.snapshot_path, value.source_sha256, value.source_size_bytes)
            != (source.path, source.sha256, source.size_bytes) or type(value.source_size_bytes) is not int):
        raise ValueError("Presenter observation source differs from the selected admitted byte identity")
    _expected({"kind": "image" if value.media_kind == "still-image" else "video",
        "sourceSizeBytes": value.source_size_bytes, "sourceSha256": value.source_sha256,
        "originalPath": value.original_path, "path": value.snapshot_path,
        "admissionReceiptPath": value.receipt_path, "admissionReceiptSha256": value.receipt_sha256})


def _current(pins: tuple[PresenterProbePin, ...], runtime: PresenterObservationRuntime) -> float:
    """Run external callbacks first, then compare every held inode before any return."""
    remaining = observation_remaining(runtime)
    for pin in pins:
        pin.assert_current()
    return min(remaining, probe_deadline_remaining(runtime))


def _run(command: tuple[str, ...], pins: tuple[PresenterProbePin, ...],
         runtime: PresenterObservationRuntime, maximum: int) -> str:
    """Use existing byte-capped group ownership; stderr/warnings are not suppressed."""
    seconds = _current(pins, runtime)
    result = run_text(ProcessRequest(command, "", runtime.working_directory, dict(_ENVIRONMENT),
        seconds, termination_grace_seconds=1, max_output_bytes=maximum))
    _current(pins, runtime)
    if result.returncode != 0 or result.stderr:
        raise ValueError("Presenter actual ffprobe failed or reported unsupported diagnostics: " + result.stderr[-1200:])
    return result.stdout


def _selected(value: SelectedPresenterAsset, source: HeldPresenterProbeFile) -> None:
    """Validate shape and original source binding without rerunning source-set hashes."""
    if type(value) is not SelectedPresenterAsset or type(value.geometry) is not PresenterGeometry:
        raise ValueError("Presenter observation requires its exact selected geometry")
    if type(value.operation_index) is not int or not 0 <= value.operation_index <= 127:
        raise ValueError("Presenter observation operation index is invalid")
    revalidate_presenter_geometry(value.geometry)
    _bound_admission(value.admission, source)
    if value.geometry.declaration.asset_id != value.admission.asset_id:
        raise ValueError("Presenter geometry and selected admission asset IDs differ")


def _observe(selected: SelectedPresenterAsset, pins: tuple[PresenterProbePin, ...],
             rate: str, runtime: PresenterObservationRuntime) -> ObservedPresenterAsset:
    """Observe metadata, then every frame, under the same original source/tool holds."""
    source, tool = pins
    commands = _commands(source.value.path, tool.value.path, selected.admission.media_kind)
    png = inspect_presenter_png(source) if selected.admission.media_kind == "still-image" else None
    header_raw = _run(commands[0], pins, runtime, MAX_HEADER_BYTES)
    header = read_presenter_header(probe_document(header_raw, MAX_HEADER_BYTES), selected.admission.media_kind, rate)
    if png is not None and (header.width, header.height) != (png.width, png.height):
        raise ValueError("Presenter PNG container and decoded stream dimensions disagree")
    frames_raw = _run(commands[1], pins, runtime, MAX_FRAME_BYTES)
    frames = probe_document(frames_raw, MAX_FRAME_BYTES)
    asset = finish_presenter_probe(selected, header, frames, lambda: probe_deadline_remaining(runtime))
    evidence = PresenterProbeEvidence(rate, canonical_presenter_rate(rate), header_raw, frames_raw,
        commands, tuple(_command_hash(command) for command in commands), png)
    result = ObservedPresenterAsset(asset, selected.admission, source.value, tool.value, evidence)
    _current(pins, runtime)
    return result


def observe_presenter_asset(selected: SelectedPresenterAsset, source: HeldPresenterProbeFile,
                            frame_rate: str, runtime: PresenterObservationRuntime) -> ObservedPresenterAsset:
    """Acquire live bounded metadata while borrowing original authority and deadline.

    One actual full decode may be reused by the owner for repeated occurrences;
    each occurrence still requires its own exact geometry/offset/coverage check.
    No renderer, source-set verifier, rights decision or human approval is called.
    """
    observation_remaining(runtime)
    _selected(selected, source)
    canonical_presenter_rate(frame_rate)
    real_directory(Path(runtime.working_directory))
    with PresenterProbePin(source, runtime) as source_pin, PresenterProbePin(runtime.ffprobe, runtime, True) as tool_pin:
        return _observe(selected, (source_pin, tool_pin), frame_rate, runtime)


def validate_presenter_observation(value: ObservedPresenterAsset, guard: Callable[[], None] | None = None) -> None:
    """Reparse immutable retained evidence only; this grants no cold execution authority."""
    if guard is not None and not callable(guard):
        raise ValueError("Presenter evidence revalidation guard must be callable")
    check = guard if guard is not None else lambda: None
    check()
    if type(value) is not ObservedPresenterAsset or type(value.evidence) is not PresenterProbeEvidence:
        raise ValueError("Presenter observation has the wrong actual typed result")
    _bound_admission(value.admission, value.source)
    _validate_reference(value.ffprobe, True)
    evidence = value.evidence
    if canonical_presenter_rate(evidence.requested_frame_rate) != evidence.graph_frame_rate:
        raise ValueError("Presenter observation requested/graph clocks differ")
    expected = _commands(value.source.path, value.ffprobe.path, value.admission.media_kind)
    if evidence.commands != expected or evidence.command_sha256 != tuple(_command_hash(command) for command in expected):
        raise ValueError("Presenter observation exact commands differ from its held sources")
    header = read_presenter_header(probe_document(evidence.header_json, MAX_HEADER_BYTES),
                                  value.admission.media_kind, evidence.requested_frame_rate)
    check()
    frames = probe_document(evidence.frames_json, MAX_FRAME_BYTES)
    check()
    count = validate_presenter_frames(header, frames, check)
    if value.graph_asset != observed_graph_asset(value.admission, header, count):
        raise ValueError("Presenter observation graph metadata differs from retained decoded evidence")
    png = evidence.png_metadata
    if header.kind == "still-image" and (type(png) is not PresenterPngMetadata or (png.width, png.height) != (header.width, header.height)):
        raise ValueError("Presenter still lacks its held PNG metadata observation")
    if png is not None:
        validate_presenter_png_metadata(png, value.source.size_bytes)
    if header.kind != "still-image" and png is not None:
        raise ValueError("Presenter video contains transplanted PNG observation metadata")
    check()
