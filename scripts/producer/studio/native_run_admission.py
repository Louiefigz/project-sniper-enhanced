"""Bounded capacity waiting without launching a child or weakening host gates."""
from __future__ import annotations

import json
import time
from dataclasses import asdict
from typing import TYPE_CHECKING

from native_render_processes import ProcessRequest
from native_render_resources import admission_reasons
from native_render_policy import AdaptiveMemoryGuard, adaptive_admission_reasons, capacity_derivation
from native_work_lease import NativeWorkLease, NativeWorkBusy
from studio.native_run_config import policy_for_baseline

if TYPE_CHECKING:
    from studio.native_run import NativeRun


def wait_capacity(owner: NativeRun, reasons: tuple, until: float) -> None:
    """Persist the real waiting state, with cancellation and a finite wait budget."""
    if owner.abort_reason:
        raise RuntimeError(owner.abort_reason)
    if time.monotonic() >= until:
        raise RuntimeError('Admission refused: ' + '; '.join(reasons))
    owner.result.update(status='waiting-for-capacity', admissionReasons=reasons)
    owner.persist()
    print(json.dumps({'status': 'waiting-for-capacity', 'reasons': reasons,
                      'childLaunched': False}), flush=True)
    time.sleep(min(2, max(0, until - time.monotonic())))


def acquire_capacity(owner: NativeRun) -> None:
    """Wait only for live contention/host pressure; never reclaim unverified cleanup."""
    until = min(owner.started + owner.deadline,
                time.monotonic() + owner.settings.capacity_wait_seconds)
    while owner.lease is None:
        try:
            owner.lease = NativeWorkLease.acquire('heavy', str(owner.project))
        except NativeWorkBusy as error:
            if 'already active' not in str(error):
                raise
            wait_capacity(owner, (str(error),), until)
    while True:
        owner.baseline = owner.measure_resources(ProcessRequest())
        owner.policy = policy_for_baseline(owner.settings, owner.baseline)
        owner.result.update(baseline=asdict(owner.baseline), policy=asdict(owner.policy))
        if owner.settings.policy is None:
            owner.resource_guard = AdaptiveMemoryGuard(owner.baseline, owner.policy)
            owner.result['resourcePolicyDerivation'] = capacity_derivation(owner.baseline, owner.policy)
        admission = adaptive_admission_reasons if owner.resource_guard else admission_reasons
        reasons = admission(owner.baseline, owner.policy)
        if owner.settings.unused_ram_advisory:
            reasons = tuple(value for value in reasons if value != 'unused physical RAM is below the reserved host margin')
        owner.result['admissionReasons'] = reasons
        owner.persist()
        if not reasons:
            owner.result['status'] = 'preparing'
            return
        if any('disk' in value for value in reasons):
            raise RuntimeError('Admission refused: ' + '; '.join(reasons))
        wait_capacity(owner, reasons, until)
