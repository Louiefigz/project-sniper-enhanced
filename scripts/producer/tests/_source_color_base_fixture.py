"""Actual all-source handoff/identity reads with explicitly fake media authority.

Source and selected-presentation observations use supplied TEST probe records;
no decoder, admission, V8 intake/14-document qualification or base pixels are
claimed. Real byte holds, project publication/sealing, metadata replay, original
clock and base-entry guards are exercised. No renderer/native leaf may run.
"""
from __future__ import annotations

import copy
import subprocess
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from _grade_bt709_identity_fixture import Bt709IdentityFixture
from _grade_project_owned_fixture import OwnedGradeFixture
from _guided_presenter_observation_fixture import ObservationFixture
from _source_color_opening_fixture import SourceColorOpeningFixture
from graphics.presenter_layout_contract import declaration_payload
from graphics.presenter_layout_geometry import compile_presenter_geometry
from guided_presenter_base import PresenterBaseContext
from guided_presenter_execution import OwnedPresenterExecution
from guided_presenter_observation import observe_presenter_asset
from guided_source_color_base import hold_bt709_base_identity
from render import RenderCtx


class SourceColorBaseFixture(SourceColorOpeningFixture):
    """Two real TEST source holds and one real typed selected-observation wrapper."""

    def __init__(self, pins: list[dict], baseline: object = "ABSENT") -> None:
        """Prepare original metadata before the source batch takes its initial snapshots."""
        self.presentation = ObservationFixture()
        try:
            self._initialize(pins, baseline)
        except BaseException:
            self.presentation.close()
            raise

    def _initialize(self, pins: list[dict], baseline: object) -> None:
        """Keep constructor failure cleanup scoped to the separate TEST presentation root."""
        self.baseline = baseline
        selected = self.presentation.selected
        payload = declaration_payload(selected.geometry)
        payload["sourceIds"] = ["raw-b", "raw-a"]
        timing = selected.geometry.timing
        geometry = compile_presenter_geometry(payload, selected.geometry.canvas,
                                               (timing.start_frame, timing.end_frame_exclusive))
        self.presentation.selected = replace(selected, geometry=geometry)
        super().__init__(pins)
        self.stack.callback(self.presentation.close)
        self.metadata_mutator = self._dimensions
        self.stack.enter_context(patch.object(OwnedGradeFixture, "run_stub", Bt709IdentityFixture.run_stub))
        runtime = replace(self.presentation.runtime, deadline=self.clock)
        results = [subprocess.CompletedProcess([], 0, raw, "") for raw in self.presentation.raw()]
        with patch("guided_presenter_observation.run_text", side_effect=results):
            observed = observe_presenter_asset(self.presentation.selected, self.presentation.source,
                                                "30000/1001", runtime)
        self.presenter = OwnedPresenterExecution((self.presentation.selected,), (observed,), "30000/1001", runtime)

    def _opening(self) -> Path:
        """Attach TEST presenter metadata before any original preparation hold is captured."""
        path = super()._opening()
        selected = self.presentation.selected
        plan = self.inputs.documents["candidatePlan"]
        plan.update(target={"mode": "longform", "width": 64, "height": 36},
            presenterLayouts=[{"operationIndex": selected.operation_index,
                "startFrame": selected.geometry.timing.start_frame,
                "endFrameExclusive": selected.geometry.timing.end_frame_exclusive,
                "layout": declaration_payload(selected.geometry)}])
        if self.baseline != "ABSENT":
            plan["baselineLook"] = self.baseline
        self.inputs.documents["authority"].update(frameRate="30000/1001", totalFrames=24,
                                                   target={"width": 64, "height": 36})
        return path

    @staticmethod
    def _dimensions(probe: dict, rows: list[dict]) -> None:
        """Match the TEST admitted32x18 source metadata, still without an actual decoder."""
        probe["streams"][0].update(width=32, height=18)
        for row in rows:
            row.update(width=32, height=18)

    def read_stub(self, directory: Path, parents: tuple[dict, dict], execution: dict) -> object:
        """Retain the actual raw-record reader and stub only native provenance checks."""
        result = Bt709IdentityFixture.read_stub(self, directory, parents, execution)
        self.returned_by_source[parents[0]["sourceId"]] = result
        return result

    def identity(self) -> object:
        """Run actual all-source metadata/typed handoff then the new identity reader."""
        return hold_bt709_base_identity(self.execute())

    def render_context(self, identity: object) -> RenderCtx:
        """Build original command inputs only; no output directory or media work exists."""
        refs = self.inputs.value["documents"]
        manifest = {**copy.deepcopy(self.inputs.documents["manifest"]), "_path": refs["manifest"]["path"]}
        base = PresenterBaseContext(self.inputs, self.presenter, identity)
        return RenderCtx(copy.deepcopy(self.inputs.documents["candidatePlan"]), manifest,
            str(self.root / "TEST-unstarted-base"), str(self.root / "TEST-unstarted-work"),
            skip_graphics=True, plan_path=refs["candidatePlan"]["path"], audio_clock_policy="source-float-v2",
            presenter_base=base)
