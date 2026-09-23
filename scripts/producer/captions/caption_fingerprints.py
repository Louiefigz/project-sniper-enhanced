#!/usr/bin/env python3
"""Content/timing fingerprints and local caption invalidation receipts."""
from __future__ import annotations

import hashlib
import json
import os

from captions.caption_contract import (
    validate_caption_track,
    validate_correction_ledger,
)

_HERE = os.path.dirname(os.path.abspath(__file__))
_COMPILER_SOURCES = (
    "caption_contract.py",
    "caption_context.py",
    "caption_occurrences.py",
    "caption_words.py",
    "caption_word_exact_timing.py",
    "caption_grouping.py",
    "caption_compile.py",
    "caption_exact_payload.py",
    "caption_fingerprints.py",
    "caption_outputs.py",
    "caption_ass_projection.py",
    "captions_ass.py",
    "caption_plan_pipeline.py",
    "caption_authority.py",
    "caption_render.py",
    "caption_assemble.py",
    "caption_shards.py",
    "caption_font_closure.py",
    "caption_shard_contract.py",
    "caption_shard_media.py",
    "caption_shard_composite.py",
    "caption_shard_authority.py",
    "dialogue_caption_timing.py",
    "dialogue_caption_compile.py",
    "cut_repair_dialogue_words.py",
    "cut_repair_dialogue_authority.py",
    "../edit/dialogue_contracts.py",
    "../edit/dialogue_authority.py",
    "../edit/picture_lock_common.py",
    "../compile_timeline.py",
    "../edit_scope.py",
    "../cross_runtime_canonical_json.py",
    "../producer_config.py",
)


def canonical_digest(domain: str, value: object) -> str:
    """Domain-separated SHA-256 over canonical JSON."""
    blob = json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False).encode("ascii")
    return hashlib.sha256(domain.encode("ascii") + b"\0" + blob).hexdigest()


def caption_track_hash(track: object) -> str:
    """Digest strict normalized CaptionTrackV1 authority."""
    return canonical_digest(
        "sniper-caption-track-v1", validate_caption_track(track))


def correction_ledger_hash(ledger: object) -> str:
    """Digest strict global display-correction authority."""
    return canonical_digest(
        "sniper-caption-correction-ledger-v1",
        validate_correction_ledger(ledger))


def caption_compiler_hash(toolchain: object = None) -> str:
    """Bind caption compiler source closure plus declared render toolchain."""
    sources = []
    for name in _COMPILER_SOURCES:
        path = os.path.join(_HERE, name)
        if not os.path.isfile(path):
            continue
        with open(path, "rb") as handle:
            sources.append({
                "name": name,
                "sha256": hashlib.sha256(handle.read()).hexdigest(),
            })
    return canonical_digest("sniper-caption-compiler-v1", {
        "sources": sources, "toolchain": toolchain or {},
    })


def caption_content_digest(payload: object) -> str:
    """Hash shaping/content inputs, excluding timing and placement."""
    return canonical_digest("sniper-caption-content-v1", payload)


def caption_cue_fingerprint(payload: object) -> str:
    """Hash resolved timing, map slice, placement, and destination inputs."""
    return canonical_digest("sniper-caption-cue-v1", payload)


def _cue_map(compilation: dict) -> dict[str, dict]:
    cues = compilation.get("cues")
    if not isinstance(cues, list) or any(not isinstance(row, dict)
                                         for row in cues):
        raise ValueError("caption compilation has no valid cues")
    result = {row.get("cueId"): row for row in cues}
    if None in result or len(result) != len(cues):
        raise ValueError("caption compilation cue ids are missing or duplicate")
    return result


def _dirty_windows(cues: list[dict]) -> list[list[int]]:
    windows = sorted((row["startFrame"], row["endFrameExclusive"])
                     for row in cues)
    result: list[list[int]] = []
    for start, end in windows:
        if not result or start > result[-1][1]:
            result.append([start, end])
        else:
            result[-1][1] = max(result[-1][1], end)
    return result


def diff_caption_compilations(before: dict, after: dict) -> dict:
    """Return node-local invalidation; picture/base authority is never dirty."""
    old, new = _cue_map(before), _cue_map(after)
    all_ids = sorted(set(old) | set(new))
    content_dirty, cue_dirty, content_reused = [], [], []
    affected: list[dict] = []
    for ident in all_ids:
        left, right = old.get(ident), new.get(ident)
        if left is None or right is None:
            cue_dirty.append(ident)
            content_dirty.append(ident)
            affected.extend(row for row in (left, right) if row is not None)
            continue
        content_changed = (
            left.get("captionContentDigest")
            != right.get("captionContentDigest"))
        cue_changed = content_changed or (
            left.get("captionCueFingerprint")
            != right.get("captionCueFingerprint"))
        if content_changed:
            content_dirty.append(ident)
        if cue_changed and not content_changed:
            content_reused.append(ident)
        if cue_changed:
            cue_dirty.append(ident)
            affected.extend((left, right))
    return {
        "schemaVersion": 1, "kind": "caption-invalidation",
        "baseDirty": False,
        "captionContentNodes": content_dirty,
        "captionCueNodes": cue_dirty,
        "reusedContentNodes": content_reused,
        "dirtyFrameWindows": _dirty_windows(affected),
    }
