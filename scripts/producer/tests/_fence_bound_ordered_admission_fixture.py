"""Exact fixture for the work-disabled fence-bound admission controller."""

from __future__ import annotations

import dataclasses
import os
import tempfile

from _operation_admission_fixture import (
    CHILD,
    admission,
    proposal,
    quality_operation,
)
from _unit_enrollment_fixture import enrollment, enrollment_proposal
from headless.active_fence_protocol import (
    bootstrap_active_generation_fence_v1,
)
from headless.cross_ledger_order_types import CrossLedgerOrderRequestV1
from headless.fence_bound_ordered_admission_types import (
    FenceBoundOrderedAdmissionRequestV1,
)
from headless.operation_admission_store_types import (
    OperationAdmissionStoreRequestV3,
)
from headless.unit_enrollment_store import (
    persist_or_replay_prospective_unit_enrollment_v1,
)
from headless.unit_enrollment_store_types import UnitEnrollmentStoreRequestV1

SECOND_ATTEMPT = "99999999-9999-4999-8999-999999999999"
SECOND_IDEMPOTENCY = "88888888-8888-4888-8888-888888888888"
SECOND_CHILD = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
CHANGED_CHILD = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


class FenceBoundOrderedAdmissionFixture:
    """Private authority with FENCE bootstrapped but no enrolled unit."""

    def __init__(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(
            os.path.join(self.temporary.name, "authority")
        )
        os.mkdir(self.root, 0o700)
        os.chmod(self.root, 0o700)
        self.operation = quality_operation()
        self.enrollment = enrollment(
            self.operation, enrollment_proposal(self.operation)
        )
        self.proposal = proposal(self.operation)
        self.admitted = admission(self.operation, self.proposal)
        bootstrap_active_generation_fence_v1(
            self.root, self.admitted.authority_id
        )

    def close(self) -> None:
        """Remove the temporary authority root."""
        self.temporary.cleanup()

    def request(
        self, proposed: object | None = None
    ) -> FenceBoundOrderedAdmissionRequestV1:
        """Build a controller request for the selected exact proposal."""
        selected = proposed or self.proposal
        admitted = admission(self.operation, selected)
        store = OperationAdmissionStoreRequestV3(
            self.root, self.operation, admitted, selected
        )
        return FenceBoundOrderedAdmissionRequestV1(self.enrollment, store)

    def changed_child_request(self) -> FenceBoundOrderedAdmissionRequestV1:
        """Reuse the first attempt while changing its requested child."""
        changed = dataclasses.replace(
            self.proposal, intended_child_generation_id=CHANGED_CHILD
        )
        return self.request(changed)

    def second_request(self) -> FenceBoundOrderedAdmissionRequestV1:
        """Build a wholly distinct attempt for the same enrolled unit."""
        second = dataclasses.replace(
            self.proposal,
            idempotency_key=SECOND_IDEMPOTENCY,
            attempt_id=SECOND_ATTEMPT,
            intended_child_generation_id=SECOND_CHILD,
        )
        return self.request(second)

    def cross_request(
        self, request: FenceBoundOrderedAdmissionRequestV1 | None = None
    ) -> CrossLedgerOrderRequestV1:
        """Persist enrollment and project one standalone cross request."""
        selected = request or self.request()
        durable = persist_or_replay_prospective_unit_enrollment_v1(
            UnitEnrollmentStoreRequestV1(self.root, self.enrollment)
        )
        return CrossLedgerOrderRequestV1(
            self.root, durable, selected.admission
        )

    def path(self, name: str) -> str:
        """Return one test-owned authority path."""
        return os.path.join(self.root, name)

    @property
    def attempt_id(self) -> str:
        """Return the primary exact attempt UUID."""
        return self.admitted.attempt_id

    @property
    def child_id(self) -> str:
        """Return the primary exact intended child UUID."""
        return CHILD
