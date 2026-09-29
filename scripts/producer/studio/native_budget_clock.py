"""One inherited absolute deadline for budgeted native production work.

A batch clock never restarts. Each observation takes the larger of wall-clock
elapsed time and the boot-continuous monotonic delta from the last durable
anchor, and never goes below that anchor's recorded elapsed time. Suspend
(``CLOCK_MONOTONIC`` keeps counting on macOS), a wall-clock rollback or a
reboot therefore cannot grant fresh time; a forward wall-clock jump can only
consume time early, which is the conservative direction.

A live request carries its remaining allocation as two deadlines: a
continuous-monotonic one valid within the admitting boot, and a wall-clock
one. The smaller remaining value wins. Unbudgeted requests (no
``productionBudget``) keep their existing per-stage limits.
"""
from __future__ import annotations

import math
import subprocess
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

MIN_STAGE_SECONDS = 1.0


class BudgetClockError(RuntimeError):
    """The host cannot supply the clock identity a budgeted run requires."""


class BudgetExhausted(RuntimeError):
    """The inherited production deadline leaves no time for the requested stage."""

    category = 'budget-exhausted'


@lru_cache(maxsize=1)
def boot_id() -> str:
    """Return this boot's identity; budgeted work fails closed without one."""
    try:
        if Path('/usr/sbin/sysctl').is_file():
            value = subprocess.run(['/usr/sbin/sysctl', '-n', 'kern.bootsessionuuid'],
                                   capture_output=True, text=True, check=True, timeout=5).stdout
        else:
            value = Path('/proc/sys/kernel/random/boot_id').read_text()
    except (OSError, subprocess.SubprocessError) as error:
        raise BudgetClockError(f'Boot identity is unavailable: {error}') from error
    value = value.strip()
    if not 8 <= len(value) <= 64 or any(ch not in '0123456789abcdefABCDEF-' for ch in value):
        raise BudgetClockError('Boot identity is malformed')
    return value


def continuous_now() -> float:
    """Monotonic seconds that keep counting through system sleep."""
    return time.clock_gettime(time.CLOCK_MONOTONIC)


@dataclass(frozen=True)
class ClockAnchor:
    """The last durable observation of one batch clock."""

    boot: str
    continuous: float
    epoch: float
    elapsed: float

    @classmethod
    def from_record(cls, value: object) -> ClockAnchor:
        """Validate a stored anchor exactly; malformed time is corrupt authority."""
        keys = {'boot', 'continuous', 'epoch', 'elapsed'}
        if type(value) is not dict or set(value) != keys or type(value['boot']) is not str:
            raise ValueError('Budget clock anchor is malformed')
        numbers = [value[key] for key in ('continuous', 'epoch', 'elapsed')]
        if any(type(item) not in (int, float) or not math.isfinite(item) for item in numbers) \
                or value['elapsed'] < 0:
            raise ValueError('Budget clock anchor has invalid numbers')
        return cls(value['boot'], float(value['continuous']), float(value['epoch']), float(value['elapsed']))

    def record(self) -> dict:
        """Serialize the anchor for the authority record."""
        return {'boot': self.boot, 'continuous': self.continuous, 'epoch': self.epoch,
                'elapsed': self.elapsed}


def start_anchor() -> ClockAnchor:
    """Anchor a new batch at zero elapsed seconds."""
    return ClockAnchor(boot_id(), continuous_now(), time.time(), 0.0)


def observe(anchor: ClockAnchor, start_epoch: float) -> ClockAnchor:
    """Advance a batch clock without ever granting time back.

    Within one boot the continuous clock carries elapsed time (through sleep
    and wall-clock changes). Across a reboot only wall time can measure the
    downtime; if wall time is then behind the last observation, the downtime
    is unknowable and the clock fails closed instead of guessing.
    """
    now_boot, now_continuous, now_epoch = boot_id(), continuous_now(), time.time()
    carried = anchor.elapsed
    if now_boot == anchor.boot and now_continuous >= anchor.continuous:
        carried += now_continuous - anchor.continuous
    elif now_epoch < anchor.epoch:
        raise BudgetClockError('The wall clock is behind the batch clock\'s last observation after a '
                               'restart; elapsed time cannot be established, so no new work is admitted')
    elapsed = max(carried, now_epoch - start_epoch, anchor.elapsed)
    return ClockAnchor(now_boot, now_continuous, now_epoch, elapsed)


def allocation(anchor: ClockAnchor, remaining: float, cleanup_reserve: float) -> dict:
    """Describe a live grant as deadlines that later stages inherit, never reset."""
    if not math.isfinite(remaining) or not math.isfinite(cleanup_reserve) or cleanup_reserve < 0:
        raise ValueError('Budget allocation needs finite seconds')
    return {'boot': anchor.boot, 'continuousDeadline': anchor.continuous + remaining,
            'epochDeadline': anchor.epoch + remaining, 'grantedSeconds': remaining,
            'cleanupReserveSeconds': cleanup_reserve}


def allocation_remaining(grant: dict) -> float:
    """Seconds left in one granted allocation; a different boot has none left."""
    wall = grant['epochDeadline'] - time.time()
    if boot_id() != grant['boot']:
        return min(wall, 0.0)
    from studio.production.queue_authority import credit_delta
    return min(wall, grant['continuousDeadline'] - continuous_now()) + credit_delta(grant)


def remaining_seconds(request: dict) -> float | None:
    """Seconds left in the inherited deadline; None when the request is unbudgeted."""
    budget = request.get('productionBudget')
    if not budget:
        return None
    return allocation_remaining(budget['allocation'])


def stage_allowance(request: dict, stage_limit: float) -> float:
    """The smaller of a stage's own limit and the inherited deadline minus cleanup."""
    remaining = remaining_seconds(request)
    if remaining is None:
        return stage_limit
    reserve = request['productionBudget']['allocation']['cleanupReserveSeconds']
    available = remaining - reserve
    if available < MIN_STAGE_SECONDS:
        raise BudgetExhausted(
            f'Production deadline reached: {max(remaining, 0):.0f}s remain and '
            f'{reserve:.0f}s are reserved for cleanup and handoff')
    return min(stage_limit, available)
