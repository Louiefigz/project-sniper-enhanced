#!/usr/bin/env python3
"""Closed Ask Editor phrase-analysis bridge for ``cut.restoreSpeech``."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from edit.cut_repair import RestoreSpeechInput, analyze_restore_speech
from edit.cut_repair_existing_lead_filter import filter_existing_lead_candidates
from edit.cut_repair_context_sources import (
    digest as materialized_digest,
    stable_file_digest,
    stable_text,
)
from edit.exact_timing import (
    FrameRange,
    PositiveRational,
    ProjectClock,
    SampleRange,
)
from edit.non_ripple_contracts import (
    CompiledCutSegment,
    DependentTiming,
    RemovableSilence,
)
from edit.cut_repair_route_target import parse_phrase_target
from edit.cut_repair_route_evidence import (
    RouteEvidenceError,
    validate_route_evidence,
)
from edit.target_resolver import build_word_refs

_HASH = re.compile(r"^[0-9a-f]{64}$")
_CONTEXT_NAME = "cut_repair_context_v1.json"
class RouteContractError(ValueError):
    """Controller-owned route input is absent, stale, or malformed."""

def _object(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise RouteContractError(f"{label} must be an object")
    return value

def _keys(value: dict, allowed: set[str], required: set[str],
          label: str) -> None:
    extras = set(value) - allowed
    missing = required - set(value)
    if extras or missing:
        raise RouteContractError(
            f"{label} fields are not closed: "
            f"extras={sorted(extras)}, missing={sorted(missing)}")

def _integer(value: object, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise RouteContractError(f"{label} must be an integer >= {minimum}")
    return value

def _hash(value: object, label: str) -> str:
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        raise RouteContractError(f"{label} must be a lowercase SHA-256")
    return value

def _canonical_hash(value: object) -> str:
    return materialized_digest(value)

def _stable_json(path: str, label: str) -> dict:
    lexical = os.path.abspath(path)
    if lexical != path or os.path.realpath(path) != path:
        raise RouteContractError(f"{label} path must be canonical")
    before = os.stat(path, follow_symlinks=False)
    if not os.path.isfile(path) or os.path.islink(path):
        raise RouteContractError(f"{label} must be a regular file")
    with open(path, encoding="utf-8") as stream:
        value = json.load(stream)
    after = os.stat(path, follow_symlinks=False)
    observed = (before.st_dev, before.st_ino, before.st_size,
                before.st_mtime_ns, before.st_ctime_ns)
    final = (after.st_dev, after.st_ino, after.st_size,
             after.st_mtime_ns, after.st_ctime_ns)
    if observed != final:
        raise RouteContractError(f"{label} changed while read")
    return _object(value, label)

def _range(value: object, label: str, sample: bool = False):
    row = _object(value, label)
    keys = ({"startSample", "endSampleExclusive"} if sample else
            {"startFrame", "endFrameExclusive"})
    _keys(row, keys, keys, label)
    start_key = "startSample" if sample else "startFrame"
    end_key = "endSampleExclusive" if sample else "endFrameExclusive"
    start = _integer(row[start_key], f"{label}.{start_key}")
    end = _integer(row[end_key], f"{label}.{end_key}", 1)
    try:
        return SampleRange(start, end) if sample else FrameRange(start, end)
    except ValueError as exc:
        raise RouteContractError(f"{label} is empty") from exc

def _rate(value: object, label: str) -> PositiveRational:
    try:
        return PositiveRational.from_value(value)
    except (TypeError, ValueError) as exc:
        raise RouteContractError(f"{label} is not a positive rational") from exc

def _segments(rows: object) -> tuple[CompiledCutSegment, ...]:
    if not isinstance(rows, list) or not rows:
        raise RouteContractError("context.segments must be non-empty")
    result = []
    allowed = {
        "segmentId", "elementVersion", "sourceId", "sourceRate",
        "sourceSamples", "outputFrames", "speed", "sourceFps",
    }
    for index, value in enumerate(rows):
        row = _object(value, f"segments[{index}]")
        _keys(row, allowed, allowed - {"sourceFps"}, f"segments[{index}]")
        result.append(CompiledCutSegment(
            str(row["segmentId"]),
            _integer(row["elementVersion"], "segment elementVersion", 1),
            str(row["sourceId"]),
            _integer(row["sourceRate"], "segment sourceRate", 1),
            _range(row["sourceSamples"], "segment sourceSamples", True),
            _range(row["outputFrames"], "segment outputFrames"),
            _rate(row["speed"], "segment speed"),
            (_rate(row["sourceFps"], "segment sourceFps")
             if "sourceFps" in row else None),
        ))
    return tuple(result)

def _silences(rows: object) -> tuple[RemovableSilence, ...]:
    if not isinstance(rows, list):
        raise RouteContractError("context.silences must be an array")
    result = []
    keys = {
        "silenceId", "segmentId", "sourceId",
        "sourceSamples", "outputFrames",
    }
    for index, value in enumerate(rows):
        row = _object(value, f"silences[{index}]")
        _keys(row, keys, keys, f"silences[{index}]")
        result.append(RemovableSilence(
            str(row["silenceId"]), str(row["segmentId"]),
            str(row["sourceId"]),
            _range(row["sourceSamples"], "silence sourceSamples", True),
            _range(row["outputFrames"], "silence outputFrames"),
        ))
    return tuple(result)

def _dependents(rows: object) -> tuple[DependentTiming, ...]:
    if not isinstance(rows, list):
        raise RouteContractError("context.dependents must be an array")
    result = []
    keys = {"stableId", "elementKind", "frames", "anchorType"}
    for index, value in enumerate(rows):
        row = _object(value, f"dependents[{index}]")
        _keys(row, keys, keys, f"dependents[{index}]")
        result.append(DependentTiming(
            str(row["stableId"]), str(row["elementKind"]),
            _range(row["frames"], "dependent frames"),
            str(row["anchorType"])))
    return tuple(result)

def _ranges(rows: object, label: str, sample: bool = False) -> tuple:
    if not isinstance(rows, list):
        raise RouteContractError(f"{label} must be an array")
    return tuple(_range(row, f"{label}[{index}]", sample)
                 for index, row in enumerate(rows))

def _evidence(value: object) -> None:
    try:
        validate_route_evidence(value)
    except RouteEvidenceError as exc:
        raise RouteContractError(str(exc)) from exc

def _media(value: object, label: str, source: bool = False) -> None:
    row = _object(value, label)
    keys = {"path", "sha256"} | ({"sourceId"} if source else set())
    _keys(row, keys, keys, label)
    if source and not isinstance(row["sourceId"], str):
        raise RouteContractError(f"{label}.sourceId must be a string")
    if not isinstance(row["path"], str) or stable_file_digest(
            row["path"], label) != _hash(row["sha256"], f"{label}.sha256"):
        raise RouteContractError(f"{label} bytes are stale")


@dataclass(frozen=True)
class _Authority:
    document: dict
    authority_hash: str

def _authority(producer_dir: str,
               context_path: str | None = None) -> _Authority:
    context_path = context_path or os.path.join(producer_dir, _CONTEXT_NAME)
    document = _stable_json(context_path, "cut repair context")
    allowed = {
        "schemaVersion", "kind", "parentRevisionHash", "transcript",
        "segments", "silences", "coveredPicture", "replaceableAudio",
        "replaceableAudioEvidenceHash", "dependents", "clock", "totalFrames",
        "parentTimelineMapHash", "parentPictureLockHash", "maxDirtyFrames",
        "maxAudioOverlapFrames", "evidence", "sourceMedia", "parentMedia",
        "sourceSnapshotSetHash", "dialogueSources", "authorityHash",
        "existingAudioLeadSampleRanges",
    }
    required = allowed - {
        "sourceSnapshotSetHash", "dialogueSources",
        "existingAudioLeadSampleRanges"}
    _keys(document, allowed, required, "cut repair context")
    if ("sourceSnapshotSetHash" in document) \
            != ("dialogueSources" in document):
        raise RouteContractError(
            "cut repair dialogue context bindings are incomplete")
    supplied = _hash(document["authorityHash"], "context.authorityHash")
    core = {key: value for key, value in document.items()
            if key != "authorityHash"}
    if supplied != _canonical_hash(core):
        raise RouteContractError("cut repair context authority hash is stale")
    if document["schemaVersion"] != 1 \
            or document["kind"] != "cut-repair-analysis-context":
        raise RouteContractError("cut repair context type is unsupported")
    head_path = os.path.join(producer_dir, ".sniper-authority-v1", "ACTIVE_HEAD")
    head = stable_text(head_path, "ACTIVE_HEAD", "ascii").strip()
    if _hash(head, "ACTIVE_HEAD") != document["parentRevisionHash"]:
        raise RouteContractError("cut repair context does not bind ACTIVE_HEAD")
    _evidence(document["evidence"])
    _media(document["sourceMedia"], "context.sourceMedia", True)
    _media(document["parentMedia"], "context.parentMedia")
    return _Authority(document, supplied)

def _input(authority: _Authority, directive: dict) -> RestoreSpeechInput:
    document = authority.document
    transcript = _object(document["transcript"], "context.transcript")
    _keys(transcript, {"sourceId", "timingHash", "words"},
          {"sourceId", "timingHash", "words"}, "context.transcript")
    clock = _object(document["clock"], "context.clock")
    _keys(clock, {"fps", "sampleRate"}, {"fps", "sampleRate"}, "context.clock")
    words = transcript["words"]
    if not isinstance(words, list):
        raise RouteContractError("context transcript words must be an array")
    return RestoreSpeechInput(
        tuple(build_word_refs(
            str(transcript["sourceId"]), words,
            _hash(transcript["timingHash"], "transcript timing hash"))),
        parse_phrase_target(directive["target"]),
        _segments(document["segments"]), _silences(document["silences"]),
        _ranges(document["coveredPicture"], "coveredPicture"),
        _ranges(document["replaceableAudio"], "replaceableAudio", True),
        _hash(document["replaceableAudioEvidenceHash"],
              "replaceable audio evidence"),
        _dependents(document["dependents"]),
        ProjectClock(
            _rate(clock["fps"], "project fps"),
            _integer(clock["sampleRate"], "sampleRate", 1)),
        _integer(document["totalFrames"], "totalFrames", 1),
        _hash(document["parentTimelineMapHash"], "parent timeline map"),
        _hash(document["parentPictureLockHash"], "parent picture lock"),
        _integer(document["maxDirtyFrames"], "maxDirtyFrames", 1),
        _integer(document["maxAudioOverlapFrames"],
                 "maxAudioOverlapFrames", 1),
    )

def run(producer_dir: str, directive_path: str,
        context_path: str | None = None) -> dict:
    """Resolve a closed phrase against controller-owned exact evidence."""
    producer = os.path.realpath(producer_dir)
    if producer != os.path.abspath(producer_dir) or not os.path.isdir(producer):
        raise RouteContractError("producer directory must be canonical")
    directive = _stable_json(directive_path, "cut repair directive")
    keys = {"schemaVersion", "operation", "mode", "target"}
    _keys(directive, keys, keys, "cut repair directive")
    if directive["schemaVersion"] != 1 \
            or directive["operation"] != "cut.restoreSpeech" \
            or directive["mode"] != "analyze":
        raise RouteContractError("cut repair directive mode is unsupported")
    authority = _authority(producer, context_path)
    result = filter_existing_lead_candidates(analyze_restore_speech(
        _input(authority, directive)),
        authority.document.get("existingAudioLeadSampleRanges"))
    return {
        **result,
        "routeStatus": "analysis-only-no-mutation",
        "contextAuthorityHash": authority.authority_hash,
        "parentRevisionHash": authority.document["parentRevisionHash"],
    }
