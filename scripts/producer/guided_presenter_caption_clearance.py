"""Live precomposition caption clearance for a manually declared subject envelope.

This is not face tracking, presentation-text readability, picture completion,
or approval. The caller must retain the actual returned caption projection and
presenter execution; a serialized report cannot acquire either owner. A later
integration must bind this report to the actual combined picture proof.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import math
from pathlib import Path

from cut_preview_io import digest, real_directory
from graphics.presenter_layout_contract import PresenterGeometry
from graphics.presenter_layout_geometry import presenter_frame
from graphics.presenter_layout_graph import PresenterGraphSpec, PresenterGraphWindow
from guided_caption_dependencies import Guard, MAX_FILES, read_caption_json
from guided_caption_layout import _MAX_PAIRS, _clock, _cue, _span
from guided_caption_projection import HeldCaptionProjection
from guided_caption_screen import CaptionScreenContext, held_cues
from guided_opening_inputs import OpeningInputs, hash_value
from guided_presenter_execution import OwnedPresenterExecution
from guided_presenter_probe_identity import presenter_stat_identity, probe_deadline_remaining
from opening_prefix_contract import canonical_hash
from opening_prefix_presenter import _observation_record, presenter_graph_payload

POLICY = "held-manual-presenter-caption-clearance-v1"
GUTTER_PX = 16


@dataclass(frozen=True)
class PresenterCaptionClearanceContext:
    """Original live owners and exact opening/full-program coverage, not authority."""

    inputs: OpeningInputs
    held: HeldCaptionProjection
    presenter: OwnedPresenterExecution
    coverage: dict


def swept_subject_bounds(geometry: PresenterGeometry, span: tuple[int, int]) -> list[float]:
    """Conservatively enclose all written-frame affine subject positions.

    Progress is monotone on enter/hold/exit, and each protected corner is
    affine in progress. Thus interval endpoints and the two ramp junctions
    contain every coordinate extremum. No duration-sized frame scan occurs.
    The live owner validates geometry before this pure projection is called.
    """
    timing = geometry.timing
    start, end = span
    if type(start) is not int or type(end) is not int \
            or not timing.start_frame <= start < end <= timing.end_frame_exclusive:
        raise RuntimeError("presenter clearance intersection is outside its original window")
    junctions = (timing.start_frame + timing.enter_frames,
                 timing.end_frame_exclusive - 1 - timing.exit_frames)
    frames = sorted({start, end - 1, *(min(end - 1, max(start, frame)) for frame in junctions)})
    points = []
    for frame in frames:
        state = presenter_frame(geometry, frame)
        points.extend((state.scale * x + state.translation[0], state.scale * y + state.translation[1])
                      for x, y in geometry.shape.surfaces.protected.corners())
    bounds = [min(x for x, _ in points), min(y for _, y in points),
              max(x for x, _ in points), max(y for _, y in points)]
    if not all(math.isfinite(value) for value in bounds):
        raise RuntimeError("presenter clearance has nonfinite derived geometry")
    return bounds


def _context(context: PresenterCaptionClearanceContext, guard: Guard) -> tuple[dict, PresenterGraphSpec]:
    """Bind the actual plan/clock and refuse a caller-chosen partial safe range."""
    if type(context) is not PresenterCaptionClearanceContext or not callable(guard) \
            or type(context.inputs) is not OpeningInputs or type(context.held) is not HeldCaptionProjection \
            or type(context.presenter) is not OwnedPresenterExecution:
        raise RuntimeError("presenter caption clearance requires original live owners")
    guard()
    inputs, owner = context.inputs, context.presenter
    authority, plan = inputs.documents["authority"], inputs.documents["candidatePlan"]
    owner.assert_plan(plan)
    owner.assert_clock((authority["target"]["width"], authority["target"]["height"]),
                       (authority["frameRate"], authority["totalFrames"]))
    if hash_value(authority["candidatePlanHash"]) != digest(plan):
        raise RuntimeError("presenter clearance candidate differs from original authority")
    rate = Fraction(authority["frameRate"])
    clock = _clock({"frameRate": f"{rate.numerator}/{rate.denominator}",
        "totalFrames": authority["totalFrames"], "width": authority["target"]["width"],
        "height": authority["target"]["height"]})
    coverage = context.coverage
    if type(coverage) is not dict or set(coverage) != {"startFrame", "endFrameExclusive"}:
        raise RuntimeError("presenter clearance coverage is malformed")
    _span(coverage, clock["totalFrames"])
    full = {"startFrame": 0, "endFrameExclusive": clock["totalFrames"]}
    if coverage != full and coverage != authority["review"]:
        raise RuntimeError("presenter clearance coverage is not original opening or full body")
    if coverage["startFrame"] != 0:
        raise RuntimeError("presenter clearance must keep original full-program origin")
    return clock, owner.full_graph()


def _captions(context: PresenterCaptionClearanceContext, graph: PresenterGraphSpec,
              clock: dict, guard: Guard) -> list[dict]:
    """Reuse exact whole-cue readback, including alpha bounds and every page file."""
    entries = context.held.data["shards"]["entries"]
    if type(entries) is not list or len(entries) > 4096 or len(entries) * len(graph.windows) > _MAX_PAIRS:
        raise RuntimeError("presenter caption clearance exceeds bounded cue/window pairs")
    source = CaptionScreenContext(context.inputs, context.held, (), context.coverage)
    cues = held_cues(source, guard)
    if digest(read_caption_json(context.held.binding.plan, guard)) != digest(context.inputs.documents["candidatePlan"]):
        raise RuntimeError("presenter clearance caption plan differs from actual candidate bytes")
    if len(cues) != len(entries):
        raise RuntimeError("presenter clearance omitted original caption cues")
    parsed = []
    for cue in cues:
        probe_deadline_remaining(context.presenter.runtime)
        parsed.append(_cue(cue, clock))
    if len({cue["cueId"] for cue in parsed}) != len(parsed):
        raise RuntimeError("presenter clearance duplicates original cue identities")
    return parsed


def _caption_identities(held: HeldCaptionProjection) -> dict[str, tuple[int, ...]]:
    """Bracket the actual byte read; current stat alone never authenticates bytes."""
    binding = held.binding
    groups = (held.files, held.external, binding.dependencies, (binding.plan, binding.manifest, binding.timeline))
    if any(type(rows) is not tuple for rows in groups) or sum(map(len, groups)) > 2 * MAX_FILES:
        raise RuntimeError("presenter caption identity inventory is unbounded")
    result = {}
    for row in (row for rows in groups for row in rows):
        path = Path(row.path)
        real_directory(path.parent)
        result[row.path] = presenter_stat_identity(path.lstat())
    return result


def _capture(context: PresenterCaptionClearanceContext, guard: Guard) -> tuple[dict, list, PresenterGraphSpec, dict]:
    """Snapshot live relationships and reread actual retained dependencies."""
    clock, graph = _context(context, guard)
    identities = _caption_identities(context.held)
    cues = _captions(context, graph, clock, guard)
    observations = []
    for row in context.presenter.observed:
        probe_deadline_remaining(context.presenter.runtime)
        observations.append(_observation_record(row))
    context.presenter.assert_current()
    graph_payload = presenter_graph_payload(graph)
    value = {"executionInputHash": hash_value(context.inputs.value["executionInputHash"]),
        "candidatePlan": dict(context.inputs.value["documents"]["candidatePlan"]),
        "candidatePlanHash": digest(context.inputs.documents["candidatePlan"]),
        "authorityHash": digest(context.inputs.documents["authority"]),
        "captionProjectionHash": context.held.data_hash, "clock": clock,
        "coverage": dict(context.coverage), "presenterGraph": graph_payload,
        "presenterGraphHash": canonical_hash(graph_payload), "presenterObservations": observations,
        "cueBindingsHash": canonical_hash([{**cue, "box": list(cue["box"])} for cue in cues])}
    probe_deadline_remaining(context.presenter.runtime)
    if _caption_identities(context.held) != identities:
        raise RuntimeError("presenter caption dependencies changed around their strong read")
    return value, cues, graph, identities


def _terminal(context: PresenterCaptionClearanceContext, binding: dict, identities: dict) -> None:
    """No further owner callbacks may hide late in-memory or retained-file drift."""
    current = {"executionInputHash": context.inputs.value["executionInputHash"],
        "candidatePlan": context.inputs.value["documents"]["candidatePlan"],
        "candidatePlanHash": digest(context.inputs.documents["candidatePlan"]),
        "authorityHash": digest(context.inputs.documents["authority"]),
        "captionProjectionHash": digest(context.held.data), "coverage": context.coverage}
    if any(canonical_hash(value) != canonical_hash(binding[key]) for key, value in current.items()):
        raise RuntimeError("presenter caption held metadata changed before report return")
    if _caption_identities(context.held) != identities:
        raise RuntimeError("presenter caption dependencies changed before report return")


def _pair(window: PresenterGraphWindow, cue: dict, coverage: dict) -> dict | None:
    """Keep original geometry/cue bounds while intersecting only report coverage."""
    timing = window.geometry.timing
    start = max(timing.start_frame, cue["startFrame"], coverage["startFrame"])
    end = min(timing.end_frame_exclusive, cue["endFrameExclusive"], coverage["endFrameExclusive"])
    if start >= end:
        return None
    bounds = swept_subject_bounds(window.geometry, (start, end))
    box = cue["box"]
    conflict = box[0] < bounds[2] + GUTTER_PX and bounds[0] < box[2] + GUTTER_PX \
        and box[1] < bounds[3] + GUTTER_PX and bounds[1] < box[3] + GUTTER_PX
    return {"operationIndex": window.operation_index, "cueId": cue["cueId"],
        "startFrame": start, "endFrameExclusive": end, "captionBounds": list(box),
        "sweptProtectedSubjectBounds": bounds, "conflict": conflict}


def inspect_presenter_caption_clearance(context: PresenterCaptionClearanceContext, guard: Guard) -> dict:
    """Reject collisions and drift before composition under the original clock."""
    binding, cues, graph, identities = _capture(context, guard)
    pairs = []
    for window in graph.windows:
        probe_deadline_remaining(context.presenter.runtime)
        pairs.extend(row for cue in cues if (row := _pair(window, cue, binding["coverage"])) is not None)
    final, _cues, _graph, final_identities = _capture(context, guard)
    if canonical_hash(final) != canonical_hash(binding) or final_identities != identities:
        raise RuntimeError("presenter caption clearance inputs changed during inspection")
    conflicts = [row for row in pairs if row["conflict"]]
    if conflicts:
        first = conflicts[0]
        raise RuntimeError(f"presenter caption clearance conflict: operation {first['operationIndex']} "
                           f"cue {first['cueId']} frames {first['startFrame']}:{first['endFrameExclusive']}")
    result = {"schemaVersion": 1, "kind": "presenter-caption-clearance", "policy": POLICY,
        "scope": "precomposition-manual-envelope-not-face-or-presentation-text-readability",
        "state": "screened-no-overlap" if pairs else "not-applicable", "gutterPx": GUTTER_PX,
        "binding": binding, "intersections": pairs, "pictureProofBound": False,
        "qcPassed": False, "creativeApproved": False, "deliveryApproved": False}
    probe_deadline_remaining(context.presenter.runtime)
    _terminal(context, binding, identities)
    return result


def verify_presenter_caption_clearance(context: PresenterCaptionClearanceContext,
                                      expected: dict, guard: Guard) -> None:
    """Rebuild only beneath the original live owner; serialized success is inert."""
    observed = inspect_presenter_caption_clearance(context, guard)
    if type(expected) is not dict or canonical_hash(expected) != canonical_hash(observed):
        raise RuntimeError("presenter caption clearance differs from original held inputs")
