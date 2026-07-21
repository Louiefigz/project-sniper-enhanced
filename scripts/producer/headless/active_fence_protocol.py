"""Non-authorizing active-fence operations; no work, CURRENT, or RELEASE."""

from __future__ import annotations

import uuid

from .active_fence_frames import (
    build_active_fence_bootstrap_v1,
    build_active_fence_cancel_v1,
    build_active_fence_reserve_v1,
)
from .active_fence_journal import (
    ActiveFenceJournalError,
    ActiveFenceJournalMissingError,
    ActiveFenceJournalSessionV1,
    append_active_fence_transition_v1,
    close_active_fence_journal_v1,
    open_active_fence_journal_v1,
)
from .active_fence_locked_reobservation import (
    finalize_active_fence_projection_v1 as _finalize_projection,
    reobserve_active_generation_fence_locked_core_v1 as _reobserve_locked,
    require_existing_active_fence_authority_v1 as _require_existing_authority,
    scan_repaired_active_fence_journal_v1 as _scan_repaired,
)
from .active_fence_lock import (
    ActiveFenceLockError,
    ActiveFenceLockV1,
    locked_existing_publish_mutex_v1,
    locked_publish_mutex_v1,
    validate_active_fence_lock_v1,
)
from .active_fence_materialized import (
    ActiveFenceMaterializedError,
    reconcile_materialized_active_fence_v1,
    require_unmaterialized_active_fence_v1,
)
from .active_fence_schema import (
    ActiveFenceSchemaError,
    validate_active_fence_attempt_id_v1,
    validate_active_fence_authority_v1,
)
from .active_fence_types import (
    ActiveFenceConflictError,
    ActiveFenceError,
    ActiveFenceJournalScanV1,
    ActiveFenceOperationResultV1,
    ActiveFenceStateV1,
)
from .authority_record import AuthorityRecordError, ensure_authority_record
from .wire_identity import same_wire_value

_INTERNAL_ERRORS = (
    ActiveFenceJournalError,
    ActiveFenceLockError,
    ActiveFenceMaterializedError,
    ActiveFenceSchemaError,
    AuthorityRecordError,
    OSError,
)


def _new_token() -> str:
    return str(uuid.uuid4())


def _unique_token(scan: ActiveFenceJournalScanV1) -> str:
    token = _new_token()
    retained = {item.state.fence_token for item in scan.transitions}
    if token in retained:
        raise ActiveFenceError("active-fence token was already used")
    return token


def _result(
    operation: str, scan: ActiveFenceJournalScanV1, created: bool
) -> ActiveFenceOperationResultV1:
    return ActiveFenceOperationResultV1(
        operation, scan.transitions[-1].state, created, not created
    )


def _bootstrap_locked(
    lock: ActiveFenceLockV1, authority_id: str
) -> ActiveFenceOperationResultV1:
    ensure_authority_record(lock.root_fd, authority_id)
    try:
        session = open_active_fence_journal_v1(lock, False)
    except ActiveFenceJournalMissingError:
        require_unmaterialized_active_fence_v1(lock)
        session = open_active_fence_journal_v1(lock, True)
    try:
        scan = _scan_repaired(session)
        created = False
        if not scan.transitions:
            require_unmaterialized_active_fence_v1(lock)
            transition = build_active_fence_bootstrap_v1(
                authority_id, _new_token()
            )
            scan = append_active_fence_transition_v1(session, scan, transition)
            created = True
        if scan.transitions[0].state.authority_id != authority_id:
            raise ActiveFenceError("active-fence journal authority mismatches")
        _finalize_projection(lock, session, scan)
        return _result("BOOTSTRAP", scan, created)
    finally:
        close_active_fence_journal_v1(session)


def bootstrap_active_generation_fence_v1(
    authority_root: str, authority_id: str
) -> ActiveFenceOperationResultV1:
    """Create or replay the inactive revision-zero active fence."""
    try:
        authority = validate_active_fence_authority_v1(authority_id)
        with locked_publish_mutex_v1(authority_root) as lock:
            return _bootstrap_locked(lock, authority)
    except ActiveFenceError:
        raise
    except _INTERNAL_ERRORS as exc:
        raise ActiveFenceError("active-fence bootstrap failed") from exc


def _append_reserve(
    session: ActiveFenceJournalSessionV1,
    scan: ActiveFenceJournalScanV1,
    attempt_id: str,
) -> tuple[ActiveFenceJournalScanV1, bool]:
    tail = scan.transitions[-1]
    if tail.state.active_attempt_id == attempt_id:
        return scan, False
    if tail.state.active_attempt_id is not None:
        raise ActiveFenceConflictError("another attempt holds active fence")
    used_attempts = {item.attempt_id for item in scan.transitions}
    if attempt_id in used_attempts:
        raise ActiveFenceConflictError("attempt ID was already fenced")
    transition = build_active_fence_reserve_v1(
        tail, attempt_id, _unique_token(scan)
    )
    return append_active_fence_transition_v1(session, scan, transition), True


def _append_cancel(
    session: ActiveFenceJournalSessionV1,
    scan: ActiveFenceJournalScanV1,
    attempt_id: str,
) -> tuple[ActiveFenceJournalScanV1, bool]:
    tail = scan.transitions[-1]
    if tail.state.active_attempt_id == attempt_id:
        transition = build_active_fence_cancel_v1(
            tail, attempt_id, _unique_token(scan)
        )
        return (
            append_active_fence_transition_v1(session, scan, transition),
            True,
        )
    replay = (
        tail.state.active_attempt_id is None
        and tail.event == "CANCEL"
        and tail.attempt_id == attempt_id
    )
    if replay:
        return scan, False
    raise ActiveFenceConflictError("cancel target does not hold active fence")


def _mutate_locked(
    lock: ActiveFenceLockV1,
    authority_id: str,
    attempt_id: str,
    operation: str,
) -> ActiveFenceOperationResultV1:
    validate_active_fence_lock_v1(lock)
    authority_id = validate_active_fence_authority_v1(authority_id)
    attempt_id = validate_active_fence_attempt_id_v1(attempt_id)
    _require_existing_authority(lock, authority_id)
    session = open_active_fence_journal_v1(lock, False)
    try:
        scan = _scan_repaired(session)
        if not scan.transitions:
            raise ActiveFenceError("active-fence journal is uninitialized")
        if scan.transitions[0].state.authority_id != authority_id:
            raise ActiveFenceError("active-fence journal authority mismatches")
        reconcile_materialized_active_fence_v1(lock, scan)
        append = _append_reserve if operation == "RESERVE" else _append_cancel
        scan, created = append(session, scan, attempt_id)
        _finalize_projection(lock, session, scan)
        return _result(operation, scan, created)
    finally:
        close_active_fence_journal_v1(session)


def _mutate(
    authority_root: str,
    authority_id: str,
    attempt_id: str,
    operation: str,
) -> ActiveFenceOperationResultV1:
    try:
        authority = validate_active_fence_authority_v1(authority_id)
        attempt = validate_active_fence_attempt_id_v1(attempt_id)
        with locked_existing_publish_mutex_v1(authority_root) as lock:
            return _mutate_locked(lock, authority, attempt, operation)
    except ActiveFenceError:
        raise
    except _INTERNAL_ERRORS as exc:
        raise ActiveFenceError(
            f"active-fence {operation.lower()} failed"
        ) from exc


def reserve_active_generation_fence_under_lock_v1(
    lock: ActiveFenceLockV1, authority_id: str, attempt_id: str
) -> ActiveFenceOperationResultV1:
    """Reserve without reacquiring the caller-held publisher mutex."""
    try:
        return _mutate_locked(lock, authority_id, attempt_id, "RESERVE")
    except ActiveFenceError:
        raise
    except _INTERNAL_ERRORS as exc:
        raise ActiveFenceError("active-fence locked reserve failed") from exc


def reobserve_active_generation_fence_under_lock_v1(
    lock: ActiveFenceLockV1,
) -> ActiveFenceStateV1:
    """Repair and durably reobserve the fence under its live outer lock."""
    try:
        return _reobserve_locked(lock)
    except ActiveFenceError:
        raise
    except _INTERNAL_ERRORS as exc:
        raise ActiveFenceError(
            "active-fence locked reobservation failed"
        ) from exc


def reobserve_exact_active_generation_fence_under_lock_v1(
    lock: ActiveFenceLockV1, expected_state: ActiveFenceStateV1
) -> ActiveFenceStateV1:
    """Require exact wire-safe equality after durable locked reobservation."""
    observed = reobserve_active_generation_fence_under_lock_v1(lock)
    if not same_wire_value(observed, expected_state):
        raise ActiveFenceConflictError("active-fence state changed")
    return observed


def reserve_active_generation_fence_v1(
    authority_root: str, authority_id: str, attempt_id: str
) -> ActiveFenceOperationResultV1:
    """Reserve one inactive authority or replay the exact active attempt."""
    return _mutate(authority_root, authority_id, attempt_id, "RESERVE")


def cancel_active_generation_fence_v1(
    authority_root: str, authority_id: str, attempt_id: str
) -> ActiveFenceOperationResultV1:
    """Rotate and clear only the exact active attempt, or replay its cancel."""
    return _mutate(authority_root, authority_id, attempt_id, "CANCEL")
