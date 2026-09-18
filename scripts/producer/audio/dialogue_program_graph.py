"""Build a strict RenderGraphV1 around exact dialogue program media."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from audio.dialogue_program_contracts import ValidatedDialogueProgram
from audio.dialogue_program_media import AuxiliaryProof, program_mix_policy
from current_render_graph_contract import (
    file_hash,
    object_hash,
    validate_graph,
    validate_receipt,
)


@dataclass(frozen=True)
class DialogueProgramGraphInput:
    """Retained paths and observations needed to compile one graph."""

    request: ValidatedDialogueProgram
    dialogue_receipt: dict
    auxiliary: tuple[AuxiliaryProof, ...]
    source_manifest_path: str
    map_path: str
    program_path: str
    reused_dialogue: bool


def _artifact(
    node_id: str,
    path: str,
    published_path: str | None = None,
) -> dict[str, object]:
    value = Path(path)
    if value.is_symlink() or not value.is_file():
        raise RuntimeError(f"program graph artifact is unsafe: {node_id}")
    retained = Path(published_path) if published_path else value
    if not retained.is_absolute():
        raise RuntimeError(f"program graph path is not absolute: {node_id}")
    return {
        "nodeId": node_id,
        "path": str(retained),
        "sha256": file_hash(value),
        "sizeBytes": value.stat().st_size,
    }


def _node(
    node_id: str,
    kind: str,
    dependencies: list[str],
    binding: tuple[
        dict[str, str], dict[str, object], dict[str, int] | None,
    ],
) -> dict[str, object]:
    input_digests, artifact, frame_range = binding
    return {
        "nodeId": node_id,
        "kind": kind,
        "dependencies": dependencies,
        "inputDigests": input_digests,
        "outputArtifactHash": artifact["sha256"],
        "frameRange": frame_range,
    }


def _toolchain_hash(request: ValidatedDialogueProgram) -> str:
    root = Path(__file__).resolve().parent
    names = (
        "dialogue_program_contracts.py",
        "dialogue_program_media.py",
        "dialogue_program_graph.py",
        "dialogue_program_receipt.py",
        "dialogue_program_render.py",
        "dialogue_stem_contracts.py",
        "dialogue_stem_media.py",
        "dialogue_stem_mix.py",
        "dialogue_stem_probe.py",
        "dialogue_stem_receipt.py",
        "dialogue_stem_render.py",
    )
    return object_hash({
        "ffmpegSha256": request.tools.ffmpeg_sha256,
        "ffprobeSha256": request.tools.ffprobe_sha256,
        "receiptSchemaSha256": file_hash(
            root.parents[2] / "schemas" / "producer"
            / "dialogue-program-receipt-v2.schema.json"),
        "modules": [{
            "name": name, "sha256": file_hash(root / name)
        } for name in names],
    })


def _dialogue_nodes(
    item: DialogueProgramGraphInput,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    request = item.request
    source = _artifact(
        "node-source", item.source_manifest_path,
        str(Path(request.program_generation_dir)
            / Path(item.source_manifest_path).name))
    timeline = _artifact(
        "node-timeline", item.map_path,
        str(Path(request.program_generation_dir) / Path(item.map_path).name))
    dialogue_path = str(
        Path(request.dialogue_generation_dir) / "dialogue-stem.wav")
    dialogue = _artifact("node-dialogue", dialogue_path)
    frame_range = {
        "startFrame": 0,
        "endFrameExclusive": request.dialogue_map["totalOutputFrames"],
    }
    nodes = [
        _node("node-source", "source-snapshot", [], ({
            "source.snapshotSet":
                request.dialogue_map["sourceSnapshotSetHash"],
        }, source, None)),
        _node("node-timeline", "timeline-map", ["node-source"], ({
            "timeline.dialogueMap": request.dialogue_map_hash,
            "timeline.dialogueTrack":
                request.dialogue_map["dialogueTrackHash"],
            "timeline.pictureMap":
                request.dialogue_map["pictureTimelineMapHash"],
        }, timeline, None)),
        _node("node-dialogue", "dialogue-stem", [
            "node-source", "node-timeline",
        ], ({
            "dialogue.map": request.dialogue_map_hash,
            "dialogue.receipt": item.dialogue_receipt["receiptHash"],
            "dialogue.tools": object_hash(item.dialogue_receipt["tools"]),
        }, dialogue, frame_range)),
    ]
    return nodes, [source, timeline, dialogue]


def _auxiliary_nodes(
    item: DialogueProgramGraphInput,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    nodes, artifacts = [], []
    frame_range = {
        "startFrame": 0,
        "endFrameExclusive": item.request.dialogue_map["totalOutputFrames"],
    }
    for index, proof in enumerate(item.auxiliary):
        node_id = f"node-aux-{index:04d}"
        artifact = _artifact(node_id, proof.stem.path)
        nodes.append(_node(
            node_id, "base-segment", ["node-source", "node-timeline"], ({
                f"aux.{index:04d}.bytes": proof.stem.sha256,
                f"aux.{index:04d}.identity":
                    object_hash(proof.stem.authority_row()),
            }, artifact, frame_range)))
        artifacts.append(artifact)
    return nodes, artifacts


def build_program_graph(
    item: DialogueProgramGraphInput,
) -> tuple[dict, list[dict], dict]:
    """Compile graph, exact artifact coverage, and execution receipt."""
    dialogue_nodes, dialogue_artifacts = _dialogue_nodes(item)
    auxiliary_nodes, auxiliary_artifacts = _auxiliary_nodes(item)
    program = _artifact(
        "node-program", item.program_path,
        str(Path(item.request.program_generation_dir)
            / Path(item.program_path).name))
    dependencies = [
        "node-dialogue",
        *[row["nodeId"] for row in auxiliary_nodes],
    ]
    frame_range = {
        "startFrame": 0,
        "endFrameExclusive": item.request.dialogue_map["totalOutputFrames"],
    }
    program_node = _node(
        "node-program", "composite-window", dependencies, ({
            "program.auxiliarySet": item.request.auxiliary_set_hash,
            "program.mixPolicy": object_hash(program_mix_policy()),
        }, program, frame_range))
    graph = validate_graph({
        "schemaVersion": 1,
        "graphId": "exact-dialogue-program-"
        + object_hash({
            "map": item.request.dialogue_map_hash,
            "aux": item.request.auxiliary_set_hash,
            "mixPolicy": program_mix_policy(),
        })[:16],
        "toolchainHash": _toolchain_hash(item.request),
        "rootNodeId": "node-program",
        "nodes": [
            *dialogue_nodes, *auxiliary_nodes, program_node,
        ],
    })
    artifacts = [
        *dialogue_artifacts, *auxiliary_artifacts, program,
    ]
    receipt = _execution_receipt(item, graph, artifacts)
    return graph, artifacts, receipt


def _execution_receipt(
    item: DialogueProgramGraphInput,
    graph: dict,
    artifacts: list[dict],
) -> dict:
    reused = ["node-source", "node-timeline", "node-dialogue"] \
        if item.reused_dialogue else []
    dirty = [
        row["nodeId"] for row in graph["nodes"]
        if row["nodeId"] not in reused
    ]
    return validate_receipt({
        "schemaVersion": 1,
        "kind": "current-render-graph-execution",
        "graphHash": object_hash(graph),
        "executionMode": item.request.execution_mode,
        "previousGraphHash": None,
        "dirtyNodeIds": dirty,
        "reusedNodeIds": reused,
        "artifacts": artifacts,
    }, graph)
