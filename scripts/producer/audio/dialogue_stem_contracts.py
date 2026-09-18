"""Closed, source-pinned inputs for exact dialogue-stem rendering."""
from __future__ import annotations

import os
from dataclasses import dataclass

from edit.dialogue_authority import (
    dialogue_map_hash,
    parse_dialogue_map,
)
from edit.dialogue_contracts import sha256, stable_id
from edit.picture_lock_common import content_hash
from fingerprints import file_sha256

_SAFE_MAX = 9_007_199_254_740_991


class DialogueStemRenderError(RuntimeError):
    """A dialogue stem cannot be rendered and proved without ambiguity."""


def _regular_snapshot(path: str, label: str) -> str:
    if type(path) is not str or not os.path.isabs(path) \
            or os.path.islink(path) or os.path.realpath(path) != path:
        raise DialogueStemRenderError(
            f"{label} must be an absolute canonical regular snapshot")
    try:
        info = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise DialogueStemRenderError(f"{label} is unreadable: {exc}") from exc
    if not os.path.isfile(path) or info.st_nlink != 1:
        raise DialogueStemRenderError(
            f"{label} must be a single-link regular snapshot")
    return path


def _expected_hash(value: object, label: str) -> str:
    try:
        return sha256(value, label)
    except ValueError as exc:
        raise DialogueStemRenderError(str(exc)) from exc


@dataclass(frozen=True)
class DialogueStemTools:
    """Byte-pinned FFmpeg executables for one stem generation."""

    ffmpeg_path: str
    ffmpeg_sha256: str
    ffprobe_path: str
    ffprobe_sha256: str

    def validate(self) -> "DialogueStemTools":
        """Reobserve both executable snapshots immediately before use."""
        ffmpeg = _regular_snapshot(self.ffmpeg_path, "ffmpeg")
        ffprobe = _regular_snapshot(self.ffprobe_path, "ffprobe")
        ffmpeg_hash = _expected_hash(self.ffmpeg_sha256, "ffmpegSha256")
        ffprobe_hash = _expected_hash(self.ffprobe_sha256, "ffprobeSha256")
        if file_sha256(ffmpeg) != ffmpeg_hash \
                or file_sha256(ffprobe) != ffprobe_hash:
            raise DialogueStemRenderError("dialogue media tool bytes drifted")
        return DialogueStemTools(
            ffmpeg, ffmpeg_hash, ffprobe, ffprobe_hash)


@dataclass(frozen=True)
class DialogueSourceSnapshot:
    """One immutable source and its explicit audio-stream selector."""

    source_id: str
    path: str
    sha256: str
    audio_stream_index: int

    def validate(self) -> "DialogueSourceSnapshot":
        """Validate identity fields and reobserve the source bytes."""
        try:
            source_id = stable_id(self.source_id, "sourceId")
        except ValueError as exc:
            raise DialogueStemRenderError(str(exc)) from exc
        path = _regular_snapshot(self.path, f"source {source_id}")
        digest = _expected_hash(self.sha256, f"{source_id}.sha256")
        if type(self.audio_stream_index) is not int \
                or not 0 <= self.audio_stream_index <= _SAFE_MAX:
            raise DialogueStemRenderError(
                f"{source_id}.audioStreamIndex must be non-negative")
        if file_sha256(path) != digest:
            raise DialogueStemRenderError(
                f"source snapshot bytes drifted for {source_id}")
        return DialogueSourceSnapshot(
            source_id, path, digest, self.audio_stream_index)

    def authority_row(self) -> dict[str, object]:
        """Return the path-free row bound by sourceSnapshotSetHash."""
        return {
            "sourceId": self.source_id,
            "sha256": self.sha256,
            "audioStreamIndex": self.audio_stream_index,
        }


@dataclass(frozen=True)
class DialogueStemRenderRequest:
    """One private, immutable dialogue-stem generation request."""

    dialogue_map: dict[str, object]
    dialogue_map_hash: str
    sources: tuple[DialogueSourceSnapshot, ...]
    generation_dir: str
    tools: DialogueStemTools


@dataclass(frozen=True)
class ValidatedDialogueStemRequest:
    """Renderer-ready request with canonical map, sources, and tools."""

    dialogue_map: dict
    dialogue_map_hash: str
    sources: tuple[DialogueSourceSnapshot, ...]
    generation_dir: str
    tools: DialogueStemTools


def dialogue_source_snapshot_set_hash(
    sources: tuple[DialogueSourceSnapshot, ...],
) -> str:
    """Hash the sole path-free source snapshot-set representation."""
    rows = [source.authority_row() for source in sources]
    return content_hash({
        "schemaVersion": 1,
        "kind": "dialogue-source-snapshot-set",
        "sources": rows,
    })


def _validated_sources(
    sources: tuple[DialogueSourceSnapshot, ...],
    dialogue_map: dict,
) -> tuple[DialogueSourceSnapshot, ...]:
    if not isinstance(sources, tuple) or not sources:
        raise DialogueStemRenderError("dialogue sources must be a non-empty tuple")
    if not all(isinstance(source, DialogueSourceSnapshot)
               for source in sources):
        raise DialogueStemRenderError(
            "dialogue sources must contain only source snapshots")
    validated = tuple(source.validate() for source in sources)
    ids = [source.source_id for source in validated]
    if ids != sorted(ids) or len(ids) != len(set(ids)):
        raise DialogueStemRenderError(
            "dialogue sources must be unique and ordered by sourceId")
    required = sorted({row["sourceId"] for row in dialogue_map["entries"]})
    if ids != required:
        raise DialogueStemRenderError(
            "dialogue source snapshot set is not exactly closed over the map")
    if dialogue_source_snapshot_set_hash(validated) \
            != dialogue_map["sourceSnapshotSetHash"]:
        raise DialogueStemRenderError(
            "dialogue source snapshots do not bind sourceSnapshotSetHash")
    return validated


def validate_dialogue_sources(
    sources: tuple[DialogueSourceSnapshot, ...],
    dialogue_map: dict,
) -> tuple[DialogueSourceSnapshot, ...]:
    """Validate one exact source closure without choosing a render target."""
    return _validated_sources(sources, dialogue_map)


def _generation_path(value: object) -> str:
    if type(value) is not str or not os.path.isabs(value) \
            or os.path.abspath(value) != value:
        raise DialogueStemRenderError(
            "dialogue generation directory must be absolute and normalized")
    parent = os.path.dirname(value)
    if os.path.realpath(parent) != parent or not os.path.isdir(parent):
        raise DialogueStemRenderError(
            "dialogue generation parent must be an existing canonical directory")
    if os.path.lexists(value):
        raise DialogueStemRenderError(
            "dialogue generation directory already exists")
    return value


def validate_dialogue_stem_request(
    request: DialogueStemRenderRequest,
) -> ValidatedDialogueStemRequest:
    """Fail closed before any media or destination byte is written."""
    if not isinstance(request, DialogueStemRenderRequest) \
            or not isinstance(request.tools, DialogueStemTools):
        raise DialogueStemRenderError(
            "dialogue stem request/tool contract is invalid")
    try:
        dialogue_map = parse_dialogue_map(request.dialogue_map)
        observed_hash = dialogue_map_hash(dialogue_map)
    except ValueError as exc:
        raise DialogueStemRenderError(str(exc)) from exc
    expected_hash = _expected_hash(
        request.dialogue_map_hash, "dialogueMapHash")
    if observed_hash != expected_hash:
        raise DialogueStemRenderError("dialogue map hash does not match")
    tools = request.tools.validate()
    sources = _validated_sources(request.sources, dialogue_map)
    generation_dir = _generation_path(request.generation_dir)
    _validate_source_rates(dialogue_map)
    return ValidatedDialogueStemRequest(
        dialogue_map, expected_hash, sources, generation_dir, tools)


def _validate_source_rates(dialogue_map: dict) -> None:
    rates: dict[str, set[int]] = {}
    for row in dialogue_map["entries"]:
        rates.setdefault(row["sourceId"], set()).add(
            row["sourceSampleRate"])
    if any(len(values) != 1 for values in rates.values()):
        raise DialogueStemRenderError(
            "one sourceId cannot claim multiple native sample rates")
