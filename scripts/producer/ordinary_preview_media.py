"""Ordinary preview media uses the actual base, compositor and full audio master.

The cold preparation still renders a full graphics-free base. Only composed
preview windows are bounded; no finished full composite or delivery is made.
"""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from pathlib import Path

from assemble import BaseManifest, _base_state
from audio.program_master_bus import build_program_master
from audio.program_master_cache import load_program_master
from audio.program_master_excerpt import extract_program_range
from audio.render_audio_authority import SOURCE_FLOAT_POLICY_V2
from audio.render_audio_cache import load_source_bus
from compile_timeline import TimelineMap
from cut_preview_io import bound_json, file_hash
from graphics.composite_core import CompositeOptions, composite
from graphics.exit_on_cut import apply_exit_on_cut
from graphics.graphics_stage import GraphicsJob, _render_all
from guided_opening_mux import mux_ranges
from guided_opening_picture import observe_picture
from ingest_execution_authority import verify_execution_media_authority
from ordinary_preview_windows import preparation_key
from render import RenderCtx, render
from render_effect_registry import validate_render_documents
from studio.native_stage_evidence import require


def _context(request: dict, root: Path) -> RenderCtx:
    """Carry the real canonical documents into ordinary private base preparation."""
    manifest = {**request["manifest"], "_path": request["manifestPath"]}
    return RenderCtx(deepcopy(request["plan"]), manifest, str(root), str(root / "work"),
                     skip_graphics=True, producer_dir=request["project"],
                     plan_path=request["planPath"], audio_clock_policy=SOURCE_FLOAT_POLICY_V2)


def prepare(request: dict, root: Path, previous: dict | None) -> dict:
    """Reopen proved unchanged media, or prepare one private full base/master."""
    key = preparation_key(request)
    if previous and previous["key"] == key:
        _load_prepared(request, previous)
        return {**previous, "baseReused": True, "masterReused": True}
    base_dir = root / "base"
    base_dir.mkdir(mode=0o700)
    (base_dir / "work").mkdir(mode=0o700)
    ctx = _context(request, base_dir)
    validate_render_documents(ctx.plan, ctx.manifest)
    verify_execution_media_authority(ctx.plan, ctx.manifest, request["manifestPath"])
    render(ctx)
    require(ctx.plan == request["plan"] and ctx.source_audio_bus is not None,
            "Ordinary preparation changed the reviewed plan or omitted its source bus")
    bus = ctx.source_audio_bus
    base = base_dir / "final.mp4"
    master = build_program_master(bus, ctx.plan)
    from media_probe import probe_video
    stream = probe_video(str(base))
    canvas = stream["width"], stream["height"]
    picture = observe_picture(base, (bus.frame_rate, bus.frames, canvas), bus.admission.tools)
    return {"key": key, "base": str(base), "baseSha256": picture["sha256"],
            "frameRate": bus.frame_rate, "totalFrames": bus.frames, "canvas": list(canvas),
            "sourceBusReceiptHash": bus.receipt["receiptHash"],
            "masterReceipt": str(Path(master.directory) / "master-receipt.json"),
            "masterReceiptHash": master.receipt["receiptHash"],
            "baseReused": False, "masterReused": False,
            "coldCost": "full-graphics-free-base-and-whole-program-audio-master"}


def _load_prepared(request: dict, prepared: dict) -> tuple:
    """Revalidate real source bytes, code, exact base and full-master receipts."""
    require(prepared["key"] == preparation_key(request), "Ordinary preparation dependencies changed")
    base = Path(prepared["base"])
    require(file_hash(base) == prepared["baseSha256"], "Ordinary preview base changed")
    state = _base_state(str(base), request["plan"], str(base.parent / "base.fingerprint.json"),
                        BaseManifest(request["manifestPath"], SOURCE_FLOAT_POLICY_V2))
    require(state == "current", "Ordinary preview base is stale")
    ctx = _context(request, base.parent)
    bus = load_source_bus(ctx.plan, ctx.manifest, (str(base.parent), str(base)), prepared["sourceBusReceiptHash"])
    require(bus.frame_rate == prepared["frameRate"] and bus.frames == prepared["totalFrames"],
            "Ordinary preview clock changed")
    master = load_program_master(bus, ctx.plan, (prepared["masterReceipt"], prepared["masterReceiptHash"]))
    return ctx, master


def _captions(ctx: RenderCtx, clock: tuple[str, int], span: tuple[int, int]) -> list[dict]:
    """Project actual full-origin caption pages after graphics, as final assembly does."""
    from captions.caption_plan_pipeline import has_explicit_caption_track
    from captions.caption_render import project_render_captions
    from edit_scope import caption_burn_enabled
    if not has_explicit_caption_track(ctx.plan) or not caption_burn_enabled(ctx.plan):
        return []
    timeline = TimelineMap.from_dict(bound_json(Path(ctx.out_dir) / "timeline_map.json"))
    projection = project_render_captions(ctx, timeline)
    rate = Fraction(clock[0])
    result = []
    for row in projection.pages.manifest["entries"]:
        start, end = row["startFrame"], row["endFrameExclusive"]
        if start >= span[1] or end <= span[0]:
            continue
        file = Path(ctx.out_dir) / row["media"]["name"]
        require(file_hash(file) == row["media"]["sha256"], "Ordinary caption page changed")
        result.append({"path": str(file), "outStart": float(start / rate), "outEnd": float(end / rate),
                       "startFrame": start, "endFrameExclusive": end, "x": 0, "y": 0,
                       "anchor": "own-screen", "compositionRole": "caption-page", "captionPageId": row["pageId"]})
    return result


def _graphics(ctx: RenderCtx, prepared: dict, window: dict, root: Path) -> list[dict]:
    """Render only intersecting graphics at their original full animation duration."""
    track, _clamped = apply_exit_on_cut(ctx.plan)
    rate = Fraction(prepared["frameRate"])
    start, end = window["startFrame"] / rate, window["endFrameExclusive"] / rate
    track = [row for row in track if row["outStart"] <= float(end) and row["outEnd"] >= float(start)]
    from planner.occupancy import plan_band_offset
    job = GraphicsJob(prepared["base"], str(root / "picture.mp4"), track,
                      cache_dir=str(Path(ctx.producer_dir) / ".sniper-previews/graphics-cache"),
                      band_y_offset_px=plan_band_offset(ctx.plan))
    clips, _placements = _render_all(job)
    return clips


def render_window(request: dict, prepared: dict, window: dict, root: Path) -> dict:
    """Trim after full-clock composition and extract samples from the whole master."""
    ctx, master = _load_prepared(request, prepared)
    span = window["startFrame"], window["endFrameExclusive"]
    rate, total = prepared["frameRate"], prepared["totalFrames"]
    require(0 <= span[0] < span[1] <= total and Fraction(span[1] - span[0]) / Fraction(rate) <= 12,
            "Ordinary preview exceeds the bounded absolute frame window")
    clips = _graphics(ctx, prepared, window, root)
    captions = _captions(ctx, (rate, total), span)
    picture_path = root / "picture.mp4"
    tools = master.source_bus.admission.tools
    options = CompositeOptions(eof_pass=True, ffmpeg=tools["ffmpeg"]["path"],
        ffprobe=tools["ffprobe"]["path"], frame_rate=rate, frame_range=span, video_only=True,
        ordinary_timing=True, caption_tail=len(captions) if captions else None)
    composite(prepared["base"], [*clips, *captions], str(picture_path), options)
    picture = observe_picture(picture_path, (rate, span[1] - span[0], tuple(prepared["canvas"])), tools)
    pcm = extract_program_range(master, ctx.plan, span, root / "audio.wav")
    audio = {"core": pcm, "review": pcm}
    media = mux_ranges(root, {"ranges": {"core": picture, "review": picture}}, audio, tools)["review"]
    _load_prepared(request, prepared)
    return {**media, "window": window, "continuousFrames": span[1] - span[0],
            "fullProgramMasterUsed": True, "editorialReview": "pending", "finalQcRequired": True}
