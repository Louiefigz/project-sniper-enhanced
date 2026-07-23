"""Exact decoded-frame oracles that are independent of renderer success."""
from __future__ import annotations

import subprocess

_WIDTH = 96
_HEIGHT = 54
# A comp whose fade tween converges to opacity 0 exactly at data-duration D can
# never encode a true-zero final frame: frames sample at t=k/fps, so the last
# frame sits 1/fps BEFORE D, where the catalog's legal power2.in fade
# (fadeDur >= min(0.42, 0.18*D)) still carries a sub-visible tail in its
# brightest downscaled pixel (~57/255 measured on chip-row/list-build at
# D >= 5; an illegally squeezed 1.0s window measured 117). The bounds accept
# that single-frame fade tail and still reject a genuinely unexited overlay,
# which holds max 255 and a mean far above the cap.
_TERMINAL_MAX_ALPHA_8 = 64
_TERMINAL_MEAN_ALPHA_8 = 8.0


def terminal_alpha(path: str, frame_count: int, ffmpeg: str,
                   environment: dict[str, str]) -> dict:
    """Require the final encoded alpha frame to be clear of visible content."""
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
    mean = sum(proc.stdout) / len(proc.stdout)
    if maximum > _TERMINAL_MAX_ALPHA_8 or mean > _TERMINAL_MEAN_ALPHA_8:
        raise RuntimeError(
            f"final overlay frame retains alpha (max={maximum}, "
            f"mean={mean:.1f})")
    return {"method": "ffmpeg-final-encoded-alpha", "frame": frame_count - 1,
            "maxAlpha8": maximum, "meanAlpha8": round(mean, 2)}
