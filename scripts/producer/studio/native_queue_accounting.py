"""Bridge supervised owners to durable, evidence-backed Short queue accounting.

A pool refusal explicitly classified as live heavy-slot contention is the only
excluded wait, and it earns credit only with its pool evidence (``pool_evidence``:
its ticket and live occupants, C11). Memory pressure, disk pressure, inspection
failures, cleanup and all running work count normally. Missing observation
heartbeats never earn credit. Longs and historical batches keep their original
wall-clock behavior.
"""
from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from studio.production.queue_authority import (
    NO_EVIDENCE, PoolEvidence, owner_context, record_observation, supporting_contexts,
)
from studio.production.queue_clock_schema import MAX_OCCUPANTS, WAIT_CLASSES

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


def pool_evidence(error: Exception | None) -> PoolEvidence:
    """The pool's evidence for this observation (C11): the refusal's ticket, live occupants and wait class
    (``native_work_pool_credit``, carried as ``capacity_evidence``); none on admission, since a working row needs no
    ticket. A value the clock's row cannot hold (``queue_clock_schema``) is dropped, so such a wait earns
    nothing and the record stays valid."""
    found = getattr(error, 'capacity_evidence', None) if error is not None else None
    if type(found) is not dict:
        return NO_EVIDENCE
    ticket, occupants, wait_class = found.get('ticket'), found.get('occupants'), found.get('waitClass')
    names = tuple(occupants) if type(occupants) is list and len(occupants) <= MAX_OCCUPANTS \
        and all(type(name) is str and len(name) <= 64 for name in occupants) else ()
    return PoolEvidence(ticket if type(ticket) is int and ticket >= 0 else None, names,
                        wait_class if wait_class in WAIT_CLASSES else None)


def pool_observation(owner: NativeRun, error: Exception | None) -> float:
    """Settle a verified queue interval, then record admission or current contention with its pool evidence."""
    contexts = [context for context in [owner.capacity_context, *getattr(owner, 'supporting_contexts', [])]
                if context is not None]
    if not contexts:
        return 0.0
    waiting = bool(error and getattr(error, 'capacity_only', False))
    # An unknown or non-capacity refusal is one 'unverified' observation (C13): it confirms no preceding pending
    # interval (that becomes uncertain), and its repeats are heartbeats, so they add no trail rows.
    state = 'working' if error is None else 'waiting' if waiting else 'unverified'
    evidence = json.dumps(getattr(error, 'capacity_evidence', {}), sort_keys=True) if error else 'admitted'
    pool = pool_evidence(error)
    before = owner.capacity_credit
    for context in contexts:
        credit = record_observation(context, state, ('heavy-pool', evidence[:2048]), pool)
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
