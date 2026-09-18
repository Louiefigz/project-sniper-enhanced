"""Shared node construction and terminal dependencies of the current renderer.

Legacy inputs retain their existing digest domains. An explicitly admitted
source-float program contributes additional final audio digests; it does not
reinterpret the old base or final plan hashes as source-audio authority.
The graph builder adds the existing dialogue-stem kind and requires it at the
composite edge, so invalidation remains dependency-closed in the V1 contract.
"""
from __future__ import annotations

from typing import Any

from current_render_graph_contract import object_hash
from fingerprints import plan_content_hash


def node(node_id: str, kind: str, dependencies: list[str], binding: tuple) -> dict[str, Any]:
    """Construct the existing closed graph node shape without inventing authority."""
    inputs, artifact, frame_range = binding
    return {"nodeId": node_id, "kind": kind, "dependencies": dependencies,
        "inputDigests": inputs, "outputArtifactHash": artifact["sha256"], "frameRange": frame_range}


def binding(inputs: dict[str, str], artifact: dict[str, Any],
            frame_range: dict[str, int] | None = None) -> tuple:
    """Group input digests, exact output artifact and optional frame interval."""
    return inputs, artifact, frame_range


def terminal_nodes(plan: dict, item: dict, dependencies: list[str]) -> list[dict]:
    """Keep visual composition and full-program mastering as explicit dependencies."""
    roots = item["roots"]
    composite = node("node-composite", "composite-window", dependencies,
        binding({"composite.plan": object_hash({
            "graphicsTrack": plan.get("graphicsTrack") or [], "captionsTrack": plan.get("captionsTrack")}),
            "composite.stageRoot": roots["plan.composite"]}, item["composite"]))
    audio = item["audio"]["finalInputs"] if item.get("audio") is not None else {}
    final = node("node-final", "final-export", ["node-composite"], binding({
        "final.plan": plan_content_hash(plan), "final.stageRoot": roots["plan.final"],
        "final.manifestStageRoot": roots["manifest.final"], **audio}, item["final"]))
    return [composite, final]


def source_nodes(plan: dict, item: dict) -> list[dict]:
    """Build source/timeline/base nodes; legacy input domains are unchanged.

    An admitted source-float program (``item["audio"]``) finishes audio in the
    retained float master, so its timeline/base digests use the finishing-free
    lineage projection: a finishing-only revision leaves them clean. The final
    node changes; composite also reads dirty when its artifact is the same
    audio-bearing final file. Legacy graphs keep the full digest."""
    from cut_delivery_authority import base_plan_lineage_digest
    roots = item["roots"]
    policy = "source-float-v2" if item.get("audio") is not None else "legacy-v1"
    lineage = base_plan_lineage_digest(plan, policy)
    return [
        node("node-source", "source-snapshot", [], binding(item["sourceInputs"], item["source"])),
        node("node-timeline", "timeline-map", ["node-source"], binding({
            "timeline.plan": lineage, "timeline.stageRoot": roots["plan.timeline"]}, item["timeline"])),
        node("node-base", "base-segment", ["node-source", "node-timeline"], binding({
            "base.plan": lineage, "base.stageRoot": roots["plan.base"],
            "base.manifestStageRoot": roots["manifest.base"]}, item["base"]))]
