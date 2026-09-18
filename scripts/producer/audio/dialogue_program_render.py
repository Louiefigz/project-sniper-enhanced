"""Explicit opt-in renderer for an exact private dialogue-program graph."""
from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path

from audio.dialogue_program_contracts import ValidatedDialogueProgram
from audio.dialogue_program_graph import (
    DialogueProgramGraphInput,
    build_program_graph,
)
from audio.dialogue_program_media import (
    PROGRAM_NAME, assert_auxiliary_stable, prove_auxiliary_stems,
    probe_program, render_dialogue_program_mix,
)
from audio.dialogue_program_receipt import (
    DialogueProgramReceiptInput,
    build_dialogue_program_receipt,
    verify_dialogue_program_receipt,
)
from audio.dialogue_stem_contracts import (
    DialogueStemRenderError,
    DialogueStemRenderRequest,
)
from audio.dialogue_stem_publish import publish_named_generation
from audio.dialogue_stem_receipt import verify_dialogue_stem_receipt
from audio.dialogue_stem_render import (
    _cleanup_private,
    _verify_publication,
    render_dialogue_stem,
)
from current_render_graph_contract import (
    canonical_bytes,
    file_hash,
    object_hash,
    validate_graph,
    validate_receipt,
)
from fingerprints import file_sha256

TRACK_NAME = "dialogue-track.json"
MAP_NAME = "dialogue-map.json"
SOURCE_SET_NAME = "dialogue-source-set.json"
GRAPH_NAME = "render-graph.json"
EXECUTION_NAME = "render-execution.json"
RECEIPT_NAME = "dialogue-program-receipt.json"
_FINAL_NAMES = {
    TRACK_NAME, MAP_NAME, SOURCE_SET_NAME, PROGRAM_NAME,
    GRAPH_NAME, EXECUTION_NAME, RECEIPT_NAME,
}


def _read_json(path: str, label: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise DialogueStemRenderError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise DialogueStemRenderError(f"{label} is not one object")
    return value


def _write_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        view = view[os.write(descriptor, view):]


def _write_json_new(path: str, value: object) -> None:
    raw = canonical_bytes(value) + b"\n"
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        _write_all(descriptor, raw)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _copy_new(source: str, target: str, expected_hash: str) -> None:
    source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    target_fd = os.open(
        target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        while chunk := os.read(source_fd, 1024 * 1024):
            _write_all(target_fd, chunk)
        os.fsync(target_fd)
    finally:
        os.close(source_fd)
        os.close(target_fd)
    if file_sha256(target) != expected_hash:
        raise DialogueStemRenderError("retained dialogue authority bytes drifted")


def _source_set(request: ValidatedDialogueProgram) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "kind": "dialogue-program-source-set",
        "sourceSnapshotSetHash":
            request.dialogue_map["sourceSnapshotSetHash"],
        "sources": [{
            **source.authority_row(), "path": source.path,
        } for source in request.sources],
    }


def _dialogue_source_rows(request: ValidatedDialogueProgram) -> list[dict]:
    return [{
        "sourceId": source.source_id,
        "path": source.path,
        "sha256": source.sha256,
        "audioStreamIndex": source.audio_stream_index,
    } for source in request.sources]


def _assert_request_stable(request: ValidatedDialogueProgram) -> None:
    authority = request.authority_files
    pairs = (
        (str(authority["trackPath"]),
         str(authority["trackFileSha256"])),
        (str(authority["mapPath"]),
         str(authority["mapFileSha256"])),
    )
    if any(file_sha256(path) != digest for path, digest in pairs):
        raise DialogueStemRenderError(
            "dialogue authority files changed during program render")
    for source in request.sources:
        source.validate()
    request.tools.validate()


def _load_reusable_dialogue(request: ValidatedDialogueProgram) -> dict | None:
    generation = request.dialogue_generation_dir
    if not os.path.lexists(generation):
        return None
    if request.execution_mode != "incremental":
        raise DialogueStemRenderError(
            "forced-full cannot reuse a dialogue generation")
    receipt_path = os.path.join(generation, "dialogue-stem-receipt.json")
    receipt = verify_dialogue_stem_receipt(
        _read_json(receipt_path, "dialogue stem receipt"))
    expected = {
        "dialogueMapHash": request.dialogue_map_hash,
        "dialogueTrackHash": request.dialogue_map["dialogueTrackHash"],
        "sourceSnapshotSetHash":
            request.dialogue_map["sourceSnapshotSetHash"],
        "pictureTimelineMapHash":
            request.dialogue_map["pictureTimelineMapHash"],
    }
    if any(receipt[key] != value for key, value in expected.items()):
        raise DialogueStemRenderError(
            "reusable dialogue receipt does not bind current authority")
    observed = [{
        key: row[key] for key in
        ("sourceId", "path", "sha256", "audioStreamIndex")
    } for row in receipt["sourceProofs"]]
    tools = receipt["tools"]
    if observed != _dialogue_source_rows(request) \
            or tools["ffmpegSha256"] != request.tools.ffmpeg_sha256 \
            or tools["ffprobeSha256"] != request.tools.ffprobe_sha256:
        raise DialogueStemRenderError(
            "reusable dialogue source or tool authority drifted")
    _verify_publication(generation, receipt)
    return receipt


def _dialogue_receipt(
    request: ValidatedDialogueProgram,
) -> tuple[dict, bool]:
    reusable = _load_reusable_dialogue(request)
    if reusable is not None:
        return reusable, True
    receipt = render_dialogue_stem(DialogueStemRenderRequest(
        request.dialogue_map, request.dialogue_map_hash, request.sources,
        request.dialogue_generation_dir, request.tools))
    return receipt, False


def _retained_authority(
    request: ValidatedDialogueProgram,
    stage: str,
) -> tuple[str, str, str]:
    track_path = os.path.join(stage, TRACK_NAME)
    map_path = os.path.join(stage, MAP_NAME)
    source_path = os.path.join(stage, SOURCE_SET_NAME)
    authority = request.authority_files
    _copy_new(
        str(authority["trackPath"]), track_path,
        str(authority["trackFileSha256"]))
    _copy_new(
        str(authority["mapPath"]), map_path,
        str(authority["mapFileSha256"]))
    _write_json_new(source_path, _source_set(request))
    return track_path, map_path, source_path


def _write_graph_receipts(
    item: DialogueProgramGraphInput,
    stage: str,
) -> tuple[dict, str, str]:
    graph, _, execution = build_program_graph(item)
    graph_path = os.path.join(stage, GRAPH_NAME)
    execution_path = os.path.join(stage, EXECUTION_NAME)
    _write_json_new(graph_path, graph)
    _write_json_new(execution_path, execution)
    return graph, graph_path, execution_path


def _published_leaf(path: str) -> None:
    info = os.stat(path, follow_symlinks=False)
    if os.path.islink(path) or not stat.S_ISREG(info.st_mode) \
            or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o400:
        raise DialogueStemRenderError(
            "dialogue program generation leaf is not sealed")


def _verify_program_publication(
    request: ValidatedDialogueProgram,
    expected_receipt: dict,
) -> None:
    generation = request.program_generation_dir
    info = os.stat(generation, follow_symlinks=False)
    if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o500 \
            or set(os.listdir(generation)) != _FINAL_NAMES:
        raise DialogueStemRenderError(
            "dialogue program generation closure is not sealed")
    for name in _FINAL_NAMES:
        _published_leaf(os.path.join(generation, name))
    graph_path = os.path.join(generation, GRAPH_NAME)
    execution_path = os.path.join(generation, EXECUTION_NAME)
    graph = validate_graph(_read_json(graph_path, "program graph"))
    execution = validate_receipt(
        _read_json(execution_path, "program graph execution"), graph)
    receipt = verify_dialogue_program_receipt(_read_json(
        os.path.join(generation, RECEIPT_NAME), "program receipt"))
    observed = probe_program(os.path.join(generation, PROGRAM_NAME), request)
    if any(receipt["output"].get(key) != value for key, value in observed.items()):
        raise DialogueStemRenderError("published dialogue program PCM proof drifted")
    if receipt != expected_receipt \
            or receipt["renderGraph"]["graphHash"] != object_hash(graph) \
            or receipt["renderGraph"]["graphFileSha256"] \
            != file_hash(Path(graph_path)) \
            or receipt["renderGraph"]["executionReceiptFileSha256"] \
            != file_hash(Path(execution_path)):
        raise DialogueStemRenderError(
            "published dialogue program graph binding drifted")
    for artifact in execution["artifacts"]:
        path = Path(artifact["path"])
        if not path.is_file() or path.is_symlink() \
                or file_hash(path) != artifact["sha256"] \
                or path.stat().st_size != artifact["sizeBytes"]:
            raise DialogueStemRenderError(
                "published dialogue program artifact drifted")


def render_dialogue_program(request: ValidatedDialogueProgram) -> dict:
    """Render, graph, receipt, seal, and publish one private program."""
    if not isinstance(request, ValidatedDialogueProgram):
        raise DialogueStemRenderError(
            "dialogue program renderer requires validated authority")
    auxiliary = prove_auxiliary_stems(request)
    dialogue_receipt, reused = _dialogue_receipt(request)
    parent = os.path.dirname(request.program_generation_dir)
    stage = tempfile.mkdtemp(
        prefix=".sniper-dialogue-program-stage-", dir=parent)
    try:
        _, map_path, source_path = _retained_authority(request, stage)
        dialogue_path = os.path.join(
            request.dialogue_generation_dir, "dialogue-stem.wav")
        program_path, program_proof = render_dialogue_program_mix(
            request, dialogue_path, auxiliary, stage)
        graph_input = DialogueProgramGraphInput(
            request, dialogue_receipt, auxiliary, source_path, map_path,
            program_path, reused)
        graph, graph_path, execution_path = _write_graph_receipts(
            graph_input, stage)
        receipt = build_dialogue_program_receipt(
            DialogueProgramReceiptInput(
                request, dialogue_receipt, reused, auxiliary, program_path,
                program_proof, graph, graph_path, execution_path))
        verify_dialogue_program_receipt(receipt)
        _write_json_new(os.path.join(stage, RECEIPT_NAME), receipt)
        _assert_request_stable(request)
        for proof in auxiliary:
            assert_auxiliary_stable(proof)
        publish_named_generation(
            stage, request.program_generation_dir, _FINAL_NAMES)
        _verify_program_publication(request, receipt)
        _verify_publication(request.dialogue_generation_dir, dialogue_receipt)
        _assert_request_stable(request)
        for proof in auxiliary:
            assert_auxiliary_stable(proof)
        return receipt
    finally:
        _cleanup_private(stage, parent, ".sniper-dialogue-program-stage-")
