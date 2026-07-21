"""Substitution and hostile-construction tests for V3 operation admission."""

from __future__ import annotations

import dataclasses
import hashlib
import unittest

from _common import pl  # noqa: F401
from _operation_admission_fixture import (
    CHILD,
    OTHER,
    admission,
    decoded,
    proposal,
    quality_operation,
    resigned,
)
from headless.operation_admission_binding import (
    OperationAdmissionBindingError,
    bind_operation_admission_v3,
)
from headless.operation_admission_schema import (
    OperationAdmissionSchemaError,
    parse_operation_admission_v3,
    validate_operation_admission_v3,
)
from headless.operation_admission_types import OperationAdmissionProposalV3
from headless.operation_wire import canonical


class _AlwaysEqual(str):
    def __eq__(self, other: object) -> bool:
        return True

    def __hash__(self) -> int:
        return str.__hash__(self)


def _reparsed(
    value: object, path: tuple[str, ...], replacement: object
) -> object:
    document = decoded(value.document_json)
    target = document
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement
    return parse_operation_admission_v3(resigned(document))


class OperationAdmissionSubstitutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.operation = quality_operation()
        self.proposed = proposal(self.operation)
        self.admission = admission(self.operation, self.proposed)

    def _reject_record(
        self, path: tuple[str, ...], replacement: object
    ) -> None:
        changed = _reparsed(self.admission, path, replacement)
        with self.assertRaises(OperationAdmissionBindingError):
            bind_operation_admission_v3(self.operation, changed, self.proposed)

    def test_unit_substitution_rejects_even_when_record_identity_is_recomputed(
        self,
    ) -> None:
        self._reject_record(("unitId",), OTHER)
        other_operation = quality_operation(OTHER)
        with self.assertRaises(OperationAdmissionBindingError):
            bind_operation_admission_v3(
                other_operation, self.admission, self.proposed
            )

    def test_parent_stringification_and_parent_field_drift_reject(
        self,
    ) -> None:
        document = decoded(self.admission.document_json)
        document["expectedParent"] = canonical(
            document["expectedParent"]
        ).decode()
        with self.assertRaises(OperationAdmissionSchemaError):
            parse_operation_admission_v3(resigned(document))
        document = decoded(self.admission.document_json)
        document["expectedParent"]["path"] = "forged-parent.json"
        with self.assertRaises(OperationAdmissionSchemaError):
            parse_operation_admission_v3(resigned(document))
        self._reject_record(("expectedParent", "commitDigest"), "0" * 64)

    def test_replay_attempt_and_child_substitutions_reject(self) -> None:
        for path, replacement in (
            (("idempotencyKey",), OTHER),
            (("attemptId",), OTHER),
            (("intendedChildGenerationId",), OTHER),
            (("firstSubmittedAt",), "2026-07-19T12:35:00Z"),
        ):
            with self.subTest(path=path):
                self._reject_record(path, replacement)
        for proposed in (
            dataclasses.replace(self.proposed, idempotency_key=OTHER),
            dataclasses.replace(self.proposed, attempt_id=OTHER),
            dataclasses.replace(
                self.proposed, intended_child_generation_id=OTHER
            ),
            dataclasses.replace(self.proposed, build_id="build-other"),
            dataclasses.replace(self.proposed, execution_policy_id="0" * 64),
        ):
            with self.subTest(proposed=proposed), self.assertRaises(
                OperationAdmissionBindingError
            ):
                bind_operation_admission_v3(
                    self.operation, self.admission, proposed
                )

    def test_operation_artifact_and_domain_digest_substitutions_reject(
        self,
    ) -> None:
        cases = (
            (("operation", "artifact", "sha256"), "0" * 64),
            (
                ("operation", "artifact", "sizeBytes"),
                len(self.operation.document_json) + 1,
            ),
            (("operation", "operationDigest"), "0" * 64),
            (("qualityRequest", "requestDigest"), "0" * 64),
            (("qualityRequest", "repairRequestId"), OTHER),
        )
        for path, replacement in cases:
            with self.subTest(path=path):
                self._reject_record(path, replacement)

    def test_build_release_authority_and_policy_drift_reject(self) -> None:
        cases = (
            (("authorityId",), "authority-other"),
            (("releaseId",), "release-other"),
            (("buildId",), "build-other"),
            (("executionPolicyId",), "0" * 64),
        )
        for path, replacement in cases:
            if path == ("authorityId",):
                document = decoded(self.admission.document_json)
                document["authorityId"] = replacement
                document["expectedParent"]["authorityId"] = replacement
                changed = parse_operation_admission_v3(resigned(document))
                with self.assertRaises(OperationAdmissionBindingError):
                    bind_operation_admission_v3(
                        self.operation, changed, self.proposed
                    )
                continue
            with self.subTest(path=path):
                self._reject_record(path, replacement)

    def test_operation_byte_mutation_rejects_old_admission(self) -> None:
        other_operation = quality_operation(OTHER)
        self.assertNotEqual(
            hashlib.sha256(other_operation.document_json).hexdigest(),
            self.admission.operation.artifact.sha256,
        )
        with self.assertRaises(OperationAdmissionBindingError):
            bind_operation_admission_v3(
                other_operation,
                self.admission,
                dataclasses.replace(self.proposed, unit_id=OTHER),
            )

    def test_directly_forged_operation_fields_reject(self) -> None:
        forged = dataclasses.replace(self.operation, operation_digest="0" * 64)
        with self.assertRaises(OperationAdmissionBindingError):
            bind_operation_admission_v3(forged, self.admission, self.proposed)


class OperationAdmissionHostileConstructionTests(unittest.TestCase):
    def test_hostile_equality_and_direct_construction_cannot_cross_boundary(
        self,
    ) -> None:
        operation = quality_operation()
        proposed = proposal(operation)
        value = admission(operation, proposed)
        forged_admission = dataclasses.replace(
            value, build_id=_AlwaysEqual(value.build_id)
        )
        with self.assertRaises(OperationAdmissionSchemaError):
            validate_operation_admission_v3(forged_admission)
        forged_proposal = dataclasses.replace(
            proposed, build_id=_AlwaysEqual(proposed.build_id)
        )
        with self.assertRaises(OperationAdmissionBindingError):
            bind_operation_admission_v3(operation, value, forged_proposal)

    def test_uuid_roles_and_parent_child_cannot_alias(self) -> None:
        document = decoded(admission(quality_operation()).document_json)
        document["attemptId"] = document["idempotencyKey"]
        with self.assertRaises(OperationAdmissionSchemaError):
            parse_operation_admission_v3(resigned(document))
        document = decoded(admission(quality_operation()).document_json)
        document["intendedChildGenerationId"] = document["expectedParent"][
            "generationId"
        ]
        with self.assertRaises(OperationAdmissionSchemaError):
            parse_operation_admission_v3(resigned(document))

    def test_proposal_must_be_exact_type(self) -> None:
        operation = quality_operation()
        value = admission(operation)
        direct = object.__new__(OperationAdmissionProposalV3)
        self.assertIs(type(direct), OperationAdmissionProposalV3)
        with self.assertRaises(OperationAdmissionBindingError):
            bind_operation_admission_v3(operation, value, direct)
        self.assertEqual(value.intended_child_generation_id, CHILD)


if __name__ == "__main__":
    unittest.main(verbosity=2)
