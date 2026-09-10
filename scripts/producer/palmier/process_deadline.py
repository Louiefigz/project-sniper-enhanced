"""Context-bound subprocess timeout for connected acceptance work."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

from palmier.mcp_client import PalmierError

_ACTIVE: ContextVar[Any | None] = ContextVar(
    "palmier_process_deadline", default=None)


@contextmanager
def use_process_deadline(deadline: Any) -> Iterator[None]:
    """Make one Deadline's remaining budget visible to local subprocesses."""
    if not callable(getattr(deadline, "remaining", None)):
        raise PalmierError("subprocess deadline has no remaining-time clock")
    token = _ACTIVE.set(deadline)
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def process_timeout(default_s: float = 300.0) -> float:
    """Return a positive timeout capped by the active run deadline."""
    if default_s <= 0:
        raise PalmierError("subprocess timeout must be positive")
    active = _ACTIVE.get()
    remaining = active.remaining() if active is not None else float(default_s)
    return max(0.001, min(float(default_s), float(remaining)))
