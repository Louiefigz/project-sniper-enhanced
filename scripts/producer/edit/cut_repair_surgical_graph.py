"""RenderGraphV1 projection for an admitted surgical repair terminal."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from current_render_graph_build import GraphBuildInputs, source_authority
from current_render_graph_contract import (
    file_hash,
    object_hash,
    validate_graph,
)
from current_render_graph_inputs import DEFAULT_CACHE
from current_render_toolchain import current_toolchain_hash
from edit.cut_repair_surgical_contract import (
    SurgicalTerminalAuthority,
    SurgicalTerminalError,
)
from edit.picture_lock_common import content_hash
from fingerprints import base_plan_digest, plan_content_hash
from render_stage_roots import stage_input_roots

_CONTRACT_SOURCES = (
    Path(__file__).resolve(),
    Path(__file__).with_name("cut_repair_surgical_terminal.py"),
    Path(__file__).with_name("cut_repair_surgical_contract.py"),
    Path(__file__).with_name("cut_repair_picture_plan_authority.py"),
    Path(__file__).parents[1] / "current_render_graph_build.py",
    Path(__file__).parents[1] / "current_render_graph_contract.py",
    Path(__file__).parents[1] / "current_render_graph_source_gate.py",
    Path(__file__).parents[1] / "current_render_graph_store.py",
    Path(__file__).parents[1] / "render_stage_roots.py",
    Path(__file__).with_name("repair_composite.py"),
    Path(__file__).with_name("repair_composite_media.py"),
    Path(__file__).with_name("repair_fragment_contracts.py"),
)


@dataclass(frozen=True)
class SurgicalGraphInput:
    """All canonical paths and authority needed for one graph projection."""

    producer: Path
    plan_path: Path
    manifest_path: Path
    candidate: Path
    timeline_path: Path
    authority: SurgicalTerminalAuthority
    terminal: dict[str, Any]


@dataclass(frozen=True)
class _NodeInput:
    node_id: str
    kind: str
    dependencies: list[str]
    inputs: dict[str, str]
    frame_range: dict[str, int] | None = None


def _artifact(node_id: str, path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise SurgicalTerminalError(f"{node_id} has no regular artifact")
    return {
        "nodeId": node_id, "path": str(path.resolve()),
        "sha256": file_hash(path), "sizeBytes": path.stat().st_size,
    }


def _node(value: _NodeInput, artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "nodeId": value.node_id, "kind": value.kind,
        "dependencies": value.dependencies, "inputDigests": value.inputs,
        "outputArtifactHash": artifact["sha256"],
        "frameRange": value.frame_range,
    }


def contract_hash(authority: SurgicalTerminalAuthority) -> str:
    """Bind the verifier sources and exact receipt-pinned media tools."""
    sources = [
        {"path": str(path), "sha256": file_hash(path)}
        for path in _CONTRACT_SOURCES
    ]
    return object_hash({
        "domain": "cut-repair-surgical-terminal-contract-v1",
        "sources": sources, "tools": authority.composite["tools"],
    })


def build_terminal_receipt(
    authority: SurgicalTerminalAuthority,
    candidate: Path,
    parent_render_authority: dict[str, Any],
) -> dict[str, Any]:
    """Seal construction, mapping, reversion, and delivery limitations."""
    picture = authority.authority
    disposition = {
        "candidateConstruction": "proved-composite-exact-byte-copy",
        "planReconstruction": "surgical-terminal-not-plan-only-reconstructable",
        "palmier": "reference-media-only-no-native-editability",
    }
    partition = {
        "revalidatedDependentIds":
            authority.operation["revalidatedDependentIds"],
        "unchangedDependentIds":
            authority.operation["unchangedDependentIds"],
    }
    return {
        "schemaVersion": 1, "kind": "cut-repair-surgical-terminal",
        "operationHash": authority.prepared["operationHash"],
        "reviewPlanObjectHash": authority.prepared["reviewPlanHash"],
        "reviewPlanContentHash": plan_content_hash(authority.plan),
        "reviewTimelineMapHash": authority.prepared["reviewTimelineMapHash"],
        "picturePlanAuthorityHash": picture["authorityHash"],
        "parentPlanObjectHash": picture["parentPlanObjectHash"],
        "parentRenderAuthority": parent_render_authority,
        "parentRenderAuthorityHash": content_hash(parent_render_authority),
        "mappingProofHash": picture["mappingProofHash"],
        "reversionHash": content_hash(picture["reversion"]),
        "selectionPolicyHash": authority.prepared["selectionPolicyHash"],
        "fragmentReceiptHash": content_hash(authority.fragment),
        "compositeReceiptHash": content_hash(authority.composite),
        "sourceSelection": authority.source_selection,
        "dependencyPartition": partition,
        "dependencyPartitionHash": authority.dependency_partition_hash,
        "dirtyFrameRange": picture["dirtyFrameRange"],
        "outsideDirtyOracle": authority.composite["outsideDirtyOracle"],
        "candidate": {
            "path": str(candidate), "sha256": authority.candidate_hash,
            "sourceCompositePath": str(authority.composite_path),
            "sourceCompositeSha256": authority.candidate_hash,
        },
        "deliveryDisposition": disposition,
        "contractHash": contract_hash(authority),
    }


def _node_inputs(value: SurgicalGraphInput) -> list[_NodeInput]:
    authority, terminal = value.authority, value.terminal
    roots = stage_input_roots(authority.plan, authority.manifest)
    dirty = authority.authority["dirtyFrameRange"]
    terminal_hash = content_hash(terminal)
    base = base_plan_digest(authority.plan)
    return [
        _NodeInput("node-timeline", "timeline-map", ["node-source"], {
            "timeline.plan": base,
            "timeline.stageRoot": roots["plan.timeline"],
            "surgical.childTimeline":
                authority.prepared["reviewTimelineMapHash"],
        }),
        _NodeInput(
            "node-base", "base-segment", ["node-source", "node-timeline"], {
                "base.plan": base, "base.stageRoot": roots["plan.base"],
                "base.manifestStageRoot": roots["manifest.base"],
                "surgical.operation": authority.prepared["operationHash"],
                "surgical.pictureAuthority":
                    authority.authority["authorityHash"],
                "surgical.fragmentReceipt": content_hash(authority.fragment),
                "surgical.compositeReceipt": content_hash(authority.composite),
                "surgical.dependencyPartition":
                    authority.dependency_partition_hash,
                "surgical.parentRenderAuthority":
                    terminal["parentRenderAuthorityHash"],
                "surgical.contract": terminal["contractHash"],
            }, dirty),
        _NodeInput("node-composite", "composite-window", ["node-base"], {
            "composite.plan": object_hash({
                "graphicsTrack": [], "captionsTrack": None}),
            "composite.stageRoot": roots["plan.composite"],
            "surgical.terminalReceipt": terminal_hash,
            "surgical.outsideDirtyOracle":
                content_hash(authority.composite["outsideDirtyOracle"]),
        }, dirty),
        _NodeInput("node-final", "final-export", ["node-composite"], {
            "final.plan": plan_content_hash(authority.plan),
            "final.stageRoot": roots["plan.final"],
            "final.manifestStageRoot": roots["manifest.final"],
            "surgical.terminalReceipt": terminal_hash,
            "surgical.deliveryDisposition":
                content_hash(terminal["deliveryDisposition"]),
        }),
    ]


def build_surgical_graph(
    value: SurgicalGraphInput,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Project the exact-copy candidate onto the standard graph closure."""
    inputs = GraphBuildInputs(
        value.producer, value.plan_path, value.manifest_path,
        value.candidate, value.candidate, DEFAULT_CACHE,
        artifact_dir=value.candidate.parent)
    source_inputs, receipt = source_authority(inputs)
    artifacts = {
        "node-source": _artifact("node-source", receipt),
        "node-timeline": _artifact("node-timeline", value.timeline_path),
        **{
            name: _artifact(name, value.candidate)
            for name in ("node-base", "node-composite", "node-final")
        },
    }
    nodes = [_node(_NodeInput(
        "node-source", "source-snapshot", [], source_inputs),
        artifacts["node-source"])]
    nodes.extend(
        _node(row, artifacts[row.node_id]) for row in _node_inputs(value))
    graph = validate_graph({
        "schemaVersion": 1,
        "graphId": "current-render-"
        + object_hash(str(value.producer))[:16],
        "toolchainHash": current_toolchain_hash(),
        "rootNodeId": "node-final", "nodes": nodes,
    })
    return graph, list(artifacts.values())
