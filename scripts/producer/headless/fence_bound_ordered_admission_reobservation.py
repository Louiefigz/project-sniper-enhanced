"""Final named-disk reobservation for one fence-bound ordered admission."""

from __future__ import annotations

import os

from .cross_ledger_order_lock import (
    CrossLedgerOrderLockV1,
    validate_publish_cross_ledger_lock_pair_v1,
)
from .cross_ledger_order_protocol import (
    preflight_cross_ledger_ordered_admission_under_lock_v1,
)
from .cross_ledger_order_types import (
    CrossLedgerOrderRequestV1,
    DurableCrossLedgerOrderedAdmissionV1,
)
from .durable_files import open_private_child_dir
from .fence_bound_ordered_admission_types import (
    FenceBoundOrderedAdmissionError,
)
from .operation_admission_durable_validation import (
    validate_durable_operation_admission_v3,
)
from .operation_admission_lock_resources import (
    OPERATION_ADMISSION_STORE_NAME,
)
from .operation_admission_store_reader import (
    operation_admission_record_name_v3,
)
from .operation_admission_store_persistence import (
    pinned_durable_operation_admission_record_v3,
)
from .operation_admission_store_result import (
    durable_operation_admission_result,
)
from .record_durability import assert_named_private_directory_identity
from .wire_identity import same_wire_value


def _reobserve_admission(
    lock: CrossLedgerOrderLockV1,
    request: CrossLedgerOrderRequestV1,
    ordered: DurableCrossLedgerOrderedAdmissionV1,
) -> None:
    store_fd = open_private_child_dir(
        lock.root_fd, OPERATION_ADMISSION_STORE_NAME
    )
    try:
        assert_named_private_directory_identity(
            lock.root_fd, OPERATION_ADMISSION_STORE_NAME, store_fd
        )
        name = operation_admission_record_name_v3(
            request.admission.admission.idempotency_key
        )
        with pinned_durable_operation_admission_record_v3(
            store_fd, name, request.admission.admission
        ) as retained:
            observed = durable_operation_admission_result(False, retained)
            validate_durable_operation_admission_v3(observed)
            if not same_wire_value(observed, ordered.admission):
                raise FenceBoundOrderedAdmissionError(
                    "ordered admission changed after commit"
                )
        assert_named_private_directory_identity(
            lock.root_fd, OPERATION_ADMISSION_STORE_NAME, store_fd
        )
    finally:
        os.close(store_fd)


def reobserve_exact_ordered_admission_under_locks_v1(
    publish_lock: object,
    cross_lock: CrossLedgerOrderLockV1,
    request: CrossLedgerOrderRequestV1,
    ordered: DurableCrossLedgerOrderedAdmissionV1,
) -> None:
    """Require the exact committed order and V3 admission at named paths."""
    try:
        validate_publish_cross_ledger_lock_pair_v1(
            publish_lock, cross_lock
        )
        state = preflight_cross_ledger_ordered_admission_under_lock_v1(
            request, cross_lock
        )
        exact_order = (
            state.state == "committed"
            and same_wire_value(state.intent, ordered.intent)
            and same_wire_value(state.receipt, ordered.receipt)
        )
        if not exact_order:
            raise FenceBoundOrderedAdmissionError(
                "ordered admission is not durably committed"
            )
        _reobserve_admission(cross_lock, request, ordered)
        validate_publish_cross_ledger_lock_pair_v1(
            publish_lock, cross_lock
        )
    except FenceBoundOrderedAdmissionError:
        raise
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise FenceBoundOrderedAdmissionError(
            "ordered admission final reobservation failed"
        ) from exc
