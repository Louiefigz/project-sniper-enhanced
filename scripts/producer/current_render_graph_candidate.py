"""QC-gated candidate activation for the current-render graph bridge."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from current_render_graph_build import GraphBuildInputs, source_authority
from current_render_graph_contract import file_hash, object_hash
from current_render_graph_store import (
    _activate,
    _candidate_key,
    _candidate_path,
    _candidates,
    _deactivate,
    _store_generation,
    load_active,
    verify_artifacts,
)
from current_render_graph_source_gate import verify_graph_source_authority
from current_render_toolchain import current_toolchain_hash
from fingerprints import plan_content_hash

_CANDIDATE_KEYS = {
    "schemaVersion", "kind", "candidatePath", "candidateSha256",
    "graphHash", "receiptHash", "previousGraphHash", "previousReceiptHash",
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _candidate(
    producer_dir: Path, candidate_path: Path,
) -> dict[str, Any]:
    canonical = _candidate_path(candidate_path)
    pointer = _candidates(producer_dir) / (
        f"{_candidate_key(candidate_path)}.json")
    if pointer.is_symlink() or not pointer.is_file():
        raise RuntimeError("render graph candidate is not staged")
    value = json.loads(pointer.read_text(encoding="utf-8"))
    if type(value) is not dict or set(value) != _CANDIDATE_KEYS \
            or value["schemaVersion"] != 1 \
            or value["kind"] != "current-render-graph-candidate" \
            or value["candidatePath"] != str(canonical) \
            or any(type(value[key]) is not str
                   or _SHA256.fullmatch(value[key]) is None
                   for key in (
                       "candidateSha256", "graphHash", "receiptHash")):
        raise RuntimeError("render graph candidate pointer is malformed")
    previous = (value["previousGraphHash"], value["previousReceiptHash"])
    if (previous[0] is None) != (previous[1] is None) \
            or any(item is not None and (
                type(item) is not str or _SHA256.fullmatch(item) is None)
                for item in previous):
        raise RuntimeError("render graph candidate parent is malformed")
    return value


def _staged_generation(
    producer_dir: Path, candidate: dict[str, Any],
    allow_promoted_candidate: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    generation = (
        producer_dir / ".render-graph-v1" / "generations"
        / candidate["graphHash"])
    receipt_path = (
        generation / "receipts" / f"{candidate['receiptHash']}.json")
    paths = (generation / "graph.json", receipt_path)
    if any(path.is_symlink() or not path.is_file() for path in paths):
        raise RuntimeError("staged render graph generation is unavailable")
    graph, receipt = (
        json.loads(paths[0].read_text(encoding="utf-8")),
        json.loads(paths[1].read_text(encoding="utf-8")),
    )
    if object_hash(graph) != candidate["graphHash"] \
            or object_hash(receipt) != candidate["receiptHash"]:
        raise RuntimeError("staged render graph generation hash changed")
    if graph.get("toolchainHash") != current_toolchain_hash():
        raise RuntimeError("staged render graph toolchain is stale")
    ignored = {
        row["nodeId"] for row in receipt["artifacts"]
        if allow_promoted_candidate
        and row["path"] == candidate["candidatePath"]
    }
    verify_artifacts(graph, receipt, ignored)
    verify_graph_source_authority(graph, receipt)
    return graph, receipt


def _active_identity(
    active: tuple[dict[str, Any], dict[str, Any]] | None,
) -> tuple[str | None, str | None]:
    if active is None:
        return None, None
    return object_hash(active[0]), object_hash(active[1])


def _assert_candidate_parent(
    producer_dir: Path,
    candidate: dict[str, Any],
    verify_media: bool,
) -> None:
    active = load_active(producer_dir)
    observed = _active_identity(active)
    expected = (
        candidate["previousGraphHash"], candidate["previousReceiptHash"])
    if observed != expected:
        raise RuntimeError(
            "active render graph changed after candidate staging")
    if not verify_media or active is None:
        return
    graph, receipt = active
    if graph.get("toolchainHash") != current_toolchain_hash():
        raise RuntimeError("active parent render graph toolchain is stale")
    verify_artifacts(graph, receipt)
    verify_graph_source_authority(graph, receipt)


def verify_candidate(
    producer_dir: Path, candidate_path: Path, expected_sha256: str,
) -> str:
    """Reopen a staged graph and its still-private candidate media."""
    candidate = _candidate(producer_dir, candidate_path)
    canonical = _candidate_path(candidate_path)
    if candidate["candidateSha256"] != expected_sha256 \
            or canonical.is_symlink() or not canonical.is_file() \
            or file_hash(canonical) != expected_sha256:
        raise RuntimeError("staged render graph candidate bytes changed")
    _assert_candidate_parent(producer_dir, candidate, True)
    graph, _ = _staged_generation(producer_dir, candidate)
    root = next(
        row for row in graph["nodes"] if row["nodeId"] == graph["rootNodeId"])
    if root["outputArtifactHash"] != expected_sha256:
        raise RuntimeError("staged render graph root does not bind candidate")
    return candidate["graphHash"]


def _promoted_receipt(
    receipt: dict[str, Any], candidate_path: Path, final_path: Path,
    expected_sha256: str,
) -> dict[str, Any]:
    promoted = json.loads(json.dumps(receipt))
    replaced = 0
    for artifact in promoted["artifacts"]:
        if artifact["path"] == str(candidate_path) \
                and artifact["sha256"] == expected_sha256:
            artifact["path"] = str(final_path.resolve())
            artifact["sizeBytes"] = final_path.stat().st_size
            replaced += 1
    if not replaced:
        raise RuntimeError("staged receipt does not name candidate output")
    return promoted


def activate_candidate(
    producer_dir: Path, candidate_path: Path, final_path: Path,
    expected_sha256: str,
) -> str:
    """Advance ACTIVE only after the approved bytes occupy final.mp4."""
    candidate = _candidate(producer_dir, candidate_path)
    graph, receipt = _staged_generation(
        producer_dir, candidate, allow_promoted_candidate=True)
    if candidate["candidateSha256"] != expected_sha256 \
            or final_path.is_symlink() or not final_path.is_file() \
            or file_hash(final_path) != expected_sha256:
        raise RuntimeError("approved final does not match staged candidate")
    promoted = _promoted_receipt(
        receipt, Path(candidate["candidatePath"]),
        final_path, expected_sha256)
    _assert_candidate_parent(producer_dir, candidate, False)
    graph_hash, receipt_hash = _store_generation(
        producer_dir, graph, promoted)
    _activate(producer_dir, graph_hash, receipt_hash)
    return graph_hash


def candidate_is_active(
    producer_dir: Path, candidate_path: Path, final_path: Path,
    expected_sha256: str,
) -> bool:
    """Resolve an ambiguous activation response from exact stored state."""
    candidate = _candidate(producer_dir, candidate_path)
    active = load_active(producer_dir)
    if active is None or object_hash(active[0]) != candidate["graphHash"]:
        return False
    graph, receipt = active
    if graph.get("toolchainHash") != current_toolchain_hash():
        raise RuntimeError("active render graph toolchain is stale")
    verify_artifacts(graph, receipt)
    verify_graph_source_authority(graph, receipt)
    root = next(
        row for row in graph["nodes"] if row["nodeId"] == graph["rootNodeId"])
    artifacts = [
        row for row in receipt["artifacts"]
        if row["nodeId"] == graph["rootNodeId"]]
    return bool(
        candidate["candidateSha256"] == expected_sha256
        and root["outputArtifactHash"] == expected_sha256
        and len(artifacts) == 1
        and artifacts[0]["path"] == str(final_path.resolve())
        and artifacts[0]["sha256"] == expected_sha256
        and not final_path.is_symlink() and final_path.is_file()
        and file_hash(final_path) == expected_sha256
    )


def _restore_parent_pointer(
    producer_dir: Path, candidate: dict[str, Any],
) -> None:
    graph_hash = candidate["previousGraphHash"]
    receipt_hash = candidate["previousReceiptHash"]
    if graph_hash is None:
        _deactivate(producer_dir)
        return
    generation = (
        producer_dir / ".render-graph-v1" / "generations" / graph_hash)
    graph = json.loads((generation / "graph.json").read_text())
    receipt = json.loads(
        (generation / "receipts" / f"{receipt_hash}.json").read_text())
    if object_hash(graph) != graph_hash or object_hash(receipt) != receipt_hash:
        raise RuntimeError("prior active render graph generation changed")
    if graph.get("toolchainHash") != current_toolchain_hash():
        raise RuntimeError("prior active render graph toolchain is stale")
    verify_artifacts(graph, receipt)
    verify_graph_source_authority(graph, receipt)
    _activate(producer_dir, graph_hash, receipt_hash)


def rollback_candidate(
    producer_dir: Path, candidate_path: Path, final_path: Path,
    expected_sha256: str,
) -> str | None:
    """CAS-safe rollback after the prior live media has been restored."""
    candidate = _candidate(producer_dir, candidate_path)
    active = load_active(producer_dir)
    if active is None:
        if candidate["previousGraphHash"] is None:
            return None
        raise RuntimeError("ACTIVE disappeared during candidate rollback")
    observed = (object_hash(active[0]), object_hash(active[1]))
    previous = (
        candidate["previousGraphHash"], candidate["previousReceiptHash"])
    if observed == previous:
        return previous[0]
    if observed[0] != candidate["graphHash"]:
        raise RuntimeError("ACTIVE is foreign during candidate rollback")
    root = next(
        row for row in active[0]["nodes"]
        if row["nodeId"] == active[0]["rootNodeId"])
    if root["outputArtifactHash"] != expected_sha256:
        raise RuntimeError("ACTIVE candidate identity changed during rollback")
    _restore_parent_pointer(producer_dir, candidate)
    return previous[0]


def active_binds(
    inputs: GraphBuildInputs, expected_sha256: str,
) -> bool:
    """Prove ACTIVE binds the current authority and approved final bytes."""
    active = load_active(inputs.producer_dir)
    if active is None:
        return False
    graph, receipt = active
    verify_artifacts(graph, receipt)
    nodes = {row["nodeId"]: row for row in graph["nodes"]}
    source_inputs, _ = source_authority(inputs)
    source = nodes.get("node-source")
    final = nodes.get("node-final")
    return bool(
        graph["toolchainHash"] == current_toolchain_hash()
        and source and source["inputDigests"] == source_inputs
        and final
        and final["inputDigests"].get("final.plan")
        == plan_content_hash(json.loads(inputs.plan_path.read_text()))
        and final["outputArtifactHash"] == expected_sha256
        and file_hash(inputs.output_path) == expected_sha256
    )
