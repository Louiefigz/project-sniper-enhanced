"""Targeted durability barriers for writer-side order decisions."""

from __future__ import annotations

import os

from .cross_ledger_order_durable_read import (
    pinned_durable_cross_ledger_order_records_v1,
)
from .cross_ledger_order_lock import CrossLedgerOrderLockV1
from .cross_ledger_order_schema import CrossLedgerOrderIdentityV1
from .cross_ledger_order_store import (
    _all_states,
    _open_store,
    _selected_state,
)
from .cross_ledger_order_types import (
    CrossLedgerOrderError,
    CrossLedgerOrderStateV1,
)
from .cross_ledger_order_store_write import STORE_NAME
from .record_durability import assert_named_private_directory_identity
from .wire_identity import same_wire_value


def _relevant_names(
    states: tuple[CrossLedgerOrderStateV1, ...],
    roles: tuple[str, str, str],
) -> frozenset[str]:
    idempotency_key, attempt_id, child_id = roles
    return frozenset(
        state.name
        for state in states
        if (
            (state.intent or state.rejection).identity.idempotency_key
            == idempotency_key
            or (state.intent or state.rejection).identity.attempt_id
            == attempt_id
            or (
                state.intent or state.rejection
            ).identity.intended_child_generation_id
            == child_id
        )
    )


def _merge_pinned(
    retained: tuple[CrossLedgerOrderStateV1, ...],
    pinned: tuple[CrossLedgerOrderStateV1, ...],
    relevant: frozenset[str],
) -> tuple[CrossLedgerOrderStateV1, ...]:
    by_name = {state.name: state for state in pinned}
    observed = {state.name: state for state in retained}
    if frozenset(by_name) != relevant:
        raise CrossLedgerOrderError("cross-ledger pinned rows changed")
    if any(
        name not in observed or not same_wire_value(state, observed[name])
        for name, state in by_name.items()
    ):
        raise CrossLedgerOrderError(
            "cross-ledger rows changed across durability reload"
        )
    return tuple(by_name.get(state.name, state) for state in retained)


def load_writer_durable_cross_ledger_order_set_v1(
    lock: CrossLedgerOrderLockV1,
    authority_id: str,
    roles: tuple[str, str, str],
) -> tuple[CrossLedgerOrderStateV1, ...]:
    """Reflush matching visible records before a writer relies on them."""
    states = _all_states(lock, authority_id)
    relevant = _relevant_names(states, roles)
    if not relevant:
        return states
    store_fd = _open_store(lock)
    if store_fd is None:
        raise CrossLedgerOrderError("cross-ledger order store disappeared")
    expected = frozenset(state.name for state in states)
    try:
        assert_named_private_directory_identity(
            lock.root_fd, STORE_NAME, store_fd
        )
        with pinned_durable_cross_ledger_order_records_v1(
            store_fd, relevant, expected
        ) as pinned:
            retained = _all_states(lock, authority_id)
            if _relevant_names(retained, roles) != relevant:
                raise CrossLedgerOrderError(
                    "cross-ledger relevant records changed across barrier"
                )
            merged = _merge_pinned(retained, pinned, relevant)
        assert_named_private_directory_identity(
            lock.root_fd, STORE_NAME, store_fd
        )
    except RuntimeError as exc:
        raise CrossLedgerOrderError(
            "cross-ledger durability barrier failed"
        ) from exc
    finally:
        os.close(store_fd)
    return merged


def load_writer_durable_cross_ledger_order_state_v1(
    lock: CrossLedgerOrderLockV1,
    identity: CrossLedgerOrderIdentityV1,
) -> CrossLedgerOrderStateV1:
    """Load one request state only after its targeted parent barrier."""
    roles = (
        identity.idempotency_key,
        identity.attempt_id,
        identity.intended_child_generation_id,
    )
    states = load_writer_durable_cross_ledger_order_set_v1(
        lock, identity.authority_id, roles
    )
    return _selected_state(states, identity)
