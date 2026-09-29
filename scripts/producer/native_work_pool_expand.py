"""Grow a running pool member's disk reservation before it writes (Long source extraction).

Policy, stated here and tested in test_native_work_pool.py:
- One ledger transaction checks every space the request names against every other member's
  committed reservation there (native_work_pool_disk.headroom). Expansion is not queued:
  FIFO tickets hold no bytes, so a grant can lengthen a queued owner's wait, and admissions
  are never held back for a pending expansion.
- The request's directories come from the owner's child. They are opened, statted and
  classified (device, space, free bytes; native_work_pool_storage refuses what cannot be
  charged) before the ledger lock, so a slow filesystem never holds the host-wide lock.
  Inside the transaction each path is re-checked with one lstat against the descriptor
  opened before (same device and inode): a directory renamed away, replaced or removed
  meanwhile is refused by name. Free bytes are therefore read at most one ledger wait
  before the transaction; bytes members write meanwhile fall inside reservations already
  charged. Paths are resolved (realpath) before the lock; the resolved path is re-checked.
- Bytes on a device other than the member's root are invisible to older pool clients, so
  off_root_fence fences the member (native_work_pool_fence.fence_member) before they are
  reserved. A member whose root space is an APFS container, or that is exclusive or
  schema-2, was already fenced at admission whenever older clients could run qualified.
- NativeWorkQueued (running members' reservations, a live member whose record cannot be
  read, a busy ledger) may clear; the owner retries it on later monitor ticks within a
  bounded window (studio/native_run_disk.serve_disk_request). Every other refusal is final.
- The ledger wait is bounded by the caller's `until` (one monitor tick), not only the 10 s
  admission bound, so a busy ledger never stalls an owner's supervision loop.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

import native_work_pool_fence as fence
import native_work_pool_policy as policy
import native_work_pool_roots as pool_roots
import native_work_pool_state as state
import native_work_pool_disk as disk
from native_work_pool import _member_charges  # shared with admission so both charge identically
from native_work_pool_observe import observe
from native_work_pool_state import NativeWorkQuarantined, NativeWorkQueued

OFF_ROOT = 'disk reserved on another filesystem'


@dataclass(frozen=True)
class Directory:
    """One requested directory, opened and classified before the ledger lock."""

    path: str
    resolved: str
    size: int
    descriptor: int
    identity: tuple[int, int]
    found: disk.Filesystem


def _open(directory: object, size: object) -> Directory:
    """Validate, open and classify one directory; its descriptor pins the inode checked later."""
    if not isinstance(directory, str) or not Path(directory).is_absolute() \
            or type(size) is not int or not 0 <= size < disk.BYTES_LIMIT:
        raise ValueError('Disk expansion requires existing absolute directories and byte counts')
    resolved = os.path.realpath(directory)
    try:
        descriptor = os.open(resolved, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as error:
        raise ValueError(f'Disk expansion directory {directory} is not an existing directory') from error
    try:
        status, named = os.fstat(descriptor), os.lstat(resolved)
        if (named.st_dev, named.st_ino) != (status.st_dev, status.st_ino):
            raise ValueError(f'Disk expansion directory {directory} changed while it was opened')
        identity = (status.st_dev, status.st_ino)
        return Directory(directory, resolved, size, descriptor, identity, disk.filesystem(resolved))
    except BaseException:
        os.close(descriptor)
        raise


def opened(directories: dict[str, int]) -> list[Directory]:
    """Open every requested directory before the ledger lock; the caller closes them (close())."""
    if not isinstance(directories, dict) or not 1 <= len(directories) <= disk.DEVICE_LIMIT:
        raise ValueError('Disk expansion names one to eight directories')
    rows: list[Directory] = []
    try:
        for directory, size in sorted(directories.items()):
            rows.append(_open(directory, size))
    except BaseException:
        close(rows)
        raise
    return rows


def close(rows: list[Directory]) -> None:
    """Release the descriptors opened for one expansion."""
    for row in rows:
        os.close(row.descriptor)


def _still_named(row: Directory) -> None:
    """The path still names the opened directory (one lstat inside the transaction); refuse by name."""
    try:
        named = os.lstat(row.resolved)
    except FileNotFoundError:
        raise ValueError(f'Disk expansion directory {row.path} was removed before the transaction') from None
    if (named.st_dev, named.st_ino) != row.identity:
        raise ValueError(f'Disk expansion directory {row.path} was renamed or replaced before the transaction')


def demands(rows: list[Directory]) -> dict[int, dict]:
    """Group requested bytes by device inside the ledger; each path is re-checked against its descriptor."""
    grouped: dict[int, dict] = {}
    for row in rows:
        _still_named(row)
        found = row.found
        entry = grouped.setdefault(found.device, {'bytes': 0, 'space': found.space, 'free': found.free,
                                                  'directories': []})
        entry['bytes'] += row.size
        entry['free'] = min(entry['free'], found.free)
        entry['directories'].append(row.path)
    return grouped


def _granted(record: dict, wanted: dict[int, dict]) -> dict[int, tuple[str, int]]:
    """Every device's new (space, bytes): the current reservation plus the requested bytes."""
    current = disk.record_disks(record)
    if current is None:
        raise RuntimeError('Native pool member disk reservation is malformed')
    granted = {device: (space or disk.root_space(record, device), size) for device, (space, size) in current.items()}
    for device, demand in wanted.items():
        space, size = granted.get(device, (demand['space'], 0))
        if space != demand['space']:
            raise RuntimeError(f'Filesystem {device} changed its space during the member lifetime')
        granted[device] = (space, size + demand['bytes'])
    if len(granted) > disk.DEVICE_LIMIT:
        raise ValueError('Disk expansion exceeds the per-member filesystem bound')
    return granted


def expanded(record: dict, rows: list[dict], wanted: dict[int, dict]) -> tuple[dict, dict]:
    """Return the member record with grown reservations, or raise without changing anything.

    Args:
        record: The member's current record (live, owned by the caller).
        rows: Every other charged member (see native_work_pool_disk.headroom).
        wanted: demands() output: device -> requested total bytes, space, live free bytes, directories.

    Returns:
        (new record, grant evidence per space). Requested bytes add to what the member already holds:
        admission covers what an owner writes in its attempt, expansion what it extracts elsewhere.

    Raises:
        NativeWorkQueued: Running members' reservations leave no room now.
        NativeWorkQuarantined: Quarantined or unknown reservations, or the free space itself, leave no room.
    """
    granted, evidence, refused = _granted(record, wanted), [], {}
    for space in sorted({demand['space'] for demand in wanted.values()}):
        need = sum(size for owner, size in granted.values() if owner == space)
        mine = [demand for demand in wanted.values() if demand['space'] == space]
        verdict, figures = disk.headroom(rows, space, min(demand['free'] for demand in mine), need)
        evidence.append({**figures, 'directories': sorted(sum((demand['directories'] for demand in mine), [])),
                         'requestedBytes': sum(demand['bytes'] for demand in mine)})
        if verdict:
            refused[space] = verdict
    if refused:
        raise _refusal(refused, evidence)
    reservations = [{'device': device, 'space': space, 'bytes': size}
                    for device, (space, size) in sorted(granted.items())]
    new = dict(record, diskReservations=reservations, diskReservationBytes=granted[record['diskDevice']][1],
               diskExpandedAt=time.time())
    return new, {'filesystems': evidence}


def _refusal(refused: dict[str, str], evidence: list[dict]) -> Exception:
    """Name each short space with its figures; only reservations by running members may clear."""
    detail = '; '.join(f"{row['space']}: {row['freeBytes']} free, {row['reservedByOthersBytes']} reserved by "
                       f"other members ({row['quarantinedBytes']} quarantined), {row['reservationBytes']} "
                       f"+ {row['reserveBytes']} reserve needed" for row in evidence if row['space'] in refused)
    if 'unknown' in refused.values():
        return NativeWorkQuarantined(f'Disk expansion refused: {disk.UNKNOWN_MEMBER}; {detail}')
    if 'terminal' in refused.values():
        return NativeWorkQuarantined('Disk expansion refused: free space after quarantined reservations '
                                     f'cannot hold the projected bytes plus reserve; {detail}')
    if 'unknown-live' in refused.values():
        return NativeWorkQueued(f'Disk expansion refused: {disk.UNKNOWN_LIVE}; {detail}')
    return NativeWorkQueued('Disk expansion refused: disk headroom is reserved by running members; ' + detail)


def off_root_fence(namespace: state.Namespace, view: state.PoolView, lease: object, off_root: bool) -> None:
    """Fence the member before it reserves bytes older pool clients cannot see.

    Older clients charge only a member's root device (diskDevice/diskReservationBytes), so
    bytes on any other device are invisible to them. The single compatibility fence
    (native_work_pool_fence, unit E3) keeps them out while this member lives; fence_member
    does nothing when the member is already fenced or no valid schema-1 record lets older
    clients run qualified. An older request already queued waits behind the new fence.

    Args:
        namespace: The open ledger namespace (the caller holds the ledger lock).
        view: The pool snapshot observed inside this ledger transaction.
        lease: The expanding member's live PoolLease.
        off_root: Whether any requested device differs from the member's root device.
    """
    if off_root:
        fence.fence_member(namespace, view, lease, [OFF_ROOT])


def expand_disk(lease: object, directories: dict[str, int], until: float | None = None) -> dict:
    """Grow a running member's disk reservation before it writes; refuse rather than wait.

    Args:
        lease: The caller's own live PoolLease.
        directories: Absolute directory -> additional bytes this member will write there; entries
            on one space are summed with its current reservation there, and each space is checked.
        until: Monotonic bound for the ledger wait (default: the 10 s admission bound).

    Returns:
        Grant evidence with every space's figures.

    Raises:
        NativeWorkQueued: May clear (running members' reservations, a live unreadable member, busy ledger,
            an earlier engine's member root not yet classified).
        NativeWorkQuarantined: Quarantined or unknown reservations, or true shortage.
        DiskUnaccountable: A directory on a filesystem the pool cannot charge exactly.
    """
    physical = policy.host_identity()['memsizeBytes']
    rows = opened(directories)
    try:
        roots = pool_roots.prescan(until)  # bounded by the monitor's tick, like the ledger wait
        with state.ledger(until or time.monotonic() + state.LEDGER_WAIT_SECONDS) as namespace:
            lease.assert_live()
            view = observe(namespace)
            view.roots = roots
            wanted = demands(rows)
            off_root_fence(namespace, view, lease, any(device != lease.record['diskDevice'] for device in wanted))
            others = [row for row in _member_charges(view, physical) if row['nonce'] != lease.nonce]
            record, grant = expanded(lease.record, others, wanted)
            lease.adopt_disk(record)
    finally:
        close(rows)
    return {**grant, 'diskChargedInEverySpace': roots.notes}
