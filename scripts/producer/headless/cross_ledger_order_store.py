"""Bounded durable state machine for cross-ledger order documents."""

from __future__ import annotations

import os
import re

from .cross_ledger_order_lock import (
    CrossLedgerOrderLockV1,
    validate_cross_ledger_order_lock_v1,
)
from .cross_ledger_order_fs import cross_ledger_order_record_name_v1
from .cross_ledger_order_schema import (
    CrossLedgerOrderIdentityV1,
    build_cross_ledger_order_intent_v1,
    build_cross_ledger_order_receipt_v1,
    build_cross_ledger_order_rejection_v1,
    require_same_cross_ledger_identity_v1,
)
from .cross_ledger_order_store_record import (
    load_cross_ledger_order_record_v1,
)
from .cross_ledger_order_store_scan import (
    CrossLedgerOrderScanError,
    load_stable_cross_ledger_order_set_v1,
)
from .cross_ledger_order_types import (
    CrossLedgerOrderConflictV1,
    CrossLedgerOrderError,
    CrossLedgerOrderPermanentRejectionV1,
    CrossLedgerOrderStateV1,
)
from .cross_ledger_order_store_write import (
    CrossLedgerOrderWriteError,
    INTENT_NAME as _INTENT_NAME,
    REJECTION_NAME as _REJECTION_NAME,
    STORE_NAME as _STORE_NAME,
    append_cross_ledger_order_receipt_v1,
    append_cross_ledger_order_rejection_v1,
    create_cross_ledger_order_record_v1,
)
from .durable_files import (
    bounded_directory_entries,
    DurableFileError,
    open_private_child_dir,
)
from .wire_identity import same_wire_value

_RECORD = re.compile(r"[0-9a-f]{64}")
_MAX_RECORDS = 50_000


def _open_store(lock: CrossLedgerOrderLockV1) -> int | None:
    try:
        return open_private_child_dir(lock.root_fd, _STORE_NAME)
    except DurableFileError as exc:
        if isinstance(exc.__cause__, FileNotFoundError):
            return None
        raise CrossLedgerOrderError(
            "cross-ledger order store is unsafe"
        ) from exc


def _validate_state(state: CrossLedgerOrderStateV1, authority_id: str) -> None:
    documents = tuple(
        row
        for row in (state.intent, state.receipt, state.rejection)
        if row is not None
    )
    if not documents:
        return
    identity = documents[0].identity
    valid = (
        all(same_wire_value(row.identity, identity) for row in documents)
        and identity.authority_id == authority_id
        and state.name
        == cross_ledger_order_record_name_v1(identity.idempotency_key)
    )
    if state.receipt is not None:
        valid = (
            valid
            and state.receipt.intent_digest == state.intent.document_digest
        )
    if not valid:
        raise CrossLedgerOrderError("cross-ledger order state is inconsistent")


def _all_states(
    lock: CrossLedgerOrderLockV1, authority_id: str
) -> tuple[CrossLedgerOrderStateV1, ...]:
    validate_cross_ledger_order_lock_v1(lock)
    store_fd = _open_store(lock)
    if store_fd is None:
        return ()
    try:
        names = bounded_directory_entries(store_fd, _MAX_RECORDS)
        if any(name.startswith(".pending-") for name in names):
            raise CrossLedgerOrderError("torn cross-ledger order exists")
        if any(not _RECORD.fullmatch(name) for name in names):
            raise CrossLedgerOrderError(
                "cross-ledger order store has unknown entries"
            )
        states = load_stable_cross_ledger_order_set_v1(
            store_fd, names, load_cross_ledger_order_record_v1
        )
        for state in states:
            _validate_state(state, authority_id)
        identities = tuple(
            (state.intent or state.rejection).identity for state in states
        )
        roles = (
            tuple(row.order_identity_digest for row in identities),
            tuple(row.idempotency_key for row in identities),
            tuple(row.attempt_id for row in identities),
            tuple(row.intended_child_generation_id for row in identities),
        )
        if any(len(set(values)) != len(values) for values in roles):
            raise CrossLedgerOrderError(
                "cross-ledger order store duplicates a reserved identity"
            )
        return states
    except (DurableFileError, CrossLedgerOrderScanError) as exc:
        raise CrossLedgerOrderError(
            "cross-ledger order store cannot be reobserved"
        ) from exc
    finally:
        os.close(store_fd)


def _selected_state(
    states: tuple[CrossLedgerOrderStateV1, ...],
    identity: CrossLedgerOrderIdentityV1,
) -> CrossLedgerOrderStateV1:
    name = cross_ledger_order_record_name_v1(identity.idempotency_key)
    found = next((state for state in states if state.name == name), None)
    if found is None:
        collision = any(
            (state.intent or state.rejection).identity.attempt_id
            == identity.attempt_id
            or (
                state.intent or state.rejection
            ).identity.intended_child_generation_id
            == identity.intended_child_generation_id
            for state in states
        )
        if collision:
            raise CrossLedgerOrderConflictV1(
                "attempt or child identity is already reserved"
            )
        return CrossLedgerOrderStateV1("absent", name, None, None, None)
    document = found.intent or found.rejection
    try:
        require_same_cross_ledger_identity_v1(document.identity, identity)
    except RuntimeError as exc:
        raise CrossLedgerOrderConflictV1(str(exc)) from exc
    if found.state == "rejected":
        raise CrossLedgerOrderPermanentRejectionV1(
            "operation admission predated prospective order intent"
        )
    return found


def load_cross_ledger_order_state_v1(
    lock: CrossLedgerOrderLockV1,
    identity: CrossLedgerOrderIdentityV1,
) -> CrossLedgerOrderStateV1:
    """Load one state, rejecting different identities and tombstones."""
    return _selected_state(_all_states(lock, identity.authority_id), identity)


def persist_cross_ledger_order_prepared_v1(
    lock: CrossLedgerOrderLockV1, identity: CrossLedgerOrderIdentityV1
) -> CrossLedgerOrderStateV1:
    """Durably install PREPARED before any matching admission write."""
    states = _all_states(lock, identity.authority_id)
    state = _selected_state(states, identity)
    if state.state != "absent":
        return state
    if len(states) >= _MAX_RECORDS:
        raise CrossLedgerOrderError(
            "cross-ledger order store exceeds its record limit"
        )
    try:
        create_cross_ledger_order_record_v1(
            lock,
            state.name,
            _INTENT_NAME,
            build_cross_ledger_order_intent_v1(identity),
        )
    except CrossLedgerOrderWriteError as exc:
        raise CrossLedgerOrderError(str(exc)) from exc
    retained = load_cross_ledger_order_state_v1(lock, identity)
    if retained.state != "prepared":
        raise CrossLedgerOrderError("prepared order intent was not retained")
    return retained


def persist_cross_ledger_order_rejection_v1(
    lock: CrossLedgerOrderLockV1, identity: CrossLedgerOrderIdentityV1
) -> None:
    """Permanently tombstone a unit whose admission predated an intent."""
    states = _all_states(lock, identity.authority_id)
    state = _selected_state(states, identity)
    if state.state != "absent":
        raise CrossLedgerOrderError("cross-ledger rejection state conflicts")
    if len(states) >= _MAX_RECORDS:
        raise CrossLedgerOrderError(
            "cross-ledger order store exceeds its record limit"
        )
    try:
        create_cross_ledger_order_record_v1(
            lock,
            state.name,
            _REJECTION_NAME,
            build_cross_ledger_order_rejection_v1(identity),
        )
    except CrossLedgerOrderWriteError as exc:
        raise CrossLedgerOrderError(str(exc)) from exc
    try:
        load_cross_ledger_order_state_v1(lock, identity)
    except CrossLedgerOrderPermanentRejectionV1:
        return
    raise CrossLedgerOrderError("cross-ledger rejection was not retained")


def reject_prepared_cross_ledger_order_v1(
    lock: CrossLedgerOrderLockV1,
    identity: CrossLedgerOrderIdentityV1,
    reason: str = "ADMISSION_REPLAYED_AFTER_FRESH_INTENT",
) -> None:
    """Poison a fresh intent when admission unexpectedly replayed."""
    state = load_cross_ledger_order_state_v1(lock, identity)
    if state.state != "prepared":
        raise CrossLedgerOrderError("order violation is not prepared")
    raw = build_cross_ledger_order_rejection_v1(identity, reason)
    try:
        append_cross_ledger_order_rejection_v1(lock, state.name, raw)
    except CrossLedgerOrderWriteError as exc:
        raise CrossLedgerOrderError(str(exc)) from exc
    try:
        load_cross_ledger_order_state_v1(lock, identity)
    except CrossLedgerOrderPermanentRejectionV1:
        return
    raise CrossLedgerOrderError("order violation rejection was not retained")


def persist_cross_ledger_order_committed_v1(
    lock: CrossLedgerOrderLockV1, identity: CrossLedgerOrderIdentityV1
) -> CrossLedgerOrderStateV1:
    """Append or recover COMMITTED after exact admission reobservation."""
    state = load_cross_ledger_order_state_v1(lock, identity)
    if state.state == "committed":
        return state
    if state.state not in {"prepared", "commit-pending"}:
        raise CrossLedgerOrderError("order intent is not prepared")
    try:
        raw = build_cross_ledger_order_receipt_v1(
            identity, state.intent.document_digest
        )
        append_cross_ledger_order_receipt_v1(
            lock,
            state.name,
            raw,
            state.state == "commit-pending",
        )
    except CrossLedgerOrderWriteError as exc:
        raise CrossLedgerOrderError(str(exc)) from exc
    retained = load_cross_ledger_order_state_v1(lock, identity)
    if retained.state != "committed":
        raise CrossLedgerOrderError("committed order receipt was not retained")
    return retained
