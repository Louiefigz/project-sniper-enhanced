"""Actual shared caption assembly with explicitly TEST-only asset callbacks.

No OCI/template renderer, original job authentication or human approval is
claimed. All ordinary caption generation, composition, audio and QC are real.
"""
from __future__ import annotations

import contextlib
import copy
from pathlib import Path
from unittest.mock import patch

from assemble import AssembleJob, assemble
from audio.assemble_publication import copy_verified
from cut_preview_io import file_hash
from graphics.owned_execution import GraphicsComposition, OwnedGraphicsExecution
from guided_caption_execution import OwnedCaptionExecution
from guided_caption_layers import caption_prefix_request
from guided_opening_inputs import OpeningInputs
from guided_opening_prepare import OpeningPreparation
from opening_prefix_composition import PrefixCompositionJob, compose_verified_prefix
from opening_prefix_contract import (CompositorPrefixRequest, PrefixClock, PrefixDeadline,
                                     PrefixOracleRuntime, PrefixRanges)
from test_opening_prefix_contract import held


class CaptionBodyFixture:
    """One test-only invocation, preserving the ordinary held-program contract."""

    def __init__(self, root: Path, prepared: OpeningPreparation,
                 context: tuple[OpeningInputs, Path, dict, PrefixDeadline]) -> None:
        self.root, self.prepared = root, prepared
        self.inputs, self.asset, self.original_clip, self.clock = context
        self.owner = OwnedCaptionExecution(prepared.captions, self.clock.remaining)
        self.composition = None
        self.root.mkdir(mode=0o700)
        self.prefix = self.root / "prefix-work"
        self.prefix.mkdir(mode=0o700)

    def render(self, entry: dict, order: int) -> dict:
        """One pre-generated flat asset, not a production template claim."""
        if order != 0 or entry["id"] != "TEST-card":
            raise AssertionError("TEST graphic callback changed")
        return {"path": str(self.asset), "kind": entry["kind"], "key": "TEST-only",
                "fmt": "mp4", "cached": False}

    def compose(self, value: GraphicsComposition) -> dict:
        """Actual shared prefix comparison and full encode, then retained copy."""
        request = CompositorPrefixRequest(held(Path(value.video_in)), (held(self.asset),),
            value.clips, (self.original_clip,), PrefixClock(*value.frame_clock, *value.canvas),
            PrefixRanges((0, 8), (0, 15)))
        request = caption_prefix_request(request, self.prepared.captions)
        tools = self.prepared.selection.master.source_bus.admission.tools
        runtime = PrefixOracleRuntime(held(Path(tools["ffmpeg"]["path"])),
            held(Path(tools["ffprobe"]["path"])), str(self.prefix), self.clock.remaining())
        proof = compose_verified_prefix(PrefixCompositionJob(request, runtime, value.video_out, self.clock.remaining))
        path = self.root / "picture-only.mp4"
        copy_verified(Path(value.video_out), path, proof["output"]["sha256"])
        retained = {"path": str(path), "sha256": file_hash(path), "sizeBytes": path.stat().st_size}
        self.owner.complete(value.video_out, proof)
        self.composition = {**proof, "retainedPicture": retained}
        return self.composition

    def execute(self) -> tuple[AssembleJob, dict]:
        """Real source-float body assembly; rebuilding either preparation fails."""
        output = self.root / "body-candidate"
        output.mkdir(mode=0o700)
        selection = self.prepared.selection
        context, bus = selection.context, selection.master.source_bus
        job = AssembleJob(str(context.base_path), copy.deepcopy(self.inputs.documents["candidatePlan"]),
            str(output / "final.mp4"), None,
            fingerprint_path=str(context.artifact_root / "base.fingerprint.json"),
            manifest=str(context.manifest_path), audio_clock_policy="source-float-v2",
            plan_path=str(context.plan_path), held_program_selection=(str(context.event_path), selection.event_sha256),
            graphic_frame_clock=(bus.frame_rate, bus.frames),
            owned_graphics=OwnedGraphicsExecution(self.render, self.compose, self.clock.remaining, self.owner))
        with patch("audio.assemble_source_audio.build_program_master", side_effect=AssertionError("no remaster")), \
                patch("render.render", side_effect=AssertionError("no new base or caption compilation")), \
                (self.root / "ordinary-body.log").open("w") as log, contextlib.redirect_stdout(log):
            result = assemble(job)
        return job, result
