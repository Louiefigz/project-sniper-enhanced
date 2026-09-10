"""Capture/read the ORIGINAL caption projection under current owner bindings.

Inputs are already authenticated by the opening/body caller. This adapter never
discovers a generation or reads a cache as execution authority. Capturing occurs
only around the actual returned ordinary renderer context; a cold read checks
the same files and cannot issue a live completion.
"""
from __future__ import annotations

from pathlib import Path

from cut_preview_io import digest, write_new
from guided_caption_dependencies import CaptionFile, Guard, hold_caption_file, read_caption_json
from guided_caption_profile import caption_profile
from guided_caption_projection import CaptionProjectionBinding, HeldCaptionProjection, capture_caption_projection
from guided_caption_records import caption_projection_record, read_caption_record
from guided_opening_inputs import OpeningInputs

RECORD_NAME = "guided-caption-projection.json"


def caption_input_dependencies(inputs: OpeningInputs, guard: Guard) -> tuple[CaptionFile, ...]:
    """Hold every transcript the existing compiler reads, plus original pipeline lock."""
    manifest = inputs.value["documents"]["manifest"]
    paths = {Path(inputs.value["pipeline"]["lockPath"])}
    for source in inputs.documents["manifest"]["sources"]:
        raw = source.get("transcriptPath")
        if raw:
            path = Path(raw)
            paths.add(path if path.is_absolute() else Path(manifest["path"]).parent / path)
    return tuple(hold_caption_file(path, guard) for path in sorted(paths))


def _binding(inputs: OpeningInputs, root: Path, dependencies: tuple[CaptionFile, ...],
             guard: Guard) -> CaptionProjectionBinding:
    """Hold exact admitted plan/manifest and actually returned ordinary timeline."""
    refs, authority = inputs.value["documents"], inputs.documents["authority"]
    rows = [hold_caption_file(Path(refs[name]["path"]), guard) for name in ("candidatePlan", "manifest")]
    if any(row.sha256 != refs[name]["sha256"] for name, row in zip(("candidatePlan", "manifest"), rows)):
        raise RuntimeError("caption owner candidate/source bytes changed")
    timeline = hold_caption_file(root / "timeline_map.json", guard)
    clock = authority["frameRate"], authority["totalFrames"], authority["target"]["width"], authority["target"]["height"]
    return CaptionProjectionBinding(*rows, timeline, clock, dependencies, inputs.value["executionInputHash"])


def capture_prepared_captions(ctx: object, inputs: OpeningInputs,
                             dependencies: tuple[CaptionFile, ...], guard: Guard) -> tuple[HeldCaptionProjection, dict]:
    """Persist actual returned original pages, not an execution claim or approval."""
    if not caption_profile(inputs.value.get("profile")):
        raise RuntimeError("old media profile cannot capture a caption completion")
    root = Path(ctx.out_dir)
    held = capture_caption_projection(ctx, _binding(inputs, root, dependencies, guard), guard)
    record = caption_projection_record(held)
    path = root / RECORD_NAME
    guard()
    write_new(path, record)
    guard()
    row = hold_caption_file(path, guard)
    if digest(read_caption_json(row, guard)) != digest(record):
        raise RuntimeError("caption record changed during new-only persistence")
    return held, {"path": row.path, "sha256": row.sha256, "sizeBytes": row.size_bytes, "recordHash": record["recordHash"]}


def read_prepared_captions(full: dict, inputs: OpeningInputs, root: Path,
                           guard: Guard) -> HeldCaptionProjection | None:
    """Original actual-result-held record only; no replacement/recompile/reseal."""
    if not caption_profile(inputs.value.get("profile")):
        if "captionProjection" in full:
            raise RuntimeError("old media profile contains unqualified caption observations")
        return None
    ref = full.get("captionProjection")
    if type(ref) is not dict or set(ref) != {"path", "sha256", "sizeBytes", "recordHash"} \
            or ref["path"] != str(root / RECORD_NAME):
        raise RuntimeError("caption projection is not the original fixed output reference")
    row = CaptionFile(ref["path"], ref["sha256"], ref["sizeBytes"])
    record = read_caption_json(row, guard)
    if record.get("recordHash") != ref["recordHash"]:
        raise RuntimeError("caption projection record differs from held original result")
    dependencies = caption_input_dependencies(inputs, guard)
    return read_caption_record(record, _binding(inputs, root, dependencies, guard), root, guard)


def caption_held_files(held: HeldCaptionProjection) -> tuple[CaptionFile, ...]:
    """Exact cheap-guard inventory; source media authority remains existing owner."""
    binding = held.binding
    rows = (binding.plan, binding.manifest, binding.timeline, *binding.dependencies, *held.files, *held.external)
    unique = {}
    for row in rows:
        if row.path in unique and unique[row.path] != row:
            raise RuntimeError("caption dependency inventories conflict")
        unique[row.path] = row
    return tuple(unique.values())


def assert_opening_caption_layers(record: dict, inputs: OpeningInputs, held: HeldCaptionProjection | None) -> None:
    """Rebind returned combined-picture policy to independently held original pages."""
    if held is None:
        if "captionLayers" in record["pictures"]:
            raise RuntimeError("uncaptioned opening acquired a caption layer proof")
        return
    from guided_body_prefix import _original_clip
    from guided_opening_frames import executable_frames
    from guided_caption_layers import opening_caption_layers
    rows = executable_frames(inputs)
    if len(rows) != len(record["graphics"]):
        raise RuntimeError("captioned opening lost original graphic coverage")
    clips = [_original_clip(row, proof) for row, proof in zip(rows, record["graphics"])]
    _combined, expected = opening_caption_layers(clips, held, inputs.documents["authority"]["review"]["endFrameExclusive"])
    if digest(record["pictures"].get("captionLayers")) != digest(expected):
        raise RuntimeError("opening picture caption graph differs from original held pages")
