#!/usr/bin/env python3
"""Run the staged Claude Code Desktop -> Palmier first-60s acceptance proof."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "producer"))

from palmier.desktop_authority import begin  # noqa: E402
from palmier.desktop_state import DesktopStageInput, load_state  # noqa: E402
from palmier.mcp_client import PalmierClient, PalmierError  # noqa: E402

DEFAULT_OUT = ROOT / "artifacts" / "palmier-live-acceptance-20260715" / "producer"
OUT = Path(os.environ.get("SNIPER_FIRST60_OUT", str(DEFAULT_OUT))).resolve()
RUNTIME = OUT / ".live-first60-runtime.json"
SOURCE_VALUE = os.environ.get("SNIPER_FIRST60_SOURCE", "").strip()
MANIFEST = OUT.parent / "source" / "asset_manifest.json"
CUT_PLAN = OUT / "cut_plan.json"
EDIT_PLAN = OUT / "edit_plan.json"
TRANSCRIPTS = OUT.parent / "source"
PREFIX = os.environ.get("SNIPER_FIRST60_PREFIX",
                        "Sniper Desktop Palmier First60 Acceptance")
MCP_CONFIG = json.dumps({"mcpServers": {"palmier-pro": {
    "type": "http", "url": "http://127.0.0.1:19789/mcp"}}})

READ_TOOLS = ["get_projects", "get_timeline", "get_transcript", "get_media",
              "inspect_media", "inspect_timeline", "inspect_color", "detect_beats"]
CUT_TOOLS = ["move_clips", "remove_clips", "split_clips", "set_clip_properties",
             "ripple_delete_ranges", "remove_silence", "remove_words"]
VISUAL_TOOLS = ["import_media", "organize_media", "add_clips", "insert_clips",
                "move_clips", "remove_clips", "set_clip_properties", "set_keyframes",
                "add_texts", "update_text", "add_captions", "apply_color",
                "apply_effect", "apply_layout", "manage_tracks", "sync_clips",
                "denoise_audio"]


def _write(value: dict) -> None:
    RUNTIME.parent.mkdir(parents=True, exist_ok=True)
    temporary = RUNTIME.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, RUNTIME)


def _read() -> dict:
    return json.loads(RUNTIME.read_text())


def _active(client: PalmierClient) -> dict | None:
    payload = client.call_json("get_projects", {})
    rows = payload.get("projects") or []
    return next((row for row in rows if row.get("isActive")), None)


def _client() -> PalmierClient:
    client = PalmierClient(timeout_s=180)
    client.handshake()
    return client


def _restore(client: PalmierClient, state: dict) -> None:
    prior = state.get("prior") or {}
    if prior.get("path"):
        client.call_json("open_project", {"path": prior["path"]})
        if state.get("priorTimelineId"):
            client.call("set_active_timeline", {"timelineId": state["priorTimelineId"]})
    if state.get("testPath"):
        client.call("close_project", {"path": state["testPath"]})


def setup() -> dict:
    if not SOURCE_VALUE:
        raise PalmierError("SNIPER_FIRST60_SOURCE must name the acceptance source")
    source = Path(SOURCE_VALUE).expanduser().resolve()
    client = _client()
    prior = _active(client)
    prior_timeline = client.call_json("get_timeline", {}).get("id") if prior else None
    state = {"ok": False, "prior": prior, "priorTimelineId": prior_timeline,
             "sessionId": str(uuid.uuid4()), "turns": {}}
    name = f"{PREFIX} {int(time.time())}"
    try:
        client.call_json("new_project", {
            "name": name, "fps": 24, "aspectRatio": "16:9", "quality": "1080p"})
        created = _active(client)
        if not created or not created.get("path"):
            raise PalmierError("disposable Palmier project was not activated")
        state.update({"name": name, "testPath": created["path"],
                      "projectId": created["id"]})
        _write(state)
        imported = client.call_json("import_media", {"source": {"path": str(source)}})
        media_ref = imported.get("mediaRef")
        if not isinstance(media_ref, str):
            raise PalmierError(f"source import returned no mediaRef: {imported}")
        client.wait_media(media_ref)
        client.call_json("add_clips", {"entries": [{
            "mediaRef": media_ref, "startFrame": 0, "source": [0.0, 60.061]}]})
        bootstrap = client.call_json("get_timeline", {"captionDetail": True})
        inputs = DesktopStageInput(str(ROOT), str(OUT), str(CUT_PLAN),
                                   str(MANIFEST), "cut", str(TRANSCRIPTS))
        authority = begin(client, inputs, hours=3.0)
        state.update({"ok": True, "mediaRef": media_ref,
                      "bootstrapFrames": bootstrap.get("totalFrames"),
                      "bootstrapTimelineId": bootstrap.get("id"),
                      "candidateTimelineId": authority["candidate"]["timelineId"]})
        _write(state)
        return state
    except Exception as exc:
        state["error"] = str(exc)
        _write(state)
        _restore(client, state)
        raise


def restore() -> dict:
    state = _read()
    _restore(_client(), state)
    state["restoredAt"] = time.time()
    _write(state)
    return state


def open_candidate() -> dict:
    state = _read()
    client = _client()
    client.call_json("open_project", {"path": state["testPath"]})
    authority = load_state(str(OUT))
    client.call("set_active_timeline", {"timelineId": authority["candidate"]["timelineId"]})
    return client.call_json("get_timeline", {"captionDetail": True})


def _prompt(phase: str) -> str:
    operations = OUT / ".palmier-desktop-operations.json"
    common = (
        f"Use the producer skill. This is the governed disposable first-60-second "
        f"acceptance build. Read {operations}, {EDIT_PLAN}, {CUT_PLAN}, and {MANIFEST}. "
        "Never invent media, copy, timing, or paths. Use get_timeline before mutation "
        "and after every risky or dependency-producing batch. Stop on uncertainty. "
    )
    if phase == "plan":
        return common + (
            "Do not mutate Palmier. Call get_timeline exactly once to bind the checklist "
            "to the visible candidate and exercise the project hooks. Verify the cut math, "
            "operation order, measured face "
            "recompose, graphic variety, typography/contrast, transition rationale, "
            "color, captions, music ducking, and final QC obligations. Return a compact "
            "execution checklist ending with CUT_READY.")
    if phase == "cut":
        return common + (
            "The visible 1441-frame single source clip is the expected pre-cut bootstrap, "
            "not stale state. Palmier timeline FPS is authoritatively 24; 23.976 is only "
            "the source media cadence. Execute only the bound native-cut-spine. Preserve "
            "the listed source ranges "
            "by one ripple_delete_ranges call using descending frame ranges on the real "
            "base track at 24 FPS: [1405,1441], [855,871], [400,410], [0,328]. "
            "Do not add a duplicate source clip. Verify "
            "the exact targetTotalFrames, contiguous seams, source order, and linked audio.")
    if phase == "visual":
        return common + (
            "capability.approved=false is expected before rendered QC approval; it is not "
            "a stop condition. Stop only for a blocksSync finding or omission; this bound "
            "worklist has neither. Map clip indices 0-2 to chronological base clips. "
            "Execute every supported visual-stage worklist step in dependency order, "
            "incrementally. Import each exact prepared asset, wait/read it back, then place "
            "it on the specified timing and layer. Treat the operation manifest as exact: "
            "do not assume an overlay count, add unbound transitions, or invent a music "
            "bed. Apply only the measured recompose, native text/captions, color, audio, "
            "and motion operations that are actually bound. Do not silently omit or replay "
            "an operation.")
    if phase == "qa":
        return common + (
            "Start with get_timeline and audit the visible candidate against every bound "
            "worklist and quality-contract line. Verify exact clip timing, graphic timing "
            "and layer order, information-form variety, cream/dark chassis rhythm, active "
            "presenter holes, native captions, color, and audio. Apply only a genuinely "
            "missing or incorrect supported operation already present in the worklist; "
            "never invent copy, media, cards, transitions, or music. Read back after any "
            "repair and report unresolved limitations.")
    if phase == "repair":
        return common + (
            "Execute only two bound repairs: native-audio-master and caption contrast. "
            "Call get_timeline; import the exact normalized hum-fixed mix path and place "
            "one audio clip from frame 0 through 1051. Mute every pre-existing audio clip "
            "with volume 0 so the newly imported master is the sole audible bus. Restyle "
            "the existing captionGroupId with the exact bound caption settings, including "
            "the #111827 backgroundColor contrast plate; do not regenerate or retime "
            "captions. Do not touch video, graphics, title, color, or motion. Read back the "
            "audio tracks and captions; verify one full-length audible master, every prior "
            "audio bus muted, and the bound caption style present.")
    if phase == "visual_repair":
        return common + (
            "Execute only the render-truth visual repairs. Apply the bound native-color "
            "reset to all three chronological base video clips. Replace only graphics 6 "
            "and 7 with their newly bound assets at their exact existing frames/tracks, "
            "preserving every other graphic and all audio/captions/motion. The corrected "
            "product-name caption uses the neutral label Project Sniper. Read back, verify no overlaps/gaps, and "
            "confirm the two old misspelled clips are gone and color reset is editable.")
    return common + (
        "Do not create tasks or re-plan. The controller has now fixed desktop_hook._clip_ids "
        "to recognize captionDetail array rows and the regression suite passed; your prior "
        "caption-update block is stale, so retry the still-missing corrections. Start with "
        "get_timeline. The first readback found "
        "editable caption errors; resolve current clip IDs by their text and apply these "
        "exact replacements: 'you write a content for clients,' -> 'You run content for "
        "clients,'; 'and this is gonna be' -> 'And this is going to be'; 'know,' -> "
        "'even'; 'even the prompts can' -> 'the prompts can'; 'build content systems for "
        "video 1st brands.' -> 'build content systems for video first brands.'; "
        "replace the bound product-name caption with 'I'm building the platform,'; "
        "'And this angle generated' -> "
        "'And this angle generator'. Restyle the captionGroupId to Inter 52 bold, text "
        "#F7F8FA, highlight #FFD166, centered at y=.88. Restyle the native title to Inter "
        "54 bold, #F7F8FA on #111827 at its existing safe placement. Then audit the live "
        "candidate against every bound worklist and quality-contract line using readback. "
        "Apply only genuinely missing or incorrect supported operations; never replay "
        "verified work. Report unresolved limitations.")


def _allowed(phase: str) -> str:
    tools = ["Skill(producer)", "Read", "Glob", "Grep"]
    tools += [f"mcp__palmier-pro__{name}" for name in READ_TOOLS]
    if phase == "cut":
        tools += [f"mcp__palmier-pro__{name}" for name in CUT_TOOLS]
    if phase in {"visual", "qa", "repair", "visual_repair"}:
        tools += [f"mcp__palmier-pro__{name}" for name in VISUAL_TOOLS]
    return ",".join(tools)


def claude(phase: str) -> dict:
    """Reject mutable user settings/hooks until shared admission is qualified."""
    raise PalmierError(
        "Subscription admission not qualified for the legacy desktop Claude "
        "harness; no provider or session mutation ran. Use an explicitly "
        "requested Codex subscription-agent review of local evidence instead.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["setup", "restore", "open", "plan",
                                             "cut", "visual", "qa", "repair", "visual_repair",
                                             "state"])
    args = parser.parse_args()
    if args.command == "setup":
        value = setup()
    elif args.command == "restore":
        value = restore()
    elif args.command == "open":
        value = open_candidate()
    elif args.command == "state":
        value = _read()
    else:
        value = claude(args.command)
    print(json.dumps(value, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
