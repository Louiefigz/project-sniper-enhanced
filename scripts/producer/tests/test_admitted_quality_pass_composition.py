"""Adversarial tests for durable-admission composition inspection."""

from __future__ import annotations

import dataclasses
import json
import unittest
from unittest.mock import patch

from _approved_parent_loader_fixture import ApprovedParentAuthorityFixture
from _approved_parent_loader_values import canonical
from _common import pl  # noqa: F401
from _retired_r0_diagnostics_fixture import historical_diagnostics, assert_retired_inspection, _leaves
from test_quality_pass_preflight import _operation
from headless.admitted_quality_pass_composition import (
    ADMISSION_BINDING_REQUIREMENT,
    ADMITTED_COMPOSITION_STATUS,
    AdmittedQualityPassCompositionError,
    AdmittedQualityPassCompositionRequestV1,
    inspect_admitted_quality_pass_composition,
    require_admitted_render_start_authorized,
)
from headless.approved_parent_media import ApprovedParentVerifierContextV1
from headless.operation_admission_binding import build_operation_admission_v3
from headless.operation_admission_types import OperationAdmissionProposalV3
from headless.operation_contract import parse_headless_mp4_operation_v1
from headless.quality_pass_composition_types import (
    QualityPassCompositionInspectionRequestV1,
)
from headless.quality_pass_composition_inspection import (
    inspect_quality_pass_composition,
)

_CONTEXT = ApprovedParentVerifierContextV1("/not/invoked/ffprobe", "0" * 64, 1.0)
_IDEMPOTENCY = "77777777-7777-4777-8777-777777777777"
_ATTEMPT = "88888888-8888-4888-8888-888888888888"
_CHILD = "99999999-9999-4999-8999-999999999999"
_OTHER_CHILD = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_OTHER_UNIT = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


class AdmittedQualityPassCompositionTests(unittest.TestCase):
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
        authority = parse_headless_mp4_operation_v1(
            self.operation_json
        ).expected_parent.authority_id
        authority_raw = (
            json.dumps(
                {"authorityId": authority, "schemaVersion": 1},
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
        assert_retired_inspection(self, ("operation-admissions-v3",))

    def tearDown(self) -> None:
        self.fixture.close()

    def _proposal(self, raw: bytes | None = None) -> OperationAdmissionProposalV3:
        operation = parse_headless_mp4_operation_v1(raw or self.operation_json)
        return OperationAdmissionProposalV3(
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

    def _request(
        self,
        raw: bytes | None = None,
        proposal: OperationAdmissionProposalV3 | None = None,
        admission: object = None,
    ) -> AdmittedQualityPassCompositionRequestV1:
        selected_raw = raw or self.operation_json
        operation = parse_headless_mp4_operation_v1(selected_raw)
        selected_proposal = proposal or self._proposal(selected_raw)
        selected_admission = admission or build_operation_admission_v3(
            operation,
            selected_proposal,
            "operations/headless-mp4-operation.json",
        )
        inspection = QualityPassCompositionInspectionRequestV1(
            str(self.fixture.authority),
            str(self.fixture.materialization),
            str(self.historical),
            selected_raw,
            _CONTEXT,
        )
        return AdmittedQualityPassCompositionRequestV1(
            inspection, selected_admission, selected_proposal
        )

    def _inspect(self, request: object):
        with patch(
            "headless.approved_parent_loader.validate_parent_media",
            return_value=self.fixture.base_probe(),
        ):
            return inspect_admitted_quality_pass_composition(request)

    def _inspect_with_baseline(self, request: object):
        baseline = []

        def capture(value: object):
            result = historical_diagnostics(value)
            baseline.append(result)
            return result

        target = (
            "headless.admitted_quality_pass_composition."
            "inspect_quality_pass_composition"
        )
        with patch(target, side_effect=capture):
            promoted = self._inspect(request)
        return baseline[0], promoted

    def test_exact_admission_closes_only_durable_child_binding(self) -> None:
        baseline, result = self._inspect_with_baseline(self._request())
        self.assertEqual(result.status, ADMITTED_COMPOSITION_STATUS)
        self.assertEqual(result.newly_closed_checks, (ADMISSION_BINDING_REQUIREMENT,))
        self.assertIn(ADMISSION_BINDING_REQUIREMENT, result.composition.closed_checks)
        self.assertEqual(
            result.composition.closed_checks,
            baseline.closed_checks + (ADMISSION_BINDING_REQUIREMENT,),
        )
        baseline_open = {row.code for row in baseline.unresolved_authority}
        codes = tuple(row.code for row in result.unresolved_authority)
        self.assertEqual(baseline_open - set(codes), {ADMISSION_BINDING_REQUIREMENT})
        self.assertNotIn(ADMISSION_BINDING_REQUIREMENT, codes)
        for code in (
            "UNIT_ENROLLMENT_AUTHORITY",
            "R1_INITIALIZATION_ORIGIN_AUTHORITY",
            "RECURSIVE_LINEAGE_AND_GENESIS_ORIGIN",
            "OPERATION_RUNTIME_EXECUTION_AND_CHILD_SEAL",
            "ACTIVE_FENCE_RECHECK",
            "FENCED_PUBLICATION_AND_TERMINAL_SEAL",
        ):
            self.assertIn(code, codes)
        self.assertTrue(result.exact_operation_bytes_admitted)
        self.assertTrue(result.durable_admission_bytes_reobserved)
        self.assertTrue(result.durable_operation_bytes_reobserved)
        self.assertTrue(result.proposed_child_bound)
        self.assertTrue(result.composition.durable_admission_bound)
        self.assertFalse(result.unit_enrollment_verified)
        self.assertFalse(result.operation_runtime_verified)
        self.assertFalse(result.fence_rechecked)
        self.assertFalse(result.execution_authorized)
        self.assertFalse(result.publication_authorized)

    def test_exact_replay_is_inspected_without_new_admission(self) -> None:
        request = self._request()
        created = self._inspect(request)
        replay_materialization = self.fixture.root / "replay-materialization"
        replay_materialization.mkdir(mode=0o700)
        replay_inspection = dataclasses.replace(
            request.inspection,
            current_materialization_root=str(replay_materialization),
        )
        replayed = self._inspect(
            dataclasses.replace(request, inspection=replay_inspection)
        )
        self.assertTrue(created.admission_created)
        self.assertFalse(replayed.admission_created)
        self.assertEqual(created.admission_digest, replayed.admission_digest)
        self.assertEqual(
            created.intended_child_generation_id,
            replayed.intended_child_generation_id,
        )

    def test_later_composition_failure_preserves_durable_admission(self) -> None:
        request = self._request()
        target = (
            "headless.admitted_quality_pass_composition."
            "inspect_quality_pass_composition"
        )

        def forge_authority(value: object):
            inspected = historical_diagnostics(value)
            return dataclasses.replace(inspected, execution_authorized=True)

        with patch(target, side_effect=forge_authority), self.assertRaisesRegex(
            AdmittedQualityPassCompositionError, "diagnostics"
        ):
            self._inspect(request)
        replay_root = self.fixture.root / "failure-replay-materialization"
        replay_root.mkdir(mode=0o700)
        replay_inspection = dataclasses.replace(
            request.inspection, current_materialization_root=str(replay_root)
        )
        replayed = self._inspect(
            dataclasses.replace(request, inspection=replay_inspection)
        )
        self.assertFalse(replayed.admission_created)
        self.assertEqual(
            replayed.admission_digest,
            request.admission.admission_digest,
        )
        self.assertEqual(
            replayed.intended_child_generation_id,
            request.proposal.intended_child_generation_id,
        )

    def test_operation_admission_and_proposed_child_mismatch_fail_closed(self) -> None:
        original = self._request()
        changed = _operation(self.fixture)
        changed["unitId"] = _OTHER_UNIT
        mismatched_raw = canonical(changed)
        operation_mismatch = dataclasses.replace(
            original.inspection, operation_json=mismatched_raw
        )
        child_mismatch = dataclasses.replace(
            original.proposal, intended_child_generation_id=_OTHER_CHILD
        )
        cases = (
            dataclasses.replace(original, inspection=operation_mismatch),
            dataclasses.replace(original, proposal=child_mismatch),
        )
        for request in cases:
            with self.subTest(request=request), self.assertRaises(
                AdmittedQualityPassCompositionError
            ):
                self._inspect(request)

    def test_same_idempotency_key_with_changed_admission_conflicts(self) -> None:
        first = self._request()
        self._inspect(first)
        changed_proposal = dataclasses.replace(
            first.proposal, build_id="build-headless-other"
        )
        changed_admission = build_operation_admission_v3(
            parse_headless_mp4_operation_v1(self.operation_json),
            changed_proposal,
            "operations/headless-mp4-operation.json",
        )
        changed = dataclasses.replace(
            first, proposal=changed_proposal, admission=changed_admission
        )
        with self.assertRaisesRegex(AdmittedQualityPassCompositionError, "idempotency"):
            self._inspect(changed)

    def test_forged_booleans_never_authorize_render_start(self) -> None:
        result = self._inspect(self._request())
        forged = dataclasses.replace(
            result, execution_authorized=True, publication_authorized=True
        )
        forged_nested = dataclasses.replace(
            result,
            composition=dataclasses.replace(
                result.composition,
                execution_authorized=True,
                publication_authorized=True,
            ),
        )
        for value in (result, forged, forged_nested, object()):
            with self.subTest(value=type(value)), self.assertRaises(
                AdmittedQualityPassCompositionError
            ):
                require_admitted_render_start_authorized(value)

    def test_result_leaks_no_lease_store_request_or_absolute_path(self) -> None:
        result = self._inspect(self._request())
        self.assertFalse(
            {"lease", "store", "request", "operation", "admission", "proposal"}
            & set(result.__dict__)
        )
        self.assertFalse(
            {"lease", "store", "request", "operation", "admission", "proposal"}
            & set(result.composition.__dict__)
        )
        leaves = _leaves(result)
        self.assertTrue(
            all(type(value) in {str, int, bool, type(None)} for value in leaves)
        )
        strings = (value for value in leaves if type(value) is str)
        self.assertFalse(any(value.startswith("/") for value in strings))
