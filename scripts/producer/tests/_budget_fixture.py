"""Shared fixtures for production-budget tests: controllable clocks, private roots, projects."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused
from studio import native_budget_clock as clock


@dataclass
class FakeClock:
    """Wall time, boot-continuous time and boot identity that tests move explicitly."""

    wall: float = 1_800_000_000.0
    continuous: float = 5_000.0
    boot: str = '11111111-2222-3333-4444-555555555555'

    def advance(self, seconds: float, wall: float | None = None) -> None:
        """Advance both clocks (optionally moving wall time by a different amount)."""
        self.continuous += seconds
        self.wall += seconds if wall is None else wall

    def reboot(self, downtime: float) -> None:
        """A new boot restarts the continuous clock; wall time moves by the downtime."""
        self.boot = self.boot[:-1] + ('0' if self.boot[-1] != '0' else '1')
        self.continuous = 10.0
        self.wall += downtime


@contextlib.contextmanager
def fake_clock(value: FakeClock) -> Iterator[FakeClock]:
    """Patch every clock the budget code reads."""
    clock.boot_id.cache_clear()
    with mock.patch.object(clock, 'boot_id', lambda: value.boot), \
            mock.patch.object(clock, 'continuous_now', lambda: value.continuous), \
            mock.patch.object(clock.time, 'time', lambda: value.wall):
        yield value


def private_root(test: object) -> Path:
    """A canonical private temporary authority root removed after the test."""
    temporary = tempfile.TemporaryDirectory()
    test.addCleanup(temporary.cleanup)
    base = Path(temporary.name).resolve()
    os.chmod(base, 0o700)
    return base / 'budgets'


SOURCE = b'source-video'
ENGINE = {'root': '/engine', 'identity': 'e' * 64, 'files': 1}


def source_sha(source: bytes = SOURCE) -> str:
    """The digest a batch declares for a TEST recording."""
    return hashlib.sha256(source).hexdigest()


def make_project(parent: Path, name: str, source: bytes = SOURCE,
                 cuts: tuple[tuple[float, float], ...] = ((10.0, 40.0), (50.0, 80.0))) -> Path:
    """A minimal native Short project: one source asset, a 60 s canvas and its source cuts."""
    project = parent / name
    project.mkdir(parents=True)
    sha = source_sha(source)
    plan = {'schemaVersion': 1, 'assets': [{'role': 'source', 'sha256': sha, 'file': f'assets/{sha}.mp4',
                                             'path': str(project / 'assets' / f'{sha}.mp4')}],
            'canvas': {'totalFrames': 1800, 'frameRate': '30/1', 'sourceFile': f'assets/{sha}.mp4',
                       'cuts': [{'start': start, 'end': end, 'speed': 1} for start, end in cuts]}}
    (project / 'SHORT-PROJECT.json').write_text(json.dumps(plan))
    manifest = {'projectHash': hashlib.sha256(name.encode()).hexdigest(), 'files': []}
    (project / 'PROJECT-MANIFEST.json').write_text(json.dumps(manifest))
    return project
