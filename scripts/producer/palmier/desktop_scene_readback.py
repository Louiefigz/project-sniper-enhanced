"""Extra preservation checks for scene-bound Desktop replacements."""
from __future__ import annotations

from palmier.desktop_ledger import clip_frames
from palmier.mcp_client import PalmierError


def _scene_rows(binding: dict) -> list[dict]:
    return [row for row in binding.get("elements") or []
            if isinstance(row, dict)
            and isinstance(row.get("sceneBindingId"), str)]


def assert_scene_replacement_readback(
    binding: dict,
    before: dict[str, dict],
    after: dict[str, dict],
) -> None:
    """Reject stale targets and every in-place unrelated clip mutation."""
    rows = _scene_rows(binding)
    if not rows:
        return
    targets = {row.get("oldClipId") for row in rows}
    if targets.intersection(after):
        raise PalmierError(
            "scene replacement retained its superseded Palmier clip")
    for row in rows:
        clip = before.get(row["oldClipId"])
        expected = (
            row.get("oldMediaRef"),
            (row.get("startFrame"), row.get("endFrame")),
            row.get("trackIndex"),
        )
        actual = (
            clip.get("mediaRef") if isinstance(clip, dict) else None,
            clip_frames(clip) if isinstance(clip, dict) else None,
            clip.get("_trackIndex") if isinstance(clip, dict) else None,
        )
        if actual != expected:
            raise PalmierError(
                "scene replacement target is stale in fresh readback")
    for clip_id in (set(before) & set(after)) - targets:
        if before[clip_id] != after[clip_id]:
            raise PalmierError(
                "scene replacement changed an unrelated clip in place")
