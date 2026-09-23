"""Lifetime-safe non-authorizing quality-pass composition inspection tests."""

from __future__ import annotations

import dataclasses
import unittest
from pathlib import Path
from unittest.mock import patch

from _approved_parent_loader_fixture import ApprovedParentAuthorityFixture
from _approved_parent_loader_values import canonical
from _common import pl  # noqa: F401
from _retired_r0_lease_fixture import inert_preflight_inputs
from test_quality_pass_preflight import _operation
from headless.approved_parent_media import ApprovedParentVerifierContextV1
from headless.quality_pass_composition_inspection import (
    R0_GENESIS_BLOCKED,
    NonAuthorizingQualityPassCompositionV1,
    QualityPassCompositionInspectionError,
    QualityPassCompositionInspectionRequestV1,
    inspect_quality_pass_composition,
    require_render_start_authorized,
)

_CONTEXT = ApprovedParentVerifierContextV1("/not/invoked/ffprobe", "0" * 64, 1.0)


class QualityPassCompositionInspectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ApprovedParentAuthorityFixture()
        self.historical = self.fixture.root / "historical-materialization"
        self.historical.mkdir(mode=0o700)

    def tearDown(self) -> None:
        self.fixture.close()

    def _request(self, raw: bytes | None = None):
        return QualityPassCompositionInspectionRequestV1(
            str(self.fixture.authority),
            str(self.fixture.materialization),
            str(self.historical),
            raw or canonical(_operation(self.fixture)),
            _CONTEXT,
        )

    def _inspect(self, raw: bytes | None = None):
        with patch(
            "headless.approved_parent_loader.validate_parent_media",
            return_value=self.fixture.base_probe(),
        ):
            return inspect_quality_pass_composition(self._request(raw))

    def test_inert_genesis_result_closes_lease_and_stays_blocked(self) -> None:
        with inert_preflight_inputs(self.fixture):
            result = self._inspect()
        self.assertIs(type(result), NonAuthorizingQualityPassCompositionV1)
        self.assertEqual(result.status, R0_GENESIS_BLOCKED)
        self.assertEqual(result.parent_profile, "legacy-r0-genesis-specimen")
        self.assertIn("REPAIR_CAS_APPLIED", result.closed_checks)
        self.assertNotEqual(
            result.expected_parent.plan_digest, result.candidate_plan_digest
        )
        codes = tuple(item.code for item in result.unresolved_authority)
        self.assertIn("R1_INITIALIZATION_ORIGIN_AUTHORITY", codes)
        self.assertIn("DISJOINT_R1_PARENT_LOADER_AND_HISTORY", codes)
        self.assertIn("OPERATION_DURABLE_ADMISSION_AND_CHILD_BINDING", codes)
        self.assertIn("UNIT_ENROLLMENT_AUTHORITY", codes)
        self.assertFalse(result.execution_authorized)
        self.assertFalse(result.publication_authorized)
        self.assertNotIn("parent", result.__dict__)

    def test_forged_authorization_boolean_never_becomes_a_capability(self) -> None:
        with inert_preflight_inputs(self.fixture):
            result = self._inspect()
        forged = dataclasses.replace(
            result, execution_authorized=True, publication_authorized=True
        )
        for value in (result, forged, object()):
            with self.subTest(value=type(value)), self.assertRaises(
                QualityPassCompositionInspectionError
            ):
                require_render_start_authorized(value)

    def test_retired_repair_is_not_reported_as_structural_success(self) -> None:
        document = _operation(self.fixture)
        document["qualityPass"]["repairIntent"]["expectedOld"] = "#000000"
        with self.assertRaisesRegex(
            ValueError, "section-marker.*retired"
        ):
            self._inspect(canonical(document))

    def test_real_retired_inspection_never_returns_or_launches_media(self) -> None:
        fixture = self.fixture
        before = {p: p.read_bytes() for p in fixture.authority.rglob('*') if p.is_file()}
        with patch('subprocess.Popen') as process, self.assertRaisesRegex(
                ValueError, 'section-marker.*retired'):
            self._inspect()
        process.assert_not_called()
        self.assertEqual(before, {p: p.read_bytes() for p in fixture.authority.rglob('*') if p.is_file()})

    def test_request_rejects_aliasing_and_noncanonical_roots(self) -> None:
        request = dataclasses.replace(
            self._request(),
            historical_materialization_root=str(self.fixture.materialization),
        )
        with self.assertRaisesRegex(QualityPassCompositionInspectionError, "alias"):
            inspect_quality_pass_composition(request)
        noncanonical = dataclasses.replace(
            self._request(), authority_root=str(Path(self.fixture.authority) / "..")
        )
        with self.assertRaisesRegex(QualityPassCompositionInspectionError, "canonical"):
            inspect_quality_pass_composition(noncanonical)


if __name__ == "__main__":
    unittest.main()
