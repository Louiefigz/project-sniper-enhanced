"""Resolve one exact repair target and bounded output-clock QC window."""
from __future__ import annotations

from edit.cut_repair_context_sources import require_hash
from edit.cut_repair_candidate_qc_types import (
    CandidateQcContractError,
    DirtyWindow,
)
from edit.target_resolver import build_word_refs


def target_phrase(
    context: dict,
    operation: dict,
) -> tuple[str, tuple[str, ...]]:
    """Rebind stable target IDs to one contiguous source transcript phrase."""
    transcript = context.get("transcript")
    target = operation.get("target")
    if not isinstance(transcript, dict) or not isinstance(target, dict) \
            or not isinstance(transcript.get("words"), list):
        raise CandidateQcContractError("cut repair target authority is malformed")
    words = build_word_refs(
        str(transcript.get("sourceId")), transcript["words"],
        require_hash(transcript.get("timingHash"), "transcript timing hash"))
    requested = target.get("wordIds")
    if not isinstance(requested, list) or not requested:
        raise CandidateQcContractError("cut repair target has no word IDs")
    indexes = [index for index, word in enumerate(words)
               if word.word_id in requested]
    selected = [words[index] for index in indexes]
    _assert_target_bindings(transcript, target, selected, indexes)
    return " ".join(word.text for word in selected), tuple(requested)


def _assert_target_bindings(
    transcript: dict,
    target: dict,
    selected: list,
    indexes: list[int],
) -> None:
    requested = target["wordIds"]
    actual = [word.word_id for word in selected]
    contiguous = indexes == list(range(min(indexes), max(indexes) + 1)) \
        if indexes else False
    sample_range = target.get("sourceSampleRange")
    bounds = (
        selected[0].samples.start_sample,
        selected[-1].samples.end_sample_exclusive,
    ) if selected else None
    expected_bounds = (
        sample_range.get("startSample"), sample_range.get("endSampleExclusive")
    ) if isinstance(sample_range, dict) else None
    if actual != requested or not contiguous or bounds != expected_bounds \
            or target.get("transcriptTimingHash") != transcript.get("timingHash"):
        raise CandidateQcContractError(
            "cut repair target word authority is stale or non-contiguous")


def _positive_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CandidateQcContractError(f"{label} is not a positive integer")
    return value


def _rate(clock: dict) -> tuple[int, int, int]:
    rate = clock.get("fps")
    if not isinstance(rate, dict):
        raise CandidateQcContractError("cut repair project rate is absent")
    try:
        numerator_value = int(rate.get("numerator"))
        denominator_value = int(rate.get("denominator"))
    except (TypeError, ValueError) as exc:
        raise CandidateQcContractError(
            "cut repair project rate is malformed") from exc
    return (
        _positive_integer(numerator_value, "fps numerator"),
        _positive_integer(denominator_value, "fps denominator"),
        _positive_integer(clock.get("sampleRate"), "project sample rate"),
    )


def dirty_window(context: dict, operation: dict) -> DirtyWindow:
    """Bound QC extraction to dirty frames plus one second of context."""
    rows = operation.get("audioDirtyWindows")
    clock = context.get("clock")
    if not isinstance(rows, list) or not rows or not isinstance(clock, dict):
        raise CandidateQcContractError("cut repair dirty window is absent")
    starts = [row.get("startFrame") for row in rows if isinstance(row, dict)]
    ends = [row.get("endFrameExclusive") for row in rows
            if isinstance(row, dict)]
    if len(starts) != len(rows) or any(type(value) is not int for value in
                                      starts + ends):
        raise CandidateQcContractError("cut repair dirty frame range is malformed")
    first, end = min(starts), max(ends)
    if first < 0 or end <= first:
        raise CandidateQcContractError("cut repair dirty frame range is empty")
    numerator, denominator, sample_rate = _rate(clock)
    total_frames = _positive_integer(
        context.get("totalFrames"), "program frame count")
    start_sample = first * denominator * sample_rate // numerator
    end_sample = end * denominator * sample_rate // numerator
    terminal_sample = (
        total_frames * denominator * sample_rate // numerator)
    bounded_start = max(0, start_sample - sample_rate)
    bounded_end = min(terminal_sample, end_sample + sample_rate)
    if bounded_end - bounded_start > 30 * sample_rate:
        raise CandidateQcContractError("DIRTY_WINDOW_EXCEEDS_QC_BOUND")
    return DirtyWindow(
        first_frame=first,
        end_frame_exclusive=end,
        dirty_start_sample=start_sample,
        dirty_end_sample_exclusive=end_sample,
        start_sample=bounded_start,
        end_sample_exclusive=bounded_end,
        sample_rate=sample_rate,
        fps_numerator=numerator,
        fps_denominator=denominator,
    )
