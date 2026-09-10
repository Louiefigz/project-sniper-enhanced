"""Bind and prove one bounded top track of sequential caption alpha pages."""
from __future__ import annotations

from typing import Any

from palmier.desktop_alpha_readback import (
    AlphaTrackPolicy, require_alpha_records,
)
from palmier.desktop_caption_page_plan import LANE, OP
from palmier.desktop_caption_shards import (
    PLACEHOLDER, _shift_existing_video_tracks, alpha_layer_pending,
)
from palmier.desktop_ledger import clip_frames, clip_inventory
from palmier.desktop_state import now, read_record
from palmier.mcp_client import PalmierError


def _step(state: dict) -> dict | None:
    operations = state.get("operations")
    path = operations.get("path") if isinstance(operations, dict) else None
    if not isinstance(path, str):
        return None
    if alpha_layer_pending(state):
        return None
    value = read_record(path, "operation manifest")
    matches = [row for row in value.get("steps") or []
               if isinstance(row, dict) and row.get("op") == OP]
    if len(matches) > 1:
        raise PalmierError("Desktop worklist repeats caption alpha pages")
    return matches[0] if matches else None


def _progress(state: dict) -> dict | None:
    value = state.get("captionPageProgress")
    return value if isinstance(value, dict) else None


def _media_ref(state: dict, row: dict) -> str:
    value = (state.get("mediaLedger") or {}).get(row.get("assetHash"))
    ref = value.get("mediaRef") if isinstance(value, dict) else None
    if not isinstance(ref, str):
        raise PalmierError("caption alpha-page media was not imported")
    return ref


def bind_caption_page_operation(
        tool: str, args: dict, state: dict) -> dict | None:
    """Bind placeholder, bulk page placement, and placeholder cleanup."""
    step, progress = _step(state), _progress(state)
    if step is None:
        return None
    if progress is None and tool == "add_texts":
        expected = {"entries": [{
            "content": PLACEHOLDER, "startFrame": 0, "endFrame": 1}]}
        if args == expected:
            return {"kind": "caption-page-placeholder", "step": step}
        return None
    if not isinstance(progress, dict):
        return None
    if progress.get("status") == "place-pages" and tool == "add_clips":
        entries = [{
            "mediaRef": _media_ref(state, row),
            "startFrame": row["startFrame"], "endFrame": row["endFrame"],
            "trackIndex": 0, "transform": row["transform"],
        } for row in step["entries"]]
        if args == {"entries": entries}:
            return {"kind": "caption-pages-added", "step": step,
                    "placeholderClipId": progress["clipId"]}
    if progress.get("status") == "cleanup-required" \
            and tool == "remove_clips" \
            and args == {"clipIds": [progress.get("clipId")]}:
        return {"kind": "caption-page-placeholder-removed",
                "step": step, "placeholderClipId": progress["clipId"]}
    return None


def assert_caption_page_mutation_allowed(
        tool: str, args: dict, state: dict) -> None:
    """Forbid interleaving or an arbitrary visual add_texts mutation."""
    step, progress = _step(state), _progress(state)
    if step is None:
        return
    binding = bind_caption_page_operation(tool, args, state)
    if progress is not None and binding is None:
        raise PalmierError("caption alpha-page placement must finish first")
    if progress is None and tool == "add_texts" and binding is None:
        raise PalmierError("caption alpha-page placeholder differs from worklist")


def _delta(before: dict, after: dict) -> tuple[dict, set[str], set[str]]:
    old, new = clip_inventory(before), clip_inventory(after)
    return new, set(old) - set(new), set(new) - set(old)


def _placeholder(state: dict, binding: dict,
                 before: dict, after: dict) -> None:
    clips, removed, added = _delta(before, after)
    matches = [clips[ident] for ident in added
               if clip_frames(clips[ident]) == (0, 1)
               and clips[ident].get("textContent") == PLACEHOLDER
               and clips[ident].get("_trackIndex") == 0]
    if removed or len(matches) != 1 or len(added) != 1:
        raise PalmierError("caption page placeholder readback is unsafe")
    _shift_existing_video_tracks(state)
    state["captionPageProgress"] = {
        "clipId": matches[0]["id"], "status": "place-pages"}


def _pages(state: dict, binding: dict,
           before: dict, after: dict) -> None:
    clips, removed, added = _delta(before, after)
    rows = binding["step"]["entries"]
    placeholder = binding["placeholderClipId"]
    matches = []
    for row in rows:
        found = [clips[ident] for ident in added
                 if clip_frames(clips[ident]) == (
                     row["startFrame"], row["endFrame"])
                 and clips[ident].get("mediaRef") == _media_ref(state, row)
                 and clips[ident].get("_trackIndex") == 0]
        if len(found) != 1:
            raise PalmierError("caption alpha-page readback is ambiguous")
        matches.append(found[0])
    if len(added) != len(rows) or removed - {placeholder}:
        raise PalmierError("caption page placement changed unrelated clips")
    _record_pages(state, rows, matches)
    if placeholder in removed:
        state.pop("captionPageProgress", None)
    else:
        state["captionPageProgress"]["status"] = "cleanup-required"


def _record_pages(state: dict, rows: list[dict],
                  clips: list[dict]) -> None:
    ledger = state.setdefault("elementLedger", {
        "schemaVersion": 2, "elements": {}, "tombstones": {}})
    for row, clip in zip(rows, clips, strict=True):
        ledger.setdefault("elements", {})[row["elementId"]] = {
            "status": "current", "lane": LANE, "clipId": clip["id"],
            "mediaRef": clip["mediaRef"], "assetHash": row["assetHash"],
            "assetPath": row["assetPath"],
            "startFrame": row["startFrame"], "endFrame": row["endFrame"],
            "trackIndex": 0, "transform": clip.get("transform"),
            "version": 1, "generation": 1, "updatedAt": now(),
        }
    ledger["updatedAt"] = now()


def observe_caption_page_operation(observation: Any) -> bool:
    """Advance page placement state from exact timeline deltas."""
    binding = observation.pending.get("binding")
    if not isinstance(binding, dict):
        return False
    handlers = {
        "caption-page-placeholder": _placeholder,
        "caption-pages-added": _pages,
    }
    handler = handlers.get(binding.get("kind"))
    if handler is not None:
        handler(observation.state, binding,
                observation.before, observation.after)
        return True
    if binding.get("kind") != "caption-page-placeholder-removed":
        return False
    _clips, removed, added = _delta(
        observation.before, observation.after)
    if added or removed != {binding["placeholderClipId"]}:
        raise PalmierError("caption page placeholder cleanup is unsafe")
    observation.state.pop("captionPageProgress", None)
    return True


def require_caption_pages_ready(
        state: dict, timeline: dict | None = None) -> dict | None:
    """Require every page on one shared, hash-bound video track."""
    step = _step(state)
    if step is None:
        return None
    if _progress(state) is not None:
        raise PalmierError("caption alpha-page placement is incomplete")
    tracks = require_alpha_records(
        state, step["entries"], timeline, AlphaTrackPolicy(
            "caption alpha-page", shared_track=True,
            descending_plan_order=False))
    return {"mode": "baked-regenerable-alpha-pages",
            "pageCount": len(tracks), "trackIndex": tracks[0],
            "editableText": False}
