"""Governed execution of one hash-bound Desktop Palmier worklist.

This module deliberately contains no project lifecycle calls.  Every timeline
mutation is routed through the production Desktop pre/post hooks, and one
caller-selected import can exercise durable missed-PostToolUse reconciliation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from palmier.desktop_audio_master_binding import expected_route_args
from palmier.desktop_exact_master_binding import expected_disable_args
from palmier.desktop_hook import authorize_pre, observe_post
from palmier.desktop_authority import reconcile
from palmier.desktop_state import load_state, read_record
from palmier.live_acceptance_worklist_contract import (
    PASSIVE_OPS, validate_steps)
from palmier.live_acceptance_runtime import AppliedResponseLost
from palmier.live_acceptance_worklist_support import (
    args_digest, audio_ids, clips, entry, json_result, load_state_dir,
    media_ref, recovered_media_ref,
)
from palmier.mcp_client import PalmierError

PREFIX = "mcp__palmier-pro__"


@dataclass
class GovernedWorklist:
    """Execute prepared steps while retaining compact per-call evidence."""

    client: Any
    repo: str
    base_timeline: dict
    disconnect_first_import: bool = False
    fault_every_mutation: bool = False
    calls: list[dict] = field(default_factory=list)
    media: dict[str, str] = field(default_factory=dict)
    disconnect_receipt: dict | None = None
    fault_receipts: list[dict] = field(default_factory=list)

    def _reconcile_call(
            self, tool: str, args: dict,
            media_ref: str | None, fault: str) -> tuple[dict, dict]:
        state = reconcile(self.client, self.repo, media_ref)
        receipt = {
            "tool": tool, "argsHash": args_digest(args),
            "operationCount": state["operationCount"],
            "pendingCleared": state.get("pendingOperation") is None,
            "fault": fault,
        }
        self.fault_receipts.append(receipt)
        return state, receipt

    def _call(self, tool: str, args: dict, disconnect: bool = False) -> object:
        event = {"tool_name": PREFIX + tool, "tool_input": args}
        authorize_pre(event, self.repo, client_factory=lambda: self.client)
        lost = self.fault_every_mutation
        if lost:
            arm = getattr(self.client, "arm_response_loss", None)
            if not callable(arm):
                raise PalmierError(
                    "fault cohort client cannot withhold mutation responses")
            arm()
        try:
            raw = self.client.call(tool, args)
        except AppliedResponseLost:
            raw = None
        result = json_result(raw) if raw is not None else None
        if lost:
            state, _receipt = self._reconcile_call(
                tool, args, None, "response-lost-after-apply")
            if tool == "import_media":
                result = {"mediaRef": recovered_media_ref(state, args)}
        elif disconnect:
            imported_ref = media_ref(result) if tool == "import_media" else None
            _state, self.disconnect_receipt = self._reconcile_call(
                tool, args, imported_ref, "missed-post-receipt")
        else:
            observe_post({**event, "hook_event_name": "PostToolUse",
                          "tool_response": raw}, self.repo,
                         client_factory=lambda: self.client)
        if tool == "import_media":
            self.client.wait_media(media_ref(result))
        self.calls.append({"tool": tool, "argsHash": args_digest(args),
                           "reconciled": lost or disconnect,
                           "responseLost": lost})
        return result

    def _import(self, step: dict) -> str:
        args = {"source": {"path": step["path"]}}
        if isinstance(step.get("importName"), str):
            args["name"] = step["importName"]
        disconnect = self.disconnect_first_import \
            and self.disconnect_receipt is None
        ref = media_ref(self._call("import_media", args, disconnect))
        identities = {
            step.get("key"), step.get("mediaKey"), step.get("elementId"),
            step.get("fileHash"), step.get("assetHash"),
        }
        for identity in identities:
            if isinstance(identity, str) and identity:
                self.media[identity] = ref
        return ref

    def _media_for(self, step: dict) -> str:
        identities = (
            step.get("mediaKey"), step.get("key"), step.get("elementId"),
            step.get("assetHash"), step.get("fileHash"),
        )
        for identity in identities:
            value = self.media.get(identity) if isinstance(identity, str) else None
            if isinstance(value, str):
                return value
        raise PalmierError(f"worklist media {identities!r} was not imported")

    def _overlays(self, step: dict) -> None:
        entries = []
        for row in step.get("entries") or []:
            if not isinstance(row, dict):
                raise PalmierError("overlay worklist entry is malformed")
            entries.append(entry(row, self._media_for(row)))
        if not entries:
            raise PalmierError("overlay worklist is empty")
        self._call("add_clips", {"entries": entries})

    def _replace(self, step: dict) -> None:
        self._call("add_clips", {
            "entries": [entry(step, self._media_for(step))]})
        state = load_state(load_state_dir(self.repo))
        elements = (state.get("elementLedger") or {}).get("elements") or {}
        current = elements.get(step.get("elementId"))
        if isinstance(current, dict) and current.get("status") == "cleanup-required":
            self._call("remove_clips", {
                "clipIds": [current["replacement"]["oldClipId"]]})

    def _base_ids(self) -> list[str]:
        return [row["id"] for row in clips(self.base_timeline, True)]

    def _baseline(self, step: dict) -> None:
        self._call("set_clip_properties", {
            "clipIds": self._base_ids(), "transform": step["transform"]})

    def _keyframes(self, step: dict) -> None:
        clips = self._base_ids()
        index = step.get("clip")
        if not isinstance(index, int) or index < 0 or index >= len(clips):
            raise PalmierError("keyframe worklist references an absent base clip")
        self._call("set_keyframes", {
            "clipId": clips[index], "property": step["property"],
            "keyframes": step["rows"]})

    def _text(self, step: dict) -> None:
        entry = {key: step[key] for key in (
            "content", "startFrame", "endFrame")}
        entry["animation"] = step.get("animation", "fadeIn")
        self._call("add_texts", {"entries": [entry]})

    def _native_media(self, step: dict) -> None:
        ref = self._import(step)
        self._call("add_clips", {"entries": [entry(step, ref)]})

    def _audio_master(self, step: dict) -> None:
        ref = self._import(step)
        self._call("add_clips", {"entries": [entry(step, ref)]})

    def _route_audio(self) -> None:
        state = load_state(load_state_dir(self.repo))
        timeline = self.client.call_json("get_timeline", {})
        self._call("manage_tracks", expected_route_args(state, timeline))

    def _disable_master(self) -> None:
        state = load_state(load_state_dir(self.repo))
        self._call("manage_tracks", expected_disable_args(state))

    def _caption_shard(self, step: dict) -> None:
        self._call("add_texts", {"entries": [{
            "content": ".", "startFrame": 0, "endFrame": 1}]})
        clip_entry = entry(step, self._media_for(step))
        clip_entry["trackIndex"] = 0
        self._call("add_clips", {"entries": [clip_entry]})
        state = load_state(load_state_dir(self.repo))
        progress = state.get("captionShardProgress")
        if isinstance(progress, dict) \
                and progress.get("status") == "cleanup-required":
            self._call("remove_clips", {
                "clipIds": [progress["clipId"]]})

    def _caption_pages(self, step: dict) -> None:
        self._call("add_texts", {"entries": [{
            "content": ".", "startFrame": 0, "endFrame": 1}]})
        entries = [{
            "mediaRef": self._media_for(row),
            "startFrame": row["startFrame"], "endFrame": row["endFrame"],
            "trackIndex": 0, "transform": row["transform"],
        } for row in step["entries"]]
        self._call("add_clips", {"entries": entries})
        state = load_state(load_state_dir(self.repo))
        progress = state.get("captionPageProgress")
        if isinstance(progress, dict) \
                and progress.get("status") == "cleanup-required":
            self._call("remove_clips", {
                "clipIds": [progress["clipId"]]})

    def _broll(self, step: dict) -> None:
        self._import(step)
        self._caption_shard(step)

    def _native_effect(self, step: dict, tool: str, audio: bool = False) -> None:
        ids = audio_ids(self.base_timeline) if audio else self._base_ids()
        if not ids:
            raise PalmierError(f"{tool} has no base clip identities")
        self._call(tool, {"clipIds": ids, **step["settings"]})

    def execute(self, operations_path: str) -> dict:
        """Execute all supported steps and reject unknown mutations."""
        manifest = read_record(operations_path, "operation manifest")
        steps = manifest.get("steps")
        if not isinstance(steps, list):
            raise PalmierError("Desktop operation manifest has no steps")
        validate_steps(steps, manifest.get("stage"))
        for step in steps:
            self._step(step)
        if self.disconnect_first_import and self.disconnect_receipt is None:
            raise PalmierError("disconnect acceptance requested but no import existed")
        if self.fault_every_mutation \
                and len(self.fault_receipts) != len(self.calls):
            raise PalmierError(
                "mutation-boundary fault cohort did not reconcile every call")
        return {"stepCount": len(steps), "calls": self.calls,
                "disconnect": self.disconnect_receipt,
                "applyAmbiguityReceipts": self.fault_receipts,
                "everyMutationReconciled": self.fault_every_mutation}

    def _step(self, step: object) -> None:
        if not isinstance(step, dict) or not isinstance(step.get("op"), str):
            raise PalmierError("Desktop worklist step is malformed")
        op = step["op"]
        handlers = {
            "import": lambda: self._import(step),
            "overlays": lambda: self._overlays(step),
            "replace-overlay": lambda: self._replace(step),
            "baseline": lambda: self._baseline(step),
            "keyframes": lambda: self._keyframes(step),
            "text": lambda: self._text(step),
            "native-broll": lambda: self._broll(step),
            "native-music": lambda: self._native_media(step),
            "native-captions": lambda: self._call(
                "add_captions", step["settings"]),
            "native-denoise": lambda: self._native_effect(
                step, "denoise_audio", True),
            "native-color": lambda: self._native_effect(
                step, "apply_color"),
            "exact-master-reference-add": lambda: self._call(
                "add_clips", {"entries": [
                    entry(step, self._media_for(step))]}),
            "exact-master-reference-disable": self._disable_master,
            "native-audio-master": lambda: self._audio_master(step),
            "mastered-stereo-route": self._route_audio,
            "caption-alpha-shard": lambda: self._caption_shard(step),
            "title-alpha-shard": lambda: self._caption_shard(step),
            "graphics-alpha-shard": lambda: self._caption_shard(step),
            "caption-alpha-pages": lambda: self._caption_pages(step),
        }
        if op in PASSIVE_OPS:
            return
        handler = handlers.get(op)
        if handler is None:
            raise PalmierError(f"live acceptance cannot execute worklist op {op!r}")
        handler()
