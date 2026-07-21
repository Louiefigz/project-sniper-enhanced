"""Exact decoded-frame oracles that are independent of renderer success."""
from __future__ import annotations

import subprocess

_WIDTH = 96
_HEIGHT = 54


def terminal_alpha(path: str, frame_count: int, ffmpeg: str,
                   environment: dict[str, str]) -> dict:
    """Require the final encoded alpha frame to be fully clear."""
    filters = (f"select=eq(n\\,{frame_count - 1}),alphaextract,"
               f"scale={_WIDTH}:{_HEIGHT}:flags=area")
    command = [ffmpeg, "-nostdin", "-v", "error", "-i", path, "-vf", filters,
               "-an", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray",
               "-"]
    proc = subprocess.run(command, capture_output=True, stdin=subprocess.DEVNULL,
                          env=environment)
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", errors="replace").strip()[-240:]
        raise RuntimeError(f"terminal alpha decode failed: {message}")
    expected = _WIDTH * _HEIGHT
    if len(proc.stdout) != expected:
        raise RuntimeError("terminal alpha oracle did not decode exactly one frame")
    maximum = max(proc.stdout)
    if maximum != 0:
        raise RuntimeError(f"final overlay frame retains alpha (max={maximum})")
    return {"method": "ffmpeg-final-encoded-alpha", "frame": frame_count - 1,
            "maxAlpha8": maximum, "meanAlpha8": 0.0}
