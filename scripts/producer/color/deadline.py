"""Main-thread POSIX wall budgets, disarmed before mandatory container cleanup."""
from __future__ import annotations

import signal
import threading
import time
from contextlib import contextmanager
from typing import Iterator


class WallBudgetExceeded(RuntimeError):
    """The original work deadline expired; this is not invalid cache evidence."""


def require_time(deadline: float) -> float:
    """Fail rather than publish successful screening beyond the work budget."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise WallBudgetExceeded("color diagnostic work deadline exceeded; cleanup time is separate")
    return remaining


def _expired(_signal: int, _frame: object) -> None:
    """Interrupt blocking host work through normal exception/finally cleanup."""
    raise WallBudgetExceeded("color diagnostic work deadline exceeded; cleanup time is separate")


@contextmanager
def wall_budget(deadline: float) -> Iterator[None]:
    """Bound one work phase; never install a timer around mandatory cleanup."""
    if threading.current_thread() is not threading.main_thread() or not hasattr(signal, "setitimer"):
        raise RuntimeError("color diagnostic requires POSIX main-thread deadline support")
    if signal.getitimer(signal.ITIMER_REAL)[0] != 0:
        raise RuntimeError("color diagnostic cannot replace another active wall timer")
    previous = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, _expired)
    try:
        signal.setitimer(signal.ITIMER_REAL, require_time(deadline))
        yield
        require_time(deadline)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _restore_owner_handler(previous: object, pending: list[bool]) -> None:
    """Restore the caller's disposition before replaying its deferred cancellation."""
    try:
        signal.signal(signal.SIGUSR1, previous)
    finally:
        if pending[0]:
            signal.pthread_kill(threading.get_ident(), signal.SIGUSR1)


def _restore_owner_cancellation(mask: set, previous: object, pending: list[bool]) -> None:
    """Restore both controls even if an alarm interrupts a completed mutation."""
    try:
        signal.pthread_sigmask(signal.SIG_SETMASK, mask)
    finally:
        _restore_owner_handler(previous, pending)


@contextmanager
def defer_owner_cancellation() -> Iterator[None]:
    """Defer USR1 across threads; restore its exact disposition and caller mask."""
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("owner cancellation deferral requires the main thread")
    previous = signal.getsignal(signal.SIGUSR1)
    pending = [False]

    def remember(_signal: int, _frame: object) -> None:
        """Coalesce cancellation while leaving the separate ALRM deadline live."""
        pending[0] = True

    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, set())
    try:
        signal.signal(signal.SIGUSR1, remember)
        signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGUSR1})
        yield
    finally:
        _restore_owner_cancellation(previous_mask, previous, pending)
