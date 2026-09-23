"""Adversarial tests for prospective enrollment plus V3 admission."""

from __future__ import annotations

import dataclasses
import json
import os
import unittest
from unittest.mock import patch

from _approved_parent_loader_fixture import ApprovedParentAuthorityFixture
from _approved_parent_loader_values import canonical
from _common import pl  # noqa: F401
from _retired_r0_diagnostics_fixture import historical_diagnostics, assert_retired_inspection
from _unit_enrollment_fixture import enrollment, enrollment_proposal
from test_quality_pass_preflight import _operation
from headless.admitted_quality_pass_composition_types import (
    ADMISSION_BINDING_REQUIREMENT,
    AdmittedQualityPassCompositionRequestV1,
)
from headless.approved_parent_media import ApprovedParentVerifierContextV1
from headless.enrolled_admitted_quality_pass_composition import (
    inspect_enrolled_admitted_quality_pass_composition,
)
from headless.enrolled_admitted_quality_pass_types import (
    ENROLLED_ADMITTED_COMPOSITION_STATUS,
    EnrolledAdmittedQualityPassCompositionError,
    EnrolledAdmittedQualityPassCompositionRequestV1,
)
from headless.operation_admission_binding import build_operation_admission_v3
from headless.operation_admission_types import OperationAdmissionProposalV3
from headless.operation_contract import parse_headless_mp4_operation_v1
from headless.quality_pass_composition_types import (
    QualityPassCompositionInspectionRequestV1,
)
from headless.unit_enrollment_admission_types import (
    CROSS_LEDGER_PROSPECTIVE_ORDER,
    UNIT_ENROLLMENT_AUTHORITY,
)

_CONTEXT = ApprovedParentVerifierContextV1(
    "/not/invoked/ffprobe", "0" * 64, 1.0
)
_IDEMPOTENCY = "77777777-7777-4777-8777-777777777777"
_ATTEMPT = "88888888-8888-4888-8888-888888888888"
_CHILD = "99999999-9999-4999-8999-999999999999"


class EnrolledAdmittedQualityPassCompositionTests(unittest.TestCase):
    def setUp(self) -> None:
        # Inert ledger/promotion seam: no current R0 execution is represented.
        seam = patch("headless.admitted_quality_pass_composition.inspect_quality_pass_composition",
                     side_effect=historical_diagnostics)
        seam.start()
        self.addCleanup(seam.stop)
        self.fixture = ApprovedParentAuthorityFixture()
        self.historical = self.fixture.root / "historical-materialization"
        self.historical.mkdir(mode=0o700)
        self.operation_json = canonical(_operation(self.fixture))
        operation = parse_headless_mp4_operation_v1(self.operation_json)
        authority_raw = (
            json.dumps(
                {
                    "authorityId": operation.expected_parent.authority_id,
                    "schemaVersion": 1,
                },
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("ascii")
        authority_path = self.fixture.authority / "authority.json"
        authority_path.write_bytes(authority_raw)
        authority_path.chmod(0o600)

    def test_real_retired_parent_never_dispatches_or_changes_publication(self) -> None:
        """Real source rejection precedes any enrollment, admission, or rendering."""
        assert_retired_inspection(self, ("unit-enrollments-v1", "operation-admissions-v3"))

    def tearDown(self) -> None:
        self.fixture.close()

    def _request(self, enrolled: object = None):
        operation = parse_headless_mp4_operation_v1(self.operation_json)
        proposed = OperationAdmissionProposalV3(
            operation.expected_parent.authority_id,
            _IDEMPOTENCY,
            _ATTEMPT,
            _CHILD,
            operation.unit_id,
            operation.expected_parent,
            "2026-07-19T12:34:56Z",
            "release-headless-v3",
            "build-headless-v3",
            operation.execution_policy_id,
        )
        admitted = build_operation_admission_v3(
            operation, proposed, "operations/headless-mp4-operation.json"
        )
        inspection = QualityPassCompositionInspectionRequestV1(
            str(self.fixture.authority),
            str(self.fixture.materialization),
            str(self.historical),
            self.operation_json,
            _CONTEXT,
        )
        admitted_request = AdmittedQualityPassCompositionRequestV1(
            inspection, admitted, proposed
        )
        enrollment_value = enrolled or enrollment(
            operation, enrollment_proposal(operation)
        )
        return EnrolledAdmittedQualityPassCompositionRequestV1(
            enrollment_value, admitted_request
        )

    def _inspect(self, request: object):
        with patch(
            "headless.approved_parent_loader.validate_parent_media",
            return_value=self.fixture.base_probe(),
        ):
            return inspect_enrolled_admitted_quality_pass_composition(request)

    def test_enrollment_closes_only_unit_authority_after_durable_admission(
        self,
    ) -> None:
        result = self._inspect(self._request())
        admitted = result.admitted_composition
        composition = admitted.composition
        self.assertEqual(result.status, ENROLLED_ADMITTED_COMPOSITION_STATUS)
        self.assertTrue(result.enrollment_created)
        self.assertTrue(result.admission_created)
        self.assertEqual(
            result.newly_closed_checks,
            (UNIT_ENROLLMENT_AUTHORITY, CROSS_LEDGER_PROSPECTIVE_ORDER),
        )
        self.assertIn(ADMISSION_BINDING_REQUIREMENT, composition.closed_checks)
        self.assertIn(UNIT_ENROLLMENT_AUTHORITY, composition.closed_checks)
        for rows in (
            result.unresolved_authority,
            admitted.unresolved_authority,
            composition.unresolved_authority,
        ):
            self.assertNotIn(
                UNIT_ENROLLMENT_AUTHORITY, {row.code for row in rows}
            )
            self.assertNotIn(
                CROSS_LEDGER_PROSPECTIVE_ORDER, {row.code for row in rows}
            )
        self.assertTrue(result.enrollment_bytes_reobserved)
        self.assertTrue(result.admission_and_operation_bytes_reobserved)
        self.assertTrue(result.global_unit_uniqueness_verified)
        self.assertTrue(result.enrollment_clock_not_after_first_submission)
        self.assertTrue(result.operation_eligibility_and_scope_bound)
        self.assertTrue(result.unit_enrollment_verified)
        self.assertTrue(result.cross_ledger_order_receipt_verified)
        self.assertTrue(admitted.unit_enrollment_verified)
        self.assertFalse(result.operation_runtime_verified)
        self.assertFalse(result.fence_rechecked)
        self.assertFalse(result.execution_authorized)
        self.assertFalse(result.publication_authorized)

    def test_exact_replay_returns_original_enrollment_and_admission(
        self,
    ) -> None:
        request = self._request()
        created = self._inspect(request)
        replay_root = self.fixture.root / "replay-materialization"
        replay_root.mkdir(mode=0o700)
        replay_inspection = dataclasses.replace(
            request.admitted.inspection,
            current_materialization_root=str(replay_root),
        )
        replayed = self._inspect(
            dataclasses.replace(
                request,
                admitted=dataclasses.replace(
                    request.admitted, inspection=replay_inspection
                ),
            )
        )
        self.assertFalse(replayed.enrollment_created)
        self.assertFalse(replayed.admission_created)
        self.assertEqual(created.enrollment_digest, replayed.enrollment_digest)
        self.assertEqual(created.admission_digest, replayed.admission_digest)

    def test_mismatched_lineage_fails_before_any_enrollment_or_admission_write(
        self,
    ) -> None:
        request = self._request()
        proposal = enrollment_proposal(
            parse_headless_mp4_operation_v1(self.operation_json)
        )
        changed = dataclasses.replace(
            proposal,
            project=dataclasses.replace(
                proposal.project, project_lineage_digest="4" * 64
            ),
        )
        mismatched = dataclasses.replace(
            request,
            enrollment=enrollment(
                parse_headless_mp4_operation_v1(self.operation_json), changed
            ),
        )
        with self.assertRaises(EnrolledAdmittedQualityPassCompositionError):
            self._inspect(mismatched)
        for name in ("unit-enrollments-v1", "operation-admissions-v3"):
            self.assertFalse(os.path.exists(self.fixture.authority / name))

    def test_later_composition_failure_preserves_both_durable_records(
        self,
    ) -> None:
        request = self._request()
        target = (
            "headless.enrolled_admitted_quality_pass_composition."
            "inspect_durable_admitted_quality_pass_composition"
        )
        with patch(
            target, side_effect=RuntimeError("later inspection failed")
        ):
            with self.assertRaises(
                EnrolledAdmittedQualityPassCompositionError
            ):
                self._inspect(request)
        replayed = self._inspect(request)
        self.assertFalse(replayed.enrollment_created)
        self.assertFalse(replayed.admission_created)

    def test_wrapper_persists_enrollment_before_operation_admission(
        self,
    ) -> None:
        request = self._request()
        events = []
        enrollment_target = (
            "headless.enrolled_admitted_quality_pass_composition."
            "persist_or_replay_prospective_unit_enrollment_v1"
        )
        admission_target = (
            "headless.enrolled_admitted_quality_pass_composition."
            "persist_or_replay_cross_ledger_ordered_admission_v1"
        )
        from headless import (
            enrolled_admitted_quality_pass_composition as module,
        )

        original_enrollment = (
            module.persist_or_replay_prospective_unit_enrollment_v1
        )
        original_admission = (
            module.persist_or_replay_cross_ledger_ordered_admission_v1
        )

        def enroll(value: object):
            events.append("enrollment")
            return original_enrollment(value)

        def admit(value: object):
            events.append("admission")
            return original_admission(value)

        with patch(enrollment_target, side_effect=enroll), patch(
            admission_target, side_effect=admit
        ):
            self._inspect(request)
        self.assertEqual(events, ["enrollment", "admission"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
