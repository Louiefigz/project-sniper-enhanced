"""Canonical immutable receipt for a private dialogue-stem generation."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from audio.dialogue_stem_contracts import (
    DialogueStemRenderError,
    ValidatedDialogueStemRequest,
)
from audio.dialogue_stem_probe import DecodedSource
from contracts.schema_validator import (
    SchemaValidationError,
    validate_document,
)
from edit.picture_lock_common import canonical_json, content_hash
from fingerprints import file_sha256


@dataclass(frozen=True)
class DialogueStemReceiptInput:
    """All proved observations needed for one receipt."""

    request: ValidatedDialogueStemRequest
    decoded: tuple[DecodedSource, ...]
    entry_proofs: list[dict[str, object]]
    output_path: str
    output_proof: dict[str, object]


def _entry_receipt(
    row: dict,
    proof: dict[str, object],
) -> dict[str, object]:
    result = {
        "dialogueSegmentId": row["dialogueSegmentId"],
        "cutSegmentId": row["cutSegmentId"],
        "elementVersion": row["elementVersion"],
        "sourceId": row["sourceId"],
        "sourceSampleRate": row["sourceSampleRate"],
        "sourceSampleRange": row["sourceSampleRange"],
        "normalizedSourceSampleRange": row["normalizedSourceSampleRange"],
        "outputSampleRange": row["outputSampleRange"],
        "requestedSpeed": row["speed"],
        "effectiveSpeed": row["effectiveSpeed"],
        "role": row["role"],
        **proof,
    }
    if row["role"] != "primary":
        result["seamSample"] = row["seamSample"]
        result["coveredByCutSegmentId"] = row["coveredByCutSegmentId"]
    return result


def _clock(dialogue_map: dict) -> dict[str, object]:
    return {
        "fps": dialogue_map["projectFps"],
        "sampleRate": dialogue_map["projectSampleRate"],
        "totalFrames": dialogue_map["totalOutputFrames"],
        "totalSamples": dialogue_map["totalOutputSamples"],
        "terminalSampleFormula": "B(F)=floor(F*S*q/p)",
    }


def _policies() -> dict[str, str]:
    return {
        "sourceIndexing": "decoded-contiguous-native-samples",
        "downmix": "content-bound-dead-channel-repair-before-mono-downmix",
        "retime": "pitch-preserving-rubberband-from-exact-rational",
        "retimeReconciliation": "bounded-tail-pad-or-trim",
        "overlapMix": "linear-sum-no-normalize-saturating-pcm-s32",
        "publication": "atomic-no-replace-read-only-generation",
    }


def build_dialogue_stem_receipt(
    item: DialogueStemReceiptInput,
) -> dict[str, object]:
    """Bind authority, every source/tool byte, exact entries, and output."""
    request = item.request
    dialogue_map = request.dialogue_map
    if len(item.entry_proofs) != len(dialogue_map["entries"]):
        raise DialogueStemRenderError(
            "dialogue entry proof closure does not match the map")
    output = {
        "fileName": os.path.basename(item.output_path),
        "sha256": file_sha256(item.output_path),
        **item.output_proof,
    }
    body = {
        "schemaVersion": 1,
        "kind": "dialogue-stem-render-receipt",
        "admissionStatus": "private-unpromoted",
        "dialogueMapHash": request.dialogue_map_hash,
        "dialogueTrackHash": dialogue_map["dialogueTrackHash"],
        "sourceSnapshotSetHash": dialogue_map["sourceSnapshotSetHash"],
        "pictureTimelineMapHash": dialogue_map["pictureTimelineMapHash"],
        "clock": _clock(dialogue_map),
        "sourceProofs": [source.proof for source in item.decoded],
        "entries": [
            _entry_receipt(row, proof)
            for row, proof in zip(
                dialogue_map["entries"], item.entry_proofs)
        ],
        "output": output,
        "tools": {
            "ffmpegPath": request.tools.ffmpeg_path,
            "ffmpegSha256": request.tools.ffmpeg_sha256,
            "ffprobePath": request.tools.ffprobe_path,
            "ffprobeSha256": request.tools.ffprobe_sha256,
            "retimeFilter": "rubberband",
        },
        "policies": _policies(),
    }
    return {**body, "receiptHash": content_hash(body)}


def verify_dialogue_stem_receipt(receipt: object) -> dict:
    """Verify the receipt's self-hash and core exact-duration assertions."""
    try:
        parsed = validate_document(
            "dialogue-stem-receipt-v1.schema.json", receipt)
    except SchemaValidationError as exc:
        raise DialogueStemRenderError(
            "dialogue stem receipt violates its closed schema") from exc
    body = {key: value for key, value in parsed.items()
            if key != "receiptHash"}
    if parsed["receiptHash"] != content_hash(body):
        raise DialogueStemRenderError("dialogue stem receipt hash drifted")
    _verify_exact_geometry(parsed)
    return parsed


def _verify_exact_geometry(receipt: dict) -> None:
    clock = receipt["clock"]
    fps = clock["fps"]
    terminal = (
        clock["totalFrames"] * clock["sampleRate"]
        * int(fps["denominator"]) // int(fps["numerator"])
    )
    if terminal != clock["totalSamples"] \
            or receipt["output"]["decodedSamples"] != terminal:
        raise DialogueStemRenderError(
            "dialogue stem receipt does not prove terminal samples")
    for row in receipt["entries"]:
        output = row["outputSampleRange"]
        length = output["endSampleExclusive"] - output["startSample"]
        reconciled = (
            row["preReconcileSamples"] + row["reconciliationSamples"])
        if length != reconciled or output["endSampleExclusive"] > terminal:
            raise DialogueStemRenderError(
                "dialogue stem entry reconciliation is not exact")


def write_dialogue_stem_receipt(path: str, receipt: dict) -> None:
    """Write one new canonical receipt leaf and re-read identical bytes."""
    verified = verify_dialogue_stem_receipt(receipt)
    raw = (canonical_json(verified) + "\n").encode("utf-8")
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        position = 0
        while position < len(raw):
            position += os.write(descriptor, raw[position:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        with open(path, "rb") as handle:
            observed = handle.read()
        parsed = json.loads(observed)
    except (OSError, json.JSONDecodeError) as exc:
        raise DialogueStemRenderError(
            "dialogue stem receipt cannot be re-read") from exc
    if observed != raw or parsed != verified:
        raise DialogueStemRenderError(
            "dialogue stem receipt bytes changed before publication")
