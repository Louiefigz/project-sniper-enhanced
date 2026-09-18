"""Small real-media fixtures for program channel-normalization gates."""
from __future__ import annotations

import json
import os
import shutil
import subprocess

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def available() -> bool:
    """Return whether the local real-media pair is callable."""
    return bool(FFMPEG and FFPROBE)


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True, capture_output=True, text=True)


def dead_stereo_wav(path: str, dead_channel: int, duration: float = 1.0) -> None:
    """Write stereo PCM with digital silence on exactly one channel."""
    if dead_channel not in {0, 1}:
        raise ValueError("dead_channel must be 0 or 1")
    inputs = [
        "-f", "lavfi", "-i",
        f"sine=frequency=440:sample_rate=48000:duration={duration}",
        "-f", "lavfi", "-i",
        f"anullsrc=channel_layout=mono:sample_rate=48000:d={duration}",
    ]
    legs = "[1:a][0:a]" if dead_channel == 0 else "[0:a][1:a]"
    _run([
        str(FFMPEG), "-nostdin", "-v", "error", "-y", *inputs,
        "-filter_complex", f"{legs}join=inputs=2:channel_layout=stereo[a]",
        "-map", "[a]", "-c:a", "pcm_s24le", path,
    ])


def dead_stereo_video(
    path: str,
    dead_channel: int,
    duration: float = 2.5,
) -> None:
    """Write a CFR H.264/AAC program with one truly silent PCM input leg."""
    wav = path + ".source.wav"
    dead_stereo_wav(wav, dead_channel, duration)
    try:
        _run([
            str(FFMPEG), "-nostdin", "-v", "error", "-y",
            "-f", "lavfi", "-i",
            f"color=c=0x203040:s=320x180:r=24:d={duration}",
            "-i", wav, "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", "-r", "24",
            "-c:a", "aac", "-b:a", "192k", "-shortest", path,
        ])
    finally:
        os.unlink(wav)


def mono_music(path: str, duration: float = 3.0) -> None:
    """Write a deterministic music-like mono PCM fixture."""
    _run([
        str(FFMPEG), "-nostdin", "-v", "error", "-y",
        "-f", "lavfi", "-i",
        f"sine=frequency=180:sample_rate=48000:duration={duration}",
        "-af", "volume=0.02", "-c:a", "pcm_s24le", path,
    ])


def stream_shape(path: str) -> dict:
    """Return the first audio stream's stable shape."""
    result = subprocess.run([
        str(FFPROBE), "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=codec_name,sample_rate,channels,channel_layout",
        "-of", "json", path,
    ], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)["streams"][0]
