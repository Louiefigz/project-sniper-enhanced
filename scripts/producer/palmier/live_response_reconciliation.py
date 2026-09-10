"""Fresh readback for non-journal mutations whose response was withheld."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Callable

from palmier.desktop_recovery import recover_media_ref
from palmier.live_acceptance_project_safety import project_surface
from palmier.mcp_client import PalmierError


@dataclass(frozen=True)
class ReconciliationRequest:
    """One applied mutation whose transport response was intentionally lost."""

    client: Any
    tool: str
    args: dict
    disposition: str


def _result(value: dict, proof: dict) -> tuple[str, dict]:
    return json.dumps(value), proof


def _projects(request: ReconciliationRequest) -> list[dict]:
    value = request.client.call_json("get_projects", {})
    project_surface(value)
    rows = value.get("projects") if isinstance(value, dict) else None
    if not isinstance(rows, list):
        raise PalmierError("response-loss project readback is malformed")
    return [row for row in rows if isinstance(row, dict)]


def _new_project(request: ReconciliationRequest) -> tuple[str, dict]:
    name = request.args.get("name")
    rows = [row for row in _projects(request)
            if row.get("name") == name and row.get("isActive") is True]
    if len(rows) != 1 or not isinstance(rows[0].get("id"), str):
        raise PalmierError("response-loss new_project did not apply uniquely")
    return _result(rows[0], {
        "kind": "new-project-readback", "projectId": rows[0]["id"],
        "path": rows[0].get("path"),
    })


def _open_project(request: ReconciliationRequest) -> tuple[str, dict]:
    path = os.path.realpath(str(request.args.get("path")))
    active = [row for row in _projects(request)
              if row.get("isActive") is True]
    if len(active) != 1 or os.path.realpath(
            str(active[0].get("path"))) != path:
        raise PalmierError("response-loss open_project did not become active")
    return _result(active[0], {
        "kind": "opened-project-readback",
        "projectId": active[0].get("id"), "path": path,
    })


def _close_project(request: ReconciliationRequest) -> tuple[str, dict]:
    path = os.path.realpath(str(request.args.get("path")))
    if any(row.get("isOpen") is True and os.path.realpath(
            str(row.get("path"))) == path for row in _projects(request)):
        raise PalmierError("response-loss close_project target remains open")
    return _result({"closed": True}, {
        "kind": "closed-project-readback", "path": path,
    })


def _timeline(request: ReconciliationRequest) -> dict:
    value = request.client.call_json("get_timeline", {})
    if not isinstance(value, dict) or not isinstance(value.get("id"), str):
        raise PalmierError("response-loss timeline readback is malformed")
    return value


def _active_timeline(request: ReconciliationRequest) -> tuple[str, dict]:
    timeline = _timeline(request)
    expected = request.args.get("timelineId")
    if timeline["id"] != expected:
        raise PalmierError(
            "response-loss set_active_timeline did not apply")
    return _result(timeline, {
        "kind": "active-timeline-readback", "timelineId": expected,
    })


def _create_timeline(request: ReconciliationRequest) -> tuple[str, dict]:
    timeline = _timeline(request)
    if timeline["id"] == request.args.get("from") \
            or timeline.get("name") != request.args.get("name"):
        raise PalmierError("response-loss create_timeline did not apply")
    return _result({"timelineId": timeline["id"]}, {
        "kind": "created-timeline-readback",
        "timelineId": timeline["id"],
        "sourceTimelineId": request.args.get("from"),
    })


def _import_media(request: ReconciliationRequest) -> tuple[str, dict]:
    source = request.args.get("source")
    path = source.get("path") if isinstance(source, dict) else None
    if not isinstance(path, str):
        raise PalmierError(
            "response-loss import recovery requires a path source")
    binding = {
        "path": path, "importName": request.args.get("name"),
    }
    media_ref = recover_media_ref(request.client, binding)
    return _result({"mediaRef": media_ref}, {
        "kind": "imported-media-readback", "mediaRef": media_ref,
        "path": os.path.realpath(path),
    })


def _clip_rows(timeline: dict) -> list[dict]:
    return [
        clip for track in timeline.get("tracks") or []
        if isinstance(track, dict)
        for clip in track.get("clips") or [] if isinstance(clip, dict)
    ]


def _add_clips(request: ReconciliationRequest) -> tuple[str, dict]:
    clips = _clip_rows(_timeline(request))
    entries = request.args.get("entries")
    if not isinstance(entries, list) or not entries:
        raise PalmierError("response-loss add_clips has no entries")
    def matches(entry: dict) -> int:
        expected = [entry.get("startFrame"), entry.get("endFrame")]
        return sum(
            row.get("mediaRef") == entry.get("mediaRef")
            and row.get("frames") == expected for row in clips)
    if any(not isinstance(entry, dict) or matches(entry) != 1
           for entry in entries):
        raise PalmierError("response-loss add_clips did not apply uniquely")
    return _result({"reconciled": True}, {
        "kind": "added-clips-readback", "entryCount": len(entries),
        "clipIds": sorted(
            row["id"] for row in clips if isinstance(row.get("id"), str)),
    })


def _set_clip_properties(
        request: ReconciliationRequest) -> tuple[str, dict]:
    clips = {row.get("id"): row for row in _clip_rows(_timeline(request))}
    ids = request.args.get("clipIds")
    expected = {
        key: value for key, value in request.args.items()
        if key != "clipIds"
    }
    valid = isinstance(ids, list) and bool(ids) and all(
        ident in clips and all(clips[ident].get(key) == value
                               for key, value in expected.items())
        for ident in ids)
    if not valid:
        raise PalmierError(
            "response-loss set_clip_properties readback differs")
    return _result({"reconciled": True}, {
        "kind": "clip-properties-readback",
        "clipIds": ids, "properties": expected,
    })


def _export_project(request: ReconciliationRequest) -> tuple[str, dict]:
    path = request.args.get("outputPath")
    if not isinstance(path, str) or os.path.islink(path):
        raise PalmierError("response-loss export path is unsafe")
    while not os.path.isfile(path) or os.path.getsize(path) <= 0:
        time.sleep(min(0.25, request.client.deadline.remaining()))
    return _result({"reconciled": True}, {
        "kind": "export-started-readback", "path": path,
        "observedBytes": os.path.getsize(path),
        "timelineId": request.args.get("timelineId"),
    })


def _add_captions(request: ReconciliationRequest) -> tuple[str, dict]:
    while True:
        timeline = _timeline(request)
        counts = [
            group.get("clipCount") for track in timeline.get("tracks") or []
            if isinstance(track, dict)
            for group in track.get("captionGroups") or []
            if isinstance(group, dict)
        ]
        if any(isinstance(count, int) and count > 0 for count in counts):
            return _result({"reconciled": True}, {
                "kind": "native-captions-readback",
                "captionGroupCounts": counts,
            })
        time.sleep(min(0.25, request.client.deadline.remaining()))


_HANDLERS: dict[str, Callable[[ReconciliationRequest], tuple[str, dict]]] = {
    "new_project": _new_project,
    "open_project": _open_project,
    "close_project": _close_project,
    "set_active_timeline": _active_timeline,
    "create_timeline": _create_timeline,
    "import_media": _import_media,
    "add_clips": _add_clips,
    "set_clip_properties": _set_clip_properties,
    "export_project": _export_project,
    "add_captions": _add_captions,
}


def reconcile_response_loss(
        client: Any, tool: str, args: dict,
        disposition: str) -> tuple[str, dict]:
    """Reobserve an applied non-journal mutation without replaying it."""
    handler = _HANDLERS.get(tool)
    if handler is None:
        raise PalmierError(
            f"response-loss cohort has no {tool!r} reconciliation contract")
    return handler(ReconciliationRequest(
        client, tool, args, disposition))
