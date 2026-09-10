#!/usr/bin/env python3
"""Execute the canonical current renderer through durable RenderGraphV1 gates."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from current_render_graph_build import (
    GraphBuildInputs,
    classify_nodes,
    compile_graph,
    source_authority,
)
from current_render_graph_arguments import RunConfig, parse_args as _parse
from current_render_graph_audio import audio_pending_facts, validate_audio_command, held_source_bus_hash
from audio.assemble_picture_reuse import picture_reuse_supported
from current_render_graph_contract import file_hash, object_hash
from current_render_graph_store import (
    clear_pending_base,
    load_active,
    publish,
    read_pending_base,
    stage_candidate,
    verify_artifacts,
    write_pending_base,
)
from current_render_toolchain import current_toolchain_hash
from cut_delivery_authority import base_plan_lineage_digest
from render_stage_roots import stage_input_roots
from stage_timing_context import timing_environment

_PENDING_KEYS = {
    "schemaVersion", "kind", "planSha256", "basePlanDigest",
    "manifestSha256", "sourceSetDigest", "toolchainHash",
    "outputSha256", "outputSizeBytes", "timelineSha256", "baseStageRoot",
    "manifestBaseStageRoot",
}
_AUDIO_PENDING_KEYS = {"audioClockPolicy", "sourceAudioBusPointerSha256", "sourceAudioBusReceiptHash"}
_MUTABLE_NODES = {"node-composite", "node-final"}
_BASE_HANDOFF_NODES = {"node-timeline", "node-base"} | _MUTABLE_NODES

def emit(**fields: object) -> None:
    """Emit one graph event on the renderer's existing NDJSON stream."""
    print(json.dumps(fields, sort_keys=True), flush=True)

def _document(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"{label} is not a regular file")
    value = json.loads(path.read_text(encoding="utf-8"))
    if type(value) is not dict:
        raise RuntimeError(f"{label} is not a JSON object")
    return value

def _pending_facts(
    config: RunConfig, rendered_output: Path, toolchain_hash: str, events: list[dict] | None = None,
) -> dict[str, Any]:
    plan_path = config.next_plan_path
    plan = _document(plan_path, "published render plan")
    manifest = _document(config.inputs.manifest_path, "render manifest")
    source_authority(config.inputs)
    policy = config.inputs.audio_clock_policy
    roots = stage_input_roots(plan, manifest, policy)
    timeline = config.inputs.artifact_root / "timeline_map.json"
    if rendered_output.is_symlink() or not rendered_output.is_file() \
            or timeline.is_symlink() or not timeline.is_file():
        raise RuntimeError("base stage produced no media or timeline authority")
    return {
        "schemaVersion": 2 if policy != "legacy-v1" else 1,
        "kind": "current-render-pending-base",
        "planSha256": file_hash(plan_path),
        "basePlanDigest": base_plan_lineage_digest(plan, policy),
        "baseStageRoot": roots["plan.base"],
        "manifestBaseStageRoot": roots["manifest.base"],
        "manifestSha256": file_hash(config.inputs.manifest_path),
        "sourceSetDigest": manifest["sourceSetAdmission"]["sourceSetDigest"],
        "toolchainHash": toolchain_hash,
        "outputSha256": file_hash(rendered_output),
        "outputSizeBytes": rendered_output.stat().st_size,
        "timelineSha256": file_hash(timeline),
        **audio_pending_facts(config.inputs, rendered_output, plan, events),
    }

def _valid_pending(config: RunConfig) -> bool:
    value = read_pending_base(config.inputs.producer_dir)
    if value is None:
        return False
    v2 = config.inputs.audio_clock_policy != "legacy-v1"
    keys = _PENDING_KEYS | (_AUDIO_PENDING_KEYS if v2 else set())
    if type(value) is not dict or set(value) != keys \
            or value["schemaVersion"] != (2 if v2 else 1) \
            or value["kind"] != "current-render-pending-base":
        raise RuntimeError("pending base handoff is malformed")
    plan = _document(config.inputs.plan_path, "render plan")
    manifest = _document(config.inputs.manifest_path, "render manifest")
    source_authority(config.inputs)
    policy = config.inputs.audio_clock_policy
    roots = stage_input_roots(plan, manifest, policy)
    timeline = config.inputs.artifact_root / "timeline_map.json"
    expected = {
        "planSha256": file_hash(config.inputs.plan_path),
        "basePlanDigest": base_plan_lineage_digest(plan, policy),
        "baseStageRoot": roots["plan.base"],
        "manifestBaseStageRoot": roots["manifest.base"],
        "manifestSha256": file_hash(config.inputs.manifest_path),
        "sourceSetDigest": manifest["sourceSetAdmission"]["sourceSetDigest"],
        "toolchainHash": current_toolchain_hash(),
        "outputSha256": file_hash(config.inputs.base_path),
        "outputSizeBytes": config.inputs.base_path.stat().st_size,
        "timelineSha256": file_hash(timeline),
        **audio_pending_facts(config.inputs, config.inputs.base_path, plan),
    }
    if any(value.get(key) != observed for key, observed in expected.items()):
        raise RuntimeError("pending base handoff does not bind current inputs")
    return True

def _preflight(
    config: RunConfig,
) -> tuple[tuple[dict[str, Any], dict[str, Any]] | None, bool, str]:
    source_authority(config.inputs)
    previous = load_active(config.inputs.producer_dir)
    pending = False
    if config.phase == "assemble":
        pending = _valid_pending(config)
    elif read_pending_base(config.inputs.producer_dir) is not None:
        pending = config.inputs.base_path.is_file()
    ignored = _BASE_HANDOFF_NODES if pending else _MUTABLE_NODES
    if previous:
        verify_artifacts(previous[0], previous[1], ignored)
    if config.force_full:
        if previous is not None and not pending:
            raise RuntimeError(
                "forced-full execution with prior state requires a fresh base")
        if config.inputs.cache_dir.exists() \
                and any(config.inputs.cache_dir.iterdir()):
            raise RuntimeError("forced-full execution requires an empty scene cache")
    emit(status="render_graph_preflight", phase=config.phase,
         previousGraphHash=object_hash(previous[0]) if previous else None,
         pendingBase=pending, forceFull=config.force_full)
    return previous, pending, current_toolchain_hash()


def _command(config: RunConfig) -> list[str]:
    command = list(config.command)
    if not command:
        raise RuntimeError("render graph bridge received no renderer command")
    if command[0].endswith(".py"):
        command.insert(0, sys.executable)
    if config.phase == "assemble" and config.inputs.audio_clock_policy == "source-float-v2":
        if any(value.startswith("--source-bus-receipt-hash") for value in command):
            raise RuntimeError("source-float child source authority is owned by the graph")
        command += ["--source-bus-receipt-hash", held_source_bus_hash(config.inputs)]
    return command


def _run_child(config: RunConfig) -> tuple[int, list[dict[str, Any]]]:
    process = subprocess.Popen(
        _command(config), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=None, text=True, bufsize=1, env=timing_environment())
    events: list[dict[str, Any]] = []
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="", flush=True)
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if type(row) is dict:
            events.append(row)
    return process.wait(), events


def _clean_graph_hit(
    config: RunConfig,
    previous: tuple[dict[str, Any], dict[str, Any]] | None,
    pending: bool,
    toolchain_hash: str,
) -> bool:
    """Reuse only exact outputs whose current consumed visual inputs are proved."""
    if config.phase != "assemble" or config.force_full \
            or config.defer_active or pending \
            or previous is None:
        return False
    if config.inputs.audio_clock_policy == "source-float-v2" \
            and not picture_reuse_supported(_document(config.inputs.plan_path, "render plan")):
        emit(status="render_graph_cache_declined", reason="visual-input-reuse-unqualified",
             note="fresh composite and full QC required for graphics or explicit captions")
        return False
    try:
        graph, _ = compile_graph(config.inputs, [], previous)
    except RuntimeError:
        return False
    if graph["toolchainHash"] != toolchain_hash:
        raise RuntimeError("render toolchain changed during graph preflight")
    dirty, reused = classify_nodes(graph, previous, False)
    if dirty or object_hash(graph) != object_hash(previous[0]):
        return False
    emit(status="render_graph_cache_hit", graphHash=object_hash(graph),
         reusedNodeIds=reused, note="all current renderer outputs rehashed")
    return True


def _commit_base(config: RunConfig, toolchain_hash: str, events: list[dict]) -> None:
    facts = _pending_facts(config, config.inputs.output_path, toolchain_hash, events)
    write_pending_base(config.inputs.producer_dir, facts)
    emit(status="render_graph_base_handoff", outputSha256=facts["outputSha256"],
         timelineSha256=facts["timelineSha256"])


def _commit_assemble(
    config: RunConfig,
    events: list[dict[str, Any]],
    previous: tuple[dict[str, Any], dict[str, Any]] | None,
    toolchain_hash: str,
) -> None:
    graph, artifacts = compile_graph(config.inputs, events, previous)
    if graph["toolchainHash"] != toolchain_hash:
        raise RuntimeError("render toolchain changed during execution")
    dirty, reused = classify_nodes(graph, previous, config.force_full)
    receipt = {
        "schemaVersion": 1, "kind": "current-render-graph-execution",
        "graphHash": object_hash(graph),
        "executionMode": "forced-full" if config.force_full else "incremental",
        "previousGraphHash": object_hash(previous[0]) if previous else None,
        "dirtyNodeIds": dirty, "reusedNodeIds": reused,
        "artifacts": artifacts,
    }
    if config.defer_active:
        graph_hash = stage_candidate(
            config.inputs.producer_dir, graph, receipt,
            config.inputs.output_path)
        status = "render_graph_candidate_staged"
    else:
        graph_hash = publish(config.inputs.producer_dir, graph, receipt)
        status = "render_graph_committed"
    clear_pending_base(config.inputs.producer_dir)
    emit(status=status, graphHash=graph_hash,
         dirtyNodeIds=dirty, reusedNodeIds=reused)


def execute(config: RunConfig) -> int:
    """Preflight immutable dependencies, run real media work, then commit."""
    validate_audio_command(config.inputs.audio_clock_policy, config.command)
    previous, pending, toolchain_hash = _preflight(config)
    if _clean_graph_hit(config, previous, pending, toolchain_hash):
        return 0
    code, events = _run_child(config)
    if code:
        emit(status="render_graph_child_failed", phase=config.phase, exitCode=code)
        return code
    if current_toolchain_hash() != toolchain_hash:
        raise RuntimeError("render toolchain changed during execution")
    source_authority(config.inputs)
    if config.phase == "base":
        _commit_base(config, toolchain_hash, events)
    else:
        _commit_assemble(config, events, previous, toolchain_hash)
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point with one typed error surface."""
    try:
        return execute(_parse(argv))
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        emit(error=str(exc), status="render_graph_failed")
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
