#!/usr/bin/env python3
"""Compile CaptionTrackV1 into deterministic word-boundary alpha shards."""
from __future__ import annotations

import hashlib

from captions.caption_contract import (
    CaptionContractError,
    validate_caption_track,
    validate_correction_ledger,
)
from captions.caption_context import (
    CaptionCompileContext,
    max_shard_frames,
    require_sha256,
    validate_compile_context,
    validate_destination,
)
from captions.caption_exact_payload import content_token, timing_token
from captions.caption_fingerprints import (
    canonical_digest,
    caption_compiler_hash,
    caption_content_digest,
    caption_cue_fingerprint,
    caption_track_hash,
    correction_ledger_hash,
)
from captions.caption_grouping import (
    resolve_groups,
    shard_runs,
    suppress_tokens,
    tokens_for_group,
    validate_scene_windows,
)
from captions.caption_words import apply_correction_ledger, validate_resolved_words


def _style(group: dict, styles: dict[str, dict]) -> dict:
    style_id = group["styleId"]
    value = styles.get(style_id)
    if not isinstance(value, dict):
        raise CaptionContractError(
            f"caption style {style_id!r} has no immutable inputs")
    return value


def _ordered_word_ids(tokens: list[dict]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    identifiers = (
        ident for token in tokens for ident in token["sourceWordIds"])
    for ident in identifiers:
        if ident not in seen:
            seen.add(ident)
            result.append(ident)
    return result


def _relevant_corrections(tokens: list[dict], ledger: dict) -> list[dict]:
    ids = {row.get("correctionId") for row in tokens
           if isinstance(row.get("correctionId"), str)}
    return [{
        key: row[key]
        for key in (
            "correctionId", "sourceWordIds", "displayTokens", "timingPolicy")
    } for row in ledger["corrections"] if row["correctionId"] in ids]


def _timeline_slice(word_ids: list[str], context: CaptionCompileContext) -> dict:
    available = [ident in context.timeline_slices for ident in word_ids]
    if any(available) and not all(available):
        raise CaptionContractError("caption timeline slices are incomplete")
    if all(available):
        rows = []
        for ident in word_ids:
            rows.append([ident, require_sha256(
                context.timeline_slices[ident],
                f"timeline slice for {ident}")])
        return {"scope": "word-slices", "digest": canonical_digest(
            "sniper-caption-map-slice-v1", rows)}
    return {"scope": "full-map", "digest": require_sha256(
        context.timeline_map_hash, "caption timeline map")}


def _cue_id(group: dict, tokens: list[dict]) -> str:
    word_ids = _ordered_word_ids(tokens)
    payload = "\0".join((
        "sniper-caption-cue-id-v1", group["groupId"],
        word_ids[0], word_ids[-1]))
    return f"cue-{hashlib.sha256(payload.encode()).hexdigest()[:16]}"


def _content_payload(group: dict, tokens: list[dict], ledger: dict,
                     inputs: dict) -> dict:
    return {
        "wordIds": _ordered_word_ids(tokens),
        "tokens": [content_token(row) for row in tokens],
        "corrections": _relevant_corrections(tokens, ledger),
        "styleId": group["styleId"], "styleInputs": inputs["style"],
        "mode": group["mode"], "language": group.get("language"),
        "compilerHash": inputs["compilerHash"],
    }


def _suppression_evidence(group: dict, scenes: list[dict],
                          tokens: list[dict]) -> list[dict]:
    scene_ids = set(group.get("suppressUnderSceneIds") or [])
    start, end = tokens[0]["startFrame"], tokens[-1]["endFrameExclusive"]
    return [row for row in scenes if row["sceneId"] in scene_ids
            and start < row["endFrameExclusive"]
            and end > row["startFrame"]]


def _cue_payload(group: dict, tokens: list[dict],
                 inputs: dict) -> dict:
    word_ids = _ordered_word_ids(tokens)
    timing = [
        timing_token(row, inputs["context"]) for row in tokens]
    timing_digest = canonical_digest("sniper-caption-word-timing-v1", timing)
    return {
        "captionContentDigest": inputs["contentDigest"],
        "startFrame": tokens[0]["startFrame"],
        "endFrameExclusive": tokens[-1]["endFrameExclusive"],
        "startSample": timing[0]["startSample"],
        "endSampleExclusive": timing[-1]["endSampleExclusive"],
        "sampleRate": inputs["context"].sample_rate,
        "tokenTiming": timing, "wordTimingDigest": timing_digest,
        "timelineMapSlice": _timeline_slice(word_ids, inputs["context"]),
        "fps": inputs["context"].rate.to_dict(),
        "segmentVersions": {
            ident: inputs["context"].segment_versions.get(ident)
            for ident in word_ids
            if ident in inputs["context"].segment_versions
        },
        "placement": group["placement"],
        "destination": inputs["destination"],
        "suppressionWindows": _suppression_evidence(
            group, inputs["scenes"], tokens),
        "compilerHash": inputs["compilerHash"],
    }


def _compile_cue(group: dict, tokens: list[dict], inputs: dict) -> dict:
    content = _content_payload(
        group, tokens, inputs["ledger"], inputs)
    content_digest = caption_content_digest(content)
    cue_payload = _cue_payload(
        group, tokens, {**inputs, "contentDigest": content_digest})
    cue_fingerprint = caption_cue_fingerprint(cue_payload)
    return {
        "cueId": _cue_id(group, tokens), "groupId": group["groupId"],
        "styleId": group["styleId"], "mode": group["mode"],
        "placement": group["placement"],
        **({"language": group["language"]} if "language" in group else {}),
        "sourceWordIds": _ordered_word_ids(tokens),
        "tokens": tokens, "startFrame": tokens[0]["startFrame"],
        "endFrameExclusive": tokens[-1]["endFrameExclusive"],
        "startSample": cue_payload["startSample"],
        "endSampleExclusive": cue_payload["endSampleExclusive"],
        "sampleRate": cue_payload["sampleRate"],
        "captionContentDigest": content_digest,
        "captionCueFingerprint": cue_fingerprint,
        "contentAssetKey": content_digest,
        "placedShardKey": cue_fingerprint,
        "timelineMapSlice": cue_payload["timelineMapSlice"],
        "wordTimingDigest": cue_payload["wordTimingDigest"],
    }


def _compile_group(group: dict, tokens: list[dict],
                   inputs: dict) -> tuple[list[dict], set[str]]:
    selected = tokens_for_group(tokens, group)
    runs, suppressed = suppress_tokens(selected, group, inputs["scenes"])
    shards = shard_runs(runs, inputs["maxFrames"])
    local = {**inputs, "style": _style(group, inputs["context"].style_inputs)}
    return [_compile_cue(group, shard, local) for shard in shards], suppressed


def _coverage(track: dict, words: list[dict], cues: list[dict],
              suppressed: set[str]) -> dict:
    expected = ({row["wordId"] for row in words}
                if track["defaultPolicy"] != "off"
                else {ident for group in track["groups"]
                      for ident in group["anchor"]["wordIds"]})
    rendered_rows = [
        ident for cue in cues for ident in cue["sourceWordIds"]]
    rendered = set(rendered_rows)
    duplicate = len(rendered_rows) != len(rendered)
    if duplicate or rendered & suppressed or rendered | suppressed != expected:
        raise CaptionContractError(
            "caption compilation has missing, duplicate, or ghost word coverage")
    all_words = {row["wordId"] for row in words}
    return {
        "expectedWordIds": sorted(expected),
        "renderedWordIds": sorted(rendered),
        "suppressedWordIds": sorted(suppressed),
        "omittedWordIds": sorted(all_words - expected),
    }


def _cue_speakers(cue: dict) -> set[str]:
    return {
        str(row["speaker"])
        for row in cue["tokens"]
        if isinstance(row.get("speaker"), (str, int))
    }


def _speaker_band(placement: str) -> str:
    if placement in {"bottom-center", "lower-third"}:
        return "lower"
    return placement


def _speaker_collision(cue: dict, active: list[dict]) -> dict | None:
    speakers = _cue_speakers(cue)
    band = _speaker_band(cue["placement"])
    for other in active:
        other_speakers = _cue_speakers(other)
        collision = (
            speakers and other_speakers
            and speakers.isdisjoint(other_speakers)
            and band == _speaker_band(other["placement"])
        )
        if collision:
            return other
    return None


def _validate_speaker_collisions(cues: list[dict]) -> None:
    """Reject simultaneous speakers assigned to the same visible band."""
    ordered = sorted(cues, key=lambda row: (
        row["startFrame"], row["endFrameExclusive"], row["cueId"]))
    active: list[dict] = []
    for cue in ordered:
        active = [
            row for row in active
            if row["endFrameExclusive"] > cue["startFrame"]
        ]
        other = _speaker_collision(cue, active)
        if other is not None:
            raise CaptionContractError(
                "simultaneous caption speakers collide in the same band: "
                f"{other['cueId']} and {cue['cueId']}")
        active.append(cue)


def compile_caption_track(context: CaptionCompileContext) -> dict:
    """Compile one authority generation into independently cacheable shards."""
    context = validate_compile_context(context)
    track = validate_caption_track(context.track)
    ledger = validate_correction_ledger(context.ledger)
    ledger_hash = correction_ledger_hash(ledger)
    bound_hash = track.get("transcriptCorrectionHash")
    if bound_hash is not None and bound_hash != ledger_hash:
        raise CaptionContractError("caption track binds a different correction ledger")
    words = validate_resolved_words(context.words)
    tokens = apply_correction_ledger(words, ledger)
    groups = resolve_groups(track, words)
    scenes = validate_scene_windows(context.scene_windows)
    compiler_hash = caption_compiler_hash(context.toolchain)
    destination = validate_destination(context.destination)
    inputs = {
        "context": context, "ledger": ledger, "scenes": scenes,
        "compilerHash": compiler_hash, "destination": destination,
        "maxFrames": max_shard_frames(context),
    }
    cues: list[dict] = []
    suppressed: set[str] = set()
    for group in groups:
        group_cues, group_suppressed = _compile_group(group, tokens, inputs)
        cues.extend(group_cues)
        suppressed.update(group_suppressed)
    _validate_speaker_collisions(cues)
    coverage = _coverage(track, words, cues, suppressed)
    return {
        "schemaVersion": 1, "kind": "caption-compilation",
        "captionTrackHash": caption_track_hash(track),
        "correctionLedgerHash": ledger_hash,
        "compilerHash": compiler_hash, "fps": context.rate.to_dict(),
        "sampleRate": context.sample_rate,
        "timelineMapHash": context.timeline_map_hash,
        "destination": destination, "maxShardFrames": inputs["maxFrames"],
        "cues": cues, "coverage": coverage,
    }
