"""Small exact fixtures for durable cross-ledger prospective ordering."""

from __future__ import annotations

import dataclasses
import os
import tempfile

from _operation_admission_fixture import admission, proposal, quality_operation
from _unit_enrollment_fixture import enrollment, enrollment_proposal
from headless.cross_ledger_order_protocol import (
    persist_or_replay_cross_ledger_ordered_admission_v1,
)
from headless.cross_ledger_order_types import CrossLedgerOrderRequestV1
from headless.operation_admission_store_types import (
    OperationAdmissionStoreRequestV3,
)
from headless.unit_enrollment_store import (
    persist_or_replay_prospective_unit_enrollment_v1,
    reobserve_prospective_unit_enrollment_v1,
)
from headless.unit_enrollment_store_types import (
    UnitEnrollmentReadRequestV1,
    UnitEnrollmentStoreRequestV1,
)

SECOND_IDEMPOTENCY = "88888888-8888-4888-8888-888888888888"
SECOND_ATTEMPT = "99999999-9999-4999-8999-999999999999"
SECOND_CHILD = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


class CrossLedgerOrderFixture:
    """Owned authority root with one retained prospective enrollment."""

    def __init__(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.temporary.name)
        os.chmod(self.root, 0o700)
        self.operation = quality_operation()
        self.enrollment = enrollment(
            self.operation, enrollment_proposal(self.operation)
        )
        persist_or_replay_prospective_unit_enrollment_v1(
            UnitEnrollmentStoreRequestV1(self.root, self.enrollment)
        )
        self.durable_enrollment = reobserve_prospective_unit_enrollment_v1(
            UnitEnrollmentReadRequestV1(
                self.root,
                self.enrollment.authority_id,
                self.enrollment.enrollment_key,
            )
        )

    def close(self) -> None:
        """Remove the temporary authority root."""
        self.temporary.cleanup()

    def request(self, second: bool = False) -> CrossLedgerOrderRequestV1:
        """Return the first or second admission for the same unit."""
        proposed = proposal(self.operation)
        if second:
            proposed = dataclasses.replace(
                proposed,
                idempotency_key=SECOND_IDEMPOTENCY,
                attempt_id=SECOND_ATTEMPT,
                intended_child_generation_id=SECOND_CHILD,
            )
        admitted = admission(self.operation, proposed)
        store = OperationAdmissionStoreRequestV3(
            self.root, self.operation, admitted, proposed
        )
        return CrossLedgerOrderRequestV1(
            self.root, self.durable_enrollment, store
        )

    def persist(self, second: bool = False):
        """Persist or replay one ordered admission."""
        return persist_or_replay_cross_ledger_ordered_admission_v1(
            self.request(second)
        )
