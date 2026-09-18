#!/usr/bin/env python3
"""Build exhaustive review windows for a frame-level reference study."""
from __future__ import annotations

import hashlib
import json
import math
import os
import unicodedata
from typing import Any

import cv2

REVIEW_SCHEMA_VERSION = 1
PRE_ROLL_FRAMES = 3
POST_ROLL_FRAMES = 6


def file_sha256(path: str) -> str:
    """Return the SHA-256 of one regular file."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_object(path: str) -> dict[str, Any]:
    """Load a required JSON object."""
    with open(path, encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def canonical_hash(value: dict[str, Any]) -> str:
    """Hash one JSON object using stable key ordering."""
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def stable_reference_id(video: str) -> str:
    """Match the server's path-bound opaque reference identifier."""
    normalized = unicodedata.normalize("NFC", os.path.abspath(video))
    return f"ref_{hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:16]}"


def _video_frames(video: str, fps: float, duration: float) -> int:
    capture = cv2.VideoCapture(video)
    try:
        measured = int(round(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
    finally:
        capture.release()
    return measured if measured > 0 else int(math.ceil(fps * duration))


def _event_span(event: dict[str, Any], fps: float,
                analysis_fps: float, total: int) -> tuple[int, int]:
    at = max(0, int(round(float(event.get("t", 0.0)) * fps)))
    duration = max(1, int(math.ceil(
        float(event.get("durationFrames", 1)) * fps / analysis_fps)))
    start = max(0, at - PRE_ROLL_FRAMES)
    end = min(total, max(start + 1, at + duration + POST_ROLL_FRAMES))
    return start, end


def _event_rows(deep: dict[str, Any], fps: float,
                total: int) -> list[dict[str, Any]]:
    params = deep.get("params") if isinstance(deep.get("params"), dict) else {}
    analysis_fps = float(params.get("fps") or fps)
    rows = []
    for event in deep.get("events") or []:
        if not isinstance(event, dict) or not isinstance(event.get("id"), str):
            continue
        start, end = _event_span(event, fps, analysis_fps, total)
        rows.append({"startFrame": start, "endFrame": end, "events": [event]})
    return sorted(rows, key=lambda row: (row["startFrame"], row["endFrame"]))


def _merge_events(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for row in rows:
        if not merged or row["startFrame"] > merged[-1]["endFrame"]:
            merged.append({**row, "events": list(row["events"])})
            continue
        current = merged[-1]
        current["endFrame"] = max(current["endFrame"], row["endFrame"])
        current["events"].extend(row["events"])
    return merged


def _event_items(rows: list[dict[str, Any]], fps: float) -> list[dict[str, Any]]:
    items = []
    for index, row in enumerate(rows):
        events = row.pop("events")
        items.append({
            "id": f"event-window-{index:04d}", "kind": "event-window",
            **row, "startS": round(row["startFrame"] / fps, 6),
            "endS": round(row["endFrame"] / fps, 6),
            "eventIds": [event["id"] for event in events],
            "eventTypes": [str(event.get("type")) for event in events],
            "eventEvidence": events, "visualPolicy": "every-frame",
        })
    return items


def _stable_items(events: list[dict[str, Any]], total: int,
                  fps: float) -> list[dict[str, Any]]:
    items, cursor, index = [], 0, 0
    for row in [*events, {"startFrame": total, "endFrame": total}]:
        if cursor < row["startFrame"]:
            start, end = cursor, row["startFrame"]
            items.append({
                "id": f"stable-span-{index:04d}", "kind": "stable-span",
                "startFrame": start, "endFrame": end,
                "startS": round(start / fps, 6), "endS": round(end / fps, 6),
                "eventIds": [], "eventTypes": [],
                "visualPolicy": "start-mid-end",
            })
            index += 1
        cursor = max(cursor, row["endFrame"])
    return items


def _assert_coverage(items: list[dict[str, Any]], total: int) -> None:
    ordered = sorted(items, key=lambda row: row["startFrame"])
    cursor = 0
    for row in ordered:
        if row["startFrame"] != cursor or row["endFrame"] <= cursor:
            raise ValueError(f"reference review coverage drift at frame {cursor}")
        cursor = row["endFrame"]
    if cursor != total:
        raise ValueError(f"reference review ends at {cursor}, expected {total}")


def build_worklist(video: str, deep_path: str) -> dict[str, Any]:
    """Build a source-frame-complete review worklist from a deep study."""
    deep = load_object(deep_path)
    source = deep.get("source") if isinstance(deep.get("source"), dict) else {}
    fps = float(source.get("fps") or 0.0)
    duration = float(source.get("durationS") or 0.0)
    if fps <= 0 or duration <= 0 or not os.path.isfile(video):
        raise ValueError("reference review requires a valid video, fps, and duration")
    total = _video_frames(video, fps, duration)
    merged = _merge_events(_event_rows(deep, fps, total))
    events = _event_items(merged, fps)
    items = sorted([*events, *_stable_items(events, total, fps)],
                   key=lambda row: row["startFrame"])
    _assert_coverage(items, total)
    signals = deep.get("signals") if isinstance(deep.get("signals"), dict) else {}
    return {
        "schemaVersion": REVIEW_SCHEMA_VERSION,
        "kind": "reference-frame-review-worklist",
        "referenceId": stable_reference_id(video),
        "source": {"video": os.path.abspath(video), "sha256": file_sha256(video),
                   "fps": fps, "durationS": duration, "frameCount": total,
                   "width": source.get("width"), "height": source.get("height")},
        "deepStudy": {"path": os.path.abspath(deep_path),
                      "sha256": file_sha256(deep_path),
                      "analysisFps": deep.get("params", {}).get("fps"),
                      "analysisFrames": signals.get("frameCount"),
                      "unclassifiedRuns": deep.get("unclassifiedRuns")},
        "policy": {
            "deterministicCoverage": "every-analysis-frame",
            "eventVisualCoverage": "every-source-frame-with-3-pre-6-post",
            "stableVisualCoverage": "start-mid-end",
            "requiredLenses": ["mechanics", "editorial"],
            "disagreement": "adjudication-required",
        },
        "items": items,
        "coverage": {"sourceFrames": total, "coveredFrames": total,
                     "uncoveredFrames": [], "overlapFrames": []},
    }
