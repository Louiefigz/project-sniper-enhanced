"""Capacity-aware native budgets and confirmed host pressure for new attempts.

Physical footprint already includes compression. Coarse memory-pressure headroom
is a percentage observation, never an estimate of allocatable bytes. Historical
explicit policies retain their existing admission and immediate-stop behavior.
"""
from __future__ import annotations

from dataclasses import asdict
import math
import time

from native_render_resources import (
    GIB, ResourcePolicy, ResourceSnapshot, _system_reasons, owned_reasons, resource_warnings,
)

MODE = 'capacity-adaptive-v1'
PRESSURE_READINGS = 3
PRESSURE_SECONDS = 10.0
MAXIMUM_READING_GAP_SECONDS = 15.0
SEVERE_HEADROOM_PERCENT = 5.0
COMPRESSOR_REASON = 'physical memory occupied by the compressor exceeds policy'
WARNING_PRESSURE_REASON = 'kernel memory pressure is warning'


def capacity_policy(baseline: ResourceSnapshot) -> ResourcePolicy:
    """Freeze bounded allowances from measured physical capacity, not idle pages."""
    physical = baseline.physical_bytes
    if type(physical) is not int or physical <= 0:
        raise ValueError('Adaptive native policy requires positive measured physical capacity')
    tree = min(16.0, physical / GIB * .25)
    return ResourcePolicy(maximum_owned_gib=tree,
                          maximum_process_gib=min(8.0, tree * .75),
                          maximum_swap_growth_gib=min(4.0, physical / GIB * .0625))


def adaptive_admission_reasons(snapshot: ResourceSnapshot, policy: ResourcePolicy,
                               now: float | None = None) -> tuple[str, ...]:
    """Require normal pressure and real headroom; old compression is only context."""
    invalid = _measurement_reasons(snapshot)
    if invalid:
        return tuple(invalid)
    observed_now = time.time() if now is None else now
    if not _finite_time(observed_now) or not _finite_time(snapshot.measured_at):
        return ('resource measurement has an invalid timestamp',)
    reasons = _system_reasons(snapshot, policy, policy.admission_free_percent, observed_now)
    return tuple(reason for reason in reasons if reason != COMPRESSOR_REASON)


def _finite_time(value: object) -> bool:
    """Do not let NaN, booleans or infinities bypass observation ordering."""
    return type(value) in {int, float} and math.isfinite(value) and value >= 0


def _measurement_reasons(snapshot: ResourceSnapshot) -> list[str]:
    """Reject malformed public inputs before arithmetic or pressure accumulation."""
    if not isinstance(snapshot, ResourceSnapshot):
        return ['resource measurement is not a complete ResourceSnapshot']
    byte_fields = ('physical_bytes', 'swap_used_bytes', 'compressor_bytes', 'disk_free_bytes',
                   'owned_footprint_bytes', 'largest_owned_process_bytes', 'unused_physical_bytes')
    invalid = [name for name in byte_fields
               if type(getattr(snapshot, name)) is not int or getattr(snapshot, name) < 0]
    if type(snapshot.physical_bytes) is int and snapshot.physical_bytes == 0:
        invalid.append('physical_bytes')
    free = snapshot.free_percent
    if type(free) not in {int, float} or not math.isfinite(free) or not 0 <= free <= 100:
        invalid.append('free_percent')
    if type(snapshot.kernel_pressure_level) is not int or snapshot.kernel_pressure_level not in {1, 2, 4}:
        invalid.append('kernel_pressure_level')
    if type(snapshot.identity_verified) is not bool:
        invalid.append('identity_verified')
    if not isinstance(snapshot.owned_pids, tuple) or any(type(pid) is not int or pid <= 1
                                                       for pid in snapshot.owned_pids):
        invalid.append('owned_pids')
    return [f'invalid resource measurement field: {name}' for name in invalid]


def _context(snapshot: ResourceSnapshot, baseline: ResourceSnapshot) -> dict:
    """Keep host-wide existing amounts distinct from growth during this job."""
    return {'physicalBytes': snapshot.physical_bytes, 'freePercent': snapshot.free_percent,
            'unusedPhysicalBytes': snapshot.unused_physical_bytes,
            'compressorBytes': snapshot.compressor_bytes,
            'compressorGrowthBytes': snapshot.compressor_bytes - baseline.compressor_bytes,
            'swapUsedBytes': snapshot.swap_used_bytes,
            'swapGrowthBytes': snapshot.swap_used_bytes - baseline.swap_used_bytes}


def _warnings(snapshot: ResourceSnapshot, baseline: ResourceSnapshot,
              policy: ResourcePolicy) -> list[str]:
    """Report compression and swap without attributing other applications to this tree."""
    warnings = list(resource_warnings(snapshot, policy))
    if snapshot.compressor_bytes > snapshot.physical_bytes * policy.maximum_compressor_fraction:
        warnings.append('host compressor occupancy is elevated; pressure is evaluated separately')
    if snapshot.compressor_bytes - baseline.compressor_bytes > GIB:
        warnings.append('host compressor grew more than one GiB since admission')
    if snapshot.swap_used_bytes > 0:
        warnings.append('host swap is present; existing use is not new render allocation')
    if snapshot.swap_used_bytes - baseline.swap_used_bytes > policy.maximum_swap_growth_gib * GIB:
        warnings.append('host swap growth exceeds the advisory allowance; pressure is evaluated separately')
    return warnings


def capacity_derivation(baseline: ResourceSnapshot, policy: ResourcePolicy) -> dict:
    """Explain frozen policy math and admission context without adding policy fields."""
    invalid = _measurement_reasons(baseline)
    if invalid:
        return {'mode': MODE, 'budgets': asdict(policy), 'invalidBaselineReasons': invalid}
    return {'mode': MODE, 'physicalBytes': baseline.physical_bytes,
            'ownedBudgetRule': 'min(16 GiB, 25% of measured physical RAM)',
            'processBudgetRule': 'min(8 GiB, 75% of the owned-tree budget)',
            'swapGrowthAdvisoryRule': 'min(4 GiB, 6.25% of measured physical RAM)',
            'budgets': asdict(policy), 'memoryContext': _context(baseline, baseline),
            'admissionWarnings': _warnings(baseline, baseline, policy),
            'literalUnusedRamAdvisory': True, 'compressorAndSwapAdvisory': True,
            'coarseHeadroomConvertedToBytes': False, **_guard_rules()}


def _guard_rules() -> dict:
    """Keep duration and immediate-stop semantics reconstructable in every receipt."""
    return {'pressureReadingsRequired': PRESSURE_READINGS, 'pressureSecondsRequired': PRESSURE_SECONDS,
            'maximumReadingGapSeconds': MAXIMUM_READING_GAP_SECONDS,
            'severeHeadroomPercent': SEVERE_HEADROOM_PERCENT,
            'pollingLimitScope': 'sampled supervision; not an OS-enforced allocation quota',
            'swapAndCompressorScope': 'host-wide advisory observations; pressure supplies stop evidence'}


class AdaptiveMemoryGuard:
    """Track independently sustained pressure while preserving immediate hard stops."""

    def __init__(self, baseline: ResourceSnapshot, policy: ResourcePolicy) -> None:
        """Start observation ordering at the admitted baseline without counting it."""
        self.baseline, self.policy = baseline, policy
        self.last_measured_at = baseline.measured_at
        self.last_monotonic: float | None = None
        self.windows: dict[str, dict | None] = {'kernel-warning': None, 'low-headroom': None}

    def _clock_reasons(self, snapshot: ResourceSnapshot, monotonic_now: float,
                       wall_now: float) -> list[str]:
        """Only fresh, strictly ordered actual samples contribute duration evidence."""
        values = (monotonic_now, wall_now, snapshot.measured_at, self.last_measured_at)
        if not all(_finite_time(value) for value in values):
            return ['resource measurement has an invalid timestamp or monotonic clock']
        reasons = []
        if snapshot.measured_at <= self.last_measured_at:
            reasons.append('resource measurement timestamp did not strictly increase')
        if self.last_monotonic is not None and monotonic_now <= self.last_monotonic:
            reasons.append('resource measurement monotonic clock did not strictly increase')
        return reasons

    def _hard_reasons(self, snapshot: ResourceSnapshot, wall_now: float) -> list[str]:
        """Keep capacity, disk, critical pressure and ownership faults immediate."""
        reasons = _system_reasons(snapshot, self.policy, SEVERE_HEADROOM_PERCENT, wall_now)
        reasons = [reason for reason in reasons
                   if reason not in {COMPRESSOR_REASON, WARNING_PRESSURE_REASON}]
        if snapshot.physical_bytes != self.baseline.physical_bytes:
            reasons.append('measured physical capacity changed after admission')
        reasons += owned_reasons(snapshot, self.policy)
        return reasons

    def _conditions(self, snapshot: ResourceSnapshot, now: float, valid: bool) -> tuple:
        """Reset each recovered condition and never bridge an unobserved long gap."""
        active = {'kernel-warning': snapshot.kernel_pressure_level == 2,
                  'low-headroom': snapshot.free_percent < self.policy.stop_free_percent}
        recovered, reset = [], []
        gap = self.last_monotonic is not None and now - self.last_monotonic > MAXIMUM_READING_GAP_SECONDS
        if valid:
            recovered, reset = self._advance_conditions(active, now, gap)
        observed_now = now if valid or self.last_monotonic is None else self.last_monotonic
        return self._states(observed_now), recovered, reset

    def _states(self, now: float) -> dict:
        """Report windows without mutating them for failed observations."""
        return {key: {'active': window is not None, 'readings': window['readings'] if window else 0,
                      'ageSeconds': max(0.0, now - window['first']) if window else 0.0}
                for key, window in self.windows.items()}

    def _advance_conditions(self, active: dict, now: float, gap: bool) -> tuple:
        """Record recovery separately from a reset caused by missing duration evidence."""
        recovered, reset = [], []
        for key, present in active.items():
            window = self.windows[key]
            if window and not present:
                recovered.append(key)
            if window and present and gap:
                reset.append(key)
            self.windows[key] = _next_window(window, present, now, gap)
        return recovered, reset

    def evaluate(self, snapshot: ResourceSnapshot, monotonic_now: float | None = None,
                 wall_now: float | None = None) -> dict:
        """Return recorded decisions; the existing owner alone signals and cleans up."""
        monotonic_now = time.monotonic() if monotonic_now is None else monotonic_now
        wall_now = time.time() if wall_now is None else wall_now
        invalid = _measurement_reasons(snapshot) + _measurement_reasons(self.baseline)
        if invalid:
            return self._invalid_evaluation(invalid)
        clock_reasons = self._clock_reasons(snapshot, monotonic_now, wall_now)
        safe_now = monotonic_now if _finite_time(monotonic_now) else self.last_monotonic or 0.0
        reasons = list(clock_reasons)
        if _finite_time(wall_now) and _finite_time(snapshot.measured_at):
            reasons += self._hard_reasons(snapshot, wall_now)
        states, recovered, reset = self._conditions(snapshot, safe_now, not reasons)
        warnings = _warnings(snapshot, self.baseline, self.policy)
        for key, state in states.items():
            if state['readings'] >= PRESSURE_READINGS and state['ageSeconds'] >= PRESSURE_SECONDS:
                reasons.append(f'sustained {key} across at least three readings and ten seconds')
            elif state['active']:
                warnings.append(f'{key} observed; awaiting sustained pressure evidence')
        if not reasons:
            self.last_measured_at, self.last_monotonic = snapshot.measured_at, monotonic_now
        return {'mode': MODE, 'stopReasons': tuple(dict.fromkeys(reasons)), 'warnings': tuple(warnings),
                'conditions': states, 'recoveries': recovered, 'gapsReset': reset,
                'budgets': asdict(self.policy), 'memoryContext': _context(snapshot, self.baseline),
                **_guard_rules()}

    def _invalid_evaluation(self, reasons: list[str]) -> dict:
        """An invalid reading never contributes to duration or claims healthy context."""
        return {'mode': MODE, 'stopReasons': tuple(dict.fromkeys(reasons)), 'warnings': (),
                'conditions': self._states(self.last_monotonic or 0.0), 'recoveries': [], 'gapsReset': [],
                'budgets': asdict(self.policy), 'memoryContext': {'status': 'invalid-telemetry'},
                **_guard_rules()}


def _next_window(window: dict | None, present: bool, now: float, gap: bool) -> dict | None:
    """Advance one valid observation, resetting absent or discontinuous conditions."""
    if not present:
        return None
    if window is None or gap:
        return {'first': now, 'readings': 1}
    return {'first': window['first'], 'readings': window['readings'] + 1}
