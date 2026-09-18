"""Frame extraction — ffmpeg pulls N frames/sec as JPGs named by their timestamp.

Each file is named ``frame_<seconds:06d>.jpg`` so the timestamp is recoverable
from the filename alone (frame_000001.jpg = the frame shown at t=1s when fps=1).
ffmpeg progress is printed to stderr so the caller can surface it live.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass

from .util import log


@dataclass
class Frame:
    """One extracted frame, before dedup."""

    index: int          # 0-based extraction order
    timestamp: float    # seconds into the source video
    path: str           # absolute path to the JPG on disk


def probe_duration(input_path: str) -> float:
    """Return the source duration in seconds (0.0 if ffprobe can't tell)."""
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                input_path,
            ],
            capture_output=True, text=True, check=True,
        )
        return float(out.stdout.strip())
    except (subprocess.CalledProcessError, ValueError):
        return 0.0


def extract_frames(
    input_path: str,
    out_dir: str,
    fps: float = 1.0,
    max_frames: int | None = None,
    on_progress=None,
) -> list[Frame]:
    """Extract frames at ``fps`` into ``out_dir`` and return them in time order.

    ``max_frames`` caps the number of frames (so a short, cheap test run is one
    flag away). ``on_progress(done, total)`` is called as ffmpeg reports frames.
    Reuses already-extracted JPGs in ``out_dir`` (the orchestrator caches frames
    by input+fps so a "proceed anyway" re-run doesn't re-extract).
    """
    os.makedirs(out_dir, exist_ok=True)

    duration = probe_duration(input_path)
    expected = int(duration * fps) if duration else 0
    if max_frames is not None and expected:
        expected = min(expected, max_frames)

    # Reuse cached frames if a prior run already extracted this input/fps.
    existing = _collect_frames(out_dir, fps)
    if existing:
        if max_frames is not None:
            existing = existing[:max_frames]
        log("extract", f"reusing {len(existing)} cached frame(s) in {out_dir}")
        if on_progress:
            on_progress(len(existing), len(existing))
        return existing

    # -vf fps=N resamples to N frames/sec; -frames:v caps the count when asked.
    # q:v 3 keeps JPGs sharp enough for text OCR without huge files.
    cmd = [
        "ffmpeg", "-hide_banner", "-y",
        "-i", input_path,
        "-vf", f"fps={fps}",
        "-q:v", "3",
    ]
    if max_frames is not None:
        cmd += ["-frames:v", str(max_frames)]
    cmd += ["-progress", "pipe:1", os.path.join(out_dir, "frame_%06d.jpg")]

    log("extract", f"ffmpeg fps={fps} max_frames={max_frames} → {out_dir}")
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
    )
    assert proc.stdout is not None
    frame_re = re.compile(r"^frame=(\d+)")
    last = 0
    for line in proc.stdout:
        m = frame_re.match(line.strip())
        if m:
            last = int(m.group(1))
            if on_progress:
                on_progress(last, expected or last)
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg exited {proc.returncode} extracting frames")

    frames = _collect_frames(out_dir, fps)
    log("extract", f"extracted {len(frames)} frame(s)")
    if on_progress:
        on_progress(len(frames), len(frames))
    return frames


def _collect_frames(out_dir: str, fps: float) -> list[Frame]:
    """Build the ordered Frame list from frame_%06d.jpg files in ``out_dir``."""
    if not os.path.isdir(out_dir):
        return []
    names = sorted(n for n in os.listdir(out_dir) if re.fullmatch(r"frame_\d+\.jpg", n))
    frames: list[Frame] = []
    for n in names:
        seq = int(re.search(r"\d+", n).group())  # 1-based ffmpeg sequence
        idx = seq - 1
        # fps frames per second → each frame is 1/fps seconds apart.
        timestamp = round(idx / fps, 3)
        frames.append(Frame(index=idx, timestamp=timestamp, path=os.path.join(out_dir, n)))
    return frames
