"""Exact sample-native dialogue track and compiled-map authority.

This layer derives and verifies media-independent mapping only.  It does not
render, stage a cut review, promote media, or mutate legacy ``audioLeadMs``.
"""
from __future__ import annotations

import hashlib

from cross_runtime_canonical_json import canonical_compact_json
from edit.dialogue_contracts import (
    MAP_KEYS,
    DialogueAuthorityError,
    derive_mapping,
    exact_keys,
    object_value,
    parse_dialogue_track,
    parse_header,
    parse_segment,
    rational,
    sha256,
    validate_segments,
)
from edit.exact_timing import PositiveRational, ProjectClock

__all__ = [
    "DialogueAuthorityError",
    "compile_dialogue_map",
    "dialogue_map_hash",
    "dialogue_track_hash",
    "parse_dialogue_map",
    "parse_dialogue_track",
    "validate_dialogue_authority",
]


def _derived_entry(row: dict, clock: ProjectClock,
                   tolerance: PositiveRational) -> dict:
    normalized, effective = derive_mapping(row, clock, tolerance)
    prefix = dict(row)
    role = prefix.pop("role")
    handle = {key: prefix.pop(key) for key in (
        "seamSample", "coveredByCutSegmentId") if key in prefix}
    return {
        **prefix,
        "normalizedSourceSampleRange": normalized.to_dict(),
        "effectiveSpeed": effective.to_dict(),
        "role": role,
        **handle,
    }


def dialogue_track_hash(value: object) -> str:
    """Hash canonical parsed track content with cross-language JSON rules."""
    track = parse_dialogue_track(value)
    encoded = canonical_compact_json(track).encode()
    return hashlib.sha256(encoded).hexdigest()


def dialogue_map_hash(value: object) -> str:
    """Hash one fully proved, canonical ``DialogueMapV1`` document."""
    dialogue_map = parse_dialogue_map(value)
    encoded = canonical_compact_json(dialogue_map).encode()
    return hashlib.sha256(encoded).hexdigest()


def compile_dialogue_map(value: object) -> dict:
    """Deterministically derive ``DialogueMapV1`` without rendering media."""
    track = parse_dialogue_track(value)
    clock = ProjectClock(
        PositiveRational.from_value(track["projectFps"]),
        track["projectSampleRate"],
    )
    tolerance = PositiveRational.from_value(
        track["maxAbsoluteSpeedDeviation"])
    header = {key: item for key, item in track.items() if key != "segments"}
    header["kind"] = "dialogue-map"
    return {
        **header,
        "dialogueTrackHash": dialogue_track_hash(track),
        "entries": [
            _derived_entry(row, clock, tolerance)
            for row in track["segments"]
        ],
    }


def parse_dialogue_map(value: object) -> dict:
    """Parse and prove all derived fields in one ``DialogueMapV1``."""
    row = object_value(value, "DialogueMapV1")
    exact_keys(row, MAP_KEYS, MAP_KEYS, "DialogueMapV1")
    parsed, clock = parse_header(row, "dialogue-map")
    value_rows = row["entries"]
    if not isinstance(value_rows, list):
        raise DialogueAuthorityError("DialogueMapV1.entries must be an array")
    entries = [parse_segment(item, f"entries[{index}]", True)
               for index, item in enumerate(value_rows)]
    validate_segments(entries, parsed["totalOutputSamples"])
    tolerance = rational(
        parsed["maxAbsoluteSpeedDeviation"], "maximum speed deviation")
    for entry in entries:
        source = {key: item for key, item in entry.items()
                  if key not in {
                      "normalizedSourceSampleRange", "effectiveSpeed"}}
        if entry != _derived_entry(source, clock, tolerance):
            raise DialogueAuthorityError(
                "DialogueMapV1 contains a stale derived sample mapping")
    return {
        **parsed,
        "dialogueTrackHash": sha256(
            row["dialogueTrackHash"], "DialogueMapV1.dialogueTrackHash"),
        "entries": entries,
    }


def validate_dialogue_authority(track_value: object,
                                map_value: object) -> tuple[dict, dict]:
    """Cross-bind one track and its exact deterministic compiled map."""
    track = parse_dialogue_track(track_value)
    dialogue_map = parse_dialogue_map(map_value)
    if dialogue_map != compile_dialogue_map(track):
        raise DialogueAuthorityError(
            "DialogueMapV1 does not exactly bind DialogueTrackV1")
    return track, dialogue_map
