"""Observed CFR picture clocks and the existing compositor's private range lane.

These are mechanical frame/decode facts, not creator-level visual approval.
Full-duration assets retain their original animation origin; only the composed
picture is trimmed. The approved whole-program cut is never rewritten.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import nullcontext
from copy import deepcopy
from fractions import Fraction
from pathlib import Path

from audio.audio_mix_picture import observe_picture_source
from audio.render_audio_authority import run_audio
from cut_preview_io import digest, file_hash
from graphics.composite_core import CompositeOptions, composite
from guided_picture_decode import decode_picture_frames
from guided_caption_projection import HeldCaptionProjection
from guided_caption_layers import opening_caption_layers
from guided_opening_presenter import OpeningPictureContext, held_presenter_ranges
from guided_presenter_caption_picture import (
    prepare_presenter_caption_picture, presenter_caption_picture_guard, finish_presenter_caption_picture,
)


def observe_picture(path: Path, expected: tuple[str, int, tuple[int, int]], tools: dict) -> dict:
    """Require exact decoded count, canvas, zero-origin CFR and complete decode."""
    rate, frames, canvas = expected
    before = file_hash(path)
    raw = run_audio([tools["ffprobe"]["path"], "-v", "error", "-show_streams", "-of", "json", str(path)])
    videos = [row for row in json.loads(raw)["streams"] if row.get("codec_type") == "video"]
    if len(videos) != 1:
        raise RuntimeError("opening picture does not have exactly one video stream")
    row = videos[0]
    if Fraction(row["r_frame_rate"]) != Fraction(rate) or Fraction(row["avg_frame_rate"]) != Fraction(rate) \
            or (row["width"], row["height"]) != canvas \
            or row.get("sample_aspect_ratio") != "1:1" or row.get("side_data_list") \
            or row.get("tags", {}).get("rotate", "0") != "0":
        raise RuntimeError("opening actual picture differs from its exact clock/canvas authority")
    decode_picture_frames(path, tools["ffmpeg"]["path"], frames)
    picture = observe_picture_source(str(path), float(Fraction(frames, 1) / Fraction(rate)), before)
    if file_hash(path) != before:
        raise RuntimeError("opening picture bytes changed during complete observation")
    packet_rows = [[str(item) if isinstance(item, Fraction) else item for item in row] for row in picture.packets]
    return {"path": str(path), "sha256": before, "sizeBytes": path.stat().st_size,
        "frameRate": rate, "frames": frames, "width": canvas[0], "height": canvas[1],
        "startPts": 0, "timeBase": str(picture.time_base), "videoDecodeSucceeded": True,
        "packetTimelineSha256": digest(packet_rows), "codec": videos[0]["codec_name"]}


def compose_ranges(base: Path, clips: list[dict], context: tuple[Path, dict, dict] | OpeningPictureContext,
                   captions: HeldCaptionProjection | None = None) -> dict:
    """Run the ordinary shared graph with explicit integer half-open opt-in only."""
    output, authority, tools = (context.root, context.authority, context.tools) if type(context) is OpeningPictureContext else context
    presenter = context.presenter if type(context) is OpeningPictureContext else None
    rate = authority["frameRate"]
    canvas = authority["target"]["width"], authority["target"]["height"]
    clearance = prepare_presenter_caption_picture(presenter, captions, authority)
    ordered = sorted(clips, key=lambda clip: float(clip["outStart"]))
    combined, layer = (clips, None) if captions is None else opening_caption_layers(
        clips, captions, authority["review"]["endFrameExclusive"])
    if presenter is not None:
        combined = deepcopy(combined)
    tail = None if layer is None else layer["captionTail"]
    live = nullcontext((None, None, lambda: None)) if presenter is None else held_presenter_ranges(
        base, presenter, authority, (tuple(combined), tail))
    with live as (graph, presenter_record, guard):
        if presenter is not None:
            guard = _command_guard(guard, clips, combined)
        guard = presenter_caption_picture_guard(clearance, guard)
        options = CompositeOptions(eof_pass=True, ffmpeg=tools["ffmpeg"]["path"],
            ffprobe=tools["ffprobe"]["path"], command_runner=run_audio,
            frame_rate=graph.frame_rate if graph is not None else rate,
            video_only=True, caption_tail=tail, presenter=graph)
        result = _compose_pairs((base, output, combined), (authority, tools, canvas), options, guard)
    if presenter_record is not None:
        guard()
        presenter_record = {**presenter_record, "pictureRangesHash": digest(result)}
    pictures = {"policy": "global-composition-then-half-open-frame-trim-v1", "ranges": result,
        **({"captionLayers": layer} if layer is not None else {}),
        **({"presenterLayers": presenter_record} if presenter_record is not None else {}),
        "candidateOrder": [clip["graphicId"] for clip in clips],
        "executedOrder": [clip["graphicId"] for clip in ordered],
        "orderPolicy": "ordinary-outStart-ascending-stable-candidate-ties",
        "placementScope": "declared-own-screen-full-canvas-not-free-space-or-perceptual-proof"}
    bound = finish_presenter_caption_picture(clearance, pictures, guard)
    return {**pictures, "presenterCaptionClearance": bound} if bound is not None else pictures


def _command_guard(guard: Callable[[], None], originals: list[dict], combined: list[dict]) -> Callable[[], None]:
    """Bind outer list membership too, not merely dictionaries held by a tuple."""
    expected = digest([originals, combined])

    def check() -> None:
        """Reject added, removed, replaced or reordered actual command inputs."""
        guard()
        if digest([originals, combined]) != expected:
            raise RuntimeError("opening presenter actual clip inventory changed")

    return check


def _compose_pairs(paths: tuple, context: tuple, options: CompositeOptions, guard: Callable[[], None]) -> dict:
    """Deduplicate identical ranges without restarting any original graph clock."""
    from dataclasses import replace

    base, output, combined = paths
    authority, tools, canvas = context
    result, completed = {}, {}
    for name in ("core", "review"):
        guard()
        span = authority[name]
        frames = span["startFrame"], span["endFrameExclusive"]
        if frames not in completed:
            path = output / f"{name}-picture.mp4"
            passes = composite(str(base), combined, str(path), replace(options, frame_range=frames))
            observed = observe_picture(path, (authority["frameRate"], frames[1] - frames[0], canvas), tools)
            guard()
            completed[frames] = {**span, **observed, "compositorPasses": passes}
        result[name] = completed[frames]
    return result
