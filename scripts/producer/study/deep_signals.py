#!/usr/bin/env python3
"""deep_signals — P2: per-frame MOTION SIGNALS for the DEEP STUDY.

One streaming pass over downscaled grayscale frames computes every signal the
event detector reads, using techniques already proven in this repo's studies:

* ``d`` — frame-diff d-metric (mean abs diff vs the previous frame, 0-255).
* ``luma`` / ``darkFrac`` / ``brightFrac`` — global luma + dark/bright pixel
  fractions (fade / flash / palette evidence).
* ``panDx`` / ``panDy`` / ``panResp`` — cv2.phaseCorrelate global translation
  between consecutive frames (sub-pixel; sign = content-motion direction).
* ``faceX`` / ``faceW`` / ``facePresent`` — Haar frontal face track: largest
  face's normalised center-x + width fraction (the zoom proxy). Haar is
  frontal-only; absent faces read 0 — downstream treats it as a hint.
* freeze runs — spans where d <= freeze_eps (the YDIF==0 analogue).

Everything is arithmetic on pixels; no judgement calls live here.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motion.face_track import _load_cascade  # noqa: E402
from study.deep_config import DEEP  # noqa: E402
from study.deep_frames import VideoInfo, iter_gray  # noqa: E402


@dataclass
class SignalTrack:
    """Parallel per-frame arrays; frame i sits at t = i / fps."""

    fps: float
    width: int
    height: int
    d: list[float] = field(default_factory=list)
    luma: list[float] = field(default_factory=list)
    dark_frac: list[float] = field(default_factory=list)
    bright_frac: list[float] = field(default_factory=list)
    pan_dx: list[float] = field(default_factory=list)
    pan_dy: list[float] = field(default_factory=list)
    pan_resp: list[float] = field(default_factory=list)
    face_x: list[float] = field(default_factory=list)
    face_w: list[float] = field(default_factory=list)
    face_present: list[int] = field(default_factory=list)

    @property
    def frames(self) -> int:
        return len(self.d)

    def t(self, i: int) -> float:
        return round(i / self.fps, 4)

    def to_json(self) -> dict:
        r3 = lambda xs: [round(float(x), 3) for x in xs]  # noqa: E731
        return {"fps": self.fps, "frameCount": self.frames,
                "analysisWidth": self.width, "analysisHeight": self.height,
                "d": r3(self.d), "luma": r3(self.luma),
                "darkFrac": r3(self.dark_frac),
                "brightFrac": r3(self.bright_frac),
                "panDx": r3(self.pan_dx), "panDy": r3(self.pan_dy),
                "panResp": r3(self.pan_resp), "faceX": r3(self.face_x),
                "faceWidthFrac": r3(self.face_w),
                "facePresent": list(self.face_present)}


def _face_signal(gray: np.ndarray, cascade) -> tuple[float, float, int]:
    """(center_x_norm, width_frac, present) of the largest Haar face."""
    h, w = gray.shape[:2]
    min_side = max(16, int(w * DEEP["face_min_size_frac"]))
    boxes = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5,
                                     minSize=(min_side, min_side))
    if len(boxes) == 0:
        return 0.0, 0.0, 0
    x, _, bw, _ = max(boxes, key=lambda b: b[2] * b[3])
    return (x + bw / 2.0) / w, bw / float(w), 1


def _frame_stats(gray: np.ndarray) -> tuple[float, float, float]:
    """(mean luma, dark fraction, bright fraction) for one frame."""
    luma = float(gray.mean())
    dark = float((gray < DEEP["dark_luma"]).mean())
    bright = float((gray > DEEP["bright_luma"]).mean())
    return luma, dark, bright


def _pan_signal(prev32, cur32) -> tuple[float, float, float]:
    """Phase-correlation shift prev→cur: (dx, dy, response)."""
    (dx, dy), resp = cv2.phaseCorrelate(prev32, cur32)
    return float(dx), float(dy), float(resp)


def collect_signals(path: str, info: VideoInfo, fps: float) -> SignalTrack:
    """Stream the video once and fill every per-frame signal array."""
    width = DEEP["analysis_width"]
    cascade = _load_cascade()
    sig, prev, prev32 = None, None, None
    for gray in iter_gray(path, info, fps, width):
        if sig is None:
            sig = SignalTrack(fps=fps, width=gray.shape[1], height=gray.shape[0])
        cur32 = gray.astype(np.float32)
        sig.d.append(0.0 if prev is None else
                     float(np.abs(cur32 - prev32).mean()))
        luma, dark, bright = _frame_stats(gray)
        sig.luma.append(luma)
        sig.dark_frac.append(dark)
        sig.bright_frac.append(bright)
        dx, dy, resp = (0.0, 0.0, 1.0) if prev is None else _pan_signal(prev32, cur32)
        sig.pan_dx.append(dx)
        sig.pan_dy.append(dy)
        sig.pan_resp.append(resp)
        fx, fw, present = _face_signal(gray, cascade)
        sig.face_x.append(fx)
        sig.face_w.append(fw)
        sig.face_present.append(present)
        prev, prev32 = gray, cur32
    if sig is None or sig.frames < 2:
        raise RuntimeError(f"decoded fewer than 2 analysis frames from {path}")
    return sig


def freeze_runs(sig: SignalTrack) -> list[dict]:
    """Spans where d <= freeze_eps for >= freeze_min_frames (YDIF==0 spans)."""
    runs, start = [], None
    for i in range(1, sig.frames):
        frozen = sig.d[i] <= DEEP["freeze_eps"]
        if frozen and start is None:
            start = i
        if frozen:
            continue
        if start is not None and i - start >= DEEP["freeze_min_frames"]:
            runs.append({"startFrame": start, "frames": i - start,
                         "t": sig.t(start),
                         "durationS": round((i - start) / sig.fps, 3)})
        start = None
    if start is not None and sig.frames - start >= DEEP["freeze_min_frames"]:
        runs.append({"startFrame": start, "frames": sig.frames - start,
                     "t": sig.t(start),
                     "durationS": round((sig.frames - start) / sig.fps, 3)})
    return runs
