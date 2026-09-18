"""Counted ordinary full-base preparation and an actual full-master selection.

This internal development adapter reuses render.render, not a preview-specific
renderer or the legacy delivery CLI's template-history approval. Its caller
must first validate the distinct accepted-cut/readiness/source authority. All
artifacts are new/private; the base's final.mp4 filename is not a public final.
"""
from __future__ import annotations

import copy
import time
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from audio.program_master_bus import build_program_master
from audio.program_master_selection import HeldMasterSelection, SelectionContext, capture_master_selection
from audio.render_audio_authority import SOURCE_FLOAT_POLICY_V2
from cut_preview_io import digest, file_hash
from cut_manifestation_authority import MANIFESTATION_NAME
from guided_opening_inputs import OpeningInputs
from guided_opening_picture import observe_picture
from ingest_execution_authority import verify_execution_media_authority
from render import RenderCtx, render
from render_effect_registry import validate_render_documents
from guided_media_profile import SHORT_PROFILE
from guided_opening_frames import _profile
from guided_short_geometry import capture_short_geometry, preflight_short_source
from guided_caption_dependencies import Guard
from guided_caption_projection import HeldCaptionProjection
from guided_caption_profile import caption_profile
from guided_caption_integration import caption_input_dependencies, capture_prepared_captions
from guided_presenter_base import PresenterBaseContext, require_presenter_preparation
from guided_source_color_base_context import SourceColorBaseContext


@dataclass(frozen=True)
class OpeningPreparation:
    """Held actual ordinary execution result, never reconstructed from pointers."""

    base: Path
    selection: HeldMasterSelection
    evidence: dict
    captions: HeldCaptionProjection | None = None


def _validate_preparation(inputs: OpeningInputs, plan: dict, manifest: dict) -> None:
    """Retain ordinary source gates and add only explicit short geometry limits."""
    validate_render_documents(plan, manifest)
    verify_execution_media_authority(plan, manifest, inputs.value["documents"]["manifest"]["path"])
    preflight_short_source(inputs)


def _base_directories(root: Path) -> tuple[Path, Path]:
    """Create only new private base/work directories after preparation admission."""
    base_dir = root / "full-program-base"
    base_dir.mkdir(mode=0o700)
    work = base_dir / "work"
    work.mkdir(mode=0o700)
    return base_dir, work


def prepare_full_program(inputs: OpeningInputs, root: Path, guard: Guard | None = None,
                         presenter_base: PresenterBaseContext | None = None) -> OpeningPreparation:
    """Run ordinary lint/ingest/cut/base, then qualify the whole float mix/master."""
    return _prepare(inputs, root, (guard, presenter_base, None))


def prepare_source_color_full_program(inputs: OpeningInputs, root: Path,
                                     context: SourceColorBaseContext) -> OpeningPreparation:
    """Borrow actual longform identity without upgrading the schema1 result proof."""
    if type(context) is not SourceColorBaseContext or context.inputs is not inputs:
        raise RuntimeError("source-color preparation requires the actual same-input context")
    context.consumption.begin_preparation()
    SourceColorBaseContext.assert_current(context)
    result = _prepare(inputs, root, (context.assert_current, None, context))
    SourceColorBaseContext.assert_current(context)
    SourceColorBaseContext.consumption_record(context)
    return result


def _prepare(inputs: OpeningInputs, root: Path, owners: tuple) -> OpeningPreparation:
    """Share ordinary operations; absent source ownership keeps its exact old path."""
    guard, presenter_base, source_color_base = owners
    require_presenter_preparation(inputs, presenter_base)
    started = time.monotonic()
    plan = copy.deepcopy(inputs.documents["candidatePlan"])
    if inputs.value.get("profile") == SHORT_PROFILE:
        _profile(plan, SHORT_PROFILE)
    manifest = copy.deepcopy(inputs.documents["manifest"])
    refs, authority = inputs.value["documents"], inputs.documents["authority"]
    captioned = caption_profile(inputs.value.get("profile"))
    if captioned and guard is None:
        raise RuntimeError("caption preparation requires its original live owner clock")
    dependencies = caption_input_dependencies(inputs, guard) if captioned else ()
    _validate_preparation(inputs, plan, manifest)
    if source_color_base is not None:
        SourceColorBaseContext.assert_current(source_color_base)
    manifest["_path"] = refs["manifest"]["path"]
    base_dir, work = _base_directories(root)
    ctx = RenderCtx(plan, manifest, str(base_dir), str(work), skip_graphics=True,
        producer_dir=str(base_dir), plan_path=refs["candidatePlan"]["path"], audio_clock_policy=SOURCE_FLOAT_POLICY_V2,
        presenter_base=presenter_base)
    ctx.source_color_base = source_color_base
    report = render(ctx)
    if source_color_base is not None:
        SourceColorBaseContext.assert_current(source_color_base)
    if digest(plan) != digest(inputs.documents["candidatePlan"]) or ctx.source_audio_bus is None:
        raise RuntimeError("ordinary opening base changed reviewed intent or omitted its actual source bus")
    bus, base = ctx.source_audio_bus, base_dir / "final.mp4"
    if Fraction(bus.frame_rate) != Fraction(authority["frameRate"]) or bus.frames != authority["totalFrames"]:
        raise RuntimeError("ordinary opening base differs from accepted exact frame clock")
    canvas = authority["target"]["width"], authority["target"]["height"]
    picture = observe_picture(base, (authority["frameRate"], bus.frames, canvas), bus.admission.tools)
    base_ms = round((time.monotonic() - started) * 1000)
    return _finish((inputs, ctx, report, picture), (base_dir, base), (guard, dependencies), (started, base_ms))


def _finish(context: tuple, paths: tuple, captions_context: tuple, timings: tuple) -> OpeningPreparation:
    """Retain existing master/caption/geometry output records without new color claims."""
    inputs, ctx, report, picture = context
    base_dir, base = paths
    guard, dependencies = captions_context
    started, base_ms = timings
    plan, bus = ctx.plan, ctx.source_audio_bus
    refs = inputs.value["documents"]
    captioned = caption_profile(inputs.value.get("profile"))
    master = build_program_master(bus, plan)
    context = SelectionContext(Path(refs["candidatePlan"]["path"]), Path(refs["manifest"]["path"]),
        base_dir, base, Path(master.directory) / "selection-event.json")
    selection = capture_master_selection(master, plan, context)
    captions, caption_ref = capture_prepared_captions(ctx, inputs, dependencies, guard) if captioned else (None, None)
    master_ms = round((time.monotonic() - started) * 1000) - base_ms
    geometry_started = time.monotonic()
    geometry = capture_short_geometry(inputs, base_dir, selection, picture)
    receipt_paths = {"sourceBus": Path(bus.directory) / "bus-receipt.json",
        "programMaster": Path(master.directory) / "master-receipt.json", "masterSelection": context.event_path,
        "cutManifestation": base_dir / MANIFESTATION_NAME, "timelineMap": base_dir / "timeline_map.json"}
    return OpeningPreparation(base, selection, {"base": picture, "fullBaseElapsedMs": base_ms,
        **({"captionProjection": caption_ref} if caption_ref is not None else {}),
        **({"shortGeometry": geometry, "shortGeometryElapsedMs": round((time.monotonic() - geometry_started) * 1000)} if geometry is not None else {}),
        "fullProgramMasterElapsedMs": master_ms if geometry is not None else round((time.monotonic() - started) * 1000) - base_ms,
        "baseReport": report, "fullBasePrepared": True, "bodyGraphicsPrepared": False,
        "baseAudibleTrackNotSelected": True, "legacyPictureTransportAacStillExecuted": True,
        "receipts": {name: {"path": str(path), "sha256": file_hash(path)} for name, path in receipt_paths.items()},
        "fullMasterSelectionEventPath": str(context.event_path), "fullMasterSelectionEventSha256": selection.event_sha256}, captions)
