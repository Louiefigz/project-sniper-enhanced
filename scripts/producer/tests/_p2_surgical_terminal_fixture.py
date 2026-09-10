"""Current-render parent fixture for picture surgical-terminal tests."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from current_render_graph_build import GraphBuildInputs, source_authority
from current_render_graph_contract import file_hash, object_hash
from current_render_graph_inputs import DEFAULT_CACHE
from current_render_graph_store import publish
from current_render_toolchain import current_toolchain_hash
from edit.cut_repair_prepare_media import prepare
from edit.cut_repair_surgical_terminal import SurgicalStageRequest, stage
from fingerprints import plan_content_hash
from tests.test_p2_cut_repair_picture_prepare_media import _write


def _artifact(node_id: str, path: Path) -> dict[str, Any]:
    return {
        "nodeId": node_id,
        "path": str(path.resolve()),
        "sha256": file_hash(path),
        "sizeBytes": path.stat().st_size,
    }


def _parent_nodes(
    source_inputs: dict[str, str],
    source_receipt: Path,
    media: Path,
    parent_plan_hash: str,
) -> list[dict[str, Any]]:
    return [
        {
            "nodeId": "node-source",
            "kind": "source-snapshot",
            "dependencies": [],
            "inputDigests": source_inputs,
            "outputArtifactHash": file_hash(source_receipt),
            "frameRange": None,
        },
        {
            "nodeId": "node-final",
            "kind": "final-export",
            "dependencies": ["node-source"],
            "inputDigests": {"final.plan": parent_plan_hash},
            "outputArtifactHash": file_hash(media),
            "frameRange": None,
        },
    ]


def publish_parent_active(
    fixture: Any,
    media_path: Path | None = None,
) -> str:
    """Publish a source-gated ACTIVE graph for the fixture parent media."""
    media = media_path or Path(fixture.parent)
    inputs = GraphBuildInputs(
        Path(fixture.producer),
        Path(fixture.producer) / "edit_plan.json",
        Path(fixture.manifest),
        media,
        media,
        DEFAULT_CACHE,
    )
    source_inputs, source_receipt = source_authority(inputs)
    artifacts = [
        _artifact("node-source", source_receipt),
        _artifact("node-final", media),
    ]
    graph = {
        "schemaVersion": 1,
        "graphId": "picture-parent-test",
        "toolchainHash": current_toolchain_hash(),
        "rootNodeId": "node-final",
        "nodes": _parent_nodes(
            source_inputs,
            source_receipt,
            media,
            plan_content_hash(fixture.plan),
        ),
    }
    receipt = {
        "schemaVersion": 1,
        "kind": "current-render-graph-execution",
        "graphHash": object_hash(graph),
        "executionMode": "incremental",
        "previousGraphHash": None,
        "dirtyNodeIds": ["node-source", "node-final"],
        "reusedNodeIds": [],
        "artifacts": artifacts,
    }
    return publish(Path(fixture.producer), graph, receipt)


def terminal_paths(fixture: Any, prepared: dict) -> tuple[Path, Path, Path]:
    """Write the exact reviewed plan/preparation pair under staging."""
    root = Path(fixture.staging) / "terminal"
    root.mkdir()
    plan = root / "edit_plan.json"
    prepared_path = root / "prepared.json"
    _write(str(plan), prepared["reviewPlan"])
    _write(str(prepared_path), prepared)
    return root, plan, prepared_path


def prepare_and_stage(
    fixture: Any,
) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    """Create one proved composite and stage its private terminal graph."""
    prepared = prepare(
        fixture.producer, fixture.directive, fixture.context, fixture.staging)
    root, plan, prepared_path = terminal_paths(fixture, prepared)
    candidate = root / "final.mp4"
    result = stage(SurgicalStageRequest(
        Path(fixture.producer),
        plan,
        Path(fixture.manifest),
        prepared_path,
        candidate,
        root,
    ))
    return prepared, candidate, result
