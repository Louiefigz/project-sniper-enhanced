"""Bounded frozen graph projections for legacy and explicit presenter proofs.

The legacy hash domain and output policy are unchanged when presenter is None.
Presenter graphs require a new domain covering full original declarations and
held asset identities; a clip-only hash cannot authenticate that extra work.
"""
from __future__ import annotations

import copy
import json
from dataclasses import asdict, dataclass, replace

from cross_runtime_canonical_json import canonical_compact_json
from graphics.composite_core import caption_layer_policy
from graphics.presenter_layout_graph import PresenterGraphSpec
from opening_prefix_contract import (CompositorPrefixRequest, HeldPrefixInput, PrefixClock,
                                     MAX_GRAPH_BYTES, PrefixOracleError, canonical_hash)
from opening_prefix_presenter import presenter_for_role, presenter_layer_policy, presenter_graph_payload


@dataclass(frozen=True)
class PresenterGraphLane:
    """Projection arguments only; not a parsed request or live execution owner."""

    clips: tuple[dict, ...]
    caption_tail: int | None
    spec: PresenterGraphSpec | None
    inputs: tuple[HeldPrefixInput, ...]


@dataclass(frozen=True)
class PresenterGraphProjection:
    """Already-validated graph data only; this type grants no executable owner."""

    clips: tuple[dict, ...]
    caption_tail: int | None
    payload: dict | None
    inputs: tuple[HeldPrefixInput, ...]


def presenter_projection_record(clock: PrefixClock, base: HeldPrefixInput, lane: PresenterGraphProjection) -> dict:
    """Share the exact live/read hash domain without rehydrating an execution owner."""
    inventory = {row.path: row for row in lane.inputs}
    paths = dict.fromkeys(row["asset"]["path"] for row in lane.payload["windows"]) if lane.payload is not None else {}
    return {"schemaVersion": 2, "kind": "held-presenter-compositor-graph",
        "clock": asdict(clock), "base": asdict(base), "clips": list(lane.clips),
        "captionTail": lane.caption_tail, "presenter": lane.payload,
        "presenterInputs": [asdict(inventory[path]) for path in paths]}


def presenter_graph_record(clock: PrefixClock, base: HeldPrefixInput, lane: PresenterGraphLane) -> dict:
    """Construct the shared hash domain from independently held caller values."""
    return presenter_projection_record(clock, base, PresenterGraphProjection(
        lane.clips, lane.caption_tail, presenter_graph_payload(lane.spec), lane.inputs))


def graph_projection(request: CompositorPrefixRequest, role: str) -> object:
    """Preserve old clip-only hashes or bind the whole new role-specific graph."""
    clips = request.full_clips if role == "full" else request.opening_clips
    if request.presenter is None:
        return list(clips)
    tail = request.caption_tail[0 if role == "full" else 1] if request.caption_tail is not None else None
    return presenter_graph_record(request.clock, request.base, PresenterGraphLane(
        clips, tail, presenter_for_role(request, role), request.presenter.assets))


def graph_hash(request: CompositorPrefixRequest, role: str) -> str:
    """Hash the complete validated graph in its explicit versioned domain."""
    return canonical_hash(graph_projection(request, role))


def freeze_request(request: CompositorPrefixRequest) -> CompositorPrefixRequest:
    """Detach both mutable clip JSON and all caller-owned presenter objects."""
    graphs = json.loads(canonical_compact_json([list(request.full_clips), list(request.opening_clips)]))
    presenter = request.presenter
    if presenter is not None:
        presenter = replace(presenter, full=copy.deepcopy(presenter.full), opening=copy.deepcopy(presenter.opening))
    return replace(request, full_clips=tuple(graphs[0]), opening_clips=tuple(graphs[1]), presenter=presenter)


def proof_header(request: CompositorPrefixRequest, composition: bool = False) -> dict:
    """A presenter result cannot masquerade as a legacy proof or encoded receipt."""
    if request.presenter is None:
        kind = "verified-prefix-private-picture-composition" if composition else "compositor-prefix-oracle"
        return {"schemaVersion": 1, "kind": kind}
    kind = "verified-presenter-prefix-private-picture-composition" if composition else "presenter-compositor-prefix-oracle"
    return {"schemaVersion": 2, "kind": kind}


def graph_layer_policy(request: CompositorPrefixRequest) -> dict:
    """The old optional policy is emitted only for the unchanged legacy graph."""
    return caption_layer_policy(request.caption_tail) if request.presenter is None else presenter_layer_policy(request)


def assert_presenter_graph_proof(request: CompositorPrefixRequest, proof: dict) -> None:
    """The actual new encoder cannot accept a legacy or different presenter oracle."""
    if request.presenter is None:
        return
    expected = {**proof_header(request), **graph_layer_policy(request), "status": "verified",
                "fullGraphHash": graph_hash(request, "full"), "openingGraphHash": graph_hash(request, "opening")}
    if any(canonical_hash(proof.get(key)) != canonical_hash(value) for key, value in expected.items()):
        raise PrefixOracleError("prefix presenter composition requires its exact schema2 graph proof")


def bounded_graph_json(value: object) -> bytes:
    """Preflight allocations before serializing exact finite graph metadata."""
    pending, nodes, size = [(value, 0)], 0, 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if depth > 12 or nodes > 32768 or size > MAX_GRAPH_BYTES:
            raise PrefixOracleError("prefix graph JSON exceeds its structural bound")
        children, added = _json_items(item, len(pending))
        size += added
        pending.extend((child, depth + 1) for child in children)
    if size > MAX_GRAPH_BYTES:
        raise PrefixOracleError("prefix graph strings exceed their byte bound")
    raw = canonical_compact_json(value).encode()
    if len(raw) > MAX_GRAPH_BYTES:
        raise PrefixOracleError("prefix graph exceeds 512 KiB")
    return raw


def _json_items(item: object, pending: int) -> tuple[list, int]:
    """Bound each allocation before appending children or encoding a string."""
    if isinstance(item, str):
        if len(item) > MAX_GRAPH_BYTES:
            raise PrefixOracleError("prefix graph string exceeds its byte bound")
        return [], len(item.encode("utf-8"))
    if not isinstance(item, (dict, list)):
        return [], 0
    if len(item) > 32768 or pending + 2 * len(item) > 32768:
        raise PrefixOracleError("prefix graph collection exceeds its structural bound")
    return (list(item.keys()) + list(item.values()) if isinstance(item, dict) else item), 0
