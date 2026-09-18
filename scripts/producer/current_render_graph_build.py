"""Compile actual current-render artifacts into a strict RenderGraphV1."""
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction
from pathlib import Path
from typing import Any

from captions.caption_plan_pipeline import has_explicit_caption_track
from captions.caption_shard_contract import validate_caption_shard_manifest
from fingerprints import base_plan_digest, plan_content_hash
from graphics.template_contract import resolved_assets
from ingest_admission_contract import verify_source_set_binding
from media_probe import _fps_fraction, probe_video
from current_render_graph_contract import (
    classify_nodes,
    file_hash,
    object_hash,
    validate_graph,
)
from current_render_graph_inputs import (
    DEFAULT_CACHE,
    MOTION_ROOT,
    GraphBuildInputs,
)
from current_render_toolchain import current_toolchain_hash
from current_render_graph_audio import audio_graph_facts
from current_render_graph_nodes import binding as _binding, node as _node, source_nodes, terminal_nodes
from render_stage_roots import effective_scene_rows, stage_input_roots

PreviousGraph = tuple[dict[str, Any], dict[str, Any]] | None
GraphResult = tuple[dict[str, Any], list[dict[str, Any]]]


@dataclass(frozen=True)
class _SceneContext:
    rate: Fraction
    inputs: GraphBuildInputs
    events: list[dict[str, Any]]
    previous: tuple[dict[str, Any], dict[str, Any]] | None
    stage_roots: dict[str, str]


def _json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"{label} is not a regular file")
    value = json.loads(path.read_text(encoding="utf-8"))
    if type(value) is not dict:
        raise RuntimeError(f"{label} is not a JSON object")
    return value


def source_authority(inputs: GraphBuildInputs) -> tuple[dict[str, Any], Path]:
    """Reverify the admitted source set and return graph input hashes."""
    manifest = _json(inputs.manifest_path, "render manifest")
    plan = _json(inputs.plan_path, "render plan")
    entries = verify_source_set_binding(manifest, inputs.manifest_path.parent)
    binding = manifest["sourceSetAdmission"]
    receipt = inputs.manifest_path.parent / binding["receiptPath"]
    roots = stage_input_roots(plan, manifest, inputs.audio_clock_policy)
    digests = {
        "source.manifest": file_hash(inputs.manifest_path),
        "source.set": binding["sourceSetDigest"],
        "source.stageRoot": roots["manifest.source"],
    }
    for index, entry in enumerate(entries):
        digests[f"source.{index:04d}"] = entry["sha256"]
    return digests, receipt


def _artifact(node_id: str, path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"render node {node_id} produced no regular artifact")
    return {
        "nodeId": node_id, "path": str(path.resolve()),
        "sha256": file_hash(path), "sizeBytes": path.stat().st_size,
    }


def _frame(seconds: object, rate: Fraction) -> int:
    frames = Decimal(str(seconds)) * Decimal(rate.numerator) \
        / Decimal(rate.denominator)
    return int(frames.to_integral_value(rounding=ROUND_HALF_UP))


def _scene_rows(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row for row in events
        if row.get("stage") == "graphics"
        and row.get("status") in {"cached", "rendered"}
        and type(row.get("key")) is str and row.get("fmt") in {"mov", "mp4"}
    ]


def _scene_asset_digest(row: dict[str, Any]) -> str:
    comp = MOTION_ROOT / "compositions" / f"{row.get('kind')}.html"
    html = comp.read_text(encoding="utf-8")
    assets = resolved_assets(row, html)
    return object_hash([
        {"field": asset["field"], "sha256": file_hash(Path(asset["path"]))}
        for asset in assets
    ])


def _previous_artifacts(
    previous: tuple[dict[str, Any], dict[str, Any]] | None,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    if previous is None:
        return {}, {}
    graph, receipt = previous
    nodes = {row["nodeId"]: row for row in graph["nodes"]}
    artifacts = {row["nodeId"]: row for row in receipt["artifacts"]}
    return nodes, artifacts


def _scene_nodes(
    plan: dict[str, Any],
    context: _SceneContext,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    track = effective_scene_rows(plan)
    observed = _scene_rows(context.events)
    prior_nodes, prior_artifacts = _previous_artifacts(context.previous)
    nodes, artifacts = [], []
    rate = context.rate
    rate_hash = object_hash({"fps": f"{rate.numerator}/{rate.denominator}"})
    if observed and len(observed) != len(track):
        raise RuntimeError("graphics events do not cover every planned scene")
    for index, row in enumerate(track):
        node_id = f"node-scene-{index:04d}"
        row_inputs = {
            f"scene.{index:04d}.plan": object_hash(row),
            f"scene.{index:04d}.rate": rate_hash,
            f"scene.{index:04d}.assets": _scene_asset_digest(row),
            f"scene.{index:04d}.stageRoot":
                context.stage_roots[f"plan.scene.{index:04d}"],
        }
        event = observed[index] if observed else None
        prior = prior_nodes.get(node_id) if event is None else None
        if event is not None and event.get("kind") != row.get("kind"):
            raise RuntimeError("graphics event order disagrees with the plan")
        if event is None and (
                not prior or prior["inputDigests"] != row_inputs):
            raise RuntimeError("assemble returned no proof for a dirty scene")
        if event is None:
            artifact = prior_artifacts[node_id]
        else:
            artifact = _artifact(
                node_id,
                context.inputs.cache_dir / f"{event['key']}.{event['fmt']}")
        frame_range = {
            "startFrame": _frame(row["outStart"], rate),
            "endFrameExclusive": _frame(row["outEnd"], rate),
        }
        nodes.append(_node(
            node_id, "scene-unit", ["node-timeline"],
            _binding(row_inputs, artifact, frame_range)))
        artifacts.append(artifact)
    return nodes, artifacts


def _caption_nodes(
    plan: dict[str, Any],
    inputs: GraphBuildInputs,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not has_explicit_caption_track(plan):
        return [], []
    manifest_path = inputs.artifact_root / "caption_shards.json"
    manifest = validate_caption_shard_manifest(
        _json(manifest_path, "caption shard manifest"), inputs.artifact_root)
    nodes, artifacts = [], []
    for index, row in enumerate(manifest["entries"]):
        node_id = f"node-caption-{index:04d}"
        row_inputs = {
            f"caption.{index:04d}.{key}": row[key]
            for key in ("mediaKey", "placedShardKey", "contentAssetKey",
                        "rendererHash", "fontClosureHash")
        }
        row_inputs[f"caption.{index:04d}.cue"] = object_hash(row["cueId"])
        artifact = _artifact(node_id, inputs.artifact_root / row["media"]["name"])
        if artifact["sha256"] != row["media"]["sha256"]:
            raise RuntimeError("caption graph artifact disagrees with its manifest")
        nodes.append(_node(
            node_id, "caption-shard", ["node-source", "node-timeline"],
            _binding(row_inputs, artifact, {
                "startFrame": row["startFrame"],
                "endFrameExclusive": row["endFrameExclusive"],
            })))
        artifacts.append(artifact)
    return nodes, artifacts


def _render_artifacts(
    plan: dict[str, Any],
    inputs: GraphBuildInputs,
    events: list[dict[str, Any]],
    previous: PreviousGraph,
) -> dict[str, Any]:
    manifest = _json(inputs.manifest_path, "render manifest")
    roots = stage_input_roots(plan, manifest, inputs.audio_clock_policy)
    source_inputs, source_receipt = source_authority(inputs)
    timeline = inputs.artifact_root / "timeline_map.json"
    for path, label in ((timeline, "timeline"), (inputs.base_path, "base"),
                        (inputs.output_path, "final")):
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"current renderer did not produce {label}")
    rate = _fps_fraction(probe_video(str(inputs.base_path))["r_frame_rate"])
    scene_nodes, scene_files = _scene_nodes(
        plan, _SceneContext(rate, inputs, events, previous, roots))
    caption_nodes, caption_files = _caption_nodes(plan, inputs)
    composite_path = inputs.artifact_root / ".caption-free-composite.mp4"
    if not has_explicit_caption_track(plan) or not composite_path.is_file():
        composite_path = inputs.output_path
    return {
        "roots": roots, "sourceInputs": source_inputs,
        "source": _artifact("node-source", source_receipt),
        "timeline": _artifact("node-timeline", timeline),
        "base": _artifact("node-base", inputs.base_path),
        "sceneNodes": scene_nodes, "sceneFiles": scene_files,
        "captionNodes": caption_nodes, "captionFiles": caption_files,
        "audio": audio_graph_facts(inputs, plan, (events, previous)),
        "composite": _artifact("node-composite", composite_path),
        "final": _artifact("node-final", inputs.output_path),
    }


def compile_graph(
    inputs: GraphBuildInputs, events: list[dict[str, Any]],
    previous: PreviousGraph) -> GraphResult:
    """Bind actual base, scene, caption, composite, and final output bytes."""
    plan = _json(inputs.plan_path, "render plan")
    item = _render_artifacts(plan, inputs, events, previous)
    nodes = [*source_nodes(plan, item), *item["sceneNodes"], *item["captionNodes"]]
    dependencies = ["node-base"] + [
        row["nodeId"] for row in item["sceneNodes"] + item["captionNodes"]]
    if item["audio"] is not None:
        nodes.append(_node("node-dialogue", "dialogue-stem", ["node-source", "node-timeline"],
            _binding(item["audio"]["sourceInputs"], item["audio"]["artifact"])))
        dependencies.append("node-dialogue")
    nodes += terminal_nodes(plan, item, dependencies)
    graph = validate_graph({
        "schemaVersion": 1, "graphId": "current-render-"
        + object_hash(str(inputs.producer_dir))[:16],
        "toolchainHash": current_toolchain_hash(), "rootNodeId": "node-final",
        "nodes": nodes})
    artifacts = [
        item["source"], item["timeline"], item["base"], *item["sceneFiles"],
        *item["captionFiles"], item["composite"], item["final"]]
    if item["audio"] is not None:
        artifacts.append(item["audio"]["artifact"])
    return graph, artifacts
