#!/usr/bin/env python3
"""Stable transcript-word identity, frame resolution, and display corrections."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from fractions import Fraction

from captions.caption_contract import (
    BIDI_CONTROL_RE,
    CaptionContractError,
    WORD_ID_RE,
    validate_correction_ledger,
)
from captions.caption_occurrences import remap_caption_occurrences
from captions.caption_word_exact_timing import (
    corrected_token_exact_fields,
    plain_token_exact_fields,
    validate_exact_word_timing,
)
from compile_timeline import TimelineMap


@dataclass(frozen=True)
class CaptionFrameRate:
    """Exact positive project frame rate."""

    numerator: int
    denominator: int

    def __post_init__(self) -> None:
        values = (self.numerator, self.denominator)
        if any(isinstance(value, bool) or not isinstance(value, int)
               for value in values):
            raise CaptionContractError("caption frame rate must use integers")
        if self.numerator <= 0 or self.denominator <= 0:
            raise CaptionContractError("caption frame rate must be positive")

    @property
    def fraction(self) -> Fraction:
        """Normalized exact rate."""
        return Fraction(self.numerator, self.denominator)

    def to_dict(self) -> dict[str, str]:
        """Canonical PositiveRationalV1 wire authority."""
        rate = self.fraction
        return {
            "numerator": str(rate.numerator),
            "denominator": str(rate.denominator),
        }


@dataclass(frozen=True)
class CaptionWordClock:
    """Delivery frame and sample clocks used while resolving kept words."""

    rate: CaptionFrameRate
    sample_rate: int = 48_000


def stable_word_id(source_id: str, ordinal: int) -> str:
    """Mint a stable word id from source identity plus transcript ordinal."""
    if not isinstance(source_id, str) or not source_id:
        raise CaptionContractError("source id must be non-empty")
    if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 0:
        raise CaptionContractError("word ordinal must be a non-negative integer")
    payload = f"sniper-caption-word-v1\0{source_id}\0{ordinal}".encode()
    return f"w-{hashlib.sha256(payload).hexdigest()[:16]}"


def assign_stable_word_ids(source_id: str, words: list[dict]) -> list[dict]:
    """Return source words with controller-owned identities before any cut."""
    if not isinstance(words, list) or any(not isinstance(row, dict)
                                          for row in words):
        raise CaptionContractError("source words must be a list of objects")
    result: list[dict] = []
    seen: set[str] = set()
    for ordinal, row in enumerate(words):
        ident = row.get("wordId") or stable_word_id(source_id, ordinal)
        if not isinstance(ident, str) or not WORD_ID_RE.fullmatch(ident):
            raise CaptionContractError(f"source word {ordinal} has malformed wordId")
        if ident in seen:
            raise CaptionContractError(f"source word id {ident} is duplicated")
        seen.add(ident)
        result.append({
            **row, "wordId": ident, "sourceId": source_id,
            "sourceStart": float(row["start"]), "sourceEnd": float(row["end"]),
        })
    return result


def _floor_frame(seconds: float, rate: CaptionFrameRate) -> int:
    value = Fraction(str(seconds)) * rate.fraction
    return value.numerator // value.denominator


def _ceil_frame(seconds: float, rate: CaptionFrameRate) -> int:
    value = Fraction(str(seconds)) * rate.fraction
    return -(-value.numerator // value.denominator)


def _resolved_word(row: dict, rate: CaptionFrameRate) -> dict:
    start = max(0, _floor_frame(float(row["start"]), rate))
    end = max(start + 1, _ceil_frame(float(row["end"]), rate))
    result = {
        "wordId": row["wordId"], "text": str(row["word"]),
        "sourceId": row["sourceId"],
        "sourceStart": float(row["sourceStart"]),
        "sourceEnd": float(row["sourceEnd"]),
        "startFrame": start, "endFrameExclusive": end,
        **{key: row[key] for key in (
            "sourceWordId", "occurrence", "cutSegmentIndex",
            "startSample", "endSampleExclusive") if key in row},
    }
    if isinstance(row.get("speaker"), (str, int)):
        result["speaker"] = row["speaker"]
    return result


def resolve_kept_words(source_id: str, words: list[dict],
                       timeline: TimelineMap,
                       rate: CaptionFrameRate) -> list[dict]:
    """Resolve one source transcript through cuts/speed onto frame ranges."""
    return resolve_kept_word_occurrences(
        source_id, words, timeline, CaptionWordClock(rate))


def resolve_kept_word_occurrences(
    source_id: str,
    words: list[dict],
    timeline: TimelineMap,
    clock: CaptionWordClock,
) -> list[dict]:
    """Resolve unique and reused source-word occurrences on exact clocks."""
    if not isinstance(clock, CaptionWordClock):
        raise CaptionContractError("caption word clock is malformed")
    identified = assign_stable_word_ids(source_id, words)
    remapped = remap_caption_occurrences(
        identified, source_id, timeline, clock.sample_rate)
    return [_resolved_word(row, clock.rate) for row in remapped]


def merge_resolved_words(sources: list[list[dict]]) -> list[dict]:
    """Sort resolved source words and fail on duplicate identity or bad order."""
    rows = sorted((row for words in sources for row in words),
                  key=lambda row: (
                      row["startFrame"], row["endFrameExclusive"],
                      row["sourceId"], row["wordId"]))
    identities = [row.get("wordId") for row in rows]
    if len(identities) != len(set(identities)):
        raise CaptionContractError("resolved caption words repeat a word id")
    for index, row in enumerate(rows):
        _validate_resolved_word(row, index)
    return rows


def _validate_resolved_word(row: object, index: int) -> None:
    if not isinstance(row, dict):
        raise CaptionContractError(f"resolved word {index} must be an object")
    if not isinstance(row.get("wordId"), str) \
            or not WORD_ID_RE.fullmatch(row["wordId"]):
        raise CaptionContractError(f"resolved word {index} has malformed identity")
    if not isinstance(row.get("text"), str) or not row["text"].strip() \
            or any(char in row["text"] for char in ("\\", "\r", "\n")) \
            or BIDI_CONTROL_RE.search(row["text"]):
        raise CaptionContractError(
            f"resolved word {index} has invalid display text")
    start, end = row.get("startFrame"), row.get("endFrameExclusive")
    if any(isinstance(value, bool) or not isinstance(value, int)
           for value in (start, end)) or start < 0 or end <= start:
        raise CaptionContractError(f"resolved word {index} has invalid frames")
    validate_exact_word_timing(row, index)


def validate_resolved_words(words: object) -> list[dict]:
    """Validate the compiler's already-resolved word input."""
    if not isinstance(words, list):
        raise CaptionContractError("resolved words must be a list")
    result = [dict(row) if isinstance(row, dict) else row for row in words]
    for index, row in enumerate(result):
        _validate_resolved_word(row, index)
    identities = [row["wordId"] for row in result]
    if len(identities) != len(set(identities)):
        raise CaptionContractError("resolved caption words repeat a word id")
    if result != sorted(result, key=lambda row: (
            row["startFrame"], row["endFrameExclusive"], row["wordId"])):
        raise CaptionContractError("resolved caption words are not ordered")
    return result


def _correction_positions(words: list[dict], correction: dict) -> list[int]:
    positions = {row["wordId"]: index for index, row in enumerate(words)}
    present = [ident in positions for ident in correction["sourceWordIds"]]
    if not any(present):
        return []
    if not all(present):
        raise CaptionContractError(
            f"correction {correction['correctionId']} is only partly kept")
    indices = [positions[ident] for ident in correction["sourceWordIds"]]
    expected = list(range(indices[0], indices[0] + len(indices)))
    if indices != expected:
        raise CaptionContractError(
            f"correction {correction['correctionId']} is not consecutive")
    return indices


def _weighted_lengths(tokens: list[str], total_frames: int) -> list[int]:
    if total_frames < len(tokens):
        raise CaptionContractError(
            "correction has fewer frames than display tokens")
    weights = [max(1, len(token)) for token in tokens]
    available = total_frames - len(tokens)
    total_weight = sum(weights)
    extras = [available * weight // total_weight for weight in weights]
    remaining = available - sum(extras)
    remainders = [
        (available * weight % total_weight, -index)
        for index, weight in enumerate(weights)
    ]
    for _, neg_index in sorted(remainders, reverse=True)[:remaining]:
        extras[-neg_index] += 1
    return [1 + extra for extra in extras]


def _corrected_tokens(words: list[dict], correction: dict) -> list[dict]:
    start = words[0]["startFrame"]
    end = words[-1]["endFrameExclusive"]
    texts = correction["displayTokens"]
    lengths = _weighted_lengths(texts, end - start)
    source_ids = [row["wordId"] for row in words]
    speaker_values = {row.get("speaker") for row in words}
    exact = corrected_token_exact_fields(words, texts)
    result: list[dict] = []
    cursor = start
    for index, (text, length) in enumerate(zip(texts, lengths, strict=True)):
        token = {
            "tokenId": f"{correction['correctionId']}:t{index}",
            "text": text, "sourceWordIds": source_ids,
            "startFrame": cursor, "endFrameExclusive": cursor + length,
            "correctionId": correction["correctionId"],
            **exact[index],
        }
        if len(speaker_values) == 1 and None not in speaker_values:
            token["speaker"] = next(iter(speaker_values))
        result.append(token)
        cursor += length
    return result


def _plain_token(word: dict) -> dict:
    result = {
        "tokenId": f"{word['wordId']}:t0", "text": word["text"],
        "sourceWordIds": [word["wordId"]],
        "startFrame": word["startFrame"],
        "endFrameExclusive": word["endFrameExclusive"],
        **plain_token_exact_fields(word),
    }
    if "speaker" in word:
        result["speaker"] = word["speaker"]
    return result


def apply_correction_ledger(words: object, ledger: object) -> list[dict]:
    """Compile occurrence-bound corrections into timed display tokens."""
    resolved = validate_resolved_words(words)
    authority = validate_correction_ledger(ledger)
    starts: dict[int, tuple[dict, list[int]]] = {}
    claimed: set[int] = set()
    for correction in authority["corrections"]:
        indices = _correction_positions(resolved, correction)
        if not indices:
            continue
        if claimed.intersection(indices):
            raise CaptionContractError("kept corrections overlap")
        claimed.update(indices)
        starts[indices[0]] = correction, indices
    result: list[dict] = []
    index = 0
    while index < len(resolved):
        match = starts.get(index)
        if match is None:
            result.append(_plain_token(resolved[index]))
            index += 1
            continue
        correction, indices = match
        result.extend(_corrected_tokens(
            [resolved[position] for position in indices], correction))
        index += len(indices)
    return result
