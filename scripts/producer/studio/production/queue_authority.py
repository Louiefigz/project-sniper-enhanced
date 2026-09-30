"""Bind scheduler observations and live grants to the existing production authority.

Credit is bound to evidence (P1 Step B4, C11): only the registered supervisor commits its own row, a wait names
its pool ticket and the live occupants it waits behind (``PoolEvidence``, from ``native_work_pool_credit``), and
every ``CHECKPOINT_SECONDS`` of credit one heartbeat becomes a ``capacity-checkpoint`` trail event (at most
``MAX_CHECKPOINTS`` per Short, each only what the audit reads and at most ``CHECKPOINT_EVENT_BYTES``, X183 m5), so
``queue_audit`` can bound the recorded total by the trail. The threat model is the unkeyed one of ``approvals``: a
writer who rewrites the record and the trail together is not detected. Owner recovery before an observation lives in
``queue_recovery`` (split out at P1-RP3; re-exported here).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from studio.production import queue_clock, queue_stall
from studio.production.queue_clock_schema import MAX_CHECKPOINTS, number
from studio.production.queue_recovery import (  # noqa: F401  Recovery is re-exported
    Recovery, recover_workers, recovery_evidence,
)

CHECKPOINT_SECONDS = 300.0
# X183 m5: the largest checkpoint event written. MAX_CHECKPOINTS (32) per Short x BOUNDS['clips'] (32) such events
# fill at most 512 KiB of native_budget_store.TERMINAL_RESERVE_BYTES (test_queue_clock_v2_c, test_trail_reserve_budget).
CHECKPOINT_EVENT_BYTES = 512
# (authority, batch, checkpoint count, clip) whose line was written but whose record was not (X190 n6).
_FAILED_CHECKPOINTS: set = set()


@dataclass(frozen=True)
class PoolEvidence:
    """The pool's evidence for one observation: the request's ticket, the live occupants it waits behind (at most
    ``native_work_pool_credit.MAX_OCCUPANTS`` nonces) and its wait class (``capacity``, ``other`` or None)."""

    ticket: int | None
    occupants: tuple[str, ...]
    wait_class: str | None


NO_EVIDENCE = PoolEvidence(None, (), None)   # an admission or a working owner: nothing to wait behind


def bind_allocation(grant: dict, record: dict, context: dict) -> dict:
    """Attach a credit baseline to a v2 Short grant; leave Long, v1-clock and old grants untouched."""
    clip = record['clips'][context['clipId']]
    if not queue_clock.writable(clip):
        return grant
    return {**grant, 'capacityCredit': {**context, 'policy': queue_clock.POLICY,
                                      'atGrant': queue_clock.excluded(clip)}}


def credit_delta(grant: dict) -> float:
    """Read only settled credit since this allocation was created, without the batch lock (``queue_credit``)."""
    ref = grant.get('capacityCredit')
    if ref is None:
        return 0.0
    validate_reference(ref)
    from studio.production.queue_credit import settled_credit
    return max(0.0, settled_credit(ref) - ref['atGrant'])


def validate_reference(ref: object) -> None:
    """Require an exact reference, without accepting a caller-supplied credit total."""
    from studio.native_budget_store import require_batch_id, require_clip_id
    keys = {'authority', 'batchId', 'clipId', 'policy', 'atGrant'}
    if type(ref) is not dict or set(ref) != keys or ref['policy'] != queue_clock.POLICY \
            or type(ref['authority']) is not str or not Path(ref['authority']).is_absolute() \
            or not number(ref['atGrant']):
        raise ValueError('Malformed capacity-credit allocation reference')
    require_batch_id(ref['batchId'])
    require_clip_id(ref['clipId'])


def owner_context(owner: object) -> dict | None:
    """Resolve the exact grant and attempt for a native owner, never a new batch."""
    ref = (owner.hard_deadline or {}).get('capacityCredit')
    if ref is None:
        return None
    from studio.native_budget_store import read_batch
    record = read_batch(Path(ref['authority']), ref['batchId'])
    clip = record['clips'][ref['clipId']]
    output = str(owner.admission['output'])
    candidates = [row for row in clip['attempts'] if row['status'] == 'running'
                  and Path(output).is_relative_to(Path(row['output']))]
    if len(candidates) > 1:
        raise ValueError('Native owner matches more than one live production attempt')
    attempt = candidates[0]['id'] if candidates else None
    task = next((row['id'] for row in record['production']['tasks'].values()
                 if attempt and row['clipId'] == ref['clipId'] and row['attempt'] == attempt), None)
    return {**ref, **owner_identity(), 'workerId': str(owner.path), 'attemptId': attempt, 'taskId': task}


def owner_identity() -> dict:
    """Bind new accounting workers to the existing exact process/boot identity."""
    from studio.native_budget_launch import own_identity
    from studio.native_budget_clock import boot_id
    return {'supervisor': own_identity(), 'boot': boot_id()}


def record_observation(context: dict | None, state: str, evidence: tuple[str, str],
                       pool: PoolEvidence | None = None) -> float:
    """Commit one observed transition under the batch lock; never reset an allowance.

    Args:
        context: The owner's accounting context (``owner_context``), or None for an unbound owner.
        state: ``working``, ``waiting`` or ``finished``.
        evidence: (resource, evidence text) of the observation.
        pool: The pool's evidence for a wait; None records none, and such a wait earns nothing (C11).

    Raises:
        ValueError: The context names a supervisor other than this process: only the registered supervisor
            commits its capacity observations.
    """
    if context is None:
        return 0.0
    if context.get('supervisor') and context['supervisor']['pid'] != os.getpid():
        raise ValueError('Only the registered supervisor commits its capacity observations')
    from studio.native_budget_store import locked_batch, read_batch
    root, batch_id = Path(context['authority']), context['batchId']
    recovered = recovery_evidence(read_batch(root, batch_id), context)
    pool = pool or NO_EVIDENCE
    observation = {'state': state, 'resource': evidence[0], 'evidence': evidence[1], 'ticket': pool.ticket,
                   'occupants': list(pool.occupants), 'waitClass': pool.wait_class}
    with locked_batch(root, batch_id) as session:
        return _observe_locked(session, context, observation, recovered)


def _observe_locked(session: object, context: dict, observation: dict, recovered: Recovery) -> float:
    """Inside the batch lock: recover ended and orphaned owners, settle this observation, commit it and its event.

    A same-state heartbeat writes no trail event, except the one that brings the Short's credit
    ``CHECKPOINT_SECONDS`` past its last checkpoint (``capacity-checkpoint``, while fewer than ``MAX_CHECKPOINTS``)
    or that names or clears its stall (``capacityState`` in the event, M-050).
    """
    from studio.native_budget_binding import advance_clock
    record = session.read()
    elapsed = advance_clock(record)
    clip_id, state = context['clipId'], observation['state']
    removed, orphaned = recover_workers(record, clip_id, recovered, elapsed)
    clip = record['clips'][clip_id]
    prior = clip.get('capacityClock', {}).get('workers', {}).get(context['workerId'])
    heartbeat = not (removed or orphaned) and prior is not None and prior['state'] == state \
        and prior['resource'] == observation['resource']
    before, stall = queue_clock.excluded(clip), queue_stall.state(clip)
    after = queue_clock.observe_worker(record, context, observation, elapsed)
    named = {'capacityState': queue_stall.state(clip)} if queue_stall.state(clip) != stall else {}   # M-050
    event = 'capacity-settled' if state == 'finished' else 'capacity-heartbeat' if heartbeat and not named \
        else 'capacity-observed'
    # A checkpoint carries only what queue_audit reads (X183 m5); every other event also carries its evidence.
    mark = {'event': 'capacity-checkpoint', 'clipId': clip_id, 'worker': context['workerId'], 'state': state,
            'elapsed': elapsed, 'excludedSeconds': after}
    if event == 'capacity-heartbeat' and _checkpoint_due(clip, mark):
        count = clip['capacityClock']['checkpoint']['count']   # the checkpoint this heartbeat makes due
        _commit_checkpoint(session, record, mark, (context.get('authority'), context.get('batchId'), count))
        return after
    from studio.native_budget_store import TrailFull
    try:
        session.commit(record, {**mark, 'event': event, 'creditedSeconds': after - before,
                                'resource': observation['resource'], 'evidence': observation['evidence'],
                                'recoveredWorkers': removed, 'orphanedWorkers': orphaned, **named})
    except TrailFull:
        if not (heartbeat and named):
            raise
        # X184 (ruling b): at a full trail a stall change is committed record-only, as the heartbeat it was: the
        # record and status still name the state, and the waiting render does not fail (as at 2bda52b5).
        session.commit(record, {**mark, 'event': 'capacity-heartbeat'})
    return after


def _commit_checkpoint(session: object, record: dict, mark: dict, key: tuple) -> None:
    """Commit a checkpoint. One whose record replace failed is on the trail already (its line, then ``commit-failed``),
    so this process never appends it again: a later heartbeat that makes the same checkpoint due commits the record
    alone (X190 n6), and the 32-per-Short bound counts that line."""
    from studio.native_budget_store import BudgetAuthorityError
    key = (*key, mark['clipId'])
    if key in _FAILED_CHECKPOINTS:
        session.commit(record, {**mark, 'event': 'capacity-heartbeat'})
        return
    try:
        session.commit(record, mark)
    except BudgetAuthorityError:
        _FAILED_CHECKPOINTS.add(key)
        raise


def _checkpoint_due(clip: dict, mark: dict) -> bool:
    """Whether this heartbeat is a trail checkpoint (v2 clocks only); if so, the checkpoint row is advanced.

    A checkpoint is written only within ``CHECKPOINT_EVENT_BYTES`` as the store encodes it (X183 m5), so its bound
    holds whatever the owner's path; a longer path leaves the heartbeat unwritten, which only widens
    ``queue_audit``'s window (credit never grows faster than time passes).
    """
    from studio.native_budget_store import canonical
    if not queue_clock.writable(clip):
        return False
    row = clip['capacityClock']['checkpoint']
    if mark['excludedSeconds'] - row['excludedSeconds'] < CHECKPOINT_SECONDS or row['count'] >= MAX_CHECKPOINTS \
            or len(canonical(mark)) > CHECKPOINT_EVENT_BYTES:
        return False
    row.update(excludedSeconds=mark['excludedSeconds'], elapsed=mark['elapsed'], count=row['count'] + 1)
    return True


def supporting_contexts(owner: object, primary: dict | None) -> list[dict]:
    """Account multi-project utility work against every Short it actually serves."""
    from studio.native_budget_owner import served_projects
    from studio.native_budget_registry import owner_binding
    from studio.native_budget_store import default_root, read_batch
    root, contexts = default_root(), []
    identity = {key: primary[key] for key in ('supervisor', 'boot')} if primary else None
    seen = {(primary['batchId'], primary['clipId'])} if primary else set()
    for project in served_projects(owner):
        binding = owner_binding(root, project)
        if not binding or binding['status'] != 'active':
            continue
        key = binding['batchId'], binding['clipId']
        record = read_batch(root, key[0])
        if key in seen or not queue_clock.writable(record['clips'][key[1]]):
            continue
        identity = identity or owner_identity()
        contexts.append({'authority': str(root), 'batchId': key[0], 'clipId': key[1], **identity,
                         'workerId': str(owner.path), 'attemptId': None, 'taskId': None})
        seen.add(key)
    return contexts
