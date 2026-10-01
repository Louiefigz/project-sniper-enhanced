"""Explicit recovery of one quarantined pool member after verified absence.

The member's own liveness lock must be free and is held during recovery; its exact
recorded supervisor identity (pid, process group, start time) and every recorded
child must be absent in two fresh process-table reads. An empty process list is
accepted only when the record never declared a launch (phase 'admitted'), which the
owner writes before its first child can exist. Signals nothing; a separate proof file
is archived before the record, and with it the slot and reservations, are released.

A record admission cannot read at all (not JSON, not an object, an unknown class, a
non-integer memory reservation or unreadable disk rows) blocks every disk admission, yet
names no processes recovery could check. It is removed by its file name only once its
liveness lock file is present and proved free; a missing lock file proves nothing (its owner
may hold a deleted lock), so such a record is refused. Any identity that can still be read
from it must be absent too. Its proof records exactly that weaker basis and the original
bytes. A readable record keeps the full rules above. A Studio member (native_work_pool_studio) is
always 'admitted' with no processes even when its start spawned the preview server, whose survivors
the Studio registry tracks: recovering it frees Studio capacity only, and its proof says so.
"""
from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import subprocess
import time

import native_work_pool_state as state
from headless.durable_files import DurableFileError, open_private_file, read_private_file
from native_render_processes import ProcessIdentity, identity_matches, process_table
from native_work_lease import NativeWorkBusy, NativeWorkLease
from native_work_pool_disk import readable
from native_work_pool_policy import LAYOUT, LEDGER_CLASSES, STUDIO_CLASS

PHASES = ('admitted', 'launching', 'launch-state-unknown')
STUDIO_SCOPE = ('; a Studio member records no process, so this frees Studio capacity only: the Studio '
                'registry tracks its preview server')


def process_snapshot() -> dict:
    """Read the whole process table; diagnostics are never treated as absence."""
    result = subprocess.run(['/bin/ps', '-axo', 'pid=,ppid=,pgid=,lstart='],
                            capture_output=True, text=True, check=True, timeout=3)
    if result.stderr.strip():
        raise RuntimeError('Process inspection returned diagnostics; recovery refused')
    return process_table(result.stdout)


def validate_member(record: object, nonce: str) -> dict:
    """Require the exact pool schema, identities and a known launch phase (any ledger class, Studio's too)."""
    if not isinstance(record, dict) or record.get('schemaVersion') != 1 or record.get('layout') != LAYOUT \
            or record.get('nonce') != nonce or record.get('class') not in LEDGER_CLASSES:
        raise RuntimeError('Recovery nonce does not match a pool member record')
    supervisor, children = record.get('supervisor'), record.get('processes')
    NativeWorkLease._validate_identity(supervisor)
    if not isinstance(children, list) or len(children) > 4096 or record.get('phase') not in PHASES:
        raise ValueError('Pool member record has an invalid child registry or launch phase')
    for row in children:
        NativeWorkLease._validate_identity(row)
    if not children and record['phase'] != 'admitted':
        raise ValueError('Empty child registry with a declared or unknown launch; '
                         'launch state cannot be proved here, investigate the owner receipt')
    return record


def verify_absence(record: dict) -> dict:
    """Refuse while the exact supervisor or any recorded child still exists."""
    table = process_snapshot()
    supervisor = ProcessIdentity(**record['supervisor'])
    if identity_matches(table, supervisor):
        raise NativeWorkBusy('The recorded supervisor is still running; recovery refused')
    live = [row for row in record['processes'] if identity_matches(table, ProcessIdentity(**row))]
    if live:
        raise NativeWorkBusy('Recorded native children are still alive; recovery refused')
    return dict(verifiedAt=time.time(), supervisorAbsent=True, recordedChildrenAbsent=True,
                recordedIdentityCount=len(record['processes']),
                supervisorPidReused=supervisor.pid in table,
                reusedChildPids=[row['pid'] for row in record['processes'] if row['pid'] in table])


def _hold_member_lock(namespace: state.Namespace, nonce: str) -> int | None:
    """Take the member's liveness lock for the whole recovery; a holder is live."""
    name = f'm-{nonce}.lock'
    if state.probe(namespace.pool_fd, name) == 'missing':
        return None
    fd = open_private_file(namespace.pool_fd, name, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise NativeWorkBusy('Pool member is still held by its supervisor; recovery refused') from None
    return fd


def _read_record(namespace: state.Namespace, marker: str) -> bytes | None:
    """The record's bytes, or None when it is not a private, single-link, bounded file."""
    try:
        return read_private_file(namespace.pool_fd, marker)
    except DurableFileError:
        return None


def _parsed(raw: bytes | None) -> object:
    """The record's JSON value, or None when the bytes are missing or not JSON."""
    try:
        return json.loads(raw) if raw is not None else None
    except ValueError:
        return None


def _valid_identity(row: object) -> bool:
    """Whether one stated identity has the exact pid/start/group shape."""
    try:
        NativeWorkLease._validate_identity(row)
    except ValueError:
        return False
    return True


def _readable_identities(value: object) -> list[dict]:
    """Every supervisor/child identity an unreadable record still states validly."""
    if not isinstance(value, dict):
        return []
    processes = value.get('processes')
    rows = [value.get('supervisor'), *(processes if isinstance(processes, list) else [])]
    return [row for row in rows if _valid_identity(row)]


def _release(namespace: state.Namespace, nonce: str, proof: tuple[str, dict], lock: int | None) -> None:
    """Publish the proof, then remove the record and its lock file."""
    state.publish(namespace.pool_fd, proof[0], proof[1])
    os.unlink(f'm-{nonce}.json', dir_fd=namespace.pool_fd)
    if lock is not None:
        os.unlink(f'm-{nonce}.lock', dir_fd=namespace.pool_fd)
    os.fsync(namespace.pool_fd)


def _recover_unreadable(namespace: state.Namespace, nonce: str, raw: bytes | None, lock: int | None) -> dict:
    """Remove a record admission cannot read, on its present and free liveness lock alone.

    `raw` is None when the file itself cannot be read safely (a link, wrong owner or mode,
    oversized); it is then removed by its name, which is all that identifies it.
    """
    if lock is None:
        raise NativeWorkBusy(f'Unreadable pool member {nonce} has no liveness lock file, so nothing proves its '
                             'owner has exited; recovery refused (inspect the owner, then remove the record by hand)')
    identities = _readable_identities(_parsed(raw))
    table = process_snapshot()
    live = [row for row in identities if identity_matches(table, ProcessIdentity(**row))]
    if live:
        raise NativeWorkBusy('An identity recorded in the unreadable pool member is still running; recovery refused')
    proof = f'recovery-{nonce}.json'
    if os.path.lexists(os.path.join(namespace.pool, proof)):
        raise RuntimeError('Recovery evidence already exists; inspect partial recovery first')
    if _read_record(namespace, f'm-{nonce}.json') != raw:
        raise RuntimeError('Pool member record changed during recovery')
    evidence = dict(schemaVersion=1, layout=LAYOUT, nonce=nonce, kind='unreadable-pool-member',
                    originalRecordBase64=base64.b64encode(raw).decode() if raw is not None else None,
                    originalRecordSha256=hashlib.sha256(raw).hexdigest() if raw is not None else None,
                    memberLockPresent=True, memberLockFree=True, readableIdentitiesChecked=len(identities),
                    verifiedAt=time.time(), signals=[], status='unreadable-record-removed-on-free-liveness-lock',
                    scope='The record could not be read, so only its free liveness lock and any readable '
                          'identity prove its owner gone; unrecorded children were not checked')
    _release(namespace, nonce, (proof, evidence), lock)
    return dict(status='recovered', kind='unreadable-pool-member', nonce=nonce,
                proof=os.path.join(namespace.pool, proof), clearedMemberRecord=True,
                memberLockPresent=True, readableIdentitiesChecked=len(identities))


def _validated(raw: bytes | None, nonce: str) -> dict | None:
    """The validated record; None when admission cannot read it at all; raise when it is readable but invalid."""
    value = _parsed(raw)
    try:
        return validate_member(value, nonce)
    except (RuntimeError, ValueError, TypeError, KeyError):
        if readable(value):
            raise
    return None


def recover_member(namespace: state.Namespace, nonce: str) -> dict:
    """Archive proof, then clear exactly one quarantined member inside the ledger lock."""
    marker, proof = f'm-{nonce}.json', f'recovery-{nonce}.json'
    lock = _hold_member_lock(namespace, nonce)
    try:
        raw = _read_record(namespace, marker)
        record = _validated(raw, nonce)
        if record is None:
            return _recover_unreadable(namespace, nonce, raw, lock)
        first = verify_absence(record)
        if os.path.lexists(os.path.join(namespace.pool, proof)):
            raise RuntimeError('Recovery evidence already exists; inspect partial recovery first')
        second = verify_absence(record)
        if read_private_file(namespace.pool_fd, marker) != raw:
            raise RuntimeError('Pool member record changed during recovery')
        evidence = dict(schemaVersion=1, layout=LAYOUT, nonce=nonce, originalRecord=record,
                        originalRecordSha256=hashlib.sha256(raw).hexdigest(), firstCheck=first,
                        finalCheck=second, memberLockPresent=lock is not None, signals=[],
                        status='recorded-process-absence-verified',
                        scope='Explicit recovery only; no output quality or unobserved-child claim'
                        + (STUDIO_SCOPE if record['class'] == STUDIO_CLASS else ''))
        _release(namespace, nonce, (proof, evidence), lock)
    finally:
        if lock is not None:
            os.close(lock)
    return dict(status='recovered', kind='pool-member', nonce=nonce, memberClass=record['class'],
                releasedReservationBytes=record['reservationBytes'],
                proof=os.path.join(namespace.pool, proof), clearedMemberRecord=True, **second)
