#!/usr/bin/env python3
"""face_track — per-shot face crop windows for the 9:16 reframe (stage 2).

For every segment of a compiled ``timeline_map.json`` (each segment is one
*shot*), this samples a handful of frames, detects the dominant face, and emits
ONE static crop window for the whole shot. Static-per-shot is deliberate: a
window that never moves reads as an intentional framing choice, whereas
per-frame tracking jitters (docs/producer/PRODUCER_PLAN.md §4.2).

Coordinate contract (IMPORTANT, and a deliberate deviation from the naive
"detect on the raw source" reading of the spec): the ``<video.mp4>`` handed in
is the **stage-1 mezzanine** — the single concatenated cut+speed file that
``reframe.py`` will actually crop. Shots are located in it by their OUTPUT time
range (``out_start``/``out_end`` from the timeline map), and ``cropCenterX`` is
a pixel coordinate in THAT video's frame. Detecting on the mezzanine at output
ranges is the only self-consistent choice: the crop is applied to the mezzanine
at the mezzanine's resolution, so its center must be measured there. On a
single-source short with no rescale the mezzanine and the raw source share a
coordinate space, so this also matches "source coords" in that common case.

Detector shipped: OpenCV's bundled Haar cascade
(``haarcascade_frontalface_default.xml`` via ``cv2.data.haarcascades``). YuNet
(``cv2.FaceDetectorYN``) is used instead when a model path is configured
(``FACE_TRACK['yunet_model_path']`` or ``$PRODUCER_YUNET_MODEL``) — its .onnx
weights are not bundled with the wheel, so Haar is the default.

CLI: face_track.py <video.mp4> <timeline_map.json> <out_windows.json>
"""

from __future__ import annotations

import json
import os
import statistics
import sys
from typing import TYPE_CHECKING, Callable, Optional

import cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # run-by-path: producer pkg root on sys.path
from compile_timeline import Segment, TimelineMap
from producer_config import FACE_TRACK

if TYPE_CHECKING:  # annotation-only; MatLike/DetectFn are never used at runtime
    from cv2.typing import MatLike

    # A frame detector: (center_x, n_faces) for the primary face, or None.
    DetectFn = Callable[[MatLike], Optional[tuple[float, int]]]


# --------------------------------------------------------------------------- #
# Pure geometry (no OpenCV) — unit-testable crop math + clamping.
# --------------------------------------------------------------------------- #
def _even(n: float) -> int:
    """Round to the nearest even int (yuv420p needs even dimensions)."""
    return int(round(n / 2.0)) * 2


def is_portrait(frame_w: int, frame_h: int) -> bool:
    """True when the frame is already taller than wide (already ~vertical)."""
    return frame_h > frame_w


def crop_width_for(frame_h: int, cfg: dict = FACE_TRACK) -> int:
    """Width of a full-height 9:16 crop of a frame ``frame_h`` px tall (even)."""
    return _even(frame_h * cfg["crop_aspect_w"] / cfg["crop_aspect_h"])


def clamp_center_x(center_x: float, crop_w: int, frame_w: int) -> int:
    """Clamp a crop center so the window never leaves the frame."""
    half = crop_w / 2.0
    return int(round(min(max(center_x, half), frame_w - half)))


def compute_crop_window(frame_w: int, frame_h: int, center_x: float,
                        cfg: dict = FACE_TRACK) -> dict:
    """Concrete crop for a landscape/square frame at a desired ``center_x``.

    Returns ``cropWidth`` (full frame height, 9:16), the clamped ``cropCenterX``
    and the top-left ``cropX``. Portrait frames are handled upstream
    (``portrait-passthrough``); calling this on one still yields a valid,
    clamped window but the caller should prefer passthrough.
    """
    crop_w = min(crop_width_for(frame_h, cfg), _even(frame_w))
    cx = clamp_center_x(center_x, crop_w, frame_w)
    crop_x = _even(min(max(cx - crop_w / 2.0, 0), frame_w - crop_w))
    return {"cropWidth": crop_w, "cropCenterX": cx, "cropX": crop_x}


# --------------------------------------------------------------------------- #
# Detection (OpenCV) — Haar cascade by default, YuNet when a model is present.
# --------------------------------------------------------------------------- #
def _load_cascade() -> cv2.CascadeClassifier:
    """Load the bundled frontal-face Haar cascade (raises if missing)."""
    path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
    cascade = cv2.CascadeClassifier(path)
    if cascade.empty():
        raise RuntimeError(f"failed to load Haar cascade at {path}")
    return cascade


def _primary_center_haar(frame: MatLike, cascade: cv2.CascadeClassifier,
                         cfg: dict) -> Optional[tuple[float, int]]:
    """Center-x of the largest detected face + total face count, or None.

    The largest face is treated as the primary subject — a stand-in for
    confidence, since Haar gives no calibrated score. ``detectMultiScale`` is
    run on greyscale for speed.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    min_side = int(cfg["haar_min_size_frac"] * frame.shape[0])
    faces = cascade.detectMultiScale(
        gray, scaleFactor=cfg["haar_scale_factor"],
        minNeighbors=cfg["haar_min_neighbors"],
        minSize=(min_side, min_side))
    if len(faces) == 0:
        return None
    x, _, w, _ = max(faces, key=lambda r: int(r[2]) * int(r[3]))
    return (x + w / 2.0, len(faces))


def _make_yunet(model_path: str, cfg: dict) -> "cv2.FaceDetectorYN":
    """Build a YuNet detector; input size is set per-frame before detect."""
    return cv2.FaceDetectorYN.create(
        model_path, "", (320, 320),
        score_threshold=cfg["yunet_score_threshold"])


def _primary_center_yunet(frame: MatLike, detector: "cv2.FaceDetectorYN",
                          _cfg: dict) -> Optional[tuple[float, int]]:
    """Center-x of the highest-score YuNet face + face count, or None."""
    h, w = frame.shape[:2]
    detector.setInputSize((w, h))
    _, faces = detector.detect(frame)
    if faces is None or len(faces) == 0:
        return None
    best = max(faces, key=lambda f: float(f[14]))  # col 14 = detection score
    return (float(best[0]) + float(best[2]) / 2.0, len(faces))


def _resolve_detector(
    cfg: dict,
) -> tuple["DetectFn", str, "cv2.CascadeClassifier | cv2.FaceDetectorYN"]:
    """Pick YuNet (if a model path resolves) else the bundled Haar cascade.

    Returns ``(detect_fn, backend, detector_obj)`` where ``detect_fn(frame)``
    yields ``(center_x, n_faces) | None``.
    """
    model = os.environ.get("PRODUCER_YUNET_MODEL") or cfg.get("yunet_model_path")
    if model and os.path.exists(model):
        det = _make_yunet(model, cfg)
        return (lambda f: _primary_center_yunet(f, det, cfg)), "yunet", det
    cascade = _load_cascade()
    return (lambda f: _primary_center_haar(f, cascade, cfg)), "haar", cascade


# --------------------------------------------------------------------------- #
# Sampling + per-segment analysis.
# --------------------------------------------------------------------------- #
def _sample_times(out_start: float, out_end: float, n: int) -> list[float]:
    """``n`` timestamps evenly spaced *inside* [out_start, out_end]."""
    if n <= 1:
        return [(out_start + out_end) / 2.0]
    span = out_end - out_start
    return [out_start + span * (i + 0.5) / n for i in range(n)]


def _read_at(cap: "cv2.VideoCapture", t_s: float) -> "Optional[MatLike]":
    """Seek to ``t_s`` seconds and read one frame (returns frame or None)."""
    cap.set(cv2.CAP_PROP_POS_MSEC, t_s * 1000.0)
    ok, frame = cap.read()
    return frame if ok and frame is not None else None


def analyze_segment(cap: "cv2.VideoCapture", seg: Segment,
                    frame_size: tuple[int, int], detect_fn: "DetectFn") -> dict:
    """Sample the shot, decide face vs center, and build its crop window."""
    cfg = FACE_TRACK
    centers: list[float] = []
    multi_face = False
    for t in _sample_times(seg.out_start, seg.out_end, cfg["samples_per_segment"]):
        frame = _read_at(cap, t)
        if frame is None:
            continue
        hit = detect_fn(frame)
        if hit is None:
            continue
        centers.append(hit[0])
        multi_face = multi_face or hit[1] > 1
    entry = _decide_window(seg, frame_size, centers, cfg)
    if multi_face:
        entry["multiFace"] = True
    return entry


def _decide_window(seg: Segment, frame_size: tuple[int, int],
                   centers: list[float], cfg: dict) -> dict:
    """Turn sampled centers into a window (portrait / face / center)."""
    frame_w, frame_h = frame_size
    base = {"segmentIndex": seg.index, "sourceId": seg.source_id,
            "outStart": seg.out_start, "outEnd": seg.out_end,
            "frameWidth": frame_w, "frameHeight": frame_h}
    n = cfg["samples_per_segment"]
    rate = round(len(centers) / n, 3)
    if is_portrait(frame_w, frame_h):
        return {**base, "strategy": "portrait-passthrough",
                "cropCenterX": frame_w // 2,
                "cropWidth": _even(frame_w), "cropX": 0, "confidence": 1.0}
    unstable = (len(centers) >= 2
                and (max(centers) - min(centers)) > cfg["max_centerx_spread_frac"] * frame_w)
    if len(centers) < cfg["min_face_samples"] or unstable:
        win = compute_crop_window(frame_w, frame_h, frame_w / 2.0, cfg)
        entry = {**base, "strategy": "center", **win, "confidence": rate}
        if unstable and len(centers) >= cfg["min_face_samples"]:
            entry["lowConfidence"] = True   # faces seen but too jittery to anchor
        return entry
    win = compute_crop_window(frame_w, frame_h, statistics.median(centers), cfg)
    return {**base, "strategy": "face", **win, "confidence": rate}


def build_windows(video_path: str, tmap: TimelineMap) -> list[dict]:
    """Detect a crop window for every segment of the timeline map."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {video_path}")
    try:
        frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if frame_w <= 0 or frame_h <= 0:
            raise RuntimeError("video reports non-positive dimensions")
        detect_fn, _backend, _det = _resolve_detector(FACE_TRACK)
        return [analyze_segment(cap, seg, (frame_w, frame_h), detect_fn)
                for seg in tmap.segments]
    finally:
        cap.release()


def detector_backend() -> str:
    """Report which detector would be used ('yunet' or 'haar') — for status."""
    return _resolve_detector(FACE_TRACK)[1]


def main() -> None:
    if len(sys.argv) != 4:
        print(json.dumps({"error": "Usage: face_track.py <video.mp4> "
                                    "<timeline_map.json> <out_windows.json>"}))
        sys.exit(1)
    try:
        with open(sys.argv[2]) as f:
            tmap = TimelineMap.from_dict(json.load(f))
        windows = build_windows(sys.argv[1], tmap)
        with open(sys.argv[3], "w") as f:
            json.dump(windows, f, indent=2)
        faces = sum(1 for w in windows if w["strategy"] == "face")
        print(json.dumps({"status": "done", "backend": detector_backend(),
                          "segments": len(windows), "faceWindows": faces,
                          "centerFallbacks": len(windows) - faces}))
    except (OSError, json.JSONDecodeError, KeyError, RuntimeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
