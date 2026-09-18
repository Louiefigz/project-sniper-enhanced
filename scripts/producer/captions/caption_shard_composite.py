#!/usr/bin/env python3
"""Consume proved caption alpha shards in one final picture composite."""
from __future__ import annotations

import os
import subprocess
import tempfile
from fractions import Fraction

from captions.caption_authority import _video_options
from captions.caption_shard_contract import validate_caption_shard_manifest
from fingerprints import file_sha256
from media_probe import _fps_fraction, probe_video
from cut_speed import probe_video_frames


def _asset_paths(video_path: str, manifest: dict) -> list[str]:
    directory = os.path.dirname(os.path.abspath(video_path))
    result = []
    for row in manifest["entries"]:
        media = row.get("media")
        name = media.get("name") if isinstance(media, dict) else None
        path = os.path.join(directory, str(name))
        if not isinstance(name, str) or os.path.basename(name) != name \
                or not os.path.isfile(path) \
                or file_sha256(path) != media.get("sha256"):
            raise RuntimeError("caption alpha shard media is missing or stale")
        result.append(path)
    return result


def _clock(manifest: dict) -> tuple[Fraction, str]:
    value = manifest.get("fps")
    try:
        rate = Fraction(
            int(value["numerator"]), int(value["denominator"]))
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise RuntimeError("caption alpha shard fps is malformed") from exc
    return rate, f"{rate.numerator}/{rate.denominator}"


def _validate_video(video_path: str, manifest: dict) -> tuple[str, int]:
    probe = probe_video(video_path)
    video_rate = _fps_fraction(probe.get("r_frame_rate"))
    rate, token = _clock(manifest)
    destination = manifest.get("destination") or {}
    if video_rate != rate:
        raise RuntimeError("caption alpha shard fps differs from final video")
    if (probe.get("width"), probe.get("height")) != (
            destination.get("width"), destination.get("height")):
        raise RuntimeError(
            "caption alpha shard canvas differs from final video")
    return token, probe_video_frames(video_path)


def _filter_graph(manifest: dict, rate: Fraction) -> str:
    labels = ["[0:v]setpts=PTS-STARTPTS[caption-base]"]
    current = "caption-base"
    for index, row in enumerate(manifest["entries"], start=1):
        start = row.get("startFrame")
        end = row.get("endFrameExclusive")
        if not isinstance(start, int) or not isinstance(end, int) or end <= start:
            raise RuntimeError("caption alpha shard frame range is invalid")
        shifted = f"caption-shard-{index}"
        output = f"caption-out-{index}"
        offset = f"{start * rate.denominator}/{rate.numerator}/TB"
        labels.append(
            f"[{index}:v]setpts=PTS-STARTPTS+{offset}[{shifted}]")
        labels.append(
            f"[{current}][{shifted}]overlay=x=0:y=0:"
            f"eof_action=pass:shortest=0:format=auto[{output}]")
        current = output
    labels.append(f"[{current}]format=yuv420p[caption-final]")
    return ";".join(labels)


def _command(video_path: str, assets: list[str], manifest: dict,
             staged: str) -> list[str]:
    rate, token = _clock(manifest)
    command = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
               "-i", video_path]
    for path in assets:
        command.extend(("-i", path))
    command.extend((
        "-filter_complex", _filter_graph(manifest, rate),
        "-map", "[caption-final]", "-map", "0:a?",
        *_video_options(token), "-c:a", "copy", staged,
    ))
    return command


def apply_caption_shards(video_path: str, value: object) -> dict:
    """Overlay all bounded alpha shards once and preserve mastered audio."""
    directory = os.path.dirname(os.path.abspath(video_path))
    manifest = validate_caption_shard_manifest(value, directory)
    if not manifest["entries"]:
        return {"shards": 0, "encoded": False}
    token, frames = _validate_video(video_path, manifest)
    assets = _asset_paths(video_path, manifest)
    suffix = os.path.splitext(video_path)[1] or ".mp4"
    descriptor, staged = tempfile.mkstemp(
        prefix=".caption-shards.", suffix=suffix, dir=directory)
    os.close(descriptor)
    try:
        process = subprocess.run(
            _command(video_path, assets, manifest, staged),
            capture_output=True, text=True)
        if process.returncode or not os.path.isfile(staged):
            raise RuntimeError(
                "caption shard composite failed: " + process.stderr[-500:])
        if probe_video_frames(staged) != frames:
            raise RuntimeError("caption shard composite changed picture frames")
        os.replace(staged, video_path)
    finally:
        if os.path.exists(staged):
            os.remove(staged)
    return {
        "shards": len(assets), "encoded": True,
        "fps": token, "frames": frames,
        "mediaKeys": [row["mediaKey"] for row in manifest["entries"]],
    }
