"""Prepare a hash-bound, Desktop-readable Palmier execution manifest."""
from __future__ import annotations
import hashlib
import json
import os

from fingerprints import file_sha256
from ingest_execution_authority import verify_execution_media_authority
from palmier.desktop_audio_master_plan import (
    MasteredStereoPlanRequest, extend_mastered_stereo_worklist,
    preserved_mastered_stereo_authority)
from palmier.checkpoint_inputs import (CheckpointInput, checkpoint_inputs,
                                       input_authority, read_json)
from palmier.mcp_client import PalmierError
from palmier.desktop_manifest_native import (
    NativeContext, _broll_steps, native_steps)
from palmier.desktop_manifest_record import (PreparedDesktopStage,
                                             manifest_content)
from palmier.desktop_manifest_media import bind_media_hashes
from palmier.desktop_state import DesktopStageInput
from palmier.timeline_authority import atomic_write_record
MANIFEST_NAME = ".palmier-desktop-operations"


def _hash(value: object) -> str:
    blob = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _duration(plan: dict) -> float:
    return sum((float(row["end"]) - float(row["start"]))
               / float(row.get("speed", 1.0) or 1.0)
               for row in plan.get("cutTrack") or [])


def _visual_steps(steps: list[dict]) -> list[dict]:
    """Cut stage already landed; retain only downstream translated steps."""
    kept = [row for row in steps if row.get("op") not in
            {"project", "cuts", "mirror", "baseline", "text"}
            and not (row.get("op") == "import" and row.get("key") == "src")]
    layered: list[dict] = []
    for row in kept:
        layered.extend(_exact_graphics(row) if row.get("op") == "overlays"
                       else [row])
    return layered


def _exact_graphics(step: dict) -> list[dict]:
    """Preserve plan order with one governed top track per full-canvas asset."""
    from palmier.desktop_caption_shard_plan import (
        FULL_CANVAS_TRANSFORM, GRAPHICS_OP,
    )
    rows = []
    for entry in step.get("entries") or []:
        if entry.get("transform") != FULL_CANVAS_TRANSFORM:
            raise PalmierError(
                "Desktop graphic is not a normalized full-canvas asset")
        rows.append({
            **entry, "op": GRAPHICS_OP, "lane": "graphics",
            "alphaMode": "proved-by-rendered-asset",
            "trackPolicy": "new-top-video-track-per-graphic",
            "transform": FULL_CANVAS_TRANSFORM,
        })
    return rows


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


def _ordered_visual_layers(groups: list[list[dict]]) -> list[dict]:
    """Emit mutations in production bottom-to-top visual layer order."""
    rows = [row for group in groups for row in group]
    layer_ops = {
        "native-broll", "title-alpha-shard",
        "graphics-alpha-shard", "caption-alpha-pages",
    }
    imports = [row for row in rows if row.get("op") == "import"]
    base = [row for row in rows
            if row.get("op") != "import" and row.get("op") not in layer_ops]
    layers = [[row for row in rows if row.get("op") == op] for op in (
        "native-broll", "title-alpha-shard",
        "graphics-alpha-shard", "caption-alpha-pages",
    )]
    return [*imports, *base, *(row for layer in layers for row in layer)]


def _repair_steps(context: NativeContext, project: dict,
                  cache: str) -> tuple[list[dict], dict]:
    plan = context.plan
    prior = project.get("plan") if isinstance(project, dict) else None
    prior_path = prior.get("path") if isinstance(prior, dict) else None
    if not isinstance(prior_path, str):
        raise PalmierError("scoped repair has no prior plan authority")
    from palmier.desktop_repair import RepairRenderContext, build_scoped_repair
    from palmier.presenter_asset import primary_source
    from palmier.checkpoint_graphics import placement_context
    old_plan = read_json(prior_path, "prior edit plan")
    settings = project.get("projectSettings") or {}
    canvas = (settings.get("width"), settings.get("height"))
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or value <= 0 for value in canvas):
        raise PalmierError("scoped repair has no positive project canvas")
    placed = placement_context(
        context.out_dir, plan, cache,
        {"fps": context.fps, "width": int(canvas[0]),
         "height": int(canvas[1])})
    render_context = RepairRenderContext(
        context.fps, cache, primary_source(context.manifest), placed)
    steps, scope = build_scoped_repair(
        old_plan, plan, render_context, project.get("elementLedger"))
    capability = {"mode": "scoped-card-repair", "approved": False,
                  "scope": scope, "omissions": [],
                  "limitations": []}
    return steps, capability


def _prepare_visual(
        request: dict, steps: list[dict],
        capability: dict) -> tuple[list[dict], dict]:
    inputs = request["inputs"]
    context = request["context"]
    project = request["project"]
    authority = request["authority"]
    from palmier.desktop_frame_authority import \
        resolve_desktop_frame_authority
    frame_authority = resolve_desktop_frame_authority(
        inputs, authority, project)
    native_rows = native_steps(context)
    from palmier.desktop_title_card_plan import plan_title_card_shards
    title_steps, title_capability = plan_title_card_shards(
        context.plan, context.out_dir, project, frame_authority.frames)
    from palmier.desktop_caption_page_plan import plan_caption_pages
    caption_steps, caption_capability = plan_caption_pages(
        context.plan, context.out_dir, project, frame_authority.frames)
    steps = _ordered_visual_layers([
        steps, native_rows, title_steps, caption_steps])
    from palmier.desktop_exact_master_plan import \
        prepare_exact_master_reference
    exact, reference = prepare_exact_master_reference(
        inputs, authority, project, frame_authority)
    steps.extend(exact)
    steps = extend_mastered_stereo_worklist(
        steps, MasteredStereoPlanRequest(
            context.plan, inputs, authority, project,
            frame_authority.frames, request["cache"]))
    capability = _desktop_capability(capability, steps)
    capability["exactMasterReference"] = reference
    if caption_capability:
        capability["captionAuthority"] = caption_capability
    if title_capability:
        capability["titleCardAuthority"] = title_capability
    return steps, capability


def _prepare_stage(inputs: DesktopStageInput, project: dict,
                   spec: CheckpointInput,
                   context: NativeContext) -> PreparedDesktopStage:
    cache = str(spec.cache_dir)
    if inputs.stage in {"repair", "revision"}:
        authority = input_authority(spec, context.plan)
        from palmier.desktop_frame_authority import \
            resolve_desktop_frame_authority
        frame_authority = resolve_desktop_frame_authority(
            inputs, authority, project)
        audio_request = MasteredStereoPlanRequest(
            context.plan, inputs, authority, project,
            frame_authority.frames, cache)
        preserved_audio = preserved_mastered_stereo_authority(audio_request)
        if inputs.stage == "repair":
            steps, capability = _repair_steps(context, project, cache)
            if preserved_audio is None:
                steps = extend_mastered_stereo_worklist(steps, audio_request)
            else:
                capability[
                    "preservedMasteredStereoAuthority"] = preserved_audio
            return PreparedDesktopStage(authority, steps, capability)
        from palmier.desktop_revision import prepare_manifest_revision
        steps, capability, revision = prepare_manifest_revision(
            inputs, context, project, cache)
        if preserved_audio is None:
            steps = extend_mastered_stereo_worklist(steps, audio_request)
        else:
            capability["preservedMasteredStereoAuthority"] = preserved_audio
        return PreparedDesktopStage(authority, steps, capability, revision)
    authority, translated, capability = checkpoint_inputs(spec, project)
    steps = _cut_worklist(context.plan, context.fps) \
        if inputs.stage == "cut" else _visual_steps(translated)
    if inputs.stage == "visual":
        steps, capability = _prepare_visual({
            "inputs": inputs, "context": context, "project": project,
            "authority": authority, "cache": cache,
        }, steps, capability)
    return PreparedDesktopStage(
        authority, bind_media_hashes(steps), capability)


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
    verify_execution_media_authority(
        plan, manifest, inputs.manifest_path)
    fps = float((project.get("projectSettings") or {}).get("fps") or 0)
    if fps <= 0:
        raise PalmierError("Desktop Palmier project has no positive fps")
    context = NativeContext(
        plan, manifest, fps, _duration(plan),
        os.path.dirname(os.path.abspath(inputs.manifest_path)),
        inputs.out_dir)
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
