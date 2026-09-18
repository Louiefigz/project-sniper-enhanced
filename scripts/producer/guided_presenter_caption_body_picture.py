"""Live whole-program presenter/caption clearance around actual body composition.

No report is reused from the opening, no page is retimed, and no raw observation
is decoded or hashed in a per-cue guard. The actual compositor return is held
before retention/completion callbacks; only its matching retained bytes can be
bound. This does not qualify source color, visual QC, delivery or human approval.
"""
from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import math
from pathlib import Path
import stat

from cut_preview_io import real_directory
from graphics.owned_execution import GraphicsComposition
from guided_caption_execution import OwnedCaptionExecution
from guided_caption_layers import caption_page_clips
from guided_opening_inputs import OpeningInputs
from guided_presenter_caption_body_record import (
    body_presenter_caption_picture_record, validate_original_body_picture_proof,
)
from guided_presenter_caption_clearance import (
    PresenterCaptionClearanceContext, _caption_identities,
    inspect_presenter_caption_clearance, verify_presenter_caption_clearance,
)
from guided_presenter_execution import OwnedPresenterExecution, _exact
from guided_presenter_probe_identity import PresenterObservationRuntime, presenter_stat_identity
from guided_presenter_read_fingerprint import hold_read_metadata, same_read_metadata
from opening_prefix_contract import CompositorPrefixRequest, canonical_hash
from opening_prefix_graphs import graph_hash, graph_projection, assert_presenter_graph_proof
from opening_prefix_presenter import presenter_graph_payload


@dataclass(frozen=True)
class BodyPresenterCaptionContext:
    """Original body owner references and clock-bearing guard, not serialized authority."""

    inputs: OpeningInputs
    captions: OwnedCaptionExecution | None
    presenter: OwnedPresenterExecution | None
    guard: Callable[[], None]


@dataclass(frozen=True)
class PreparedBodyPresenterCaption:
    """Private pre-encode state retaining exact whole-program metadata and files."""

    context: BodyPresenterCaptionContext
    request: CompositorPrefixRequest
    value: GraphicsComposition
    clearance: PresenterCaptionClearanceContext
    report: dict
    pages: tuple[dict, ...]
    retained_path: str
    original: tuple


@dataclass(frozen=True)
class HeldBodyPresenterCaptionProof:
    """Actual live return held before any retention or caption completion callback."""

    prepared: PreparedBodyPresenterCaption
    proof: dict
    metadata: object
    output_identity: tuple


@dataclass(frozen=True)
class RetainedBodyPresenterCaptionProof:
    """The actual copy return, held before any subsequent completion callback."""

    held: HeldBodyPresenterCaptionProof
    retained: dict
    metadata: object
    identity: tuple


def _fraction_components(owner: OwnedPresenterExecution) -> tuple:
    """Detach rational components too: deepcopy legitimately reuses immutable Fractions."""
    geometries = [row.geometry for row in (*owner.selected, *owner._full.windows)]
    return tuple((type(row.declaration.asset_start), row.declaration.asset_start.numerator,
                  row.declaration.asset_start.denominator) for row in geometries)


def _hold_owner(owner: OwnedPresenterExecution) -> tuple:
    """Hold original live metadata once; raw immutable probe strings are not rehashed."""
    runtime = owner.runtime
    if type(runtime) is not PresenterObservationRuntime:
        raise RuntimeError("body presenter caption original runtime is malformed")
    metadata = deepcopy((owner.selected, owner.observed, owner.frame_rate, owner._full))
    controls = (runtime, deepcopy(runtime.ffprobe), runtime.working_directory,
                runtime.deadline, runtime.guard, runtime.deadline.remaining)
    files = deepcopy(tuple(row.source for row in owner.observed) + (runtime.ffprobe,))
    return owner, metadata, controls, files, _fraction_components(owner)


def _owner_unchanged(held: tuple) -> None:
    """Check original runtime, typed observations and source/tool inodes without callbacks."""
    owner, metadata, controls, files, fractions = held
    runtime, probe, directory, deadline, guard, remaining = controls
    if owner.runtime is not runtime or type(runtime) is not PresenterObservationRuntime \
            or runtime.deadline is not deadline or runtime.guard is not guard \
            or runtime.deadline.remaining != remaining \
            or not _exact((runtime.ffprobe, runtime.working_directory), (probe, directory)) \
            or not _exact((owner.selected, owner.observed, owner.frame_rate, owner._full), metadata) \
            or not _exact(_fraction_components(owner), fractions):
        raise RuntimeError("body presenter caption original owner/runtime/observation changed")
    for row in files:
        path = Path(row.path)
        real_directory(path.parent)
        if presenter_stat_identity(path.lstat()) != row.stat_identity:
            raise RuntimeError("body presenter caption original source/tool identity changed")
        real_directory(path.parent)


def _check_owner(held: tuple) -> None:
    """Check the ORIGINAL remaining method after metadata/stats, then reject callback drift."""
    _owner_unchanged(held)
    seconds = held[2][5]()
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0:
        raise RuntimeError("body presenter caption original deadline expired")
    _owner_unchanged(held)


def _facts(context: BodyPresenterCaptionContext, request: CompositorPrefixRequest,
           value: GraphicsComposition) -> tuple:
    """Snapshot small phase metadata; never copy raw presentation probe evidence."""
    return ((str(context.inputs.path), context.inputs.sha256, context.inputs.value, context.inputs.documents),
        context.captions.held, id(context.captions.guard),
        graph_projection(request, "full"), graph_projection(request, "opening"),
        request.clock, request.ranges, request.assets,
        value.video_in, value.video_out, value.clips, value.caption_clips, value.canvas, value.frame_clock,
        asdict(replace(value.options, presenter=None)), presenter_graph_payload(value.options.presenter),
        id(context.inputs), id(context.captions), id(context.presenter), id(context.guard),
        id(value.presenter), id(request.presenter), id(request.presenter.guard))


def _selection(context: BodyPresenterCaptionContext, request: CompositorPrefixRequest,
               value: GraphicsComposition) -> tuple[dict, ...] | None:
    """Require the actual caption tail and presenter owner before any native work."""
    if type(context) is not BodyPresenterCaptionContext or type(context.inputs) is not OpeningInputs:
        raise RuntimeError("body presenter captions need original inputs and actual live owners")
    plan = context.inputs.documents["candidatePlan"]
    if context.presenter is None and "presenterLayouts" not in plan and value.presenter is None:
        return None
    requested = "captionsTrack" in plan or (type(plan.get("captions")) is dict and plan["captions"].get("burn") is True)
    if not requested and context.captions is None and not value.caption_clips and request.caption_tail is None:
        return None
    if type(context.inputs) is not OpeningInputs or type(context.captions) is not OwnedCaptionExecution \
            or type(context.presenter) is not OwnedPresenterExecution or value.presenter is not context.presenter \
            or request.presenter is None:
        raise RuntimeError("body presenter captions need original inputs and actual live owners")
    pages = caption_page_clips(context.captions.held)
    if not pages or request.caption_tail is None or request.caption_tail[0] != len(pages) \
            or value.caption_clips != pages or request.full_clips != (*value.clips, *pages):
        raise RuntimeError("body presenter captions differ from original full pages or actual request graph")
    return pages


def prepare_presenter_caption_body(context: BodyPresenterCaptionContext, request: CompositorPrefixRequest,
                                   value: GraphicsComposition, retained_path: str) -> PreparedBodyPresenterCaption | None:
    """Inspect the full body before prefix/encode; preserve genuine legacy/no-caption paths."""
    pages = _selection(context, request, value)
    if pages is None:
        return None
    authority = context.inputs.documents["authority"]
    coverage = {"startFrame": 0, "endFrameExclusive": authority["totalFrames"]}
    clearance = PresenterCaptionClearanceContext(context.inputs, context.captions.held, context.presenter, coverage)
    original = hold_read_metadata(_facts(context, request, value))
    identities = _caption_identities(clearance.held)
    owner = _hold_owner(context.presenter)
    context.guard()
    if canonical_hash(presenter_graph_payload(request.presenter.full)) \
            != canonical_hash(presenter_graph_payload(context.presenter.full_graph())):
        raise RuntimeError("body presenter captions differ from actual original owner graph")
    report = inspect_presenter_caption_clearance(clearance, context.presenter.assert_current)
    prepared = PreparedBodyPresenterCaption(context, request, value, clearance, report, pages, retained_path,
        (original, identities, hold_read_metadata(report), hold_read_metadata((coverage, pages, retained_path)), owner))
    check_presenter_caption_body(prepared)
    return prepared


def check_presenter_caption_body(prepared: PreparedBodyPresenterCaption | None) -> None:
    """Finite phase check after caller/owner callbacks, with no new deadline or byte pass."""
    if prepared is None:
        return
    context = prepared.context
    context.guard()
    context.presenter.assert_current()
    context.captions.guard()
    original, identities, report, selected, owner = prepared.original
    if prepared.clearance.inputs is not context.inputs or prepared.clearance.held is not context.captions.held \
            or prepared.clearance.presenter is not context.presenter \
            or not same_read_metadata(_facts(context, prepared.request, prepared.value), original) \
            or not same_read_metadata(prepared.report, report) \
            or not same_read_metadata((prepared.clearance.coverage, prepared.pages, prepared.retained_path), selected) \
            or _caption_identities(context.captions.held) != identities:
        raise RuntimeError("body presenter caption original metadata or held files changed")
    _check_owner(owner)


def _picture_identity(path: str, size: int) -> tuple:
    """Stat-link actual returned/retained bytes; their byte hashes remain actual owner work."""
    target = Path(path)
    real_directory(target.parent)
    info = target.lstat()
    if str(target) != path or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != size:
        raise RuntimeError("body presenter caption picture identity is unsafe or changed")
    return presenter_stat_identity(info)


def hold_presenter_caption_body_proof(prepared: PreparedBodyPresenterCaption | None,
                                      proof: dict) -> HeldBodyPresenterCaptionProof | None:
    """Hold the ACTUAL return before callbacks; reject a different independently derived graph."""
    if prepared is None:
        return None
    metadata = hold_read_metadata(proof)
    validate_original_body_picture_proof(proof)
    if proof["outputPath"] != prepared.value.video_out:
        raise RuntimeError("body presenter caption proof changed the actual output path")
    identity = _picture_identity(proof["outputPath"], proof["output"]["size_bytes"])
    held = HeldBodyPresenterCaptionProof(prepared, proof, metadata, identity)
    check_presenter_caption_body(prepared)
    assert_presenter_graph_proof(prepared.request, proof["prefixOracle"])
    check_presenter_caption_body_proof(held)
    return held


def check_presenter_caption_body_proof(held: HeldBodyPresenterCaptionProof | None) -> None:
    """No late callback can substitute proof metadata or the returned picture inode."""
    if held is None:
        return
    check_presenter_caption_body(held.prepared)
    proof = held.proof
    if not same_read_metadata(proof, held.metadata) \
            or _picture_identity(proof["outputPath"], proof["output"]["size_bytes"]) != held.output_identity \
            or proof["prefixOracle"]["fullGraphHash"] != graph_hash(held.prepared.request, "full"):
        raise RuntimeError("body presenter caption actual proof or output changed")


def hold_presenter_caption_body_retained(held: HeldBodyPresenterCaptionProof | None,
                                         retained: dict) -> RetainedBodyPresenterCaptionProof | None:
    """Capture the actual copy identity immediately, before caption completion callbacks."""
    if held is None:
        return None
    original = hold_read_metadata(retained)
    if retained["path"] != held.prepared.retained_path:
        raise RuntimeError("body presenter caption retained picture escaped its fixed caller path")
    identity = _picture_identity(retained["path"], retained["sizeBytes"])
    return RetainedBodyPresenterCaptionProof(held, retained, original, identity)


def finish_presenter_caption_body(value: RetainedBodyPresenterCaptionProof | None) -> dict | None:
    """Reinspect AFTER actual prefix, retention and caption completion; never rebaseline."""
    if value is None:
        return None
    held, retained = value.held, value.retained
    prepared = held.prepared
    check_presenter_caption_body(prepared)
    check_presenter_caption_body_proof(held)
    verify_presenter_caption_clearance(prepared.clearance, prepared.report, prepared.context.presenter.assert_current)
    check_presenter_caption_body(prepared)
    result = body_presenter_caption_picture_record(prepared.report, held.proof, retained, prepared.pages)
    check_presenter_caption_body_proof(held)
    if not same_read_metadata(retained, value.metadata) \
            or _picture_identity(retained["path"], retained["sizeBytes"]) != value.identity:
        raise RuntimeError("body presenter caption retained picture changed during verification")
    _check_owner(prepared.original[4])
    return result
