"""Real multi-source preflight/project/sealing with TEST-only decoder/admission leaves.

All files are owned inert fixture inputs. The borrowed worker writes synthetic
records, and the reader uses the actual typed frame validator. No source media,
daemon, color-resource lease, transform, playback or approval is exercised.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from _grade_project_owned_fixture import OwnedGradeFixture
from _source_color_batch_fixture import SourceColorBatchFixture
from color import grade_project as project
from color import grade_project_authority as authority
from color.grade_observation_read import BoundGradeObservation
from guided_source_color_execution import CompletedSourceColorBatch, run_source_color_batch
from headless.grade_observation_phase import OwnedGradePhase


class SourceColorExecutionFixture(SourceColorBatchFixture):
    """Keep actual all-source preflight and existing observation/project publication."""

    def __init__(self, pins: list[dict]) -> None:
        """Install only synthetic admission/worker/reader seams after real TEST staging."""
        super().__init__(pins)
        self.calls, self.returned_by_source = [], {}
        self.value, self.execution, self.returned = None, None, None
        self.work_seconds = 1.0
        self.batch = self.prepare()
        self.stack.enter_context(patch.object(authority, "execution_media_authority_entries", return_value=self.entries))
        self.worker = self.stack.enter_context(patch.object(project, "run_owned_isolated_grade", side_effect=self.native_stub))
        self.stack.enter_context(patch.object(project, "read_observation", side_effect=self.read_stub))

    def native_stub(self, source: str, request: dict, directory: Path, phase: OwnedGradePhase) -> dict:
        """Record the real dispatch and substitute only native observation at its leaf."""
        phase.check()
        job = next(row for row in self.batch.jobs if row.source.path == source)
        if phase.owner is not job.launch or directory != job.directory / "execution":
            raise AssertionError("TEST native dispatch lost its actual job/launch owner")
        self.value = job.value
        self.calls.append((source, request, directory, phase))
        self.now += self.work_seconds
        return OwnedGradeFixture.run_stub(self, source, request, directory, phase.deadline)

    def read_stub(self, directory: Path, parents: tuple[dict, dict], execution: dict) -> BoundGradeObservation:
        """Reuse actual typed validation of synthetic TEST frame records, not decoded footage."""
        result = OwnedGradeFixture.read_stub(self, directory, parents, execution)
        self.returned_by_source[parents[0]["sourceId"]] = result
        return result

    def execute(self) -> CompletedSourceColorBatch:
        """Run the real sequential owner; native data remains explicitly synthetic."""
        return run_source_color_batch(self.batch)
