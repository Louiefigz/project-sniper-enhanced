"""Pre/Post hook enforcement for staged Claude Desktop Palmier mutations."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

from palmier.candidate_receipt import load_candidate, save_candidate
from palmier.desktop_hook_authority import (read_bound_json,
                                            validate_authority)
from palmier.desktop_state import (append_journal, load_pointer, now,
                                   save_state)
from palmier.desktop_element_types import ElementObservation
from palmier.desktop_elements import bind_operation, observe_bound_operation
from palmier.desktop_revision_progress import (authorize_revision_binding,
                                                record_revision_binding)
from palmier.desktop_text import exact_text_addition
from palmier.mcp_client import PalmierClient, PalmierError
from palmier.timeline_authority import read_active

PREFIX = "mcp__palmier-pro__"
READ_TOOLS = {"get_projects", "get_timeline", "get_transcript", "get_media",
              "inspect_media", "inspect_timeline", "inspect_color", "detect_beats"}
CUT_TOOLS = {"move_clips", "remove_clips",
             "split_clips", "set_clip_properties", "ripple_delete_ranges",
             "remove_silence", "remove_words"}
VISUAL_TOOLS = {"import_media", "organize_media", "add_clips", "insert_clips",
                "move_clips", "remove_clips", "set_clip_properties",
                "set_keyframes", "add_texts", "update_text", "add_captions",
                "apply_color", "apply_effect", "apply_layout", "manage_tracks",
                "sync_clips", "denoise_audio"}
STAGE_TOOLS = {"cut": CUT_TOOLS, "visual": VISUAL_TOOLS,
               "repair": CUT_TOOLS | VISUAL_TOOLS,
               "revision": {"import_media", "add_clips", "move_clips",
                            "remove_clips", "add_texts", "update_text"}}

def _client() -> PalmierClient:
    client = PalmierClient(timeout_s=5.0)
    client.handshake()
    return client


def _operation_key(tool: str, args: dict, scope: str) -> str:
    blob = json.dumps([scope, tool, args], sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _operation_scope(state: dict) -> str:
    revision = state.get("revision")
    if isinstance(revision, dict) and isinstance(revision.get("revisionSetId"), str):
        return revision["revisionSetId"]
    operations = state.get("operations") or {}
    return str(operations.get("hash") or state.get("stage") or "unknown")


def _clip_ids(timeline: dict) -> set[str]:
    ids = set()
    for track in timeline.get("tracks") or []:
        if not isinstance(track, dict):
            continue
        for clip in track.get("clips") or []:
            if isinstance(clip, dict) and isinstance(clip.get("id"), str):
                ids.add(clip["id"])
            audio = clip.get("audio") if isinstance(clip, dict) else None
            if isinstance(audio, dict) and isinstance(audio.get("id"), str):
                ids.add(audio["id"])
        for group in track.get("captionGroups") or []:
            if not isinstance(group, dict):
                continue
            for clip in group.get("clips") or []:
                if isinstance(clip, dict) and isinstance(clip.get("id"), str):
                    ids.add(clip["id"])
                elif isinstance(clip, list) and clip \
                        and isinstance(clip[0], str):
                    ids.add(clip[0])
    return ids


def _referenced_clip_ids(args: dict) -> set[str]:
    result = set()
    for key in ("clipId", "clipIds"):
        value = args.get(key)
        if isinstance(value, str):
            result.add(value)
        elif isinstance(value, list):
            result.update(item for item in value if isinstance(item, str))
    for row in args.get("splits") or []:
        if isinstance(row, dict) and isinstance(row.get("clipId"), str):
            result.add(row["clipId"])
    for row in args.get("moves") or []:
        if isinstance(row, dict) and isinstance(row.get("clipId"), str):
            result.add(row["clipId"])
    return result


def _worklist_steps(state: dict, op: str) -> list[dict]:
    operations = read_bound_json(state["operations"]["path"])
    return [row for row in operations.get("steps") or []
            if isinstance(row, dict) and row.get("op") == op]


def _exact_settings(state: dict, op: str, args: dict,
                    ignored: set[str]) -> None:
    rows = _worklist_steps(state, op)
    expected = rows[0].get("settings") if len(rows) == 1 else None
    actual = {key: value for key, value in args.items() if key not in ignored}
    if not isinstance(expected, dict) or actual != expected:
        raise PalmierError(f"Palmier {op} settings differ from the bound worklist")


def _validate_args(tool: str, args: dict, state: dict, timeline: dict) -> None:
    if not isinstance(args, dict):
        raise PalmierError("Palmier tool input must be an object")
    if tool == "apply_color":
        _exact_settings(state, "native-color", args, {"clipIds"})
    if tool == "denoise_audio":
        _exact_settings(state, "native-denoise", args, {"clipIds"})
    if tool == "add_texts" and state.get("stage") in {"repair", "revision"}:
        exact_text_addition(state, args)
    if tool == "add_clips" and state.get("stage") == "cut" \
            and _clip_ids(timeline):
        raise PalmierError(
            "cut candidate already contains the source; use transcript/ripple "
            "deletions instead of adding a duplicate source clip")
    unknown = _referenced_clip_ids(args) - _clip_ids(timeline)
    if unknown:
        raise PalmierError("Palmier mutation references a clip absent from readback")
    total = timeline.get("totalFrames")
    if isinstance(total, int) and total > 0:
        frames = [args.get(key) for key in ("startFrame", "endFrame")]
        for row in args.get("entries") or []:
            if isinstance(row, dict):
                frames.extend((row.get("startFrame"), row.get("endFrame")))
        for row in args.get("moves") or []:
            if isinstance(row, dict):
                frames.append(row.get("toFrame"))
        if any(isinstance(value, (int, float)) and not isinstance(value, bool)
               and (value < 0 or value > total) for value in frames):
            raise PalmierError("Palmier mutation has an out-of-range timeline frame")


def _head(client: Any, state: dict) -> Any:
    found = read_active(client, state["projectId"])
    if found.timeline_id != state["candidate"]["timelineId"] \
            or found.fingerprint != state["expectedFingerprint"]:
        raise PalmierError("Palmier candidate changed outside verified Desktop ancestry")
    if found.coverage.get("complete") is not True:
        raise PalmierError("Palmier candidate readback is incomplete")
    return found


def authorize_pre(event: dict, repo: str,
                  client_factory: Callable[[], Any] = _client) -> None:
    """Validate one PreToolUse event and reserve its expected CAS head."""
    tool_name = str(event.get("tool_name") or "")
    if not tool_name.startswith(PREFIX):
        return
    tool = tool_name[len(PREFIX):]
    if tool in READ_TOOLS:
        return
    _path, state = load_pointer(repo)
    validate_authority(state)
    allowed = STAGE_TOOLS.get(str(state.get("stage")), set())
    if tool not in allowed:
        raise PalmierError(f"Palmier tool {tool} is not allowed in {state.get('stage')} stage")
    if state.get("pendingOperation"):
        raise PalmierError("a prior Palmier operation still needs PostToolUse readback")
    client = client_factory()
    found = _head(client, state)
    args = event.get("tool_input") or {}
    _validate_args(tool, args, state, found.timeline)
    binding = bind_operation(tool, args, state)
    authorize_revision_binding(state, binding)
    key = _operation_key(tool, args, _operation_scope(state))
    if key in state.get("verifiedOperationKeys", []):
        raise PalmierError("refusing to replay an already verified Palmier operation")
    state["pendingOperation"] = {
        "key": key, "tool": tool, "argsHash": hashlib.sha256(
            json.dumps(args, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "beforeFingerprint": found.fingerprint, "startedAt": now(),
    }
    if binding is not None:
        state["pendingOperation"]["binding"] = binding
    state["updatedAt"] = now()
    save_state(repo, state)


def _update_candidate(state: dict, found: Any) -> None:
    candidate = load_candidate(state["outDir"])
    if candidate is None:
        raise PalmierError("Desktop Palmier candidate receipt disappeared")
    candidate.update({"status": "edited", "fingerprint": found.fingerprint,
                      "semanticFingerprint": found.semantic_fingerprint,
                      "timeline": found.timeline,
                      "readbackCoverage": found.coverage})
    save_candidate(state["outDir"], candidate)


def _tool_failed(event: dict) -> bool:
    response = event.get("tool_response", event.get("tool_result"))
    if event.get("hook_event_name") == "PostToolUseFailure":
        return True
    if isinstance(response, dict):
        return response.get("isError") is True or response.get("error") is not None
    return False


def _observe_failed(state: dict, pending: dict, repo: str,
                    client_factory: Callable[[], Any]) -> None:
    found = read_active(client_factory(), state["projectId"])
    unchanged = found.timeline_id == state["candidate"]["timelineId"] \
        and found.fingerprint == pending["beforeFingerprint"]
    if not unchanged:
        state.update({"status": "paused", "updatedAt": now()})
        save_state(repo, state)
        raise PalmierError("failed Palmier tool may have partially mutated the candidate")
    state.update({"status": "active", "pendingOperation": None,
                  "updatedAt": now()})
    append_journal(state, {**pending, "event": "operation_failed", "at": now()})
    save_state(repo, state)


def observe_post(event: dict, repo: str,
                 client_factory: Callable[[], Any] = _client) -> None:
    """Fresh-read one completed mutation and advance the durable CAS head."""
    tool_name = str(event.get("tool_name") or "")
    if not tool_name.startswith(PREFIX):
        return
    tool = tool_name[len(PREFIX):]
    if tool in READ_TOOLS:
        return
    _path, state = load_pointer(repo)
    pending = state.get("pendingOperation")
    if not isinstance(pending, dict) or pending.get("tool") != tool:
        raise PalmierError("Palmier PostToolUse has no matching reserved operation")
    if _tool_failed(event):
        _observe_failed(state, pending, repo, client_factory)
        return
    client = client_factory()
    found = read_active(client, state["projectId"])
    if found.timeline_id != state["candidate"]["timelineId"]:
        raise PalmierError("Palmier switched timelines during a Desktop mutation")
    unchanged_ok = tool in {"import_media", "organize_media"}
    if found.fingerprint == pending["beforeFingerprint"] and not unchanged_ok:
        state.update({"status": "paused", "updatedAt": now()})
        save_state(repo, state)
        raise PalmierError(f"Palmier {tool} produced no observable timeline change")
    candidate = load_candidate(state["outDir"])
    if candidate is None or not isinstance(candidate.get("timeline"), dict):
        raise PalmierError("Desktop Palmier candidate has no prior readback")
    try:
        observe_bound_operation(ElementObservation(
            state, pending, candidate["timeline"], found.timeline, event))
    except PalmierError:
        state.update({"status": "paused", "updatedAt": now()})
        save_state(repo, state)
        raise
    state["expectedFingerprint"] = found.fingerprint
    state["candidate"]["fingerprint"] = found.fingerprint
    state["pendingOperation"] = None
    state["operationCount"] += 1
    record_revision_binding(state, pending.get("binding"))
    state.setdefault("verifiedOperationKeys", []).append(pending["key"])
    state["updatedAt"] = now()
    _update_candidate(state, found)
    append_journal(state, {**pending, "event": "operation_verified", "at": now(),
                           "afterFingerprint": found.fingerprint,
                           "timelineChanged": found.fingerprint
                           != pending["beforeFingerprint"]})
    save_state(repo, state)
