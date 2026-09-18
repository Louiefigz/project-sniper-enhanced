#!/usr/bin/env python3
"""Current-render orchestration adapter for explicit CaptionTrackV1 plans."""
from __future__ import annotations

import os
from dataclasses import dataclass
from fractions import Fraction

from captions.caption_authority import CaptionArtifactSet, write_caption_artifacts
from captions.caption_plan_pipeline import (
    PlanCaptionContext,
    compile_plan_caption_track,
)
from captions.caption_pages import CaptionPageSet, materialize_caption_pages
from captions.cut_repair_dialogue_authority import (
    compile_plan_cut_repair_captions,
)
from captions.caption_shards import CaptionShardSet, materialize_caption_shards
from captions.caption_words import CaptionFrameRate
from cut_speed import probe_video
from cut_manifestation_authority import verify_manifestation


@dataclass(frozen=True)
class RenderCaptionProjection:
    """One renderer-consumed caption compilation and its persisted artifacts."""

    compilation: dict
    artifacts: CaptionArtifactSet
    shards: CaptionShardSet
    pages: CaptionPageSet


def _source_path(ctx: object) -> str:
    plan = getattr(ctx, "plan")
    manifest = getattr(ctx, "manifest")
    first = str((plan.get("cutTrack") or [{}])[0].get("sourceId", ""))
    sources = {
        str(row.get("id")): row.get("path")
        for row in manifest.get("sources", [])
        if isinstance(row, dict)
    }
    path = sources.get(first)
    if not isinstance(path, str) or not path:
        raise RuntimeError(
            "CaptionTrackV1 cannot resolve the first picture source")
    manifest_path = manifest.get("_path")
    if not os.path.isabs(path) and isinstance(manifest_path, str):
        path = os.path.join(os.path.dirname(os.path.abspath(manifest_path)), path)
    return path


def project_render_captions(ctx: object,
                            timeline: object) -> RenderCaptionProjection:
    """Compile once per render context and persist shared output projections."""
    cached = getattr(ctx, "caption_projection", None)
    if isinstance(cached, RenderCaptionProjection):
        return cached
    raw_rate = probe_video(_source_path(ctx))["r_frame_rate"]
    rate = Fraction(str(raw_rate))
    manifest = getattr(ctx, "manifest")
    manifest_path = manifest.get("_path")
    out_dir = getattr(ctx, "out_dir")
    manifest_dir = (os.path.dirname(os.path.abspath(manifest_path))
                    if isinstance(manifest_path, str) else out_dir)
    manifestation = verify_manifestation(out_dir, getattr(ctx, "plan"))
    total_frames = manifestation["concat"]["videoFrames"]
    context = PlanCaptionContext(
        getattr(ctx, "plan"), manifest, timeline,
        CaptionFrameRate(rate.numerator, rate.denominator), manifest_dir,
        total_frames=total_frames)
    compilation = (
        compile_plan_cut_repair_captions(context.plan, context.rate)
        or compile_plan_caption_track(context))
    if compilation is None:
        raise RuntimeError("CaptionTrackV1 authority disappeared during render")
    shards = materialize_caption_shards(
        getattr(ctx, "plan"), compilation, out_dir)
    artifacts = write_caption_artifacts(
        getattr(ctx, "plan"), compilation, out_dir, shards.manifest)
    pages = materialize_caption_pages(
        shards.manifest, artifacts.receipt, out_dir, total_frames)
    projection = RenderCaptionProjection(
        compilation, artifacts, shards, pages)
    setattr(ctx, "caption_projection", projection)
    return projection
