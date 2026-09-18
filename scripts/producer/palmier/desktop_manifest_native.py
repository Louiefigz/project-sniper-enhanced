"""Native media-lane planning for Desktop Palmier manifests."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from palmier.desktop_native_captions import native_caption_settings
from palmier.mcp_client import PalmierError


@dataclass(frozen=True)
class NativeContext:
    """Inputs shared by native media-lane planners."""

    plan: dict
    manifest: dict
    fps: float
    duration_s: float
    base: str
    out_dir: str


def _asset_path(row: dict, base: str, label: str) -> str:
    value = row.get("path")
    if not isinstance(value, str) or not value:
        raise PalmierError(f"{label} has no media path")
    path = value if os.path.isabs(value) else os.path.join(base, value)
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise PalmierError(f"{label} media is missing: {path}")
    return path


def _catalog(manifest: dict, lane: str) -> dict[str, dict]:
    rows = manifest.get(lane) or []
    if not isinstance(rows, list):
        raise PalmierError(f"asset manifest {lane} catalog is malformed")
    return {
        str(row.get("id")): row for row in rows
        if isinstance(row, dict) and row.get("id")
    }


def _broll_steps(plan: dict, manifest: dict, fps: float,
                 base: str) -> list[dict]:
    from palmier.desktop_caption_shard_plan import FULL_CANVAS_TRANSFORM
    catalog = _catalog(manifest, "broll")
    steps = []
    for index, row in enumerate(plan.get("brollTrack") or []):
        if not isinstance(row, dict):
            raise PalmierError(f"brollTrack[{index}] is malformed")
        if row.get("focusOps"):
            raise PalmierError(
                f"brollTrack[{index}] focusOps have no exact Palmier "
                "mutation/readback contract")
        ident = str(row.get("assetId") or "")
        asset = catalog.get(ident)
        if asset is None:
            raise PalmierError(
                f"brollTrack[{index}] asset {ident!r} is missing")
        start = float(row.get("assetStart", 0.0))
        steps.append({
            "op": "native-broll", "lane": "broll",
            "key": f"broll:{index}",
            "elementId": row.get("id") or f"broll:{ident}:{index}",
            "path": _asset_path(
                asset, base, f"brollTrack[{index}]"),
            "startFrame": round(float(row["outStart"]) * fps),
            "endFrame": round(float(row["outEnd"]) * fps),
            "source": [
                start, start + float(row["outEnd"]) - float(row["outStart"]),
            ],
            "focusOps": [], "trackPolicy": "new-top-video-track-per-broll",
            "transform": FULL_CANVAS_TRANSFORM,
        })
    return steps


def _music_steps(context: NativeContext) -> list[dict]:
    music = context.plan.get("music") or {}
    if not isinstance(music, dict) or not music.get("enabled"):
        return []
    row: dict[str, Any] = music
    if not music.get("path"):
        row = _catalog(context.manifest, "music").get(
            str(music.get("assetId"))) or {}
    return [{
        "op": "native-music", "lane": "music", "key": "music",
        "elementId": "music",
        "path": _asset_path(row, context.base, "music"),
        "startFrame": 0,
        "endFrame": round(context.duration_s * context.fps),
        "gapDb": music.get("gapDb"), "duck": music.get("duck", True),
    }]


def native_steps(context: NativeContext) -> list[dict]:
    """Translate supported native b-roll/audio/caption/color intent."""
    steps = _broll_steps(
        context.plan, context.manifest, context.fps, context.base)
    steps.extend(_music_steps(context))
    captions = context.plan.get("captions")
    if not isinstance(context.plan.get("captionsTrack"), dict) \
            and isinstance(captions, dict) and captions:
        steps.append({
            "op": "native-captions", "lane": "captions",
            "settings": native_caption_settings(context.plan),
            "limitation": "Palmier re-transcribes editable captions",
        })
    enhance = context.plan.get("audioEnhance")
    audio_master = enhance.get("palmierAudioMaster") \
        if isinstance(enhance, dict) else None
    if isinstance(audio_master, dict):
        raise PalmierError(
            "palmierAudioMaster has no released external-media authority")
    denoise = enhance.get("palmierDenoise") \
        if isinstance(enhance, dict) else None
    if isinstance(denoise, dict):
        steps.append({
            "op": "native-denoise", "lane": "audio", "settings": denoise,
        })
    elif enhance:
        steps.append({
            "op": "native-audio-review", "lane": "audio-review",
            "settings": enhance,
            "limitation": (
                "named enhance preset has no measured Palmier strength mapping"),
        })
    look = context.plan.get("baselineLook") or {}
    if isinstance(look, dict) and look.get("lut"):
        raise PalmierError(
            "baselineLook.lut has no released external-media authority")
    if isinstance(look, dict) and look.get("palmierColor"):
        steps.append({
            "op": "native-color", "lane": "color",
            "settings": look["palmierColor"],
        })
    return steps
