"""Live selected-picture ownership for the existing shared graphics compositor.

The caller must first authenticate the actual V8 request/candidate and admitted
source set, observe each selected asset once, and retain its original guard and
deadline. This object cannot be loaded from a JSON approval or create source
rights. It binds those observations to every original operation occurrence;
base color, prefix equality, full output and audiovisual QC remain separate.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, fields, is_dataclass, replace

from cut_preview_io import digest
from graphics.presenter_layout_contract import declaration_payload
from graphics.presenter_layout_graph import (
    PresenterGraphSpec, PresenterGraphWindow, validate_presenter_graph,
)
from guided_presenter_assets import SelectedPresenterAsset
from guided_presenter_observation import ObservedPresenterAsset, validate_presenter_observation
from guided_presenter_probe_contract import canonical_presenter_rate
from guided_presenter_probe_identity import (
    PresenterObservationRuntime, observation_remaining, probe_deadline_remaining,
)
from opening_prefix_contract import HeldPrefixInput


def _exact(left: object, right: object) -> bool:
    """Compare immutable records type-strictly without reserializing frame stdout."""
    if type(left) is not type(right):
        return False
    if is_dataclass(left):
        return all(_exact(getattr(left, row.name), getattr(right, row.name)) for row in fields(left))
    if type(left) is tuple:
        return len(left) == len(right) and all(_exact(a, b) for a, b in zip(left, right))
    return left == right


def _observed_index(rows: tuple[ObservedPresenterAsset, ...],
                    runtime: PresenterObservationRuntime) -> dict[str, ObservedPresenterAsset]:
    """Require one real observation per selected asset, not one decode per window."""
    if type(rows) is not tuple or not 1 <= len(rows) <= 32:
        raise RuntimeError("owned presenter requires1–32 immutable observed assets")
    result, paths = {}, set()
    for row in rows:
        validate_presenter_observation(row, lambda: probe_deadline_remaining(runtime))
        asset_id, path = row.graph_asset.asset_id, row.source.path
        if asset_id in result or path in paths:
            raise RuntimeError("owned presenter observed asset IDs/paths are ambiguous")
        result[asset_id] = row
        paths.add(path)
    if any(row.ffprobe != runtime.ffprobe for row in rows):
        raise RuntimeError("owned presenter observations used different held probe tools")
    return result


def _window(selected: SelectedPresenterAsset, observed: ObservedPresenterAsset) -> PresenterGraphWindow:
    """Keep the exact selected admission, original index and full global geometry."""
    admission, source, asset = selected.admission, observed.source, observed.graph_asset
    if admission != observed.admission or (asset.asset_id, asset.path) != (admission.asset_id, admission.snapshot_path) \
            or (source.path, source.sha256, source.size_bytes) != (
                admission.snapshot_path, admission.source_sha256, admission.source_size_bytes):
        raise RuntimeError("owned presenter observation differs from selected admitted bytes")
    return PresenterGraphWindow(selected.operation_index, deepcopy(selected.geometry), deepcopy(asset))


def _graph(selected: tuple[SelectedPresenterAsset, ...], observed: dict[str, ObservedPresenterAsset],
           frame_rate: str) -> PresenterGraphSpec:
    """Validate coverage for all repeated occurrences, not only the first probe call."""
    if type(selected) is not tuple or not 1 <= len(selected) <= 32 \
            or any(type(row) is not SelectedPresenterAsset for row in selected):
        raise RuntimeError("owned presenter requires exact selected operation occurrences")
    ids = {row.admission.asset_id for row in selected}
    if ids != set(observed):
        raise RuntimeError("owned presenter observations omit or add selected assets")
    rate = canonical_presenter_rate(frame_rate)
    if any(row.evidence.graph_frame_rate != rate for row in observed.values()):
        raise RuntimeError("owned presenter observations differ from the original frame clock")
    windows = tuple(_window(row, observed[row.admission.asset_id]) for row in selected)
    result = PresenterGraphSpec(selected[0].geometry.canvas, rate, windows, "bt709-limited-video")
    validate_presenter_graph(result)
    return result


@dataclass(frozen=True)
class OwnedPresenterExecution:
    """Internal live binding; no parser, provider flag or serialized completion owns it."""

    selected: tuple[SelectedPresenterAsset, ...]
    observed: tuple[ObservedPresenterAsset, ...]
    frame_rate: str
    runtime: PresenterObservationRuntime
    _full: PresenterGraphSpec = field(init=False, repr=False)
    _snapshot: tuple = field(init=False, repr=False)
    _runtime_binding: tuple = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Validate once; retain immutable raw observations without another decode."""
        observation_remaining(self.runtime)
        graph = _graph(self.selected, _observed_index(self.observed, self.runtime), self.frame_rate)
        object.__setattr__(self, "_full", graph)
        object.__setattr__(self, "_snapshot", deepcopy((self.selected, self.observed, self.frame_rate, graph)))
        object.__setattr__(self, "_runtime_binding", (deepcopy(self.runtime.ffprobe),
            self.runtime.working_directory, self.runtime.deadline, self.runtime.guard))
        observation_remaining(self.runtime)

    def assert_current(self) -> None:
        """Retain caller ownership and detect changes without rereading/decoding media."""
        if type(self.runtime) is not PresenterObservationRuntime or not _exact((
                self.runtime.ffprobe, self.runtime.working_directory, self.runtime.deadline, self.runtime.guard), self._runtime_binding):
            raise RuntimeError("owned presenter original runtime/guard/deadline changed")
        observation_remaining(self.runtime)
        if not _exact((self.selected, self.observed, self.frame_rate, self._full), self._snapshot):
            raise RuntimeError("owned presenter selection/observation/graph changed")
        validate_presenter_graph(self._full)

    def full_graph(self) -> PresenterGraphSpec:
        """Supply an isolated full graph, never change ramps for an opening preview."""
        self.assert_current()
        return deepcopy(self._full)

    def held_assets(self) -> tuple[HeldPrefixInput, ...]:
        """Project already observed byte identities in first-window occurrence order."""
        self.assert_current()
        rows = {row.graph_asset.asset_id: row.source for row in self.observed}
        ids = dict.fromkeys(row.admission.asset_id for row in self.selected)
        return tuple(HeldPrefixInput(rows[key].path, rows[key].sha256, rows[key].size_bytes) for key in ids)

    def assert_plan(self, plan: dict) -> None:
        """Bind the assembler's actual track; the caller still authenticates its plan."""
        self.assert_current()
        windows = [{"operationIndex": row.operation_index,
            "startFrame": row.geometry.timing.start_frame,
            "endFrameExclusive": row.geometry.timing.end_frame_exclusive,
            "layout": declaration_payload(row.geometry)} for row in self.selected]
        if type(plan) is not dict or digest(plan.get("presenterLayouts")) != digest(windows):
            raise RuntimeError("owned presenter differs from the exact requested plan track")

    def assert_clock(self, canvas: tuple[int, int], clock: tuple[str, int]) -> None:
        """Bind the full held canvas/count while allowing only reduced N/1 spelling."""
        self.assert_current()
        expected = self._full.canvas
        if type(canvas) is not tuple or type(clock) is not tuple or len(clock) != 2 \
                or canvas != (expected.width, expected.height) or type(clock[1]) is not int \
                or clock[1] != expected.total_frames or canonical_presenter_rate(clock[0]) != self._full.frame_rate:
            raise RuntimeError("owned presenter differs from the actual full canvas/frame clock")

    def prefix_graphs(self, review_end: int) -> object:
        """Create the internal prefix pair with all crossing-window timing unchanged."""
        from opening_prefix_presenter import PrefixPresenterGraphs

        full = self.full_graph()
        if type(review_end) is not int or not 1 <= review_end <= full.canvas.total_frames:
            raise RuntimeError("owned presenter opening end is outside the original program")
        windows = tuple(row for row in full.windows if row.geometry.timing.start_frame < review_end)
        opening = replace(full, windows=windows) if windows else None
        return PrefixPresenterGraphs(full, opening, self.held_assets(), self.observed, self.assert_current)
