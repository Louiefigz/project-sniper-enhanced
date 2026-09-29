"""Bridge supervised owners to durable, evidence-backed Short queue accounting.

A pool refusal explicitly classified as live heavy-slot contention is the only
excluded wait. Memory pressure, disk pressure, inspection failures, cleanup and
all running work count normally. Missing observation heartbeats never earn
credit. Longs and historical batches keep their original wall-clock behavior.
"""
from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from studio.production.queue_authority import owner_context, record_observation, supporting_contexts

if TYPE_CHECKING:
    from studio.native_run import NativeRun


def start_owner(owner: NativeRun) -> None:
    """Register useful work before this owner starts preparation or pool admission."""
    owner.capacity_context = owner_context(owner)
    owner.capacity_credit = record_observation(owner.capacity_context, 'working', ('native-owner', 'preparation'))
    owner.supporting_contexts = supporting_contexts(owner, owner.capacity_context)
    for context in owner.supporting_contexts:
        record_observation(context, 'working', ('native-owner', 'shared utility preparation'))
    if owner.capacity_context is not None and owner.settings.queue_work_seconds is not None:
        owner.deadline = min(owner.deadline, owner.settings.queue_work_seconds)
        owner.result['runDeadlineSeconds'] = owner.deadline
    owner.capacity_wait_started = None


def pool_observation(owner: NativeRun, error: Exception | None) -> float:
    """Settle a verified queue interval, then record admission or current contention."""
    contexts = [context for context in [owner.capacity_context, *getattr(owner, 'supporting_contexts', [])]
                if context is not None]
    if not contexts:
        return 0.0
    waiting = bool(error and getattr(error, 'capacity_only', False))
    state = 'waiting' if waiting else 'working'
    evidence = json.dumps(getattr(error, 'capacity_evidence', {}), sort_keys=True) if error else 'admitted'
    # Unknown/non-capacity refusals do not confirm the preceding pending interval.
    before = owner.capacity_credit
    for context in contexts:
        if error is not None and not waiting:
            record_observation(context, 'finished', ('heavy-pool', 'unverified wait ended'))
        credit = record_observation(context, state, ('heavy-pool', evidence[:2048]))
        if context is owner.capacity_context:
            owner.capacity_credit = credit
    now = time.monotonic()
    prior = owner.capacity_wait_started
    own_wait = max(0.0, now - prior) if prior is not None and (waiting or error is None) else 0.0
    owner.capacity_wait_started = now if waiting else None
    # Preserve the independent active-work cap; batch credit may be smaller when another task worked.
    if owner.capacity_context is not None:
        owner.deadline += own_wait
    owner.result.update(runDeadlineSeconds=owner.deadline,
                        excludedRenderQueueSeconds=owner.capacity_credit)
    return max(0.0, owner.capacity_credit - before)


def finish_owner(owner: NativeRun) -> None:
    """Remove the owner; termination alone cannot certify its last queue interval."""
    for context in [owner.capacity_context, *getattr(owner, 'supporting_contexts', [])]:
        record_observation(context, 'finished', ('native-owner', 'owner finished'))


def waiting_for_capacity(owner: NativeRun, error: Exception) -> bool:
    """Only a bound Short waiting solely on occupied heavy slots may extend its wait."""
    return owner.capacity_context is not None and getattr(error, 'capacity_only', False) is True
