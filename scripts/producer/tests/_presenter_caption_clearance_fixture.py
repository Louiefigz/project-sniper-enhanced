"""Actual held TEST metadata with stubbed decoding; never renderer/admission proof."""
from __future__ import annotations

import subprocess
import tempfile
from dataclasses import asdict, replace
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

import _guided_caption_fixture as captions
from _guided_presenter_observation_fixture import ObservationFixture
from cut_preview_io import digest
from graphics.presenter_layout_contract import PresenterCanvas, declaration_payload
from graphics.presenter_layout_geometry import compile_presenter_geometry
from guided_caption_projection import capture_caption_projection
from guided_opening_inputs import OpeningInputs
from guided_presenter_caption_clearance import PresenterCaptionClearanceContext
from guided_presenter_execution import OwnedPresenterExecution
from guided_presenter_observation import observe_presenter_asset
from guided_presenter_probe_identity import presenter_stat_identity
from test_presenter_layout_graph import declaration


class ClearanceFixture:
    """Reuse original projection contracts without invoking a native child."""

    def __init__(self, frame_rate: str = "30") -> None:
        """Capture real file bindings and actual observer control flow over TEST JSON."""
        self.probe = ObservationFixture(image=True)
        self.directory = tempfile.TemporaryDirectory(prefix="sniper-presenter-caption-TEST-", dir="/private/tmp")
        self.root = Path(self.directory.name)
        self.frame_rate = frame_rate
        self.runtime = replace(self.probe.runtime, guard=self.guard)
        results = [subprocess.CompletedProcess([], 0, raw, "") for raw in self.probe.raw()]
        with patch("guided_presenter_observation.run_text", side_effect=results):
            self.observed = observe_presenter_asset(self.probe.selected, self.probe.source, frame_rate, self.runtime)
        self.selected = self.window((0, 120))
        self.owner = self.make_owner((self.selected,))
        render, binding = self.caption_fixture()
        self.held = capture_caption_projection(render, binding, self.guard)
        authority = {"frameRate": frame_rate, "totalFrames": 960, "target": {"width": 1080, "height": 1920},
            "candidatePlanHash": digest(render.plan), "review": {"startFrame": 0, "endFrameExclusive": 120}}
        self.inputs = OpeningInputs(self.root / "TEST-input.json", "c" * 64,
            {"executionInputHash": binding.execution_input_hash, "documents": {
                "candidatePlan": asdict(binding.plan), "manifest": asdict(binding.manifest)}},
            {"authority": authority, "candidatePlan": render.plan})
        self.context = PresenterCaptionClearanceContext(self.inputs, self.held, self.owner, authority["review"].copy())

    def caption_fixture(self) -> tuple:
        """Build honest TEST rational pages before capture, never relabel held assets."""
        self.original_plan = captions.legacy_plan
        rate = Fraction(self.frame_rate)
        actual_rate = captions.CaptionFrameRate(rate.numerator, rate.denominator)
        planner = captions.plan_caption_pages
        maximum = int(rate * 30)
        with patch.object(captions, "legacy_plan", side_effect=self.plan), \
                patch.object(captions, "CaptionFrameRate", return_value=actual_rate), \
                patch.object(captions, "plan_caption_pages", side_effect=lambda rows, total, _bound: planner(rows, total, maximum)):
            render, binding = captions.fixture(self.root)
        projection = render.caption_projection
        fields = {key: value for key, value in projection.pages.manifest.items() if key != "authorityHash"}
        manifest = captions.sealed("sniper-caption-alpha-page-manifest-v1", {**fields, "maxPageFrames": maximum})
        captions.write(Path(render.out_dir) / "caption_pages.json", manifest)
        render.caption_projection = replace(projection, pages=captions.CaptionPageSet(manifest, 0, 0))
        return render, replace(binding, frame_clock=(self.frame_rate, 960, 1080, 1920))

    def guard(self) -> None:
        """Check original TEST source/tool identity without another media hash/decode."""
        self.probe.deadline.remaining()
        for row in (self.probe.source, self.probe.runtime.ffprobe):
            if presenter_stat_identity(Path(row.path).lstat()) != row.stat_identity:
                raise RuntimeError("TEST held source/tool changed")

    def window(self, span: tuple[int, int], index: int = 7) -> object:
        """A valid manually authored portrait envelope over a small TEST still."""
        payload = declaration()
        payload.update(enterFrames=15, exitFrames=15, mask={"kind": "rounded-rect", "radiusPx": 24})
        geometry = compile_presenter_geometry(payload, PresenterCanvas(1080, 1920, 960, "yuv420p"), span)
        return replace(self.probe.selected, geometry=geometry, operation_index=index)

    def make_owner(self, selected: tuple) -> OwnedPresenterExecution:
        """Use the live execution object, never deserialize an execution success."""
        return OwnedPresenterExecution(selected, (self.observed,), self.frame_rate, self.runtime)

    def plan(self) -> dict:
        """Include the presenter declaration BEFORE caption compilation and holding."""
        plan = self.original_plan()
        row = self.selected
        plan["presenterLayouts"] = [{"operationIndex": row.operation_index,
            "startFrame": row.geometry.timing.start_frame, "endFrameExclusive": row.geometry.timing.end_frame_exclusive,
            "layout": declaration_payload(row.geometry)}]
        return plan

    def cue(self, span: tuple[int, int], box: tuple[int, int, int, int]) -> dict:
        """A plainly synthetic whole-cue box for pure intersection fault tests."""
        return {"cueId": "TEST-cue", "startFrame": span[0], "endFrameExclusive": span[1],
            "media": {"path": "/TEST/never-rendered.mov", "sha256": "a" * 64}, "box": box}

    def close(self) -> None:
        """Remove only this test's disposable temporary files."""
        self.directory.cleanup()
        self.probe.close()
