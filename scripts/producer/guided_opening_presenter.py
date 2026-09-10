"""Live original presenter graph at the existing opening composition boundary.

This internal opt-in does not select a public profile or grant caption/creative
approval. The caller authenticates the exact request and preparation. A range
record is actual invocation evidence, not the separate body prefix oracle.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from functools import partial

from cut_preview_io import digest
from graphics.presenter_layout_graph import PresenterGraphSpec
from guided_opening_inputs import OpeningInputs
from guided_presenter_execution import OwnedPresenterExecution
from guided_presenter_probe_identity import presenter_stat_identity
from opening_prefix_contract import HeldPrefixInput, PrefixClock, canonical_hash, verify_held_input
from opening_prefix_graphs import PresenterGraphLane, bounded_graph_json, presenter_graph_record
from opening_prefix_presenter import _observation_record, presenter_graph_payload


@dataclass(frozen=True)
class OpeningPresenterContext:
    """Actual live observation owner, original plan and independently held base."""

    owner: OwnedPresenterExecution
    plan: dict
    base: HeldPrefixInput
    inputs: OpeningInputs | None = None


@dataclass(frozen=True)
class OpeningPictureContext:
    """Optional new lane; the historical tuple keeps its exact result shape."""

    root: Path
    authority: dict
    tools: dict
    presenter: OpeningPresenterContext | None = None


def _range_projection(context: OpeningPresenterContext, authority: dict,
                      clips: tuple[dict, ...], tail: int | None) -> tuple[PresenterGraphSpec | None, dict]:
    """Keep crossing and future original geometry, with no shortened exit ramp."""
    if type(context) is not OpeningPresenterContext or type(context.owner) is not OwnedPresenterExecution:
        raise RuntimeError("opening presenter requires an actual live observation owner")
    owner = context.owner
    owner.assert_plan(context.plan)
    if digest(context.plan) != authority["candidatePlanHash"]:
        raise RuntimeError("opening presenter plan differs from actual candidate authority")
    clock = PrefixClock(authority["frameRate"], authority["totalFrames"],
                        authority["target"]["width"], authority["target"]["height"])
    owner.assert_clock((clock.width, clock.height), (clock.frame_rate, clock.total_frames))
    spans = [authority[name] for name in ("core", "review")]
    if any(type(row) is not dict or set(row) != {"startFrame", "endFrameExclusive"}
            or type(row["startFrame"]) is not int or row["startFrame"] != 0
            or type(row["endFrameExclusive"]) is not int or not 0 < row["endFrameExclusive"] <= clock.total_frames
            for row in spans) or spans[0]["endFrameExclusive"] > spans[1]["endFrameExclusive"]:
        raise RuntimeError("opening presenter requires exact original origin core/review ranges")
    pair = owner.prefix_graphs(spans[1]["endFrameExclusive"])
    graph = presenter_graph_record(clock, context.base, PresenterGraphLane(clips, tail, pair.opening, pair.assets))
    bounded_graph_json(graph)
    record = {"schemaVersion": 1, "kind": "live-presenter-opening-range-composition",
        "scope": "actual-opening-graph-not-body-prefix-caption-clearance-or-approval",
        "candidatePlanHash": authority["candidatePlanHash"], "authorityHash": digest(authority),
        "graph": graph, "graphHash": canonical_hash(graph),
        "fullPresenterGraphHash": canonical_hash(presenter_graph_payload(pair.full)),
        "layerPolicy": "held-presenter-then-graphics-then-caption-pages-v1",
        "deliveryApproved": False, "captionClearanceVerified": False}
    return deepcopy(pair.opening), record


def _graph(context: OpeningPresenterContext, authority: dict,
           clips: tuple[dict, ...], tail: int | None) -> tuple[PresenterGraphSpec | None, dict]:
    """Hash retained raw probe JSON once; subsequent guards use immutable ownership."""
    graph, record = _range_projection(context, authority, clips, tail)
    return graph, {**record, "observations": [_observation_record(row) for row in context.owner.observed]}


def _unchanged(context: OpeningPresenterContext, geometry: tuple,
               original: tuple, arguments: tuple) -> None:
    """Check live ownership, original metadata and the base's same-read identity."""
    graph, record = geometry
    identity, binding, graph_hash, record_hash = original
    authority, clips, tail = arguments
    context.owner.assert_plan(context.plan)
    if digest([authority, list(clips), tail]) != binding or canonical_hash(presenter_graph_payload(graph)) != graph_hash \
            or canonical_hash(record) != record_hash:
        raise RuntimeError("opening presenter range graph or original arguments changed")
    current, expected = _range_projection(context, authority, clips, tail)
    original_projection = {key: value for key, value in record.items() if key != "observations"}
    if canonical_hash(presenter_graph_payload(current)) != graph_hash \
            or canonical_hash(expected) != canonical_hash(original_projection):
        raise RuntimeError("opening presenter range lost original held observations")
    if presenter_stat_identity(Path(context.base.path).lstat()) != identity:
        raise RuntimeError("opening presenter held base changed after byte verification")
    context.owner.runtime.deadline.remaining()


@contextmanager
def held_presenter_ranges(base: Path, context: OpeningPresenterContext, authority: dict,
                          layers: tuple[tuple[dict, ...], int | None]) -> Iterator[tuple]:
    """Hold a real base hash once and fence both range encodes under the original clock."""
    clips, tail = layers
    graph, record = _graph(context, authority, clips, tail)
    if type(context.base) is not HeldPrefixInput or context.base.path != str(base):
        raise RuntimeError("opening presenter base is not its independently held preparation")
    identity = verify_held_input(context.base, context.owner.runtime.deadline)
    original = (identity, digest([authority, list(clips), tail]), canonical_hash(presenter_graph_payload(graph)), canonical_hash(record))
    arguments = authority, clips, tail
    geometry = graph, record
    _unchanged(context, geometry, original, arguments)
    yield graph, record, partial(_unchanged, context, geometry, original, arguments)
    _unchanged(context, geometry, original, arguments)
