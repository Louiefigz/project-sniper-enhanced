#!/usr/bin/env python3
"""Render and decode-prove one bounded CaptionTrackV1 alpha page."""
from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from fractions import Fraction

from captions.caption_page_decode import decode_caption_page


@dataclass(frozen=True)
class CaptionPageMediaContext:
    """Immutable canvas, tool, and source-directory facts."""

    manifest: dict
    directory: str
    tools: dict


def _rate(manifest: dict) -> tuple[Fraction, str]:
    row = manifest["fps"]
    rate = Fraction(int(row["numerator"]), int(row["denominator"]))
    return rate, f"{rate.numerator}/{rate.denominator}"


def _filter_graph(page: dict, rate: Fraction) -> str:
    labels = ["[0:v]setpts=PTS-STARTPTS[page-base]"]
    current = "page-base"
    for index, row in enumerate(page["inputs"], start=1):
        offset = row["pageStartFrame"] * rate.denominator
        labels.append(
            f"[{index}:v]trim=start_frame={row['sourceStartFrame']}:"
            f"end_frame={row['sourceEndFrameExclusive']},"
            f"setpts=PTS-STARTPTS+{offset}/{rate.numerator}/TB"
            f"[page-input-{index}]")
        labels.append(
            f"[{current}][page-input-{index}]overlay=x=0:y=0:"
            "eof_action=pass:repeatlast=0:shortest=0:format=auto"
            f"[page-out-{index}]")
        current = f"page-out-{index}"
    labels.append(f"[{current}]format=rgba[page-final]")
    return ";".join(labels)


def _command(page: dict, context: CaptionPageMediaContext,
             output: str) -> list[str]:
    rate, token = _rate(context.manifest)
    destination = context.manifest["destination"]
    frames = page["endFrameExclusive"] - page["startFrame"]
    source = (f"color=c=black@0.0:s={destination['width']}x"
              f"{destination['height']}:r={token},format=rgba")
    command = [context.tools["ffmpeg"]["path"], "-y", "-hide_banner",
               "-loglevel", "error", "-f", "lavfi", "-i", source]
    for row in page["inputs"]:
        command.extend((
            "-i", os.path.join(context.directory, row["media"]["name"])))
    command.extend((
        "-filter_complex", _filter_graph(page, rate),
        "-map", "[page-final]", "-frames:v", str(frames), "-an",
        "-c:v", "png", "-pix_fmt", "rgba", "-r", token,
        "-fps_mode", "cfr", "-map_metadata", "-1",
        "-metadata", "creation_time=1970-01-01T00:00:00Z", output,
    ))
    return command


def caption_page_command(
        page: dict, context: CaptionPageMediaContext,
        output: str) -> list[str]:
    """Return the exact normalized compositor argv for one page."""
    return _command(page, context, output)


def prove_caption_page(path: str, context: CaptionPageMediaContext,
                       frames: int) -> dict:
    """Fully decode one page once; retain the exact stream/alpha/hash proof shape."""
    _, token = _rate(context.manifest)
    expected = {
        "codec_name": "png", "pix_fmt": "rgba",
        "width": context.manifest["destination"]["width"],
        "height": context.manifest["destination"]["height"],
        "r_frame_rate": token, "nb_read_frames": str(frames),
    }
    return decode_caption_page(path, context.tools, expected)


def render_caption_page(
    page: dict,
    media_path: str,
    context: CaptionPageMediaContext,
) -> tuple[dict, list[str]]:
    """Atomically render one page and return proof plus normalized argv."""
    descriptor, staged = tempfile.mkstemp(
        prefix=".caption-page.", suffix=".mov", dir=context.directory)
    os.close(descriptor)
    os.remove(staged)
    command = _command(page, context, staged)
    try:
        process = subprocess.run(command, capture_output=True, text=True)
        if process.returncode or not os.path.isfile(staged):
            raise RuntimeError(
                "caption page render failed: " + process.stderr[-500:])
        frames = page["endFrameExclusive"] - page["startFrame"]
        proof = prove_caption_page(staged, context, frames)
        os.replace(staged, media_path)
        return proof, command[:-1] + [media_path]
    finally:
        if os.path.exists(staged):
            os.remove(staged)
