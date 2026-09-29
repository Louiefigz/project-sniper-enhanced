"""The launch-deferral hook: a qualified CPU profile may hold a new launch, nothing more.

No profile exists. No measured profile has yet shown that holding a launch while host
CPU is busy improves throughput or meets a deadline, so admission passes ``None`` and
every decision is 'launch'. A future profile must be bound to the admitted qualified
pool record, name its measured evidence and bound its hold. Even then a decision only
delays a launch that has not started: it never stops, signals or shrinks running work,
and it never outlasts the owner's capacity-wait limit. Only a measured host interval
can hold a launch: the first admission reading is a baseline, so without earlier
evidence a profile launches rather than holding every owner for a poll. Memory, disk
and ownership admission (native_run_admission.py) and the running guards
(native_render_policy.py) are unchanged and decided first.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from native_work_pool_policy import POOL_CLASSES, QUEUE_SECONDS

NO_CPU_PROFILE = ('No qualified CPU launch-deferral profile exists: no measured profile has shown a '
                  'throughput or deadline benefit, so host CPU never delays or stops native work')
NO_INTERVAL = 'no measured host CPU interval at this poll; a profile holds only on measured evidence'
MEMORY_WAITING = {'decision': 'not-evaluated', 'reasons': (),
                  'why': 'memory, disk or ownership admission has not passed at this poll'}
DEFERRAL_MARGIN_SECONDS = 5.0
HEX_DIGITS = frozenset('0123456789abcdef')


def _digest(value: object) -> bool:
    """A lowercase SHA-256 hex digest naming exact evidence."""
    return isinstance(value, str) and len(value) == 64 and set(value) <= HEX_DIGITS


@dataclass(frozen=True)
class CpuDeferralProfile:
    """A qualified rule that holds a new launch while measured host CPU is busy.

    Attributes:
        profile_id: Stable name of the qualified profile.
        pool_record_sha256: The qualified pool record the benefit was measured under.
        lanes: Pool classes the benefit was measured for.
        busy_fraction: Hold a launch while the measured host busy fraction is at least this.
        maximum_deferral_seconds: Longest one launch may be held.
        evidence_sha256: Digest of the measured throughput or deadline evidence.
    """

    profile_id: str
    pool_record_sha256: str
    lanes: tuple[str, ...]
    busy_fraction: float
    maximum_deferral_seconds: float
    evidence_sha256: str

    def __post_init__(self) -> None:
        """Refuse a profile without exact evidence, known lanes and bounded holds."""
        if not isinstance(self.profile_id, str) or not self.profile_id.strip():
            raise ValueError('CPU deferral profile needs a name')
        if not _digest(self.pool_record_sha256) or not _digest(self.evidence_sha256):
            raise ValueError('CPU deferral profile must name its pool record and measured evidence')
        if not isinstance(self.lanes, tuple) or not self.lanes or not set(self.lanes) <= set(POOL_CLASSES):
            raise ValueError('CPU deferral profile lanes must be pool classes')
        numbers = (self.busy_fraction, self.maximum_deferral_seconds)
        if any(type(value) not in {int, float} or not math.isfinite(value) for value in numbers):
            raise ValueError('CPU deferral profile thresholds must be finite numbers')
        if not 0 < self.busy_fraction < 1 or not 0 < self.maximum_deferral_seconds <= QUEUE_SECONDS:
            raise ValueError('CPU deferral profile thresholds are out of bounds')


@dataclass(frozen=True)
class DeferralRequest:
    """One launch that already passed memory, disk and ownership admission.

    Attributes:
        lane: Pool class of the launch.
        pool: The pool lease admission record (mode and qualified record digest).
        cpu: The owner's latest interval from ``native_render_cpu.CpuTracker``.
        waited_seconds: Time this launch has already been held by CPU deferral.
        remaining_seconds: Time left before the owner's capacity-wait limit.
    """

    lane: str
    pool: dict
    cpu: dict
    waited_seconds: float
    remaining_seconds: float


def _blocker(request: DeferralRequest, profile: CpuDeferralProfile) -> str | None:
    """Name why a profile cannot hold this launch; a hold never outlives its budget."""
    record = request.pool.get('modeRecord') or {}
    if request.lane not in profile.lanes:
        return 'profile was not qualified for this pool class'
    if request.pool.get('mode') != 'qualified' or record.get('sha256') != profile.pool_record_sha256:
        return 'profile was not measured under the admitted pool record'
    if request.waited_seconds >= profile.maximum_deferral_seconds:
        return 'qualified deferral time is exhausted'
    if request.remaining_seconds <= DEFERRAL_MARGIN_SECONDS:
        return 'owner capacity-wait limit leaves no deferral time'
    return None


def launch_deferral(request: DeferralRequest, profile: CpuDeferralProfile | None) -> dict:
    """Decide whether a qualified profile holds this launch for one more admission poll.

    Args:
        request: The admitted-but-unlaunched owner and its latest CPU evidence.
        profile: A qualified profile, or None (the only value admission passes today).

    Returns:
        A receipt-ready decision; non-empty ``reasons`` hold the launch for one poll.
    """
    if profile is None:
        return {'enabled': False, 'decision': 'launch', 'reasons': (), 'why': NO_CPU_PROFILE}
    decision = {'enabled': True, 'profile': profile.profile_id, 'waitedSeconds': request.waited_seconds}
    blocker = _blocker(request, profile)
    if blocker:
        return decision | {'decision': 'launch', 'reasons': (), 'why': blocker}
    host = request.cpu.get('host') if isinstance(request.cpu, dict) else None
    if not isinstance(host, dict) or host.get('status') != 'measured':
        return decision | {'decision': 'launch', 'reasons': (), 'why': NO_INTERVAL}
    busy = host['busyFraction']
    if busy < profile.busy_fraction:
        return decision | {'decision': 'launch', 'reasons': (), 'why': 'host CPU is below the qualified threshold'}
    reason = f'qualified CPU deferral: host busy {busy:.3f} >= {profile.busy_fraction:.3f}'
    return decision | {'decision': 'defer', 'reasons': (reason,), 'why': reason}
