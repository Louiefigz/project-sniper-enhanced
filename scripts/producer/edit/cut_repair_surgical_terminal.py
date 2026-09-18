#!/usr/bin/env python3
"""Stage a proved picture-repair composite as a governed terminal graph."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from compile_timeline import compile_plan
from current_render_graph_contract import (
    classify_nodes,
    file_hash,
    object_hash,
)
from current_render_graph_store import (
    load_active,
    stage_candidate,
    verify_artifacts,
)
from current_render_graph_source_gate import verify_graph_source_authority
from edit.cut_repair_surgical_contract import (
    SurgicalTerminalAuthority,
    SurgicalTerminalError,
    load_surgical_terminal_authority,
)
from edit.cut_repair_surgical_graph import (
    SurgicalGraphInput,
    build_surgical_graph,
    build_terminal_receipt,
)
from edit.picture_lock_common import canonical_json, content_hash


@dataclass(frozen=True)
class SurgicalStageRequest:
    """Canonical CLI paths for one private candidate staging attempt."""

    producer_dir: Path
    plan_path: Path
    manifest_path: Path
    prepared_path: Path
    candidate_path: Path
    artifact_dir: Path


def _canonical_directory(path: Path, label: str) -> Path:
    absolute = Path(os.path.abspath(path))
    if absolute != path or absolute.is_symlink() or not absolute.is_dir() \
            or absolute.resolve() != absolute:
        raise SurgicalTerminalError(f"{label} is not a canonical directory")
    return absolute


def _layout(
    producer: Path,
    artifact_dir: Path,
    candidate: Path,
) -> tuple[Path, Path, Path]:
    producer = _canonical_directory(producer, "producer")
    artifacts = _canonical_directory(artifact_dir, "artifact directory")
    staging = producer / ".sniper-cut-repair-staging"
    if os.path.commonpath((str(staging), str(artifacts))) != str(staging):
        raise SurgicalTerminalError(
            "surgical terminal artifacts escaped cut-repair staging")
    expected = artifacts / candidate.name
    if not candidate.is_absolute() or candidate != expected:
        raise SurgicalTerminalError(
            "surgical terminal candidate must be in artifact directory")
    return (
        producer, artifacts / "timeline_map.json",
        artifacts / "cut_repair_surgical_terminal_receipt.json",
    )


def _atomic_json(path: Path, value: object) -> None:
    payload = (canonical_json(value) + "\n").encode("utf-8")
    if os.path.lexists(path):
        if path.is_symlink() or not path.is_file() \
                or path.read_bytes() != payload:
            raise SurgicalTerminalError(
                f"immutable surgical artifact changed: {path.name}")
        return
    descriptor, staged = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged, path)
        _fsync_directory(path.parent)
    finally:
        try:
            os.unlink(staged)
        except FileNotFoundError:
            pass


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _exact_copy(source: Path, candidate: Path, expected: str) -> None:
    if os.path.lexists(candidate):
        if candidate.is_symlink() or not candidate.is_file() \
                or file_hash(candidate) != expected:
            raise SurgicalTerminalError("surgical candidate path is occupied")
        return
    descriptor, staged = tempfile.mkstemp(
        prefix=f".{candidate.name}.", suffix=".tmp", dir=candidate.parent)
    os.close(descriptor)
    staged_path = Path(staged)
    try:
        before = file_hash(source)
        shutil.copyfile(source, staged_path)
        with staged_path.open("rb") as handle:
            os.fsync(handle.fileno())
        if before != expected or file_hash(source) != expected \
                or file_hash(staged_path) != expected:
            raise SurgicalTerminalError(
                "proved composite changed during exact copy")
        os.replace(staged_path, candidate)
        _fsync_directory(candidate.parent)
    finally:
        try:
            staged_path.unlink()
        except FileNotFoundError:
            pass


def _active_parent(
    previous: tuple[dict[str, Any], dict[str, Any]] | None,
    authority: SurgicalTerminalAuthority,
) -> dict[str, Any]:
    if previous is None:
        raise SurgicalTerminalError(
            "SURGICAL_TERMINAL_ACTIVE_PARENT_REQUIRED")
    graph, receipt = previous
    verify_artifacts(graph, receipt)
    verify_graph_source_authority(graph, receipt)
    root_id = graph["rootNodeId"]
    roots = [row for row in graph["nodes"] if row["nodeId"] == root_id]
    artifacts = [
        row for row in receipt["artifacts"] if row["nodeId"] == root_id]
    expected = authority.composite["inputs"]["parentSha256"]
    if len(roots) != 1 or len(artifacts) != 1:
        raise SurgicalTerminalError(
            "surgical ACTIVE parent has no unique root media")
    root, artifact = roots[0], artifacts[0]
    if root.get("kind") != "final-export" \
            or root.get("outputArtifactHash") != expected \
            or artifact.get("sha256") != expected \
            or root.get("inputDigests", {}).get("final.plan") \
            != authority.parent_plan_content_hash:
        raise SurgicalTerminalError(
            "SURGICAL_TERMINAL_ACTIVE_PARENT_MISMATCH")
    return {
        "graphHash": object_hash(graph),
        "receiptHash": object_hash(receipt),
        "rootNodeId": root_id,
        "rootArtifactPath": artifact["path"],
        "rootMediaSha256": expected,
        "rootPlanContentHash": authority.parent_plan_content_hash,
    }


def stage(request: SurgicalStageRequest) -> dict[str, Any]:
    """Exact-copy proved media and stage its dependency-closed graph."""
    producer, timeline_path, terminal_path = _layout(
        request.producer_dir, request.artifact_dir, request.candidate_path)
    authority = load_surgical_terminal_authority(
        request.plan_path, request.manifest_path, request.prepared_path)
    previous = load_active(producer)
    parent = _active_parent(previous, authority)
    _exact_copy(
        authority.composite_path, request.candidate_path,
        authority.candidate_hash)
    _atomic_json(timeline_path, compile_plan(authority.plan).to_dict())
    terminal = build_terminal_receipt(
        authority, request.candidate_path, parent)
    _atomic_json(terminal_path, terminal)
    graph, artifacts = build_surgical_graph(SurgicalGraphInput(
        producer, request.plan_path, request.manifest_path,
        request.candidate_path, timeline_path, authority, terminal))
    dirty, reused = classify_nodes(graph, previous, False)
    receipt = {
        "schemaVersion": 1, "kind": "current-render-graph-execution",
        "graphHash": object_hash(graph), "executionMode": "incremental",
        "previousGraphHash": object_hash(previous[0]) if previous else None,
        "dirtyNodeIds": dirty, "reusedNodeIds": reused,
        "artifacts": artifacts,
    }
    graph_hash = stage_candidate(
        producer, graph, receipt, request.candidate_path)
    return {
        "status": "render_graph_candidate_staged",
        "graphHash": graph_hash, "receiptHash": object_hash(receipt),
        "terminalReceiptHash": content_hash(terminal),
        "terminalReceiptPath": str(terminal_path),
        "candidateSha256": authority.candidate_hash,
        "candidatePath": str(request.candidate_path),
        "previousGraphHash": parent["graphHash"],
        "previousReceiptHash": parent["receiptHash"],
        "parentMediaSha256": parent["rootMediaSha256"],
        "dirtyNodeIds": dirty, "reusedNodeIds": reused,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--producer-dir", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--prepared", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--artifact-dir", required=True, type=Path)
    return parser


def main() -> int:
    """CLI with one closed success event and one typed failure event."""
    try:
        args = _parser().parse_args()
        value = stage(SurgicalStageRequest(
            args.producer_dir, args.plan, args.manifest, args.prepared,
            args.candidate, args.artifact_dir))
        print(json.dumps(value, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        print(json.dumps({
            "status": "render_graph_failed", "error": str(exc),
        }, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
