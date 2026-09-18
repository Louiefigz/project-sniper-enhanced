"""Conditional exact-sample fields for caption content and cue payloads."""
from __future__ import annotations

from captions.caption_context import CaptionCompileContext, sample_at_frame
from captions.caption_contract import CaptionContractError


def content_token(row: dict) -> dict:
    """Return fingerprinted display content plus optional source occurrence."""
    result = {
        "text": row["text"],
        "sourceWordIds": row["sourceWordIds"],
    }
    if "correctionId" in row:
        result["correctionId"] = row["correctionId"]
    if "speaker" in row:
        result["speaker"] = row["speaker"]
    if "sourceWordOccurrences" in row:
        result["sourceWordOccurrences"] = row["sourceWordOccurrences"]
    return result


def _sample_bounds(row: dict, context: CaptionCompileContext) -> tuple[int, int]:
    present = {
        key for key in ("startSample", "endSampleExclusive") if key in row}
    if not present:
        return (
            sample_at_frame(row["startFrame"], context),
            sample_at_frame(row["endFrameExclusive"], context),
        )
    if present != {"startSample", "endSampleExclusive"}:
        raise CaptionContractError("caption token has incomplete exact samples")
    start, end = row["startSample"], row["endSampleExclusive"]
    if type(start) is not int or type(end) is not int \
            or start < 0 or end <= start:
        raise CaptionContractError("caption token has invalid exact samples")
    return start, end


def timing_token(row: dict, context: CaptionCompileContext) -> dict:
    """Return fingerprinted frame/sample timing for one display token."""
    start, end = _sample_bounds(row, context)
    result = {
        "tokenId": row["tokenId"],
        "sourceWordIds": row["sourceWordIds"],
        "startFrame": row["startFrame"],
        "endFrameExclusive": row["endFrameExclusive"],
        "startSample": start,
        "endSampleExclusive": end,
    }
    if "sourceWordOccurrences" in row:
        result["sourceWordOccurrences"] = row["sourceWordOccurrences"]
    return result
