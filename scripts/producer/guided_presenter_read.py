"""Data-only checks beneath an authenticated stopped-worker presenter receipt.

The enclosing opening/body reader owns receipt authentication, original source
verification, held tools and the original deadline. Existing V8 validation reads
the pinned schemas only; no media reads, decoders, live owners or approval occur.
Raw probe hashes remain original-worker attestations, not freshly decoded facts.
"""
from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from typing import ClassVar

from cut_preview_io import digest
from graphics.presenter_layout_graph import PresenterGraphSpec, PresenterGraphWindow, validate_presenter_graph
from guided_opening_inputs import OpeningInputs, closed
from guided_presenter_assets import _absolute, _sha
from guided_presenter_capture_inputs import PresenterCaptureSelection, capture_input_binding, capture_selection
from guided_presenter_probe_contract import canonical_presenter_rate
from guided_presenter_probe_identity import HeldPresenterProbeFile, _validate_reference
from guided_presenter_profile import presenter_caption_profile, presenter_graph_workload
from guided_presenter_read_fingerprint import _MetadataSnapshot, hold_read_metadata, same_read_metadata
from guided_presenter_read_records import read_observation_records
from headless.external_media_verification import VerifiedSnapshotIdentity
from ingest_media_observation import VerifiedExecutionMedia
from opening_prefix_contract import HeldPrefixInput, MAX_INPUT_BYTES, PrefixClock, canonical_hash
from opening_prefix_graphs import PresenterGraphLane, bounded_graph_json, presenter_graph_record
from opening_prefix_presenter import _file_record, presenter_graph_payload


@dataclass(frozen=True)
class PresenterReadContext:
    """Independently held source capture/base/tool and the caller's original guard."""

    inputs: OpeningInputs
    base: HeldPrefixInput
    ffprobe: HeldPresenterProbeFile
    guard: Callable[[], None]


@dataclass(frozen=True)
class PresenterReadEvidence:
    """Data projections only; no decoder, renderer, owner or executable capability."""

    full: dict
    opening: dict | None
    assets: tuple[dict, ...]
    observations: tuple[dict, ...]
    executable: ClassVar[bool] = False
    scope: ClassVar[str] = "original-worker-attestations-not-redecoded-pictures-or-approval"


def _captured_identity(value: VerifiedExecutionMedia | None) -> _MetadataSnapshot:
    """Validate originals once, then detach every capture field type and value."""
    if value is None:
        return hold_read_metadata(None)
    if type(value) is not VerifiedExecutionMedia or type(value.entries_json) is not bytes \
            or type(value.snapshots) is not tuple or any(type(row) is not VerifiedSnapshotIdentity for row in value.snapshots):
        raise RuntimeError("presenter read initial capture structure changed")
    for row in value.snapshots:
        if type(row.size_bytes) is not int or row.size_bytes <= 0 or type(row.stat_identity) is not tuple \
                or len(row.stat_identity) != 9 or any(type(part) is not int for part in row.stat_identity):
            raise RuntimeError("presenter read initial capture identity changed")
        _absolute(row.path)
        _sha(row.sha256)
        # Unselected talking sources retain their admission class, which may be
        # larger than the selected presentation-asset observer's8GiB bound.
    return hold_read_metadata(value)


def _reference_identity(context: PresenterReadContext) -> list:
    """Validate original references before detaching the typed callback snapshot."""
    if type(context.base) is not HeldPrefixInput or type(context.base.size_bytes) is not int \
            or not 0 < context.base.size_bytes <= MAX_INPUT_BYTES:
        raise RuntimeError("presenter read base is not an independently held input")
    _absolute(context.base.path)
    _sha(context.base.sha256)
    _validate_reference(context.ffprobe, True)
    return [asdict(context.base), _file_record(context.ffprobe)]


def _read_guard(context: PresenterReadContext, arguments: object) -> Callable[[], None]:
    """Fence final callbacks against changing the very inputs/records being checked."""
    if type(context) is not PresenterReadContext or not callable(context.guard):
        raise RuntimeError("presenter read requires its original held reader context")
    callback, inputs, captured = context.guard, context.inputs, context.inputs.verified_media
    # Keep the existing initial JSON-domain checks; only repeated private
    # comparisons change, never capture_input_binding or receipt hash domains.
    capture_input_binding(inputs)
    canonical_hash([*_reference_identity(context), arguments])
    capture = _captured_identity(captured)
    references = hold_read_metadata((context.base, context.ffprobe))
    metadata = lambda: [str(inputs.path), inputs.sha256, inputs.value, inputs.documents, arguments]
    expected, path_type = hold_read_metadata(metadata()), type(inputs.path)

    def check() -> None:
        """Call original source/time checks, then compare exact metadata before return."""
        callback()
        if context.guard is not callback or context.inputs is not inputs or inputs.verified_media is not captured \
                or type(inputs.path) is not path_type or not same_read_metadata(captured, capture) \
                or not same_read_metadata((context.base, context.ffprobe), references) \
                or not same_read_metadata(metadata(), expected):
            raise RuntimeError("presenter cold read original arguments changed")

    return check


def _context(context: PresenterReadContext) -> PrefixClock:
    """Validate held metadata only; caller guards retain actual file/hash ownership."""
    _reference_identity(context)
    authority = context.inputs.documents["authority"]
    return PrefixClock(authority["frameRate"], authority["totalFrames"],
                       authority["target"]["width"], authority["target"]["height"])


def _compile(context: PresenterReadContext, selection: PresenterCaptureSelection, assets: dict) -> PresenterGraphSpec:
    """Recompile manual candidate geometry and each repeated window's exact coverage."""
    clock = _context(context)
    declared = {row["assetId"]: row for row in context.inputs.documents["readinessPacket"]["evidence"]["presenterPolicy"]["assets"]}
    windows = tuple(PresenterGraphWindow(row.operation_index, deepcopy(row.geometry), assets[row.admission.asset_id])
                    for row in selection.selected)
    graph = PresenterGraphSpec(selection.selected[0].geometry.canvas,
                              canonical_presenter_rate(selection.frame_rate), windows, "bt709-limited-video")
    validate_presenter_graph(graph)
    canvases = tuple((row.asset.width, row.asset.height) for row in windows)
    expected = tuple((declared[row.asset.asset_id]["width"], declared[row.asset.asset_id]["height"]) for row in windows)
    if canvases != expected:
        raise RuntimeError("presenter read observed dimensions differ from original declared metadata")
    presenter_graph_workload(clock, len(context.inputs.documents["frameBindings"]["graphics"]),
        presenter_caption_profile(context.inputs.value["profile"]), canvases)
    return graph


def _read(records: object, context: PresenterReadContext, check: Callable[[], None]) -> tuple:
    """Keep complete future windows and a whole-clock opening selection, not a new plan."""
    check()
    selection = capture_selection(context.inputs)
    if selection is None:
        if records is not None:
            raise RuntimeError("legacy opening cannot acquire presenter observations")
        check()
        return None, None
    assets = read_observation_records(records, selection, context.ffprobe, check)
    full = _compile(context, selection, assets)
    review_end = context.inputs.documents["authority"]["review"]["endFrameExclusive"]
    selected = tuple(row for row in full.windows if row.geometry.timing.start_frame < review_end)
    opening = replace(full, windows=selected) if selected else None
    refs = tuple(asdict(HeldPrefixInput(row.path, row.sha256, row.size_bytes)) for row in selection.sources)
    evidence = PresenterReadEvidence(presenter_graph_payload(full), presenter_graph_payload(opening),
                                     refs, tuple(deepcopy(records)))
    check()
    return evidence, opening


def read_presenter_graphs(records: object, context: PresenterReadContext) -> PresenterReadEvidence | None:
    """Return original receipt-attested data only, never a live selected-media owner."""
    check = _read_guard(context, records)
    evidence, _opening = _read(records, context, check)
    check()
    return evidence


def _layers(value: object) -> tuple:
    """Require independently derived combined clips and exact optional caption tail."""
    if type(value) is not tuple or len(value) != 2 or type(value[0]) is not tuple \
            or len(value[0]) > 512 or any(type(row) is not dict for row in value[0]):
        raise RuntimeError("presenter read combined layers are malformed")
    clips, tail = value
    if tail is not None and (type(tail) is not int or not 0 <= tail <= len(clips)):
        raise RuntimeError("presenter read caption tail is malformed")
    bounded_graph_json(list(clips))
    return clips, tail


def verify_opening_presenter_layers(pictures: dict, context: PresenterReadContext,
                                    combined_layers: tuple) -> PresenterReadEvidence | None:
    """Compare actual range evidence; existing output/AAC/decode readers remain required."""
    if type(pictures) is not dict:
        raise RuntimeError("presenter opening pictures are malformed")
    clips, tail = _layers(combined_layers)
    check = _read_guard(context, [pictures, list(clips), tail])
    layers = pictures.get("presenterLayers")
    records = layers.get("observations") if type(layers) is dict else None
    evidence, opening = _read(records, context, check)
    if evidence is None:
        if "presenterLayers" in pictures:
            raise RuntimeError("legacy opening contains an unsupported presenter record")
        return None
    authority = context.inputs.documents["authority"]
    graph = presenter_graph_record(_context(context), context.base, PresenterGraphLane(
        clips, tail, opening, tuple(HeldPrefixInput(**row) for row in evidence.assets)))
    bounded_graph_json(graph)
    expected = {"schemaVersion": 1, "kind": "live-presenter-opening-range-composition",
        "scope": "actual-opening-graph-not-body-prefix-caption-clearance-or-approval",
        "candidatePlanHash": authority["candidatePlanHash"], "authorityHash": digest(authority),
        "graph": graph, "graphHash": canonical_hash(graph),
        "fullPresenterGraphHash": canonical_hash(evidence.full),
        "layerPolicy": "held-presenter-then-graphics-then-caption-pages-v1",
        "deliveryApproved": False, "captionClearanceVerified": False,
        "observations": list(evidence.observations), "pictureRangesHash": digest(pictures["ranges"])}
    closed(layers, set(expected), "presenter opening range evidence")
    if canonical_hash(layers) != canonical_hash(expected):
        raise RuntimeError("presenter opening evidence differs from independently reconstructed graph/ranges")
    check()
    return evidence
