"""Bind scheduler observations and live grants to the existing production authority."""
from __future__ import annotations

from pathlib import Path
import subprocess

from studio.production import queue_clock
from studio.production.queue_clock_schema import number


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


def record_observation(context: dict | None, state: str, evidence: tuple[str, str]) -> float:
    """Commit one observed transition under the batch lock; never reset an allowance."""
    if context is None:
        return 0.0
    from studio.native_budget_binding import advance_clock
    from studio.native_budget_store import locked_batch, read_batch
    root, batch_id = Path(context['authority']), context['batchId']
    snapshot = read_batch(root, batch_id)
    recovered = recovery_evidence(snapshot, context)
    with locked_batch(root, batch_id) as session:
        record = session.read()
        elapsed = advance_clock(record)
        removed = recover_workers(record, context['clipId'], recovered)
        observation = {'state': state, 'resource': evidence[0], 'evidence': evidence[1]}
        prior = record['clips'][context['clipId']].get('capacityClock', {}).get('workers', {}).get(context['workerId'])
        heartbeat = not removed and prior is not None and prior['state'] == state and prior['resource'] == evidence[0]
        before = queue_clock.excluded(record['clips'][context['clipId']])
        after = queue_clock.observe_worker(record, context, observation, elapsed)
        event = 'capacity-settled' if state == 'finished' else 'capacity-heartbeat' if heartbeat else 'capacity-observed'
        session.commit(record, {'event': event, 'clipId': context['clipId'],
                                'worker': context['workerId'], 'state': state, 'elapsed': elapsed,
                                'excludedSeconds': after, 'creditedSeconds': after - before,
                                'resource': evidence[0], 'evidence': evidence[1], 'recoveredWorkers': removed})
    return after


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


def recovery_evidence(record: dict, context: dict) -> dict:
    """Observe possible departed workers before taking the authority lock."""
    from studio.native_budget_clock import boot_id
    from studio.native_budget_launch import _process_table
    from native_render_processes import ResourceMeasurementError
    clip = record['clips'][context['clipId']]
    candidates = {key: row for key, row in clip.get('capacityClock', {}).get('workers', {}).items()
                  if key != context['workerId']}
    if not candidates:
        return {}
    try:
        table = _process_table()
    except (OSError, subprocess.SubprocessError, ResourceMeasurementError):
        table = None
    boot = boot_id()
    return {key: row for key, row in candidates.items() if _recoverable((key, row), clip, (boot, table))}


def _recoverable(worker: tuple, clip: dict, observed: tuple) -> bool:
    """A reboot, completed cleanup, or a dead prelaunch waiter proves an owner ended."""
    key, row = worker
    boot, table = observed
    if row.get('boot') and row['boot'] != boot:
        return True
    if _finished_receipt(key):
        return True
    if row['state'] != 'waiting' or table is None:
        return False  # A dead working supervisor alone cannot prove detached-child cleanup.
    identity = row.get('supervisor')
    if identity is None:
        attempt = next((item for item in clip['attempts'] if item['id'] == row['attemptId']), None)
        identity = attempt.get('supervisor') if attempt else None
    if identity is None:
        return False
    from native_render_processes import ProcessIdentity, identity_matches
    return not identity_matches(table, ProcessIdentity(**identity)) \
        and not any(item[1] == identity['pgid'] for item in table.values())


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


def recover_workers(record: dict, clip_id: str, evidence: dict) -> list[str]:
    """Remove only unchanged proved-ended rows, retaining every unconfirmed interval as counted."""
    clock = record['clips'][clip_id].get('capacityClock')
    if clock is None:
        return []
    removed = [key for key, row in evidence.items() if clock['workers'].get(key) == row]
    if removed:
        clock['uncertainSeconds'] += clock['pendingSeconds']
        clock['pendingSeconds'] = 0.0
    for key in removed:
        del clock['workers'][key]
    return removed
