"""Forged diagnostics and temporal edge attacks on enrolled admission."""

from __future__ import annotations

import dataclasses
import os
import tempfile
import unittest
from unittest import mock

from _common import pl  # noqa: F401
from _operation_admission_fixture import quality_operation
from _unit_enrollment_fixture import enrollment, enrollment_proposal
from test_enrolled_admitted_quality_pass_composition import (
    EnrolledAdmittedQualityPassCompositionTests as _CompositionCase,
)
from test_unit_enrollment_admission_binding import _durable_pair
from headless import (
    enrolled_admitted_quality_pass_composition as composition_module,
)
from headless.enrolled_admitted_quality_pass_types import (
    EnrolledAdmittedQualityPassCompositionError,
    EnrolledAdmittedQualityPassCompositionRequestV1,
)
from headless.operation_contract import parse_headless_mp4_operation_v1
from headless.unit_enrollment_admission_binding import (
    UnitEnrollmentAdmissionBindingError,
    bind_reobserved_unit_enrollment_to_admission_v1,
)
from headless.unit_enrollment_admission_types import (
    CROSS_LEDGER_PROSPECTIVE_ORDER,
)


class _AlwaysEqual(str):
    def __eq__(self, other: object) -> bool:
        return True

    def __ne__(self, other: object) -> bool:
        return False

    __hash__ = str.__hash__


def _with_materialization(
    case: _CompositionCase,
    request: EnrolledAdmittedQualityPassCompositionRequestV1,
    name: str,
) -> EnrolledAdmittedQualityPassCompositionRequestV1:
    materialization = case.fixture.root / name
    materialization.mkdir(mode=0o700)
    inspection = dataclasses.replace(
        request.admitted.inspection,
        current_materialization_root=str(materialization),
    )
    return dataclasses.replace(
        request,
        admitted=dataclasses.replace(request.admitted, inspection=inspection),
    )


class UnitEnrollmentValidationAdversarialTests(unittest.TestCase):
    def _root(self) -> str:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = os.path.realpath(temporary.name)
        os.chmod(root, 0o700)
        return root

    def _composition_case(self) -> _CompositionCase:
        case = _CompositionCase(
            methodName=(
                "test_enrollment_closes_only_unit_authority_"
                "after_durable_admission"
            )
        )
        case.setUp()
        self.addCleanup(case.tearDown)
        return case

    def test_every_durable_enrollment_flag_and_identity_is_revalidated(
        self,
    ) -> None:
        enrolled, admitted = _durable_pair(self._root(), quality_operation())
        binding = enrolled.structural_binding
        cases = (
            dataclasses.replace(enrolled, created=1),
            dataclasses.replace(enrolled, record_id="0" * 64),
            dataclasses.replace(enrolled, closed_requirements=()),
            dataclasses.replace(enrolled, unresolved_authority=()),
            dataclasses.replace(enrolled, enrollment_bytes_reobserved=False),
            dataclasses.replace(
                enrolled,
                structural_binding=dataclasses.replace(
                    binding, feedback_and_outcome_absent=False
                ),
            ),
        )
        for forged in cases:
            with self.subTest(forged=forged), self.assertRaises(
                UnitEnrollmentAdmissionBindingError
            ):
                bind_reobserved_unit_enrollment_to_admission_v1(
                    forged, admitted
                )

    def test_every_durable_admission_flag_and_identity_is_revalidated(
        self,
    ) -> None:
        enrolled, admitted = _durable_pair(self._root(), quality_operation())
        binding = admitted.structural_binding
        cases = (
            dataclasses.replace(admitted, created=1),
            dataclasses.replace(admitted, record_id="0" * 64),
            dataclasses.replace(admitted, closed_requirements=()),
            dataclasses.replace(admitted, unresolved_authority=()),
            dataclasses.replace(
                admitted, durable_operation_bytes_reobserved=False
            ),
            dataclasses.replace(
                admitted,
                structural_binding=dataclasses.replace(
                    binding, exact_admission_bytes_reparsed=False
                ),
            ),
        )
        for forged in cases:
            with self.subTest(forged=forged), self.assertRaises(
                UnitEnrollmentAdmissionBindingError
            ):
                bind_reobserved_unit_enrollment_to_admission_v1(
                    enrolled, forged
                )

    def test_promotion_rejects_forged_enrolled_admission_diagnostics(
        self,
    ) -> None:
        case = self._composition_case()
        request = case._request()
        original = composition_module._bind
        mutators = (
            lambda value: dataclasses.replace(
                value, status=_AlwaysEqual(value.status)
            ),
            lambda value: dataclasses.replace(value, closed_requirements=()),
            lambda value: dataclasses.replace(value, unresolved_authority=()),
            lambda value: dataclasses.replace(
                value, global_unit_uniqueness_verified=False
            ),
            lambda value: dataclasses.replace(
                value, cross_ledger_order_receipt_verified=False
            ),
            lambda value: dataclasses.replace(
                value, execution_authorized=True
            ),
        )
        for index, mutate in enumerate(mutators):
            attempted = _with_materialization(
                case, request, f"forged-materialization-{index}"
            )

            def forged(enrolled: object, admitted: object) -> object:
                return mutate(original(enrolled, admitted))

            with self.subTest(mutate=mutate), mock.patch.object(
                composition_module, "_bind", side_effect=forged
            ), self.assertRaises(EnrolledAdmittedQualityPassCompositionError):
                case._inspect(attempted)
        final_request = _with_materialization(
            case, request, "valid-materialization"
        )
        result = case._inspect(final_request)
        codes = {row.code for row in result.unresolved_authority}
        self.assertNotIn(CROSS_LEDGER_PROSPECTIVE_ORDER, codes)
        self.assertTrue(result.cross_ledger_order_receipt_verified)
        self.assertFalse(result.execution_authorized)

    def test_same_second_order_succeeds_from_durable_receipt(
        self,
    ) -> None:
        case = self._composition_case()
        operation = parse_headless_mp4_operation_v1(case.operation_json)
        proposed = enrollment_proposal(operation)
        same_second = dataclasses.replace(
            proposed,
            clock=dataclasses.replace(
                proposed.clock, observed_at="2026-07-19T12:34:56Z"
            ),
        )
        request = case._request(enrollment(operation, same_second))
        result = case._inspect(request)
        self.assertTrue(result.cross_ledger_order_receipt_verified)
        self.assertFalse(result.execution_authorized)


if __name__ == "__main__":
    unittest.main(verbosity=2)
