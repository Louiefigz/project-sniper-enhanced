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
