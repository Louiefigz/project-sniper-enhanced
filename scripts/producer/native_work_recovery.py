"""Explicit recovery of one native heavy-job cleanup fence after verified exit.

Never called by acquisition. Requires an explicitly selected exact nonce, an idle
existing kernel lock, an absent supervisor and absence of all retained children.
This command signals nothing and never edits the original failed job receipt.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import time

from headless.durable_files import (
    _assert_root_identity, assert_private_lock_identity, open_private_dir,
    open_private_file, read_private_file, write_pending_replace,
)
from native_render_processes import ProcessIdentity, identity_matches, process_table
from native_work_lease import NativeWorkBusy, NativeWorkLease, state_root


def _read_marker(directory: int, nonce: str) -> tuple[dict, bytes]:
    """Validate the specific prior obligation without trusting a PID alone."""
    raw = read_private_file(directory, 'heavy.active.json')
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
    """Require fresh successful inspection; any live supervisor blocks recovery."""
    result = subprocess.run(['/bin/ps', '-axo', 'pid=,ppid=,pgid=,lstart='],
                            capture_output=True, text=True, check=True, timeout=3)
    if result.stderr.strip():
        raise RuntimeError('Process inspection returned diagnostics; recovery refused')
    table = process_table(result.stdout)
    if record['supervisorPid'] in table:
        raise NativeWorkBusy('The recorded supervisor PID is still present; recovery refused')
    live = [row for row in record['processes'] if identity_matches(table, ProcessIdentity(**row))]
    if live:
        raise NativeWorkBusy('Recorded native children are still alive; recovery refused')
    reused = [row['pid'] for row in record['processes'] if row['pid'] in table]
    return dict(verifiedAt=time.time(), supervisorAbsent=True, recordedChildrenAbsent=True,
                recordedIdentityCount=len(record['processes']), reusedChildPids=reused)


def _assert_unchanged(directory: int, lock: int, raw: bytes) -> None:
    """Bind recovery to the original namespace, mutex inode and active bytes."""
    _assert_root_identity(str(state_root()), directory)
    assert_private_lock_identity(directory, 'heavy.lock', lock)
    if read_private_file(directory, 'heavy.active.json') != raw:
        raise RuntimeError('Active native obligation changed during recovery')


def _recover_locked(directory: int, lock: int, nonce: str) -> dict:
    """Archive a separate proof before clearing only the selected active marker."""
    record, raw = _read_marker(directory, nonce)
    _assert_unchanged(directory, lock, raw)
    first = _verify_absence(record)
    archive = f'heavy.recovery-{nonce}.json'
    try:
        os.stat(archive, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        raise RuntimeError('Recovery evidence already exists; inspect partial recovery instead of overwriting it')
    second = _verify_absence(record)
    _assert_unchanged(directory, lock, raw)
    proof = dict(schemaVersion=1, nonce=nonce, originalMarker=record,
                 originalMarkerSha256=hashlib.sha256(raw).hexdigest(), firstCheck=first,
                 finalCheck=second, status='recorded-process-absence-verified', signals=[],
                 scope='Explicit recovery only; no output quality or unobserved-child claim')
    write_pending_replace(directory, ('heavy.recovery.pending.json', archive),
                          (json.dumps(proof, indent=2)+'\n').encode())
    _assert_unchanged(directory, lock, raw)
    os.unlink('heavy.active.json', dir_fd=directory)
    os.fsync(directory)
    return dict(status='recovered', nonce=nonce, proof=str(state_root()/archive),
                clearedActiveMarker=True, **second)


def recover(nonce: str) -> dict:
    """Recover an exact obligation only after obtaining its existing mutex."""
    if not isinstance(nonce, str) or not re.fullmatch(r'[0-9a-f]{32}', nonce):
        raise ValueError('Recovery requires the exact 32-character active nonce')
    directory = open_private_dir(str(state_root()))
    lock = None
    try:
        lock = open_private_file(directory, 'heavy.lock', os.O_RDWR)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise NativeWorkBusy('Heavy work is still locked; recovery refused') from error
        return _recover_locked(directory, lock, nonce)
    finally:
        if lock is not None:
            os.close(lock)
        os.close(directory)


def main() -> None:
    """Require the explicit nonce rather than offering automatic stale takeover."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('nonce')
    print(json.dumps(recover(parser.parse_args().nonce), indent=2))


if __name__ == '__main__':
    main()
