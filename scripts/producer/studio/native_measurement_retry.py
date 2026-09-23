"""Retry missing footprints or command timeouts in one bounded measurement window.

Use the mixin before the existing NativeRun subclass in its MRO. The inherited
sample(), stop_reasons(), identity registry, lease and cleanup remain unchanged.
This module never launches a job or interprets a missing sample as healthy.
"""
from __future__ import annotations

import copy
import signal
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Protocol, cast

from native_render_processes import (
    MissingProcessFootprint, ProcessIdentity, ProcessRequest, ResourceMeasurementError,
)
from native_render_resources import ResourceCommandTimeout, ResourceSnapshot

from native_render_sampling import read_compact_snapshot as read_snapshot

MAX_SAMPLES = 4
MAX_WINDOW_SECONDS = 18.0
# Preview packaging launches bursts of short FFmpeg probes lasting multiple seconds.
# Spread the same four real samples across the existing 18-second window; never
# turn a disappeared process or an old reading into a successful measurement.
RETRY_DELAYS_SECONDS = (.5, 1.5, 4.0)


class MeasurementRegistry(Protocol):
    """The existing owner keeps authoritative identities and discovers children."""

    known: dict[int, Any]

    def live(self) -> dict:
        """Refresh actual live ancestry without deleting remembered identities."""
        ...


class MeasurementOwner(Protocol):
    """Only the existing supervisor supplies ownership and durable evidence."""

    project: Path
    result: dict
    registry: MeasurementRegistry | None
    started: float
    deadline: float
    abort_reason: str | None

    def persist(self) -> None:
        """Write current evidence or propagate the failure to write."""
        ...

    def record_lease_processes(self) -> None:
        """Preserve newly observed identities in the existing heavy-work lease."""
        ...


class MeasurementWindowExpired(ResourceMeasurementError):
    """No sample may be accepted after the measurement or run deadline."""


def deadline_signal(_signum: int, _frame: object) -> None:
    """Interrupt a blocking read so the existing supervisor enters cleanup."""
    raise MeasurementWindowExpired('Native resource measurement window expired')


@contextmanager
def measurement_alarm(deadline: float) -> Iterator[None]:
    """Use one temporary main-thread timer without displacing an active alarm."""
    if threading.current_thread() is not threading.main_thread():
        raise ResourceMeasurementError('Bounded measurement requires the main thread')
    if any(signal.getitimer(signal.ITIMER_REAL)):
        raise ResourceMeasurementError('An existing real-time alarm prevents bounded measurement')
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise MeasurementWindowExpired('Native resource measurement deadline already expired')
    previous = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, deadline_signal)
    try:
        signal.setitimer(signal.ITIMER_REAL, remaining)
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


class MeasurementWindow:
    """Require a fresh complete reading; retain every unsuccessful read attempt."""

    def __init__(self, owner: MeasurementOwner, request: ProcessRequest) -> None:
        """Use the earlier of the 18-second budget and the existing run limit."""
        self.owner, self.request = owner, request
        self.started = time.monotonic()
        self.deadline = min(self.started + MAX_WINDOW_SECONDS, owner.started + owner.deadline)
        self.record = {
            'status': 'sampling', 'maximumSamples': MAX_SAMPLES,
            'maximumWindowSeconds': MAX_WINDOW_SECONDS,
            'startedMonotonic': self.started, 'deadlineMonotonic': self.deadline,
            'attempts': [], 'phase': 'baseline' if not request.root and not request.remembered else 'owned-tree',
            'scope': 'Actual measurements; health requires existing admission or stop checks',
        }
        owner.result.setdefault('measurementRetryWindows', []).append(self.record)

    def check_deadline(self) -> None:
        """Respect cancellation and refuse even a complete but late reading."""
        if self.owner.abort_reason:
            raise ResourceMeasurementError(self.owner.abort_reason)
        if self.owner.registry is None and (self.request.root or self.request.remembered):
            raise ResourceMeasurementError('Owned measurement requires its existing process registry')
        if time.monotonic() >= self.deadline:
            raise MeasurementWindowExpired('Native resource measurement window expired')

    def run(self) -> ResourceSnapshot:
        """Record terminal failure without retrying unrelated errors or cleanup."""
        self.owner.persist()
        try:
            with measurement_alarm(self.deadline):
                return self.sample_loop()
        except Exception as error:
            self.record.update(status='failed', errorType=type(error).__name__, error=str(error))
            if self.record['attempts'] and self.record['attempts'][-1]['status'] == 'reading':
                self.record['attempts'][-1].update(
                    status='failed', errorType=type(error).__name__, error=str(error))
            raise
        finally:
            self.record['elapsedSeconds'] = time.monotonic() - self.started
            self.owner.persist()

    def sample_loop(self) -> ResourceSnapshot:
        """Call the real sampler directly at most four times, never nested retries."""
        for number in range(1, MAX_SAMPLES + 1):
            self.check_deadline()
            self.record['attempts'].append({'sample': number, 'status': 'reading'})
            self.owner.persist()
            self.check_deadline()
            try:
                snapshot = read_snapshot(self.owner.project, self.request)
            except (MissingProcessFootprint, ResourceCommandTimeout) as error:
                self.incomplete_sample(error, number)
            else:
                return self.complete_sample(snapshot)
        raise ResourceMeasurementError('Native resource sample limit exhausted')

    def incomplete_sample(self, error: MissingProcessFootprint | ResourceCommandTimeout,
                          number: int) -> None:
        """Keep exact failure evidence and refresh ownership before a fresh sample."""
        evidence = copy.deepcopy(error.evidence)
        self.owner.result.setdefault('measurementFailureEvidence', []).append(evidence)
        timed_out = isinstance(error, ResourceCommandTimeout)
        self.record['attempts'][-1].update(
            status='command-timeout' if timed_out else 'missing-footprint',
            elapsedSeconds=time.monotonic() - self.started,
            errorType=type(error).__name__, evidence=evidence)
        self.owner.persist()
        self.check_deadline()
        if number == MAX_SAMPLES:
            raise error
        self.refresh_request(error.identities)
        counter = 'commandTimeoutMeasurementRetries' if timed_out else 'processExitMeasurementRetries'
        self.owner.result[counter] = self.owner.result.get(counter, 0) + 1
        self.wait_before_retry(number)

    def wait_before_retry(self, number: int) -> None:
        """Let short child bursts settle inside the same attempt and deadline limits."""
        self.check_deadline()
        remaining = max(0, self.deadline - time.monotonic())
        delay = min(RETRY_DELAYS_SECONDS[number - 1], remaining)
        self.record['attempts'][-1]['retryDelaySeconds'] = delay
        self.owner.persist()
        self.check_deadline()
        started = time.monotonic()
        try:
            time.sleep(delay)
        finally:
            self.record['attempts'][-1]['retryWaitElapsedSeconds'] = time.monotonic() - started
        self.check_deadline()

    def refresh_request(self, discovered: tuple[ProcessIdentity, ...]) -> None:
        """Retain prior and sampler-observed identities, including detached children."""
        if self.owner.registry is None:
            if self.request.root or self.request.remembered or discovered:
                raise ResourceMeasurementError('Owned measurement requires its existing process registry')
            self.check_deadline()
            return
        self.owner.registry.live()
        current = tuple(ProcessIdentity(row.pid, row.started, row.pgid)
                        for row in self.owner.registry.known.values())
        remembered = {
            (row.pid, row.started, row.pgid): row
            for row in self.request.remembered + discovered + current
        }
        self.request = ProcessRequest(self.request.root, tuple(remembered.values()))
        self.owner.record_lease_processes()
        self.check_deadline()

    def complete_sample(self, snapshot: ResourceSnapshot) -> ResourceSnapshot:
        """Return the actual snapshot unchanged for the inherited policy checks."""
        self.check_deadline()
        if not isinstance(snapshot, ResourceSnapshot):
            raise ResourceMeasurementError('Sampler did not return a complete resource snapshot')
        self.record['attempts'][-1].update(
            status='measured', elapsedSeconds=time.monotonic() - self.started)
        self.record['status'] = 'measured-awaiting-existing-policy-check'
        return snapshot


class BoundedMeasurementRetryMixin:
    """Override measurement only; inherit admission, stop caps, lease and cleanup."""

    def measure_resources(self, request: ProcessRequest) -> ResourceSnapshot:
        """Require one complete actual sample within four attempts and 18 seconds."""
        return MeasurementWindow(cast(MeasurementOwner, self), request).run()
