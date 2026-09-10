"""Resolve controller-bound transcript words into kept dialogue occurrences."""
from __future__ import annotations

from dataclasses import dataclass

from captions.caption_contract import WORD_ID_RE
from captions.caption_occurrences import occurrence_word_id
from edit.cut_repair_context_sources import digest, require_hash
from edit.dialogue_authority import parse_dialogue_map

_PARTIAL_WORD_FLOOR_MS = 40


class CutRepairDialogueWordError(ValueError):
    """Source timing cannot be mapped to unambiguous kept occurrences."""


@dataclass(frozen=True)
class _CatalogRow:
    source_word: dict
    owner: str
    occurrence: int
    occurrence_count: int
    output_order: int


def _source_index(context: dict) -> dict[str, dict]:
    rows = context.get("dialogueSources")
    if not isinstance(rows, list) or not rows:
        raise CutRepairDialogueWordError(
            "CAPTION_DIALOGUE_SOURCE_TIMING_REQUIRED")
    result = {}
    for position, value in enumerate(rows):
        if not isinstance(value, dict):
            raise CutRepairDialogueWordError(
                "CAPTION_DIALOGUE_SOURCE_TIMING_REQUIRED")
        required = {
            "sourceId", "sourceSampleRate", "sourceMediaSha256",
            "transcriptTimingHash", "words",
        }
        if set(value) != required or value.get("sourceId") in result:
            raise CutRepairDialogueWordError(
                "CAPTION_DIALOGUE_SOURCE_TIMING_REQUIRED")
        result[value["sourceId"]] = _source(value, position)
    snapshots = [{
        "sourceId": row["sourceId"],
        "sourceMediaSha256": row["sourceMediaSha256"],
        "transcriptTimingHash": row["transcriptTimingHash"],
    } for row in result.values()]
    try:
        expected = require_hash(
            context.get("sourceSnapshotSetHash"),
            "caption dialogue source snapshot set")
    except ValueError as exc:
        raise CutRepairDialogueWordError(
            "CAPTION_DIALOGUE_SOURCE_SNAPSHOT_STALE") from exc
    if digest(sorted(snapshots, key=lambda row: row["sourceId"])) != expected:
        raise CutRepairDialogueWordError(
            "CAPTION_DIALOGUE_SOURCE_SNAPSHOT_STALE")
    return result


def _source(value: dict, position: int) -> dict:
    words = value.get("words")
    rate = value.get("sourceSampleRate")
    if type(rate) is not int or rate <= 0 \
            or not isinstance(words, list) or not words:
        raise CutRepairDialogueWordError(
            "CAPTION_DIALOGUE_SOURCE_TIMING_REQUIRED")
    try:
        media_hash = require_hash(
            value.get("sourceMediaSha256"), "dialogue source media")
        timing_hash = require_hash(
            value.get("transcriptTimingHash"), "dialogue transcript timing")
    except ValueError as exc:
        raise CutRepairDialogueWordError(
            "CAPTION_DIALOGUE_SOURCE_TIMING_REQUIRED") from exc
    parsed = [_word(row, position, index)
              for index, row in enumerate(words)]
    ids = [row["sourceWordId"] for row in parsed]
    if len(ids) != len(set(ids)):
        raise CutRepairDialogueWordError(
            "CAPTION_DIALOGUE_SOURCE_WORD_ID_DUPLICATED")
    return {
        **value, "sourceMediaSha256": media_hash,
        "transcriptTimingHash": timing_hash, "words": parsed,
    }


def _word(value: object, source_position: int, word_position: int) -> dict:
    label = f"dialogueSources[{source_position}].words[{word_position}]"
    if not isinstance(value, dict):
        raise CutRepairDialogueWordError(f"{label} is malformed")
    allowed = {"sourceWordId", "text", "sourceSampleRange", "speaker"}
    required = allowed - {"speaker"}
    if set(value) - allowed or required - set(value):
        raise CutRepairDialogueWordError(f"{label} is not closed")
    ident, text, sample_range = (
        value["sourceWordId"], value["text"], value["sourceSampleRange"])
    if not isinstance(ident, str) or not WORD_ID_RE.fullmatch(ident) \
            or not isinstance(text, str) or not text.strip() \
            or not isinstance(sample_range, dict) \
            or set(sample_range) != {"startSample", "endSampleExclusive"}:
        raise CutRepairDialogueWordError(f"{label} is malformed")
    start = sample_range["startSample"]
    end = sample_range["endSampleExclusive"]
    if type(start) is not int or type(end) is not int or start < 0 or end <= start:
        raise CutRepairDialogueWordError(f"{label} has invalid samples")
    return dict(value)


def _owner_entries(dialogue_map: dict) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for entry in dialogue_map["entries"]:
        result.setdefault(entry["cutSegmentId"], []).append(entry)
    return result


def _intersections(word: dict, entries: list[dict]) -> list[tuple[int, int]]:
    target = word["sourceSampleRange"]
    result = []
    for entry in entries:
        source = entry["sourceSampleRange"]
        start = max(target["startSample"], source["startSample"])
        end = min(target["endSampleExclusive"], source["endSampleExclusive"])
        if start < end:
            result.append((start, end))
    return sorted(result)


def _merged(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    result: list[list[int]] = []
    for start, end in ranges:
        if not result or start > result[-1][1]:
            result.append([start, end])
        else:
            result[-1][1] = max(result[-1][1], end)
    return [(start, end) for start, end in result]


def _clipped(word: dict, entries: list[dict], source_rate: int) -> dict | None:
    ranges = _merged(_intersections(word, entries))
    if len(ranges) != 1:
        return None
    start, end = ranges[0]
    target = word["sourceSampleRange"]
    complete = (start, end) == (
        target["startSample"], target["endSampleExclusive"])
    kept = end - start
    total = target["endSampleExclusive"] - target["startSample"]
    perceptible = kept * 1000 >= _PARTIAL_WORD_FLOOR_MS * source_rate
    if not complete and (kept * 2 < total or not perceptible):
        return None
    return {"startSample": start, "endSampleExclusive": end}


def _entry_source(entries: list[dict]) -> tuple[str, int]:
    identities = {
        (row["sourceId"], row["sourceSampleRate"]) for row in entries
    }
    if len(identities) != 1:
        raise CutRepairDialogueWordError(
            "CAPTION_DIALOGUE_OWNER_SOURCE_AMBIGUOUS")
    return next(iter(identities))


def _owner_candidates(
    owner: str, entries: list[dict], sources: dict[str, dict],
) -> list[tuple[dict, str, int]]:
    source_id, source_rate = _entry_source(entries)
    source = sources.get(source_id)
    if source is None or source["sourceSampleRate"] != source_rate:
        raise CutRepairDialogueWordError(
            "CAPTION_DIALOGUE_SOURCE_TIMING_REQUIRED")
    return [
        (word, owner, min(
            row["outputSampleRange"]["startSample"] for row in entries))
        for word in source["words"]
        if _intersections(word, entries)
    ]


def _catalog(context: dict, child_map: dict) -> list[_CatalogRow]:
    sources = _source_index(context)
    candidates = []
    for owner, entries in _owner_entries(child_map).items():
        candidates.extend(_owner_candidates(owner, entries, sources))
    grouped: dict[str, list[tuple[dict, str, int]]] = {}
    for row in candidates:
        grouped.setdefault(row[0]["sourceWordId"], []).append(row)
    result = []
    for rows in grouped.values():
        ordered = sorted(rows, key=lambda row: (row[2], row[1]))
        for index, (word, owner, output) in enumerate(ordered, 1):
            result.append(_CatalogRow(
                word, owner, index, len(ordered), output))
    return sorted(result, key=lambda row: (
        row.output_order, row.source_word["sourceWordId"], row.owner))


def _caption_id(row: _CatalogRow) -> str:
    source_id = row.source_word["sourceWordId"]
    return (source_id if row.occurrence_count == 1
            else occurrence_word_id(source_id, row.occurrence))


def source_words_for_dialogue_map(
    context: dict,
    map_value: object,
    child_map_value: object,
) -> list[dict]:
    """Return exact kept source-word occurrences using one shared child catalog."""
    dialogue_map = parse_dialogue_map(map_value)
    child_map = parse_dialogue_map(child_map_value)
    sources = _source_index(context)
    owners = _owner_entries(dialogue_map)
    result = []
    for row in _catalog(context, child_map):
        entries = owners.get(row.owner, [])
        source_id, source_rate = _entry_source(entries) if entries else ("", 0)
        source = sources.get(source_id)
        clipped = (_clipped(row.source_word, entries, source_rate)
                   if source is not None else None)
        if clipped is None:
            continue
        result.append({
            "sourceWordId": row.source_word["sourceWordId"],
            "captionWordId": _caption_id(row),
            "occurrence": row.occurrence,
            "text": row.source_word["text"],
            "sourceId": source_id,
            "ownerCutSegmentId": row.owner,
            "sourceSampleRate": source_rate,
            "sourceSampleRange": clipped,
            "transcriptTimingHash": source["transcriptTimingHash"],
            **({"speaker": row.source_word["speaker"]}
               if "speaker" in row.source_word else {}),
        })
    if not result:
        raise CutRepairDialogueWordError(
            "CAPTION_DIALOGUE_NO_KEPT_WORD_AUTHORITY")
    return result
