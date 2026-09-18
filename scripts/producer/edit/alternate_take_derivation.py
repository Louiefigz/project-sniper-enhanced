"""System-owned discovery of the one take bound to a rendered operation."""
from __future__ import annotations

from edit.alternate_take_candidates import (
    alternate_take_output_range,
    build_alternate_take_candidate_set,
)
from edit.alternate_take_scan_authority import released_retake_ids
from edit.alternate_take_types import (
    AlternateTakeAuthorityError,
    CandidateSetInput,
)
from edit.exact_timing import PositiveRational


def _expected_ranges(context: dict, operation: dict) -> tuple[dict, dict, dict]:
    extension = operation.get("sourceExtension")
    frames = operation.get("sourceVideoFrameRange")
    if not isinstance(extension, dict) or set(extension) != {
            "startSample", "endSampleExclusive"} \
            or not isinstance(frames, dict) or set(frames) != {
                "startFrame", "endFrameExclusive"}:
        raise AlternateTakeAuthorityError(
            "rendered alternate-take source ranges are absent")
    rate = PositiveRational.from_value(operation.get("sourceFrameRate"))
    samples = {
        **extension, "sampleRate": operation.get("sourceSampleRate")}
    source_frames = {
        "firstFrame": frames["startFrame"],
        "endFrameExclusive": frames["endFrameExclusive"],
        "fpsNumerator": rate.numerator,
        "fpsDenominator": rate.denominator,
    }
    return (
        samples, source_frames,
        alternate_take_output_range(context, operation))


def _later_candidate(candidate_set: dict) -> dict:
    rows = candidate_set.get("candidates")
    later = [
        row for row in rows if isinstance(row, dict)
        and row.get("role") == "later"
    ] if isinstance(rows, list) else []
    if len(later) != 1:
        raise AlternateTakeAuthorityError(
            "alternate-take candidate set has no unique later take")
    return later[0]


def _matches_operation(
    candidate_set: dict,
    context: dict,
    operation: dict,
) -> bool:
    candidate = _later_candidate(candidate_set)
    samples, frames, output = _expected_ranges(context, operation)
    media = context.get("sourceMedia")
    target = operation.get("target")
    if not isinstance(media, dict) or not isinstance(target, dict):
        raise AlternateTakeAuthorityError(
            "alternate-take source authority is absent")
    expected = (
        media.get("sourceId"), media.get("path"), media.get("sha256"),
        samples, frames, output,
    )
    observed = (
        candidate.get("sourceId"), candidate.get("sourceMediaPath"),
        candidate.get("sourceMediaSha256"),
        candidate.get("sourceSampleRange"),
        candidate.get("sourceFrameRange"),
        candidate.get("outputFrameRange"),
    )
    return observed == expected and target.get("sourceId") == expected[0]


def derive_alternate_take_candidate_set(
    context: dict,
    operation: dict,
    transcript_path: str,
) -> dict:
    """Require exactly one released detector event to match the operation."""
    matches = []
    for retake_id in released_retake_ids(transcript_path):
        candidate_set = build_alternate_take_candidate_set(
            CandidateSetInput(
                context, operation, transcript_path, retake_id))
        if _matches_operation(candidate_set, context, operation):
            matches.append(candidate_set)
    if len(matches) != 1:
        raise AlternateTakeAuthorityError(
            "prepared operation does not resolve to one released later take")
    return matches[0]


def validate_alternate_take_candidate_set(
    candidate_set: dict,
    context: dict,
    operation: dict,
) -> dict:
    """Re-enumerate all events and reject stale, invented, or ambiguous sets."""
    if not isinstance(candidate_set, dict) \
            or not isinstance(candidate_set.get("transcriptPath"), str):
        raise AlternateTakeAuthorityError(
            "alternate-take candidate provenance is absent")
    rebuilt = derive_alternate_take_candidate_set(
        context, operation, candidate_set["transcriptPath"])
    if rebuilt != candidate_set:
        raise AlternateTakeAuthorityError(
            "alternate-take candidate set is stale or substituted")
    return rebuilt
