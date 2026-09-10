"""Remove repair candidates that would overwrite a governed prior J-cut."""
from __future__ import annotations

from edit.cut_repair_selection import select_restore_candidate
from edit.exact_timing import SampleRange


class ExistingLeadFilterError(ValueError):
    """Existing lead context or candidate audio ownership is malformed."""


def _range(value: object, label: str) -> SampleRange:
    if not isinstance(value, dict) \
            or set(value) != {"startSample", "endSampleExclusive"}:
        raise ExistingLeadFilterError(f"{label} is malformed")
    try:
        return SampleRange(
            value["startSample"], value["endSampleExclusive"])
    except (TypeError, ValueError) as exc:
        raise ExistingLeadFilterError(f"{label} is malformed") from exc


def _existing(value: object) -> dict[str, SampleRange]:
    if value is None:
        return {}
    if not isinstance(value, list) or not value:
        raise ExistingLeadFilterError(
            "existing audio lead ranges must be non-empty")
    result = {}
    for index, item in enumerate(value):
        if not isinstance(item, dict) \
                or set(item) != {"segmentId", "outputSampleRange"} \
                or not isinstance(item["segmentId"], str) \
                or not item["segmentId"] or item["segmentId"] in result:
            raise ExistingLeadFilterError(
                f"existing audio lead range {index} is malformed")
        result[item["segmentId"]] = _range(
            item["outputSampleRange"],
            f"existing audio lead range {index}")
    return result


def _overlap(left: SampleRange, right: SampleRange) -> bool:
    return (
        left.start_sample < right.end_sample_exclusive
        and right.start_sample < left.end_sample_exclusive)


def _blocked(operation: object,
             existing: dict[str, SampleRange]) -> list[str]:
    if not isinstance(operation, dict):
        raise ExistingLeadFilterError("repair candidate operation is malformed")
    if operation.get("method") != "audio-lj-overlap":
        return []
    rows = operation.get("replacedAudioSampleRanges")
    if not isinstance(rows, list) or not rows:
        raise ExistingLeadFilterError(
            "audio repair replacement ranges are absent")
    requested = [
        _range(row, f"repair replacement range {index}")
        for index, row in enumerate(rows)
    ]
    return sorted(
        ident for ident, current in existing.items()
        if any(_overlap(current, target) for target in requested))


def filter_existing_lead_candidates(
    result: dict,
    existing_value: object,
) -> dict:
    """Keep disjoint candidates and explain when prior audio owns the range."""
    existing = _existing(existing_value)
    if not existing:
        return result
    candidates = result.get("candidates")
    if not isinstance(candidates, list):
        raise ExistingLeadFilterError("repair candidates must be an array")
    kept, blocked = [], set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ExistingLeadFilterError(
                "repair candidate envelope is malformed")
        conflicts = _blocked(candidate.get("operation"), existing)
        if conflicts:
            blocked.update(conflicts)
        else:
            kept.append(candidate)
    if len(kept) == len(candidates):
        return result
    if kept:
        return {
            **result, "candidates": kept,
            "recommendedCandidate": select_restore_candidate(kept),
        }
    return {
        **result,
        "status": "impossible-without-ripple",
        "candidates": [],
        "recommendedCandidate": None,
        "rippleImpact": {
            "reason": "existing-audio-lead-overlap",
            "preservedExistingAudioLeadSegmentIds": sorted(blocked),
        },
    }
