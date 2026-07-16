"""Prepare a hash-bound, Desktop-readable Palmier execution manifest."""
from __future__ import annotations
import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any

from fingerprints import file_sha256
from palmier.checkpoint_inputs import (CheckpointInput, checkpoint_inputs,
                                       input_authority, read_json)
from palmier.mcp_client import PalmierError
from palmier.desktop_manifest_record import (PreparedDesktopStage,
                                             manifest_content)
from palmier.desktop_state import DesktopStageInput
from palmier.timeline_authority import atomic_write_record
MANIFEST_NAME = ".palmier-desktop-operations"
@dataclass(frozen=True)
class NativeContext:
    """Inputs shared by native media-lane planners."""

    plan: dict
    manifest: dict
    fps: float
    duration_s: float
    base: str


def _hash(value: object) -> str:
    blob = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


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
    return {str(row.get("id")): row for row in rows
            if isinstance(row, dict) and row.get("id")}


def _broll_steps(plan: dict, manifest: dict, fps: float,
                 base: str) -> list[dict]:
    catalog = _catalog(manifest, "broll")
    steps = []
    for index, row in enumerate(plan.get("brollTrack") or []):
        if not isinstance(row, dict):
            raise PalmierError(f"brollTrack[{index}] is malformed")
        ident = str(row.get("assetId") or "")
        asset = catalog.get(ident)
        if asset is None:
            raise PalmierError(f"brollTrack[{index}] asset {ident!r} is missing")
        steps.append({
            "op": "native-broll", "lane": "broll", "key": f"broll:{index}",
            "elementId": row.get("id") or f"broll:{ident}:{index}",
            "path": _asset_path(asset, base, f"brollTrack[{index}]"),
            "startFrame": round(float(row["outStart"]) * fps),
            "endFrame": round(float(row["outEnd"]) * fps),
            "source": [float(row.get("assetStart", 0.0)),
                       float(row.get("assetStart", 0.0))
                       + float(row["outEnd"]) - float(row["outStart"])],
            "focusOps": row.get("focusOps") or [],
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
    path = _asset_path(row, context.base, "music")
    return [{"op": "native-music", "lane": "music", "key": "music",
             "elementId": "music",
             "path": path, "startFrame": 0,
             "endFrame": round(context.duration_s * context.fps),
             "gapDb": music.get("gapDb"), "duck": music.get("duck", True)}]


def _native_steps(context: NativeContext) -> list[dict]:
    steps = _broll_steps(
        context.plan, context.manifest, context.fps, context.base)
    steps.extend(_music_steps(context))
    captions = context.plan.get("captions")
    if isinstance(captions, dict) and captions:
        steps.append({"op": "native-captions", "lane": "captions",
                      "settings": captions,
                      "limitation": "Palmier re-transcribes editable captions"})
    enhance = context.plan.get("audioEnhance")
    audio_master = enhance.get("palmierAudioMaster") \
        if isinstance(enhance, dict) else None
    if isinstance(audio_master, dict):
        steps.append({
            "op": "native-audio-master", "lane": "audio-master",
            "elementId": "audio-master",
            "path": _asset_path(audio_master, context.base, "audio master"),
            "startFrame": 0, "endFrame": round(context.duration_s * context.fps),
            "muteExisting": True, "targetLUFS": audio_master.get("targetLUFS"),
            "targetTruePeak": audio_master.get("targetTruePeak"),
            "sourceExportHash": audio_master.get("sourceExportHash"),
        })
    native_denoise = enhance.get("palmierDenoise") \
        if isinstance(enhance, dict) else None
    if isinstance(native_denoise, dict):
        steps.append({"op": "native-denoise", "lane": "audio",
                      "settings": native_denoise})
    elif enhance:
        steps.append({"op": "native-audio-review", "lane": "audio-review",
                      "settings": enhance,
                      "limitation": "named enhance preset has no measured Palmier strength mapping"})
    look = context.plan.get("baselineLook") or {}
    if isinstance(look, dict) and (look.get("palmierColor") or look.get("lut")):
        steps.append({"op": "native-color", "lane": "color",
                      "settings": look.get("palmierColor") or
                      {"lut": look["lut"]}})
    return steps


def _duration(plan: dict) -> float:
    return sum((float(row["end"]) - float(row["start"]))
               / float(row.get("speed", 1.0) or 1.0)
               for row in plan.get("cutTrack") or [])


def _visual_steps(steps: list[dict]) -> list[dict]:
    """Cut stage already landed; retain only downstream translated steps."""
    kept = [row for row in steps if row.get("op") not in
            {"project", "cuts", "mirror"}
            and not (row.get("op") == "import" and row.get("key") == "src")]
    layered: list[dict] = []
    for row in kept:
        layered.extend(_layer_overlays(row) if row.get("op") == "overlays"
                       else [row])
    return layered


def _layer_overlays(step: dict) -> list[dict]:
    """Allocate overlapping overlays to distinct non-destructive tracks."""
    entries = step.get("entries") or []
    ordered = sorted(enumerate(entries),
                     key=lambda item: (item[1]["startFrame"], item[0]))
    layers: list[list[dict]] = []
    layer_ends: list[int] = []
    for _index, entry in ordered:
        layer = next((index for index, end in enumerate(layer_ends)
                      if entry["startFrame"] >= end), len(layers))
        if layer == len(layers):
            layers.append([]); layer_ends.append(0)
        layers[layer].append(entry)
        layer_ends[layer] = int(entry["endFrame"])
    return [{**step, "entries": rows, "layer": index,
             "stacking": "higher layer renders above lower layer"}
            for index, rows in enumerate(layers)]


def _cut_worklist(plan: dict, fps: float) -> list[dict]:
    kept = [{"sourceId": row["sourceId"],
             "source": [float(row["start"]), float(row["end"])],
             "speed": float(row.get("speed", 1.0) or 1.0)}
            for row in plan.get("cutTrack") or []]
    return [{
        "op": "native-cut-spine", "lane": "cuts",
        "strategy": "edit-existing-source",
        "keptSourceRanges": kept,
        "targetTotalFrames": round(_duration(plan) * fps),
        "rules": [
            "use get_transcript before remove_words; re-read after indexes shift",
            "use frame-unit ripple ranges in descending order",
            "never add a duplicate source clip to the forked source bootstrap",
            "read back totalFrames and every seam before visual-stage advance",
        ],
    }]


def _desktop_capability(capability: dict, steps: list[dict]) -> dict:
    mapped = {row.get("lane") for row in steps if isinstance(row, dict)}
    omissions = [row for row in capability.get("omissions") or []
                 if row.get("lane") not in mapped]
    return {**capability, "omissions": omissions,
            "desktopNativeLanes": sorted(lane for lane in mapped if lane)}


def _bind_media_hashes(steps: list[dict]) -> list[dict]:
    """Bind every path-bearing operation to the exact imported file bytes."""
    bound = [{**row, "fileHash": file_sha256(row["path"])}
             if isinstance(row.get("path"), str) else row for row in steps]
    resources = {str(row["key"]): row for row in bound
                 if row.get("op") == "import"
                 and isinstance(row.get("key"), str)}
    result = []
    for row in bound:
        if row.get("op") != "overlays":
            result.append(row)
            continue
        entries = []
        for entry in row.get("entries") or []:
            asset = resources.get(str(entry.get("mediaKey")))
            if not asset or not asset.get("fileHash"):
                raise PalmierError(
                    f"overlay {entry.get('elementId')!r} has no bound asset")
            entries.append({**entry, "assetPath": asset["path"],
                            "assetHash": asset["fileHash"]})
        result.append({**row, "entries": entries})
    return result

def _repair_steps(context: NativeContext, project: dict,
                  cache: str) -> tuple[list[dict], dict]:
    plan = context.plan
    prior = project.get("plan") if isinstance(project, dict) else None
    prior_path = prior.get("path") if isinstance(prior, dict) else None
    if not isinstance(prior_path, str):
        raise PalmierError("scoped repair has no prior plan authority")
    from palmier.desktop_repair import RepairRenderContext, build_scoped_repair
    from palmier.presenter_asset import primary_source
    old_plan = read_json(prior_path, "prior edit plan")
    render_context = RepairRenderContext(
        context.fps, cache, primary_source(context.manifest))
    steps, scope = build_scoped_repair(
        old_plan, plan, render_context, project.get("elementLedger"))
    capability = {"mode": "scoped-card-repair", "approved": False,
                  "scope": scope, "omissions": [],
                  "limitations": []}
    return steps, capability


def _prepare_stage(inputs: DesktopStageInput, project: dict,
                   spec: CheckpointInput,
                   context: NativeContext) -> PreparedDesktopStage:
    cache = str(spec.cache_dir)
    if inputs.stage in {"repair", "revision"}:
        authority = input_authority(spec, context.plan)
        if inputs.stage == "repair":
            steps, capability = _repair_steps(context, project, cache)
            return PreparedDesktopStage(authority, steps, capability)
        from palmier.desktop_revision import prepare_manifest_revision
        steps, capability, revision = prepare_manifest_revision(
            inputs, context, project, cache)
        return PreparedDesktopStage(authority, steps, capability, revision)
    authority, translated, capability = checkpoint_inputs(spec, project)
    steps = _cut_worklist(context.plan, context.fps) \
        if inputs.stage == "cut" else _visual_steps(translated)
    if inputs.stage == "visual":
        steps.extend(_native_steps(context))
        capability = _desktop_capability(capability, steps)
    return PreparedDesktopStage(
        authority, _bind_media_hashes(steps), capability)


def prepare_desktop_manifest(inputs: DesktopStageInput,
                             project: dict) -> dict:
    """Render deterministic assets and persist the exact staged worklist."""
    if inputs.stage not in {"cut", "visual", "repair", "revision"}:
        raise PalmierError(
            f"unknown Desktop Palmier stage {inputs.stage!r}")
    cache = os.path.join(inputs.out_dir, ".palmier-desktop-assets")
    os.makedirs(cache, exist_ok=True)
    stage = inputs.stage if inputs.stage in {"cut", "repair"} else "plan"
    spec = CheckpointInput(inputs.out_dir, inputs.plan_path,
                           inputs.manifest_path, stage, 0,
                           cache_dir=cache)
    plan = read_json(inputs.plan_path, "edit plan")
    manifest = read_json(inputs.manifest_path, "asset manifest")
    fps = float((project.get("projectSettings") or {}).get("fps") or 0)
    if fps <= 0:
        raise PalmierError("Desktop Palmier project has no positive fps")
    context = NativeContext(
        plan, manifest, fps, _duration(plan),
        os.path.dirname(os.path.abspath(inputs.manifest_path)))
    prepared = _prepare_stage(inputs, project, spec, context)
    content = manifest_content(inputs, prepared)
    content["digest"] = _hash(content)
    path = os.path.join(
        inputs.out_dir, f"{MANIFEST_NAME}.{content['digest'][:16]}.json")
    atomic_write_record(path, content)
    result = {"path": path, "hash": file_sha256(path), "content": content}
    if prepared.revision is not None:
        result["revision"] = content["revision"]
    return result
