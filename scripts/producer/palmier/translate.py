#!/usr/bin/env python3
"""Translate a gated ``edit_plan.json`` into ordered Palmier steps.

The companion ``translate_math`` module keeps timeline math deterministic and
unit-testable without a running app (docs/PIPELINE.md units rules):

* Palmier timeline positions are integer FRAMES; our plan speaks output
  SECONDS → ``round(t * fps)``.
* ``set_keyframes`` frames are CLIP-RELATIVE; ``position`` rows are the
  TOP-LEFT corner (0–1 canvas coords); ``scale`` rows are normalized w/h
  (1.0 = fills the axis), NOT a factor.
* A zoom ``z`` recomposed toward source point ``(cx, cy)`` puts that point at
  canvas center: topLeft = (0.5 − z·cx, 0.5 − z·cy), clamped so no canvas
  edge is exposed (each axis in [1−z, 0] for z ≥ 1).

No fallbacks: vocabulary this version cannot express in Palmier — transitions
(no primitive), bracket/static punches, or non-smooth ramps — raises
``TranslateError`` naming the entry; softer fidelity losses (grade, duck,
burned captions) become explicit ``warn`` steps the executor must surface.
"""
from __future__ import annotations

from dataclasses import dataclass
from palmier.translate_math import (Placement, TranslateError,
                                    build_placements, clip_windows,
                                    punch_keyframes, top_left)


_CANVAS_BY_TARGET = {
    "longform": (1920, 1080), "16:9": (1920, 1080),
    "short": (1080, 1920), "9:16": (1080, 1920),
}


@dataclass(frozen=True)
class TranslateRequest:
    """Project/media facts surrounding one pure plan translation."""

    fps: float
    source_path: str
    graphics_paths: dict[int, str]
    project_name: str
    width: int
    height: int
    export_path: str | None = None
    master_path: str | None = None
    master_hash: str | None = None
    master_duration_s: float | None = None
    master_fps: float | None = None
    component_paths: dict[str | int, str] | None = None
    normalize_graphics_to_canvas: bool = False


def _project_fps(fps: float, warn: list[dict]) -> float:
    """The Palmier project rate: ``round(fps)``, warned when it differs.

    ALL frame math must run at this rate — Palmier conforms clips by REAL
    TIME at the integer project fps, so placements computed at the true NTSC
    rate (29.97) drift ~1 frame/33s under the conformed clips and Palmier's
    same-track overwrite silently trims the neighbors.
    """
    if abs(fps - round(fps)) > 1e-6:
        warn.append({"op": "warn", "message":
                     f"source fps {fps} rounded to {round(fps)} for the "
                     "Palmier timeline (integer fps only); all frame math "
                     "runs at the rounded rate"})
    return float(round(fps))


def _baseline_steps(plan: dict) -> list[dict]:
    look = plan.get("baselineLook")
    if not look:
        return []
    z = float(look.get("zoom", 1.0))
    cx, cy = float(look.get("centerX", 0.5)), float(look.get("centerY", 0.5))
    x, y = top_left(z, cx, cy)
    steps: list[dict] = [{"op": "baseline",
                          "transform": {"width": z, "height": z,
                                        "centerX": round(x + z / 2, 4),
                                        "centerY": round(y + z / 2, 4)}}]
    if look.get("grade") and look["grade"] != "none":
        steps.append({"op": "warn", "message":
                      f"baselineLook.grade '{look['grade']}' not translated — "
                      "the apply_color mapping is unmeasured; grade in "
                      "Palmier or keep the base-side render"})
    return steps


def _check_graphics_canvas(plan: dict, width: int, height: int) -> None:
    """Reject overlays whose fixed comp canvas differs from the project."""
    if not plan.get("graphicsTrack"):
        return
    target = plan.get("target") or {}
    label = target.get("aspect") or target.get("mode")
    expected = _CANVAS_BY_TARGET.get(label)
    if expected is None:
        raise TranslateError(
            f"graphicsTrack: target aspect/mode {label!r} has no fixed comp canvas")
    if (width, height) == expected:
        return
    expected_w, expected_h = expected
    raise TranslateError(
        f"graphicsTrack: Palmier project/source canvas {width}x{height} does "
        f"not match the fixed {expected_w}x{expected_h} comp canvas for "
        f"target {label!r}; render at {expected_w}x{expected_h} before pushing")


def _media_and_overlay_steps(plan: dict, fps: float, graphics_paths: dict,
                             warn: list[dict], normalize: bool = False) -> list[dict]:
    steps: list[dict] = []
    overlays = []
    for i, g in enumerate(plan.get("graphicsTrack") or []):
        if i not in graphics_paths:
            raise TranslateError(
                f"graphicsTrack[{i}] ({g.get('kind')}): no pre-rendered file "
                "— render via graphics_render first (push.py does this)")
        element_id = g.get("id") or g.get("semanticBeatId") or f"graphicsTrack:{i}"
        stable_identity = bool(g.get("id") or g.get("semanticBeatId"))
        steps.append({"op": "import", "key": f"gfx:{i}",
                      "path": graphics_paths[i], "elementId": element_id,
                      "stableIdentity": stable_identity})
        entry = {"mediaKey": f"gfx:{i}",
                 "elementId": element_id,
                 "stableIdentity": stable_identity,
                 "startFrame": round(float(g["outStart"]) * fps),
                 "endFrame": round(float(g["outEnd"]) * fps)}
        if normalize:
            entry["transform"] = {
                "width": 1.0, "height": 1.0,
                "centerX": 0.5, "centerY": 0.5,
            }
        overlays.append(entry)
    if overlays:
        steps.append({"op": "overlays", "entries": overlays})
    music = plan.get("music") or {}
    if music.get("enabled"):
        if "path" not in music and "assetId" in music:
            raise TranslateError(
                f"music.assetId '{music['assetId']}' not resolved — the "
                "push CLI must resolve it through the manifest before export")
        warn.append({"op": "warn", "message":
                     "music is preview-silent in Palmier: final export uses "
                     "the verified in-house audio bus so its voice-priority "
                     "ducking, fade, loudness, and hum QC cannot disappear"})
    return steps


def _project_steps(request: TranslateRequest, placements: list[Placement],
                   fps: float) -> list[dict]:
    """Project declaration, source import, and ordered cut placements."""
    return [
        {"op": "project", "name": request.project_name, "fps": round(fps),
         "width": request.width, "height": request.height},
        {"op": "import", "key": "src", "path": request.source_path},
        {"op": "cuts", "entries": [
            {"mediaKey": "src", "source": list(p.source),
             "startFrame": p.start_frame, "endFrame": p.end_frame,
             "speed": p.speed}
            for p in placements]},
    ]


def _motion_steps(plan: dict, placements: list[Placement],
                  fps: float) -> list[dict]:
    """Baseline transform and merged per-clip punch tracks."""
    steps = _baseline_steps(plan)
    look = plan.get("baselineLook") or {}
    base = (float(look.get("zoom", 1.0)), float(look.get("centerX", 0.5)),
            float(look.get("centerY", 0.5)))
    tracks = punch_keyframes(plan.get("punchIns") or [], placements, base, fps)
    for clip_i, properties in sorted(tracks.items()):
        for prop in ("scale", "position"):
            if prop not in properties:
                continue
            steps.append({"op": "keyframes", "clip": clip_i,
                          "property": prop, "rows": properties[prop]})
    return steps


def _tail_steps(plan: dict, fps: float, warn: list[dict],
                export_path: str | None) -> list[dict]:
    """Audio fidelity notes, native text, captions note, and export marker."""
    steps: list[dict] = []
    if plan.get("audioEnhance") or plan.get("audioGain"):
        warn.append({"op": "warn", "message":
                     "audioEnhance/audioGain are not editable Palmier effects; "
                     "re-render final.mp4 before push. Export replaces the raw "
                     "Palmier mix with that verified authoritative audio bus"})
    for card in plan.get("titleCards") or []:
        steps.append({"op": "text", "content": card["text"],
                      "startFrame": round(float(card["outStart"]) * fps),
                      "endFrame": round(float(card["outEnd"]) * fps)})
    if isinstance(plan.get("captionsTrack"), dict):
        warn.append({"op": "warn", "message":
                     "CaptionTrackV1 is mirrored from the approved master and "
                     "preserved as regenerable caption artifacts; native "
                     "captions remain disabled because exact timing/style "
                     "readback is unproved"})
    elif (plan.get("captions") or {}).get("burn"):
        warn.append({"op": "warn", "message":
                     "captions.burn=true not translated — Palmier re-transcribes "
                     "(word timing lost); burn via the in-house renderer or "
                     "add_captions manually"})
    steps.extend(warn)
    if export_path:
        steps.append({"op": "export", "outputPath": export_path})
    return steps


def _mirror_steps(request: TranslateRequest) -> list[dict]:
    """Describe one flattened visual-master clip plus non-visible components."""
    duration = request.master_duration_s
    fps = request.master_fps
    if not request.master_path or not request.master_hash:
        raise TranslateError("visual mirror requires an approved master path and hash")
    if not isinstance(duration, (int, float)) or duration <= 0:
        raise TranslateError("visual mirror master has no positive duration")
    if not isinstance(fps, (int, float)) or fps <= 0:
        raise TranslateError("visual mirror master has no positive frame rate")
    if request.width <= 0 or request.height <= 0:
        raise TranslateError("visual mirror master has no positive canvas")
    project_fps = float(round(fps))
    end_frame = round(float(duration) * project_fps)
    if end_frame <= 0:
        raise TranslateError("visual mirror master resolves to zero frames")
    steps = [
        {"op": "project", "name": request.project_name,
         "fps": round(project_fps), "width": request.width,
         "height": request.height, "mirrorMode": "visual-master",
         "masterHash": request.master_hash},
        {"op": "import", "key": "master", "path": request.master_path},
        {"op": "mirror", "entry": {
            "mediaKey": "master", "startFrame": 0, "endFrame": end_frame,
            "source": [0.0, float(duration)], "speed": 1.0,
            "masterHash": request.master_hash}},
    ]
    for ident, component in sorted((request.component_paths or {}).items(),
                                   key=lambda item: str(item[0])):
        key = f"gfx:{ident}" if isinstance(ident, int) else str(ident)
        steps.append({"op": "component_import", "key": key,
                      "path": component})
    if request.export_path:
        steps.append({"op": "export", "outputPath": request.export_path})
    return steps


def translate(plan: dict, request: TranslateRequest) -> list[dict]:
    """The full plan → ordered executor steps. Pure; raises TranslateError."""
    if request.master_path is not None:
        if not isinstance(plan, dict):
            raise TranslateError("visual mirror plan must be an object")
        return _mirror_steps(request)
    if plan.get("transitions"):
        raise TranslateError(f"{len(plan['transitions'])} transitions: Palmier "
                             "has no primitive; strip them or keep the lane in-house")
    if plan.get("brollTrack"):
        raise TranslateError(
            f"{len(plan['brollTrack'])} brollTrack entries: Palmier b-roll "
            "asset trims/focusOps are not translated yet — keep the lane "
            "in-house rather than silently dropping it")
    if not request.normalize_graphics_to_canvas:
        _check_graphics_canvas(plan, request.width, request.height)
    cut = plan.get("cutTrack") or []
    if not cut:
        raise TranslateError("empty cutTrack — nothing to place")
    src_ids = {seg["sourceId"] for seg in cut}
    if len(src_ids) > 1:
        raise TranslateError(f"multi-source cutTrack {sorted(src_ids)} — "
                             "v1 translates single-source plans")
    warn: list[dict] = []
    fps = _project_fps(request.fps, warn)
    placements = build_placements(cut, fps)
    steps = _project_steps(request, placements, fps)
    steps.extend(_motion_steps(plan, placements, fps))
    steps.extend(_media_and_overlay_steps(
        plan, fps, request.graphics_paths, warn,
        request.normalize_graphics_to_canvas))
    steps.extend(_tail_steps(plan, fps, warn, request.export_path))
    return steps
