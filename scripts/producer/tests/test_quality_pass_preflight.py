"""Disk-backed operation/current-parent preflight regressions."""

from __future__ import annotations

import dataclasses
import unittest
from unittest.mock import patch

from _common import pl  # noqa: F401
from _retired_r0_lease_fixture import inert_preflight_inputs
from _approved_parent_loader_fixture import ApprovedParentAuthorityFixture
from _approved_parent_loader_values import canonical
from headless.approved_parent_media import ApprovedParentVerifierContextV1
from headless.quality_pass_preflight import (
    PREFLIGHT_STATUS,
    QualityPassPreflightError,
    _requirements,
    inspect_quality_pass_preflight,
    require_execution_authorized,
)

_CONTEXT = ApprovedParentVerifierContextV1("/not/invoked/ffprobe", "0" * 64, 1.0)
_REQUEST_ID = "44444444-4444-4444-8444-444444444444"


def _parent_document(fixture: ApprovedParentAuthorityFixture) -> dict:
    ref = fixture.documents.expected_parent()
    return {
        "authorityId": ref.authority_id,
        "publicationSeq": ref.publication_seq,
        "generationId": ref.generation_id,
        "commitDigest": ref.commit_digest,
        "planDigest": ref.plan_digest,
    }


def _operation(fixture: ApprovedParentAuthorityFixture) -> dict:
    documents = fixture.documents
    parent = _parent_document(fixture)
    row = documents.plan["graphicsTrack"][0]
    quality_pass = {
        "schemaVersion": 1,
        "operation": "quality-pass",
        "realizationKind": "deterministic-mp4",
        "fallbackPolicy": "none",
        "repairPolicyId": documents.commit.repair_policy_id,
        "qualityPolicyId": documents.commit.quality_policy_id,
        "repairIntent": {
            "schemaVersion": 1,
            "effectClass": "SECTION_MARKER_ACCENT_V1",
            "realizationKind": "deterministic-mp4",
            "expectedParent": parent,
            "requestId": _REQUEST_ID,
            "target": {"lane": "graphicsTrack", "id": row["id"]},
            "op": "replace",
            "relativePointer": "/spec/accent",
            "expectedOld": row["spec"]["accent"],
            "value": "#FFD400",
        },
    }
    return {
        "schemaVersion": 1,
        "operation": "quality-pass",
        "realizationKind": "deterministic-mp4",
        "unitId": "55555555-5555-4555-8555-555555555555",
        "expectedParent": parent,
        "executionPolicyId": documents.commit.execution_policy_id,
        "baseRebuildAllowed": False,
        "writerRebuildAllowed": False,
        "fallbackPolicy": "none",
        "qualityPass": quality_pass,
    }


class QualityPassPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ApprovedParentAuthorityFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def _inspect(self, raw: bytes):
        fixture = self.fixture
        return inspect_quality_pass_preflight(
            str(fixture.authority),
            str(fixture.materialization),
            raw,
            _CONTEXT,
        )

    def test_inert_parent_candidate_wiring_does_not_authorize(self) -> None:
        fixture = self.fixture
        with patch(
            "headless.approved_parent_loader.validate_parent_media",
            return_value=fixture.base_probe(),
        ), inert_preflight_inputs(fixture), self._inspect(canonical(_operation(fixture))) as preflight:
            self.assertEqual(
                preflight.operation.expected_parent, preflight.parent.parent.ref
            )
            self.assertTrue(preflight.policy.executable)
            self.assertNotEqual(
                preflight.candidate.before_digest, preflight.candidate.after_digest
            )
            self.assertEqual(
                preflight.candidate.changed_pointers,
                ("/graphicsTrack/0/spec/accent",),
            )
            self.assertEqual(preflight.status, PREFLIGHT_STATUS)
            self.assertFalse(preflight.execution_authorized)
            codes = tuple(item.code for item in preflight.unresolved_authority)
            self.assertEqual(codes[0], "R1_INITIALIZATION_ORIGIN_AUTHORITY")
            self.assertIn("OPERATION_DURABLE_ADMISSION_AND_CHILD_BINDING", codes)
            self.assertIn("UNIT_ENROLLMENT_AUTHORITY", codes)
            self.assertIn("PARENT_QUALITY_RUNTIME_REOBSERVATION", codes)
            with self.assertRaises(QualityPassPreflightError):
                require_execution_authorized(preflight)
            forged = dataclasses.replace(preflight, execution_authorized=True)
            with self.assertRaises(QualityPassPreflightError):
                require_execution_authorized(forged)
            retained = preflight.parent
        with self.assertRaisesRegex(RuntimeError, "stale or closed"):
            retained.resolve_parent(retained.parent.ref)

    def test_real_retired_preflight_never_yields_or_launches_media(self) -> None:
        fixture = self.fixture
        before = {p: p.read_bytes() for p in fixture.authority.rglob('*') if p.is_file()}
        with patch('subprocess.Popen') as process, patch(
                'headless.approved_parent_loader.validate_parent_media',
                return_value=fixture.base_probe()), self.assertRaisesRegex(
                    ValueError, 'section-marker.*retired'):
            with self._inspect(canonical(_operation(fixture))):
                self.fail('retired preflight yielded')
        process.assert_not_called()
        self.assertEqual(before, {p: p.read_bytes() for p in fixture.authority.rglob('*') if p.is_file()})

    def test_historical_parent_does_not_erase_genesis_origin_requirement(self) -> None:
        fixture = self.fixture
        with patch(
            "headless.approved_parent_loader.validate_parent_media",
            return_value=fixture.base_probe(),
        ), inert_preflight_inputs(fixture), self._inspect(canonical(_operation(fixture))) as preflight:
            lease = preflight.parent
            commit = dataclasses.replace(
                lease.generation.commit, expected_parent=lease.parent.ref
            )
            lease.generation = dataclasses.replace(lease.generation, commit=commit)
            codes = tuple(item.code for item in _requirements(lease))
            self.assertEqual(codes[0], "R1_INITIALIZATION_ORIGIN_AUTHORITY")
            self.assertIn("SELECTED_PARENT_LINEAGE_CONTINUITY", codes)

    def test_stale_parent_or_policy_fails_before_preflight_yields(self) -> None:
        for field, value in (
            ("commitDigest", "0" * 64),
            ("executionPolicyId", "0" * 64),
        ):
            fixture = ApprovedParentAuthorityFixture()
            try:
                document = _operation(fixture)
                if field == "commitDigest":
                    document["expectedParent"][field] = value
                    document["qualityPass"]["repairIntent"]["expectedParent"][
                        field
                    ] = value
                else:
                    document[field] = value
                loader = inspect_quality_pass_preflight(
                    str(fixture.authority),
                    str(fixture.materialization),
                    canonical(document),
                    _CONTEXT,
                )
                with patch(
                    "headless.approved_parent_loader.validate_parent_media",
                    return_value=fixture.base_probe(),
                ), self.assertRaises(QualityPassPreflightError), loader:
                    self.fail("invalid preflight unexpectedly yielded")
            finally:
                fixture.close()

    def test_noncanonical_operation_and_initialize_are_rejected(self) -> None:
        raw = canonical(_operation(self.fixture))
        for value in (
            raw + b"\n",
            canonical({**_operation(self.fixture), "operation": "initialize"}),
        ):
            with self.subTest(value=value), self.assertRaises(
                QualityPassPreflightError
            ):
                with self._inspect(value):
                    pass

    def test_retired_preflight_refuses_alternative_repair_values(self) -> None:
        for field, value in (("expectedOld", "#000000"), ("value", "#123456")):
            fixture = ApprovedParentAuthorityFixture()
            try:
                document = _operation(fixture)
                document["qualityPass"]["repairIntent"][field] = value
                inspection = inspect_quality_pass_preflight(
                    str(fixture.authority),
                    str(fixture.materialization),
                    canonical(document),
                    _CONTEXT,
                )
                with self.subTest(field=field), patch(
                    "headless.approved_parent_loader.validate_parent_media",
                    return_value=fixture.base_probe(),
                ), self.assertRaisesRegex(ValueError, "section-marker.*retired"):
                    with inspection:
                        self.fail("inapplicable repair unexpectedly passed preflight")
            finally:
                fixture.close()

    def test_candidate_repair_failure_is_wrapped_without_claiming_success(self) -> None:
        from headless.quality_pass_preflight import _candidate
        from headless.operation_contract import parse_headless_mp4_operation_v1
        from headless.repair_intent import RepairIntentError
        from _retired_r0_lease_fixture import historical_lease
        operation = parse_headless_mp4_operation_v1(canonical(_operation(self.fixture)))
        refusal = RepairIntentError('TEST injected repair-stage refusal')
        with historical_lease(self.fixture) as lease, patch(
                'headless.quality_pass_preflight.apply_repair', side_effect=refusal), self.assertRaisesRegex(
                    QualityPassPreflightError, 'repair CAS') as caught:
            _candidate(operation, lease)
        self.assertIs(caught.exception.__cause__, refusal)

    def test_caller_exception_is_not_rewritten(self) -> None:
        fixture = self.fixture
        with patch(
            "headless.approved_parent_loader.validate_parent_media",
            return_value=fixture.base_probe(),
        ), inert_preflight_inputs(fixture):
            with self.assertRaisesRegex(RuntimeError, "caller failure"):
                with self._inspect(canonical(_operation(fixture))):
                    raise RuntimeError("caller failure")
