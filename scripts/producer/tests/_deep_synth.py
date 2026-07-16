#!/usr/bin/env python3
"""_deep_synth — synthetic ground-truth clip for the DEEP STUDY tests.

Renders a 12s 640x360@30 clip where every edit event is CONSTRUCTED with
known parameters, so test_study_deep can assert the pipeline recovers them:

  t=1.0   graphic-in   dark card + white "HELLO WORLD" (instant)
  t=2.5   graphic-out  card removed (instant)
  t=3.0   cut          texture A → texture B (hard)
  t=3.5   zoom-in      scale 1.00 → 1.25 over 30 frames, POWER3-OUT easing
  t=5.5   panel-in     solid panel SWEEPS from-left to 40% width in 18 frames
  t=6.2   graphic-in   white "POP" keyword pops top-right (instant, holds 1s)
  t=7.0   panel-out    panel removed (instant)
  t=7.2   graphic-out  "POP" removed (instant)
  t=7.5   freeze       one frame repeated 15x (14 zero-diff frames)
  t=8.0   pan          content shifts LEFT 40 px over 21 frames, BELL easing
  t=9.0   flash        2 pure-white frames
  t=9.8   graphic-in   dark caption bar (bottom band)
  t=10.0/10.4/10.8     words ONE / TWO / THREE land in the bar (per-word timing)
  t=11.3  cut          scale STEPS 1.25 → 1.50 in one frame (jump-cut punch;
                       must classify as a cut, NEVER an eased zoom)

Textures are seeded block noise (ORB-friendly corners); a small orbiting dot
keeps d > 0 outside the freeze so static spans never read as frozen. Encoded
x264 CRF 12, one keyframe (no mid-stream IDR jitter). GROUND_TRUTH captures
every constructed number the tests assert against.
"""

from __future__ import annotations

import math
import subprocess

import cv2
import numpy as np

W, H, FPS, DUR_S = 640, 360, 30, 12.0
CARD = (200, 120, 240, 120)          # x, y, w, h
BAR = (40, 300, 560, 52)
PANEL_FRAC_W = 0.40
ZOOM_SCALE = 1.25
PAN_PX = 40.0
SWEEP_FRAMES = 18
FREEZE_FRAMES = 15

JUMP_SCALE = 1.5                     # instant step from ZOOM_SCALE at 11.3

GROUND_TRUTH = {
    "cardInT": 1.0, "cardOutT": 2.5, "cardText": "HELLO WORLD",
    "cardBboxNorm": [CARD[0] / W, CARD[1] / H, CARD[2] / W, CARD[3] / H],
    "cutT": 3.0,
    "zoomT": 3.5, "zoomFrames": 30, "zoomMagnitude": ZOOM_SCALE - 1.0,
    "zoomEasing": "power3-out",
    "sweepT": 5.5, "sweepFrames": SWEEP_FRAMES, "sweepDirection": "from-left",
    "popT": 6.2, "popOutT": 7.2, "popText": "POP",
    "panelOutT": 7.0,
    "freezeT": 7.5, "freezeFrames": FREEZE_FRAMES,
    "panT": 8.0, "panPx": PAN_PX, "panDirection": "left", "panEasing": "bell",
    "flashT": 9.0,
    "barInT": 9.8,
    "wordsT": {"ONE": 10.0, "TWO": 10.4, "THREE": 10.8},
    "jumpCutT": 11.3,
    "jumpPunchPct": (JUMP_SCALE / ZOOM_SCALE - 1.0) * 100.0,
}


def _texture(seed: int) -> np.ndarray:
    """Seeded block-noise BGR texture (strong ORB corners at block edges)."""
    rs = np.random.RandomState(seed)
    small = rs.randint(40, 216, (H // 16, W // 16), dtype=np.uint8)
    up = cv2.resize(small, (W, H), interpolation=cv2.INTER_NEAREST)
    return cv2.cvtColor(up, cv2.COLOR_GRAY2BGR)


def _warp(base: np.ndarray, scale: float, shift_x: float) -> np.ndarray:
    """Zoom about center by ``scale`` then shift content left by ``shift_x``."""
    cx, cy = W / 2.0, H / 2.0
    m = np.float32([[scale, 0, cx * (1 - scale) - shift_x],
                    [0, scale, cy * (1 - scale)]])
    return cv2.warpAffine(base, m, (W, H), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_REFLECT)


def _smoothstep(u: float) -> float:
    return u * u * (3.0 - 2.0 * u)


def _zoom_scale_at(t: float) -> float:
    """Scale path: power3-out ramp to 1.25 at 3.5, INSTANT step to 1.5 at
    11.3 (the jump-cut punch — a step, never an eased zoom)."""
    if t < 3.5:
        return 1.0
    if t >= 11.3:
        return JUMP_SCALE
    u = min(1.0, (t - 3.5) / 1.0)
    return 1.0 + (ZOOM_SCALE - 1.0) * (1.0 - (1.0 - u) ** 3)


def _pan_shift_at(t: float) -> float:
    """Content shift (px, leftward) — smoothstep 0→PAN_PX over 8.0-8.7s."""
    if t < 8.0:
        return 0.0
    u = min(1.0, (t - 8.0) / 0.7)
    return PAN_PX * _smoothstep(u)


def _put_text(frame: np.ndarray, text: str, org: tuple) -> None:
    cv2.putText(frame, text, org, cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                (245, 245, 245), 2, cv2.LINE_AA)


def _overlays(frame: np.ndarray, t: float) -> None:
    """Draw the card / panel / bar / words active at time t (in place)."""
    if 1.0 <= t < 2.5:
        x, y, w, h = CARD
        frame[y:y + h, x:x + w] = (18, 18, 18)
        _put_text(frame, "HELLO WORLD", (x + 18, y + h // 2 + 10))
    if 5.5 <= t < 7.0:
        u = min(1.0, (t - 5.5) * FPS / SWEEP_FRAMES)
        edge = int(W * PANEL_FRAC_W * u)
        frame[:, :edge] = (60, 60, 60)
    if 6.2 <= t < 7.2:
        _put_text(frame, "POP", (440, 70))
    if t >= 9.8:
        x, y, w, h = BAR
        frame[y:y + h, x:x + w] = (22, 22, 22)
        for k, (word, t_in) in enumerate(GROUND_TRUTH["wordsT"].items()):
            if t >= t_in:
                _put_text(frame, word, (x + 20 + k * 170, y + 38))


def _dot(frame: np.ndarray, i: int) -> None:
    """Small orbiting dot: keeps d>0 on otherwise static spans."""
    ang = i * 0.12
    x = int(70 + 26 * math.cos(ang))
    y = int(70 + 26 * math.sin(ang))
    cv2.rectangle(frame, (x, y), (x + 10, y + 10), (250, 250, 250), -1)


def build_frames() -> list[np.ndarray]:
    """Every frame of the clip, ground truth baked in."""
    tex_a, tex_b = _texture(1), _texture(2)
    frames: list[np.ndarray] = []
    frozen: "np.ndarray | None" = None
    for i in range(int(DUR_S * FPS)):
        t = i / FPS
        if 7.5 <= t < 7.5 + FREEZE_FRAMES / FPS:
            if frozen is None:
                frozen = frames[-1].copy()
            frames.append(frozen)
            continue
        if 9.0 <= t < 9.0 + 2.0 / FPS:
            frames.append(np.full((H, W, 3), 255, dtype=np.uint8))
            continue
        base = tex_a if t < 3.0 else tex_b
        frame = _warp(base, _zoom_scale_at(t), _pan_shift_at(t)) \
            if t >= 3.0 else base.copy()
        _overlays(frame, t)
        _dot(frame, i)
        frames.append(frame)
    return frames


def write_video(path: str) -> None:
    """Encode the synthetic clip (x264 CRF 12, single keyframe)."""
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo",
           "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", "pipe:0", "-c:v", "libx264", "-crf", "12", "-g", "999",
           "-x264-params", "scenecut=0", "-pix_fmt", "yuv420p", path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    assert proc.stdin is not None
    for frame in build_frames():
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg failed encoding the synthetic deep clip")


def synthetic_words() -> list[dict]:
    """A word list whose boundaries land exactly on known event times."""
    return [
        {"word": "hello", "start": 0.55, "end": 1.0},
        {"word": "cut", "start": 2.6, "end": 3.0},
        {"word": "zoom", "start": 3.5, "end": 3.9},
        {"word": "panel", "start": 5.1, "end": 5.5},
        {"word": "flash", "start": 8.96, "end": 9.3},
    ]
