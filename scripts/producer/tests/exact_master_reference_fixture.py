"""Small real-vocabulary timelines for exact-master Desktop tests."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

from fingerprints import file_sha256
from palmier.desktop_exact_master_plan import (ADD_OP, DISABLE_OP,
                                               ELEMENT_ID, MEDIA_KEY)

COVERAGE = {"complete": True, "scope": "mcp-readable-timeline"}


def base_timeline() -> dict:
    """One editable video/audio pair before the reference is added."""
    return {
        "id": "candidate", "name": "Desktop candidate",
        "fps": 24, "width": 1920, "height": 1080,
        "totalFrames": 120, "durationSeconds": 5.0,
        "tracks": [
            {
                "index": 0, "label": "V1", "type": "video",
                "clips": [{
                    "id": "base-video", "mediaRef": "source",
                    "frames": [0, 120],
                    "audio": {"id": "base-audio", "track": 1},
                }],
            },
            {
                "index": 1, "label": "A1", "type": "audio",
                "linkedClips": 1,
            },
        ],
    }


def added_timeline(disabled: bool = False) -> dict:
    """Reference on its own auto-created linked track pair."""
    timeline = base_timeline()
    base_video = copy.deepcopy(timeline["tracks"][0])
    base_audio = copy.deepcopy(timeline["tracks"][1])
    base_video.update({"index": 1, "label": "V1"})
    base_video["clips"][0]["audio"]["track"] = 2
    base_audio.update({"index": 2, "label": "A1"})
    video = {
        "index": 0, "label": "V2", "type": "video",
        "clips": [{
            "id": "master-video", "mediaRef": "master-media",
            "frames": [0, 120],
            "audio": {"id": "master-audio", "track": 3},
        }],
    }
    audio = {
        "index": 3, "label": "A2", "type": "audio", "linkedClips": 1,
    }
    if disabled:
        video.update({"hidden": True, "syncLocked": True})
        audio.update({"muted": True, "syncLocked": True})
    timeline["tracks"] = [video, base_video, base_audio, audio]
    return timeline


def make_state(root: str) -> dict:
    """Persist an operation manifest and return its in-memory authority state."""
    path = Path(root) / "final.mp4"
    path.write_bytes(b"approved-master")
    digest = file_sha256(str(path))
    operations = Path(root) / "operations.json"
    content = {
        "stage": "visual",
        "steps": [
            {
                "op": "import", "key": MEDIA_KEY, "elementId": ELEMENT_ID,
                "path": str(path), "fileHash": digest,
                "importName": f"Sniper · exact master · {digest[:8]}",
            },
            {
                "op": ADD_OP, "elementId": ELEMENT_ID,
                "mediaKey": MEDIA_KEY, "assetPath": str(path),
                "assetHash": digest, "startFrame": 0, "endFrame": 120,
                "fps": 24, "frameRate": "24/1",
            },
            {
                "op": DISABLE_OP, "elementId": ELEMENT_ID,
                "videoFlags": {"hidden": True, "syncLocked": True},
                "audioFlags": {"muted": True, "syncLocked": True},
            },
        ],
    }
    operations.write_text(json.dumps(content), encoding="utf-8")
    return {
        "stage": "visual", "outDir": root,
        "operations": {"path": str(operations),
                       "hash": file_sha256(str(operations))},
        "mediaLedger": {digest: {
            "mediaRef": "master-media", "path": str(path),
            "mediaKey": MEDIA_KEY,
        }},
        "elementLedger": {
            "schemaVersion": 2, "elements": {}, "tombstones": {},
        },
    }


def add_args() -> dict:
    return {"entries": [{
        "mediaRef": "master-media", "startFrame": 0, "endFrame": 120,
    }]}


def clone(value: dict) -> dict:
    return copy.deepcopy(value)
