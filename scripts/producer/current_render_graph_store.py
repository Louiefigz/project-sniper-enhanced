"""Crash-safe generation store for the current-render RenderGraphV1 bridge."""
from __future__ import annotations

import json
import os
import re
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from current_render_graph_contract import (
    ACTIVE_NAME,
    GRAPH_DIR,
    PENDING_BASE_NAME,
    canonical_bytes,
    file_hash,
    object_hash,
    validate_graph,
    validate_receipt,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _store(producer_dir: Path) -> Path:
    path = producer_dir / GRAPH_DIR
    if path.is_symlink() or path.exists() and not path.is_dir():
        raise RuntimeError("render graph store is not a regular directory")
    return path


def _generations(producer_dir: Path) -> Path:
    path = _store(producer_dir) / "generations"
    if path.is_symlink() or path.exists() and not path.is_dir():
        raise RuntimeError("render graph generations is not a regular directory")
    return path


def _candidates(producer_dir: Path) -> Path:
    path = _store(producer_dir) / "candidates"
    if path.is_symlink() or path.exists() and not path.is_dir():
        raise RuntimeError("render graph candidates is not a regular directory")
    return path


def _write_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, staged = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_bytes(value) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        try:
            os.unlink(staged)
        except FileNotFoundError:
            pass


def _store_generation(
    producer_dir: Path, graph: dict[str, Any], receipt: dict[str, Any],
) -> tuple[str, str]:
    validate_graph(graph)
    validate_receipt(receipt, graph)
    graph_hash = object_hash(graph)
    receipt_hash = object_hash(receipt)
    generation = _generations(producer_dir) / graph_hash
    if generation.is_symlink() or generation.exists() and not generation.is_dir():
        raise RuntimeError("render graph generation is not a regular directory")
    receipts = generation / "receipts"
    if receipts.is_symlink() or receipts.exists() and not receipts.is_dir():
        raise RuntimeError("render graph receipts is not a regular directory")
    files = (
        (generation / "graph.json", graph),
        (receipts / f"{receipt_hash}.json", receipt),
    )
    for path, value in files:
        expected = canonical_bytes(value)
        if path.is_symlink() or path.exists() and not path.is_file():
            raise RuntimeError("render graph generation path is not a regular file")
        if path.exists() and path.read_bytes().rstrip(b"\n") != expected:
            raise RuntimeError("content-addressed render graph collision")
        if not path.exists():
            _write_atomic(path, value)
    return graph_hash, receipt_hash


def _activate(
    producer_dir: Path, graph_hash: str, receipt_hash: str,
) -> None:
    _write_atomic(_store(producer_dir) / ACTIVE_NAME, {
        "schemaVersion": 1, "graphHash": graph_hash,
        "receiptHash": receipt_hash,
    })


def _deactivate(producer_dir: Path) -> None:
    """Remove ACTIVE when a candidate whose parent was empty rolls back."""
    pointer = _store(producer_dir) / ACTIVE_NAME
    if pointer.is_symlink() or pointer.exists() and not pointer.is_file():
        raise RuntimeError("active render graph pointer is not a regular file")
    try:
        pointer.unlink()
    except FileNotFoundError:
        return
    descriptor = os.open(pointer.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publish(
    producer_dir: Path,
    graph: dict[str, Any],
    receipt: dict[str, Any],
) -> str:
    """Publish an immutable graph generation, then atomically advance ACTIVE."""
    graph_hash, receipt_hash = _store_generation(
        producer_dir, graph, receipt)
    _activate(producer_dir, graph_hash, receipt_hash)
    return graph_hash


def _candidate_path(candidate_path: Path) -> Path:
    if not candidate_path.is_absolute():
        raise RuntimeError("render graph candidate path must be absolute")
    return candidate_path.parent.resolve(strict=True) / candidate_path.name


def _candidate_key(candidate_path: Path) -> str:
    canonical = _candidate_path(candidate_path)
    return object_hash({
        "kind": "current-render-candidate-path",
        "path": str(canonical),
    })


def stage_candidate(
    producer_dir: Path, graph: dict[str, Any], receipt: dict[str, Any],
    candidate_path: Path,
) -> str:
    """Store a proved generation without advancing ACTIVE before visual QC."""
    from current_render_graph_source_gate import verify_graph_source_authority
    verify_graph_source_authority(graph, receipt)
    active = load_active(producer_dir)
    previous_graph_hash = object_hash(active[0]) if active else None
    previous_receipt_hash = object_hash(active[1]) if active else None
    if receipt["previousGraphHash"] != previous_graph_hash:
        raise RuntimeError("render graph candidate parent is not ACTIVE")
    graph_hash, receipt_hash = _store_generation(
        producer_dir, graph, receipt)
    canonical = _candidate_path(candidate_path)
    final_node = next(
        row for row in graph["nodes"] if row["nodeId"] == graph["rootNodeId"])
    candidate_hash = final_node["outputArtifactHash"]
    final_artifact = next(
        row for row in receipt["artifacts"]
        if row["nodeId"] == graph["rootNodeId"])
    if canonical.is_symlink() or not canonical.is_file() \
            or canonical.resolve() != canonical \
            or final_artifact["path"] != str(canonical) \
            or final_artifact["sha256"] != candidate_hash \
            or file_hash(canonical) != candidate_hash:
        raise RuntimeError("render graph candidate does not bind root media")
    candidate = {
        "schemaVersion": 1,
        "kind": "current-render-graph-candidate",
        "candidatePath": str(canonical),
        "candidateSha256": candidate_hash,
        "graphHash": graph_hash,
        "receiptHash": receipt_hash,
        "previousGraphHash": previous_graph_hash,
        "previousReceiptHash": previous_receipt_hash,
    }
    pointer = _candidates(producer_dir) / (
        f"{_candidate_key(candidate_path)}.json")
    if pointer.exists():
        observed = json.loads(pointer.read_text(encoding="utf-8"))
        if observed != candidate:
            raise RuntimeError("render graph candidate path is already staged")
    else:
        _write_atomic(pointer, candidate)
    return graph_hash


def validate_active_pointer(value: object) -> tuple[str, str]:
    """The one closed ACTIVE v1 pointer shape; every reader of those bytes uses this."""
    keys = {"schemaVersion", "graphHash", "receiptHash"}
    if type(value) is not dict or set(value) != keys \
            or value["schemaVersion"] != 1:
        raise RuntimeError("active render graph pointer is malformed")
    graph_hash, receipt_hash = value["graphHash"], value["receiptHash"]
    if not all(type(item) is str and _SHA256.fullmatch(item)
               for item in (graph_hash, receipt_hash)):
        raise RuntimeError("active render graph pointer hashes are malformed")
    return graph_hash, receipt_hash


def _pointer(path: Path) -> tuple[str, str]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("active render graph pointer is not a regular file")
    return validate_active_pointer(json.loads(path.read_text()))


def load_active(producer_dir: Path) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Open and validate the active immutable graph generation."""
    pointer = _store(producer_dir) / ACTIVE_NAME
    if not pointer.exists():
        return None
    graph_hash, receipt_hash = _pointer(pointer)
    generation = _generations(producer_dir) / graph_hash
    if generation.is_symlink() or not generation.is_dir():
        raise RuntimeError("active render graph generation is not regular")
    receipts = generation / "receipts"
    if receipts.is_symlink() or not receipts.is_dir():
        raise RuntimeError("active render graph receipts is not regular")
    graph_path = generation / "graph.json"
    receipt_path = receipts / f"{receipt_hash}.json"
    if any(path.is_symlink() or not path.is_file()
           for path in (graph_path, receipt_path)):
        raise RuntimeError("active render graph generation is not regular")
    graph = validate_graph(json.loads(graph_path.read_text()))
    receipt = validate_receipt(
        json.loads(receipt_path.read_text()), graph)
    if object_hash(graph) != graph_hash or object_hash(receipt) != receipt_hash:
        raise RuntimeError("active render graph generation hash is stale")
    return graph, receipt


def verify_artifacts(
    graph: dict[str, Any],
    receipt: dict[str, Any],
    ignored: set[str] | None = None,
) -> None:
    """Rehash every retained artifact not intentionally replaced this run."""
    ignored = ignored or set()
    nodes = {row["nodeId"]: row for row in graph["nodes"]}
    for row in receipt["artifacts"]:
        if row["nodeId"] in ignored:
            continue
        path = Path(row["path"])
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"cached render artifact is missing: {row['nodeId']}")
        if path.stat().st_size != row["sizeBytes"] \
                or file_hash(path) != nodes[row["nodeId"]]["outputArtifactHash"]:
            raise RuntimeError(f"cached render artifact is corrupt: {row['nodeId']}")


def write_pending_base(producer_dir: Path, value: dict[str, Any]) -> None:
    """Persist exact base-stage output for the following assemble stage."""
    _write_atomic(_store(producer_dir) / PENDING_BASE_NAME, value)


def read_pending_base(producer_dir: Path) -> dict[str, Any] | None:
    """Read a pending base receipt; its caller validates current bindings."""
    path = _store(producer_dir) / PENDING_BASE_NAME
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("pending base receipt is not a regular file")
    return json.loads(path.read_text())


def clear_pending_base(producer_dir: Path) -> None:
    """Remove a consumed pending-base handoff."""
    try:
        (_store(producer_dir) / PENDING_BASE_NAME).unlink()
    except FileNotFoundError:
        pass
