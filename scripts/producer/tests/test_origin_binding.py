"""Adversarial structural and R0-gap tests for initialization origin."""

from __future__ import annotations

import dataclasses
import unittest

from _assembly_receipt_fixture import assembly_fixture
from _common import pl  # noqa: F401
from _origin_fixture import changed, decoded, origin_fixture
from _approved_parent_loader_values import canonical
from headless.approved_parent_assembly_binding import (
    ApprovedParentAssemblyBindingError,
    bind_approved_parent_assembly_receipt,
)
from headless.generation_profile import (
    R0_GENERATION_ARTIFACT_CLASS_COUNTS,
    R0_MANIFEST_ROWS,
)
from headless.generation_schema import parse_generation_commit
from headless.operation_contract import parse_headless_mp4_operation_v1
from headless.origin_binding import (
    InitializationOriginBindingError,
    bind_initialization_origin_receipt,
)
from headless.origin_receipt import parse_initialization_origin_receipt_v1
from headless.origin_requirements import R0_BLOCKED_STATUS
from test_operation_contract import _quality_operation


class InitializationOriginBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = origin_fixture()

    def _bind(
        self,
        receipt: object | None = None,
        commit: object | None = None,
        operation: object | None = None,
    ):
        return bind_initialization_origin_receipt(
            self.fixture.descriptor,
            commit or self.fixture.commit,
            receipt or self.fixture.receipt,
            operation or self.fixture.operation,
        )

    def test_current_card_binds_but_result_is_explicitly_non_authorizing(self) -> None:
        report = self._bind()
        self.assertEqual(report.status, R0_BLOCKED_STATUS)
        self.assertTrue(report.structural_current_card_bound)
        self.assertTrue(report.operation_bytes_bound)
        self.assertTrue(report.snapshot_bytes_bound)
        self.assertFalse(report.profile_compatible)
        self.assertFalse(report.initialization_policy_authorized)
        self.assertFalse(report.runtime_verified)
        self.assertFalse(report.publication_authorized)
        self.assertEqual(len(report.bound_current_card_roles), 22)

    def test_r0_gap_report_names_every_required_versioned_authority(self) -> None:
        report = self._bind()
        codes = tuple(item.code for item in report.missing_profile_authority)
        self.assertEqual(
            codes,
            (
                "DISJOINT_GENERATION_PROFILE_R1",
                "INITIALIZATION_ORIGIN_RECEIPT_CLASS",
                "HEADLESS_INITIALIZE_OPERATION_CLASS",
                "INITIALIZATION_SNAPSHOT_AUTHORITY_CLASS",
                "GENESIS_APPROVED_CARD_V2",
                "INITIALIZATION_EXECUTION_POLICY_V2",
                "GENERATION_VERIFICATION_PROFILE_V2",
            ),
        )
        self.assertNotIn(
            "initialization-origin-receipt-v1",
            R0_GENERATION_ARTIFACT_CLASS_COUNTS,
        )
        self.assertNotIn("headless-operation-v1", R0_GENERATION_ARTIFACT_CLASS_COUNTS)
        self.assertEqual(len(self.fixture.commit.files), R0_MANIFEST_ROWS)

    def test_current_execution_policy_cannot_authorize_initialize(self) -> None:
        report = self._bind()
        self.assertEqual(
            tuple(gap.code for gap in report.execution_policy_gaps),
            (
                "OPERATION_DISCRIMINANT",
                "INITIAL_BASE_BUILD_DISPOSITION",
                "INITIALIZATION_SNAPSHOT_AUTHORITY",
            ),
        )
        codes = tuple(item.code for item in report.unresolved_authority)
        self.assertIn("TRUSTED_INITIALIZATION_EXECUTION_POLICY", codes)
        self.assertEqual(codes[-1], "GENESIS_PUBLICATION_SEQUENCE")

    def test_identity_policy_operation_and_snapshot_drift_reject(self) -> None:
        mutations = (
            (("identity", "requestDigest"), "0" * 64),
            (("policies", "initializationExecutionPolicyId"), "0" * 64),
            (("operation", "digest"), "0" * 64),
            (("operation", "snapshotId"), "0" * 64),
            (("operation", "snapshotAuthority", "sha256"), "0" * 64),
        )
        for path, value in mutations:
            receipt = parse_initialization_origin_receipt_v1(
                changed(self.fixture.receipt.document_json, path, value)
            )
            with self.subTest(path=path), self.assertRaises(
                InitializationOriginBindingError
            ):
                self._bind(receipt=receipt)

    def test_every_requested_product_and_evidence_family_is_bound(self) -> None:
        mutations = (
            (("plan", "approvedPlanDigest"), "0" * 64),
            (("base", "planArtifact", "sha256"), "0" * 64),
            (("base", "receipt", "sha256"), "0" * 64),
            (("base", "timelineMap", "sha256"), "0" * 64),
            (("graphics", "preboundClips", "sha256"), "0" * 64),
            (("graphics", "assets", 0, "receipt", "sha256"), "0" * 64),
            (("buildRuntime", "renderBuildReceipt", "sha256"), "0" * 64),
            (("buildRuntime", "compositorBuildReceipt", "sha256"), "0" * 64),
            (("output", "final", "artifact", "sha256"), "0" * 64),
            (("output", "cover", "sha256"), "0" * 64),
            (("quality", "audit", "sha256"), "0" * 64),
            (("quality", "critics", 1, "artifact", "sha256"), "0" * 64),
        )
        for path, value in mutations:
            receipt = parse_initialization_origin_receipt_v1(
                changed(self.fixture.receipt.document_json, path, value)
            )
            with self.subTest(path=path), self.assertRaises(
                InitializationOriginBindingError
            ):
                self._bind(receipt=receipt)

    def test_non_genesis_commit_and_quality_pass_operation_reject(self) -> None:
        document = decoded(self.fixture.commit.document_json)
        document["expectedParent"] = {
            "authorityId": self.fixture.commit.authority_id,
            "publicationSeq": 1,
            "generationId": "99999999-9999-4999-8999-999999999999",
            "commitDigest": "8" * 64,
            "planDigest": self.fixture.receipt.plan.approved_plan_digest,
        }
        with self.assertRaisesRegex(InitializationOriginBindingError, "genesis"):
            self._bind(commit=parse_generation_commit(canonical(document)))
        quality = parse_headless_mp4_operation_v1(canonical(_quality_operation()))
        with self.assertRaisesRegex(InitializationOriginBindingError, "inputs"):
            self._bind(operation=quality)

    def test_manifest_class_or_bytes_cannot_substitute_for_a_bound_role(self) -> None:
        document = decoded(self.fixture.commit.document_json)
        row = next(
            item
            for item in document["files"]
            if item["artifactClass"] == "render-build-receipt-v1"
        )
        row["sha256"] = "0" * 64
        commit = parse_generation_commit(canonical(document))
        with self.assertRaisesRegex(InitializationOriginBindingError, "class"):
            self._bind(commit=commit)
        receipt = decoded(self.fixture.receipt.document_json)
        receipt["operation"]["artifact"]["path"] = self.fixture.commit.files[0].path
        parsed = parse_initialization_origin_receipt_v1(canonical(receipt))
        with self.assertRaisesRegex(InitializationOriginBindingError, "aliases"):
            self._bind(receipt=parsed)

    def test_directly_forged_wire_instances_reject(self) -> None:
        commit = dataclasses.replace(self.fixture.commit, request_digest="0" * 64)
        with self.assertRaisesRegex(InitializationOriginBindingError, "construction"):
            self._bind(commit=commit)
        operation = dataclasses.replace(
            self.fixture.operation, operation_digest="0" * 64
        )
        with self.assertRaises(InitializationOriginBindingError):
            self._bind(operation=operation)

    def test_existing_assembly_receipt_still_rejects_genesis(self) -> None:
        fixture = assembly_fixture()
        document = decoded(fixture.commit.document_json)
        document["expectedParent"] = None
        genesis = parse_generation_commit(canonical(document))
        with self.assertRaisesRegex(ApprovedParentAssemblyBindingError, "genesis"):
            bind_approved_parent_assembly_receipt(
                fixture.descriptor, genesis, fixture.receipt
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
