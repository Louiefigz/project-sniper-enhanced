"""Actual original source/master and cheap live ownership for one body invocation.

This internal context never prepares a replacement base/master. Its owner must
separately authenticate activation, journal, approval and process cleanup.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from audio.program_master_selection import HeldMasterSelection, revalidate_master_selection
from cut_preview_io import digest, file_hash
from guided_body_admission import admit_body_workload
from guided_body_execution import BodyExecutionClock, BodyHeldFile, assert_body_files, hold_body_file, revalidate_body_files
from guided_body_inputs import BodyControl
from guided_body_pipeline import hold_body_dependencies, observe_body_pipeline
from guided_graphic_template import inspect_full_program_graphics
from guided_opening_claim import read_execution_claim
from guided_opening_frames import full_program_frames
from guided_opening_inputs import OpeningInputs, observe_inputs, read_current_inputs
from headless.external_media_verification import SourceVerificationRuntime
from guided_short_geometry import verify_short_geometry, short_geometry_refs
from guided_opening_read import _full_program, _identity
from guided_opening_result import check_held_artifacts
from guided_caption_projection import HeldCaptionProjection
from guided_caption_integration import read_prepared_captions, caption_held_files, assert_opening_caption_layers
from guided_body_source_color_entry import (BodyInputRead, capture_body_source_color_entry,
    finish_body_source_color_inputs, capture_body_control_origin, assert_body_control_origin)
from guided_body_source_color_work import (body_source_color_required, source_color_body_scope,
    register_body_source_color_work, assert_body_source_color_work, append_body_source_color_files,
    retain_body_source_color_preparation, replay_body_source_color, body_source_color_readback, register_body_work_origin)


@dataclass(eq=False)
class BodyWork:
    """Source-authenticated work context; repeated guards use held file identities."""

    control: BodyControl
    inputs: OpeningInputs
    clock: BodyExecutionClock
    pipeline: dict
    files: tuple[BodyHeldFile, ...]
    selection: HeldMasterSelection | None = None
    audio: dict | None = None
    workload: dict | None = None
    templates: dict | None = None
    captions: HeldCaptionProjection | None = None

    def __post_init__(self) -> None:
        """Retain actual constructor identity and original raw body input before callbacks."""
        register_body_work_origin(self)

    def guard(self) -> None:
        """Reject control/source-code mutation or lost original time before publication."""
        assert_body_source_color_work(self)
        assert_body_files(self.files, self.clock)
        assert_body_source_color_work(self)

    def revalidate(self) -> None:
        """Fresh full source/master proof stays separate from cheap repeated guards."""
        self.guard()
        assert_body_source_color_work(self, True)
        observe_inputs(self.inputs)
        original = self.control.documents["openingResult"]
        if digest(observe_body_pipeline(self.inputs, original)) != digest(self.pipeline):
            raise RuntimeError("body source/tool closure changed during execution")
        if self.selection is None or self.audio is None:
            raise RuntimeError("body has no actual held whole-program preparation")
        revalidate_master_selection(self.selection)
        root = Path(self.control.documents["heldInput"]["opening"]["outputRoot"])
        check_held_artifacts(original, self.audio, root)
        verify_short_geometry(original["fullProgram"], self.inputs, root / "full-program-base", self.selection)
        captions = read_prepared_captions(original["fullProgram"], self.inputs, root / "full-program-base", self.guard)
        if captions != self.captions:
            raise RuntimeError("body original held caption projection changed")
        revalidate_body_files(self.files, self.clock)
        assert_body_source_color_work(self, True)


def read_original_inputs(control: BodyControl, clock: BodyExecutionClock | None = None) -> OpeningInputs:
    """Read the original14 documents and source admission without resealing them."""
    ref = control.value["references"]["openingInput"]
    if clock is None:
        return read_current_inputs(Path(ref["path"]), ref["sha256"])
    return read_current_inputs(Path(ref["path"]), ref["sha256"], SourceVerificationRuntime(clock.remaining))


def read_body_inputs(control: BodyControl, clock: BodyExecutionClock) -> BodyInputRead:
    """Capture source2 original controls BEFORE the unchanged initial source read."""
    origin = capture_body_control_origin(control, clock)
    if not body_source_color_required(control):
        inputs = read_original_inputs(control, clock)
        assert_body_control_origin(origin, control, clock)
        return BodyInputRead(inputs, None)
    seed = capture_body_source_color_entry(control, clock, origin)
    inputs = read_original_inputs(control, clock)
    return finish_body_source_color_inputs(seed, inputs)


def prepare_body_work(control: BodyControl, inputs: OpeningInputs, clock: BodyExecutionClock, source_entry: object = None) -> BodyWork:
    """Bind current code and original claim; no graphic seal or decoder is launched."""
    if body_source_color_required(control, source_entry):
        return _prepare_source_color_work(control, inputs, clock, source_entry)
    old = control.documents["heldInput"]["opening"]
    claim = read_execution_claim((inputs.path, Path(old["outputRoot"])),
        (inputs.sha256, Path(old["claimPath"]), old["claimSha256"]))
    _identity(control.documents["openingResult"], inputs, claim)
    pipeline = observe_body_pipeline(inputs, control.documents["openingResult"])
    files = (*control.held_files, *hold_body_dependencies(inputs, pipeline),
             hold_body_file(Path(old["claimPath"]), old["claimSha256"]))
    work = BodyWork(control, inputs, clock, pipeline, files)
    work.guard()
    return work


def _prepare_source_color_work(control: BodyControl, inputs: OpeningInputs, clock: BodyExecutionClock, seed: object) -> BodyWork:
    """Use original claim metadata and exact private seed; never admit the old runtime."""
    scope = source_color_body_scope(control, inputs, clock, seed)
    pipeline = observe_body_pipeline(inputs, control.documents["openingResult"])
    work = BodyWork(control, inputs, clock, pipeline, control.held_files)
    register_body_source_color_work(work, seed, scope)
    append_body_source_color_files(work, hold_body_dependencies(inputs, pipeline))
    work.guard()
    return work


def admit_body_templates(work: BodyWork) -> list[dict]:
    """Prove all rows fit the existing profile/workload/template rules before render."""
    work.workload = admit_body_workload(work.inputs, work.control.documents["openingResult"])
    rows = full_program_frames(work.inputs)
    if work.control.value["selectedGraphicOrders"] != [row["order"] for row in rows]:
        raise RuntimeError("body activation omitted or added a complete candidate row")
    work.templates = inspect_full_program_graphics(work.inputs, work.guard)
    refs = {row["templatePath"]: row["templateSha256"] for row in work.templates["graphics"]}
    append_body_source_color_files(work, tuple(hold_body_file(Path(path), sha) for path, sha in refs.items()))
    work.guard()
    return rows


def read_body_preparation(work: BodyWork) -> None:
    """Only the original actual invocation-held whole base/master may be reused."""
    assert_body_source_color_work(work, True)
    original = work.control.documents["heldInput"]["opening"]
    if file_hash(Path(original["resultPath"])) != original["resultSha256"]:
        raise RuntimeError("body original opening result changed before master selection")
    work.selection, work.audio = _full_program(work.control.documents["openingResult"],
        work.inputs, Path(original["outputRoot"]))
    retain_body_source_color_preparation(work)
    refs = short_geometry_refs(work.control.documents["openingResult"]["fullProgram"], Path(original["outputRoot"]) / "full-program-base")
    append_body_source_color_files(work, tuple(hold_body_file(Path(row["path"]), row["sha256"], 2 * 1024 ** 3) for row in refs))
    full = work.control.documents["openingResult"]["fullProgram"]
    work.captions = read_prepared_captions(full, work.inputs, Path(original["outputRoot"]) / "full-program-base", work.guard)
    assert_opening_caption_layers(work.control.documents["openingResult"], work.inputs, work.captions)
    if work.captions is not None:
        append_body_source_color_files(work, tuple(hold_body_file(Path(row.path), row.sha256, 2 * 1024 ** 3) for row in caption_held_files(work.captions)))
        ref = full["captionProjection"]
        append_body_source_color_files(work, (hold_body_file(Path(ref["path"]), ref["sha256"]),))
    work.guard()
