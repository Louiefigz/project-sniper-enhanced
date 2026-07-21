"""Exact schema and structural binding tests for V3 operation admission."""

from __future__ import annotations

import dataclasses
import hashlib
import unittest

from _common import pl  # noqa: F401
from _operation_admission_fixture import (
    AUTHORITY,
    CHILD,
    REPAIR_REQUEST,
    TIMESTAMP,
    admission,
    decoded,
    initialize_operation,
    proposal,
    quality_operation,
    resigned,
)
from headless.operation_admission_binding import (
    OPERATION_ADMISSION_STATUS,
    OperationAdmissionBindingError,
    bind_operation_admission_v3,
    build_operation_admission_v3,
    require_operation_admission_execution_authorized,
)
from headless.operation_admission_schema import (
    OperationAdmissionSchemaError,
    parse_operation_admission_v3,
    validate_operation_admission_v3,
)
from headless.operation_wire import canonical


class OperationAdmissionV3SchemaTests(unittest.TestCase):
    def test_initialize_has_typed_null_parent_and_no_quality_identity(
        self,
    ) -> None:
        operation = initialize_operation()
        value = admission(operation)
        parsed = parse_operation_admission_v3(value.document_json)
        validate_operation_admission_v3(parsed)
        self.assertIsNone(parsed.expected_parent)
        self.assertIsNone(parsed.quality_request)
        self.assertEqual(parsed.operation.kind, "initialize")
        self.assertEqual(parsed.unit_id, operation.unit_id)
        self.assertEqual(parsed.first_submitted_at, TIMESTAMP)

    def test_quality_pass_retains_exact_parent_and_nested_request_identity(
        self,
    ) -> None:
        operation = quality_operation()
        value = admission(operation)
        self.assertEqual(value.authority_id, AUTHORITY)
        self.assertEqual(value.intended_child_generation_id, CHILD)
        self.assertEqual(value.expected_parent, operation.expected_parent)
        self.assertEqual(
            value.quality_request.request_digest,
            operation.quality_pass.request_digest,
        )
        self.assertEqual(
            value.quality_request.repair_request_id, REPAIR_REQUEST
        )
        self.assertEqual(
            value.operation.artifact.sha256,
            hashlib.sha256(operation.document_json).hexdigest(),
        )
        self.assertEqual(
            value.operation.artifact.size_bytes, len(operation.document_json)
        )
        self.assertEqual(
            value.operation.operation_digest, operation.operation_digest
        )

    def test_wire_is_exact_closed_canonical_and_timestamp_has_one_form(
        self,
    ) -> None:
        value = admission(quality_operation())
        extra = decoded(value.document_json)
        extra["executionAuthorized"] = False
        cases = (
            value.document_json + b"\n",
            decoded(value.document_json),
            canonical(extra),
        )
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(
                OperationAdmissionSchemaError
            ):
                parse_operation_admission_v3(raw)
        for timestamp in (
            "2026-07-19T12:34:56+00:00",
            "2026-07-19T12:34:56.000000Z",
            "2026-02-30T12:34:56Z",
        ):
            document = decoded(value.document_json)
            document["firstSubmittedAt"] = timestamp
            with self.subTest(timestamp=timestamp), self.assertRaises(
                OperationAdmissionSchemaError
            ):
                parse_operation_admission_v3(resigned(document))

    def test_request_identity_covers_semantics_not_admission_created_fields(
        self,
    ) -> None:
        value = admission(quality_operation())
        fields = (
            ("unitId", "77777777-7777-4777-8777-777777777777"),
            ("buildId", "build-other"),
            ("releaseId", "release-other"),
            ("executionPolicyId", "0" * 64),
        )
        for key, replacement in fields:
            document = decoded(value.document_json)
            document[key] = replacement
            stale = canonical(document)
            with self.subTest(key=key), self.assertRaisesRegex(
                OperationAdmissionSchemaError, "identity"
            ):
                parse_operation_admission_v3(stale)
        replay_fields = (
            ("idempotencyKey", "77777777-7777-4777-8777-777777777777"),
            ("attemptId", "77777777-7777-4777-8777-777777777777"),
            (
                "intendedChildGenerationId",
                "77777777-7777-4777-8777-777777777777",
            ),
            ("firstSubmittedAt", "2026-07-19T12:35:00Z"),
        )
        for key, replacement in replay_fields:
            document = decoded(value.document_json)
            document[key] = replacement
            replay = parse_operation_admission_v3(canonical(document))
            self.assertEqual(
                replay.request_identity_digest, value.request_identity_digest
            )


class OperationAdmissionV3BindingTests(unittest.TestCase):
    def test_valid_binding_is_structural_and_never_authorizing(self) -> None:
        operation = quality_operation()
        proposed = proposal(operation)
        value = admission(operation, proposed)
        report = bind_operation_admission_v3(operation, value, proposed)
        self.assertEqual(report.status, OPERATION_ADMISSION_STATUS)
        self.assertTrue(report.exact_admission_bytes_reparsed)
        self.assertTrue(report.operation_artifact_bytes_bound)
        self.assertTrue(report.unit_parent_and_quality_bound)
        self.assertTrue(report.replay_identities_bound)
        self.assertTrue(report.child_identity_bound)
        self.assertFalse(report.durable_store_reobserved)
        self.assertFalse(report.runtime_verified)
        self.assertFalse(report.execution_authorized)
        self.assertFalse(report.publication_authorized)
        with self.assertRaises(OperationAdmissionBindingError):
            require_operation_admission_execution_authorized(report)
        forged = dataclasses.replace(
            report, execution_authorized=True, publication_authorized=True
        )
        with self.assertRaises(OperationAdmissionBindingError):
            require_operation_admission_execution_authorized(forged)

    def test_builder_rejects_proposal_parent_or_policy_drift(self) -> None:
        operation = quality_operation()
        for proposed in (
            dataclasses.replace(proposal(operation), expected_parent=None),
            dataclasses.replace(
                proposal(operation), execution_policy_id="0" * 64
            ),
        ):
            with self.subTest(proposed=proposed), self.assertRaises(
                OperationAdmissionBindingError
            ):
                build_operation_admission_v3(
                    operation, proposed, "operations/operation.json"
                )

    def test_initialize_and_quality_admission_modes_cannot_be_hybridized(
        self,
    ) -> None:
        operation = initialize_operation()
        value = admission(operation)
        document = decoded(value.document_json)
        document["operation"]["kind"] = "quality-pass"
        with self.assertRaises(OperationAdmissionSchemaError):
            parse_operation_admission_v3(resigned(document))


if __name__ == "__main__":
    unittest.main(verbosity=2)
