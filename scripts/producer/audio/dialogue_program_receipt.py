"""Closed receipt for exact dialogue plus preserved auxiliary program audio."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from audio.dialogue_program_contracts import ValidatedDialogueProgram
from audio.dialogue_program_media import AuxiliaryProof, PROGRAM_MIX_POLICY_VERSION
from audio.dialogue_stem_contracts import DialogueStemRenderError
from contracts.schema_validator import (
    SchemaValidationError,
    validate_document,
)
from current_render_graph_contract import file_hash, object_hash
from edit.picture_lock_common import content_hash


@dataclass(frozen=True)
class DialogueProgramReceiptInput:
    """Every authority and observation bound by one program receipt."""

    request: ValidatedDialogueProgram
    dialogue_receipt: dict
    reused_dialogue: bool
    auxiliary: tuple[AuxiliaryProof, ...]
    program_path: str
    program_proof: dict[str, object]
    graph: dict
    graph_path: str
    execution_path: str


def _clock(request: ValidatedDialogueProgram) -> dict[str, object]:
    dialogue_map = request.dialogue_map
    return {
        "fps": dialogue_map["projectFps"],
        "sampleRate": dialogue_map["projectSampleRate"],
        "totalFrames": dialogue_map["totalOutputFrames"],
        "totalSamples": dialogue_map["totalOutputSamples"],
        "terminalSampleFormula": "B(F)=floor(F*S*q/p)",
    }


def _policies() -> dict[str, object]:
    """Bind float premix semantics without granting delivery-master status."""
    return {"mix": "linear-sum-no-normalize",
            "mixPolicyVersion": PROGRAM_MIX_POLICY_VERSION,
            "masteringApplied": False,
            "dialogueChannels": "mono-duplicated-to-stereo",
            "auxiliaryDisposition": "program-aligned-preserved-inputs",
            "legacyDefaultsMutated": False,
            "publication": "atomic-no-replace-read-only-generation"}


def build_dialogue_program_receipt(
        item: DialogueProgramReceiptInput) -> dict[str, object]:
    """Bind the exact stem, every preserved auxiliary, graph, and output."""
    request = item.request
    body = {
        "schemaVersion": 2,
        "kind": "dialogue-program-render-receipt",
        "admissionStatus": "private-unpromoted",
        "executionMode": request.execution_mode,
        "reusedDialogueStem": item.reused_dialogue,
        "authority": request.authority_files,
        "sourceSnapshotSetHash":
            request.dialogue_map["sourceSnapshotSetHash"],
        "auxiliarySnapshotSetHash": request.auxiliary_set_hash,
        "expectedAuxiliaryCounts": request.expected_auxiliary_counts,
        "dialogue": {
            "generationPath": request.dialogue_generation_dir,
            "receiptHash": item.dialogue_receipt["receiptHash"],
            "outputSha256": item.dialogue_receipt["output"]["sha256"],
        },
        "auxiliaryProofs": [proof.proof for proof in item.auxiliary],
        "clock": _clock(request),
        "output": {
            "fileName": os.path.basename(item.program_path),
            "sha256": file_hash(Path(item.program_path)),
            **item.program_proof,
        },
        "renderGraph": {
            "graphHash": object_hash(item.graph),
            "graphFileSha256": file_hash(Path(item.graph_path)),
            "executionReceiptFileSha256":
                file_hash(Path(item.execution_path)),
            "dialogueNodeId": "node-dialogue",
            "programNodeId": "node-program",
        },
        "tools": {
            "ffmpegPath": request.tools.ffmpeg_path,
            "ffmpegSha256": request.tools.ffmpeg_sha256,
            "ffprobePath": request.tools.ffprobe_path,
            "ffprobeSha256": request.tools.ffprobe_sha256,
        },
        "policies": _policies(),
    }
    return {**body, "receiptHash": content_hash(body)}


def _auxiliary_hash(receipt: dict) -> str:
    keys = ("stemId", "role", "sha256", "audioStreamIndex")
    return content_hash({
        "schemaVersion": 1,
        "kind": "dialogue-program-auxiliary-set",
        "stems": [{
            key: row[key] for key in keys
        } for row in receipt["auxiliaryProofs"]],
    })


def verify_dialogue_program_receipt(value: object) -> dict:
    """Validate closed fields, self-hash, role closure, and exact B(F)."""
    try:
        receipt = validate_document(
            "dialogue-program-receipt-v2.schema.json", value)
    except SchemaValidationError as exc:
        raise DialogueStemRenderError(
            "dialogue program receipt violates its closed schema") from exc
    body = {key: item for key, item in receipt.items()
            if key != "receiptHash"}
    if receipt["receiptHash"] != content_hash(body):
        raise DialogueStemRenderError("dialogue program receipt hash drifted")
    clock = receipt["clock"]
    fps = clock["fps"]
    terminal = (
        clock["totalFrames"] * clock["sampleRate"]
        * int(fps["denominator"]) // int(fps["numerator"])
    )
    if terminal != clock["totalSamples"] \
            or receipt["output"]["decodedSamples"] != terminal:
        raise DialogueStemRenderError(
            "dialogue program terminal sample proof is invalid")
    observed = {
        role: sum(row["role"] == role
                  for row in receipt["auxiliaryProofs"])
        for role in ("room-tone", "music", "sfx")
    }
    if observed != receipt["expectedAuxiliaryCounts"]:
        raise DialogueStemRenderError(
            "dialogue program auxiliary role closure drifted")
    if _auxiliary_hash(receipt) != receipt["auxiliarySnapshotSetHash"]:
        raise DialogueStemRenderError(
            "dialogue program auxiliary snapshot hash drifted")
    if receipt["executionMode"] == "forced-full" \
            and receipt["reusedDialogueStem"]:
        raise DialogueStemRenderError(
            "forced-full dialogue program cannot claim reused dialogue")
    if receipt["output"]["sampleRate"] != clock["sampleRate"] \
            or any(row["sampleRate"] != clock["sampleRate"]
                   or row["decodedSamples"] != terminal
                   for row in receipt["auxiliaryProofs"]):
        raise DialogueStemRenderError(
            "dialogue program stem clock closure drifted")
    return receipt
