"""Faces per sampled source frame, in source pixels, and contact sheets of the face crops (P2-06).

The sampled frames are decoded once with the shared streamed selected-frame reader
(``native_selected_frames.compare_selected_frames``). One RGB frame is held at a time and nothing
decoded is written to disk. Detection runs on a copy scaled to at most ``DETECTION_WIDTH`` pixels
wide. ``face_rows`` maps every box back to source pixels and keeps only faces at or above the
``FACE_TRACK`` score threshold. Contact-sheet tiles are cut from the full-resolution frame.

A sheet shows, for each retained range of a clip, its first frame, then a sampled frame at least
``SHEET_SPACING_SECONDS`` after the previous one, then its last frame. Each tile is one face crop at
480 px (or the whole frame when no face was found), labelled with source seconds and frame index.
Tiles are cues for the person or agent who attributes speech; they are not attribution.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from cut_preview_io import real_directory
from producer_config import FACE_TRACK
from studio.native_runtime import digest as file_digest
from studio.native_selected_frames import compare_selected_frames
from studio.native_speaker_sampling import frame_selection
from studio.native_stage_evidence import require

DETECTION_WIDTH = 1280
TILE = 480
COLUMNS, ROWS = 4, 3
SHEET_SPACING_SECONDS = 1.0
CROP_MARGIN = 0.25
BOX_KEYS = ('x', 'y', 'w', 'h')


def face_rows(frames: list[dict], detect: Callable[[dict], list[dict]]) -> list[dict]:
    """Every face above the FACE_TRACK score threshold per sampled frame, in source pixels.

    Args:
        frames: ``{frame, t, scale: [x, y]}`` rows; ``scale`` is source pixels per detection pixel.
        detect: Returns ``{x, y, w, h, score}`` boxes in detection pixels for one frame row.

    Returns:
        ``{frame, t, faces: [{x, y, w, h, score}]}`` rows; faces ordered left to right.

    Raises:
        ValueError: A box is not finite with a positive size, or a score is not a number.
    """
    threshold = float(FACE_TRACK['yunet_score_threshold'])
    rows = []
    for row in frames:
        scale_x, scale_y = row['scale']
        faces = [_source_box(face, scale_x, scale_y) for face in detect(row) if _score(face) >= threshold]
        rows.append({'frame': row['frame'], 't': row['t'], 'faces': sorted(faces, key=lambda f: (f['x'], f['y']))})
    return rows


def _score(face: dict) -> float:
    """A detection's score as a finite float."""
    score = face.get('score')
    if type(score) not in (int, float) or not np.isfinite(score):
        raise ValueError(f'Face detection score must be a finite number, not {score!r}')
    return float(score)


def _source_box(face: dict, scale_x: float, scale_y: float) -> dict:
    """One detection-pixel box mapped to source pixels."""
    values = [face.get(key) for key in BOX_KEYS]
    if not all(type(value) in (int, float) and np.isfinite(value) for value in values) or min(values[2:]) <= 0:
        raise ValueError(f'Face box must hold finite x, y and a positive w, h: {face!r}')
    x, y, w, h = values
    return {'x': round(x * scale_x, 1), 'y': round(y * scale_y, 1), 'w': round(w * scale_x, 1),
            'h': round(h * scale_y, 1), 'score': round(_score(face), 4)}


def detection_image(bgr: np.ndarray) -> tuple[np.ndarray, list[float]]:
    """The frame scaled to at most DETECTION_WIDTH wide, and source pixels per detection pixel."""
    height, width = bgr.shape[:2]
    if width <= DETECTION_WIDTH:
        return bgr, [1.0, 1.0]
    size = (DETECTION_WIDTH, max(1, round(height * DETECTION_WIDTH / width)))
    return cv2.resize(bgr, size, interpolation=cv2.INTER_AREA), [width / size[0], height / size[1]]


def face_detector(model: Path, threshold: float) -> Callable[[np.ndarray], list[dict]]:
    """YuNet over a BGR image through ``study_zoom_faces.all_faces`` (imported only where measured)."""
    from study.study_zoom_faces import all_faces
    detector = cv2.FaceDetectorYN.create(str(model), '', (320, 320), score_threshold=threshold)
    return lambda image: all_faces(detector, image)


def _spaced(inside: list[int], times: dict[int, float]) -> list[int]:
    """The first frame, each frame at least SHEET_SPACING_SECONDS after the last picked one, and the last."""
    picked = inside[:1]
    for frame in inside[1:]:
        if times[frame] - times[picked[-1]] >= SHEET_SPACING_SECONDS or frame == inside[-1]:
            picked.append(frame)
    return picked


def sheet_frames(sampling: dict) -> dict[int, list[str]]:
    """Frame -> clips whose contact sheets show it: each range's first, spaced and last frames."""
    chosen: dict[int, set[str]] = {}
    times = {row['frame']: row['t'] for row in sampling['frames']}
    for span in sampling['ranges']:
        inside = [frame for frame in sorted(times) if span['firstFrame'] <= frame < span['endFrame']]
        for frame in _spaced(inside, times):
            chosen.setdefault(frame, set()).add(span['clipId'])
    return {frame: sorted(clips) for frame, clips in chosen.items()}


def _jpeg(image: np.ndarray) -> bytes:
    """Encode one BGR image as a JPEG."""
    ok, buffer = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 90])
    require(bool(ok), 'Speaker contact-sheet image did not encode')
    return buffer.tobytes()


def _tile(image: np.ndarray, label: str) -> bytes:
    """Fit an image into a TILE square with a label band; returns the JPEG bytes."""
    height, width = image.shape[:2]
    factor = TILE / max(height, width)
    size = (max(1, round(width * factor)), max(1, round(height * factor)))
    fitted = cv2.resize(image, size, interpolation=cv2.INTER_AREA if factor < 1 else cv2.INTER_LINEAR)
    canvas = np.zeros((TILE, TILE, 3), np.uint8)
    top, left = (TILE - size[1]) // 2, (TILE - size[0]) // 2
    canvas[top:top + size[1], left:left + size[0]] = fitted
    cv2.rectangle(canvas, (0, TILE - 34), (TILE, TILE), (0, 0, 0), -1)
    cv2.putText(canvas, label, (8, TILE - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    return _jpeg(canvas)


def face_tiles(bgr: np.ndarray, row: dict) -> list[bytes]:
    """One labelled tile per face in a measured frame, or the whole frame when none was found."""
    label = f"{row['t']:.2f} s  f{row['frame']}"
    if not row['faces']:
        return [_tile(bgr, f'{label}  no face')]
    height, width = bgr.shape[:2]
    tiles = []
    for index, face in enumerate(row['faces'], start=1):
        margin = CROP_MARGIN * max(face['w'], face['h'])
        x0, y0 = max(0, int(face['x'] - margin)), max(0, int(face['y'] - margin))
        x1, y1 = min(width, int(face['x'] + face['w'] + margin)), min(height, int(face['y'] + face['h'] + margin))
        crop = bgr[y0:y1, x0:x1] if x1 > x0 and y1 > y0 else bgr
        tiles.append(_tile(crop, f'{label}  face {index}'))
    return tiles


def _write_new_bytes(path: Path, data: bytes) -> None:
    """Publish one new file; never overwrite or follow a link."""
    real_directory(path.parent)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.write(descriptor, data)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sheet(chunk: list[tuple[int, bytes]]) -> np.ndarray:
    """One COLUMNS x ROWS grid of tiles, filled row by row."""
    sheet = np.zeros((ROWS * TILE, COLUMNS * TILE, 3), np.uint8)
    for index, (_frame, data) in enumerate(chunk):
        top, left = (index // COLUMNS) * TILE, (index % COLUMNS) * TILE
        sheet[top:top + TILE, left:left + TILE] = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    return sheet


def write_sheets(directory: Path, tiles: dict[str, list[tuple[int, bytes]]]) -> list[dict]:
    """Write ``<clipId>-<n>.jpg`` grids (n from 1) in the new ``directory``; returns ``{path, sha256, frames}``."""
    directory.mkdir(mode=0o700)
    rows, per_sheet = [], COLUMNS * ROWS
    for clip in sorted(tiles):
        for number, start in enumerate(range(0, len(tiles[clip]), per_sheet), start=1):
            chunk = tiles[clip][start:start + per_sheet]
            path = directory / f'{clip}-{number}.jpg'
            _write_new_bytes(path, _jpeg(_sheet(chunk)))
            rows.append({'path': str(path), 'sha256': file_digest(path), 'frames': sorted({f for f, _ in chunk})})
    return rows


@dataclass
class FramePass:
    """Per decoded frame: faces in source pixels, plus sheet tiles for the frames sheets show.

    Each measured frame prints ``SNIPER_PROGRESS speaker-frames <n>``: the inspection owner's
    idle watchdog (600 s) counts only advancing progress lines as forward progress.
    """

    rows: dict[int, dict]
    detect: Callable[[np.ndarray], list[dict]]
    sheets: dict[int, list[str]]
    tiles: dict[str, list[tuple[int, bytes]]] = field(default_factory=dict)
    measured: int = 0

    def __call__(self, frame: int, pixels: np.ndarray) -> dict:
        """Measure one RGB frame (valid only during this call) and keep its tiles as JPEG bytes."""
        bgr = cv2.cvtColor(pixels, cv2.COLOR_RGB2BGR)
        small, scale = detection_image(bgr)
        plan = self.rows[frame]
        row = face_rows([{'frame': frame, 't': plan['t'], 'scale': scale}], lambda _row: self.detect(small))[0]
        for clip in self.sheets.get(frame, []):
            self.tiles.setdefault(clip, []).extend((frame, tile) for tile in face_tiles(bgr, row))
        self.measured += 1
        print(f'SNIPER_PROGRESS speaker-frames {self.measured}', flush=True)
        return row


def measure_frames(request: dict, source: dict, sampling: dict, root: Path) -> tuple[list[dict], list[dict], dict]:
    """Decode the sampled frames once; returns (face rows, sheet rows, decode summary).

    Args:
        request: The inspection request (``model`` path and ``scoreThreshold`` from FACE_TRACK).
        source: The manifest source row; its bytes were checked against ``sourceSha256``.
        sampling: ``observation_plan``'s result.
        root: The inspection directory (the filter script and ``sheets/`` live here).
    """
    detect = face_detector(Path(request['model']['path']), request['scoreThreshold'])
    frame_pass = FramePass({row['frame']: row for row in sampling['frames']}, detect, sheet_frames(sampling))
    faces, decode = compare_selected_frames(Path(source['path']), frame_selection(source, sampling), frame_pass, root)
    return faces, write_sheets(root / 'sheets', frame_pass.tiles), decode
