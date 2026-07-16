#!/usr/bin/env python3
"""Prove one skill-enabled headless Claude session can edit Palmier via MCP.

The smoke creates a matte-only disposable project, invokes Claude twice with a
stable session id, verifies direct MCP tool events and Palmier readback, then
restores the previously active project and trashes only the disposable project.
No user project metadata is included in either Claude prompt or allowed tool set.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from palmier.mcp_client import PalmierClient, PalmierError  # noqa: E402
from palmier.verify import _keyframe_map  # noqa: E402

PREFIX = "Sniper Headless Claude MCP Test"
MCP_CONFIG = json.dumps({"mcpServers": {"palmier-pro": {
    "type": "http", "url": "http://127.0.0.1:19789/mcp"}}})


def _active(info: dict) -> dict | None:
    """Return the active project row from get_projects."""
    rows = info.get("projects") or []
    found = next((row for row in rows if row.get("isActive")), None)
    return found or (info.get("active") if info.get("active", {}).get("path") else None)


def _active_row(client: PalmierClient) -> dict:
    """Require the active Palmier project identity."""
    found = _active(client.call_json("get_projects", {}))
    if not found or not found.get("id") or not found.get("path"):
        raise PalmierError("headless Claude smoke could not resolve its project")
    return found


def _events(raw: str) -> list[dict]:
    """Parse Claude stream-json rows."""
    rows: list[dict] = []
    for line in raw.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _tool_uses(events: list[dict]) -> list[dict]:
    """Extract assistant tool-use blocks from stream-json events."""
    uses: list[dict] = []
    for event in events:
        message = event.get("message")
        content = message.get("content", []) if isinstance(message, dict) else []
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                uses.append(block)
    return uses


def _claude_args(prompt: str, session_id: str, resume: bool) -> list[str]:
    """Build the narrowly allowlisted headless Claude invocation."""
    session = ["--resume", session_id] if resume else ["--session-id", session_id]
    allowed = ",".join([
        "Skill(producer)",
        "Read", "Glob", "Grep",
        "mcp__palmier-pro__get_timeline",
        "mcp__palmier-pro__add_texts",
        "mcp__palmier-pro__set_keyframes",
    ])
    return [
        "claude", "-p", prompt, *session,
        "--model", "sonnet", "--effort", "low",
        "--output-format", "stream-json", "--verbose",
        "--mcp-config", MCP_CONFIG, "--strict-mcp-config",
        "--permission-mode", "dontAsk", "--allowedTools", allowed,
    ]


def _run_claude(prompt: str, session_id: str, resume: bool) -> dict:
    """Run one Claude turn and return bounded stream evidence."""
    started = time.monotonic()
    result = subprocess.run(
        _claude_args(prompt, session_id, resume), check=False,
        capture_output=True, text=True, timeout=240)
    events = _events(result.stdout)
    uses = _tool_uses(events)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout[-2_000:]
        raise PalmierError(f"Claude exited {result.returncode}: {detail}")
    names = [str(row.get("name")) for row in uses]
    return {
        "elapsedS": round(time.monotonic() - started, 3),
        "toolNames": names,
        "skillInvoked": any(name == "Skill" and
                             row.get("input", {}).get("skill") == "producer"
                             for name, row in zip(names, uses)),
        "mcpToolCount": sum(name.startswith("mcp__palmier-pro__") for name in names),
        "sessionIds": sorted({str(row.get("session_id")) for row in events
                              if row.get("session_id")}),
        "result": next((row.get("result") for row in reversed(events)
                        if row.get("type") == "result"), None),
    }


def _matte_clip(timeline: dict) -> dict:
    """Return the first non-text video clip."""
    for track in timeline.get("tracks", []):
        for clip in track.get("clips", []):
            if clip.get("mediaType", "video") in ("video", "image"):
                return clip
    raise PalmierError("disposable timeline has no matte clip")


def _text_proof(timeline: dict) -> dict:
    """Prove Claude's first-turn text exists in Palmier readback."""
    matches: list[dict] = []
    for track in timeline.get("tracks", []):
        for clip in track.get("clips", []):
            serialized = json.dumps(clip, sort_keys=True)
            if "Headless MCP proof" in serialized:
                matches.append(clip)
    if len(matches) != 1:
        raise PalmierError(f"expected one proof text clip, found {len(matches)}")
    return {"textClipId": matches[0].get("id")}


def _motion_proof(timeline: dict) -> dict:
    """Prove Claude's resumed turn wrote material scale keyframes."""
    clip = _matte_clip(timeline)
    rows = _keyframe_map(clip).get("scale", [])
    if len(rows) < 3 or max(float(row[1]) for row in rows) < 1.07:
        raise PalmierError(f"scale keyframes missing or immaterial: {rows}")
    return {"clipId": clip.get("id"), "scaleKeyframes": rows}


def _restore(client: PalmierClient, prior: dict | None,
             prior_timeline: str | None, test_path: str | None) -> None:
    """Restore the prior project and close the disposable project."""
    if prior and prior.get("path"):
        client.call_json("open_project", {"path": prior["path"]})
        if prior_timeline:
            client.call("set_active_timeline", {"timelineId": prior_timeline})
    if test_path:
        client.call("close_project", {"path": test_path})


def _trash_disposable(path: str | None) -> bool:
    """Move only the uniquely prefixed Palmier test bundle to Trash."""
    if not path or not os.path.exists(path):
        return False
    if not path.endswith(".palmier") or not os.path.basename(path).startswith(PREFIX):
        raise PalmierError(f"refusing to remove non-test project {path}")
    script = f'tell application "Finder" to delete POSIX file {json.dumps(path)}'
    subprocess.run(["osascript", "-e", script], check=True,
                   capture_output=True, text=True)
    return True


def _assert_tool_proof(first: dict, second: dict) -> None:
    """Require the direct MCP calls from both Claude turns."""
    required = {"mcp__palmier-pro__get_timeline",
                "mcp__palmier-pro__add_texts"}
    if not required.issubset(set(first["toolNames"])):
        raise PalmierError(f"first turn lacked direct MCP calls: {first['toolNames']}")
    if "mcp__palmier-pro__set_keyframes" not in second["toolNames"]:
        raise PalmierError(f"resume lacked set_keyframes: {second['toolNames']}")


def _cleanup(client: PalmierClient, prior: dict | None,
             prior_timeline: str | None, test_path: str | None,
             result: dict) -> None:
    """Restore/cleanup while preserving evidence from either failure path."""
    try:
        _restore(client, prior, prior_timeline, test_path)
        result["priorProjectRestored"] = True
    except Exception as exc:
        result["restoreError"] = str(exc)
    try:
        result["testProjectRemoved"] = _trash_disposable(test_path)
    except Exception as exc:
        result["cleanupError"] = str(exc)


def run() -> dict:
    """Execute the isolated skill + MCP + resume proof."""
    client = PalmierClient(timeout_s=30)
    client.handshake()
    prior = _active(client.call_json("get_projects", {}))
    prior_timeline = client.call_json("get_timeline", {}).get("id") if prior else None
    name = f"{PREFIX} {int(time.time())}"
    test_path: str | None = None
    result: dict = {"ok": False, "name": name}
    try:
        client.call_json("new_project", {
            "name": name, "fps": 24, "aspectRatio": "16:9", "quality": "720p"})
        created = _active_row(client)
        test_path = created["path"]
        imported = client.call_json("import_media", {
            "source": {"matte": {"hex": "#17324D"}}, "name": "Disposable matte"})
        client.call_json("add_clips", {"entries": [{
            "mediaRef": imported["mediaRef"], "startFrame": 0, "endFrame": 48}]})
        session_id = str(uuid.uuid4())
        first = _run_claude(
            "Use the producer skill. This is a disposable 48-frame test timeline. "
            "Call get_timeline, then add exactly one text entry reading "
            "'Headless MCP proof' from frame 0 through frame 48. Do not inspect "
            "projects, paths, files, or call any other mutation tool.",
            session_id, False)
        after_text = client.call_json("get_timeline", {"captionDetail": True})
        text = _text_proof(after_text)
        second = _run_claude(
            "Resume the same disposable build. Call get_timeline. On the matte "
            "video clip, set scale keyframes at frames 0, 12, and 36 to 1.0, "
            "1.08, and 1.0 with smooth easing. Call no other mutation tool.",
            session_id, True)
        after_motion = client.call_json("get_timeline", {"captionDetail": True})
        motion = _motion_proof(after_motion)
        _assert_tool_proof(first, second)
        result.update({
            "ok": True, "sessionId": session_id,
            "projectId": created["id"], "timelineId": after_motion.get("id"),
            "firstTurn": first, "resumeTurn": second,
            "textReadback": text, "motionReadback": motion,
        })
        return result
    finally:
        _cleanup(client, prior, prior_timeline, test_path, result)


if __name__ == "__main__":
    try:
        print(json.dumps(run(), indent=2, sort_keys=True))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        raise
