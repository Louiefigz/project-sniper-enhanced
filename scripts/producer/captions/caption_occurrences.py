"""Occurrence-safe source-word mapping for reused timeline slices."""
from __future__ import annotations

import hashlib
from decimal import Decimal, ROUND_HALF_UP

from captions.caption_contract import CaptionContractError, WORD_ID_RE
from compile_timeline import Segment, TimelineMap

_AUDIBLE_WORD_SECONDS = 0.04


def occurrence_word_id(source_word_id: str, occurrence: int) -> str:
    """Mint one stable plan-local ID for a kept source-word occurrence."""
    if not isinstance(source_word_id, str) \
            or WORD_ID_RE.fullmatch(source_word_id) is None:
        raise CaptionContractError("sourceWordId must be a stable word ID")
    if type(occurrence) is not int or occurrence <= 0:
        raise CaptionContractError("occurrence must be a positive integer")
    payload = (
        f"sniper-dialogue-caption-occurrence-v1\0"
        f"{source_word_id}\0{occurrence}")
    return f"w-{hashlib.sha256(payload.encode()).hexdigest()[:16]}"


def _overlap(word: dict, segment: Segment) -> tuple[float, float] | None:
    start = max(float(word["start"]), segment.src_start)
    end = min(float(word["end"]), segment.src_end)
    return (start, end) if start < end else None


def _candidates(
    word: dict,
    source_id: str,
    timeline: TimelineMap,
) -> list[Segment]:
    rows = [
        row for row in timeline.segments
        if row.source_id == source_id and _overlap(word, row) is not None
    ]
    start = float(word["start"])
    onset = [
        row for row in rows if row.src_start <= start < row.src_end
    ]
    if onset:
        return onset
    length = float(word["end"]) - start
    return [
        row for row in rows
        if (_overlap(word, row)[1] - _overlap(word, row)[0]) * 2 >= length
    ]


def _sample(seconds: float, sample_rate: int) -> int:
    return int((Decimal(str(seconds)) * sample_rate).quantize(
        Decimal(1), rounding=ROUND_HALF_UP))


def _mapped(
    word: dict,
    segment: Segment,
) -> tuple[dict, float, float] | None:
    overlap = _overlap(word, segment)
    if overlap is None or overlap[1] - overlap[0] < _AUDIBLE_WORD_SECONDS:
        return None
    output_start = segment.src_to_out(overlap[0])
    output_end = segment.src_to_out(overlap[1])
    return ({
        **word,
        "start": round(output_start, 4),
        "end": round(output_end, 4),
    }, output_start, output_end)


def _bound_occurrence(
    value: tuple[dict, float, float],
    segment: Segment,
    occurrence: int,
    sample_rate: int,
) -> dict:
    row, output_start, output_end = value
    source_word_id = row["wordId"]
    return {
        **row,
        "wordId": occurrence_word_id(source_word_id, occurrence),
        "sourceWordId": source_word_id,
        "occurrence": occurrence,
        "cutSegmentIndex": segment.index,
        "startSample": _sample(output_start, sample_rate),
        "endSampleExclusive": _sample(output_end, sample_rate),
    }


def remap_caption_occurrences(
    words: list[dict],
    source_id: str,
    timeline: TimelineMap,
    sample_rate: int,
) -> list[dict]:
    """Map every reused output occurrence while preserving unique legacy IDs."""
    if type(sample_rate) is not int or sample_rate <= 0:
        raise CaptionContractError("caption occurrence sample rate is invalid")
    result = []
    for word in words:
        candidates = _candidates(word, source_id, timeline)
        mapped = [
            (value, segment)
            for segment in candidates
            if (value := _mapped(word, segment)) is not None
        ]
        if len(mapped) == 1:
            result.append(mapped[0][0][0])
            continue
        result.extend(
            _bound_occurrence(value, segment, occurrence, sample_rate)
            for occurrence, (value, segment) in enumerate(mapped, 1)
        )
    return sorted(result, key=lambda row: (
        row["start"], row["end"], row["wordId"]))
