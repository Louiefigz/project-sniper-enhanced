"""Collect current-edit component files for non-visible Palmier preservation."""
from __future__ import annotations

import os


def _asset_path(value: object, manifest_path: str) -> str | None:
    """Resolve one declared component path without claiming it is importable."""
    if not isinstance(value, str) or not value.strip():
        return None
    path = os.path.expanduser(value)
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(os.path.abspath(manifest_path)), path)
    return os.path.abspath(path)


def _declared_artifacts(plan: dict, manifest_path: str) -> dict[str, str]:
    """Collect explicit caption, text, animation, and SFX artifact paths."""
    artifacts: dict[str, str] = {}
    lanes = (("captions", [plan.get("captions")]),
             ("title", plan.get("titleCards") or []),
             ("transition", plan.get("transitions") or []))
    path_keys = ("path", "artifactPath", "renderPath", "srtPath", "vttPath")
    for lane, rows in lanes:
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            for field in path_keys:
                path = _asset_path(row.get(field), manifest_path)
                if path:
                    artifacts[f"{lane}:{index}:{field}"] = path
            sfx = row.get("sfx")
            value = sfx.get("path") if isinstance(sfx, dict) else sfx
            path = _asset_path(value, manifest_path)
            if path:
                artifacts[f"{lane}:{index}:sfx"] = path
    return artifacts


def component_assets(plan: dict, manifest: dict, manifest_path: str,
                     graphics: dict[int, str]) -> dict[str, str]:
    """Return all referenced source, b-roll, audio, graphics, and text assets."""
    result = {f"graphics:{index}": path for index, path in graphics.items()}
    for index, row in enumerate(manifest.get("sources") or []):
        ident = row.get("id", index)
        path = _asset_path(row.get("path"), manifest_path)
        if path:
            result[f"source:{ident}"] = path
        transcript = _asset_path(
            row.get("transcriptPath") or row.get("transcript"), manifest_path)
        if transcript:
            result[f"source:{ident}:transcript"] = transcript
    selected = {row.get("assetId") for row in plan.get("brollTrack") or []
                if isinstance(row, dict)}
    for index, row in enumerate(manifest.get("broll") or []):
        ident = row.get("id", index)
        path = _asset_path(row.get("path"), manifest_path)
        if ident in selected and path:
            result[f"broll:{ident}"] = path
    music = plan.get("music") or {}
    music_path = _asset_path(music.get("path"), manifest_path)
    if music.get("enabled") and music_path:
        result["music:selected"] = music_path
    result.update(_declared_artifacts(plan, manifest_path))
    return result
