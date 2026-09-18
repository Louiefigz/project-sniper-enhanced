#!/usr/bin/env python3
"""Resolve caption groups, word-boundary suppression, and bounded shards."""
from __future__ import annotations

import hashlib

from captions.caption_contract import CaptionContractError


def _group_id(word_ids: list[str]) -> str:
    payload = ("sniper-caption-default-group-v1\0"
               + "\0".join(word_ids)).encode()
    return f"cg-{hashlib.sha256(payload).hexdigest()[:16]}"


def _runs(rows: list[dict], selected: set[str]) -> list[list[dict]]:
    result: list[list[dict]] = []
    current: list[dict] = []
    for row in rows:
        if row["wordId"] in selected:
            current.append(row)
            continue
        if current:
            result.append(current)
            current = []
    if current:
        result.append(current)
    return result


def _default_group(words: list[dict], policy: str) -> dict:
    word_ids = [row["wordId"] for row in words]
    return {
        "groupId": _group_id(word_ids),
        "anchor": {"kind": "word-range", "wordIds": word_ids},
        "styleId": "default",
        "mode": "line" if policy == "line" else "karaoke-word",
        "placement": "bottom-center",
    }


def resolve_groups(track: dict, words: list[dict]) -> list[dict]:
    """Resolve explicit groups plus default-policy gaps in timeline order."""
    positions = {row["wordId"]: index for index, row in enumerate(words)}
    claimed: set[str] = set()
    explicit: list[tuple[int, dict]] = []
    for group in track["groups"]:
        ids = group["anchor"]["wordIds"]
        if any(ident not in positions for ident in ids):
            raise CaptionContractError(
                f"caption group {group['groupId']} references a non-kept word")
        indices = [positions[ident] for ident in ids]
        expected = list(range(indices[0], indices[0] + len(indices)))
        if indices != expected:
            raise CaptionContractError(
                f"caption group {group['groupId']} is not a consecutive range")
        claimed.update(ids)
        explicit.append((indices[0], group))
    defaults: list[tuple[int, dict]] = []
    if track["defaultPolicy"] != "off":
        uncovered = {row["wordId"] for row in words} - claimed
        for run in _runs(words, uncovered):
            defaults.append((positions[run[0]["wordId"]],
                             _default_group(run, track["defaultPolicy"])))
    return [row for _, row in sorted(explicit + defaults, key=lambda item: item[0])]


def tokens_for_group(tokens: list[dict], group: dict) -> list[dict]:
    """Select display tokens without allowing a correction across a boundary."""
    selected = set(group["anchor"]["wordIds"])
    result: list[dict] = []
    for token in tokens:
        source = set(token["sourceWordIds"])
        overlap = source & selected
        if overlap and not source <= selected:
            raise CaptionContractError(
                f"correction {token.get('correctionId')} crosses caption groups")
        if source <= selected:
            result.append(token)
    if not result:
        raise CaptionContractError(
            f"caption group {group['groupId']} compiled no display tokens")
    return result


def validate_scene_windows(value: object) -> list[dict]:
    """Validate exact half-open scene ranges used for caption suppression."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise CaptionContractError("caption scene windows must be a list")
    result: list[dict] = []
    for index, row in enumerate(value):
        if not isinstance(row, dict) or set(row) != {
                "sceneId", "startFrame", "endFrameExclusive"}:
            raise CaptionContractError(f"caption scene window {index} is malformed")
        start, end = row["startFrame"], row["endFrameExclusive"]
        if not isinstance(row["sceneId"], str) or not row["sceneId"]:
            raise CaptionContractError(f"caption scene window {index} has no id")
        if any(isinstance(item, bool) or not isinstance(item, int)
               for item in (start, end)) or start < 0 or end <= start:
            raise CaptionContractError(
                f"caption scene window {index} has invalid frames")
        result.append(dict(row))
    return result


def _overlaps(token: dict, window: dict) -> bool:
    return (token["startFrame"] < window["endFrameExclusive"]
            and token["endFrameExclusive"] > window["startFrame"])


def suppress_tokens(tokens: list[dict], group: dict,
                    scenes: list[dict]) -> tuple[list[list[dict]], set[str]]:
    """Drop only word-boundary correction atoms overlapping declared scenes."""
    scene_ids = set(group.get("suppressUnderSceneIds") or [])
    windows = [row for row in scenes if row["sceneId"] in scene_ids]
    suppressed = {
        ident
        for token in tokens
        if any(_overlaps(token, window) for window in windows)
        for ident in token["sourceWordIds"]
    }
    runs: list[list[dict]] = []
    current: list[dict] = []
    for token in tokens:
        hidden = bool(suppressed & set(token["sourceWordIds"]))
        if hidden and current:
            runs.append(current)
            current = []
        if hidden:
            continue
        current.append(token)
    if current:
        runs.append(current)
    return runs, suppressed


def _atoms(run: list[dict]) -> list[list[dict]]:
    """Keep every multi-token correction indivisible at shard boundaries."""
    result: list[list[dict]] = []
    for token in run:
        correction_id = token.get("correctionId")
        if correction_id and result \
                and result[-1][-1].get("correctionId") == correction_id:
            result[-1].append(token)
        else:
            result.append([token])
    return result


def _shard_run(run: list[dict], max_frames: int) -> list[list[dict]]:
    result: list[list[dict]] = []
    current: list[dict] = []
    for atom in _atoms(run):
        start, end = atom[0]["startFrame"], atom[-1]["endFrameExclusive"]
        if end - start > max_frames:
            raise CaptionContractError(
                f"caption token {atom[0]['tokenId']} exceeds shard bound")
        candidate_start = current[0]["startFrame"] if current else start
        if current and end - candidate_start > max_frames:
            result.append(current)
            current = []
        current.extend(atom)
    if current:
        result.append(current)
    return result


def shard_runs(runs: list[list[dict]], max_frames: int) -> list[list[dict]]:
    """Split visible runs at token boundaries under a hard duration bound."""
    if isinstance(max_frames, bool) or not isinstance(max_frames, int) \
            or max_frames < 1:
        raise CaptionContractError("max caption shard frames must be positive")
    result: list[list[dict]] = []
    for run in runs:
        result.extend(_shard_run(run, max_frames))
    return result
