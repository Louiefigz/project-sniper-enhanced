"""Run-level status: AI and media activity, CPU, memory, disk reservations and unresolved cleanup.

- AI: the authority's task summary (``production.lifecycle.task_summary``: counts, slots,
  reservations and charges, governance and what it cannot enforce, overdue, ready and unsettled
  work) and the batch's media dispatcher.
- Media: this batch's running launches by route and media tasks by state (authority), and the
  host-wide native pool's members and waiting tickets by class (``native_budget_pool``: liveness
  from a non-blocking shared probe of each liveness lock, exactly as admission classifies it; no
  ledger lock, no writes). The pool is shared with other work.
- CPU and memory pressure: E1 evidence in this batch's owner receipts (``<attempt>/*.render.json``:
  ``cpu`` summaries and the latest resource snapshot of running owners). CPU seconds are work
  summed across owners, lower bounds, never elapsed time; nothing measured is unknown.
- Memory headroom and disk reservations: the pool's reservations against its aggregate budget,
  charged by the admission's own rule (an unreadable record is charged maximally).
- Cleanup: unresolved or unsettled tasks, launches still running after their output was handed
  off, a drain in progress and quarantined pool members (each named with its
  ``native_work_recovery.py <nonce>`` command, as admission names them).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from native_render_resources import KERNEL_PRESSURE_NAMES
from native_render_cpu import SCHEMA as CPU_SCHEMA
from studio.native_budget_pool import pool_snapshot
from studio.production.lifecycle import task_summary
from studio.production.task_schema import LIVE, is_ai
from studio.production.tasks import tasks_of

MAX_OWNER_RECEIPTS = 32           # per attempt directory
MAX_RECEIPT_BYTES = 8 * 1024 * 1024
CPU_SCOPE = ('Sampled owned-process CPU from each owner receipt (E1): lower bounds, summed as work across '
             'owners, never elapsed time; host busy fractions are per owner and are not added.')


def _pool() -> dict:
    """The pool snapshot, or the reason it could not be read now."""
    try:
        return pool_snapshot()
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        return {'status': 'unavailable', 'reason': f'{type(error).__name__}: {error}'[:400]}


def _receipt(file: Path) -> dict | None:
    """One bounded owner receipt, or None when it cannot be read as an object."""
    with file.open('rb') as handle:
        data = handle.read(MAX_RECEIPT_BYTES + 1)
    value = json.loads(data) if len(data) <= MAX_RECEIPT_BYTES else None
    return value if isinstance(value, dict) else None


def _attempt_receipts(clip_id: str, attempt: dict) -> tuple[list[dict], list[str]]:
    """The readable owner receipts in one launch's directory, and the files that could not be read."""
    rows, problems = [], []
    for file in sorted(Path(attempt['output']).glob('*.render.json'))[:MAX_OWNER_RECEIPTS]:
        try:
            value = _receipt(file)
        except (OSError, ValueError):
            value = None
        if value is None:
            problems.append(str(file))
            continue
        rows.append({'clipId': clip_id, 'attemptId': attempt['id'], 'file': str(file),
                     'running': attempt['status'] == 'running', 'cpu': value.get('cpu'),
                     'snapshot': value.get('latestResourceSnapshot')})
    return rows, problems


def owner_receipts(record: dict) -> tuple[list[dict], list[str]]:
    """Every readable owner receipt of this batch's launches, and the files that could not be read."""
    rows, problems = [], []
    for clip_id, clip in record['clips'].items():
        for attempt in clip['attempts']:
            found, unreadable = _attempt_receipts(clip_id, attempt)
            rows.extend(found)
            problems.extend(unreadable)
    return rows, problems


def cpu(receipts: list[dict]) -> dict:
    """Owned CPU work and host busy fractions, only where an owner measured them."""
    measured = [row['cpu'] for row in receipts
                if isinstance(row['cpu'], dict) and row['cpu'].get('schema') == CPU_SCHEMA]
    if not measured:
        return {'status': 'unknown', 'reason': 'no owner receipt of this batch carries a CPU summary',
                'ownerReceipts': len(receipts)}
    busy = [row['peakHostBusyFraction'] for row in measured if row.get('peakHostBusyFraction') is not None]
    return {'status': 'measured', 'owners': len(measured), 'ownersWithoutCpu': len(receipts) - len(measured),
            'observedOwnedCpuSeconds': round(sum(row.get('observedOwnedCpuSeconds') or 0.0 for row in measured), 3),
            'measuredOwnedCpuSeconds': round(sum(row.get('measuredOwnedCpuSeconds') or 0.0 for row in measured), 3),
            'peakHostBusyFraction': max(busy, default=None), 'scope': CPU_SCOPE}


def memory(receipts: list[dict], pool: dict) -> dict:
    """The latest sampled pressure of a running owner, and the pool's reservation headroom."""
    samples = [row for row in receipts if row['running'] and isinstance(row['snapshot'], dict)
               and row['snapshot'].get('measured_at') is not None]
    latest = max(samples, key=lambda row: row['snapshot']['measured_at'], default=None)
    pressure = {'status': 'unknown', 'reason': 'no running owner of this batch has sampled memory'}
    if latest is not None:
        snapshot = latest['snapshot']
        pressure = {'status': 'sampled', 'measuredAtEpoch': snapshot['measured_at'], 'attemptId': latest['attemptId'],
                    'kernelPressure': KERNEL_PRESSURE_NAMES.get(snapshot.get('kernel_pressure_level'), 'unknown'),
                    'unusedPhysicalBytes': snapshot.get('unused_physical_bytes'),
                    'freePercent': snapshot.get('free_percent')}
    return {'pressure': pressure, 'reservations': pool.get('memory') or {'status': pool['status']}}


def media(record: dict, pool: dict) -> dict:
    """This batch's launches and media tasks, and the host pool by class."""
    attempts = [row for clip in record['clips'].values() for row in clip['attempts']]
    running: dict[str, int] = {}
    for row in attempts:
        if row['status'] == 'running':
            running[row['route']] = running.get(row['route'], 0) + 1
    tasks = [task for task in tasks_of(record).values() if task['kind'] == 'media']
    states = {state: sum(task['state'] == state for task in tasks) for state in ('ready', 'claimed', 'running')}
    return {'batchRunningLaunchesByRoute': running, 'batchMediaTasks': states,
            'hostPool': {key: pool[key] for key in ('status', 'consistency', 'byClass', 'legacyMarker', 'staleTickets',
                                                   'liveWithoutProcessTableMatch', 'reason') if key in pool}}


def unresolved(record: dict, summary: dict, pool: dict) -> dict:
    """Everything that still holds a slot, a reservation or a process after its work should have ended."""
    handed = {clip_id for clip_id, clip in record['clips'].items() if clip['state'] == 'handed-off'}
    late = [row['id'] for clip_id in handed for row in record['clips'][clip_id]['attempts']
            if row['status'] == 'running']
    cancelling = sorted(task['id'] for task in tasks_of(record).values() if task['state'] == 'cancel-requested')
    return {'unresolvedTasks': summary['unresolved'], 'unsettledTasks': summary['unsettled'],
            'cancelRequested': cancelling, 'launchesRunningAfterHandoff': late, 'drain': summary['drain'],
            'quarantinedPoolMembers': pool.get('quarantinedMembers'),
            'settled': not (summary['unresolved'] or cancelling or late)}


def run_status(record: dict, elapsed: float, dispatcher: dict | None = None) -> dict:
    """The run-level status section; ``ai`` is the authority's task summary (it replaces a separate one)."""
    summary = task_summary(record, elapsed)
    pool = _pool()
    receipts, problems = owner_receipts(record)
    ai = [task for task in tasks_of(record).values() if is_ai(task)]
    return {'ai': {**{key: value for key, value in summary['ai'].items() if key != 'usage'},
                   'liveAiTasks': sum(task['state'] in LIVE for task in ai),
                   'readyAiTasks': sum(task['state'] == 'ready' for task in ai), 'readyTasks': summary['ready'],
                   'taskCounts': summary['counts'], 'governance': summary['governance'],
                   'limitations': summary['limitations'], 'overdue': summary['overdue']},
            'dispatcher': dispatcher, 'media': media(record, pool), 'cpu': cpu(receipts),
            'memory': memory(receipts, pool),
            'disk': {'reservedBytesByDevice': pool.get('diskReservedBytesByDevice'), 'poolStatus': pool['status']},
            'cleanup': unresolved(record, summary, pool), 'unreadableOwnerReceipts': problems}
