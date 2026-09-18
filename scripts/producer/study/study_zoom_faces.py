#!/usr/bin/env python3
"""study_zoom_faces — per-frame face-area time series via YuNet (STUDY verb).

The ZOOM MAP needs a fine-grained framing signal: how big is the presenter's
face, frame by frame, across the whole edited cut. On a locked-camera talking
head the ONLY thing that changes face size is an EDIT decision — a punch-in cut
or an animated push/pull — so a face-area timeline is a direct readout of the
editor's zoom choices (docs/studies/LONGFORM_VISUAL_STUDY.md).

This samples a directory of pre-extracted JPGs (``frame_%06d.jpg`` /
``f_%06d.jpg`` at a known fps) and, per frame, runs YuNet
(``cv2.FaceDetectorYN``) and records the LARGEST face's area fraction + centre.
Largest-area = the primary subject (a stand-in for "the presenter"); tiny
background detections lose to it. Frames with no face score 0.0 area and
``present=false`` — those are cutaways / b-roll for the downstream b-roll map.

YuNet (not Haar) on purpose: it holds through the small head turns a talking
head makes, where a frontal Haar detector drops out and injects fake area
steps. Area is a ratio, so a downscaled analysis frame yields the same number
as the native one. Uses cv2 — run with the venv python.

CLI: study_zoom_faces.py <frames_dir> <out.json> [--fps 5] [--score 0.6]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass

import cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from producer_config import FACE_TRACK  # noqa: E402

_FRAME_RE = re.compile(r"(?:frame|f)_(\d+)\.jpg$")
DEFAULT_FPS = 5.0
# A touch below the reframe stage's 0.7: the study wants to KEEP a slightly
# soft/turned face in the series (so a shot doesn't read as a false cutaway)
# rather than drop it. Low-score detections are recorded with their score so a
# consumer can re-threshold without re-running.
DEFAULT_SCORE = 0.6


@dataclass
class FaceSample:
    """One frame's dominant-face measurement (area as a fraction of frame)."""

    t: float             # seconds into the source
    present: bool        # a face cleared the score gate
    area: float          # largest-face box area / frame area (0.0 if none)
    cx: float            # face-centre x, normalised 0..1 (0.5 if none)
    cy: float            # face-centre y, normalised 0..1 (0.5 if none)
    score: float         # YuNet detection score of that face (0.0 if none)
    n_faces: int         # faces above the gate in the frame


def _resolve_model() -> str:
    """Path to the YuNet .onnx (env override wins), or raise if absent."""
    model = os.environ.get("PRODUCER_YUNET_MODEL") or FACE_TRACK.get("yunet_model_path")
    if not model or not os.path.exists(model):
        raise RuntimeError(f"YuNet model not found: {model!r}")
    return model


def _frame_files(frames_dir: str) -> list[tuple[int, str]]:
    """(sequence, path) for every ``frame_N.jpg`` / ``f_N.jpg``, time-ordered."""
    out: list[tuple[int, str]] = []
    for name in os.listdir(frames_dir):
        m = _FRAME_RE.search(name)
        if m:
            out.append((int(m.group(1)), os.path.join(frames_dir, name)))
    out.sort(key=lambda p: p[0])
    return out


def _largest_face(detector: "cv2.FaceDetectorYN", frame) -> "FaceSample | None":
    """Dominant (largest-area) YuNet face in a BGR frame, or None."""
    h, w = frame.shape[:2]
    detector.setInputSize((w, h))
    _, faces = detector.detect(frame)
    if faces is None or len(faces) == 0:
        return None
    best = max(faces, key=lambda f: float(f[2]) * float(f[3]))
    fw, fh = float(best[2]), float(best[3])
    return FaceSample(
        t=0.0, present=True, area=round((fw * fh) / float(w * h), 5),
        cx=round((float(best[0]) + fw / 2.0) / w, 4),
        cy=round((float(best[1]) + fh / 2.0) / h, 4),
        score=round(float(best[14]), 3), n_faces=len(faces))


def sample_face_areas(frames_dir: str, fps: float, score: float) -> list[FaceSample]:
    """Face-area series over every extracted frame (time-ordered)."""
    model = _resolve_model()
    detector = cv2.FaceDetectorYN.create(model, "", (320, 320), score_threshold=score)
    files = _frame_files(frames_dir)
    if not files:
        raise RuntimeError(f"no frame_*.jpg / f_*.jpg in {frames_dir}")
    samples: list[FaceSample] = []
    for i, (seq, path) in enumerate(files):
        t = round((seq - 1) / fps, 3)
        frame = cv2.imread(path)
        if frame is None:
            samples.append(FaceSample(t, False, 0.0, 0.5, 0.5, 0.0, 0))
            continue
        hit = _largest_face(detector, frame)
        if hit is None:
            samples.append(FaceSample(t, False, 0.0, 0.5, 0.5, 0.0, 0))
        else:
            hit.t = t
            samples.append(hit)
        if i % 500 == 0:
            print(json.dumps({"status": "sampling", "done": i, "total": len(files)}),
                  flush=True)
    return samples


def main() -> int:
    parser = argparse.ArgumentParser(description="YuNet face-area time series")
    parser.add_argument("frames_dir")
    parser.add_argument("out_json")
    parser.add_argument("--fps", type=float, default=DEFAULT_FPS)
    parser.add_argument("--score", type=float, default=DEFAULT_SCORE)
    args = parser.parse_args()
    try:
        samples = sample_face_areas(args.frames_dir, args.fps, args.score)
    except RuntimeError as exc:
        print(json.dumps({"error": str(exc)}), flush=True)
        return 1
    with open(args.out_json, "w") as handle:
        json.dump({"fps": args.fps, "score": args.score,
                   "samples": [asdict(s) for s in samples]}, handle)
    present = sum(1 for s in samples if s.present)
    print(json.dumps({"status": "done", "frames": len(samples),
                      "facePresent": present,
                      "faceRate": round(present / len(samples), 3)}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
