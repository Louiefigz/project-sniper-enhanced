"""Bind Desktop Palmier media/clip mutations to stable plan element ids."""
from __future__ import annotations
import json
import os
from fingerprints import file_sha256
from ingest_probe import probe_media
from palmier.desktop_element_types import (ElementObservation,
                                           RecoveryObservation)
from palmier.desktop_ledger import clip_frames, clip_inventory
from palmier.desktop_scene_readback import assert_scene_replacement_readback
from palmier.desktop_state import now, read_record
from palmier.desktop_text import observe_texts, text_add_binding
from palmier.mcp_client import PalmierError
_RESOURCE_OPS = {"import", "native-broll", "native-music"}
def _operations(state: dict) -> list[dict]:
    value = read_record(state["operations"]["path"], "operation manifest")
    rows = value.get("steps")
    if not isinstance(rows, list):
        raise PalmierError("Desktop Palmier operation manifest has no steps")
    return [row for row in rows if isinstance(row, dict)]

def _import_path(args: dict) -> str | None:
    source = args.get("source")
    value = source.get("path") if isinstance(source, dict) else args.get("path")
    return os.path.realpath(value) if isinstance(value, str) else None

def _resource_binding(args: dict, steps: list[dict]) -> dict:
    path = _import_path(args)
    matches = [row for row in steps if row.get("op") in _RESOURCE_OPS
               and isinstance(row.get("path"), str)
               and os.path.realpath(row["path"]) == path]
    if any(row.get("importName") for row in matches):
        matches = [row for row in matches
                   if row.get("importName") == args.get("name")]
    if len(matches) != 1 or not isinstance(matches[0].get("fileHash"), str):
        raise PalmierError("Palmier import is not a unique bound worklist resource")
    row = matches[0]
    if not os.path.isfile(row["path"]) or file_sha256(row["path"]) != row["fileHash"]:
        raise PalmierError("Palmier import bytes changed after worklist binding")
    return {"kind": "resource", "path": row["path"],
            "fileHash": row["fileHash"], "mediaKey": row.get("key"),
            "elementId": row.get("elementId"),
            "importName": row.get("importName") or args.get("name"),
            "mutationId": row.get("mutationId")}


def _placements(steps: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for step in steps:
        if step.get("op") == "overlays":
            rows.extend({**entry, "lane": "graphics", "op": "add-overlay"}
                        for entry in step.get("entries") or [])
        elif step.get("op") == "add-overlay":
            rows.append(step)
        elif step.get("op") == "replace-overlay":
            rows.append(step)
        elif step.get("op") in {"native-broll", "native-music"}:
            rows.append(step)
    return rows


def _media_ref(state: dict, row: dict) -> str | None:
    digest = row.get("assetHash") or row.get("fileHash")
    media = (state.get("mediaLedger") or {}).get(digest)
    return media.get("mediaRef") if isinstance(media, dict) else None


def _entry_binding(entry: dict, placements: list[dict], state: dict) -> dict:
    matches = []
    for row in placements:
        expected_ref = _media_ref(state, row)
        same = (expected_ref == entry.get("mediaRef")
                and row.get("startFrame") == entry.get("startFrame")
                and row.get("endFrame") == entry.get("endFrame"))
        if row.get("op") == "replace-overlay":
            same = same and row.get("trackIndex") == entry.get("trackIndex")
        if same:
            matches.append(row)
    if len(matches) != 1:
        raise PalmierError(
            "Palmier add_clips entry is not uniquely bound to the worklist")
    row = matches[0]
    ident = row.get("elementId")
    digest = row.get("assetHash") or row.get("fileHash")
    if not isinstance(ident, str) or not isinstance(digest, str):
        raise PalmierError("Palmier placement has no stable element/asset identity")
    return {"elementId": ident, "assetHash": digest,
            "assetPath": row.get("assetPath") or row.get("path"),
            "mediaRef": entry["mediaRef"],
            "startFrame": row["startFrame"], "endFrame": row["endFrame"],
            "trackIndex": row.get("trackIndex"),
            "transform": row.get("transform"),
            "oldClipId": row.get("oldClipId"),
            "oldMediaRef": row.get("oldMediaRef"), "lane": row.get("lane"),
            "sceneBindingId": row.get("sceneBindingId"),
            "mutationId": row.get("mutationId"),
            "sourceAnchor": row.get("sourceAnchor")}


def _add_binding(args: dict, steps: list[dict], state: dict) -> dict:
    entries = args.get("entries")
    if not isinstance(entries, list) or not entries \
            or any(not isinstance(row, dict) for row in entries):
        raise PalmierError("Palmier add_clips requires explicit bound entries")
    placements = _placements(steps)
    bound = [_entry_binding(row, placements, state) for row in entries]
    ids = [row["elementId"] for row in bound]
    if len(ids) != len(set(ids)):
        raise PalmierError("Palmier add_clips repeats one worklist element")
    return {"kind": "elements-added", "elements": bound,
            "mutationIds": [row["mutationId"] for row in bound
                            if isinstance(row.get("mutationId"), str)]}


def _remove_binding(args: dict, steps: list[dict], state: dict) -> dict:
    ids = args.get("clipIds")
    if not isinstance(ids, list) or not ids:
        raise PalmierError("Palmier remove_clips requires explicit clipIds")
    replacements = {row.get("oldClipId"): row.get("elementId")
                    for row in steps if row.get("op") == "replace-overlay"}
    if state.get("stage") == "revision":
        from palmier.desktop_revision_elements import remove_binding
        return remove_binding(args, steps)
    if any(clip_id not in replacements for clip_id in ids):
        raise PalmierError("Palmier removal is not a bound replacement cleanup")
    return {"kind": "replacement-cleanup", "clipIds": ids,
            "elementIds": [replacements[clip_id] for clip_id in ids]}


def bind_operation(tool: str, args: dict, state: dict) -> dict | None:
    """Return immutable worklist identity for a media/structural mutation."""
    steps = _operations(state)
    if tool == "import_media":
        return _resource_binding(args, steps)
    if tool == "add_clips" and state.get("stage") in {
            "visual", "repair", "revision"}:
        return _add_binding(args, steps, state)
    if tool == "remove_clips" and state.get("stage") in {"repair", "revision"}:
        return _remove_binding(args, steps, state)
    if tool == "move_clips" and state.get("stage") == "revision":
        from palmier.desktop_revision_elements import move_binding
        return move_binding(args, steps)
    if tool == "update_text" and state.get("stage") == "revision":
        from palmier.desktop_revision_elements import text_update_binding
        return text_update_binding(args, steps)
    if tool == "add_texts" and state.get("stage") in {"repair", "revision"}:
        return text_add_binding(args, state)
    return None


def _response_value(event: dict) -> object:
    value = event.get("tool_response", event.get("tool_result"))
    content = value.get("content") if isinstance(value, dict) else value
    if isinstance(content, list):
        texts = [row.get("text") for row in content
                 if isinstance(row, dict) and isinstance(row.get("text"), str)]
        value = "".join(texts)
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _media_ref_from_response(event: dict) -> str | None:
    value = _response_value(event)
    if isinstance(value, dict):
        direct = value.get("mediaRef") or value.get("id")
        if isinstance(direct, str):
            return direct
        result = value.get("result")
        if isinstance(result, dict):
            return _media_ref_from_response({"tool_response": result})
    return None


def _observe_resource(state: dict, binding: dict, event: dict) -> None:
    media_ref = _media_ref_from_response(event)
    if not isinstance(media_ref, str):
        raise PalmierError("Palmier import response exposed no mediaRef")
    state.setdefault("mediaLedger", {})[binding["fileHash"]] = {
        "mediaRef": media_ref, "path": binding["path"],
        "mediaKey": binding.get("mediaKey"), "updatedAt": now(),
    }


def _matching_added(after: dict[str, dict], added: set[str], row: dict) -> list[dict]:
    return [clip for clip_id, clip in after.items() if clip_id in added
            and clip.get("mediaRef") == row["mediaRef"]
            and clip_frames(clip) == (row["startFrame"], row["endFrame"])
            and (row.get("trackIndex") is None
                 or clip["_trackIndex"] == row["trackIndex"])]


def _observe_added(state: dict, binding: dict,
                   before: dict, after: dict) -> None:
    old, new = clip_inventory(before), clip_inventory(after)
    removed, added = set(old) - set(new), set(new) - set(old)
    allowed_removed = {row["oldClipId"] for row in binding["elements"]
                       if isinstance(row.get("oldClipId"), str)}
    if removed - allowed_removed:
        raise PalmierError("Palmier placement removed an unrelated clip")
    assert_scene_replacement_readback(binding, old, new)
    ledger = state.setdefault("elementLedger", {
        "schemaVersion": 2, "elements": {}, "tombstones": {}})
    elements = ledger.setdefault("elements", {})
    matched_ids = set()
    for row in binding["elements"]:
        matches = _matching_added(new, added, row)
        if len(matches) != 1:
            raise PalmierError("Palmier placement readback is ambiguous")
        clip = matches[0]
        matched_ids.add(clip["id"])
        previous = elements.get(row["elementId"])
        version = previous.get("version", 0) + 1 \
            if isinstance(previous, dict) else 1
        generation = previous.get("generation", 1) \
            if isinstance(previous, dict) else 1
        record = {"status": "current", "lane": row.get("lane"),
                  "clipId": clip["id"], "mediaRef": row["mediaRef"],
                  "assetHash": row["assetHash"], "assetPath": row.get("assetPath"),
                  "startFrame": row["startFrame"], "endFrame": row["endFrame"],
                  "trackIndex": clip["_trackIndex"],
                  "transform": clip.get("transform", row.get("transform")),
                  "sourceAnchor": row.get("sourceAnchor"),
                  "version": version, "generation": generation,
                  "updatedAt": now()}
        old_id = row.get("oldClipId")
        if isinstance(old_id, str) and old_id not in removed:
            record.update({"status": "cleanup-required", "clipId": old_id,
                           "replacement": {"oldClipId": old_id,
                                           "newClipId": clip["id"]}})
        elements[row["elementId"]] = record
    if added - matched_ids:
        raise PalmierError("Palmier placement added an unrelated clip")
    ledger["updatedAt"] = now()


def _observe_cleanup(state: dict, binding: dict, after: dict) -> None:
    clips = clip_inventory(after)
    elements = (state.get("elementLedger") or {}).get("elements") or {}
    for ident, old_id in zip(binding["elementIds"], binding["clipIds"], strict=True):
        row = elements.get(ident)
        replacement = row.get("replacement") if isinstance(row, dict) else None
        new_id = replacement.get("newClipId") if isinstance(replacement, dict) else None
        if old_id in clips or not isinstance(new_id, str) or new_id not in clips:
            raise PalmierError("Palmier replacement cleanup did not converge")
        clip = clips[new_id]
        row.update({"status": "current", "clipId": new_id,
                    "trackIndex": clip["_trackIndex"], "replacement": None,
                    "updatedAt": now()})
    state["elementLedger"]["updatedAt"] = now()


def observe_bound_operation(observation: ElementObservation) -> None:
    """Advance media/element ledgers from one verified mutation readback."""
    state, pending = observation.state, observation.pending
    before, after, event = (observation.before, observation.after,
                            observation.event)
    binding = pending.get("binding")
    if not isinstance(binding, dict):
        return
    kind = binding.get("kind")
    if kind == "resource":
        _observe_resource(state, binding, event)
    elif kind == "elements-added":
        _observe_added(state, binding, before, after)
    elif kind == "replacement-cleanup":
        _observe_cleanup(state, binding, after)
    elif kind == "native-texts-added":
        observe_texts(state, binding, before, after)
    elif kind == "elements-removed":
        from palmier.desktop_revision_elements import observe_removed
        observe_removed(state, binding, before, after)
    elif kind == "elements-moved":
        from palmier.desktop_revision_elements import observe_moved
        observe_moved(state, binding, before, after)
    elif kind == "native-text-updated":
        from palmier.desktop_revision_elements import observe_text_update
        observe_text_update(state, binding, before, after)


def recover_bound_operation(recovery: RecoveryObservation) -> None:
    """Rebuild a missed PostToolUse ledger receipt from exact live readback."""
    state, pending = recovery.state, recovery.pending
    binding = pending.get("binding")
    if not isinstance(binding, dict):
        return
    if binding.get("kind") == "resource":
        from palmier.desktop_recovery import recover_media_ref
        media_ref = recover_media_ref(
            recovery.client, binding, recovery.media_ref, probe_media)
        _observe_resource(
            state, binding, {"tool_response": {"mediaRef": media_ref}})
        return
    observe_bound_operation(ElementObservation(
        state, pending, recovery.before, recovery.after, {}))
