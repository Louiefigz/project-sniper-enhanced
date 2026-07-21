"""Closed-schema and structural tests for prospective unit enrollment."""

from __future__ import annotations

import dataclasses
import json
import unittest

from _common import pl  # noqa: F401
from _operation_admission_fixture import (
    initialize_operation,
    quality_operation,
)
from _unit_enrollment_fixture import enrollment, enrollment_proposal
from headless.operation_wire import canonical
from headless.unit_enrollment_binding import (
    UnitEnrollmentBindingError,
    bind_prospective_unit_enrollment_v1,
    build_prospective_unit_enrollment_v1,
    require_unit_enrollment_execution_authorized,
)
from headless.unit_enrollment_schema import (
    UnitEnrollmentSchemaError,
    enrollment_identity_digest_v1,
    parse_prospective_unit_enrollment_v1,
    validate_prospective_unit_enrollment_v1,
)


class _AlwaysEqual(str):
    def __eq__(self, other: object) -> bool:
        return True

    __hash__ = str.__hash__


def _resign(document: dict) -> bytes:
    document.pop("enrollmentIdentityDigest", None)
    document["enrollmentIdentityDigest"] = enrollment_identity_digest_v1(
        document
    )
    return canonical(document)


class UnitEnrollmentV1Tests(unittest.TestCase):
    def test_quality_and_initialize_enrollments_are_disjoint_and_closed(
        self,
    ) -> None:
        quality = enrollment(quality_operation())
        initialize = enrollment(initialize_operation())
        self.assertEqual(quality.eligibility.operation, "quality-pass")
        self.assertEqual(quality.eligibility.allowed_lanes, ("graphicsTrack",))
        self.assertEqual(initialize.eligibility.operation, "initialize")
        self.assertEqual(initialize.eligibility.allowed_lanes, ())
        self.assertNotEqual(
            quality.project.project_lineage_digest,
            initialize.project.project_lineage_digest,
        )
        validate_prospective_unit_enrollment_v1(quality)
        validate_prospective_unit_enrollment_v1(initialize)

    def test_binding_is_explicitly_non_authorizing(self) -> None:
        result = bind_prospective_unit_enrollment_v1(
            enrollment(quality_operation())
        )
        self.assertTrue(result.feedback_and_outcome_absent)
        self.assertTrue(result.operation_eligibility_and_scope_bound)
        self.assertFalse(result.durable_store_reobserved)
        self.assertFalse(result.operation_admission_bound)
        self.assertFalse(result.execution_authorized)
        self.assertFalse(result.publication_authorized)
        for value in (
            result,
            dataclasses.replace(result, execution_authorized=True),
        ):
            with self.subTest(value=value), self.assertRaises(
                UnitEnrollmentBindingError
            ):
                require_unit_enrollment_execution_authorized(value)

    def test_feedback_outcome_and_unknown_fields_are_impossible(self) -> None:
        original = enrollment(quality_operation())
        for field, value in (
            ("feedback", "make it yellow"),
            ("outcome", "accepted"),
            ("success", True),
        ):
            document = json.loads(original.document_json)
            document[field] = value
            with self.subTest(field=field), self.assertRaises(
                UnitEnrollmentSchemaError
            ):
                parse_prospective_unit_enrollment_v1(_resign(document))

    def test_scope_clock_and_identity_forms_fail_closed(self) -> None:
        original = enrollment(quality_operation())
        cases = []
        clock = json.loads(original.document_json)
        clock["enrollmentClock"]["observedAt"] = "2026-07-19T12:34:55+00:00"
        cases.append(clock)
        lanes = json.loads(original.document_json)
        lanes["operationEligibility"]["scope"]["allowedLanes"] = [
            "graphicsTrack",
            "audioTrack",
        ]
        cases.append(lanes)
        empty = json.loads(original.document_json)
        empty["operationEligibility"]["scope"]["allowedLanes"] = []
        cases.append(empty)
        aliases = json.loads(original.document_json)
        aliases["enrollmentKey"] = aliases["unitId"]
        cases.append(aliases)
        for document in cases:
            with self.subTest(document=document), self.assertRaises(
                UnitEnrollmentSchemaError
            ):
                parse_prospective_unit_enrollment_v1(_resign(document))

    def test_direct_construction_and_hostile_equality_are_rejected(
        self,
    ) -> None:
        value = enrollment(quality_operation())
        forged = dataclasses.replace(value, authority_id=_AlwaysEqual("other"))
        hostile_proposal = dataclasses.replace(
            enrollment_proposal(quality_operation()),
            authority_id=_AlwaysEqual("authority-mp4-v1"),
        )
        with self.assertRaises(UnitEnrollmentSchemaError):
            validate_prospective_unit_enrollment_v1(forged)
        with self.assertRaises(UnitEnrollmentBindingError):
            build_prospective_unit_enrollment_v1(hostile_proposal)


if __name__ == "__main__":
    unittest.main(verbosity=2)
