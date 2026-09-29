"""Earlier engines' member roots, classified before the host-wide ledger lock, never inside it.

A record written by an earlier engine names only its root device (diskDevice); its space
comes from its root directory (native_work_pool_disk.root_space), which may sit on a slow or
hung filesystem. So every transaction first reads the member records without the lock and
classifies those roots (prescan), and inside the lock reads only that result (RootCharges).

Each (root, device) has at most one classification thread in this process: a pending one is
reused (never a second thread for the same root), a finished one for ROOT_REUSE_SECONDS. All
roots of one prescan are classified concurrently, and the wait ends at the earlier of
ROOT_CLASSIFY_SECONDS after each thread's start and the caller's own bound (an owner's
admission deadline, a Long monitor's expansion tick), so hung roots never add up. A root that
has not answered by then, a classifier that crashes, a root that cannot be classified, a
record naming no root or project, and a member that appeared after the prescan are all
charged in every space (conservative) and named in the admission receipt
('diskChargedInEverySpace'); none refuses admission forever.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import native_work_pool_disk as disk
import native_work_pool_state as state
from headless.durable_files import DurableFileError, bounded_directory_entries

ROOT_CLASSIFY_SECONDS = 5.0
ROOT_REUSE_SECONDS = 60.0
_SLOTS: dict[tuple[str, int], dict] = {}
_SLOTS_LOCK = threading.Lock()


def legacy_root(record: dict) -> tuple[str, int] | None:
    """(root directory, device) of an earlier engine's record; None when it names no root or project."""
    path, device = record.get('root') or record.get('project'), record.get('diskDevice')
    return (path, device) if isinstance(path, str) and type(device) is int else None


def _earlier(record: object) -> bool:
    """A readable record written by an earlier engine (its root reservation names no space)."""
    return isinstance(record, dict) and record.get('diskAccounting') is None


@dataclass
class RootCharges:
    """One transaction's root spaces of earlier engines' members, and why any is charged everywhere."""

    spaces: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)

    def space_of(self, record: dict) -> str:
        """The pre-lock classification; a root without one is charged in every space (named)."""
        key = legacy_root(record)
        if key in self.spaces:
            return self.spaces[key]
        why = 'its record names no root or project' if key is None else 'it appeared after classification'
        self.named(f"member {record.get('nonce')}: {why}")
        return disk.EVERY_SPACE

    def named(self, note: str) -> None:
        """Record one conservative every-space charge for the receipt, once."""
        if f'charged in every space: {note}' not in self.notes:
            self.notes.append(f'charged in every space: {note}')


def _classify(key: tuple[str, int], slot: dict) -> None:
    """Thread target: one root's space; a crash is recorded, never raised."""
    try:
        slot['space'] = disk.root_space({'root': key[0]}, key[1])
    except BaseException as error:
        slot['error'] = f'{type(error).__name__}: {error}'
    finally:
        slot['finished'] = time.monotonic()
        slot['done'].set()


def _slot(key: tuple[str, int]) -> dict:
    """The pending or reusable classification of one root; a thread starts only when there is none."""
    with _SLOTS_LOCK:
        slot = _SLOTS.get(key)
        fresh = slot is not None and (slot['finished'] is None
                                      or time.monotonic() - slot['finished'] < ROOT_REUSE_SECONDS)
        if fresh:
            return slot
        slot = _SLOTS[key] = {'started': time.monotonic(), 'finished': None, 'done': threading.Event()}
    threading.Thread(target=_classify, args=(key, slot), daemon=True, name=f'sniper-pool-root:{key[0]}').start()
    return slot


def _unclassified(key: tuple[str, int], slot: dict) -> str | None:
    """Why this root is charged in every space, or None when its space is known."""
    if not slot['done'].is_set() and time.monotonic() >= slot['started'] + ROOT_CLASSIFY_SECONDS:
        return f'root {key[0]} did not answer within {ROOT_CLASSIFY_SECONDS:g} s'
    if not slot['done'].is_set():
        return f"root {key[0]} had not answered by this attempt's deadline"
    if 'error' in slot:
        return f"root {key[0]} classifier failed ({slot['error']})"
    if slot['space'] == disk.EVERY_SPACE:
        return f'root {key[0]} is unreadable, not accountable or no longer on device {key[1]}'
    return None


def _charge(key: tuple[str, int], slot: dict, until: float, charges: RootCharges) -> None:
    """Wait until the thread's own deadline or the caller's bound; record its space or an every-space charge."""
    slot['done'].wait(max(0.0, min(until, slot['started'] + ROOT_CLASSIFY_SECONDS) - time.monotonic()))
    reason = _unclassified(key, slot)
    if reason:
        charges.named(reason)
    charges.spaces[key] = disk.EVERY_SPACE if reason else slot['space']


def classify(records: list, until: float | None = None) -> RootCharges:
    """Classify every earlier engine's member root concurrently (outside the ledger lock).

    Args:
        records: The member records read before the lock.
        until: The caller's monotonic bound; None waits at most ROOT_CLASSIFY_SECONDS per thread.
    """
    charges = RootCharges()
    keys = {legacy_root(record) for record in records if _earlier(record)} - {None}
    slots = {key: _slot(key) for key in sorted(keys)}  # every thread starts before any wait
    bound = until if until is not None else float('inf')
    for key, slot in slots.items():
        _charge(key, slot, bound, charges)
    with _SLOTS_LOCK:  # forget finished classifications of members that are gone
        for key in [key for key, slot in _SLOTS.items() if key not in keys and slot['finished'] is not None]:
            del _SLOTS[key]
    return charges


def _peek(directory: int, name: str) -> object:
    """One member record read without the ledger (records are replaced atomically); None if unreadable."""
    try:
        return state.read_json(directory, name)
    except (DurableFileError, OSError, ValueError):
        return None


def prescan(until: float | None = None) -> RootCharges:
    """Before the ledger lock: read the member records and classify earlier engines' roots by `until`."""
    namespace = state.open_namespace()
    try:
        names = bounded_directory_entries(namespace.pool_fd, state.ENTRY_LIMIT)
        records = [_peek(namespace.pool_fd, name) for name in names if state.MEMBER.fullmatch(name)]
    finally:
        namespace.close()
    return classify(records, until)
