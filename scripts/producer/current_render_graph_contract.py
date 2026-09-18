"""Durable file-backed authority for the current renderer's RenderGraphV1."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from cross_runtime_canonical_json import canonical_compact_json

GRAPH_DIR = ".render-graph-v1"
ACTIVE_NAME = "ACTIVE.json"
PENDING_BASE_NAME = "PENDING_BASE.json"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
_NODE_KEYS = {"nodeId", "kind", "dependencies", "inputDigests",
              "outputArtifactHash", "frameRange"}
_GRAPH_KEYS = {"schemaVersion", "graphId", "toolchainHash",
               "rootNodeId", "nodes"}
_RECEIPT_KEYS = {
    "schemaVersion", "kind", "graphHash", "executionMode",
    "previousGraphHash", "dirtyNodeIds", "reusedNodeIds", "artifacts",
}
_ARTIFACT_KEYS = {"nodeId", "path", "sha256", "sizeBytes"}
_KINDS = {"source-snapshot", "timeline-map", "base-segment",
          "dialogue-stem", "scene-unit", "caption-shard",
          "composite-window", "preview", "final-export"}


def canonical_bytes(value: object) -> bytes:
    """Match TypeScript canonicalJson: compact JSON with code-point key order."""
    return canonical_compact_json(value).encode("utf-8")


def object_hash(value: object) -> str:
    """SHA-256 of cross-runtime canonical JSON."""
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_hash(path: Path) -> str:
    """Constant-memory SHA-256 for media and toolchain inputs."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _exact(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise RuntimeError(f"{label} has unknown or missing fields")
    return value


def _hash(value: object, label: str) -> str:
    if type(value) is not str or not _SHA256.fullmatch(value):
        raise RuntimeError(f"{label} is not a lowercase SHA-256")
    return value


def _stable(value: object, label: str) -> str:
    if type(value) is not str or not _STABLE_ID.fullmatch(value):
        raise RuntimeError(f"{label} is not a stable id")
    return value


def _frame_range(value: object, label: str) -> None:
    if value is None:
        return
    row = _exact(value, {"startFrame", "endFrameExclusive"}, label)
    start, end = row["startFrame"], row["endFrameExclusive"]
    if type(start) is not int or type(end) is not int or start < 0 or end <= start:
        raise RuntimeError(f"{label} is not a positive half-open frame range")


def _required_for(
    kind: str,
    ids_by_kind: dict[str, set[str]],
) -> set[str] | None:
    source = ids_by_kind.get("source-snapshot", set())
    timeline = ids_by_kind.get("timeline-map", set())
    base = ids_by_kind.get("base-segment", set())
    composite = ids_by_kind.get("composite-window", set())
    if kind == "timeline-map":
        return source
    if kind in {"base-segment", "dialogue-stem"}:
        return source | timeline
    if kind in {"scene-unit", "caption-shard"}:
        return timeline | (source if kind == "caption-shard" else set())
    if kind == "composite-window":
        return (
            base | ids_by_kind.get("scene-unit", set())
            | ids_by_kind.get("caption-shard", set())
            | ids_by_kind.get("dialogue-stem", set()))
    if kind == "final-export":
        return composite
    return None


def _required_edges(nodes: list[dict[str, Any]]) -> dict[str, set[str]]:
    ids_by_kind: dict[str, set[str]] = {}
    for row in nodes:
        ids_by_kind.setdefault(row["kind"], set()).add(row["nodeId"])
    required: dict[str, set[str]] = {}
    for row in nodes:
        edges = _required_for(row["kind"], ids_by_kind)
        if edges is not None:
            required[row["nodeId"]] = edges
    return required


def validate_graph(value: object) -> dict[str, Any]:
    """Validate strict RenderGraphV1 plus current-stage dependency semantics."""
    graph = _exact(value, _GRAPH_KEYS, "render graph")
    if graph["schemaVersion"] != 1 or type(graph["nodes"]) is not list:
        raise RuntimeError("render graph version or nodes are invalid")
    _stable(graph["graphId"], "graph id")
    _stable(graph["rootNodeId"], "root node id")
    _hash(graph["toolchainHash"], "toolchain hash")
    nodes: dict[str, dict[str, Any]] = {}
    for index, value_node in enumerate(graph["nodes"]):
        node = _exact(value_node, _NODE_KEYS, f"render node {index}")
        node_id = _stable(node["nodeId"], "render node id")
        if node_id in nodes or node["kind"] not in _KINDS:
            raise RuntimeError("render graph has duplicate ids or an unknown kind")
        dependencies = node["dependencies"]
        if type(dependencies) is not list \
                or len(set(dependencies)) != len(dependencies):
            raise RuntimeError(f"render node {node_id} dependencies are invalid")
        if type(node["inputDigests"]) is not dict:
            raise RuntimeError(f"render node {node_id} inputs are invalid")
        for key, digest in node["inputDigests"].items():
            _stable(key, "render input key")
            _hash(digest, "render input digest")
        output_hash = node["outputArtifactHash"]
        if output_hash is not None:
            _hash(output_hash, "render output hash")
        _frame_range(node["frameRange"], f"render node {node_id} frame range")
        nodes[node_id] = node
    if not nodes or graph["rootNodeId"] not in nodes:
        raise RuntimeError("render graph has no root")
    for node in nodes.values():
        if any(item not in nodes for item in node["dependencies"]):
            raise RuntimeError(f"render node {node['nodeId']} has an unknown edge")
    for node_id, required in _required_edges(list(nodes.values())).items():
        missing = required - set(nodes[node_id]["dependencies"])
        if missing:
            detail = ", ".join(sorted(missing))
            raise RuntimeError(
                f"render node {node_id} is missing required dependencies: {detail}")
    _assert_closed_dag(nodes, graph["rootNodeId"])
    return graph


def _assert_closed_dag(nodes: dict[str, dict[str, Any]], root: str) -> None:
    visiting: set[str] = set()
    reached: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            raise RuntimeError("render graph contains a cycle")
        if node_id in reached:
            return
        visiting.add(node_id)
        for dependency in nodes[node_id]["dependencies"]:
            visit(dependency)
        visiting.remove(node_id)
        reached.add(node_id)

    visit(root)
    if reached != set(nodes):
        raise RuntimeError("render graph has nodes outside the root closure")


def _artifact(value: object, node_hash: str) -> dict[str, Any]:
    row = _exact(value, _ARTIFACT_KEYS, "render artifact")
    _stable(row["nodeId"], "artifact node id")
    _hash(row["sha256"], "artifact hash")
    path = Path(row["path"])
    size = row["sizeBytes"]
    if not path.is_absolute() or type(size) is not int or size < 0 \
            or row["sha256"] != node_hash:
        raise RuntimeError("render artifact receipt is malformed")
    return row


def validate_receipt(value: object, graph: dict[str, Any]) -> dict[str, Any]:
    """Validate execution receipt and exact node/output bindings."""
    receipt = _exact(value, _RECEIPT_KEYS, "render execution receipt")
    if receipt["schemaVersion"] != 1 \
            or receipt["kind"] != "current-render-graph-execution":
        raise RuntimeError("render execution receipt version is unsupported")
    _hash(receipt["graphHash"], "receipt graph hash")
    if receipt["graphHash"] != object_hash(graph):
        raise RuntimeError("render execution receipt graph hash is stale")
    if receipt["executionMode"] not in {"incremental", "forced-full"}:
        raise RuntimeError("render execution mode is unsupported")
    if receipt["previousGraphHash"] is not None:
        _hash(receipt["previousGraphHash"], "previous graph hash")
    nodes = {row["nodeId"]: row for row in graph["nodes"]}
    artifacts = receipt["artifacts"]
    if type(artifacts) is not list:
        raise RuntimeError("render artifact list is malformed")
    mapped = {}
    for item in artifacts:
        raw = _exact(item, _ARTIFACT_KEYS, "render artifact")
        node_id = _stable(raw["nodeId"], "artifact node id")
        if node_id not in nodes:
            raise RuntimeError("render artifact names an unknown node")
        mapped[node_id] = _artifact(raw, nodes[node_id]["outputArtifactHash"])
    expected = {node_id for node_id, node in nodes.items()
                if node["outputArtifactHash"] is not None}
    if set(mapped) != expected or len(mapped) != len(artifacts):
        raise RuntimeError("render artifacts do not cover graph outputs exactly")
    classifications = []
    for key in ("dirtyNodeIds", "reusedNodeIds"):
        values = receipt[key]
        if type(values) is not list or len(set(values)) != len(values) \
                or any(item not in nodes for item in values):
            raise RuntimeError(f"{key} is malformed")
        classifications.append(set(values))
    dirty, reused = classifications
    if dirty & reused or dirty | reused != set(nodes):
        raise RuntimeError("render receipt does not classify every node exactly once")
    return receipt


def classify_nodes(
    graph: dict[str, Any],
    previous: tuple[dict[str, Any], dict[str, Any]] | None,
    forced_full: bool,
) -> tuple[list[str], list[str]]:
    """Return dependency-closed dirty and exactly reusable node ids."""
    nodes = {row["nodeId"]: row for row in graph["nodes"]}
    if forced_full or previous is None:
        return list(nodes), []
    old_graph, _ = previous
    old = {row["nodeId"]: row for row in old_graph["nodes"]}
    dirty = {
        node_id for node_id, row in nodes.items()
        if old_graph["toolchainHash"] != graph["toolchainHash"]
        or node_id not in old
        or any(row[key] != old[node_id][key]
               for key in (
                   "kind", "dependencies", "inputDigests",
                   "outputArtifactHash",
               ))
    }
    grew = True
    while grew:
        before = len(dirty)
        dirty |= {
            node_id for node_id, row in nodes.items()
            if any(dependency in dirty for dependency in row["dependencies"])
        }
        grew = len(dirty) != before
    reused = [node_id for node_id in nodes if node_id not in dirty]
    return [node_id for node_id in nodes if node_id in dirty], reused
