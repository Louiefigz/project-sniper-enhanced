"""Shared recovery barriers for an already-held active-fence lock."""

from __future__ import annotations

from .active_fence_journal import (
    ActiveFenceJournalSessionV1,
    close_active_fence_journal_v1,
    open_active_fence_journal_v1,
    repair_torn_active_fence_tail_v1,
    resync_active_fence_journal_v1,
    scan_active_fence_journal_v1,
)
from .active_fence_lock import (
    ActiveFenceLockV1,
    validate_active_fence_lock_v1,
)
from .active_fence_materialized import reconcile_materialized_active_fence_v1
from .active_fence_types import (
    ActiveFenceError,
    ActiveFenceJournalScanV1,
    ActiveFenceStateV1,
)
from .authority_record import read_authority_record


def require_existing_active_fence_authority_v1(
    lock: ActiveFenceLockV1, authority_id: str
) -> None:
    """Require the exact authority record through the held root descriptor."""
    observed = read_authority_record(lock.root_fd)
    expected = {"schemaVersion": 1, "authorityId": authority_id}
    if observed != expected:
        raise ActiveFenceError(
            "active-fence authority record is absent or mismatched"
        )


def scan_repaired_active_fence_journal_v1(
    session: ActiveFenceJournalSessionV1,
) -> ActiveFenceJournalScanV1:
    """Repair only a torn tail, then durably re-scan the journal."""
    scan = scan_active_fence_journal_v1(session)
    if scan.torn_bytes:
        scan = repair_torn_active_fence_tail_v1(session, scan)
    return resync_active_fence_journal_v1(session)


def finalize_active_fence_projection_v1(
    lock: ActiveFenceLockV1,
    session: ActiveFenceJournalSessionV1,
    scan: ActiveFenceJournalScanV1,
) -> None:
    """Reconcile and re-fsync FENCE around two exact journal barriers."""
    first = resync_active_fence_journal_v1(session)
    if first != scan:
        raise ActiveFenceError(
            "active-fence journal changed before projection"
        )
    reconcile_materialized_active_fence_v1(lock, first)
    second = resync_active_fence_journal_v1(session)
    if second != first:
        raise ActiveFenceError("active-fence journal changed after projection")
    reconcile_materialized_active_fence_v1(lock, second)


def reobserve_active_generation_fence_locked_core_v1(
    lock: ActiveFenceLockV1,
) -> ActiveFenceStateV1:
    """Return the repaired, resynced, and reconciled journal-tail state."""
    validate_active_fence_lock_v1(lock)
    session = open_active_fence_journal_v1(lock, False)
    try:
        scan = scan_repaired_active_fence_journal_v1(session)
        if not scan.transitions:
            raise ActiveFenceError("active-fence journal is uninitialized")
        state = scan.transitions[-1].state
        require_existing_active_fence_authority_v1(lock, state.authority_id)
        finalize_active_fence_projection_v1(lock, session, scan)
        return state
    finally:
        close_active_fence_journal_v1(session)
