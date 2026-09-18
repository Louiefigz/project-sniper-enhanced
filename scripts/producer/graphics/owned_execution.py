"""Internal owned-assembly hooks, never a JSON renderer or approval capability.

The executable body owner supplies these functions after admitting its exact
source, full plan, runtime and deadline. This seam keeps ordinary placement and
QC in the assembler; it does not establish those caller-owned facts itself.
"""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, replace
from typing import Any, Callable

from cross_runtime_canonical_json import canonical_compact_json
from graphics.composite_core import CompositeOptions
from opening_prefix_contract import canonical_hash
from guided_caption_execution import OwnedCaptionExecution
from guided_presenter_execution import OwnedPresenterExecution


@dataclass(frozen=True)
class GraphicsComposition:
    """Actual ordinary resolved graph, before any encode or delivery decision."""

    video_in: str
    video_out: str
    clips: tuple[dict, ...]
    options: CompositeOptions
    canvas: tuple[int, int]
    frame_clock: tuple[str, int]
    caption_clips: tuple[dict, ...] = ()
    presenter: OwnedPresenterExecution | None = None


@dataclass(frozen=True)
class OwnedGraphicsExecution:
    """Only an internal live owner can provide render/composition/guard calls."""

    render: Callable[[dict, int], dict]
    compose: Callable[[GraphicsComposition], dict]
    assert_current: Callable[[], None]
    captions: OwnedCaptionExecution | None = None
    presenter: OwnedPresenterExecution | None = None


def current(job: Any) -> OwnedGraphicsExecution | None:
    """Check the live hook without adding authority to ordinary unowned jobs."""
    execution = getattr(job, "owned_graphics", None)
    if execution is None:
        return None
    if type(execution) is not OwnedGraphicsExecution:
        raise RuntimeError("owned graphics requires the internal execution object")
    if execution.captions is not None and type(execution.captions) is not OwnedCaptionExecution:
        raise RuntimeError("owned captions requires the live internal completion object")
    if execution.presenter is not None and type(execution.presenter) is not OwnedPresenterExecution:
        raise RuntimeError("owned presenter requires the live internal observation owner")
    execution.assert_current()
    if execution.presenter is not None:
        execution.presenter.assert_current()
    return execution


def require_held_assembly(job: Any) -> None:
    """No hook may enter the legacy or unheld public assembly path."""
    if getattr(job, "owned_graphics", None) is None:
        if type(getattr(job, "plan", None)) is dict and "presenterLayouts" in job.plan:
            raise RuntimeError("presenter plan cannot use an unowned assembly path")
        return
    if not job.held_program_selection or job.audio_clock_policy != "source-float-v2" \
            or job.graphic_frame_clock is None or job.audio_only:
        raise RuntimeError("owned graphics requires exact held source-float-v2 assembly")
    execution = current(job)
    if execution.presenter is not None:
        execution.presenter.assert_plan(job.plan)
    elif type(getattr(job, "plan", None)) is dict and "presenterLayouts" in job.plan:
        raise RuntimeError("presenter plan lacks its actual live observation owner")


def render_owned(execution: OwnedGraphicsExecution, entry: dict, order: int) -> dict:
    """Preserve original order/content; a failed owned render never falls back."""
    execution.assert_current()
    original = canonical_compact_json(entry)
    supplied = copy.deepcopy(entry)
    result = execution.render(supplied, order)
    execution.assert_current()
    if canonical_compact_json(entry) != original or canonical_compact_json(supplied) != original:
        raise RuntimeError("owned graphic renderer changed its exact candidate entry")
    if type(result) is not dict or not {"path", "kind", "key", "fmt", "cached"}.issubset(result):
        raise RuntimeError("owned graphic renderer did not return an ordinary asset result")
    return result


def _full_graph_hash(value: GraphicsComposition, proof: dict) -> str:
    """Use one graph identity constructor for the oracle and the live caller."""
    if value.presenter is None:
        return canonical_hash([*value.clips, *value.caption_clips])
    from opening_prefix_contract import HeldPrefixInput, PrefixClock
    from opening_prefix_graphs import PresenterGraphLane, presenter_graph_record

    inputs = proof.get("inputs")
    if type(inputs) is not list or not inputs or type(inputs[0]) is not dict \
            or set(inputs[0]) != {"path", "sha256", "size_bytes"}:
        raise RuntimeError("owned presenter proof lacks its exact observed base reference")
    assets = value.presenter.held_assets()
    tool = value.presenter.runtime.ffprobe
    references = (*assets, HeldPrefixInput(tool.path, tool.sha256, tool.size_bytes))
    if any(type(row) is not dict for row in inputs) or any(canonical_compact_json(
            [row for row in inputs if row.get("path") == ref.path]) != canonical_compact_json([asdict(ref)])
            for ref in references):
        raise RuntimeError("owned presenter proof lost its exact observed asset/tool inventory")
    lane = PresenterGraphLane((*value.clips, *value.caption_clips), len(value.caption_clips) or None,
                              value.options.presenter, assets)
    clock = PrefixClock(*value.frame_clock, *value.canvas)
    return canonical_hash(presenter_graph_record(clock, HeldPrefixInput(**inputs[0]), lane))


def _layer_evidence(proof: dict, value: GraphicsComposition) -> None:
    """A caption-only policy cannot authenticate a presenter graph beneath it."""
    policy = proof.get("layerPolicy")
    if value.presenter is not None:
        keys = {"kind", "fullPresenterWindows", "openingPresenterWindows", "fullCaptionTail", "openingCaptionTail"}
        if type(policy) is not dict or set(policy) != keys \
                or policy["kind"] != "held-presenter-then-graphics-then-caption-pages-v1" \
                or type(policy["fullPresenterWindows"]) is not int \
                or policy["fullPresenterWindows"] != len(value.options.presenter.windows) \
                or type(policy["fullCaptionTail"]) is not int or policy["fullCaptionTail"] != len(value.caption_clips):
            raise RuntimeError("owned presenter proof lost its exact combined layer binding")
        return
    if value.caption_clips:
        if type(policy) is not dict or set(policy) != {"kind", "fullCaptionTail", "openingCaptionTail"} \
                or policy["kind"] != "graphics-then-held-caption-pages-v1" \
                or type(policy["fullCaptionTail"]) is not int or policy["fullCaptionTail"] != len(value.caption_clips):
            raise RuntimeError("owned compositor proof lost its exact caption-tail binding")
    elif policy is not None:
        raise RuntimeError("uncaptioned owned compositor acquired an unqualified caption tail")


def _composition_evidence(result: dict, value: GraphicsComposition) -> None:
    """A genuine proof for a different full graph is not this assembly's proof.

    Input bytes remain independently held by the execution owner and adapter;
    this seam binds their observed base path, exact graph and clock to the call.
    It does not turn returned JSON into independent source or approval authority.
    """
    composition_kind = "verified-presenter-prefix-private-picture-composition" if value.presenter \
        else "verified-prefix-private-picture-composition"
    oracle_kind = "presenter-compositor-prefix-oracle" if value.presenter else "compositor-prefix-oracle"
    if type(result) is not dict or result.get("kind") != composition_kind \
            or result.get("outputPath") != value.video_out or result.get("deliveryApproved") is not False:
        raise RuntimeError("owned compositor omitted its exact private picture evidence")
    proof, output = result.get("prefixOracle"), result.get("output")
    if type(proof) is not dict or type(output) is not dict or output.get("path") != value.video_out:
        raise RuntimeError("owned compositor omitted its graph-bound output evidence")
    expected_clock = {"frame_rate": value.frame_clock[0], "total_frames": value.frame_clock[1],
                      "width": value.canvas[0], "height": value.canvas[1]}
    inputs = proof.get("inputs")
    if value.presenter is not None and (type(result.get("schemaVersion")) is not int or result["schemaVersion"] != 2 \
            or type(proof.get("schemaVersion")) is not int or proof["schemaVersion"] != 2):
        raise RuntimeError("owned presenter requires the distinct schema2 combined graph proof")
    if proof.get("kind") != oracle_kind or proof.get("status") != "verified" \
            or proof.get("fullGraphHash") != _full_graph_hash(value, proof) \
            or canonical_compact_json(proof.get("clock")) != canonical_compact_json(expected_clock) \
            or type(inputs) is not list or not inputs or type(inputs[0]) is not dict \
            or inputs[0].get("path") != value.video_in:
        raise RuntimeError("owned compositor proof differs from the actual full graph, base or frame clock")
    _layer_evidence(proof, value)


def _composition_identity(value: GraphicsComposition) -> str:
    """Freeze actual presenter geometry alongside the existing mutable clip graph."""
    clips = [*value.clips, *value.caption_clips]
    if value.presenter is None:
        return canonical_compact_json(clips)
    from opening_prefix_presenter import presenter_graph_payload

    return canonical_compact_json({"clips": clips, "presenter": presenter_graph_payload(value.options.presenter)})


def compose_owned(execution: OwnedGraphicsExecution, value: GraphicsComposition) -> dict:
    """Bind the actual graph; smoothness is measured separately, not a missing tap."""
    execution.assert_current()
    if value.options.presenter is not None or value.presenter is not None:
        raise RuntimeError("caller-supplied presenter composition has no released held execution/proof owner")
    if value.caption_clips or value.options.caption_tail is not None:
        raise RuntimeError("ordinary graphics cannot supply serialized caption ownership")
    captions = execution.captions.clips() if execution.captions is not None else ()
    value = replace(value, caption_clips=captions)
    if execution.presenter is not None:
        if type(execution.presenter) is not OwnedPresenterExecution:
            raise RuntimeError("owned presenter requires the live internal observation owner")
        execution.presenter.assert_clock(value.canvas, value.frame_clock)
        value = replace(value, presenter=execution.presenter,
                        options=replace(value.options, presenter=execution.presenter.full_graph()))
    original = _composition_identity(value)
    supplied = replace(value, clips=tuple(copy.deepcopy(value.clips)),
                       caption_clips=tuple(copy.deepcopy(value.caption_clips)),
                       options=replace(value.options, ydif_file=None, presenter=copy.deepcopy(value.options.presenter)))
    result = execution.compose(supplied)
    execution.assert_current()
    if supplied.presenter is not execution.presenter or _composition_identity(value) != original \
            or _composition_identity(supplied) != original:
        raise RuntimeError("owned compositor changed the actual resolved graph")
    if execution.presenter is not None:
        execution.presenter.assert_current()
    _composition_evidence(result, value)
    return result
