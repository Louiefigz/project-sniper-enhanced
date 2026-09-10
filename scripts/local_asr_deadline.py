"""One local-ASR work clock; retry and cleanup never grant more work time.

This is an aggregate cooperative deadline plus owned leaf-process timeouts,
not proof that an externally killed Python owner left no detached descendants.
"""
from __future__ import annotations

import math
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator, Mapping

TIMEOUT_ENV = "WHISPER_CPP_TIMEOUT_SECONDS"
MAX_LOCAL_ASR_SECONDS = 3600


class LocalWhisperError(RuntimeError):
    """A local-ASR preflight, execution, or output-contract failure."""


class LocalAsrDeadlineError(LocalWhisperError):
    """The one aggregate local-ASR work allowance has expired."""


def configured_timeout(environ: Mapping[str, str] | None = None) -> int:
    """Reject malformed or over-ceiling limits before any filesystem work."""
    env = os.environ if environ is None else environ
    raw = env.get(TIMEOUT_ENV, str(MAX_LOCAL_ASR_SECONDS))
    if not isinstance(raw, str) or not raw.strip().isascii() or not raw.strip().isdecimal():
        raise LocalWhisperError(f"{TIMEOUT_ENV} must be an integer from 1 to 3600")
    digits = raw.strip().lstrip("0") or "0"
    value = int(digits) if len(digits) <= 4 else MAX_LOCAL_ASR_SECONDS + 1
    if not 1 <= value <= MAX_LOCAL_ASR_SECONDS:
        raise LocalWhisperError(f"{TIMEOUT_ENV} must be an integer from 1 to 3600")
    return value


@dataclass(frozen=True)
class LocalAsrDeadline:
    """An absolute same-host monotonic expiry, never an individual-attempt limit."""

    expires_at: float
    timeout_seconds: int = MAX_LOCAL_ASR_SECONDS

    @classmethod
    def start(cls, environ: Mapping[str, str] | None = None,
              parent_expires_at: float | None = None) -> LocalAsrDeadline:
        """Capture once before source/tool/model reads; inherited clocks only shorten."""
        now = time.monotonic()
        timeout = configured_timeout(environ)
        expires = now + timeout
        if parent_expires_at is not None:
            _finite_expiry(parent_expires_at)
            expires = min(expires, parent_expires_at)
        active = _ACTIVE.get()
        if active is not None:
            expires = min(expires, active.expires_at)
        result = cls(expires, timeout)
        result.guard()
        return result

    def remaining(self) -> float:
        """Reject expiry instead of clamping it into fresh positive work credit."""
        _finite_expiry(self.expires_at)
        remaining = self.expires_at - time.monotonic()
        if not math.isfinite(remaining) or remaining <= 0:
            raise LocalAsrDeadlineError("local ASR aggregate work deadline exceeded")
        return remaining

    def guard(self) -> None:
        """Check the same deadline at a work/publication boundary."""
        self.remaining()


_ACTIVE: ContextVar[LocalAsrDeadline | None] = ContextVar("local_asr_deadline", default=None)


def _finite_expiry(value: float) -> None:
    """An explicit parent clock is a finite monotonic number, not wall time."""
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise LocalWhisperError("local ASR parent expiry must be a finite positive monotonic time")


def current_local_asr_deadline() -> LocalAsrDeadline:
    """Require explicit ownership; leaf helpers may not silently start new clocks."""
    deadline = _ACTIVE.get()
    if deadline is None:
        raise LocalWhisperError("local ASR work requires an active aggregate deadline")
    deadline.guard()
    return deadline


@contextmanager
def use_local_asr_deadline(deadline: LocalAsrDeadline) -> Iterator[LocalAsrDeadline]:
    """Propagate through synchronous helpers and asyncio.to_thread without signals."""
    if type(deadline) is not LocalAsrDeadline:
        raise LocalWhisperError("local ASR deadline must be a LocalAsrDeadline")
    held = LocalAsrDeadline.start(parent_expires_at=deadline.expires_at)
    token = _ACTIVE.set(held)
    try:
        yield held
        held.guard()
    finally:
        _ACTIVE.reset(token)
