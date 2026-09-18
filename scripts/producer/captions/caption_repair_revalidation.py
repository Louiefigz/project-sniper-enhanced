#!/usr/bin/env python3
"""Recompile caption/chapter authority against a proved non-ripple repair."""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from captions.caption_fingerprints import (
    canonical_digest,
    diff_caption_compilations,
)
from captions.caption_plan_pipeline import (
    PlanCaptionContext,
    compile_plan_caption_track,
)
from contracts.schema_validator import validate_document
from edit.picture_lock_common import PictureLockError, content_hash


@dataclass(frozen=True)
class CaptionRepairContexts:
    """Actual parent/child compiler inputs; callers cannot assert hash parity."""

    before: PlanCaptionContext
    after: PlanCaptionContext


@dataclass(frozen=True)
class CaptionCompilationPair:
    """Actual before/after compiler products plus their exact program clocks."""

    before: dict | None
    after: dict | None
    before_frames: int
    after_frames: int
    same_rate: bool


def _windows(operation: dict) -> list[list[int]]:
    if operation.get("schemaVersion") != 1 \
            or operation.get("operation") != "cut.restoreSpeech":
        raise PictureLockError("caption revalidation requires cut.restoreSpeech")
    totals = (
        operation.get("totalOutputFramesBefore"),
        operation.get("totalOutputFramesAfter"),
    )
    if any(isinstance(value, bool) or not isinstance(value, int)
           or value < 1 for value in totals):
        raise PictureLockError("caption repair frame totals are malformed")
    if totals[0] != totals[1]:
        raise PictureLockError("caption revalidation requires non-ripple repair")
    rows = [
        row for key in ("pictureDirtyWindows", "audioDirtyWindows")
        for row in (operation.get(key) or [])
    ]
    parsed = []
    for row in rows:
        start = row.get("startFrame") if isinstance(row, dict) else None
        end = row.get("endFrameExclusive") if isinstance(row, dict) else None
        if not isinstance(start, int) or not isinstance(end, int) \
                or start < 0 or end <= start:
            raise PictureLockError("caption repair dirty window is malformed")
        parsed.append([start, end])
    if not parsed:
        raise PictureLockError("caption repair has no dirty windows")
    merged: list[list[int]] = []
    for start, end in sorted(parsed):
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return merged


def _context_frames(context: PlanCaptionContext) -> int:
    frames = Fraction(str(context.timeline.output_duration)) \
        * context.rate.fraction
    whole, remainder = divmod(frames.numerator, frames.denominator)
    return whole + int(remainder * 2 >= frames.denominator)


def _validate_context_clocks(
    contexts: CaptionRepairContexts,
    operation: dict,
) -> None:
    expected = (
        operation["totalOutputFramesBefore"],
        operation["totalOutputFramesAfter"],
    )
    actual = (
        _context_frames(contexts.before),
        _context_frames(contexts.after),
    )
    if actual != expected:
        raise PictureLockError(
            "caption compiler contexts do not match repair frame totals")
    if contexts.before.rate != contexts.after.rate:
        raise PictureLockError(
            "caption compiler frame rate changed through cut repair")


def _overlaps(row: dict, windows: list[list[int]]) -> bool:
    return any(
        row["startFrame"] < end
        and row["endFrameExclusive"] > start
        for start, end in windows)


def _cue_rows(compilation: dict) -> dict[str, dict]:
    rows = compilation.get("cues")
    if not isinstance(rows, list):
        raise PictureLockError("caption compilation has no cue authority")
    result = {row.get("cueId"): row for row in rows}
    if None in result or len(result) != len(rows):
        raise PictureLockError("caption compilation cue ids are invalid")
    return result


def _cue_revalidation(before: dict, after: dict,
                      windows: list[list[int]]) -> dict:
    old, new = _cue_rows(before), _cue_rows(after)
    invalidation = diff_caption_compilations(before, after)
    changed = invalidation["captionCueNodes"]
    for cue_id in changed:
        candidates = [
            row for row in (old.get(cue_id), new.get(cue_id))
            if isinstance(row, dict)
        ]
        if not any(_overlaps(row, windows) for row in candidates):
            raise PictureLockError(
                f"non-ripple repair changed caption cue {cue_id} "
                "outside its dirty windows")
    return {
        "changedCueIds": changed,
        "unchangedCueIds": sorted((set(old) & set(new)) - set(changed)),
        "dirtyFrameWindows": invalidation["dirtyFrameWindows"],
        "contentNodesRebuilt": invalidation["captionContentNodes"],
        "contentNodesReused": invalidation["reusedContentNodes"],
    }


def _chapter_core(row: dict) -> tuple[object, ...]:
    return (
        row.get("chapterId"), row.get("title"), row.get("sourceWordId"))


def _chapter_revalidation(before: dict, after: dict,
                          windows: list[list[int]]) -> dict:
    left = before.get("chapterProjection")
    right = after.get("chapterProjection")
    if (left is None) != (right is None):
        raise PictureLockError("caption chapters appeared or disappeared")
    if left is None:
        return {"status": "not-present", "changedChapterIds": []}
    old = {row["chapterId"]: row for row in left.get("chapters") or []}
    new = {row["chapterId"]: row for row in right.get("chapters") or []}
    if set(old) != set(new) or any(
            _chapter_core(old[key]) != _chapter_core(new[key])
            for key in old):
        raise PictureLockError("caption chapter semantic authority changed")
    changed = []
    for key in sorted(old):
        if old[key] == new[key]:
            continue
        frames = (old[key]["startFrame"], new[key]["startFrame"])
        if not any(start <= frame < end
                   for frame in frames for start, end in windows):
            raise PictureLockError(
                f"non-ripple repair moved chapter {key} outside dirty windows")
        changed.append(key)
    return {
        "status": "revalidated", "changedChapterIds": changed,
        "beforeHash": left["digest"], "afterHash": right["digest"],
    }


def caption_compilation_hash(value: dict) -> str:
    """Return the domain-separated identity of one caption compilation."""
    return canonical_digest("sniper-caption-compilation-v1", value)


def _revalidation_payload(
    before: dict | None, after: dict | None, base: dict,
    windows: list[list[int]],
) -> dict:
    if before is None and after is None:
        return {**base, "status": "not-present"}
    if before is None or after is None:
        raise PictureLockError(
            "caption authority appeared or disappeared through cut repair")
    stable = ("captionTrackHash", "correctionLedgerHash", "compilerHash",
              "fps", "destination")
    if any(before.get(key) != after.get(key) for key in stable):
        raise PictureLockError("cut repair changed stable caption authority")
    return {
        **base, "status": "revalidated",
        "beforeCompilationHash": caption_compilation_hash(before),
        "afterCompilationHash": caption_compilation_hash(after),
        "cues": _cue_revalidation(before, after, windows),
        "chapters": _chapter_revalidation(before, after, windows),
        "beforeCoverage": before["coverage"],
        "afterCoverage": after["coverage"],
    }


def revalidate_caption_compilations(
    compilations: CaptionCompilationPair,
    operation: dict,
) -> dict:
    """Build one receipt from already executed before/after compilers."""
    if not isinstance(compilations, CaptionCompilationPair):
        raise PictureLockError("caption repair compilations are missing")
    windows = _windows(operation)
    expected = (
        operation["totalOutputFramesBefore"],
        operation["totalOutputFramesAfter"],
    )
    if (compilations.before_frames, compilations.after_frames) != expected:
        raise PictureLockError(
            "caption compiler contexts do not match repair frame totals")
    if not compilations.same_rate:
        raise PictureLockError(
            "caption compiler frame rate changed through cut repair")
    before, after = compilations.before, compilations.after
    base = {
        "schemaVersion": 1, "kind": "caption-repair-revalidation",
        "operationHash": content_hash(operation),
        "authorizedDirtyWindows": windows,
    }
    payload = _revalidation_payload(before, after, base, windows)
    return {
        **payload, "revalidationHash": canonical_digest(
            "sniper-caption-repair-revalidation-v1", payload),
    }


def revalidate_caption_repair(contexts: CaptionRepairContexts,
                              operation: dict) -> dict:
    """Build a receipt from actual parent/child caption compiler executions."""
    if not isinstance(contexts, CaptionRepairContexts):
        raise PictureLockError("caption repair compiler contexts are missing")
    _validate_context_clocks(contexts, operation)
    return revalidate_caption_compilations(CaptionCompilationPair(
        compile_plan_caption_track(contexts.before),
        compile_plan_caption_track(contexts.after),
        _context_frames(contexts.before),
        _context_frames(contexts.after),
        contexts.before.rate == contexts.after.rate,
    ), operation)


def validate_caption_revalidation(value: object, operation: dict) -> dict:
    """Recompute identity and reject an open or stale revalidation receipt."""
    if not isinstance(value, dict):
        raise PictureLockError("caption revalidation receipt must be an object")
    validate_document("caption-repair-revalidation-v1.schema.json", value)
    common = {
        "schemaVersion", "kind", "operationHash",
        "authorizedDirtyWindows", "status", "revalidationHash",
    }
    status = value.get("status")
    detail = ({
        "beforeCompilationHash", "afterCompilationHash", "cues", "chapters",
        "beforeCoverage", "afterCoverage",
    } if status == "revalidated" else set())
    if status not in {"not-present", "revalidated"} \
            or set(value) != common | detail:
        raise PictureLockError("caption revalidation receipt is not closed")
    payload = {key: item for key, item in value.items()
               if key != "revalidationHash"}
    expected_hash = canonical_digest(
        "sniper-caption-repair-revalidation-v1", payload)
    if value.get("schemaVersion") != 1 \
            or value.get("kind") != "caption-repair-revalidation" \
            or value.get("operationHash") != content_hash(operation) \
            or value.get("authorizedDirtyWindows") != _windows(operation) \
            or value.get("revalidationHash") != expected_hash:
        raise PictureLockError("caption revalidation receipt is stale")
    return dict(value)
