"""Closed plan-carried dialogue/caption authority for one cut repair."""
from __future__ import annotations

from dataclasses import dataclass

from captions.caption_repair_revalidation import (
    CaptionCompilationPair,
    caption_compilation_hash,
    revalidate_caption_compilations,
    validate_caption_revalidation,
)
from captions.caption_words import CaptionFrameRate
from captions.cut_repair_dialogue_words import source_words_for_dialogue_map
from captions.dialogue_caption_compile import (
    compile_plan_dialogue_caption_track,
)
from captions.dialogue_caption_timing import resolve_dialogue_caption_words
from contracts.schema_validator import validate_document
from edit.cut_repair_dialogue_track import (
    DialogueAuthorityPair,
    build_cut_repair_dialogue_authority,
)
from edit.cut_repair_existing_leads import existing_audio_lead_ranges
from edit.dialogue_authority import (
    dialogue_map_hash,
    dialogue_track_hash,
    validate_dialogue_authority,
)
from edit.exact_timing import ProjectClock
from edit.picture_lock_common import PictureLockError, content_hash

PLAN_FIELD = "dialogueCaptionAuthority"
EXISTING_TRACK_FIELD = "_existingDialogueTrack"
EXISTING_MAP_FIELD = "_existingDialogueMap"
_CORE_KEYS = {
    "schemaVersion", "kind", "operation", "operationHash",
    "sourceSnapshotSetHash",
    "parentDialogueTrack", "parentDialogueTrackHash",
    "parentDialogueMap", "parentDialogueMapHash", "parentSourceWords",
    "childDialogueTrack", "childDialogueTrackHash",
    "childDialogueMap", "childDialogueMapHash", "childSourceWords",
    "captionRevalidation",
}


@dataclass(frozen=True)
class CutRepairCaptionAuthorityInput:
    """All controller-owned inputs needed for one plan-carried proof."""

    parent_plan: dict
    child_plan: dict
    context: dict
    operation: dict
    child_timeline_map_hash: str
    clock: ProjectClock


def _seed_context(value: CutRepairCaptionAuthorityInput) -> dict:
    leads = existing_audio_lead_ranges(
        value.parent_plan, value.context, value.clock)
    raw = value.parent_plan.get(PLAN_FIELD)
    if not leads and raw is None:
        return value.context
    if raw is None:
        raise PictureLockError(
            "CAPTION_DIALOGUE_EXISTING_JCUT_AUTHORITY_REQUIRED")
    previous = parse_cut_repair_caption_authority(raw)
    handles = [
        row for row in previous["childDialogueTrack"]["segments"]
        if row["role"] != "primary"
    ]
    if any(row["role"] != "j-cut-handle" for row in handles):
        raise PictureLockError(
            "existing caption dialogue handle kind is unsupported")
    by_segment = {row["cutSegmentId"]: row for row in handles}
    if len(by_segment) != len(handles) or set(by_segment) != set(leads):
        raise PictureLockError(
            "existing caption dialogue handles do not match the live plan")
    for ident, sample_range in leads.items():
        if by_segment[ident]["outputSampleRange"] != sample_range.to_dict():
            raise PictureLockError(
                "existing caption dialogue handle placement changed")
    return {
        **value.context,
        EXISTING_TRACK_FIELD: previous["childDialogueTrack"],
        EXISTING_MAP_FIELD: previous["childDialogueMap"],
    }


def _compilations(
    value: CutRepairCaptionAuthorityInput,
    authority: DialogueAuthorityPair,
    parent_words: list[dict],
    child_words: list[dict],
) -> tuple[dict, dict, dict]:
    rate = CaptionFrameRate(
        value.clock.fps.numerator, value.clock.fps.denominator)
    before = compile_plan_dialogue_caption_track(
        value.parent_plan, rate, parent_words, authority.parent_map)
    after = compile_plan_dialogue_caption_track(
        value.child_plan, rate, child_words, authority.child_map)
    receipt = revalidate_caption_compilations(CaptionCompilationPair(
        before, after,
        authority.parent_track["totalOutputFrames"],
        authority.child_track["totalOutputFrames"],
        authority.parent_track["projectFps"]
        == authority.child_track["projectFps"],
    ), value.operation)
    return before, after, receipt


def _core(
    value: CutRepairCaptionAuthorityInput,
    authority: DialogueAuthorityPair,
    words: tuple[list[dict], list[dict]],
    receipt: dict,
) -> dict:
    parent_words, child_words = words
    return {
        "schemaVersion": 1,
        "kind": "cut-repair-dialogue-caption-authority",
        "operation": value.operation,
        "operationHash": content_hash(value.operation),
        "sourceSnapshotSetHash":
            authority.child_track["sourceSnapshotSetHash"],
        "parentDialogueTrack": authority.parent_track,
        "parentDialogueTrackHash": authority.parent_track_hash,
        "parentDialogueMap": authority.parent_map,
        "parentDialogueMapHash": authority.parent_map_hash,
        "parentSourceWords": parent_words,
        "childDialogueTrack": authority.child_track,
        "childDialogueTrackHash": authority.child_track_hash,
        "childDialogueMap": authority.child_map,
        "childDialogueMapHash": authority.child_map_hash,
        "childSourceWords": child_words,
        "captionRevalidation": receipt,
    }


def build_cut_repair_caption_authority(
    value: CutRepairCaptionAuthorityInput,
) -> dict:
    """Compile both caption generations and attach their complete proof."""
    authority = build_cut_repair_dialogue_authority(
        _seed_context(value), value.operation, value.child_timeline_map_hash,
        value.clock)
    return build_caption_authority_from_dialogue(value, authority)


def build_caption_authority_from_dialogue(
    value: CutRepairCaptionAuthorityInput,
    authority: DialogueAuthorityPair,
) -> dict:
    """Seal caption recompilation around an already-proved dialogue pair."""
    parent_words = source_words_for_dialogue_map(
        value.context, authority.parent_map, authority.child_map)
    child_words = source_words_for_dialogue_map(
        value.context, authority.child_map, authority.child_map)
    _, _, receipt = _compilations(
        value, authority, parent_words, child_words)
    core = _core(value, authority, (parent_words, child_words), receipt)
    return parse_cut_repair_caption_authority({
        **core, "authorityHash": content_hash(core)})


def _bound_dialogue(row: dict, prefix: str) -> tuple[dict, dict]:
    track = row[f"{prefix}DialogueTrack"]
    dialogue_map = row[f"{prefix}DialogueMap"]
    parsed_track, parsed_map = validate_dialogue_authority(
        track, dialogue_map)
    if dialogue_track_hash(parsed_track) != row[f"{prefix}DialogueTrackHash"] \
            or dialogue_map_hash(parsed_map) \
            != row[f"{prefix}DialogueMapHash"]:
        raise PictureLockError(
            f"{prefix} dialogue authority hash is stale")
    return parsed_track, parsed_map


def parse_cut_repair_caption_authority(value: object) -> dict:
    """Reopen one exact plan-carried authority and prove every binding."""
    if not isinstance(value, dict) \
            or set(value) != _CORE_KEYS | {"authorityHash"}:
        raise PictureLockError(
            "cut repair dialogue caption authority is not closed")
    validate_document(
        "cut-repair-dialogue-caption-authority-v1.schema.json", value)
    core = {key: item for key, item in value.items()
            if key != "authorityHash"}
    operation = core.get("operation")
    if core.get("schemaVersion") != 1 \
            or core.get("kind") \
            != "cut-repair-dialogue-caption-authority" \
            or not isinstance(operation, dict) \
            or core.get("operationHash") != content_hash(operation) \
            or value.get("authorityHash") != content_hash(core):
        raise PictureLockError(
            "cut repair dialogue caption authority is stale")
    parent_track, parent_map = _bound_dialogue(core, "parent")
    child_track, child_map = _bound_dialogue(core, "child")
    snapshot = core.get("sourceSnapshotSetHash")
    if parent_track["sourceSnapshotSetHash"] != snapshot \
            or child_track["sourceSnapshotSetHash"] != snapshot:
        raise PictureLockError("dialogue source snapshots changed through repair")
    for prefix, dialogue_map in (
            ("parent", parent_map), ("child", child_map)):
        words = core.get(f"{prefix}SourceWords")
        resolve_dialogue_caption_words(words, dialogue_map)
    validate_caption_revalidation(
        core.get("captionRevalidation"), operation)
    return dict(value)


def compile_plan_cut_repair_captions(
    plan: dict,
    rate: CaptionFrameRate,
) -> dict | None:
    """Compile the plan's child dialogue authority, if the plan carries one."""
    raw = plan.get(PLAN_FIELD)
    if raw is None:
        return None
    authority = parse_cut_repair_caption_authority(raw)
    compilation = compile_plan_dialogue_caption_track(
        plan, rate, authority["childSourceWords"],
        authority["childDialogueMap"])
    receipt = authority["captionRevalidation"]
    if receipt.get("status") != "revalidated" \
            or receipt.get("afterCompilationHash") \
            != caption_compilation_hash(compilation):
        raise PictureLockError(
            "rendered caption compilation is not the approved repair child")
    return compilation
