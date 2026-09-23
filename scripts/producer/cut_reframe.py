"""Fuse deterministic native-resolution crops into the existing cut encoder."""
from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Protocol

from media_probe import display_dims, probe_video
from motion.reframe import crop_scale_vf
from producer_config import CANVAS, MODES

if TYPE_CHECKING:
    from cut_speed import Profile


@dataclass(frozen=True)
class FusedReframe:
    """Geometry already determined before any cut part is encoded."""

    source_width: int
    source_height: int
    strategy: str
    video_filter: str

    def output_profile(self, profile: Profile) -> Profile:
        """Keep the exact source frame clock while encoding at delivery geometry."""
        if (profile.width, profile.height) != (self.source_width, self.source_height):
            raise RuntimeError("fused reframe source geometry changed before cut encoding")
        return replace(profile, width=CANVAS["width"], height=CANVAS["height"],
                       pix_fmt=CANVAS["pix_fmt"])

    def record(self) -> dict:
        """Record actual crop order, geometry and the selected existing strategy."""
        return {"schemaVersion": 1, "kind": "cut-reframe-fusion",
                "strategy": self.strategy, "sourceWidth": self.source_width,
                "sourceHeight": self.source_height, "width": CANVAS["width"],
                "height": CANVAS["height"], "pixelFormat": CANVAS["pix_fmt"],
                "filter": self.video_filter, "cropBeforeScale": True}


class ReframeContext(Protocol):
    """Required render facts without importing the GUI-capable orchestrator."""

    plan: dict
    manifest: dict
    resume: bool
    out_dir: str
    bootstrap_trace: list[dict]
    fused_reframe: FusedReframe | None


def _common_dimensions(plan: dict, manifest: dict) -> tuple[int, int] | None:
    """Mixed geometry retains the original normalize-then-reframe pipeline."""
    sources = {row["id"]: row["path"] for row in manifest.get("sources", [])}
    used = {row["sourceId"] for row in plan.get("cutTrack", [])}
    if not used or not used.issubset(sources):
        return None
    paths = {sources[key] for key in used}
    if any(not os.path.isfile(path) for path in paths):
        return None
    sizes = {display_dims(probe_video(path)) for path in paths}
    return next(iter(sizes)) if len(sizes) == 1 else None


def select_fusion(ctx: ReframeContext, guarded: bool) -> FusedReframe | None:
    """Optimize known crops; tracking, baseline and protected routes keep their owner."""
    cfg = ctx.plan.get("reframe") or {}
    mode = ctx.plan.get("target", {}).get("mode")
    if guarded or ctx.resume or ctx.plan.get("baselineLook") or mode not in MODES:
        return None
    if cfg.get("layout", "fill") != "fill" or cfg.get("crop") is not None:
        return None
    strategy = cfg.get("strategy", MODES[mode]["reframe_default"])
    if strategy not in {"center", "face"}:
        return None
    dimensions = _common_dimensions(ctx.plan, ctx.manifest)
    if dimensions is None:
        return None
    width, height = dimensions
    if width * height <= CANVAS["width"] * CANVAS["height"]:
        return None
    if strategy == "face" and height <= width:
        return None  # Landscape face windows still require measured tracking.
    # face_track._decide_window always returns portrait-passthrough here,
    # independent of detections. Use its identical downstream crop filter.
    return FusedReframe(width, height, strategy, crop_scale_vf(width, height))


def finish_fused_reframe(ctx: ReframeContext, video: str) -> str:
    """Expose the completed cut-stage operation without pretending to run it twice."""
    from fingerprint_io import write_json_atomic
    from media_probe import probe_video_frames

    if ctx.fused_reframe is None:
        raise RuntimeError("fused reframe requires a selected crop")
    record = ctx.fused_reframe.record()
    actual = probe_video(video)
    if display_dims(actual) != (record["width"], record["height"]):
        raise RuntimeError("fused cut did not produce the required reframe geometry")
    record["videoFrames"] = probe_video_frames(video)
    write_json_atomic(os.path.join(ctx.out_dir, "cut_reframe.json"), record)
    ctx.bootstrap_trace.append({"stage": "reframe", "executed": False,
        "status": "fused-in-cut", "input": video, "output": video, **record})
    return video
