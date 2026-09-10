"""Pure helpers for the governed connected-acceptance worklist."""
from __future__ import annotations

import hashlib
import json
import os

from palmier.desktop_state import load_pointer
from palmier.mcp_client import PalmierError


def json_result(value: str) -> object:
    """Decode a Palmier text result, preserving legitimate scalar text."""
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def media_ref(value: object) -> str:
    """Resolve the stable media id from Palmier's supported result shapes."""
    if not isinstance(value, dict):
        raise PalmierError("Palmier import returned no JSON media record")
    direct = value.get("mediaRef") or value.get("id")
    if isinstance(direct, str) and direct:
        return direct
    result = value.get("result")
    if isinstance(result, dict):
        return media_ref(result)
    raise PalmierError("Palmier import returned no mediaRef")


def clips(timeline: dict, visual: bool) -> list[dict]:
    """Return ordered clip rows, optionally excluding every audio row."""
    rows = []
    for track_index, track in enumerate(timeline.get("tracks") or []):
        if not isinstance(track, dict):
            continue
        kind = str(track.get("type", track.get("trackType", ""))).lower()
        if visual and "audio" in kind:
            continue
        for clip in track.get("clips") or []:
            if not isinstance(clip, dict) or not isinstance(
                    clip.get("id"), str):
                continue
            media_type = str(clip.get("mediaType", "video")).lower()
            if visual and media_type == "audio":
                continue
            rows.append({**clip, "_trackIndex": track_index})
    return sorted(rows, key=lambda row: (
        (row.get("frames") or [0])[0], row["_trackIndex"], row["id"]))


def audio_ids(timeline: dict) -> list[str]:
    """Return stable linked-audio ids for the visual spine."""
    result = []
    for clip in clips(timeline, True):
        audio = clip.get("audio")
        if isinstance(audio, dict) and isinstance(audio.get("id"), str):
            result.append(audio["id"])
    return result


def entry(step: dict, media_ref_value: str) -> dict:
    """Translate a bound worklist row into Palmier add_clips vocabulary."""
    value = {
        "mediaRef": media_ref_value, "startFrame": step["startFrame"],
        "endFrame": step["endFrame"],
    }
    for key in ("trackIndex", "transform", "source"):
        if step.get(key) is not None:
            value[key] = step[key]
    return value


def args_digest(args: dict) -> str:
    """Hash exact mutation arguments for journal reconciliation."""
    blob = json.dumps(args, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def recovered_media_ref(state: dict, args: dict) -> str:
    """Resolve one response-lost import from the durable media ledger."""
    source = args.get("source")
    path = source.get("path") if isinstance(source, dict) else None
    matches = [
        row.get("mediaRef")
        for row in (state.get("mediaLedger") or {}).values()
        if isinstance(row, dict) and isinstance(path, str)
        and os.path.realpath(str(row.get("path"))) == os.path.realpath(path)
        and isinstance(row.get("mediaRef"), str)
    ]
    if len(matches) != 1:
        raise PalmierError(
            "response-loss import recovery has no unique mediaRef")
    return matches[0]


def load_state_dir(repo: str) -> str:
    """Resolve active authority storage without exposing pointer internals."""
    path, _state = load_pointer(repo)
    return os.path.dirname(path)
