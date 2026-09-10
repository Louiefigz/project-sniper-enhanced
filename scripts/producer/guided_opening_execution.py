"""Per-invocation opening work clocks, honest phase failures and byte guards.

The server owns the original generation clock, lease, process group and crash
reconciliation. This local monotonic budget cannot extend that authority.
Timers cover work only; existing owned container cleanup runs outside phases.
"""
from __future__ import annotations

import math
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from palmier.process_deadline import use_process_deadline


def _expired(_signal: int, _frame: object) -> None:
    """Interrupt blocking work through its normal exception/finally path."""
    raise RuntimeError("opening media work deadline exceeded; cleanup remains required")


@dataclass
class OpeningExecutionClock:
    """One finite remainder, never a renewed allowance for a later phase."""

    end: float
    events: list[dict] = field(default_factory=list)

    def remaining(self) -> float:
        """Provide the same remaining budget to existing media subprocess seams."""
        value = self.end - time.monotonic()
        if value <= 0:
            raise RuntimeError("opening media work deadline exceeded")
        return value

    def phase(self, name: str, operation: Callable[[], Any], limit: float | None = None) -> Any:
        """Record actual failed work too; never label a timed-out candidate complete."""
        started = time.monotonic()
        if limit is not None and (not math.isfinite(limit) or limit <= 0):
            raise RuntimeError("opening phase limit must be positive")
        bound = self if limit is None else OpeningExecutionClock(min(self.end, started + limit))
        event = {"stage": name, "status": "failed"}
        try:
            with work_timer(bound), use_process_deadline(bound):
                result = operation()
            event["status"] = "complete"
            return result
        except (OSError, RuntimeError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
            event["error"] = str(error)
            raise
        finally:
            event["elapsedMs"] = round((time.monotonic() - started) * 1000)
            self.events.append(event)


def opening_clock(timeout: float) -> OpeningExecutionClock:
    """Capture the server-provided remainder at the worker's actual entry."""
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 1500:
        raise RuntimeError("opening media requires a positive remaining budget at most25 minutes")
    return OpeningExecutionClock(time.monotonic() + timeout)


@contextmanager
def work_timer(clock: OpeningExecutionClock) -> Iterator[None]:
    """Bound host hashing/legacy subprocess work without replacing another timer."""
    if threading.current_thread() is not threading.main_thread() or not hasattr(signal, "setitimer"):
        raise RuntimeError("opening media requires POSIX main-thread work timers")
    if signal.getitimer(signal.ITIMER_REAL)[0] != 0:
        raise RuntimeError("opening media cannot replace another active timer")
    previous = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, _expired)
    try:
        signal.setitimer(signal.ITIMER_REAL, clock.remaining())
        yield
        clock.remaining()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
