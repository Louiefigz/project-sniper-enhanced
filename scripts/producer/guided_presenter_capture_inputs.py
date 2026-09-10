"""Join actual V8 intent to initial-read identities, never create admission authority.

The enclosing opening/body owner must already authenticate OpeningInputs and
its original source verification. Frozen records supplied by an arbitrary
caller are not proof that admission or that verification actually happened.
"""
from __future__ import annotations

from dataclasses import dataclass

from cut_preview_io import digest
from graphics.presenter_layout_contract import PresenterCanvas
from guided_opening_inputs import OpeningInputs
from guided_presenter_assets import SelectedPresenterAsset, select_presenter_assets
from guided_presenter_probe_identity import HeldPresenterProbeFile
from guided_presenter_observation import ObservedPresenterAsset
from guided_presenter_frames import presenter_program_frames
from guided_presenter_profile import (assert_presenter_graphics_disjoint, presenter_caption_profile,
    presenter_graph_workload, presenter_profile_for_plan)
from guided_proposal_presenter import validate_requested_presenter
from headless.external_media_verification import VerifiedSnapshotIdentity
from ingest_media_observation import VerifiedExecutionMedia
from opening_prefix_contract import PrefixClock


@dataclass(frozen=True)
class PresenterCaptureSelection:
    """Ordered windows and distinct original identities, not picture eligibility."""

    selected: tuple[SelectedPresenterAsset, ...]
    sources: tuple[HeldPresenterProbeFile, ...]
    frame_rate: str


def capture_input_binding(inputs: OpeningInputs) -> str:
    """Detect in-memory input drift without reading or hashing source files again."""
    return digest({"path": str(inputs.path), "sha256": inputs.sha256,
                   "value": inputs.value, "documents": inputs.documents})


def _sources(selected: tuple[SelectedPresenterAsset, ...],
             captured: VerifiedExecutionMedia) -> tuple[HeldPresenterProbeFile, ...]:
    """Use only the identities returned by the same admitted snapshot hash pass."""
    if type(captured.snapshots) is not tuple or any(type(row) is not VerifiedSnapshotIdentity
                                                  for row in captured.snapshots):
        raise RuntimeError("Presenter requires initial source identity capture")
    snapshots = {row.path: row for row in captured.snapshots}
    if len(snapshots) != len(captured.snapshots):
        raise RuntimeError("Presenter initial source identities contain duplicate paths")
    by_path, result = {}, {}
    for row in selected:
        admission = row.admission
        previous = by_path.setdefault(admission.snapshot_path, admission.asset_id)
        if previous != admission.asset_id:
            raise RuntimeError("Presenter selected path is ambiguous across asset IDs")
        source = snapshots.get(admission.snapshot_path)
        if source is None or (source.sha256, source.size_bytes) != (
                admission.source_sha256, admission.source_size_bytes):
            raise RuntimeError("Presenter selected bytes lack their exact initial source capture")
        result.setdefault(admission.asset_id, HeldPresenterProbeFile(
            source.path, source.sha256, source.size_bytes, source.stat_identity))
    return tuple(result.values())


def _profile_clock(inputs: OpeningInputs) -> tuple[str, PrefixClock]:
    """Match both actual new tokens; this never changes public profile dispatch."""
    docs, authority = inputs.documents, inputs.documents["authority"]
    plan = docs["candidatePlan"]
    clock = PrefixClock(authority["frameRate"], authority["totalFrames"],
                        authority["target"]["width"], authority["target"]["height"])
    profile = presenter_profile_for_plan(plan, clock)
    if inputs.value.get("profile") != profile or authority.get("profile") != profile:
        raise RuntimeError("presenter capture requires both exact supplied new profile tokens")
    return profile, clock


def admit_capture_metadata(inputs: OpeningInputs, selected: tuple[SelectedPresenterAsset, ...]) -> None:
    """Admit exact new profile and whole native workload before any selected decode."""
    docs, plan = inputs.documents, inputs.documents["candidatePlan"]
    profile, clock = _profile_clock(inputs)
    graphics = presenter_program_frames(inputs)
    assert_presenter_graphics_disjoint(graphics, plan["presenterLayouts"], clock.total_frames)
    assets = {row["assetId"]: row for row in docs["readinessPacket"]["evidence"]["presenterPolicy"]["assets"]}
    canvases = tuple((assets[row.admission.asset_id]["width"], assets[row.admission.asset_id]["height"])
                     for row in selected)
    presenter_graph_workload(clock, len(graphics), presenter_caption_profile(profile), canvases)


def admit_observed_capture(inputs: OpeningInputs, selected: tuple[SelectedPresenterAsset, ...],
                           observed: tuple[ObservedPresenterAsset, ...]) -> None:
    """Actual native dimensions must match declarations and requalify the same whole workload."""
    if type(observed) is not tuple or any(type(row) is not ObservedPresenterAsset for row in observed):
        raise RuntimeError("presenter capture requires actual typed observation results")
    actual = {row.graph_asset.asset_id: row.graph_asset for row in observed}
    if len(actual) != len(observed) or set(actual) != {row.admission.asset_id for row in selected}:
        raise RuntimeError("presenter observed asset coverage is not exact and unique")
    docs = inputs.documents
    declared = {row["assetId"]: row for row in docs["readinessPacket"]["evidence"]["presenterPolicy"]["assets"]}
    canvases = tuple((actual[row.admission.asset_id].width, actual[row.admission.asset_id].height) for row in selected)
    expected = tuple((declared[row.admission.asset_id]["width"], declared[row.admission.asset_id]["height"]) for row in selected)
    if canvases != expected:
        raise RuntimeError("presenter observed dimensions differ from exact declared admitted metadata")
    profile, clock = _profile_clock(inputs)
    presenter_graph_workload(clock, len(docs["frameBindings"]["graphics"]), presenter_caption_profile(profile), canvases)


def capture_selection(inputs: OpeningInputs) -> PresenterCaptureSelection | None:
    """Validate actual policy first; absent layout never touches tools or sources."""
    if type(inputs) is not OpeningInputs:
        raise RuntimeError("Presenter capture requires the original opening inputs")
    docs = inputs.documents
    requested = validate_requested_presenter(docs["acceptedPlan"], docs["candidatePlan"],
                                            docs["readinessPacket"], docs["manifest"])
    if "presenterLayouts" not in docs["candidatePlan"]:
        return None
    if requested is None or not requested.windows:
        raise RuntimeError("Presenter acquisition requires actual nonempty V8 requested windows")
    captured = inputs.verified_media
    if type(captured) is not VerifiedExecutionMedia or type(captured.entries_json) is not bytes:
        raise RuntimeError("Presenter acquisition requires initial source identity capture")
    authority, evidence = docs["authority"], docs["readinessPacket"]["evidence"]
    if any(digest(authority.get(key)) != digest(evidence.get(key))
           for key in ("target", "frameRate", "totalFrames")):
        raise RuntimeError("Presenter original authority canvas/clock differs from V8 evidence")
    target = authority["target"]
    canvas = PresenterCanvas(target.get("width"), target.get("height"), authority["totalFrames"], "yuv420p")
    selected = select_presenter_assets(docs["candidatePlan"], docs["manifest"], captured.entries(), canvas)
    sources = _sources(selected, captured)
    admit_capture_metadata(inputs, selected)
    return PresenterCaptureSelection(selected, sources, authority["frameRate"])
