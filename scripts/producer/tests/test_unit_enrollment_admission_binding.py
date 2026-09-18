"""Binding tests for reobserved enrollment and durable V3 admission."""

from __future__ import annotations

import dataclasses
import os
import tempfile
import unittest

from _common import pl  # noqa: F401
from _operation_admission_fixture import (
    admission,
    initialize_operation,
    proposal,
    quality_operation,
)
from _unit_enrollment_fixture import enrollment, enrollment_proposal
from headless.operation_admission_store import (
    persist_or_replay_operation_admission_v3,
)
from headless.operation_admission_store_types import (
    OperationAdmissionStoreRequestV3,
)
from headless.unit_enrollment_admission_binding import (
    UnitEnrollmentAdmissionBindingError,
    bind_reobserved_unit_enrollment_to_admission_v1,
    require_enrolled_admission_execution_authorized,
)
from headless.unit_enrollment_admission_types import (
    CROSS_LEDGER_PROSPECTIVE_ORDER,
    ENROLLED_ADMISSION_STATUS,
    UNIT_ENROLLMENT_AUTHORITY,
)
from headless.unit_enrollment_store import (
    persist_or_replay_prospective_unit_enrollment_v1,
    reobserve_prospective_unit_enrollment_v1,
)
from headless.unit_enrollment_store_types import (
    UnitEnrollmentReadRequestV1,
    UnitEnrollmentStoreRequestV1,
)


class _AlwaysEqual(str):
    def __eq__(self, other: object) -> bool:
        return True

    __hash__ = str.__hash__


def _durable_pair(
    root: str, operation: object, enrolled: object = None
) -> tuple:
    proposed_enrollment = enrolled or enrollment_proposal(operation)
    enrollment_value = enrollment(operation, proposed_enrollment)
    enrollment_request = UnitEnrollmentStoreRequestV1(root, enrollment_value)
    persist_or_replay_prospective_unit_enrollment_v1(enrollment_request)
    read = reobserve_prospective_unit_enrollment_v1(
        UnitEnrollmentReadRequestV1(
            root,
            enrollment_value.authority_id,
            enrollment_value.enrollment_key,
        )
    )
    proposed_admission = proposal(operation)
    admission_value = admission(operation, proposed_admission)
    admitted = persist_or_replay_operation_admission_v3(
        OperationAdmissionStoreRequestV3(
            root, operation, admission_value, proposed_admission
        )
    )
    return read, admitted


class UnitEnrollmentAdmissionBindingTests(unittest.TestCase):
    def _root(self):
        temporary = tempfile.TemporaryDirectory()
        root = os.path.realpath(temporary.name)
        os.chmod(root, 0o700)
        self.addCleanup(temporary.cleanup)
        return root

    def test_reobserved_quality_unit_closes_only_enrollment_authority(
        self,
    ) -> None:
        enrolled, admitted = _durable_pair(self._root(), quality_operation())
        result = bind_reobserved_unit_enrollment_to_admission_v1(
            enrolled, admitted
        )
        self.assertEqual(result.status, ENROLLED_ADMISSION_STATUS)
        self.assertEqual(
            result.closed_requirements, (UNIT_ENROLLMENT_AUTHORITY,)
        )
        self.assertNotIn(
            UNIT_ENROLLMENT_AUTHORITY,
            {row.code for row in result.unresolved_authority},
        )
        self.assertIn(
            CROSS_LEDGER_PROSPECTIVE_ORDER,
            {row.code for row in result.unresolved_authority},
        )
        self.assertTrue(result.enrollment_bytes_reobserved)
        self.assertTrue(result.admission_and_operation_bytes_reobserved)
        self.assertTrue(result.global_unit_uniqueness_verified)
        self.assertTrue(result.authority_unit_and_lineage_bound)
        self.assertTrue(result.enrollment_clock_not_after_first_submission)
        self.assertTrue(result.operation_eligibility_and_scope_bound)
        self.assertTrue(result.release_build_and_policy_bound)
        self.assertFalse(result.cross_ledger_order_receipt_verified)
        self.assertFalse(result.execution_authorized)
        self.assertFalse(result.publication_authorized)

    def test_initialize_unit_binds_snapshot_lineage_and_empty_lane_scope(
        self,
    ) -> None:
        enrolled, admitted = _durable_pair(
            self._root(), initialize_operation()
        )
        result = bind_reobserved_unit_enrollment_to_admission_v1(
            enrolled, admitted
        )
        self.assertTrue(result.authority_unit_and_lineage_bound)
        self.assertTrue(result.operation_eligibility_and_scope_bound)

    def test_lineage_scope_release_unit_and_clock_mismatches_fail_closed(
        self,
    ) -> None:
        operation = quality_operation()
        base = enrollment_proposal(operation)
        cases = (
            dataclasses.replace(
                base,
                project=dataclasses.replace(
                    base.project, project_lineage_digest="4" * 64
                ),
            ),
            dataclasses.replace(
                base,
                eligibility=dataclasses.replace(
                    base.eligibility, allowed_lanes=("audioTrack",)
                ),
            ),
            dataclasses.replace(
                base,
                eligibility=dataclasses.replace(
                    base.eligibility, release_id="release-other"
                ),
            ),
            dataclasses.replace(
                base, unit_id="eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
            ),
            dataclasses.replace(
                base,
                clock=dataclasses.replace(
                    base.clock, observed_at="2026-07-19T12:34:57Z"
                ),
            ),
        )
        for proposed in cases:
            with self.subTest(proposed=proposed):
                enrolled, admitted = _durable_pair(
                    self._root(), operation, proposed
                )
                with self.assertRaises(UnitEnrollmentAdmissionBindingError):
                    bind_reobserved_unit_enrollment_to_admission_v1(
                        enrolled, admitted
                    )

    def test_forged_diagnostics_and_hostile_equality_never_bind_or_authorize(
        self,
    ) -> None:
        enrolled, admitted = _durable_pair(self._root(), quality_operation())
        hostile = dataclasses.replace(
            enrolled, status=_AlwaysEqual(enrolled.status)
        )
        forged_enrollment = dataclasses.replace(
            enrolled, operation_admission_bound=True
        )
        forged_admission = dataclasses.replace(
            admitted, execution_authorized=True
        )
        for left, right in (
            (hostile, admitted),
            (forged_enrollment, admitted),
            (enrolled, forged_admission),
        ):
            with self.subTest(left=left, right=right), self.assertRaises(
                UnitEnrollmentAdmissionBindingError
            ):
                bind_reobserved_unit_enrollment_to_admission_v1(left, right)
        result = bind_reobserved_unit_enrollment_to_admission_v1(
            enrolled, admitted
        )
        for value in (
            result,
            dataclasses.replace(result, execution_authorized=True),
        ):
            with self.assertRaises(UnitEnrollmentAdmissionBindingError):
                require_enrolled_admission_execution_authorized(value)


if __name__ == "__main__":
    unittest.main(verbosity=2)
