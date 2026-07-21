"""Durable causal marker proving active fence before order PREPARED."""

from __future__ import annotations

import os

from .active_fence_lock import ActiveFenceLockError
from .active_fence_types import ActiveFenceError
from .authority_record import AuthorityRecordError, read_authority_record
from .cross_ledger_order_barrier import (
    load_writer_durable_cross_ledger_order_state_v1,
)
from .cross_ledger_order_lock import CrossLedgerOrderLockError
from .cross_ledger_order_types import CrossLedgerOrderError
from .durable_files import DurableFileError
from .fence_admission_reservation_types import (
    FenceAdmissionReservationError,
)
from .fence_order_start_input_reobservation import (
    require_exact_fence_order_start_inputs_v1,
    validate_fence_order_start_lock_pair_v1,
)
from .fence_order_start_pending import (
    recover_fence_order_start_pending_v1,
    write_fence_order_start_record_v1,
)
from .fence_order_start_records import (
    MAX_START_RECORDS,
    STORE_NAME,
    ObservedFenceOrderStartV1,
    fence_order_start_record_name_v1,
    open_existing_fence_order_start_store_v1,
    open_fence_order_start_store_v1,
    pinned_fence_order_start_record_v1,
    stable_fence_order_start_scan_v1,
)
from .fence_order_start_schema import (
    FenceOrderStartSchemaError,
    build_fence_order_start_intent_v1,
)
from .fence_order_start_types import (
    FENCE_ORDER_START_STATUS,
    DurableFenceOrderStartV1,
    FenceOrderStartConflictV1,
    FenceOrderStartError,
    FenceOrderStartIntentV1,
    FenceOrderStartRequestV1,
)
from .record_durability import assert_named_private_directory_identity


def _checked_request(
    value: object,
) -> tuple[FenceOrderStartRequestV1, FenceOrderStartIntentV1]:
    if type(value) is not FenceOrderStartRequestV1:
        raise FenceOrderStartError("fence order start request is invalid")
    validate_fence_order_start_lock_pair_v1(value.locks)
    intent = build_fence_order_start_intent_v1(
        value.reservation, value.fence, value.order_identity
    )
    return value, intent


def _require_authority(request: FenceOrderStartRequestV1) -> None:
    retained = read_authority_record(request.locks.publish_lock.root_fd)
    expected = {
        "authorityId": request.order_identity.authority_id,
        "schemaVersion": 1,
    }
    if retained != expected:
        raise FenceOrderStartError("start authority is invalid")


def _validate_records(
    records: tuple[ObservedFenceOrderStartV1, ...], authority_id: str
) -> None:
    attempts: set[str] = set()
    reservations: set[str] = set()
    orders: set[str] = set()
    tokens: set[str] = set()
    for item in records:
        intent = item.intent
        named = fence_order_start_record_name_v1(intent.attempt_id)
        values = (
            (attempts, intent.attempt_id),
            (reservations, intent.reservation_digest),
            (orders, intent.order_identity_digest),
            (tokens, intent.fence_token),
        )
        duplicate = any(value in retained for retained, value in values)
        if (
            item.name != named
            or intent.authority_id != authority_id
            or duplicate
        ):
            raise FenceOrderStartError("start record set identity is invalid")
        for retained, value in values:
            retained.add(value)


def _candidate_conflicts(
    records: tuple[ObservedFenceOrderStartV1, ...],
    candidate: FenceOrderStartIntentV1,
) -> bool:
    return any(
        candidate.reservation_digest == item.intent.reservation_digest
        or candidate.order_identity_digest == item.intent.order_identity_digest
        or candidate.fence_token == item.intent.fence_token
        for item in records
    )


def _result(
    store_fd: int, expected: FenceOrderStartIntentV1, created: bool
) -> DurableFenceOrderStartV1:
    name = fence_order_start_record_name_v1(expected.attempt_id)
    with pinned_fence_order_start_record_v1(store_fd, name) as selected:
        if selected.raw != expected.document_json:
            raise FenceOrderStartConflictV1(
                "attempt is bound to another start intent"
            )
        records = stable_fence_order_start_scan_v1(store_fd)
        _validate_records(records, expected.authority_id)
        if not any(item.name == name for item in records):
            raise FenceOrderStartError("start intent disappeared")
        return DurableFenceOrderStartV1(
            FENCE_ORDER_START_STATUS,
            created,
            name,
            selected.intent,
            True,
            True,
            True,
            True,
            True,
            False,
            False,
        )


def _persist(
    store_fd: int,
    intent: FenceOrderStartIntentV1,
    allow_create: bool,
) -> DurableFenceOrderStartV1:
    name = fence_order_start_record_name_v1(intent.attempt_id)
    if allow_create:
        recover_fence_order_start_pending_v1(
            store_fd, name, intent.document_json
        )
    records = stable_fence_order_start_scan_v1(store_fd)
    _validate_records(records, intent.authority_id)
    if any(item.name == name for item in records):
        return _result(store_fd, intent, False)
    if not allow_create:
        raise FenceOrderStartError(
            "start intent cannot be created after order transition"
        )
    if len(records) >= MAX_START_RECORDS:
        raise FenceOrderStartError("start store exceeds its record limit")
    if _candidate_conflicts(records, intent):
        raise FenceOrderStartConflictV1("start identity is already retained")
    write_fence_order_start_record_v1(store_fd, name, intent.document_json)
    return _result(store_fd, intent, True)


def _run(value: object, create: bool) -> DurableFenceOrderStartV1:
    store_fd = None
    try:
        request, intent = _checked_request(value)
        _require_authority(request)
        require_exact_fence_order_start_inputs_v1(request)
        allow_create = False
        if create:
            cross_state = load_writer_durable_cross_ledger_order_state_v1(
                request.locks.cross_lock, request.order_identity
            )
            allow_create = cross_state.state == "absent"
        opener = open_existing_fence_order_start_store_v1
        if create and allow_create:
            opener = open_fence_order_start_store_v1
        store_fd = opener(request.locks)
        result = (
            _persist(store_fd, intent, allow_create)
            if create
            else _result(store_fd, intent, False)
        )
        require_exact_fence_order_start_inputs_v1(request)
        assert_named_private_directory_identity(
            request.locks.publish_lock.root_fd, STORE_NAME, store_fd
        )
        validate_fence_order_start_lock_pair_v1(request.locks)
        return result
    except (FenceOrderStartConflictV1, FenceOrderStartError):
        raise
    except (
        ActiveFenceError,
        ActiveFenceLockError,
        AuthorityRecordError,
        CrossLedgerOrderError,
        CrossLedgerOrderLockError,
        DurableFileError,
        FenceAdmissionReservationError,
        FenceOrderStartSchemaError,
        OSError,
    ) as exc:
        action = "persistence" if create else "reobservation"
        raise FenceOrderStartError(
            f"fence order start {action} failed"
        ) from exc
    finally:
        if store_fd is not None:
            os.close(store_fd)


def persist_or_replay_fence_order_start_v1(
    value: object,
) -> DurableFenceOrderStartV1:
    """Persist the fence-before-order edge under both exact live locks."""
    return _run(value, True)


def reobserve_fence_order_start_v1(
    value: object,
) -> DurableFenceOrderStartV1:
    """Reobserve an existing exact edge without creating or healing it."""
    return _run(value, False)
