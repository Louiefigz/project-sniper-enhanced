"""Bindings and readback checks for structural revision mutations."""
from __future__ import annotations

from palmier.desktop_ledger import clip_frames, clip_inventory
from palmier.desktop_state import now
from palmier.mcp_client import PalmierError


def remove_binding(args: dict, steps: list[dict]) -> dict:
    """Bind exact remove_clips args to revision removal work."""
    ids = args.get("clipIds")
    if not isinstance(ids, list) or not ids:
        raise PalmierError("Palmier remove_clips requires explicit clipIds")
    removals = {row.get("clipId"): row for row in steps
                if row.get("op") == "remove-element"}
    if any(clip_id not in removals for clip_id in ids):
        raise PalmierError("Palmier removal is not revision-bound")
    rows = [removals[clip_id] for clip_id in ids]
    return {"kind": "elements-removed", "clipIds": ids,
            "elementIds": [row["elementId"] for row in rows],
            "mutationIds": [row["mutationId"] for row in rows]}


def move_binding(args: dict, steps: list[dict]) -> dict:
    """Bind exact move_clips args to revision movement work."""
    moves = args.get("moves")
    if not isinstance(moves, list) or not moves:
        raise PalmierError("Palmier move_clips requires explicit moves")
    planned = {row.get("clipId"): row for row in steps
               if row.get("op") == "move-element"}
    rows = []
    for move in moves:
        row = planned.get(move.get("clipId")) if isinstance(move, dict) else None
        expected = {"clipId": row.get("clipId"), "toFrame": row.get("toFrame"),
                    "toTrack": row.get("toTrack")} if isinstance(row, dict) else None
        if move != expected:
            raise PalmierError("Palmier move differs from the revision worklist")
        rows.append(row)
    return {"kind": "elements-moved", "moves": rows,
            "mutationIds": [row["mutationId"] for row in rows]}


def text_update_binding(args: dict, steps: list[dict]) -> dict:
    """Bind one copy-only update_text call to a native-text operation."""
    matches = [row for row in steps if row.get("op") == "native-text-update"
               and args == {"clipIds": [row.get("clipId")],
                            "content": row.get("content")}]
    if len(matches) != 1:
        raise PalmierError("Palmier text update differs from the revision worklist")
    row = matches[0]
    return {"kind": "native-text-updated", "elementId": row["elementId"],
            "clipId": row["clipId"], "content": row["content"],
            "mutationId": row["mutationId"]}


def observe_removed(state: dict, binding: dict,
                    before: dict, after: dict) -> None:
    """Verify exactly the bound clips disappeared and write tombstones."""
    old, new = clip_inventory(before), clip_inventory(after)
    removed, added = set(old) - set(new), set(new) - set(old)
    if removed != set(binding["clipIds"]) or added:
        raise PalmierError("Palmier revision removal changed unrelated clips")
    ledger = state["elementLedger"]
    elements = ledger.setdefault("elements", {})
    tombstones = ledger.setdefault("tombstones", {})
    pairs = zip(binding["elementIds"], binding["clipIds"], strict=True)
    for ident, clip_id in pairs:
        row = elements.pop(ident, None)
        if not isinstance(row, dict) or row.get("clipId") != clip_id:
            raise PalmierError("Palmier revision removal lost its ledger binding")
        tombstones[ident] = {**row, "status": "removed",
                             "version": row.get("version", 1) + 1,
                             "removedAt": now()}
    ledger["updatedAt"] = now()


def observe_moved(state: dict, binding: dict,
                  before: dict, after: dict) -> None:
    """Verify move-only structural change and advance element versions."""
    old, new = clip_inventory(before), clip_inventory(after)
    if set(old) != set(new):
        raise PalmierError("Palmier revision move added or removed clips")
    moved = {row["clipId"] for row in binding["moves"]}
    for clip_id in set(old) - moved:
        if clip_frames(old[clip_id]) != clip_frames(new[clip_id]):
            raise PalmierError("Palmier revision move shifted an unrelated clip")
    elements = state["elementLedger"]["elements"]
    for move in binding["moves"]:
        _observe_one_move(elements, move, new[move["clipId"]])


def _observe_one_move(elements: dict, move: dict, clip: dict) -> None:
    duration = move["endFrame"] - move["toFrame"]
    expected = (move["toFrame"], move["toFrame"] + duration)
    if clip_frames(clip) != expected or clip["_trackIndex"] != move["toTrack"]:
        raise PalmierError("Palmier revision move readback does not match")
    row = elements[move["elementId"]]
    row.update({"startFrame": expected[0], "endFrame": expected[1],
                "trackIndex": move["toTrack"],
                "version": row.get("version", 1) + 1,
                "updatedAt": now()})


def observe_text_update(state: dict, binding: dict,
                        before: dict, after: dict) -> None:
    """Verify exact copy update without structural or unrelated text drift."""
    old, new = clip_inventory(before), clip_inventory(after)
    if set(old) != set(new):
        raise PalmierError("Palmier native text update changed clip structure")
    clip_id = binding["clipId"]
    if new.get(clip_id, {}).get("textContent") != binding["content"]:
        raise PalmierError("Palmier native text update did not land exact copy")
    for ident in set(old) - {clip_id}:
        if old[ident].get("textContent") != new[ident].get("textContent"):
            raise PalmierError("Palmier native text update changed unrelated copy")
    row = state["elementLedger"]["elements"][binding["elementId"]]
    row.update({"textContent": binding["content"],
                "version": row.get("version", 1) + 1, "updatedAt": now()})
