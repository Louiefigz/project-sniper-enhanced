#!/usr/bin/env python3
"""Live, isolated Palmier canonical-timeline contract smoke test.

This test creates a uniquely named project, proves copy-before-edit behavior,
exports the candidate by explicit timeline id, restores the project that was
active before the test, then removes only the disposable project it created.
It is intentionally excluded from the offline unit-test suite.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from palmier.export import verify_export, wait_for_export  # noqa: E402
from palmier.executor import Executor  # noqa: E402
from palmier.mcp_client import PalmierClient, PalmierError  # noqa: E402
from palmier.translate_math import build_placements, punch_keyframes  # noqa: E402
from palmier.verify import _keyframe_map  # noqa: E402
from palmier.timeline_authority import (                    # noqa: E402
    _content_timeline, _semantic, compare_authority, fork_candidate,
    record_authority, snapshot)

PREFIX = "Sniper Canonical Contract Test"


def _active(info: dict) -> dict | None:
    rows = info.get("projects") or []
    found = next((row for row in rows if row.get("isActive")), None)
    return found or (info.get("active") if info.get("active", {}).get("path") else None)


def _active_row(client: PalmierClient) -> dict:
    found = _active(client.call_json("get_projects", {}))
    if not found or not found.get("id") or not found.get("path"):
        raise PalmierError("live smoke could not resolve its active project")
    return found


def _visual_clip(timeline: dict) -> dict:
    for track in timeline.get("tracks", []):
        for clip in track.get("clips", []):
            if clip.get("mediaType", "video") in ("video", "image"):
                return clip
    raise PalmierError("live smoke timeline has no visual clip")


def _first_diff(left, right, path="$") -> str:
    if type(left) is not type(right):
        return f"{path}: {type(left).__name__} != {type(right).__name__}"
    if isinstance(left, dict):
        if left.keys() != right.keys():
            return f"{path}: keys {sorted(left)} != {sorted(right)}"
        for key in left:
            found = _first_diff(left[key], right[key], f"{path}.{key}")
            if found:
                return found
        return ""
    if isinstance(left, list):
        if len(left) != len(right):
            return f"{path}: lengths {len(left)} != {len(right)}"
        for index, item in enumerate(left):
            found = _first_diff(item, right[index], f"{path}[{index}]")
            if found:
                return found
        return ""
    return "" if left == right else f"{path}: {left!r} != {right!r}"


def _motion_tracks() -> dict:
    placements = build_placements(
        [{"start": 0.0, "end": 2.0, "speed": 1.0}], 24)
    windows = [
        {"outStart": 0.0, "outEnd": 0.75, "ease": "smooth",
         "ramp": {"direction": "in", "ratePctPerS": 2.0}},
        {"outStart": 0.75, "outEnd": 1.75, "zoom": 1.2,
         "attackS": 0.25, "releaseS": 0.25,
         "centerX": 0.45, "centerY": 0.5},
    ]
    return punch_keyframes(windows, placements, (1.0, 0.5, 0.5), 24)[0]


def _prove_motion(client: PalmierClient, clip: dict) -> dict:
    expected = _motion_tracks()
    executor = Executor(client)
    executor.cut_clip_ids = [clip["id"]]
    for prop, rows in expected.items():
        executor._op_keyframes({
            "op": "keyframes", "clip": 0, "property": prop, "rows": rows})
    actual_clip = _visual_clip(client.call_json("get_timeline", {}))
    actual = _keyframe_map(actual_clip)
    if not actual:
        raise PalmierError("live motion smoke readback exposed no keyframes")
    for prop, rows in expected.items():
        stripped = [row[:-1] for row in rows]
        if actual.get(prop) not in (rows, stripped):
            raise PalmierError(f"live motion smoke {prop} readback differs")
    scale = max(row[1] for row in actual["scale"])
    position_x = [row[1] for row in actual["position"]]
    if scale <= 1.1 or max(position_x) - min(position_x) <= 0.01:
        raise PalmierError("live motion smoke has no material scale/pan")
    return {"properties": sorted(expected), "maxScale": scale,
            "positionRangeX": max(position_x) - min(position_x)}


def _restore(client: PalmierClient, prior: dict | None,
             prior_timeline: str | None, test_path: str | None) -> None:
    if prior and prior.get("path"):
        client.call_json("open_project", {"path": prior["path"]})
        if prior_timeline:
            client.call("set_active_timeline", {"timelineId": prior_timeline})
    elif test_path:
        client.call("close_project", {"path": test_path})
    if prior and test_path:
        client.call("close_project", {"path": test_path})


def _remove_disposable(path: str | None) -> bool:
    if not path or not os.path.exists(path):
        return False
    if not path.endswith(".palmier") or not os.path.basename(path).startswith(PREFIX):
        raise PalmierError(f"refusing to remove non-test Palmier path {path}")
    script = f'tell application "Finder" to delete POSIX file {json.dumps(path)}'
    subprocess.run(["osascript", "-e", script], check=True,
                   capture_output=True, text=True)
    return True


def run() -> dict:
    client = PalmierClient(timeout_s=180)
    client.handshake()
    prior = _active(client.call_json("get_projects", {}))
    prior_timeline = None
    if prior:
        prior_timeline = client.call_json("get_timeline", {}).get("id")
    name = f"{PREFIX} {int(time.time())}"
    test_path = None
    output = os.path.join(tempfile.gettempdir(), f"{name}.mp4")
    authority_dir = tempfile.mkdtemp(prefix="sniper-palmier-authority-")
    result: dict = {"name": name, "output": output}
    try:
        client.call_json("new_project", {
            "name": name, "fps": 24, "aspectRatio": "16:9", "quality": "720p"})
        created = _active_row(client)
        test_path = created["path"]
        imported = client.call_json("import_media", {
            "source": {"matte": {"hex": "#17324D"}}, "name": "Contract matte"})
        media_ref = imported.get("mediaRef")
        if not isinstance(media_ref, str):
            raise PalmierError(f"matte import returned no mediaRef: {imported}")
        client.call_json("add_clips", {"entries": [{
            "mediaRef": media_ref, "startFrame": 0, "endFrame": 48}]})
        client.call_json("add_texts", {"entries": [{
            "startFrame": 0, "endFrame": 48,
            "content": "Palmier is canonical"}]})
        baseline_timeline = client.call_json("get_timeline", {"captionDetail": True})
        baseline = snapshot(created["id"], baseline_timeline)
        authority = record_authority(
            authority_dir, baseline, "sniper-bootstrap")
        try:
            candidate = fork_candidate(
                client, authority_dir, authority, "AI candidate contract test")
        except PalmierError as exc:
            candidate_raw = client.call_json("get_timeline", {"captionDetail": True})
            before = _semantic(_content_timeline(baseline.timeline), root=True)
            after = _semantic(_content_timeline(candidate_raw), root=True)
            raise PalmierError(f"{exc}; first readback difference: "
                               f"{_first_diff(before, after)}") from exc
        candidate_timeline = client.call_json("get_timeline", {"captionDetail": True})
        clip = _visual_clip(candidate_timeline)
        result["motionReadback"] = _prove_motion(client, clip)
        client.call("set_clip_properties", {
            "clipIds": [clip["id"]], "opacity": 0.72})
        changed = snapshot(created["id"], client.call_json(
            "get_timeline", {"captionDetail": True}))
        if changed.semantic_fingerprint == baseline.semantic_fingerprint:
            raise PalmierError("candidate mutation did not change semantic content")
        inspection = client.call("inspect_timeline", {"startFrame": 24})
        client.call("set_active_timeline", {"timelineId": baseline.timeline_id})
        parent_now = snapshot(created["id"], client.call_json(
            "get_timeline", {"captionDetail": True}))
        if compare_authority(authority, parent_now) != "unchanged":
            raise PalmierError("candidate edit changed the canonical parent")
        client.call("set_active_timeline", {"timelineId": changed.timeline_id})
        try:
            os.unlink(output)
        except FileNotFoundError:
            pass
        client.call("export_project", {
            "timelineId": changed.timeline_id, "outputPath": output,
            "overwrite": False})
        stat = wait_for_export(output, None, 180, 0.5)
        probe = verify_export(output, 48, 24)
        result.update({
            "projectId": created["id"], "projectPath": test_path,
            "parentTimelineId": baseline.timeline_id,
            "candidateTimelineId": changed.timeline_id,
            "parentUnchanged": True, "semanticCopyVerified": True,
            "candidateMutationVerified": True,
            "inspectTextBytes": len(inspection.encode("utf-8")),
            "exportBytes": stat.st_size, "exportDuration": probe.duration_s,
        })
        return result
    finally:
        try:
            _restore(client, prior, prior_timeline, test_path)
            result["priorProjectRestored"] = True
        except Exception as exc:  # cleanup evidence must survive a test failure
            result["restoreError"] = str(exc)
        try:
            result["testProjectRemoved"] = _remove_disposable(test_path)
        except Exception as exc:
            result["cleanupError"] = str(exc)
        shutil.rmtree(authority_dir, ignore_errors=True)
        try:
            os.unlink(output)
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    try:
        print(json.dumps(run(), indent=2, sort_keys=True))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        raise
