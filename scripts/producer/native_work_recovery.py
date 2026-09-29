"""Explicit recovery of one native cleanup obligation after verified exit.

Never called by admission. Requires the exact 32-character nonce of either a
quarantined pool member (pool-v1/m-<nonce>.json, any class; see
native_work_pool_recovery.py) or a legacy heavy.active.json written by old lease
code. Legacy recovery keeps the legacy rules (idle legacy lock, absent supervisor
PID, 1-4096 recorded children, all absent) but takes the legacy lock shared, so
running pool members need not stop and no legacy job can start meanwhile.
This command signals nothing and never edits the original failed job receipt.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import time

import native_work_pool_state as state
from headless.durable_files import assert_private_lock_identity, open_private_file, read_private_file
from native_render_processes import ProcessIdentity, identity_matches
from native_work_lease import NativeWorkBusy, NativeWorkLease
import native_work_pool_recovery as pool_recovery


def _read_marker(directory: int, nonce: str) -> tuple[dict, bytes]:
    """Validate the specific legacy obligation without trusting a PID alone."""
    raw = read_private_file(directory, state.LEGACY_MARKER)
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get('schemaVersion') != 1 or value.get('nonce') != nonce:
        raise RuntimeError('Recovery nonce does not match the active obligation')
    supervisor, children = value.get('supervisorPid'), value.get('processes')
    if type(supervisor) is not int or supervisor <= 1:
        raise ValueError('Recovery requires a recorded supervisor PID')
    if not isinstance(children, list) or not 1 <= len(children) <= 4096:
        raise ValueError('Recovery requires a nonempty bounded child registry; unknown launch state is not recoverable here')
    for row in children:
        NativeWorkLease._validate_identity(row)
    return value, raw


def _verify_absence(record: dict) -> dict:
    """Legacy records name only a supervisor PID, so any process with it blocks recovery."""
    table = pool_recovery.process_snapshot()
    if record['supervisorPid'] in table:
        raise NativeWorkBusy('The recorded supervisor PID is still present; recovery refused')
    live = [row for row in record['processes'] if identity_matches(table, ProcessIdentity(**row))]
    if live:
        raise NativeWorkBusy('Recorded native children are still alive; recovery refused')
    reused = [row['pid'] for row in record['processes'] if row['pid'] in table]
    return dict(verifiedAt=time.time(), supervisorAbsent=True, recordedChildrenAbsent=True,
                recordedIdentityCount=len(record['processes']), reusedChildPids=reused)


def _assert_unchanged(namespace: state.Namespace, lock: int, raw: bytes) -> None:
    """Bind recovery to the original namespace, legacy mutex inode and marker bytes."""
    state.assert_namespace(namespace)
    assert_private_lock_identity(namespace.root_fd, state.LEGACY_LOCK, lock)
    if read_private_file(namespace.root_fd, state.LEGACY_MARKER) != raw:
        raise RuntimeError('Active native obligation changed during recovery')


def _recover_legacy_locked(namespace: state.Namespace, lock: int, nonce: str) -> dict:
    """Archive a separate proof before clearing only the selected legacy marker."""
    directory = namespace.root_fd
    record, raw = _read_marker(directory, nonce)
    _assert_unchanged(namespace, lock, raw)
    first = _verify_absence(record)
    archive = f'heavy.recovery-{nonce}.json'
    if os.path.lexists(os.path.join(namespace.root, archive)):
        raise RuntimeError('Recovery evidence already exists; inspect partial recovery instead of overwriting it')
    second = _verify_absence(record)
    _assert_unchanged(namespace, lock, raw)
    proof = dict(schemaVersion=1, nonce=nonce, originalMarker=record,
                 originalMarkerSha256=hashlib.sha256(raw).hexdigest(), firstCheck=first,
                 finalCheck=second, status='recorded-process-absence-verified', signals=[],
                 legacyLockMode='shared-with-running-pool-members',
                 scope='Explicit recovery only; no output quality or unobserved-child claim')
    state.publish(directory, archive, proof)
    _assert_unchanged(namespace, lock, raw)
    os.unlink(state.LEGACY_MARKER, dir_fd=directory)
    os.fsync(directory)
    return dict(status='recovered', kind='legacy-heavy', nonce=nonce,
                proof=os.path.join(namespace.root, archive), clearedActiveMarker=True, **second)


def _recover_legacy(namespace: state.Namespace, nonce: str) -> dict:
    """Hold the legacy lock shared: an old-code holder means that job is still live.

    A missing lock file (tmp_cleaner can delete an unread lock) is recreated; the exact
    absence checks below still refuse while the recorded supervisor PID exists.
    """
    lock = open_private_file(namespace.root_fd, state.LEGACY_LOCK, os.O_CREAT | os.O_RDWR)
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise NativeWorkBusy('Heavy work is still locked; recovery refused') from error
        return _recover_legacy_locked(namespace, lock, nonce)
    finally:
        os.close(lock)


def recover(nonce: str) -> dict:
    """Recover an exact pool member or legacy obligation inside one ledger transaction."""
    if not isinstance(nonce, str) or not re.fullmatch(r'[0-9a-f]{32}', nonce):
        raise ValueError('Recovery requires the exact 32-character active nonce')
    with state.ledger(time.monotonic() + state.LEDGER_WAIT_SECONDS) as namespace:
        if os.path.lexists(os.path.join(namespace.pool, f'm-{nonce}.json')):
            return pool_recovery.recover_member(namespace, nonce)
        return _recover_legacy(namespace, nonce)


def main() -> None:
    """Require the explicit nonce rather than offering automatic stale takeover."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('nonce')
    print(json.dumps(recover(parser.parse_args().nonce), indent=2))


if __name__ == '__main__':
    main()
