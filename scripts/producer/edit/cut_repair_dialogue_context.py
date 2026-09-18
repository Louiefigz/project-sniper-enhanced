"""Controller-bound source-word authority for caption-aware cut repair."""
from __future__ import annotations

from captions.caption_words import stable_word_id
from edit.cut_repair_context_sources import (
    ContextMaterializationError,
    digest,
    require_hash,
    transcript,
)


def _used_source_ids(plan: dict) -> list[str]:
    track = plan.get("cutTrack")
    if not isinstance(track, list) or not track:
        raise ContextMaterializationError("caption plan has no cutTrack")
    result = {
        row.get("sourceId") for row in track if isinstance(row, dict)
    }
    if None in result or any(not isinstance(value, str) or not value
                             for value in result):
        raise ContextMaterializationError(
            "caption cutTrack source identity is malformed")
    return sorted(result)


def _source_words(source_id: str, timing: dict) -> list[dict]:
    rows = timing.get("words")
    if not isinstance(rows, list) or not rows:
        raise ContextMaterializationError(
            "CAPTION_DIALOGUE_SOURCE_TIMING_REQUIRED: "
            f"{source_id} has no source words")
    result = []
    for ordinal, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ContextMaterializationError(
                "CAPTION_DIALOGUE_SOURCE_TIMING_REQUIRED: malformed word")
        result.append({
            "sourceWordId": stable_word_id(source_id, ordinal),
            "text": row["word"],
            "sourceSampleRange": {
                "startSample": row["startSample"],
                "endSampleExclusive": row["endSampleExclusive"],
            },
            **({"speaker": row["speaker"]} if "speaker" in row else {}),
        })
    return result


def _dialogue_source(
    source_id: str,
    source: dict,
    manifest_dir: str,
) -> dict:
    audio = source.get("audio")
    sample_rate = audio.get("sampleRate") if isinstance(audio, dict) else None
    if type(sample_rate) is not int or sample_rate <= 0:
        raise ContextMaterializationError(
            "CAPTION_DIALOGUE_SOURCE_TIMING_REQUIRED: "
            f"{source_id} has no exact sample clock")
    try:
        timing = transcript(source, manifest_dir, source_id, sample_rate)
    except ContextMaterializationError as exc:
        raise ContextMaterializationError(
            "CAPTION_DIALOGUE_SOURCE_TIMING_REQUIRED: "
            f"{source_id}: {exc}") from exc
    return {
        "sourceId": source_id,
        "sourceSampleRate": sample_rate,
        "sourceMediaSha256": require_hash(
            source.get("contentHash"), f"{source_id} source media"),
        "transcriptTimingHash": timing["timingHash"],
        "words": _source_words(source_id, timing),
    }


def materialize_dialogue_context(
    plan: dict,
    sources: dict[str, dict],
    manifest_dir: str,
) -> dict | None:
    """Return all kept-source timing only for explicit caption authority."""
    if not isinstance(plan.get("captionsTrack"), dict):
        return None
    rows = []
    for source_id in _used_source_ids(plan):
        source = sources.get(source_id)
        if not isinstance(source, dict):
            raise ContextMaterializationError(
                "CAPTION_DIALOGUE_SOURCE_TIMING_REQUIRED: "
                f"{source_id} is absent from the manifest")
        rows.append(_dialogue_source(source_id, source, manifest_dir))
    snapshot_rows = [{
        "sourceId": row["sourceId"],
        "sourceMediaSha256": row["sourceMediaSha256"],
        "transcriptTimingHash": row["transcriptTimingHash"],
    } for row in rows]
    return {
        "sourceSnapshotSetHash": digest(snapshot_rows),
        "dialogueSources": rows,
    }
