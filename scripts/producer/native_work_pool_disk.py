"""Disk reservations of pool members, charged by the space their free bytes come from.

A filesystem's free bytes may be shared: every APFS volume of one container reports the
container's free space (less its own reserve or quota), so reservations on sibling
volumes compete. Each reservation is therefore charged to a *space*: the APFS container
(the whole disk of the volume's /dev/diskNsM slice, which diskutil reports as
APFSContainerReference) or, for an HFS+, exFAT or FAT volume, that filesystem alone.
Filesystems whose free bytes cannot be charged exactly (network, stacked, memory, disk
images, an unnamed APFS container) refuse disk accounting (native_work_pool_storage.py).

Record versions, all readable here:
- earlier engines: diskDevice/diskReservationBytes only (root filesystem; its space is
  derived from the record's root directory, else charged in every space);
- 90896bc (first E2 commit): adds diskReservations rows {device, bytes} with no space;
  non-root rows are charged in every space;
- current (diskAccounting == ACCOUNTING): diskSpace plus rows {device, space, bytes}.
The root entry is always mirrored into diskReservationBytes so earlier readers still
charge the root filesystem. A record that cannot be read or validated is unknown: while
its supervisor holds the member lock, disk admission and expansion wait for it; once the
lock is free they are refused until native_work_recovery.py removes it. Space keys name
disks by boot-session numbers (diskN, st_dev): a quarantined record keeps the key it was
written with, so if its disk is ejected and another disk takes that number in the same
boot, the old reservation is charged against the newcomer until it is recovered.
Expansion lives in native_work_pool_expand.py.
"""
from __future__ import annotations

import os
from typing import NamedTuple

import native_work_pool_storage as storage
from native_work_pool_policy import DISK_RESERVE_BYTES, LEDGER_CLASSES
from native_work_pool_storage import DiskUnaccountable

DEVICE_LIMIT = 8
BYTES_LIMIT = 2 ** 53
EVERY_SPACE = '*'  # a reservation whose space cannot be identified is charged in every space
ACCOUNTING = 'space-v2'  # records without it come from earlier engines
UNKNOWN_MEMBER = ('an unreadable pool member record holds unknown disk reservations; '
                  'no disk can be admitted until it is recovered')
UNKNOWN_LIVE = ('a live pool member\'s record cannot be read, so its disk reservations are unknown '
                'until its supervisor finishes')
ADMISSION_REFUSALS = {  # headroom verdict -> (Decision list, reason); 'reasons' may clear, 'terminal' cannot
    'unknown': ('terminal', UNKNOWN_MEMBER),
    'terminal': ('terminal', 'disk headroom for output and OS swap is below policy after reservations'),
    'unknown-live': ('reasons', UNKNOWN_LIVE),
    'waitable': ('reasons', 'disk headroom is reserved by running members')}


class Filesystem(NamedTuple):
    """Where a directory's bytes land and whose free bytes they consume."""

    device: int
    space: str
    free: int


def free_bytes(path: str) -> int:
    """Live bytes an unprivileged writer may still use on the directory's filesystem."""
    info = os.statvfs(path)
    return info.f_bavail * info.f_frsize


def filesystem(path: str) -> Filesystem:
    """Return the device, shared space and live free bytes for a real directory, or refuse.

    Raises:
        DiskUnaccountable: The filesystem cannot be charged exactly (native_work_pool_storage).
    """
    device = os.stat(path).st_dev
    return Filesystem(device, storage.space(path, device), free_bytes(path))


def _rows(record: dict) -> list[tuple[int, str | None, int]] | None:
    """Validated diskReservations rows in the record's own version; None when malformed."""
    rows, current = record.get('diskReservations'), record.get('diskAccounting') == ACCOUNTING
    keys = {'device', 'space', 'bytes'} if current else {'device', 'bytes'}
    if not isinstance(rows, list) or not 1 <= len(rows) <= DEVICE_LIMIT:
        return None
    parsed = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != keys or type(row['device']) is not int \
                or not isinstance(row.get('space', ''), str) or type(row['bytes']) is not int \
                or not 0 <= row['bytes'] < BYTES_LIMIT:
            return None
        parsed.append((row['device'], row.get('space'), row['bytes']))
    return parsed if len({device for device, _space, _size in parsed}) == len(parsed) else None


def record_disks(record: dict) -> dict[int, tuple[str | None, int]] | None:
    """Device -> (space or None when unrecorded, reserved bytes); None when malformed."""
    device, total, space = record.get('diskDevice'), record.get('diskReservationBytes'), record.get('diskSpace')
    marker = record.get('diskAccounting')
    if type(device) is not int or type(total) is not int or total < 0 or marker not in (None, ACCOUNTING) \
            or not (space is None or isinstance(space, str)) or (marker is None) != (space is None):
        return None
    if record.get('diskReservations') is None:
        return {device: (space, total)}
    rows = _rows(record)
    disks = {row_device: (row_space, size) for row_device, row_space, size in rows or []}
    if rows is None or disks.get(device, (None, None))[1] != total:
        return None
    return disks


def root_space(record: dict, device: int) -> str:
    """An earlier engine's record: the space of its root directory while it still shows that device."""
    path = record.get('root') or record.get('project')
    try:
        found = filesystem(path)
    except (OSError, TypeError, ValueError, DiskUnaccountable):
        return EVERY_SPACE
    return found.space if found.device == device else EVERY_SPACE


def readable(record: object) -> bool:
    """Admission can read the record's class (a Studio member's too), memory reservation and disk rows."""
    return isinstance(record, dict) and record.get('class') in LEDGER_CLASSES \
        and type(record.get('reservationBytes')) is int and record_disks(record) is not None


def charged_spaces(record: object, roots: object | None = None) -> dict[str, int] | None:
    """Reserved bytes by space of a record admission can read (class, memory, disk); else None."""
    return record_spaces(record, roots) if readable(record) else None


def _root_charge(record: dict, device: int, roots: object | None) -> str:
    """The space of an earlier engine's root: classified before the lock (roots), or here without one."""
    return root_space(record, device) if roots is None else roots.space_of(record)


def record_spaces(record: dict, roots: object | None = None) -> dict[str, int] | None:
    """Reserved bytes by space ('*' is charged in every space); None when the record is malformed.

    `roots` is native_work_pool_roots.prescan() output; inside the ledger lock callers always
    pass it, so no foreign root is statted while the lock is held.
    """
    disks = record_disks(record)
    if disks is None:
        return None
    spaces: dict[str, int] = {}
    for device, (space, size) in disks.items():
        key = space or (_root_charge(record, device, roots) if device == record['diskDevice'] else EVERY_SPACE)
        spaces[key] = spaces.get(key, 0) + size
    return spaces


def headroom(rows: list[dict], space: str, free: int, need: int) -> tuple[str | None, dict]:
    """Classify one space for a total reservation of `need` bytes by the requester.

    Args:
        rows: Charged members other than the requester, each with 'spaces' (None = unknown).
        space: The space being charged.
        free: Live free bytes of the space.
        need: The requester's total reservation in this space.

    Returns:
        (None | 'waitable' | 'unknown-live' | 'terminal' | 'unknown', figures): waitable means
        running members' reservations are in the way and unknown-live that a live member's record
        cannot be read (both may clear); terminal means quarantined reservations or true shortage
        and unknown a quarantined unreadable record (both need recovery or space).
    """
    known = [row for row in rows if row['spaces'] is not None]
    others = sum(row['spaces'].get(space, 0) + row['spaces'].get(EVERY_SPACE, 0) for row in known)
    quarantined = sum(row['spaces'].get(space, 0) + row['spaces'].get(EVERY_SPACE, 0)
                      for row in known if row['quarantined'])
    unknown = [row['quarantined'] for row in rows if row['spaces'] is None]
    figures = {'space': space, 'freeBytes': free, 'reservedByOthersBytes': others,
               'quarantinedBytes': quarantined, 'reservationBytes': need, 'reserveBytes': DISK_RESERVE_BYTES}
    if any(unknown):
        return 'unknown', figures
    if free - quarantined < need + DISK_RESERVE_BYTES:
        return 'terminal', figures
    if unknown:
        return 'unknown-live', figures
    if free - others < need + DISK_RESERVE_BYTES:
        return 'waitable', figures
    return None, figures


def fence_reasons(space: str) -> list[str]:
    """Why a reservation in this space needs the older-client fence (native_work_pool_fence).

    Older pool clients charge a member only on its recorded device. Every volume of an APFS
    container (including one mounted later) spends the same free bytes, so an older client
    admitted on any other volume of the container would not see this reservation.
    """
    if not space.startswith('apfs-container:'):
        return []
    return [f'disk reserved in {space}, which older pool clients charge per volume']


def admission(decision: object, rows: list[dict], path: str) -> None:
    """Charge a new member's disk to its root filesystem's space; add refusal reasons to `decision`."""
    found = filesystem(path)
    decision.device, decision.space = found.device, found.space
    verdict, figures = headroom(rows, found.space, found.free, decision.disk)
    decision.context.update(diskFreeBytes=found.free, diskReservedByOthersBytes=figures['reservedByOthersBytes'])
    if verdict:
        kind, message = ADMISSION_REFUSALS[verdict]
        getattr(decision, kind).append(message)
