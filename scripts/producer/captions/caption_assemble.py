#!/usr/bin/env python3
"""Assemble-time CaptionTrackV1 projection outside the reusable picture base."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from typing import Callable

from captions.caption_authority import write_caption_artifacts
from captions.caption_fingerprints import canonical_digest
from captions.caption_plan_pipeline import (
    PlanCaptionContext,
    compile_plan_caption_track,
    has_explicit_caption_track,
)
from captions.caption_words import CaptionFrameRate
from captions.cut_repair_dialogue_authority import (
    compile_plan_cut_repair_captions,
)
from captions.caption_shard_composite import apply_caption_shards
from captions.caption_shards import materialize_caption_shards
from compile_timeline import TimelineMap
from fingerprints import file_sha256, write_json_atomic
from media_probe import _fps_fraction, probe_video, probe_video_frames
from producer_config import MODES

CAPTION_FREE_NAME = ".caption-free-composite.mp4"
CAPTION_FREE_AUTHORITY_NAME = ".caption-free-composite.json"


def _cache_paths(job: object) -> tuple[str, str]:
    directory = os.path.dirname(os.path.abspath(getattr(job, "out")))
    return (
        os.path.join(directory, CAPTION_FREE_NAME),
        os.path.join(directory, CAPTION_FREE_AUTHORITY_NAME),
    )


def _graphics_source_closure() -> list[dict]:
    producer_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    roots = (
        os.path.join(producer_dir, "graphics"),
        os.path.join(producer_dir, "planner"),
    )
    paths = [
        os.path.join(root, name)
        for root in roots for name in sorted(os.listdir(root))
        if name.endswith(".py")
    ]
    paths.extend((
        os.path.join(producer_dir, "assemble.py"),
        os.path.join(producer_dir, "producer_config.py"),
    ))
    return [{
        "name": os.path.relpath(path, producer_dir),
        "sha256": file_sha256(path),
    } for path in paths]


def _tool_identity(name: str) -> dict:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"caption-free cache cannot resolve {name}")
    resolved = os.path.realpath(path)
    info = os.stat(resolved)
    return {
        "path": resolved, "size": info.st_size, "mtimeNs": info.st_mtime_ns,
    }


def _graphics_authority(plan: dict) -> str:
    from graphics.exit_on_cut import apply_exit_on_cut
    from graphics.graphics_render import comp_path, content_hash
    from planner.occupancy import plan_band_offset
    track, _ = apply_exit_on_cut(plan)
    render_keys = []
    for row in track:
        path = comp_path(row["kind"])
        with open(path, encoding="utf-8") as handle:
            html = handle.read()
        render_keys.append(content_hash(
            row["kind"], row.get("spec") or {},
            float(row["outEnd"]) - float(row["outStart"]), html))
    return canonical_digest("sniper-caption-free-graphics-v1", {
        "track": track,
        "bandYOffsetPx": plan_band_offset(plan),
        "renderKeys": render_keys,
        "compositeFfmpeg": _tool_identity("ffmpeg"),
        "sourceClosure": _graphics_source_closure(),
    })


def _cache_inputs(job: object) -> dict:
    from fingerprints import base_plan_digest
    plan = getattr(job, "plan")
    return {
        "baseAuthorityHash": file_sha256(getattr(job, "base")),
        "basePlanDigest": base_plan_digest(plan),
        "graphicsAuthorityHash": _graphics_authority(plan),
    }


def _atomic_copy(source: str, destination: str) -> None:
    directory = os.path.dirname(os.path.abspath(destination))
    descriptor, staged = tempfile.mkstemp(
        prefix=f".{os.path.basename(destination)}.", suffix=".tmp",
        dir=directory)
    os.close(descriptor)
    try:
        os.remove(staged)
        try:
            os.link(source, staged)
        except OSError:
            shutil.copyfile(source, staged)
        with open(staged, "rb") as handle:
            os.fsync(handle.fileno())
        os.replace(staged, destination)
    finally:
        if os.path.exists(staged):
            os.remove(staged)


def checkpoint_caption_free_composite(job: object) -> dict | None:
    """Persist the proved post-graphics/pre-caption node for local caption edits."""
    if not has_explicit_caption_track(getattr(job, "plan")):
        return None
    media_path, receipt_path = _cache_paths(job)
    _atomic_copy(getattr(job, "out"), media_path)
    payload = {
        "schemaVersion": 1, "kind": "caption-free-composite-authority",
        **_cache_inputs(job),
        "media": {
            "name": os.path.basename(media_path),
            "sha256": file_sha256(media_path),
        },
    }
    receipt = {
        **payload,
        "authorityHash": canonical_digest(
            "sniper-caption-free-composite-authority-v1", payload),
    }
    write_json_atomic(receipt_path, receipt, indent=2)
    return receipt


def restore_caption_free_composite(job: object) -> bool:
    """Restore a caption-free composite only when every upstream byte matches."""
    if not has_explicit_caption_track(getattr(job, "plan")):
        return False
    media_path, receipt_path = _cache_paths(job)
    try:
        with open(receipt_path, encoding="utf-8") as handle:
            receipt = json.load(handle)
        current_inputs = _cache_inputs(job)
        payload = {key: value for key, value in receipt.items()
                   if key != "authorityHash"}
        current = (
            receipt.get("authorityHash") == canonical_digest(
                "sniper-caption-free-composite-authority-v1", payload)
            and {key: receipt.get(key) for key in current_inputs}
            == current_inputs
            and receipt.get("media") == {
                "name": os.path.basename(media_path),
                "sha256": file_sha256(media_path),
            }
        )
    except (OSError, ValueError, json.JSONDecodeError, AttributeError):
        return False
    if not current:
        return False
    _atomic_copy(media_path, getattr(job, "out"))
    return True


def _compile_caption_authority(job: object, plan: dict) -> tuple[str, dict]:
    manifest_path = getattr(job, "manifest")
    output_path = getattr(job, "out")
    if not manifest_path or not os.path.isfile(manifest_path):
        raise RuntimeError(
            "CaptionTrackV1 assemble requires the source manifest")
    out_dir = os.path.dirname(os.path.abspath(output_path))
    map_path = os.path.join(out_dir, "timeline_map.json")
    if not os.path.isfile(map_path):
        raise RuntimeError(
            "CaptionTrackV1 assemble requires timeline_map.json beside output")
    with open(manifest_path, encoding="utf-8") as handle:
        manifest = json.load(handle)
    manifest["_path"] = os.path.abspath(manifest_path)
    with open(map_path, encoding="utf-8") as handle:
        timeline = TimelineMap.from_dict(json.load(handle))
    fraction = _fps_fraction(probe_video(
        getattr(job, "base"))["r_frame_rate"])
    rate = CaptionFrameRate(fraction.numerator, fraction.denominator)
    context = PlanCaptionContext(
        plan, manifest, timeline, rate,
        os.path.dirname(os.path.abspath(manifest_path)),
        total_frames=probe_video_frames(getattr(job, "base")))
    compilation = (
        compile_plan_cut_repair_captions(context.plan, context.rate)
        or compile_plan_caption_track(context))
    if compilation is None:
        raise RuntimeError(
            "CaptionTrackV1 authority disappeared during assemble")
    return output_path, compilation


def project_caption_track(job: object, emit: Callable[..., None]) -> dict | None:
    """Compile/burn explicit captions after graphics, outside the picture base."""
    plan = getattr(job, "plan")
    if not has_explicit_caption_track(plan):
        return None
    output_path, compilation = _compile_caption_authority(job, plan)
    out_dir = os.path.dirname(os.path.abspath(output_path))
    shards = materialize_caption_shards(plan, compilation, out_dir)
    artifacts = write_caption_artifacts(
        plan, compilation, out_dir, shards.manifest)
    mode = (plan.get("target") or {}).get("mode")
    fallback = MODES.get(mode, {}).get("captions_burn", False)
    burn = bool((plan.get("captions") or {}).get("burn", fallback))
    if burn and not compilation["cues"]:
        raise RuntimeError(
            "captions.burn is on but CaptionTrackV1 compiled no cues")
    composite = (apply_caption_shards(output_path, shards.manifest)
                 if burn else {"shards": 0, "encoded": False})
    emit(status="caption_track_projected", cues=len(compilation["cues"]),
         burned=burn, alphaShards=composite["shards"],
         cacheHits=shards.cache_hits, renderedShards=shards.rendered,
         authorityHash=artifacts.receipt["authorityHash"])
    return {
        "cues": len(compilation["cues"]), "burned": burn,
        "alphaShards": composite["shards"],
        "cacheHits": shards.cache_hits, "renderedShards": shards.rendered,
        "authorityHash": artifacts.receipt["authorityHash"],
    }
