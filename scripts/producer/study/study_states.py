#!/usr/bin/env python3
"""study_states — unique on-screen visual states + per-state signals (STUDY verb).

The brain can't vision-review 130 near-identical frames; it wants ONE
representative per distinct on-screen state, each tagged with cheap deterministic
signals so it knows what to look at. This module reuses the FRAME.IO REVIEW
machinery verbatim — ``extract`` (ffmpeg → 1 JPG per 1/fps second) + ``dedup``
(perceptual-hash collapse, settled-frame representative) — then, per kept state,
fuses the producer's existing face / screen-content detectors (``visual_state``)
with mean-luma (``audit_probe``) and a top-3 dominant-colour readout (PIL
quantize). The representative JPGs are copied into ``<out_dir>/states/`` — those
are exactly the images the editor brain vision-reviews for layout / graphics /
caption style.

Signals are deterministic hints, NOT classifications of graphics/layout — that
judgement is brain-side, per the STUDY design. Haar is frontal-only (turned or
tiny corner-cam faces are missed); every state carries its raw numbers so the
brain can override. Uses cv2 + PIL — run with the venv python.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field

_PRODUCER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ROOT = os.path.dirname(os.path.dirname(_PRODUCER_DIR))   # PROJECT_SNIPER root
sys.path.insert(0, _PRODUCER_DIR)
sys.path.insert(0, _ROOT)

import cv2  # noqa: E402
from PIL import Image  # noqa: E402

from scripts.frameio.extract import extract_frames  # noqa: E402
from scripts.frameio.dedup import KeptFrame, dedup_frames  # noqa: E402
from audit.audit_probe import mean_luma  # noqa: E402
from motion.face_track import _load_cascade  # noqa: E402
from motion.visual_state import (  # noqa: E402
    VISUAL_STATE, _busy_cell_fraction, _largest_face, _resolve_cfg,
)

DEFAULT_FPS = 2.0
DEFAULT_DEDUP_THRESHOLD = 6      # pHash Hamming gate; a touch looser than QC's 5
DOMINANT_COLORS = 3             # top-N palette entries per representative
# Face/edge detection runs on a downscaled copy (all signals are ratios or the
# busy-scan downscales itself). Keeps 4K reference footage tractable — Haar on a
# native 3840px frame is ~16x the work of a 960px one for identical bboxes.
ANALYSIS_MAX_W = 1280


@dataclass
class StudyState:
    """One distinct on-screen state, with its deterministic signals."""

    index: int
    t_start: float
    t_end: float
    duration: float
    frames_held: int             # source frames collapsed into this state
    rep_path: str                # JPG in <out_dir>/states/
    phash: str
    face_present: bool
    face_area_frac: float        # face box / frame area (0 if none)
    face_prominent: bool
    face_bbox_norm: list | None  # [x,y,w,h] normalised, or None
    busy_frac: float             # screen-content spread (0-1)
    mean_luma: float | None      # 0-255
    dominant_colors: list = field(default_factory=list)   # ["#rrggbb", ...]


def _dominant_colors(path: str, n: int = DOMINANT_COLORS) -> list[str]:
    """Top-``n`` colours as hex via PIL adaptive quantize (most-frequent first)."""
    try:
        with Image.open(path) as image:
            small = image.convert("RGB").resize((160, 284))   # cheap, keeps 9:16
            quant = small.quantize(colors=16, method=Image.Quantize.FASTOCTREE)
            palette = quant.getpalette() or []
            counts = sorted(quant.getcolors() or [], reverse=True)
    except (OSError, ValueError):
        return []
    hexes: list[str] = []
    for _, idx in counts[:n]:
        r, g, b = palette[idx * 3:idx * 3 + 3]
        hexes.append(f"#{r:02x}{g:02x}{b:02x}")
    return hexes


def _load_for_analysis(path: str):
    """Read a representative JPG (BGR), downscaled to ``ANALYSIS_MAX_W`` wide.

    Signals derived from it are all scale-invariant (face_area/bbox are ratios,
    the busy-scan downscales again internally), so working at capped width keeps
    4K reference footage fast without changing the numbers materially.
    """
    frame = cv2.imread(path)
    if frame is None:
        return None
    w = frame.shape[1]
    if w > ANALYSIS_MAX_W:
        scale = ANALYSIS_MAX_W / float(w)
        frame = cv2.resize(frame, (ANALYSIS_MAX_W, int(frame.shape[0] * scale)))
    return frame


def _state_signals(rep: KeptFrame, cfg: dict, cascade, index: int,
                   states_dir: str) -> StudyState:
    """Compute all per-state signals for one kept representative frame."""
    dst = os.path.join(states_dir,
                       f"state_{index:03d}_t{rep.t_start:07.2f}.jpg")
    shutil.copyfile(rep.path, dst)
    frame = _load_for_analysis(rep.path)
    face_area, busy, bbox_norm, present = 0.0, 0.0, None, False
    if frame is not None:
        h, w = frame.shape[:2]
        busy = round(_busy_cell_fraction(frame, cfg), 3)
        box = _largest_face(frame, cascade, cfg)
        if box is not None and w and h:
            present = True
            face_area = round((box[2] * box[3]) / float(w * h), 4)
            bbox_norm = [round(box[0] / w, 4), round(box[1] / h, 4),
                         round(box[2] / w, 4), round(box[3] / h, 4)]
    return StudyState(
        index=index, t_start=round(rep.t_start, 2), t_end=round(rep.t_end, 2),
        duration=round(rep.t_end - rep.t_start, 2), frames_held=rep.duplicates + 1,
        rep_path=dst, phash=rep.phash, face_present=present,
        face_area_frac=face_area,
        face_prominent=present and face_area >= VISUAL_STATE["face_prominent_area"],
        face_bbox_norm=bbox_norm, busy_frac=busy, mean_luma=mean_luma(rep.path),
        dominant_colors=_dominant_colors(dst))


def analyze_states(video_path: str, out_dir: str, fps: float = DEFAULT_FPS,
                   threshold: int = DEFAULT_DEDUP_THRESHOLD) -> list[StudyState]:
    """Extract → dedup → per-state signals. Returns states in time order.

    Raw frames cache under ``<out_dir>/frames/`` (reused on a re-run, same as the
    QC tool); representatives land in ``<out_dir>/states/``.
    """
    frames_dir = os.path.join(out_dir, "frames")
    states_dir = os.path.join(out_dir, "states")
    os.makedirs(states_dir, exist_ok=True)
    frames = extract_frames(video_path, frames_dir, fps=fps)
    kept = dedup_frames(frames, threshold=threshold)
    cfg = _resolve_cfg()
    cascade = _load_cascade()
    return [_state_signals(rep, cfg, cascade, i, states_dir)
            for i, rep in enumerate(kept)]
