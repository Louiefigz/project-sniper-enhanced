#!/usr/bin/env python3
"""studio_project — generate a HyperFrames Studio review project from a plan.

CLI::

    studio_project.py <edit_plan.json> <base_video> <out_dir> [--force]
                      [--copy-base]

Turns ``edit_plan.json`` + the graphics-free base video into a project
directory that ``hyperframes preview`` opens as a review timeline: the base
footage on track 0, every graphicsTrack entry as a timed sub-composition clip
above it. The exit-on-cut clamp (``graphics/exit_on_cut.py``) is applied
first, so the view shows the same timing the renderers composite. The
directory is a VIEW — never ``hyperframes render`` it; deliverables still go
through ``graphics_render.py`` + ``assemble.py``.

Refuses to overwrite a studio directory whose files differ from its
generation manifest (unsynced Studio edits) unless ``--force``.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # run-by-path: producer pkg root on sys.path

from graphics.exit_on_cut import apply_exit_on_cut
from graphics.graphics_render import comp_path
from graphics.template_contract import (
    composition_dimensions,
    resolved_assets,
    validate_entry,
)
from ingest_probe import probe_media
from studio import StudioProjectError
from studio.comp_transform import (
    InstancePlan,
    SourceComp,
    build_instance,
    parse_source_comp,
)
from studio.lane_layout import assign_lanes
from studio.comp_hf_ids import normalize_instances
from studio.comp_dependencies import STYLE_SCOPE
from studio.project_assets import stage_base_video, stage_icons, \
    stage_shared_assets
from studio.project_writer import (
    ReviewBase,
    ReviewClip,
    build_index_html,
    build_storyboard,
    hyperframes_json_text,
    readback_window,
)
from studio.view_manifest import (
    FINGERPRINT_NAME,
    GENERATOR_VERSION,
    MANIFEST_NAME,
    build_fingerprint,
    file_sha256,
    generation_fields,
    stale_generated_files,
    unsynced_changes,
    write_json,
)

_WINDOW_TOLERANCE_S = 0.05


@dataclasses.dataclass(frozen=True)
class GenerateRequest:
    """One studio-project generation job."""

    plan_path: str
    base_video: str
    out_dir: str
    force: bool = False


@dataclasses.dataclass(frozen=True)
class _Built:
    """Everything derived from the plan before any file is written."""

    clips: list[ReviewClip]
    instances: dict[str, str]
    icon_rows: list[dict]
    effective_track: list[dict]
    clamped: int
    need_split_text: bool
    style_scope: str | None = None


def _probe_base(base_video: str) -> ReviewBase:
    """Read the base footage's display geometry and duration via ffprobe."""
    probe = probe_media(base_video)
    if not probe.duration or not probe.width or not probe.height:
        raise StudioProjectError(
            f"base video is not probeable footage: {base_video}")
    width, height = probe.width, probe.height
    if probe.rotation in (90, 270):
        width, height = height, width
    return ReviewBase(width=width, height=height, duration=probe.duration,
                      fps=probe.fps, src_rel="", has_audio=probe.audio_present)


def _check_window(tag: str, entry: dict, base_duration: float) -> None:
    start, end = float(entry["outStart"]), float(entry["outEnd"])
    if not (0 <= start < end <= base_duration + _WINDOW_TOLERANCE_S):
        raise StudioProjectError(
            f"{tag}: window [{start}, {end}] outside the base video's "
            f"{base_duration:.2f}s")


def _clip_for(entry: dict, ids: tuple[str, str], authored_end: float,
              source_dims: tuple[int, int]) -> ReviewClip:
    slot_id, instance_id = ids
    return ReviewClip(
        slot_id=slot_id, instance_id=instance_id, kind=str(entry["kind"]),
        file_rel=f"compositions/{instance_id}.html",
        spec=entry.get("spec") or {},
        out_start=float(entry["outStart"]), out_end=float(entry["outEnd"]),
        authored_out_end=authored_end, track=0, z_index=0,
        width=source_dims[0], height=source_dims[1],
        anchor=str(entry.get("anchor", "free-band")),
        reason=str(entry.get("reason", "")),
        plan_id=entry.get("id"), non_panel_keys=())


def _entry_clip(index: int, entry: dict, authored_end: float,
                source: tuple[SourceComp, str]) -> tuple[ReviewClip, str]:
    """One entry's review clip plus its built instance file."""
    comp, comp_html = source
    instance_id = f"gfx-{index + 1:02d}-{comp.kind}"
    duration = round(float(entry["outEnd"]) - float(entry["outStart"]), 4)
    built = build_instance(comp, InstancePlan(
        instance_id=instance_id, spec=entry.get("spec") or {},
        duration=duration))
    clip = _clip_for(entry, (f"gfx-{index + 1:02d}", instance_id),
                     authored_end, composition_dimensions(comp_html))
    return dataclasses.replace(
        clip, non_panel_keys=built.non_panel_keys), built.html


def _build_entries(plan: dict, base_duration: float, scope_styles: bool = False) -> _Built:
    """Validate + transform every graphicsTrack entry into review clips."""
    effective, clamped = apply_exit_on_cut(plan)
    authored = plan.get("graphicsTrack") or []
    sources: dict[str, tuple[SourceComp, str]] = {}
    clips, instances, icon_rows = [], {}, []
    for i, entry in enumerate(effective):
        kind = str(entry.get("kind", ""))
        if not kind or ".." in kind or "/" in kind or "\\" in kind:
            raise StudioProjectError(
                f"graphicsTrack[{i}]: kind {kind!r} is not a plain "
                "composition name")
        if kind not in sources:
            try:
                path = comp_path(kind)
            except ValueError as exc:
                raise StudioProjectError(
                    f"graphicsTrack[{i}]: {exc}") from exc
            with open(path, encoding="utf-8") as handle:
                comp_html = handle.read()
            sources[kind] = (parse_source_comp(kind, comp_html, scope_styles, scope_styles), comp_html)
        _check_window(f"graphicsTrack[{i}]", entry, base_duration)
        validate_entry(entry, sources[kind][1])
        icon_rows.extend(resolved_assets(entry, sources[kind][1]))
        clip, html = _entry_clip(i, entry, float(authored[i]["outEnd"]),
                                 sources[kind])
        instances[clip.file_rel] = html
        clips.append(clip)
    lanes = assign_lanes([(c.out_start, c.out_end) for c in clips])
    clips = [dataclasses.replace(c, track=lane.track, z_index=lane.z_index)
             for c, lane in zip(clips, lanes)]
    return _Built(clips, instances, icon_rows, effective, clamped,
                  any(comp.uses_split_text for comp, _ in sources.values()),
                  STYLE_SCOPE if scope_styles else None)


def _manifest_entries(built: _Built) -> list[dict]:
    entries = []
    for c in built.clips:
        # Timing baselines are the view's read-back projection, not the raw
        # plan floats — sync_diff compares against what the slot attrs yield.
        out_start, out_end = readback_window(c.out_start, c.out_end)
        entries.append(
            {**({'styleScope': built.style_scope, 'durationBinding': 'mounted-host-v1'}
                if built.style_scope else {}),
             "slot": c.slot_id, "instanceId": c.instance_id, "kind": c.kind,
             "file": c.file_rel, "track": c.track, "zIndex": c.z_index,
             "outStart": out_start, "outEnd": out_end,
             "authoredOutEnd": c.authored_out_end,
             "exitClamped": c.out_end != c.authored_out_end,
             "anchor": c.anchor, "planId": c.plan_id,
             "nonPanelKeys": list(c.non_panel_keys)})
    return entries


def _write_project(request: GenerateRequest, built: _Built,
                   base: ReviewBase) -> dict:
    """Write every project file, then seal fingerprint + manifest."""
    out_dir = os.path.abspath(request.out_dir)
    os.makedirs(os.path.join(out_dir, "compositions"), exist_ok=True)
    base_stage = stage_base_video(out_dir, request.base_video)
    base = dataclasses.replace(base, src_rel=base_stage.rel_path)
    title = f"{os.path.basename(out_dir)} review"
    text_files = dict(built.instances)
    text_files["index.html"] = build_index_html(
        base, built.clips, title, built.need_split_text)
    text_files["hyperframes.json"] = hyperframes_json_text()
    text_files["STORYBOARD.md"] = build_storyboard(base, built.clips, title)
    files: dict[str, str] = {}
    for rel, text in text_files.items():
        path = os.path.join(out_dir, rel)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        files[rel] = file_sha256(path)
    for rel in stage_shared_assets(out_dir) + stage_icons(out_dir,
                                                          built.icon_rows):
        files[rel] = file_sha256(os.path.join(out_dir, rel))
    write_json(os.path.join(out_dir, FINGERPRINT_NAME),
               build_fingerprint(built.effective_track, request.base_video, GENERATOR_VERSION))
    files[FINGERPRINT_NAME] = file_sha256(
        os.path.join(out_dir, FINGERPRINT_NAME))
    for rel in stale_generated_files(out_dir, set(files)):
        os.remove(os.path.join(out_dir, rel))
    media = {"rel": base_stage.rel_path,
             "target": os.path.abspath(request.base_video),
             "bytes": base_stage.bytes}
    write_json(os.path.join(out_dir, MANIFEST_NAME),
               {**generation_fields(GENERATOR_VERSION), "files": files,
                "media": media, "entries": _manifest_entries(built),
                "exitClampedCount": built.clamped})
    return {"status": "generated", "dir": out_dir,
            "entries": len(built.clips), "exitClamped": built.clamped,
            "tracks": max((c.track for c in built.clips), default=0)}


def generate_project(request: GenerateRequest) -> dict:
    """Generate (or safely regenerate) one studio review project."""
    changes = unsynced_changes(os.path.abspath(request.out_dir))
    if changes and not request.force:
        raise StudioProjectError(
            "studio dir has unsynced edits (rerun with --force to discard): "
            + "; ".join(changes))
    with open(request.plan_path, encoding="utf-8") as handle:
        plan = json.load(handle)
    base = _probe_base(request.base_video)
    built = _build_entries(plan, base.duration, scope_styles=True)
    if built.instances:
        built = dataclasses.replace(built, instances=normalize_instances(built.instances))
    return _write_project(request, built, base)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", help="edit_plan.json path")
    parser.add_argument("base_video", help="graphics-free base video")
    parser.add_argument("out_dir", help="studio project directory to write")
    parser.add_argument("--force", action="store_true",
                        help="overwrite even when the dir has unsynced edits")
    args = parser.parse_args(argv)
    try:
        result = generate_project(GenerateRequest(
            args.plan, args.base_video, args.out_dir, force=args.force))
    except StudioProjectError as exc:
        print(json.dumps({"status": "refused", "error": str(exc)}))
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
