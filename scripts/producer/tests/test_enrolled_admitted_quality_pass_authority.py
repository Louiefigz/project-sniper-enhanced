"""Authority failures for enrolled and durably admitted quality passes."""

from __future__ import annotations

import dataclasses
import unittest
from unittest.mock import patch

from _common import pl  # noqa: F401
from test_enrolled_admitted_quality_pass_composition import (
    EnrolledAdmittedQualityPassCompositionTests as _Fixture,
)
from headless.admitted_quality_pass_composition import (
    inspect_durable_admitted_quality_pass_composition,
)
from headless.enrolled_admitted_quality_pass_composition import (
    require_enrolled_admitted_render_start_authorized,
)
from headless.enrolled_admitted_quality_pass_types import (
    EnrolledAdmittedQualityPassCompositionError,
)
from headless.operation_admission_store import (
    persist_or_replay_operation_admission_v3,
)
from headless.operation_admission_store_types import (
    OperationAdmissionStoreRequestV3,
)
from headless.operation_contract import parse_headless_mp4_operation_v1


class EnrolledAdmittedQualityPassAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.case = _Fixture(methodName="runTest")
        self.case.setUp()

    def tearDown(self) -> None:
        self.case.tearDown()

    def test_preexisting_admission_is_permanently_rejected(self) -> None:
        request = self.case._request()
        operation = parse_headless_mp4_operation_v1(self.case.operation_json)
        persist_or_replay_operation_admission_v3(
            OperationAdmissionStoreRequestV3(
                str(self.case.fixture.authority),
                operation,
                request.admitted.admission,
                request.admitted.proposal,
            )
        )
        for _attempt in range(2):
            with self.assertRaises(
                EnrolledAdmittedQualityPassCompositionError
            ):
                self.case._inspect(request)

    def test_forged_nested_authority_and_output_flags_never_authorize(
        self,
    ) -> None:
        request = self.case._request()
        target = (
            "headless.enrolled_admitted_quality_pass_composition."
            "inspect_durable_admitted_quality_pass_composition"
        )

        def forged(value: object, durable: object):
            result = inspect_durable_admitted_quality_pass_composition(
                value, durable
            )
            return dataclasses.replace(result, execution_authorized=True)

        with patch(target, side_effect=forged), self.assertRaises(
            EnrolledAdmittedQualityPassCompositionError
        ):
            self.case._inspect(request)
        retry_root = self.case.fixture.root / "forged-retry-materialization"
        retry_root.mkdir(mode=0o700)
        retry_inspection = dataclasses.replace(
            request.admitted.inspection,
            current_materialization_root=str(retry_root),
        )
        retry = dataclasses.replace(
            request,
            admitted=dataclasses.replace(
                request.admitted, inspection=retry_inspection
            ),
        )
        result = self.case._inspect(retry)
        forged_result = dataclasses.replace(
            result, execution_authorized=True, publication_authorized=True
        )
        for value in (result, forged_result, object()):
            with self.assertRaises(
                EnrolledAdmittedQualityPassCompositionError
            ):
                require_enrolled_admitted_render_start_authorized(value)

    def test_enrolled_path_does_not_replay_the_public_v3_writer(self) -> None:
        target = (
            "headless.admitted_quality_pass_composition."
            "persist_or_replay_operation_admission_v3"
        )
        with patch(target, side_effect=AssertionError("redundant replay")):
            result = self.case._inspect(self.case._request())
        self.assertTrue(result.admission_created)
        self.assertFalse(result.admitted_composition.admission_created)


if __name__ == "__main__":
    unittest.main(verbosity=2)
