"""Closed presenter inputs for the shared prefix oracle, not source authority.

The actual execution owner supplies the graph and separately verified files.
This module preserves original geometry and only selects whole global windows;
neither frozen types nor these projections establish admission or approval.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
import hashlib
from pathlib import Path
from typing import Protocol

from graphics.presenter_layout_contract import declaration_payload
from graphics.presenter_layout_graph import PresenterGraphSpec, validate_presenter_graph
from guided_presenter_probe_contract import canonical_presenter_rate
from guided_presenter_observation import ObservedPresenterAsset, PresenterProbeEvidence, validate_presenter_observation
from guided_presenter_probe_identity import HeldPresenterProbeFile
from guided_presenter_png import PresenterPngMetadata
from cut_preview_io import real_directory
from opening_prefix_contract import (CompositorPrefixRequest, HeldPrefixInput, MAX_CLIPS,
                                     PrefixOracleError, PrefixOracleRuntime, _identity, canonical_hash)


class PresenterPrefixDeadline(Protocol):
    """Either existing oracle or composition clock; no new start or allowance."""

    def remaining(self) -> float:
        """Require original unexpired remaining seconds."""
        ...


@dataclass(frozen=True)
class PrefixPresenterGraphs:
    """Actual full graph, unchanged opening selection and distinct held assets."""

    full: PresenterGraphSpec
    opening: PresenterGraphSpec | None
    assets: tuple[HeldPrefixInput, ...]
    observations: tuple[ObservedPresenterAsset, ...]
    guard: Callable[[], None]


def validate_presenter_request(request: CompositorPrefixRequest) -> tuple[HeldPrefixInput, ...]:
    """Check exact graph/clock/inventory relationships before hashes or processes."""
    value = request.presenter
    if value is None:
        return ()
    if type(value) is not PrefixPresenterGraphs or type(value.assets) is not tuple \
            or type(value.observations) is not tuple or not callable(value.guard):
        raise PrefixOracleError("prefix presenter requires its closed held graph pair")
    value.guard()
    try:
        validate_presenter_graph(value.full)
        if value.opening is not None:
            validate_presenter_graph(value.opening)
        rate = canonical_presenter_rate(request.clock.frame_rate)
    except (TypeError, ValueError, AttributeError) as error:
        raise PrefixOracleError("prefix presenter graph is invalid") from error
    canvas, clock = value.full.canvas, request.clock
    if (canvas.width, canvas.height, canvas.total_frames, value.full.frame_rate) != (
            clock.width, clock.height, clock.total_frames, rate):
        raise PrefixOracleError("prefix presenter lost the original full canvas/frame clock")
    selected = tuple(window for window in value.full.windows
                     if window.geometry.timing.start_frame < request.ranges.review[1])
    expected = replace(value.full, windows=selected) if selected else None
    if value.opening != expected:
        raise PrefixOracleError("prefix presenter opening changed or omitted original global windows")
    _inventory(value)
    counts = (len(value.full.windows), len(selected))
    if any(len(clips) + count > MAX_CLIPS for clips, count in zip(
            (request.full_clips, request.opening_clips), counts)):
        raise PrefixOracleError("prefix combined presenter/overlay input count exceeds its bound")
    return value.assets


def compositor_rate(request: CompositorPrefixRequest) -> str:
    """Keep legacy argv exact; new graphs use their equivalent canonical clock."""
    return request.clock.frame_rate if request.presenter is None else request.presenter.full.frame_rate


def _inventory(value: PrefixPresenterGraphs) -> None:
    """Each distinct presentation path has one held reference; repeats are inputs."""
    if not 1 <= len(value.assets) <= 32 or any(type(row) is not HeldPrefixInput
            or type(row.path) is not str for row in value.assets):
        raise PrefixOracleError("prefix presenter held asset inventory is malformed")
    paths = {row.path for row in value.assets}
    used = {window.asset.path for window in value.full.windows}
    if len(paths) != len(value.assets) or paths != used:
        raise PrefixOracleError("prefix presenter has duplicate, missing or unconsumed held assets")
    if len(value.observations) != len(value.assets) \
            or any(type(row) is not ObservedPresenterAsset or type(row.source) is not HeldPresenterProbeFile
                   or type(row.ffprobe) is not HeldPresenterProbeFile or type(row.evidence) is not PresenterProbeEvidence
                   for row in value.observations):
        raise PrefixOracleError("prefix presenter lacks its actual held observations")


def presenter_for_role(request: CompositorPrefixRequest, role: str) -> PresenterGraphSpec | None:
    """Choose the actual graph without changing any original geometry or phase."""
    if role not in ("full", "opening", "core", "review"):
        raise PrefixOracleError("prefix presenter graph role is invalid")
    if request.presenter is None:
        return None
    return request.presenter.full if role == "full" else request.presenter.opening


def presenter_graph_payload(spec: PresenterGraphSpec | None) -> dict | None:
    """Bind exact declarations and observed metadata without serializing Fraction."""
    if spec is None:
        return None
    validate_presenter_graph(spec)
    windows = [{"operationIndex": window.operation_index,
        "frameRange": [window.geometry.timing.start_frame, window.geometry.timing.end_frame_exclusive],
        "declaration": declaration_payload(window.geometry), "asset": asdict(window.asset)} for window in spec.windows]
    return {"canvas": asdict(spec.canvas), "frameRate": spec.frame_rate,
            "baseColorPolicy": spec.base_color_policy, "windows": windows}


def presenter_input_pixels(request: CompositorPrefixRequest) -> tuple[int, int]:
    """Repeated windows cost one decoder surface each, including the same file."""
    specs = (presenter_for_role(request, role) for role in ("full", "opening"))
    return tuple(sum(window.asset.width * window.asset.height for window in spec.windows)
                 if spec is not None else 0 for spec in specs)


def validate_presenter_base(row: dict) -> None:
    """Observe explicit source tags; setparams is never evidence of BT709 input."""
    expected = {"color_space": "bt709", "color_primaries": "bt709",
                "color_transfer": "bt709", "color_range": "tv"}
    if any(row.get(key) != value for key, value in expected.items()):
        raise PrefixOracleError("presenter base lacks explicit observed BT709-limited metadata")


def presenter_layer_policy(request: CompositorPrefixRequest) -> dict:
    """New layer contract, never a legacy graphics/caption-only proof label."""
    value = request.presenter
    if value is None:
        raise PrefixOracleError("presenter layer policy requires actual presenter graphs")
    counts = request.caption_tail or (0, 0)
    return {"layerPolicy": {"kind": "held-presenter-then-graphics-then-caption-pages-v1",
        "fullPresenterWindows": len(value.full.windows),
        "openingPresenterWindows": len(value.opening.windows) if value.opening is not None else 0,
        "fullCaptionTail": counts[0], "openingCaptionTail": counts[1]}}


def _held_observation_file(actual: HeldPresenterProbeFile, expected: HeldPrefixInput,
                           identities: dict[str, tuple]) -> None:
    """Link observed stat facts to this oracle's actual full-byte verification."""
    if type(actual) is not HeldPresenterProbeFile or (
            actual.path, actual.sha256, actual.size_bytes) != (expected.path, expected.sha256, expected.size_bytes) \
            or actual.stat_identity != identities.get(expected.path):
        raise PrefixOracleError("prefix presenter observation differs from independently verified held input")
    path = Path(actual.path)
    real_directory(path.parent)
    if _identity(path.lstat()) != actual.stat_identity:
        raise PrefixOracleError("prefix presenter observed input changed after byte verification")


def assert_presenter_live(request: CompositorPrefixRequest, runtime: PrefixOracleRuntime,
                          identities: dict[str, tuple]) -> None:
    """Call ownership only at phase boundaries, then recheck all exact bindings."""
    value = request.presenter
    if value is None:
        return
    value.guard()
    expected = {row.path: row for row in value.assets}
    observed = {row.source.path: row for row in value.observations}
    if len(observed) != len(value.observations) or set(observed) != set(expected):
        raise PrefixOracleError("prefix presenter observed inventory is duplicated or incomplete")
    for path, row in observed.items():
        _held_observation_file(row.source, expected[path], identities)
        _held_observation_file(row.ffprobe, runtime.ffprobe, identities)
        if row.evidence.graph_frame_rate != value.full.frame_rate:
            raise PrefixOracleError("prefix presenter observed frame clock differs from actual graph")
    if any(window.asset != observed[window.asset.path].graph_asset for window in value.full.windows):
        raise PrefixOracleError("prefix presenter graph metadata differs from actual returned observation")


def _observation_record(value: ObservedPresenterAsset) -> dict:
    """Retain hashes of immutable raw observations, not duplicate large frame JSON."""
    evidence = value.evidence
    return {"policy": value.policy, "scope": value.scope, "source": _file_record(value.source),
        "ffprobe": _file_record(value.ffprobe), "graphAsset": asdict(value.graph_asset),
        "admissionHash": canonical_hash(asdict(value.admission)),
        "requestedFrameRate": evidence.requested_frame_rate, "graphFrameRate": evidence.graph_frame_rate,
        "headerSha256": hashlib.sha256(evidence.header_json.encode()).hexdigest(),
        "framesSha256": hashlib.sha256(evidence.frames_json.encode()).hexdigest(),
        "commands": [list(row) for row in evidence.commands], "commandSha256": list(evidence.command_sha256),
        "pngMetadata": _png_record(evidence.png_metadata)}


def _file_record(value: HeldPresenterProbeFile) -> dict:
    """Preserve exact nanosecond/inode integers without crossing JS number bounds."""
    return {"path": value.path, "sha256": value.sha256, "size_bytes": value.size_bytes,
            "statIdentityEncoding": "decimal-strings", "stat_identity": [str(part) for part in value.stat_identity]}


def _png_record(value: PresenterPngMetadata | None) -> dict | None:
    """Encode already-validated exact PNG chunk bytes losslessly for JSON proof."""
    if value is None:
        return None
    return {"width": value.width, "height": value.height, "color_chunks": list(value.color_chunks),
        "chunks": [list(row) for row in value.chunks], "metadata_bytes_read": value.metadata_bytes_read,
        "metadataEncoding": "hex", "metadata": [[kind, payload.hex()] for kind, payload in value.metadata]}


def presenter_observation_records(request: CompositorPrefixRequest, runtime: PrefixOracleRuntime,
                                  identities: dict[str, tuple], deadline: PresenterPrefixDeadline) -> dict:
    """Validate actual retained results under the original clock; never decode again."""
    if request.presenter is None:
        return {}
    deadline.remaining()
    assert_presenter_live(request, runtime, identities)
    records = []
    for row in request.presenter.observations:
        try:
            validate_presenter_observation(row, deadline.remaining)
        except (TypeError, ValueError, KeyError) as error:
            raise PrefixOracleError("prefix presenter held observation evidence is invalid") from error
        records.append(_observation_record(row))
        deadline.remaining()
    return {"presenterObservations": records}
