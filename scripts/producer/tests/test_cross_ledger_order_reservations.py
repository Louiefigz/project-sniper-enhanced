"""Adversarial uniqueness-reservation tests for cross-ledger ordering."""

from __future__ import annotations

import dataclasses
import fcntl
import os
import unittest
from unittest.mock import patch

from _common import pl  # noqa: F401
from _cross_ledger_order_fixture import (
    SECOND_ATTEMPT,
    SECOND_CHILD,
    SECOND_IDEMPOTENCY,
    CrossLedgerOrderFixture,
)
from _operation_admission_fixture import admission
from headless.cross_ledger_order_lock import (
    CrossLedgerOrderLockError,
    locked_cross_ledger_order_root_v1,
    validate_cross_ledger_order_lock_v1,
)
from headless.cross_ledger_order_protocol import (
    persist_or_replay_cross_ledger_ordered_admission_v1,
)
from headless.cross_ledger_order_types import (
    CrossLedgerOrderConflictV1,
    CrossLedgerOrderError,
    CrossLedgerOrderPermanentRejectionV1,
    CrossLedgerOrderRequestV1,
)
from headless.operation_admission_store import (
    OperationAdmissionStoreError,
    persist_or_replay_operation_admission_v3,
)
from headless.operation_admission_store_types import (
    OperationAdmissionStoreRequestV3,
)


def _conflicting_request(
    fixture: CrossLedgerOrderFixture, role: str
) -> CrossLedgerOrderRequestV1:
    base = fixture.request()
    proposal = dataclasses.replace(
        base.admission.proposal,
        idempotency_key=SECOND_IDEMPOTENCY,
        attempt_id=(
            base.admission.admission.attempt_id
            if role == "attempt"
            else SECOND_ATTEMPT
        ),
        intended_child_generation_id=(
            base.admission.admission.intended_child_generation_id
            if role == "child"
            else SECOND_CHILD
        ),
    )
    admitted = admission(fixture.operation, proposal)
    stored = OperationAdmissionStoreRequestV3(
        fixture.root, fixture.operation, admitted, proposal
    )
    return CrossLedgerOrderRequestV1(
        fixture.root, fixture.durable_enrollment, stored
    )


def _leave_prepared(fixture: CrossLedgerOrderFixture) -> None:
    target = (
        "headless.cross_ledger_order_protocol."
        "persist_or_replay_operation_admission_v3_in_transaction"
    )
    with patch(target, side_effect=RuntimeError("crash after PREPARED")):
        try:
            fixture.persist()
        except CrossLedgerOrderError:
            return
    raise AssertionError("PREPARED crash was not surfaced")


class CrossLedgerOrderReservationTests(unittest.TestCase):
    def test_prepared_reserves_attempt_and_child_from_direct_writers(
        self,
    ) -> None:
        for role in ("attempt", "child"):
            with self.subTest(role=role):
                fixture = CrossLedgerOrderFixture()
                self.addCleanup(fixture.close)
                _leave_prepared(fixture)
                conflict = _conflicting_request(fixture, role)
                with self.assertRaises(OperationAdmissionStoreError):
                    persist_or_replay_operation_admission_v3(
                        conflict.admission
                    )
                self.assertEqual(fixture.persist().state, "committed")

    def test_prepared_reserves_attempt_and_child_from_ordered_writers(
        self,
    ) -> None:
        for role in ("attempt", "child"):
            with self.subTest(role=role):
                fixture = CrossLedgerOrderFixture()
                self.addCleanup(fixture.close)
                _leave_prepared(fixture)
                with self.assertRaises(CrossLedgerOrderConflictV1):
                    persist_or_replay_cross_ledger_ordered_admission_v1(
                        _conflicting_request(fixture, role)
                    )

    def test_preexisting_attempt_or_child_conflict_is_tombstoned(self) -> None:
        for role in ("attempt", "child"):
            with self.subTest(role=role):
                fixture = CrossLedgerOrderFixture()
                self.addCleanup(fixture.close)
                conflict = _conflicting_request(fixture, role)
                persist_or_replay_operation_admission_v3(conflict.admission)
                with self.assertRaises(CrossLedgerOrderPermanentRejectionV1):
                    fixture.persist()
                store = os.path.join(fixture.root, "cross-ledger-orders-v1")
                record = os.path.join(store, os.listdir(store)[0])
                self.assertEqual(os.listdir(record), ["rejection.json"])

    def test_explicitly_unlocked_witness_is_rejected(self) -> None:
        fixture = CrossLedgerOrderFixture()
        self.addCleanup(fixture.close)
        with self.assertRaises(CrossLedgerOrderLockError):
            with locked_cross_ledger_order_root_v1(fixture.root) as lock:
                fcntl.flock(lock.lock_fd, fcntl.LOCK_UN)
                validate_cross_ledger_order_lock_v1(lock)

    def test_malformed_and_cross_role_alias_requests_are_normalized(
        self,
    ) -> None:
        fixture = CrossLedgerOrderFixture()
        self.addCleanup(fixture.close)
        malformed = dataclasses.replace(fixture.request(), admission=None)
        with self.assertRaises(CrossLedgerOrderError):
            persist_or_replay_cross_ledger_ordered_admission_v1(malformed)
        base = fixture.request()
        proposed = dataclasses.replace(
            base.admission.proposal,
            idempotency_key=fixture.enrollment.enrollment_key,
        )
        admitted = admission(fixture.operation, proposed)
        stored = OperationAdmissionStoreRequestV3(
            fixture.root, fixture.operation, admitted, proposed
        )
        aliased = CrossLedgerOrderRequestV1(
            fixture.root, fixture.durable_enrollment, stored
        )
        with self.assertRaises(CrossLedgerOrderError):
            persist_or_replay_cross_ledger_ordered_admission_v1(aliased)
        self.assertFalse(
            os.path.exists(
                os.path.join(fixture.root, "operation-admissions-v3")
            )
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
