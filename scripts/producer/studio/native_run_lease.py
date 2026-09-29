"""Keep a native owner's durable lease rows to its recorded processes, within one bound.

A long owner sees thousands of short processes exit. After each verified sample the
owner forgets identities that sample found exited or reassigned (never the root) and
asks its lease to drop their rows; the lease drops a row only once its own process
table read shows it absent. At most ``MAX_RECORDED_IDENTITIES`` identities stay
recorded at once. Exceeding that fails the owner as ``process-registry-overflow``; a
verified cleanup still completes the lease, because that cleanup already proved every
registry identity absent, including any the bounded lease could not hold.
"""
from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from native_render_processes import ResourceMeasurementError
from native_work_lease import ProcessRegistryOverflow

if TYPE_CHECKING:
    from native_render_resources import ResourceSnapshot
    from studio.native_run import NativeRun

OVERFLOW = 'process-registry-overflow'


def lease_rows(owner: NativeRun) -> list[dict]:
    """The registry's current identities in the lease's row shape."""
    return [{'pid': row.pid, 'started': row.started, 'pgid': row.pgid}
            for row in owner.registry.known.values()]


def row_key(row: dict) -> tuple:
    """One row's exact identity."""
    return row['pid'], row['started'], row['pgid']


def record_lease_processes(owner: NativeRun) -> None:
    """Durably add newly recorded identities; name an overflow before it aborts the owner."""
    if owner.registry is None or owner.lease is None:
        return
    rows = lease_rows(owner)
    if rows == owner.lease_identities:
        return
    try:
        owner.lease.record_processes(rows)
    except ProcessRegistryOverflow:
        owner.result['failureCategory'] = OVERFLOW
        raise
    owner.lease_identities = rows
    owner.lease_recorded.update((row_key(row), row) for row in rows)


def retire_exited(owner: NativeRun, snapshot: ResourceSnapshot) -> None:
    """After a verified sample, forget exited identities and retire their lease rows."""
    exited = set(snapshot.missing_registered_pids) | set(snapshot.recycled_registered_pids)
    exited -= set(snapshot.owned_pids)
    counts = owner.result.setdefault('identityRetirement', {
        'registry': 0, 'lease': 0, 'leaseDeferred': 0, 'lastDeferral': None})
    if exited:
        counts['registry'] += len(owner.registry.retire(exited))
    if owner.lease is None:
        return
    current = {row_key(row) for row in lease_rows(owner)}
    stale = [row for key, row in owner.lease_recorded.items() if key not in current]
    if not stale:
        return
    try:
        live = {row_key(row) for row in owner.lease.retire_processes(stale)}
    except (subprocess.SubprocessError, ResourceMeasurementError) as error:
        counts['leaseDeferred'] += 1  # Rows stay recorded; the next verified sample retries.
        counts['lastDeferral'] = f'{type(error).__name__}: {error}'
        return
    for row in stale:
        if row_key(row) not in live:
            del owner.lease_recorded[row_key(row)]
            counts['lease'] += 1


def _unverified(owner: NativeRun, reason: str) -> None:
    """Record why the lease was not completed; the member stays quarantined when one exists."""
    owner.result.update(leaseCleanupVerified=False, leaseCleanupReason=reason)


def release_lease(owner: NativeRun) -> None:
    """Complete the lease only after verified cleanup, even when the bound overflowed.

    Every receipt records leaseCleanupVerified: True, or False with leaseCleanupReason (no
    member admitted, owned cleanup unverified, or the exception completion raised).
    """
    if owner.lease is None:
        _unverified(owner, 'no pool member was admitted')
        return
    try:
        try:
            record_lease_processes(owner)
        except ProcessRegistryOverflow as error:
            owner.result['leaseRecordOverflowAtRelease'] = str(error)
        if owner.result.get('cleanup', {}).get('verified'):
            owner.lease.complete()
            owner.result['leaseCleanupVerified'] = True
        else:
            _unverified(owner, 'owned-process cleanup was not verified; the member stays quarantined')
    except Exception as error:
        _unverified(owner, f'{type(error).__name__}: {error}')
        owner.abort_reason = owner.abort_reason or f'Heavy-work cleanup fence: {error}'
    finally:
        owner.lease.close()
