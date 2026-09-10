"""Resolve stable source words through exact ``DialogueMapV1`` authority."""
from __future__ import annotations

import re

from captions.caption_occurrences import occurrence_word_id
from captions.caption_contract import BIDI_CONTROL_RE, CaptionContractError, WORD_ID_RE
from edit.dialogue_authority import dialogue_map_hash, parse_dialogue_map
from edit.exact_timing import PositiveRational, ProjectClock, SampleRange

_HASH = re.compile(r"^[0-9a-f]{64}$")
_STABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
_WORD_KEYS = {"sourceWordId", "occurrence", "text", "sourceId",
              "ownerCutSegmentId", "sourceSampleRate", "sourceSampleRange",
              "transcriptTimingHash", "speaker", "captionWordId"}
_WORD_REQUIRED = _WORD_KEYS - {"ownerCutSegmentId", "speaker", "captionWordId"}
_ROLE_TRANSITIONS = {("j-cut-handle", "primary"), ("primary", "l-cut-handle")}

class DialogueCaptionTimingError(CaptionContractError):
    """A source word cannot be mapped to one exact dialogue occurrence."""


def _object(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise DialogueCaptionTimingError(f"{label} must be an object")
    return value


def _keys(row: dict, allowed: set[str], required: set[str], label: str) -> None:
    extras = set(row) - allowed
    missing = required - set(row)
    if extras or missing:
        raise DialogueCaptionTimingError(
            f"{label} fields are not closed: "
            f"extras={sorted(extras)}, missing={sorted(missing)}")


def _positive(value: object, label: str) -> int:
    if type(value) is not int or value <= 0 \
            or value > 9_007_199_254_740_991:
        raise DialogueCaptionTimingError(
            f"{label} must be a positive safe integer")
    return value


def _stable(value: object, label: str) -> str:
    if not isinstance(value, str) or _STABLE_ID.fullmatch(value) is None:
        raise DialogueCaptionTimingError(f"{label} must be a stable ID")
    return value


def _source_word_id(value: object, label: str) -> str:
    if not isinstance(value, str) or WORD_ID_RE.fullmatch(value) is None:
        raise DialogueCaptionTimingError(f"{label} must be a stable word ID")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 500 \
            or any(char in value for char in ("\\", "\r", "\n")) \
            or BIDI_CONTROL_RE.search(value):
        raise DialogueCaptionTimingError(f"{label} is unsafe or empty")
    return value


def _sample_range(value: object, label: str) -> SampleRange:
    row = _object(value, label)
    keys = {"startSample", "endSampleExclusive"}
    _keys(row, keys, keys, label)
    try:
        return SampleRange(row["startSample"], row["endSampleExclusive"])
    except (TypeError, ValueError) as exc:
        raise DialogueCaptionTimingError(
            f"{label} must be a non-empty integer sample range") from exc


def _source_word(value: object, index: int) -> dict:
    label = f"dialogue source word[{index}]"
    row = _object(value, label)
    _keys(row, _WORD_KEYS, _WORD_REQUIRED, label)
    timing_hash = row["transcriptTimingHash"]
    if not isinstance(timing_hash, str) or _HASH.fullmatch(timing_hash) is None:
        raise DialogueCaptionTimingError(
            f"{label}.transcriptTimingHash must be a SHA-256")
    result = {
        "sourceWordId": _source_word_id(
            row["sourceWordId"], f"{label}.sourceWordId"),
        "occurrence": _positive(row["occurrence"], f"{label}.occurrence"),
        "text": _text(row["text"], f"{label}.text"),
        "sourceId": _stable(row["sourceId"], f"{label}.sourceId"),
        "sourceSampleRate": _positive(
            row["sourceSampleRate"], f"{label}.sourceSampleRate"),
        "sourceSampleRange": _sample_range(
            row["sourceSampleRange"], f"{label}.sourceSampleRange").to_dict(),
        "transcriptTimingHash": timing_hash,
    }
    if "ownerCutSegmentId" in row:
        result["ownerCutSegmentId"] = _stable(
            row["ownerCutSegmentId"], f"{label}.ownerCutSegmentId")
    if "captionWordId" in row:
        result["captionWordId"] = _source_word_id(
            row["captionWordId"], f"{label}.captionWordId")
    if isinstance(row.get("speaker"), (str, int)) \
            and not isinstance(row.get("speaker"), bool):
        result["speaker"] = row["speaker"]
    elif "speaker" in row:
        raise DialogueCaptionTimingError(f"{label}.speaker is invalid")
    return result


def _point(entry: dict, source_sample: int, project_rate: int) -> int:
    normalized = source_sample * project_rate // entry["sourceSampleRate"]
    source = entry["normalizedSourceSampleRange"]
    output = entry["outputSampleRange"]
    source_length = source["endSampleExclusive"] - source["startSample"]
    output_length = output["endSampleExclusive"] - output["startSample"]
    return output["startSample"] + (
        (normalized - source["startSample"]) * output_length // source_length)


def _overlap(entry: dict, word: dict) -> tuple[int, int] | None:
    source = entry["sourceSampleRange"]
    target = word["sourceSampleRange"]
    start = max(source["startSample"], target["startSample"])
    end = min(source["endSampleExclusive"], target["endSampleExclusive"])
    return (start, end) if start < end else None


def _candidate_groups(word: dict, dialogue_map: dict) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for entry in dialogue_map["entries"]:
        if entry["sourceId"] != word["sourceId"] \
                or entry["sourceSampleRate"] != word["sourceSampleRate"] \
                or _overlap(entry, word) is None:
            continue
        groups.setdefault(entry["cutSegmentId"], []).append(entry)
    owner = word.get("ownerCutSegmentId")
    if owner is not None:
        return {owner: groups.get(owner, [])}
    return groups


def _pieces(word: dict, entries: list[dict],
            project_rate: int) -> list[dict]:
    rows = []
    for entry in entries:
        overlap = _overlap(entry, word)
        if overlap is None:
            continue
        start, end = overlap
        rows.append({
            "entry": entry, "sourceStart": start, "sourceEnd": end,
            "outputStart": _point(entry, start, project_rate),
            "outputEnd": _point(entry, end, project_rate),
        })
    rows.sort(key=lambda row: (
        row["sourceStart"], row["sourceEnd"],
        row["entry"]["dialogueSegmentId"]))
    return rows


def _validate_pieces(word: dict, rows: list[dict]) -> None:
    target = word["sourceSampleRange"]
    if not rows or rows[0]["sourceStart"] != target["startSample"] \
            or rows[-1]["sourceEnd"] != target["endSampleExclusive"]:
        raise DialogueCaptionTimingError(
            "dialogue ownership does not cover the complete source word")
    for left, right in zip(rows, rows[1:]):
        roles = left["entry"]["role"], right["entry"]["role"]
        if left["sourceEnd"] != right["sourceStart"] \
                or left["outputEnd"] != right["outputStart"] \
                or roles not in _ROLE_TRANSITIONS:
            raise DialogueCaptionTimingError(
                "source word crosses incompatible split dialogue spans")
    if any(row["outputEnd"] <= row["outputStart"] for row in rows):
        raise DialogueCaptionTimingError(
            "source word collapses on the project sample clock")


def _mapped_owner(word: dict, owner: str, entries: list[dict],
                  clock: ProjectClock) -> dict:
    rows = _pieces(word, entries, clock.sample_rate)
    _validate_pieces(word, rows)
    output = SampleRange(rows[0]["outputStart"], rows[-1]["outputEnd"])
    first_frame = clock.containing_frame(output.start_sample)
    last_frame = clock.containing_frame(output.end_sample_exclusive - 1)
    roles = [row["entry"]["role"] for row in rows]
    covering = [
        (row["entry"].get("coveredByCutSegmentId")
         if row["entry"]["role"] != "primary" else owner)
        for row in rows
    ]
    return {
        "ownerCutSegmentId": owner,
        "ownerElementVersion": rows[0]["entry"]["elementVersion"],
        "dialogueSegmentIds": [
            row["entry"]["dialogueSegmentId"] for row in rows],
        "dialogueRoles": roles,
        "coveringCutSegmentIds": covering,
        "startSample": output.start_sample,
        "endSampleExclusive": output.end_sample_exclusive,
        "startFrame": first_frame,
        "endFrameExclusive": last_frame + 1,
    }


def _resolve_owner(word: dict, dialogue_map: dict,
                   clock: ProjectClock) -> dict:
    valid: list[dict] = []
    errors: list[DialogueCaptionTimingError] = []
    for owner, entries in _candidate_groups(word, dialogue_map).items():
        try:
            valid.append(_mapped_owner(word, owner, entries, clock))
        except DialogueCaptionTimingError as exc:
            errors.append(exc)
    if len(valid) > 1:
        raise DialogueCaptionTimingError(
            "source word has ambiguous/double dialogue ownership")
    if not valid:
        if errors:
            raise errors[0]
        raise DialogueCaptionTimingError(
            "source word has no dialogue-map ownership")
    return valid[0]


def _resolved_word(word: dict, mapping: dict) -> dict:
    caption_word_id = word.get("captionWordId")
    source = {key: value for key, value in word.items() if key != "captionWordId"}
    return {
        "wordId": caption_word_id or occurrence_word_id(
            word["sourceWordId"], word["occurrence"]),
        **source,
        **mapping,
    }


def _validate_occurrences(words: list[dict]) -> None:
    seen: set[tuple[str, int]] = set()
    grouped: dict[str, list[dict]] = {}
    for word in words:
        key = word["sourceWordId"], word["occurrence"]
        if key in seen:
            raise DialogueCaptionTimingError(
                "source word occurrence identity is duplicated")
        seen.add(key)
        grouped.setdefault(word["sourceWordId"], []).append(word)
    identity = ("text", "sourceId", "sourceSampleRate",
                "sourceSampleRange", "transcriptTimingHash")
    for rows in grouped.values():
        if any(any(row[key] != rows[0][key] for key in identity)
               for row in rows[1:]):
            raise DialogueCaptionTimingError(
                "stable source word identity changed across occurrences")
        ordered = sorted(rows, key=lambda row: (
            row["startSample"], row["endSampleExclusive"],
            row["ownerCutSegmentId"]))
        if [row["occurrence"] for row in ordered] \
                != list(range(1, len(rows) + 1)):
            raise DialogueCaptionTimingError(
                "word occurrences must follow exact output order")


def resolve_dialogue_caption_words(source_words: object,
                                   map_value: object) -> dict:
    """Resolve exact words and retain source plus kept-occurrence identity."""
    if not isinstance(source_words, list) or not source_words:
        raise DialogueCaptionTimingError(
            "dialogue source words must be a non-empty array")
    dialogue_map = parse_dialogue_map(map_value)
    clock = ProjectClock(
        PositiveRational.from_value(dialogue_map["projectFps"]),
        dialogue_map["projectSampleRate"])
    parsed = [_source_word(row, index)
              for index, row in enumerate(source_words)]
    resolved = [_resolved_word(
        word, _resolve_owner(word, dialogue_map, clock)) for word in parsed]
    resolved.sort(key=lambda row: (
        row["startSample"], row["endSampleExclusive"], row["wordId"]))
    _validate_occurrences(resolved)
    if len({row["wordId"] for row in resolved}) != len(resolved):
        raise DialogueCaptionTimingError(
            "derived occurrence word identity collided")
    return {
        "schemaVersion": 1, "kind": "dialogue-caption-timing",
        "dialogueMapHash": dialogue_map_hash(dialogue_map),
        "dialogueTrackHash": dialogue_map["dialogueTrackHash"],
        "pictureTimelineMapHash": dialogue_map["pictureTimelineMapHash"],
        "fps": dialogue_map["projectFps"],
        "sampleRate": dialogue_map["projectSampleRate"],
        "words": resolved,
    }
