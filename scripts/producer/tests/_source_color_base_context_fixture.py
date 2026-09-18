"""Actual source-only holders over owned TEST bytes and explicit native stubs.

No presentation owner is constructed. Source admission/decoder leaves retain
the existing fixture's TEST boundaries; all batch/read/identity objects are
the actual production returns. No real media may run through this fixture.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from _grade_bt709_identity_fixture import Bt709IdentityFixture
from _grade_project_owned_fixture import OwnedGradeFixture
from _source_color_opening_fixture import SourceColorOpeningFixture
from guided_source_color_base import hold_bt709_base_identity
from guided_source_color_base_context import SourceColorBaseContext
from render import RenderCtx


class SourceOnlyBaseFixture(SourceColorOpeningFixture):
    """Two actual held TEST sources, original opening clock, and no presenter."""

    def __init__(self, pins: list[dict], change: dict | None = None) -> None:
        """Set plan changes before every original batch/file lifetime starts."""
        self.plan_changes = change or {}
        super().__init__(pins)
        self.metadata_mutator = self._dimensions
        self.stack.enter_context(patch.object(OwnedGradeFixture, "run_stub", Bt709IdentityFixture.run_stub))

    def _opening(self) -> Path:
        """Declare TEST longform metadata before any source-only holder exists."""
        path = super()._opening()
        plan = self.inputs.documents["candidatePlan"]
        plan.update(target={"mode": "longform", "width": 1920, "height": 1080},
                    captions={"burn": False}, reframe={"strategy": "none"})
        plan.update(self.plan_changes)
        self.inputs.documents["authority"].update(frameRate="30000/1001", totalFrames=24,
                                                   target={"width": 1920, "height": 1080})
        return path

    @staticmethod
    def _dimensions(probe: dict, rows: list[dict]) -> None:
        """Keep supplied TEST frame metadata aligned with its admitted32x18 entry."""
        probe["streams"][0].update(width=32, height=18)
        for row in rows:
            row.update(width=32, height=18)

    def read_stub(self, directory: Path, parents: tuple[dict, dict], execution: dict) -> object:
        """Use actual record validation with only native provenance leaves stubbed."""
        result = Bt709IdentityFixture.read_stub(self, directory, parents, execution)
        self.returned_by_source[parents[0]["sourceId"]] = result
        return result

    def identity(self) -> object:
        """Return the genuine all-source batch-derived supplemental identity holder."""
        return hold_bt709_base_identity(self.execute())

    def base_context(self, identity: object) -> SourceColorBaseContext:
        """Carry original input/clock/guard objects, never reconstructed authority."""
        return SourceColorBaseContext(self.inputs, self.clock, identity, self.guard)

    def render_context(self, context: SourceColorBaseContext) -> RenderCtx:
        """Build only original command metadata; native paths remain uncreated."""
        refs = self.inputs.value["documents"]
        manifest = deepcopy(self.inputs.documents["manifest"])
        manifest["_path"] = refs["manifest"]["path"]
        return RenderCtx(deepcopy(self.inputs.documents["candidatePlan"]), manifest,
            str(self.root / "TEST-unstarted-base"), str(self.root / "TEST-unstarted-work"),
            skip_graphics=True, plan_path=refs["candidatePlan"]["path"],
            audio_clock_policy="source-float-v2", source_color_base=context)
