"""Closed opt-in authority for exact dialogue-aware program mixing."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from audio.dialogue_stem_contracts import (
    DialogueSourceSnapshot,
    DialogueStemRenderError,
    DialogueStemTools,
    _regular_snapshot,
    validate_dialogue_sources,
)
from contracts.schema_validator import (
    SchemaValidationError,
    validate_document,
)
from edit.dialogue_authority import (
    dialogue_map_hash,
    dialogue_track_hash,
    validate_dialogue_authority,
)
from edit.dialogue_contracts import sha256, stable_id
from edit.picture_lock_common import content_hash
from fingerprints import file_sha256

_ROLES = {"room-tone", "music", "sfx"}
_SAFE_MAX = 9_007_199_254_740_991


@dataclass(frozen=True)
class AuxiliaryStemSnapshot:
    """One program-aligned non-dialogue PCM authority."""

    stem_id: str
    role: str
    path: str
    sha256: str
    audio_stream_index: int

    def authority_row(self) -> dict[str, object]:
        """Return the path-free auxiliary-set row."""
        return {
            "stemId": self.stem_id,
            "role": self.role,
            "sha256": self.sha256,
            "audioStreamIndex": self.audio_stream_index,
        }


@dataclass(frozen=True)
class DialogueProgramRequest:
    """One schema-parsed production program render request."""

    authority: dict[str, object]
    sources: tuple[DialogueSourceSnapshot, ...]
    auxiliary_stems: tuple[AuxiliaryStemSnapshot, ...]
    expected_auxiliary_counts: dict[str, int]
    dialogue_generation_dir: str
    program_generation_dir: str
    tools: DialogueStemTools
    execution_mode: str


@dataclass(frozen=True)
class ValidatedDialogueProgram:
    """Exact authorities and snapshots admitted for media execution."""

    track: dict
    dialogue_map: dict
    dialogue_map_hash: str
    authority_files: dict[str, object]
    sources: tuple[DialogueSourceSnapshot, ...]
    auxiliary_stems: tuple[AuxiliaryStemSnapshot, ...]
    auxiliary_set_hash: str
    expected_auxiliary_counts: dict[str, int]
    dialogue_generation_dir: str
    program_generation_dir: str
    tools: DialogueStemTools
    execution_mode: str


def auxiliary_snapshot_set_hash(
    stems: tuple[AuxiliaryStemSnapshot, ...],
) -> str:
    """Hash the canonical path-free non-dialogue snapshot set."""
    return content_hash({
        "schemaVersion": 1,
        "kind": "dialogue-program-auxiliary-set",
        "stems": [stem.authority_row() for stem in stems],
    })


def _json_file(path: object, digest: object, label: str) -> tuple[dict, str]:
    source = _regular_snapshot(path, label)
    expected = _hash(digest, f"{label} file hash")
    if file_sha256(source) != expected:
        raise DialogueStemRenderError(f"{label} file bytes drifted")
    try:
        with open(source, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise DialogueStemRenderError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise DialogueStemRenderError(f"{label} must contain one object")
    return value, source


def _hash(value: object, label: str) -> str:
    try:
        return sha256(value, label)
    except ValueError as exc:
        raise DialogueStemRenderError(str(exc)) from exc


def _authority(value: dict) -> tuple[dict, dict, dict[str, object]]:
    track_raw, track_path = _json_file(
        value["trackPath"], value["trackFileSha256"], "dialogue track")
    map_raw, map_path = _json_file(
        value["mapPath"], value["mapFileSha256"], "dialogue map")
    try:
        track, dialogue_map = validate_dialogue_authority(track_raw, map_raw)
    except ValueError as exc:
        raise DialogueStemRenderError(str(exc)) from exc
    track_hash = dialogue_track_hash(track)
    map_hash = dialogue_map_hash(dialogue_map)
    if track_hash != value["dialogueTrackHash"] \
            or map_hash != value["dialogueMapHash"]:
        raise DialogueStemRenderError(
            "dialogue authority content hashes do not match")
    proof = {
        "trackPath": track_path,
        "trackFileSha256": value["trackFileSha256"],
        "dialogueTrackHash": track_hash,
        "mapPath": map_path,
        "mapFileSha256": value["mapFileSha256"],
        "dialogueMapHash": map_hash,
    }
    return track, dialogue_map, proof


def _source(row: dict) -> DialogueSourceSnapshot:
    return DialogueSourceSnapshot(
        row["sourceId"], row["path"], row["sha256"],
        row["audioStreamIndex"])


def _auxiliary(row: dict) -> AuxiliaryStemSnapshot:
    try:
        stem_id = stable_id(row["stemId"], "stemId")
    except ValueError as exc:
        raise DialogueStemRenderError(str(exc)) from exc
    role = row["role"]
    path = _regular_snapshot(row["path"], f"auxiliary stem {stem_id}")
    digest = _hash(row["sha256"], f"{stem_id}.sha256")
    stream = row["audioStreamIndex"]
    if role not in _ROLES or type(stream) is not int \
            or not 0 <= stream <= _SAFE_MAX:
        raise DialogueStemRenderError(
            f"auxiliary stem {stem_id} role/stream is invalid")
    if file_sha256(path) != digest:
        raise DialogueStemRenderError(
            f"auxiliary stem bytes drifted for {stem_id}")
    return AuxiliaryStemSnapshot(stem_id, role, path, digest, stream)


def _auxiliary_set(
    rows: list[dict],
    expected: dict[str, int],
) -> tuple[AuxiliaryStemSnapshot, ...]:
    stems = tuple(_auxiliary(row) for row in rows)
    order = [(stem.role, stem.stem_id) for stem in stems]
    if order != sorted(order) or len(order) != len(set(order)):
        raise DialogueStemRenderError(
            "auxiliary stems must be unique and canonically ordered")
    observed = {
        role: sum(stem.role == role for stem in stems) for role in _ROLES}
    if observed != expected:
        raise DialogueStemRenderError(
            "auxiliary stem closure does not match expected counts")
    return stems


def _target(path: object, label: str, allow_existing: bool) -> str:
    if type(path) is not str or not os.path.isabs(path) \
            or os.path.abspath(path) != path:
        raise DialogueStemRenderError(f"{label} must be absolute and normalized")
    parent = os.path.dirname(path)
    if os.path.realpath(parent) != parent or not os.path.isdir(parent):
        raise DialogueStemRenderError(
            f"{label} parent must be an existing canonical directory")
    if os.path.lexists(path):
        valid = allow_existing and os.path.isdir(path) \
            and not os.path.islink(path) and os.path.realpath(path) == path
        if not valid:
            raise DialogueStemRenderError(f"{label} already exists")
    return path


def _tools(row: dict) -> DialogueStemTools:
    return DialogueStemTools(
        row["ffmpegPath"], row["ffmpegSha256"],
        row["ffprobePath"], row["ffprobeSha256"]).validate()


def parse_dialogue_program_request(
    value: object,
) -> ValidatedDialogueProgram:
    """Parse all exact authorities before permitting any output byte."""
    try:
        row = validate_document(
            "dialogue-program-request-v1.schema.json", value)
    except SchemaValidationError as exc:
        raise DialogueStemRenderError(
            "dialogue program request violates its closed schema") from exc
    track, dialogue_map, authority = _authority(row["authority"])
    sources = validate_dialogue_sources(
        tuple(_source(item) for item in row["sources"]), dialogue_map)
    expected = dict(row["expectedAuxiliaryCounts"])
    stems = _auxiliary_set(row["auxiliaryStems"], expected)
    mode = row["executionMode"]
    dialogue_dir = _target(
        row["dialogueGenerationDir"], "dialogue generation",
        mode == "incremental")
    program_dir = _target(
        row["programGenerationDir"], "program generation", False)
    return ValidatedDialogueProgram(
        track, dialogue_map, authority["dialogueMapHash"], authority,
        sources, stems, auxiliary_snapshot_set_hash(stems), expected,
        dialogue_dir, program_dir, _tools(row["tools"]), mode)
