"""Explicit DialogueMapV1-aware CaptionTrackV1 compilation entry point."""
from __future__ import annotations

from dataclasses import dataclass, replace

from captions.caption_compile import compile_caption_track
from captions.caption_context import (
    CaptionCompileContext,
    require_sha256,
    validate_compile_context,
)
from captions.caption_contract import CaptionContractError
from captions.caption_fingerprints import canonical_digest
from captions.caption_outputs import compile_chapters
from captions.caption_plan_pipeline import plan_dialogue_compile_context
from captions.caption_words import CaptionFrameRate
from captions.dialogue_caption_timing import resolve_dialogue_caption_words


@dataclass(frozen=True)
class DialogueCaptionCompileContext:
    """Legacy-safe opt-in inputs for exact dialogue caption compilation."""

    caption: CaptionCompileContext
    source_words: object
    dialogue_map: object
    dialogue_map_hash: str


def _validate_context(value: object) -> DialogueCaptionCompileContext:
    if not isinstance(value, DialogueCaptionCompileContext):
        raise CaptionContractError(
            "dialogue caption compile context is malformed")
    caption = validate_compile_context(value.caption)
    if caption.words not in (None, []):
        raise CaptionContractError(
            "dialogue caption entry point owns resolved word timing")
    if caption.timeline_slices or caption.segment_versions:
        raise CaptionContractError(
            "dialogue caption entry point owns map slices and segment versions")
    require_sha256(value.dialogue_map_hash, "dialogue caption map")
    return value


def _clock_checks(context: DialogueCaptionCompileContext,
                  timing: dict) -> None:
    caption = context.caption
    if caption.rate.to_dict() != timing["fps"]:
        raise CaptionContractError(
            "caption frame rate does not match DialogueMapV1")
    if caption.sample_rate != timing["sampleRate"]:
        raise CaptionContractError(
            "caption sample rate does not match DialogueMapV1")
    if caption.timeline_map_hash != timing["pictureTimelineMapHash"]:
        raise CaptionContractError(
            "caption timeline does not match DialogueMapV1 picture authority")
    if context.dialogue_map_hash != timing["dialogueMapHash"]:
        raise CaptionContractError(
            "caption context binds stale DialogueMapV1 content")


def _word_slice(word: dict) -> str:
    return canonical_digest("sniper-dialogue-caption-slice-v1", {
        "sourceWordId": word["sourceWordId"],
        "occurrence": word["occurrence"],
        "sourceSampleRange": word["sourceSampleRange"],
        "outputSampleRange": {
            "startSample": word["startSample"],
            "endSampleExclusive": word["endSampleExclusive"],
        },
        "ownerCutSegmentId": word["ownerCutSegmentId"],
        "ownerElementVersion": word["ownerElementVersion"],
        "dialogueSegmentIds": word["dialogueSegmentIds"],
        "dialogueRoles": word["dialogueRoles"],
        "coveringCutSegmentIds": word["coveringCutSegmentIds"],
    })


def _caption_context(context: DialogueCaptionCompileContext,
                     timing: dict) -> CaptionCompileContext:
    words = timing["words"]
    slices = {
        word["wordId"]: _word_slice(word)
        for word in words
    }
    versions = {
        word["wordId"]: {
            "cutSegmentId": word["ownerCutSegmentId"],
            "elementVersion": word["ownerElementVersion"],
        }
        for word in words
    }
    return replace(
        context.caption,
        words=words,
        timeline_slices=slices,
        segment_versions=versions,
    )


def _binding(word: dict) -> dict:
    keys = (
        "wordId", "sourceWordId", "occurrence", "sourceId",
        "sourceSampleRange", "ownerCutSegmentId", "ownerElementVersion",
        "dialogueSegmentIds", "dialogueRoles", "coveringCutSegmentIds",
        "startSample", "endSampleExclusive", "startFrame",
        "endFrameExclusive", "transcriptTimingHash",
    )
    return {key: word[key] for key in keys}


def compile_dialogue_caption_track(
    value: DialogueCaptionCompileContext,
) -> dict:
    """Compile exact dialogue timing without changing the legacy entry point."""
    context = _validate_context(value)
    timing = resolve_dialogue_caption_words(
        context.source_words, context.dialogue_map)
    _clock_checks(context, timing)
    return _compile_timing(context, timing)


def _compile_timing(
    context: DialogueCaptionCompileContext,
    timing: dict,
) -> dict:
    compilation = compile_caption_track(_caption_context(context, timing))
    bindings = [_binding(word) for word in timing["words"]]
    return {
        **compilation,
        "dialogueTimingAuthority": {
            "kind": "dialogue-map",
            "dialogueMapHash": timing["dialogueMapHash"],
            "dialogueTrackHash": timing["dialogueTrackHash"],
            "pictureTimelineMapHash": timing["pictureTimelineMapHash"],
        },
        "wordOccurrenceBindings": bindings,
        "dialogueWordTimingHash": canonical_digest(
            "sniper-dialogue-caption-word-timing-v1", bindings),
    }


def _ambiguous_source_ids(source_words: object) -> set[str]:
    if not isinstance(source_words, list):
        raise CaptionContractError("dialogue source words must be an array")
    counts: dict[str, int] = {}
    for row in source_words:
        if not isinstance(row, dict) \
                or not isinstance(row.get("sourceWordId"), str):
            raise CaptionContractError("dialogue source word identity is absent")
        ident = row["sourceWordId"]
        counts[ident] = counts.get(ident, 0) + 1
    return {ident for ident, count in counts.items() if count > 1}


def _plan_word_references(plan: dict) -> set[str]:
    track = plan.get("captionsTrack")
    groups = track.get("groups") if isinstance(track, dict) else []
    references = {
        ident for group in (groups or [])
        for ident in ((group.get("anchor") or {}).get("wordIds") or [])
        if isinstance(ident, str)
    }
    ledger = plan.get("captionCorrectionLedger")
    corrections = ledger.get("corrections") if isinstance(ledger, dict) else []
    references.update(
        ident for row in (corrections or [])
        for ident in (row.get("sourceWordIds") or [])
        if isinstance(ident, str))
    references.update(
        row.get("wordId") for row in (plan.get("captionChapters") or [])
        if isinstance(row, dict) and isinstance(row.get("wordId"), str))
    return references


def compile_plan_dialogue_caption_track(
    plan: dict,
    rate: CaptionFrameRate,
    source_words: object,
    dialogue_map: object,
) -> dict:
    """Compile a plan through exact dialogue authority, including chapters."""
    ambiguous = _ambiguous_source_ids(source_words)
    if ambiguous & _plan_word_references(plan):
        raise CaptionContractError(
            "CAPTION_OCCURRENCE_BINDING_REQUIRED: repeated source words "
            "must use occurrence word IDs")
    timing = resolve_dialogue_caption_words(source_words, dialogue_map)
    caption = plan_dialogue_compile_context(
        plan, rate, timing["pictureTimelineMapHash"], timing["sampleRate"])
    context = DialogueCaptionCompileContext(
        caption, source_words, dialogue_map, timing["dialogueMapHash"])
    _clock_checks(context, timing)
    compilation = _compile_timing(context, timing)
    if "captionChapters" in plan:
        compilation["chapterProjection"] = compile_chapters(
            plan["captionChapters"], timing["words"], rate)
    return compilation
