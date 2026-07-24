"""Exact decoded-frame oracles that are independent of renderer success."""
from __future__ import annotations

import subprocess

_WIDTH = 96
_HEIGHT = 54
# A comp whose fade tween converges to opacity 0 exactly at data-duration D can
# never encode a true-zero final frame: frames sample at t=k/fps, so the last
# frame sits 1/fps BEFORE D, where a legal fade still carries a sub-visible
# tail in its brightest downscaled pixel. Measured tails by comp family:
# chip-row/list-build ~57 (D >= 5), fragment-payoff 67 (D = 1.33s), an
# illegally squeezed 1.0s chip window 117. The MEAN is the load-bearing
# discriminator: fade tails measure mean ~1 while a genuinely unexited
# overlay holds max 255 / mean 255 (statement-card, measured). Bounds set
# from the three measured families: max admits the brightest legal tail
# with margin, mean at 4.0 is ~4x the worst legal tail and ~60x below the
# smallest real-defect signal.
_TERMINAL_MAX_ALPHA_8 = 72
_TERMINAL_MEAN_ALPHA_8 = 4.0


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
