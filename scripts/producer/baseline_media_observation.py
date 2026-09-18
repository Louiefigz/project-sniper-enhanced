#!/usr/bin/env python3
"""Produce decoded-media identity for current-path baseline outputs."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from baseline_qc_observation import observe_qc

_HASH = re.compile(r"^SHA256=([0-9a-f]{64})$", re.MULTILINE)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _tool(name: str) -> tuple[Path, dict[str, str]]:
    found = shutil.which(name)
    if not found:
        raise RuntimeError(f"baseline media observation needs {name}")
    path = Path(os.path.realpath(found))
    version = subprocess.run(
        [str(path), "-version"], stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=30, check=False,
    )
    if version.returncode or not version.stdout:
        raise RuntimeError(f"cannot attest baseline {name}")
    return path, {
        "path": str(path),
        "sha256": _sha256_file(path),
        "version": version.stdout.splitlines()[0],
    }


def _probe(path: Path, ffprobe: Path) -> tuple[dict, dict]:
    result = subprocess.run(
        [
            str(ffprobe), "-v", "error", "-count_frames",
            "-show_entries",
            "stream=codec_type,width,height,r_frame_rate,avg_frame_rate,"
            "nb_read_frames,duration,sample_rate,channels",
            "-of", "json", str(path),
        ],
        stdin=subprocess.DEVNULL, capture_output=True, text=True,
        timeout=7_200, check=False,
    )
    try:
        streams = json.loads(result.stdout)["streams"]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("baseline ffprobe returned malformed JSON") from exc
    videos = [row for row in streams if row.get("codec_type") == "video"]
    audio = [row for row in streams if row.get("codec_type") == "audio"]
    if result.returncode or len(videos) != 1 or len(audio) != 1:
        raise RuntimeError("baseline output needs one video and one audio stream")
    video = videos[0]
    return ({
        "width": int(video["width"]),
        "height": int(video["height"]),
        "rFrameRate": str(video["r_frame_rate"]),
        "avgFrameRate": str(video["avg_frame_rate"]),
        "decodedFrames": int(video["nb_read_frames"]),
        "duration": str(video["duration"]),
    }, {
        "sampleRate": int(audio[0]["sample_rate"]),
        "channels": int(audio[0]["channels"]),
        "duration": str(audio[0]["duration"]),
    })


def _decoded_video_hash(ffmpeg: Path, path: Path) -> str:
    result = subprocess.run(
        [str(ffmpeg), "-v", "error", "-i", str(path),
         "-map", "0:v:0", "-an", "-c:v", "rawvideo", "-pix_fmt", "yuv420p",
         "-f", "hash", "-hash", "sha256", "-"],
        stdin=subprocess.DEVNULL, capture_output=True, text=True,
        timeout=7_200, check=False,
    )
    match = _HASH.search(result.stdout)
    if result.returncode or match is None or result.stderr:
        raise RuntimeError("baseline video full decode failed")
    return match.group(1)


def _decoded_audio(ffmpeg: Path, path: Path) -> dict[str, int | str]:
    command = [
        str(ffmpeg), "-v", "error", "-i", str(path),
        "-map", "0:a:0", "-vn", "-c:a", "pcm_s16le",
        "-ar", "48000", "-ac", "2", "-f", "s16le", "-",
    ]
    digest = hashlib.sha256()
    byte_count = 0
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=errors,
        )
        if process.stdout is None:
            raise RuntimeError("baseline audio decode has no output pipe")
        while chunk := process.stdout.read(1024 * 1024):
            digest.update(chunk)
            byte_count += len(chunk)
        return_code = process.wait(timeout=7_200)
        errors.seek(0)
        error_text = errors.read()
    if return_code or error_text or byte_count <= 0 or byte_count % 4:
        raise RuntimeError("baseline audio full decode failed")
    return {
        "audioPcmS16le48000StereoSha256": digest.hexdigest(),
        "audioPcmBytes": byte_count,
        "audioSamplesPerChannel": byte_count // 4,
    }


def observe_media(path: Path) -> dict:
    """Fully decode one output and return exact stream/payload identity."""
    ffmpeg, ffmpeg_tool = _tool("ffmpeg")
    ffprobe, ffprobe_tool = _tool("ffprobe")
    video, audio = _probe(path, ffprobe)
    final_sha256 = _sha256_file(path)
    return {
        "video": video,
        "audio": audio,
        "fullDecode": {
            "videoSha256": _decoded_video_hash(ffmpeg, path),
            **_decoded_audio(ffmpeg, path),
        },
        "tools": {"ffmpeg": ffmpeg_tool, "ffprobe": ffprobe_tool},
        "qc": observe_qc(path, final_sha256),
    }
