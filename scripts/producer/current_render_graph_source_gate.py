"""Final-promotion source authority for staged current-render graphs."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from current_render_graph_contract import file_hash
from source_set_receipt_authority import (
    verify_source_set_receipt_artifact,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _source_rows(
    graph: dict[str, Any],
    receipt: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    nodes = [
        row for row in graph.get("nodes", [])
        if row.get("kind") == "source-snapshot"
    ]
    if len(nodes) != 1 or nodes[0].get("nodeId") != "node-source":
        raise RuntimeError("staged render graph has no unique source authority")
    artifacts = [
        row for row in receipt.get("artifacts", [])
        if row.get("nodeId") == "node-source"
    ]
    if len(artifacts) != 1:
        raise RuntimeError("staged render graph has no unique source receipt")
    return nodes[0], artifacts[0]


def verify_graph_source_authority(
    graph: dict[str, Any],
    receipt: dict[str, Any],
) -> str:
    """Rehash the exact source set immediately before candidate promotion."""
    source, artifact = _source_rows(graph, receipt)
    path = Path(str(artifact.get("path", "")))
    document = verify_source_set_receipt_artifact(path)
    entries = document["entries"]
    inputs = source.get("inputDigests", {})
    stage_root = inputs.get("source.stageRoot")
    if not isinstance(stage_root, str) \
            or _SHA256.fullmatch(stage_root) is None:
        raise RuntimeError("staged graph source stage root is malformed")
    expected = {
        "source.manifest": source.get("inputDigests", {}).get(
            "source.manifest"),
        "source.set": document["sourceSetDigest"],
        "source.stageRoot": stage_root,
        **{
            f"source.{index:04d}": row["sha256"]
            for index, row in enumerate(entries)
        },
    }
    if not isinstance(expected["source.manifest"], str) \
            or _SHA256.fullmatch(expected["source.manifest"]) is None \
            or source.get("inputDigests") != expected:
        raise RuntimeError("staged graph source inputs changed authority")
    if artifact.get("sha256") != file_hash(path) \
            or source.get("outputArtifactHash") != artifact.get("sha256"):
        raise RuntimeError("staged graph source receipt changed identity")
    return document["sourceSetDigest"]
