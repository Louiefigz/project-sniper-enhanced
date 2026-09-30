"""Owner recovery before a capacity observation (P1 Step B5, M-048; C7, P3, P6), split from ``queue_authority``.

Before the authority lock, ``recovery_evidence`` reads the process table once and sorts the Short's other owner rows
into ``ended`` ones (a reboot, a finished receipt with proved cleanup, or a dead prelaunch waiter) and ``orphaned``
ones (a working row of this boot whose supervisor is gone); inside the lock, ``recover_workers`` removes or moves
only rows still unchanged. ``queue_authority`` re-exports ``Recovery``, ``recovery_evidence`` and
``recover_workers``.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from studio.production import queue_clock
from studio.production.queue_clock_schema import MAX_ORPHAN_ROWS


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
