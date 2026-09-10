"""Bind and prove exact CaptionTrackV1 alpha-shard tracks."""
from __future__ import annotations

from typing import Any

from palmier.desktop_alpha_readback import (
    AlphaTrackPolicy, require_alpha_records,
)
from palmier.desktop_ledger import clip_frames, clip_inventory
from palmier.desktop_caption_shard_plan import (
    ALPHA_OPS, BROLL_OP, GRAPHICS_OP, LANE, OP, TITLE_OP,
    plan_caption_shards,
)
from palmier.desktop_state import now, read_record
from palmier.mcp_client import PalmierError

PLACEHOLDER = "."


def _rows(state: dict) -> list[dict]:
    value = read_record(state["operations"]["path"], "operation manifest")
    return [row for row in value.get("steps") or []
            if isinstance(row, dict) and row.get("op") in ALPHA_OPS]


def _current_row(state: dict) -> dict | None:
    progress = _progress(state)
    if isinstance(progress, dict):
        return next((row for row in _rows(state)
                     if row.get("elementId")
                     == progress.get("elementId")), None)
    elements = (state.get("elementLedger") or {}).get("elements") or {}
    return next((row for row in _rows(state)
                 if row.get("elementId") not in elements), None)


def _progress(state: dict) -> dict | None:
    value = state.get("captionShardProgress")
    return value if isinstance(value, dict) else None


def _media_ref(state: dict, row: dict) -> str:
    digest = row.get("assetHash") or row.get("fileHash")
    value = (state.get("mediaLedger") or {}).get(digest)
    ref = value.get("mediaRef") if isinstance(value, dict) else None
    if not isinstance(ref, str):
        raise PalmierError("caption shard media has not been imported")
    return ref


def bind_caption_operation(
        tool: str, args: dict, state: dict) -> dict | None:
    """Bind placeholder/add/cleanup calls for one chronological cue."""
    if tool not in {"add_texts", "add_clips", "remove_clips"} \
            or not isinstance(state.get("operations"), dict):
        return None
    row, progress = _current_row(state), _progress(state)
    if row is None:
        return None
    if progress is None and tool == "add_texts":
        expected = {"entries": [{
            "content": PLACEHOLDER, "startFrame": 0, "endFrame": 1}]}
        if args != expected:
            return None
        return {"kind": "caption-placeholder-added", "row": row}
    if not isinstance(progress, dict) \
            or progress.get("elementId") != row.get("elementId"):
        return None
    if progress.get("status") == "place-shard" and tool == "add_clips":
        entry = {
            "mediaRef": _media_ref(state, row),
            "startFrame": row["startFrame"], "endFrame": row["endFrame"],
            "trackIndex": 0, "transform": row["transform"]}
        if row.get("source") is not None:
            entry["source"] = row["source"]
        expected = {"entries": [entry]}
        if args != expected:
            return None
        return {"kind": "caption-shard-added", "row": row,
                "placeholderClipId": progress["clipId"]}
    if progress.get("status") == "cleanup-required" \
            and tool == "remove_clips" \
            and args == {"clipIds": [progress.get("clipId")]}:
        return {"kind": "caption-placeholder-removed", "row": row,
                "placeholderClipId": progress["clipId"]}
    return None


def assert_caption_mutation_allowed(
        tool: str, args: dict, state: dict) -> None:
    """Prevent any interleaving while a temporary top track is open."""
    progress = _progress(state)
    row = _current_row(state)
    if progress is None and row is not None and tool == "add_texts" \
            and bind_caption_operation(tool, args, state) is None:
        raise PalmierError(
            "exact alpha top-track placeholder differs from worklist")
    if progress is None:
        return
    binding = bind_caption_operation(tool, args, state)
    if binding is None:
        raise PalmierError(
            "caption alpha-shard top-track placement must finish first")


def _added(before: dict, after: dict) -> tuple[dict, set[str], set[str]]:
    old, new = clip_inventory(before), clip_inventory(after)
    return new, set(old) - set(new), set(new) - set(old)


def _observe_placeholder(state: dict, binding: dict,
                         before: dict, after: dict) -> None:
    clips, removed, added = _added(before, after)
    matches = [clips[ident] for ident in added
               if clip_frames(clips[ident]) == (0, 1)
               and clips[ident].get("textContent") == PLACEHOLDER
               and clips[ident].get("_trackIndex") == 0]
    if removed or len(matches) != 1 or len(added) != 1:
        raise PalmierError("caption top-track placeholder readback is unsafe")
    _shift_existing_video_tracks(state)
    state["captionShardProgress"] = {
        "elementId": binding["row"]["elementId"],
        "clipId": matches[0]["id"], "status": "place-shard"}


def _shift_existing_video_tracks(state: dict) -> None:
    """A new top video track increments every prior governed video index."""
    elements = (state.get("elementLedger") or {}).get("elements") or {}
    for record in elements.values():
        if not isinstance(record, dict):
            continue
        index = record.get("trackIndex")
        if isinstance(index, int) and not isinstance(index, bool):
            record["trackIndex"] = index + 1


def _observe_shard(state: dict, binding: dict,
                   before: dict, after: dict) -> None:
    row = binding["row"]
    clips, removed, added = _added(before, after)
    ref = _media_ref(state, row)
    matches = [clips[ident] for ident in added
               if clip_frames(clips[ident]) == (
                   row["startFrame"], row["endFrame"])
               and clips[ident].get("mediaRef") == ref
               and clips[ident].get("_trackIndex") == 0]
    placeholder = binding["placeholderClipId"]
    if len(matches) != 1 or len(added) != 1 \
            or removed - {placeholder}:
        raise PalmierError("caption alpha-shard placement readback is unsafe")
    clip = matches[0]
    ledger = state.setdefault("elementLedger", {
        "schemaVersion": 2, "elements": {}, "tombstones": {}})
    ledger.setdefault("elements", {})[row["elementId"]] = {
        "status": "current", "lane": row["lane"], "clipId": clip["id"],
        "mediaRef": ref, "assetHash": row.get("assetHash") or row["fileHash"],
        "assetPath": row.get("assetPath") or row["path"],
        "startFrame": row["startFrame"],
        "endFrame": row["endFrame"], "trackIndex": 0,
        "alphaMode": row["alphaMode"], "version": 1, "generation": 1,
        "transform": clip.get("transform"),
        "updatedAt": now(),
    }
    ledger["updatedAt"] = now()
    if placeholder in removed:
        state.pop("captionShardProgress", None)
    else:
        state["captionShardProgress"]["status"] = "cleanup-required"


def _observe_cleanup(state: dict, binding: dict,
                     before: dict, after: dict) -> None:
    _clips, removed, added = _added(before, after)
    if added or removed != {binding["placeholderClipId"]}:
        raise PalmierError("caption placeholder cleanup changed other clips")
    state.pop("captionShardProgress", None)


def observe_caption_operation(observation: Any) -> bool:
    """Apply exact caption readback to the Desktop element ledger."""
    binding = observation.pending.get("binding")
    if not isinstance(binding, dict):
        return False
    handlers = {
        "caption-placeholder-added": _observe_placeholder,
        "caption-shard-added": _observe_shard,
        "caption-placeholder-removed": _observe_cleanup,
    }
    handler = handlers.get(binding.get("kind"))
    if handler is None:
        return False
    handler(
        observation.state, binding, observation.before, observation.after)
    return True


def require_caption_shards_ready(
        state: dict, timeline: dict | None = None) -> dict | None:
    """Prove every declared cue is a current, dedicated, hash-bound clip."""
    rows = [row for row in _rows(state) if row.get("op") == OP]
    if not rows:
        return None
    if _progress(state) is not None:
        raise PalmierError("caption alpha-shard placement is incomplete")
    tracks = require_alpha_records(
        state, rows, timeline, AlphaTrackPolicy(
            "caption alpha-shard", shared_track=False))
    return {"mode": "baked-regenerable-alpha-shards",
            "cueCount": len(rows), "editableText": False,
            "tracks": tracks}


def require_title_shards_ready(
        state: dict, timeline: dict | None = None) -> dict | None:
    """Prove every branded title card landed as its exact alpha asset."""
    rows = [row for row in _rows(state) if row.get("op") == TITLE_OP]
    if not rows:
        return None
    if _progress(state) is not None:
        raise PalmierError("title-card alpha placement is incomplete")
    tracks = require_alpha_records(
        state, rows, timeline, AlphaTrackPolicy(
            "title-card alpha", shared_track=False))
    return {
        "mode": "baked-regenerable-alpha-shards",
        "cardCount": len(rows), "editableText": False,
        "tracks": tracks,
    }


def require_graphics_shards_ready(
        state: dict, timeline: dict | None = None) -> dict | None:
    """Prove normalized graphics preserve authored order on dedicated tracks."""
    rows = [row for row in _rows(state) if row.get("op") == GRAPHICS_OP]
    if not rows:
        return None
    tracks = require_alpha_records(
        state, rows, timeline, AlphaTrackPolicy(
            "governed full-canvas graphic", shared_track=False))
    return {
        "mode": "full-canvas-governed-alpha-assets",
        "graphicCount": len(rows), "tracks": tracks,
        "planOrderPreserved": True,
    }


def require_broll_layers_ready(
        state: dict, timeline: dict | None = None) -> dict | None:
    """Prove every b-roll item is above base on a dedicated governed track."""
    rows = [row for row in _rows(state) if row.get("op") == BROLL_OP]
    if not rows:
        return None
    if _progress(state) is not None:
        raise PalmierError("b-roll top-track placement is incomplete")
    tracks = require_alpha_records(
        state, rows, timeline, AlphaTrackPolicy(
            "governed b-roll", shared_track=False))
    return {
        "mode": "native-governed-top-tracks",
        "clipCount": len(rows), "tracks": tracks,
        "planOrderPreserved": True,
    }


def alpha_layer_pending(state: dict) -> bool:
    """Whether an earlier dedicated alpha/b-roll layer is unfinished."""
    return _progress(state) is not None or _current_row(state) is not None
