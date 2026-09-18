#!/usr/bin/env python3
"""Extract every event frame and stable-span representatives for review."""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

SHEET_COLUMNS = 5
SHEET_ROWS = 4
THUMB_WIDTH = 360
LABEL_HEIGHT = 30


@dataclass(frozen=True)
class ExtractContext:
    """Immutable media extraction inputs."""

    video: str
    output_dir: str
    fps: float


def _indices(item: dict[str, Any]) -> list[int]:
    start, end = int(item["startFrame"]), int(item["endFrame"])
    if item["kind"] == "event-window":
        return list(range(start, end))
    return sorted({start, (start + end - 1) // 2, end - 1})


def _safe_read(capture: Any, index: int, seek: bool = True) -> np.ndarray:
    if seek:
        capture.set(cv2.CAP_PROP_POS_FRAMES, index)
    ok, frame = capture.read()
    if not ok or frame is None:
        raise RuntimeError(f"could not decode reference frame {index}")
    return frame


def _save_frames(ctx: ExtractContext, item: dict[str, Any]) -> list[dict[str, Any]]:
    item_dir = os.path.join(ctx.output_dir, "frames", item["id"])
    os.makedirs(item_dir, exist_ok=True)
    capture = cv2.VideoCapture(ctx.video)
    rows = []
    try:
        indices = _indices(item)
        sequential = item["kind"] == "event-window"
        if sequential and indices:
            capture.set(cv2.CAP_PROP_POS_FRAMES, indices[0])
        for index in indices:
            frame = _safe_read(capture, index, seek=not sequential)
            path = os.path.join(item_dir, f"f_{index:08d}.jpg")
            if not cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, 94]):
                raise RuntimeError(f"could not write review frame: {path}")
            rows.append({"frame": index, "t": round(index / ctx.fps, 6),
                         "path": os.path.abspath(path)})
    finally:
        capture.release()
    return rows


def _thumb(frame: np.ndarray, label: str) -> np.ndarray:
    height = max(2, int(round(frame.shape[0] * THUMB_WIDTH / frame.shape[1])))
    resized = cv2.resize(frame, (THUMB_WIDTH, height), interpolation=cv2.INTER_AREA)
    labeled = cv2.copyMakeBorder(resized, LABEL_HEIGHT, 0, 0, 0,
                                 cv2.BORDER_CONSTANT, value=(18, 18, 18))
    cv2.putText(labeled, label, (8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.48,
                (245, 245, 245), 1, cv2.LINE_AA)
    return labeled


def _sheet_page(rows: list[dict[str, Any]], fps: float) -> np.ndarray:
    thumbs = []
    for row in rows:
        frame = cv2.imread(row["path"])
        if frame is None:
            raise RuntimeError(f"could not reopen review frame: {row['path']}")
        thumbs.append(_thumb(frame, f"f{row['frame']}  {row['frame'] / fps:.3f}s"))
    height = max(thumb.shape[0] for thumb in thumbs)
    blank = np.full((height, THUMB_WIDTH, 3), 18, dtype=np.uint8)
    cells = [cv2.copyMakeBorder(thumb, 0, height - thumb.shape[0], 0, 0,
                                cv2.BORDER_CONSTANT, value=(18, 18, 18))
             for thumb in thumbs]
    cells += [blank] * (SHEET_COLUMNS * SHEET_ROWS - len(cells))
    bands = [np.hstack(cells[i:i + SHEET_COLUMNS])
             for i in range(0, len(cells), SHEET_COLUMNS)]
    return np.vstack(bands)


def _contact_sheets(ctx: ExtractContext, item: dict[str, Any],
                    rows: list[dict[str, Any]]) -> list[str]:
    sheets_dir = os.path.join(ctx.output_dir, "contact-sheets")
    os.makedirs(sheets_dir, exist_ok=True)
    page_size = SHEET_COLUMNS * SHEET_ROWS
    paths = []
    for page in range(int(math.ceil(len(rows) / page_size))):
        subset = rows[page * page_size:(page + 1) * page_size]
        path = os.path.join(sheets_dir, f"{item['id']}_p{page + 1:03d}.jpg")
        if not cv2.imwrite(path, _sheet_page(subset, ctx.fps),
                           [cv2.IMWRITE_JPEG_QUALITY, 92]):
            raise RuntimeError(f"could not write contact sheet: {path}")
        paths.append(os.path.abspath(path))
    return paths


def extract_review_media(worklist: dict[str, Any], output_dir: str) -> dict[str, Any]:
    """Attach exact visual evidence to every worklist item."""
    source = worklist.get("source") if isinstance(worklist.get("source"), dict) else {}
    ctx = ExtractContext(str(source.get("video")), os.path.abspath(output_dir),
                         float(source.get("fps") or 0.0))
    if not os.path.isfile(ctx.video) or ctx.fps <= 0:
        raise ValueError("review media extraction requires a valid source")
    for item in worklist.get("items") or []:
        rows = _save_frames(ctx, item)
        item["visualFrames"] = rows
        item["visualFrameCount"] = len(rows)
        item["contactSheets"] = _contact_sheets(ctx, item, rows)
        if item["kind"] == "event-window" and len(rows) != (
                item["endFrame"] - item["startFrame"]):
            raise RuntimeError(f"event frame extraction incomplete: {item['id']}")
    return worklist
