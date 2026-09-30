"""Bind scheduler observations and live grants to the existing production authority.

Credit is bound to evidence (P1 Step B4, C11): only the registered supervisor commits its own row, a wait names
its pool ticket and the live occupants it waits behind (``PoolEvidence``, from ``native_work_pool_credit``), and
every ``CHECKPOINT_SECONDS`` of credit one heartbeat becomes a ``capacity-checkpoint`` trail event (at most
``MAX_CHECKPOINTS`` per Short), so ``queue_audit`` can bound the recorded total by the trail. The threat model is
the unkeyed one of ``approvals``: a writer who rewrites the record and the trail together is not detected.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
import subprocess

from studio.production import queue_clock
from studio.production.queue_clock_schema import MAX_CHECKPOINTS, MAX_ORPHAN_ROWS, number

CHECKPOINT_SECONDS = 300.0


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
    """Read only settled credit since this allocation was created."""
    ref = grant.get('capacityCredit')
    if ref is None:
        return 0.0
    validate_reference(ref)
    from studio.native_budget_store import read_batch
    record = read_batch(Path(ref['authority']), ref['batchId'])
    clip = record['clips'][ref['clipId']]
    if not queue_clock.enabled(clip) or record['status'] != 'active':
        return 0.0
    return max(0.0, queue_clock.excluded(clip) - ref['atGrant'])


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
    ``CHECKPOINT_SECONDS`` past its last checkpoint (``capacity-checkpoint``, while fewer than ``MAX_CHECKPOINTS``).
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
    before = queue_clock.excluded(clip)
    after = queue_clock.observe_worker(record, context, observation, elapsed)
    event = 'capacity-settled' if state == 'finished' else 'capacity-heartbeat' if heartbeat else 'capacity-observed'
    if event == 'capacity-heartbeat' and _checkpoint_due(clip, after, elapsed):
        event = 'capacity-checkpoint'
    session.commit(record, {'event': event, 'clipId': clip_id, 'worker': context['workerId'], 'state': state,
                            'elapsed': elapsed, 'excludedSeconds': after, 'creditedSeconds': after - before,
                            'resource': observation['resource'], 'evidence': observation['evidence'],
                            'recoveredWorkers': removed, 'orphanedWorkers': orphaned})
    return after


def _checkpoint_due(clip: dict, after: float, elapsed: float) -> bool:
    """Whether this heartbeat is a trail checkpoint (v2 clocks only); if so, the checkpoint row is advanced."""
    if not queue_clock.writable(clip):
        return False
    row = clip['capacityClock']['checkpoint']
    if after - row['excludedSeconds'] < CHECKPOINT_SECONDS or row['count'] >= MAX_CHECKPOINTS:
        return False
    row.update(excludedSeconds=after, elapsed=elapsed, count=row['count'] + 1)
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


@dataclass(frozen=True)
class Recovery:
    """Other owners' rows seen before the lock: ``ended`` ones (proved gone) and ``orphaned`` ones (C7: a working
    row of this boot whose own supervisor is gone, with no finished receipt; its children may still run)."""

    ended: dict
    orphaned: dict


def recovery_evidence(record: dict, context: dict) -> Recovery:
    """Observe possible departed workers before taking the authority lock (an unreadable table proves nothing)."""
    from studio.native_budget_clock import boot_id
    from studio.native_budget_launch import _process_table
    from native_render_processes import ResourceMeasurementError
    clip = record['clips'][context['clipId']]
    candidates = {key: row for key, row in clip.get('capacityClock', {}).get('workers', {}).items()
                  if key != context['workerId']}
    if not candidates:
        return Recovery({}, {})
    try:
        table = _process_table()
    except (OSError, subprocess.SubprocessError, ResourceMeasurementError):
        table = None
    observed = boot_id(), table
    ended = {key: row for key, row in candidates.items() if _recoverable((key, row), clip, observed)}
    return Recovery(ended, {key: row for key, row in candidates.items()
                            if key not in ended and _orphaned(row, observed)})


def _recoverable(worker: tuple, clip: dict, observed: tuple) -> bool:
    """A reboot, completed cleanup, or a dead prelaunch waiter proves an owner ended.

    A waiting row is written only before pool admission (``native_run_admission.acquire_capacity``: ``join_queue``
    precedes ``lease.mark_launching``), so its owner launched no child: once its supervisor is gone, a surviving
    member of its process group cannot be its work (P3), and the group is not checked.
    """
    key, row = worker
    boot, table = observed
    if row.get('boot') and row['boot'] != boot:
        return True
    if _finished_receipt(key):
        return True
    if row['state'] != 'waiting' or table is None:
        return False  # A dead working supervisor alone cannot prove detached-child cleanup (it is orphaned).
    identity = row.get('supervisor')
    if identity is None:
        attempt = next((item for item in clip['attempts'] if item['id'] == row['attemptId']), None)
        identity = attempt.get('supervisor') if attempt else None
    if identity is None:
        return False
    from native_render_processes import ProcessIdentity, identity_matches
    return not identity_matches(table, ProcessIdentity(**identity))


def _orphaned(row: dict, observed: tuple) -> bool:
    """A working row of this boot, the table readable, whose recorded supervisor no longer runs (PID, start and group
    compared, so a recycled PID is not that supervisor). The caller has already ruled out an ended row."""
    boot, table = observed
    identity = row.get('supervisor')
    if row['state'] != 'working' or table is None or identity is None or row.get('boot') != boot:
        return False
    from native_render_processes import ProcessIdentity, identity_matches
    return not identity_matches(table, ProcessIdentity(**identity))


def _finished_receipt(path: str) -> bool:
    """Only the actual terminal owner receipt with proved cleanup retires a working row."""
    from cut_preview_io import bound_json
    try:
        value = bound_json(Path(path), maximum=4 * 1024 ** 2)
    except (OSError, ValueError, TypeError, RuntimeError):
        return False
    if type(value) is not dict or not value.get('completedAt') or type(value.get('cleanup')) is not dict:
        return False
    cleanup = value['cleanup']
    return cleanup.get('verified') is True and (value.get('leaseCleanupVerified') is True
                                               or cleanup.get('childNeverLaunched') is True)


def recover_workers(record: dict, clip_id: str, evidence: Recovery, elapsed: float) -> tuple[list[str], list[str]]:
    """Remove unchanged proved-ended rows; on a v2 clock move unchanged orphaned rows to ``orphans`` (C7).

    Either way the pending interval becomes uncertain: every unconfirmed interval stays counted. An orphan no longer
    counts as work or toward the owner cap, and its identity stays visible (``orphans.recent``, the last 16).
    Returns the (removed, orphaned) owner keys.
    """
    clock = record['clips'][clip_id].get('capacityClock')
    if clock is None:
        return [], []
    removed = [key for key, row in evidence.ended.items() if clock['workers'].get(key) == row]
    orphaned = [key for key, row in evidence.orphaned.items()
                if queue_clock.writable(record['clips'][clip_id]) and clock['workers'].get(key) == row]
    if removed or orphaned:
        clock['uncertainSeconds'] += clock['pendingSeconds']
        clock['pendingSeconds'] = 0.0
    rows = [{**clock['workers'][key], 'orphanedElapsed': elapsed} for key in orphaned]
    for key in removed + orphaned:
        del clock['workers'][key]
    if orphaned:
        orphans = clock['orphans']
        orphans.update(count=orphans['count'] + len(orphaned), recent=(orphans['recent'] + rows)[-MAX_ORPHAN_ROWS:])
    return removed, orphaned
