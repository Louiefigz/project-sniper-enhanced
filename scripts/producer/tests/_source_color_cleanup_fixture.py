"""Actual metadata/coordinator flow with entirely virtual Docker and timer leaves."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from unittest.mock import Mock, patch

from _grade_batch_cleanup_fixture import GradeBatchCleanupFixture
from _source_color_reservation_fixture import SourceColorReservationFixture
from guided_opening_execution import OpeningExecutionClock
from guided_source_color_cleanup import SourceColorCleanupContext, prepare_opening_source_color_cleanup
from headless.container_policy import DockerRuntime


class SourceColorCleanupFixture:
    """Two explicit TEST roots: partial metadata and an existing private Docker config."""

    def __init__(self) -> None:
        """Reuse actual readers/coordinator; native leaves cannot address any daemon."""
        self.files = SourceColorReservationFixture()
        self.daemon = GradeBatchCleanupFixture()
        runtime = self.files.context.opening.value["runtime"]
        self.daemon.runtime = DockerRuntime(runtime["dockerPath"], runtime["dockerSocketPath"], runtime["imageId"],
                                            runtime["userId"], {"imageId": runtime["imageId"], "TEST": "not admitted"})
        self.daemon.names = tuple(row["containerName"] for row in self.files.reservation["jobs"])
        self.clock, self.guard = OpeningExecutionClock(self.daemon.deadline), Mock()
        original = self.files.context
        self.context = SourceColorCleanupContext(original.opening, original.producer_dir, original.resource_dir,
                                                 original.source_color_hash, self.clock, self.daemon.runtime,
                                                 self.daemon.config, self.guard)
        self.active, self.timer_events = None, []
        self.stack = ExitStack()
        self.stack.enter_context(patch("guided_opening_execution.work_timer", side_effect=self.phase_timer))
        self.stack.enter_context(patch("headless.grade_batch_cleanup.wall_budget", side_effect=self.batch_timer))

    @contextmanager
    def phase_timer(self, clock: OpeningExecutionClock) -> Iterator[None]:
        """Observe real phase semantics without installing an actual signal timer."""
        if self.active is not None or clock is not self.clock:
            raise AssertionError("TEST phase nested a timer or changed the original clock")
        self.active = "phase"
        self.timer_events.append(("phase", clock.end))
        try:
            clock.remaining()
            yield
            clock.remaining()
        finally:
            self.active = None

    @contextmanager
    def batch_timer(self, deadline: float) -> Iterator[None]:
        """The actual coordinator must own a separate nonnested interval at SAME end."""
        if self.active is not None or deadline != self.clock.end:
            raise AssertionError("TEST batch nested a timer or renewed cleanup time")
        self.active = "batch"
        self.timer_events.append(("batch", deadline))
        try:
            with self.daemon.timer(deadline):
                yield
        finally:
            self.active = None

    def prepare(self) -> object:
        """Read exactly partial reservation metadata; no native work occurs here."""
        return prepare_opening_source_color_cleanup(self.files.reference, self.context)

    def run(self) -> dict:
        """Exercise the public split with one simulated caller control-check phase."""
        prepared = self.prepare()
        self.clock.phase("cleanup-controls-after", lambda: None)
        return prepared.reconcile()

    def close(self) -> None:
        """Restore virtual leaves before removing only the two allocated TEST roots."""
        self.stack.close()
        self.daemon.close()
        self.files.close()
