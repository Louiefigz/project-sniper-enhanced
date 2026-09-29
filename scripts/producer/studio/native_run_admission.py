"""Bounded capacity waiting without launching a child or weakening host gates.

Each baseline also records host CPU evidence (cpuAtAdmission) and each poll records the deferral hook's outcome
(cpuLaunchDeferral); the hook receives no qualified CPU profile, so CPU never holds a launch
(native_render_deferral.py). A CPU hold, were one qualified, is counted in cpuDeferralSeconds, not
pressureWaitSeconds. Under an owner that journals its work, the queue and pressure phases are also child
timing spans (diagnostics only). Disk refusals at admission say "Disk admission refused".
"""
from __future__ import annotations

import json
import subprocess
import time
from dataclasses import asdict
from typing import TYPE_CHECKING

from native_render_processes import ProcessRequest
from native_render_resources import admission_reasons
from native_render_policy import AdaptiveMemoryGuard, adaptive_admission_reasons, capacity_derivation
from native_render_deferral import MEMORY_WAITING, DeferralRequest, launch_deferral
from native_work_lease import NativeWorkLease, NativeWorkBusy
from native_work_pool import PoolRequest
from native_work_pool_policy import reserved_policy
from stage_timing import child_span
from studio.native_run_config import policy_for_baseline
from studio.native_run_lifecycle import require_production_time
from studio.native_run_disk import disk_request_path, pool_refusal_category

if TYPE_CHECKING:
    from studio.native_run import NativeRun


def wait_capacity(owner: NativeRun, reasons: tuple, until: float) -> None:
    """Persist the real waiting state, with cancellation and a finite wait budget."""
    require_production_time(owner)
    if owner.abort_reason:
        raise RuntimeError(owner.abort_reason)
    if time.monotonic() >= until:
        raise RuntimeError('Admission refused: ' + '; '.join(reasons))
    owner.result.update(status='waiting-for-capacity', admissionReasons=reasons)
    owner.persist()
    print(json.dumps({'status': 'waiting-for-capacity', 'reasons': reasons,
                      'childLaunched': False}), flush=True)
    time.sleep(min(2, max(0, until - time.monotonic())))


def _baseline_policy(owner: NativeRun) -> tuple:
    """Measure, derive the policy, bound it by the reservation and return the memory admission reasons."""
    owner.baseline = owner.measure_resources(ProcessRequest())
    owner.result['cpuAtAdmission'] = owner.cpu.observe(owner.baseline)
    derived = policy_for_baseline(owner.settings, owner.baseline)
    owner.policy = reserved_policy(derived, owner.lease.reservation_bytes)
    owner.result.update(baseline=asdict(owner.baseline), policy=asdict(owner.policy),
                        poolReservationBound={'reservationBytes': owner.lease.reservation_bytes,
                                              'derivedOwnedGib': derived.maximum_owned_gib,
                                              'boundOwnedGib': owner.policy.maximum_owned_gib,
                                              'boundProcessGib': owner.policy.maximum_process_gib})
    if owner.settings.policy is None:
        owner.resource_guard = AdaptiveMemoryGuard(owner.baseline, owner.policy)
        owner.result['resourcePolicyDerivation'] = capacity_derivation(owner.baseline, owner.policy)
    admission = adaptive_admission_reasons if owner.resource_guard else admission_reasons
    reasons = admission(owner.baseline, owner.policy)
    if owner.settings.unused_ram_advisory:
        reasons = tuple(value for value in reasons if value != 'unused physical RAM is below the reserved host margin')
    return reasons


def _cpu_deferral(owner: NativeRun, memory: tuple, clock: tuple) -> tuple:
    """Record this poll's deferral outcome; only memory-admitted launches reach the hook.

    No measured profile has shown a throughput or deadline benefit from CPU deferral, so
    the hook receives None and always launches (E detail, row 2).
    """
    if memory:
        owner.result['cpuLaunchDeferral'] = dict(MEMORY_WAITING)
        return ()
    held, until = clock
    request = DeferralRequest(owner.settings.lane, owner.result['pool'], owner.result['cpuAtAdmission'],
                              held, until - time.monotonic())
    owner.result['cpuLaunchDeferral'] = launch_deferral(request, None)
    return owner.result['cpuLaunchDeferral']['reasons']


def _await_pressure(owner: NativeRun, until: float) -> None:
    """Measure the host and wait only for pressure, bounded by the same admission clock."""
    pressure_started, held = time.monotonic(), 0.0
    while True:
        require_production_time(owner)
        memory = _baseline_policy(owner)
        held_reasons = _cpu_deferral(owner, memory, (held, until))  # Called every poll: no stale record.
        reasons = memory or held_reasons
        owner.result['admissionReasons'] = reasons
        owner.persist()
        if not reasons:
            owner.result.update(status='preparing', cpuDeferralSeconds=held,
                                pressureWaitSeconds=time.monotonic() - pressure_started - held)
            owner.lease.mark_launching()
            return
        if any('disk' in value for value in reasons):
            raise RuntimeError('Disk admission refused: ' + '; '.join(reasons))
        began = time.monotonic()
        wait_capacity(owner, reasons, until)
        held += 0.0 if memory else time.monotonic() - began


def acquire_capacity(owner: NativeRun) -> None:
    """Wait only for live contention/host pressure; never reclaim unverified cleanup."""
    until = min(owner.started + owner.deadline,
                time.monotonic() + owner.settings.capacity_wait_seconds)
    remaining = require_production_time(owner)
    if remaining is not None:
        until = min(until, time.monotonic() + remaining)
    with child_span('native_queue_admission', {'activity': 'native-queue-wait'}):
        join_queue(owner, until)
    until = min(owner.started + owner.deadline, time.monotonic() + owner.settings.capacity_wait_seconds)
    admission = owner.lease.admission
    if not isinstance(admission, dict):
        raise RuntimeError('Native pool lease did not report its admission record')
    owner.result['pool'] = admission
    if owner.settings.disk_expansion:
        owner.result['diskExpansion'] = {'status': 'available', 'request': str(disk_request_path(owner.path))}
    with child_span('native_pressure_admission', {'activity': 'pressure-wait'}):
        _await_pressure(owner, until)


def join_queue(owner: NativeRun, until: float) -> None:
    """Keep one existing pool ticket across bounded polls and withdraw on every exit."""
    fixed = owner.settings.policy.maximum_owned_gib if owner.settings.policy else None
    request = PoolRequest(owner.settings.lane, str(owner.project), root=str(owner.root),
                          receipt=str(owner.path), fixed_owned_gib=fixed,
                          disk_bytes=owner.settings.disk_reservation_bytes, declares_launch=True)
    request.until = until
    started = time.monotonic()
    try:
        while owner.lease is None:
            until = attempt_pool_admission(owner, request, until)
    finally:
        request.withdraw()
        waited = time.monotonic() - started
        owner.result['queueSeconds'] = waited  # top-level: the pool qualification evidence reads it (I-E23)
        owner.result['queue'] = {'ticket': request.sequence, 'attempts': request.attempts,
                                 'queueSeconds': waited, 'admitted': owner.lease is not None}


def attempt_pool_admission(owner: NativeRun, request: PoolRequest, until: float) -> float:
    """Temporary occupancy waits; uncertain cleanup and unsupported work fail closed."""
    from studio.native_queue_accounting import pool_observation, waiting_for_capacity
    try:
        owner.lease = _acquire(owner, request, until)
        until += pool_observation(owner, None)
        require_production_time(owner)
    except NativeWorkBusy as error:
        until += pool_observation(owner, error)
        if waiting_for_capacity(owner, error):
            until = max(until, time.monotonic() + 4.0)
        request.until = until
        if 'already active' not in str(error):
            record_pool_refusal(owner, error)
            raise
        wait_capacity(owner, (str(error),), until)
    return until


INSPECTION_ATTEMPTS, INSPECTION_BACKOFF_SECONDS = 3, 0.5
TIMEOUT_CATEGORY = 'host-inspection-timeout'


class HostInspectionTimeout(RuntimeError):
    """The pool's host inspection (sysctl identity, ps identity) kept timing out at admission."""


def _acquire(owner: NativeRun, request: PoolRequest, until: float) -> object:
    """One admission; a timed-out sysctl/ps read is retried up to 3 times with exponential backoff.

    Each backoff is clamped to the admission deadline, and no retry starts after it.
    """
    for attempt in range(INSPECTION_ATTEMPTS):
        remaining = until - time.monotonic()
        if attempt and remaining <= 0:
            break
        if attempt:
            time.sleep(min(INSPECTION_BACKOFF_SECONDS * 2 ** (attempt - 1), remaining))  # 0.5 s, then 1 s
        if attempt and time.monotonic() >= until:
            break
        try:
            return NativeWorkLease.acquire(owner.settings.lane, str(owner.project), request=request)
        except subprocess.TimeoutExpired as error:
            owner.result.setdefault('admissionInspectionTimeouts', []).append(str(error))
    owner.result['failureCategory'] = TIMEOUT_CATEGORY
    timeouts = owner.result['admissionInspectionTimeouts']
    raise HostInspectionTimeout(f'Host inspection timed out {len(timeouts)} times during pool admission: '
                                + timeouts[-1])


def record_pool_refusal(owner: NativeRun, error: NativeWorkBusy) -> None:
    """Keep non-capacity refusal diagnoses without changing their terminal behavior."""
    category = pool_refusal_category(error)
    if category:
        owner.result['failureCategory'] = category
