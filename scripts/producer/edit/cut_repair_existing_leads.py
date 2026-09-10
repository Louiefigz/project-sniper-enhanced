"""Validate that a new repair preserves every existing plan J-cut."""
from __future__ import annotations

from fractions import Fraction

from edit.exact_timing import ProjectClock, SampleRange


class ExistingLeadError(ValueError):
    """Existing audio-lead placement cannot safely coexist with a repair."""


def _sample_range(value: object, label: str) -> SampleRange:
    if not isinstance(value, dict) \
            or set(value) != {"startSample", "endSampleExclusive"}:
        raise ExistingLeadError(f"{label} is malformed")
    try:
        return SampleRange(
            value["startSample"], value["endSampleExclusive"])
    except (TypeError, ValueError) as exc:
        raise ExistingLeadError(f"{label} is malformed") from exc


def _lead_samples(value: object, sample_rate: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExistingLeadError(
            "EXISTING_JCUT_SAMPLE_AUTHORITY_REQUIRED")
    try:
        samples = Fraction(str(value)) * sample_rate / 1000
    except (ValueError, ZeroDivisionError) as exc:
        raise ExistingLeadError(
            "EXISTING_JCUT_SAMPLE_AUTHORITY_REQUIRED") from exc
    if samples.denominator != 1 or samples <= 0:
        raise ExistingLeadError(
            "EXISTING_JCUT_SAMPLE_AUTHORITY_REQUIRED")
    return samples.numerator


def existing_audio_lead_ranges(
    plan: dict,
    context: dict,
    clock: ProjectClock,
) -> dict[str, SampleRange]:
    """Return exact output-sample ownership for every current plan J-cut."""
    track = plan.get("cutTrack")
    segments = context.get("segments")
    if not isinstance(track, list) or not isinstance(segments, list) \
            or len(track) != len(segments):
        raise ExistingLeadError("existing J-cut segment authority is malformed")
    result = {}
    for index, (row, segment) in enumerate(zip(track, segments, strict=True)):
        if not isinstance(row, dict) or not isinstance(segment, dict):
            raise ExistingLeadError(
                "existing J-cut segment authority is malformed")
        if row.get("audioLeadMs") is None:
            continue
        frames = segment.get("outputFrames")
        if not isinstance(frames, dict) \
                or type(frames.get("startFrame")) is not int:
            raise ExistingLeadError(
                "existing J-cut segment authority is malformed")
        if row.get("id") not in (None, segment.get("segmentId")) \
                or row.get("sourceId") != segment.get("sourceId"):
            raise ExistingLeadError(
                f"existing J-cut segment {index} changed identity")
        seam = clock.sample_at_frame(frames["startFrame"])
        lead = _lead_samples(row["audioLeadMs"], clock.sample_rate)
        if lead > seam:
            raise ExistingLeadError(
                "EXISTING_JCUT_SAMPLE_AUTHORITY_REQUIRED")
        ident = segment.get("segmentId")
        if not isinstance(ident, str) or not ident or ident in result:
            raise ExistingLeadError(
                "existing J-cut segment authority is malformed")
        result[ident] = SampleRange(seam - lead, seam)
    return result


def assert_new_repair_disjoint(
    plan: dict,
    context: dict,
    operation: dict,
    clock: ProjectClock,
) -> None:
    """Reject any new audio replacement that touches an existing lead."""
    existing = existing_audio_lead_ranges(plan, context, clock)
    raw = operation.get("replacedAudioSampleRanges")
    if not isinstance(raw, list) or not raw:
        raise ExistingLeadError("new repair audio replacement is absent")
    if operation.get("audioDirtySampleRanges") != raw:
        raise ExistingLeadError(
            "new repair audio dirty/replacement authority diverged")
    requested = [
        _sample_range(row, f"repair audio range {index}")
        for index, row in enumerate(raw)
    ]
    if any(left.start_sample < right.end_sample_exclusive
           and right.start_sample < left.end_sample_exclusive
           for left in existing.values() for right in requested):
        raise ExistingLeadError(
            "CUT_REPAIR_OVERLAPS_EXISTING_AUDIO_LEAD")
