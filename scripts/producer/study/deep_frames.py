#!/usr/bin/env python3
"""deep_frames — frame decoding for the DEEP STUDY passes (ffmpeg rawvideo).

Two access patterns, both deterministic and memory-safe:

* ``iter_gray`` — stream the WHOLE video as downscaled grayscale frames, one at
  a time (the P2 signals pass keeps only the previous frame).
* ``decode_window`` — re-decode a short window around a detected event at a
  chosen width/pixel format (the P3/P4 classification passes touch only the
  frames they need — a 10-minute source never sits in RAM).

Dims are DISPLAY dims (``cut_speed.display_dims`` — rotation side data swaps
the canvas, ffmpeg autorotates; edge I9). Fail loudly on unreadable sources.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audit.audit_probe import ffprobe_json, first_stream  # noqa: E402
from cut_speed import display_dims  # noqa: E402


@dataclass(frozen=True)
class VideoInfo:
    """Probed source geometry/timing (display-oriented)."""

    width: int
    height: int
    fps: float
    duration: float


@dataclass(frozen=True)
class Window:
    """One decode request: [t0, t1) sampled at ``fps``, ``width`` px wide.

    ``width=None`` decodes at native resolution (used for OCR windows).
    """

    t0: float
    t1: float
    fps: float
    width: "int | None" = None


def _parse_rate(rate: str) -> float:
    """'30000/1001' → 29.97; fail loudly on garbage."""
    num, _, den = (rate or "").partition("/")
    value = float(num) / float(den or 1)
    if value <= 0:
        raise ValueError(f"non-positive frame rate: {rate!r}")
    return value


def probe_video(path: str) -> VideoInfo:
    """Display dims + fps + duration for ``path`` (raises when unreadable)."""
    probe = ffprobe_json(path)
    stream = first_stream(probe, "video")
    if stream is None:
        raise RuntimeError(f"no video stream in {path}")
    width, height = display_dims(stream)
    fps = _parse_rate(stream.get("avg_frame_rate")
                      or stream.get("r_frame_rate") or "")
    duration = float(stream.get("duration")
                     or probe.get("format", {}).get("duration") or 0.0)
    if duration <= 0:
        raise RuntimeError(f"cannot read duration for {path}")
    return VideoInfo(width=width, height=height, fps=round(fps, 4),
                     duration=round(duration, 4))


def scaled_dims(info: VideoInfo, width: "int | None") -> tuple[int, int]:
    """Even-snapped (w, h) for an analysis decode at ``width`` (None=native)."""
    if width is None or width >= info.width:
        return info.width, info.height
    h = max(2, int(round(info.height * width / info.width / 2.0)) * 2)
    return width, h


def _decode_cmd(path: str, win: Window, dims: tuple[int, int],
                pix_fmt: str) -> list[str]:
    """The ffmpeg rawvideo pipe command for one window."""
    vf = f"fps={win.fps},scale={dims[0]}:{dims[1]}"
    cmd = ["ffmpeg", "-v", "error"]
    if win.t0 > 0:
        cmd += ["-ss", f"{win.t0:.6f}"]
    cmd += ["-i", path, "-t", f"{max(0.0, win.t1 - win.t0):.6f}", "-vf", vf,
            "-f", "rawvideo", "-pix_fmt", pix_fmt, "pipe:1"]
    return cmd


def _frame_shape(dims: tuple[int, int], pix_fmt: str) -> tuple:
    """(numpy shape, bytes per frame) for a rawvideo pixel format."""
    w, h = dims
    if pix_fmt == "gray":
        return (h, w), w * h
    if pix_fmt == "bgr24":
        return (h, w, 3), w * h * 3
    raise ValueError(f"unsupported pix_fmt: {pix_fmt}")


def iter_frames(path: str, win: Window, info: VideoInfo, pix_fmt: str = "gray"):
    """Yield frames of one Window as numpy arrays, streaming (no full buffer)."""
    dims = scaled_dims(info, win.width)
    shape, nbytes = _frame_shape(dims, pix_fmt)
    proc = subprocess.Popen(_decode_cmd(path, win, dims, pix_fmt),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdout is not None
    try:
        while True:
            buf = proc.stdout.read(nbytes)
            if len(buf) < nbytes:
                break
            yield np.frombuffer(buf, dtype=np.uint8).reshape(shape)
    finally:
        proc.stdout.close()
        stderr = b""
        if proc.stderr is not None:
            stderr = proc.stderr.read()
            proc.stderr.close()
        stderr_text = stderr.decode("utf-8", "replace")
        if proc.wait() != 0:
            raise RuntimeError(f"ffmpeg decode failed on {path}: "
                               f"{stderr_text.strip()[-300:] or 'no stderr'}")


def decode_window(path: str, win: Window, info: VideoInfo,
                  pix_fmt: str = "gray") -> list[np.ndarray]:
    """All frames of one short window as a list (bounded by the window)."""
    return list(iter_frames(path, win, info, pix_fmt))


def iter_gray(path: str, info: VideoInfo, fps: float, width: int):
    """Stream the whole video as grayscale analysis frames."""
    win = Window(t0=0.0, t1=info.duration + 1.0, fps=fps, width=width)
    return iter_frames(path, win, info, "gray")
