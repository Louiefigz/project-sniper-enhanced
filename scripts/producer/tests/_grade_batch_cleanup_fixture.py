"""Virtual daemon/clock only; no Docker command, process or resource probing occurs."""
from __future__ import annotations

import tempfile
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import UUID

from headless import grade_batch_cleanup as cleanup
from headless.container_policy import DockerRuntime


class GradeBatchCleanupFixture:
    """One actual private TEST config directory and wholly simulated native leaves."""

    def __init__(self, count: int = 2, duration: float = 30.0) -> None:
        """Hold original virtual cleanup time and inert exact UUIDv4 names."""
        self.temporary = tempfile.TemporaryDirectory(prefix="grade-batch-cleanup-TEST-")
        self.root = Path(self.temporary.name).resolve()
        self.config = self.root / "config"
        self.config.mkdir(mode=0o700)
        self.names = tuple("sniper-grade-observation-" + UUID(int=index + 1, version=4).hex for index in range(count))
        self.now, self.deadline = 1000.0, 1000.0 + duration
        self.present: set[str] = set()
        self.events, self.timers, self.masks = [], [], []
        self.before_inspect = Mock()
        self.before_remove = Mock()
        self.guard = Mock()
        self.runtime = DockerRuntime("/TEST/no-docker", "/TEST/no-socket", "sha256:" + "a" * 64,
                                     "501:20", {"imageId": "sha256:" + "a" * 64, "TEST": True})
        self.context = cleanup.GradeBatchCleanupContext(self.runtime, self.config, self.deadline, self.guard)
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(cleanup.time, "monotonic", side_effect=lambda: self.now))
        self.stack.enter_context(patch.object(cleanup.time, "sleep", side_effect=self.sleep))
        self.stack.enter_context(patch.object(cleanup, "_is_absent", side_effect=self.inspect))
        self.stack.enter_context(patch.object(cleanup, "_force_remove", side_effect=self.remove))
        self.stack.enter_context(patch.object(cleanup, "wall_budget", side_effect=self.timer))
        self.stack.enter_context(patch.object(cleanup.signal, "getitimer", return_value=(0.0, 0.0)))
        self.stack.enter_context(patch.object(cleanup.signal, "pthread_sigmask", side_effect=self.mask))

    def sleep(self, seconds: float) -> None:
        """Advance only the one original virtual clock, never real wall-clock sleep."""
        self.now += seconds

    @contextmanager
    def timer(self, deadline: float) -> Iterator[None]:
        """Record one unchanged supplied timer; production wall_budget remains unmodified."""
        self.timers.append(deadline)
        yield
        cleanup.require_time(deadline)

    def mask(self, action: int, signals: set) -> set:
        """Observe masking/restoration without modifying the test process's signal mask."""
        self.masks.append((action, signals))
        return set()

    def inspect(self, runtime: DockerRuntime, config: str, name: str) -> bool | None:
        """Simulate only exact per-name absence; no filesystem or daemon is queried."""
        if runtime is not self.runtime or config != str(self.config) or name not in self.names:
            raise AssertionError("TEST cleanup primitive used different original controls")
        self.events.append(("inspect", name, self.now))
        self.before_inspect(name)
        return name not in self.present

    def remove(self, runtime: DockerRuntime, config: str, name: str) -> bool:
        """Remove only an entry from the virtual TEST set, not an actual container."""
        if runtime is not self.runtime or config != str(self.config) or name not in self.names:
            raise AssertionError("TEST cleanup removal used different original controls")
        self.events.append(("remove", name, self.now))
        self.before_remove(name)
        existed = name in self.present
        self.present.discard(name)
        return existed

    def run(self) -> dict:
        """Exercise the real coordinator with all native Docker leaves replaced."""
        return cleanup.reconcile_grade_batch(self.names, self.context)

    def close(self) -> None:
        """Remove only this exact owned TEST directory and restore Python patches."""
        self.stack.close()
        self.temporary.cleanup()
