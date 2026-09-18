#!/usr/bin/env python3
"""Timeline placement primitives for a disposable Palmier shadow timeline.

The translator owns the math; :class:`Executor` binds media references and
executes one complete lane at a time.  A caller-supplied identity guard runs
before every mutation batch so a human project/timeline switch aborts before
automation can land in the wrong place.
"""
from __future__ import annotations

import json
from collections.abc import Callable

from palmier.mcp_client import PalmierClient, PalmierError, emit

IdentityGuard = Callable[[str], None]


def _created_clip_ids(delta: dict | None, expected: int,
                      context: str) -> list[str]:
    """Clip ids created by a Palmier delta, validated for cardinality."""
    clips = (delta or {}).get("clips") or []
    ids = [c["id"] for c in clips if "id" in c]
    if len(ids) < expected:
        raise PalmierError(
            f"{context}: expected {expected} clips in the delta, got "
            f"{len(ids)}: {json.dumps(delta)[:300]}")
    return ids


def _video_clip_ids(delta: dict | None,
                    context: str) -> tuple[list[str], set]:
    """Video-zone ids and tracks, excluding linked audio partners."""
    clips = [c for c in (delta or {}).get("clips") or []
             if c.get("mediaType") != "audio" and "audio" not in str(
                 c.get("trackType", "video"))]
    if not clips:
        raise PalmierError(f"{context}: no video clips in delta")
    return [c["id"] for c in clips], {c.get("track") for c in clips}


def _overlay_groups(entries: list[dict]) -> list[list[tuple[int, dict]]]:
    """Partition overlapping overlays onto the fewest deterministic tracks."""
    groups: list[list[tuple[int, dict]]] = []
    ends: list[int] = []
    ordered = sorted(enumerate(entries), key=lambda row: (
        int(row[1]["startFrame"]), int(row[1]["endFrame"]), row[0]))
    for index, entry in ordered:
        start, end = int(entry["startFrame"]), int(entry["endFrame"])
        target = next((i for i, prior_end in enumerate(ends)
                       if prior_end <= start), None)
        if target is None:
            groups.append([])
            ends.append(end)
            target = len(groups) - 1
        groups[target].append((index, entry))
        ends[target] = end
    return groups


class Executor:
    """Execute translated placement steps against the active shadow timeline."""

    def __init__(self, client: PalmierClient,
                 identity_guard: IdentityGuard | None = None):
        self.client = client
        self.identity_guard = identity_guard or (lambda _phase: None)
        self.media: dict[str, str] = {}
        self.media_s: dict[str, float] = {}
        self.mirror_clip_ids: list[str] = []
        self.cut_clip_ids: list[str] = []
        self.overlay_clip_ids: list[str] = []
        self.music_clip_ids: list[str] = []
        self.text_clip_ids: list[str] = []
        self.overlay_track: int | None = None
        self.project_fps = 0
        self.expected_end_frame = 0

    def run(self, step: dict) -> None:
        """Run one translated step, guarding mutation operations first."""
        if step["op"] != "warn":
            self.identity_guard(step["op"])
        handler = getattr(self, "_op_" + step["op"], None)
        if handler is None:
            raise PalmierError(f"executor cannot run op {step['op']!r}")
        handler(step)

    def _op_cuts(self, step: dict) -> None:
        for index, entry in enumerate(step["entries"]):
            if index:
                self.identity_guard(f"cuts[{index}]")
            placement = {"mediaRef": self.media[entry["mediaKey"]],
                         "startFrame": entry["startFrame"],
                         "source": entry["source"]}
            delta = self.client.call_json("add_clips", {"entries": [placement]})
            ids, _tracks = _video_clip_ids(delta, "cuts")
            self.cut_clip_ids.append(ids[0])
            # Honor the translator's tiled end_frame — do NOT re-round the clip
            # length from source. round(out_s*fps)+round(dur*fps) drifts a frame
            # from round((out_s+dur)*fps), opening a seam gap/overlap between
            # adjacent cuts on non-integer source fps (e.g. 23.976→24). endFrame
            # equals the next cut's startFrame by construction, so cuts tile.
            duration = int(entry["endFrame"]) - int(entry["startFrame"])
            properties = {"clipIds": [ids[0]], "durationFrames": duration}
            if entry["speed"] != 1.0:
                properties["speed"] = entry["speed"]
            self.client.call("set_clip_properties", properties)
        self._verify_cut_end(step["entries"])

    def _verify_cut_end(self, entries: list[dict]) -> None:
        # Cuts tile onto the translator's frames, so the timeline ends at the
        # last cut's end_frame — not a re-rounded source length.
        self.expected_end_frame = int(entries[-1]["endFrame"])
        total = self.client.call_json("get_timeline", {}).get("totalFrames", 0)
        if abs(total - self.expected_end_frame) > 2:
            raise PalmierError(
                f"cut placement mismatch: timeline reports {total} frames, "
                f"translator expected {self.expected_end_frame}")
        emit(status="cuts_placed", clips=len(self.cut_clip_ids),
             totalFrames=total)

    def _op_mirror(self, step: dict) -> None:
        """Place the approved final as the shadow's only visible video clip."""
        entry = step["entry"]
        placement = {"mediaRef": self.media[entry["mediaKey"]],
                     "startFrame": 0, "source": entry["source"]}
        delta = self.client.call_json("add_clips", {"entries": [placement]})
        ids, _tracks = _video_clip_ids(delta, "visual mirror")
        if len(ids) != 1 or (delta or {}).get("removedClipIds"):
            raise PalmierError(
                "visual mirror did not create exactly one non-destructive clip")
        self.mirror_clip_ids = ids
        self.expected_end_frame = int(entry["endFrame"])
        total = self.client.call_json("get_timeline", {}).get("totalFrames")
        if total != self.expected_end_frame:
            raise PalmierError(
                f"visual mirror frame mismatch: timeline reports {total}, "
                f"expected {self.expected_end_frame}")
        emit(status="mirror_placed", clips=1, totalFrames=total,
             masterHash=entry["masterHash"])

    def _op_baseline(self, step: dict) -> None:
        self.client.call("set_clip_properties", {
            "clipIds": self.cut_clip_ids, "transform": step["transform"]})
        emit(status="baseline_applied", clips=len(self.cut_clip_ids))

    def _op_keyframes(self, step: dict) -> None:
        self.client.call("set_keyframes", {
            "clipId": self.cut_clip_ids[step["clip"]],
            "property": step["property"], "keyframes": step["rows"]})
        emit(status="keyframes_set", clip=step["clip"],
             property=step["property"], rows=len(step["rows"]))

    def _make_overlay_track(self) -> str:
        delta = self.client.call_json("add_texts", {"entries": [{
            "content": ".", "startFrame": 0, "endFrame": 1}]})
        created = (delta or {}).get("createdTracks") or []
        if not created or created[0].get("index") != 0:
            raise PalmierError(
                "placeholder text did not create a top track: "
                f"{json.dumps(delta)[:300]}")
        return delta["clips"][0]["id"]

    def _place_overlay(self, entry: dict, track: int,
                       placeholder: str | None) -> str:
        end = entry["endFrame"]
        available = int(self.media_s[entry["mediaKey"]] * self.project_fps)
        if end - entry["startFrame"] > available:
            end = entry["startFrame"] + available
            emit(status="overlay_clamped", mediaKey=entry["mediaKey"],
                 frames=end - entry["startFrame"])
        delta = self.client.call_json("add_clips", {"entries": [{
            "mediaRef": self.media[entry["mediaKey"]],
            "startFrame": entry["startFrame"], "endFrame": end,
            "trackIndex": track}]})
        ids, tracks = _video_clip_ids(delta, "overlays")
        removed = (delta or {}).get("removedClipIds") or []
        allowed_removed = {placeholder} if placeholder else set()
        if len(ids) != 1 or set(removed) - allowed_removed or tracks != {track}:
            self.identity_guard("overlay_delta_cleanup")
            self.client.call("remove_clips", {"clipIds": ids})
            raise PalmierError(
                f"overlay {entry['mediaKey']} landed destructively "
                f"(clips={ids}, removed={removed}, tracks={tracks}) — "
                "disposable clip removed")
        transform = entry.get("transform")
        if transform:
            self.identity_guard("overlay_transform")
            self.client.call("set_clip_properties", {
                "clipIds": [ids[0]], "transform": transform})
        return ids[0]

    def _place_overlay_group(self, group: list[tuple[int, dict]],
                             placed: list[str | None]) -> None:
        placeholder: str | None = None
        failure: BaseException | None = None
        try:
            placeholder = self._make_overlay_track()
            for position, (index, entry) in enumerate(group):
                if position:
                    self.identity_guard(f"overlays[{index}]")
                placed[index] = self._place_overlay(entry, 0, placeholder)
        except BaseException as exc:
            failure = exc
            raise
        finally:
            self._cleanup_placeholder(placeholder, failure)

    def _op_overlays(self, step: dict) -> None:
        entries = step["entries"]
        groups = _overlay_groups(entries)
        placed: list[str | None] = [None] * len(entries)
        self.overlay_track = 0
        for group in groups:
            self._place_overlay_group(group, placed)
        if any(clip_id is None for clip_id in placed):
            raise PalmierError("overlay placement did not return every clip id")
        self.overlay_clip_ids = [str(clip_id) for clip_id in placed]
        emit(status="overlays_placed", count=len(entries), tracks=len(groups))

    def _cleanup_placeholder(self, placeholder: str | None,
                             failure: BaseException | None) -> None:
        if placeholder is None:
            return
        try:
            self.identity_guard("overlay_placeholder_cleanup")
            self.client.call("remove_clips", {"clipIds": [placeholder]})
        except Exception as exc:
            if failure is None:
                raise
            emit(status="warning", warning=f"placeholder cleanup failed: {exc}")

    def _op_music(self, step: dict) -> None:
        from producer_config import AUDIO
        gap_db = sum(AUDIO["music_gap_db"]) / 2.0
        volume = round(10 ** (-gap_db / 20.0), 4)
        bed = int(self.media_s[step["mediaKey"]] * self.project_fps)
        if bed <= 0:
            raise PalmierError("music asset has no positive duration")
        start, tiles = 0, []
        while start < step["endFrame"]:
            tiles.append((start, min(start + bed, step["endFrame"])))
            start += bed
        self._place_music_tiles(step["mediaKey"], tiles, volume)
        emit(status="music_placed", tiles=len(tiles), volume=volume,
             rest_gap_db=gap_db)

    def _place_music_tiles(self, media_key: str, tiles: list[tuple[int, int]],
                           volume: float) -> None:
        for index, (start, end) in enumerate(tiles):
            if index:
                self.identity_guard(f"music[{index}]")
            delta = self.client.call_json("add_clips", {"entries": [{
                "mediaRef": self.media[media_key], "startFrame": start,
                "endFrame": end}]})
            clip_id = _created_clip_ids(delta, 1, "music")[0]
            self.music_clip_ids.append(clip_id)
            self.client.call("set_keyframes", {"clipId": clip_id,
                                               "property": "volume",
                                               "keyframes": [[0, volume]]})

    def _op_text(self, step: dict) -> None:
        delta = self.client.call_json("add_texts", {"entries": [{
            "content": step["content"], "startFrame": step["startFrame"],
            "endFrame": step["endFrame"], "animation": "fadeIn"}]})
        self.text_clip_ids.extend(
            c["id"] for c in (delta or {}).get("clips") or [] if "id" in c)
        emit(status="text_added", startFrame=step["startFrame"])

    @staticmethod
    def _op_warn(step: dict) -> None:
        emit(status="warning", warning=step["message"])
