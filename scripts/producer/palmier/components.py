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


def _caption_artifacts(plan: dict, manifest_path: str) -> dict[str, str]:
    """Preserve proved first-class caption projections as regenerable assets."""
    if not isinstance(plan.get("captionsTrack"), dict):
        return {}
    directory = os.path.dirname(os.path.abspath(manifest_path))
    plan_path = plan.get("_path")
    if isinstance(plan_path, str):
        directory = os.path.dirname(os.path.abspath(plan_path))
    names = (
        "caption_authority.json", "caption_compilation.json",
        "caption_palmier.json", "captions.ass", "captions.srt",
        "caption_chapters.json", "chapters.txt",
    )
    return {
        f"captions:v1:{name}": os.path.join(directory, name)
        for name in names if os.path.isfile(os.path.join(directory, name))
    }


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
    result.update(_caption_artifacts(plan, manifest_path))
    return result
