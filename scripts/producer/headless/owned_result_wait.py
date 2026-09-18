"""Terminal-aware publication waiting, never resource-removal authority.

Only an execution owner may supply the exact returned container ID and original
absolute work deadline. The supplied reader retains its existing file safety
and size limits; the caller still validates the document and proves cleanup.
"""
from __future__ import annotations

import math
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from color.deadline import require_time
from headless.container_policy import DockerRuntime
from headless.external_media_probe import CONTAINER_ID, _is_terminal, _state, _terminal_failure

_STATE_INTERVAL_SECONDS = 2.0
ResultReader = Callable[[], str | None]


@dataclass(frozen=True)
class OwnedResultWait:
    """Held owner inputs, not authentication or a newly granted work budget."""

    runtime: DockerRuntime
    config_dir: str
    container_id: str
    deadline: float


def _validate(context: OwnedResultWait, read_result: ResultReader) -> None:
    """Reject malformed private controls before file or daemon observations."""
    if type(context) is not OwnedResultWait or not callable(read_result):
        raise RuntimeError("owned result wait requires its exact context and reader")
    if type(context.container_id) is not str or not CONTAINER_ID.fullmatch(context.container_id):
        raise RuntimeError("owned result wait requires the exact returned container ID")
    if type(context.config_dir) is not str or not Path(context.config_dir).is_absolute():
        raise RuntimeError("owned result wait requires an absolute private directory")
    if not _finite_deadline(context.deadline):
        raise RuntimeError("owned result wait requires a finite original deadline")
    require_time(context.deadline)


def _finite_deadline(value: object) -> bool:
    """Oversized Python integers are invalid clocks, not conversion exceptions."""
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _read(context: OwnedResultWait, read_result: ResultReader) -> str | None:
    """Even an already-published result must finish reading before expiry."""
    require_time(context.deadline)
    raw = read_result()
    require_time(context.deadline)
    if raw is not None and type(raw) is not str:
        raise RuntimeError("owned result reader returned non-text publication")
    return raw


def _pending(context: OwnedResultWait, read_result: ResultReader) -> str | None:
    """A terminal observation prompts one final publication read, not cleanup."""
    timeout = min(15.0, require_time(context.deadline))
    try:
        state = _state(context.runtime, context.config_dir, context.container_id, timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("owned result state observation failed before publication") from error
    require_time(context.deadline)
    if not _is_terminal(state):
        return None
    raw = _read(context, read_result)
    if raw is not None:
        return raw
    raise RuntimeError(_terminal_failure(state))


def wait_owned_result(context: OwnedResultWait, read_result: ResultReader) -> str:
    """Wait on one held resource without renewing time or inferring removal."""
    _validate(context, read_result)
    delay, next_state_check = 0.05, 0.0
    while True:
        raw = _read(context, read_result)
        if raw is not None:
            require_time(context.deadline)
            return raw
        if time.monotonic() >= next_state_check:
            raw = _pending(context, read_result)
            next_state_check = time.monotonic() + _STATE_INTERVAL_SECONDS
        if raw is not None:
            require_time(context.deadline)
            return raw
        time.sleep(min(delay, require_time(context.deadline)))
        delay = min(delay * 1.5, 1.0)
