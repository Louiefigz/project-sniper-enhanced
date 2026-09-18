"""Adversarial structural binding tests for genesis R1 authority."""

from __future__ import annotations

import dataclasses
import unittest

from _approved_parent_loader_values import canonical
from _common import pl  # noqa: F401
from _genesis_r1_fixture import changed, decoded, genesis_r1_fixture
from headless.generation_schema import parse_generation_commit
from headless.genesis_approved_card import parse_genesis_approved_card_v2
from headless.genesis_authority_binding import (
    bind_genesis_r1_authority,
    require_genesis_execution_authorized,
)
from headless.genesis_authority_types import (
    GENESIS_R1_STRUCTURAL_STATUS,
    GenesisAuthorityInputsV2,
)
from headless.genesis_authority_validation import (
    GenesisAuthorityBindingError,
    bind_genesis_current_card,
)
from headless.genesis_generation_profile import select_disjoint_generation_profile
from headless.genesis_policy_bundle import bind_genesis_policy_bundle
from headless.origin_receipt import parse_initialization_origin_receipt_v1


class GenesisR1AuthorityBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = genesis_r1_fixture()
        self.inputs = self.fixture.inputs

    def _replace(self, **changes: object) -> GenesisAuthorityInputsV2:
        return dataclasses.replace(self.inputs, **changes)

    def test_all_seven_r1_requirements_close_structurally_only(self) -> None:
        report = bind_genesis_r1_authority(self.inputs)
        self.assertEqual(report.status, GENESIS_R1_STRUCTURAL_STATUS)
        self.assertEqual(
            tuple(item.code for item in report.closed_profile_requirements),
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
        self.assertTrue(report.profile_selected)
        self.assertTrue(report.manifest_bytes_bound)
        self.assertTrue(report.approved_card_bound)
        self.assertTrue(report.origin_receipt_bound)
        self.assertTrue(report.operation_bound)
        self.assertTrue(report.snapshot_authority_bound)
        self.assertTrue(report.initialization_policy_compatible)
        self.assertTrue(report.generation_policies_bound)
        self.assertTrue(report.structural_verification_bound)
        self.assertFalse(report.trusted_store_verified)
        self.assertFalse(report.runtime_verified)
        self.assertFalse(report.execution_authorized)
        self.assertFalse(report.publication_authorized)

    def test_remaining_blockers_are_trusted_observation_and_publication_gates(
        self,
    ) -> None:
        report = bind_genesis_r1_authority(self.inputs)
        self.assertEqual(
            tuple(item.code for item in report.remaining_trusted_blockers),
            (
                "TRUSTED_SEALED_GENESIS_STORE",
                "BASE_PLAN_GRAPHICS_REOBSERVATION",
                "BUILD_RUNTIME_AND_TOOL_ATTESTATION",
                "MEDIA_QUALITY_AND_COVER_REOBSERVATION",
                "GENESIS_PUBLICATION_SEQUENCE",
            ),
        )
        self.assertNotIn(
            "TRUSTED_INITIALIZATION_EXECUTION_POLICY",
            tuple(item.code for item in report.remaining_trusted_blockers),
        )

    def test_execution_gate_always_rejects_even_a_forged_true_report(self) -> None:
        report = bind_genesis_r1_authority(self.inputs)
        forged = dataclasses.replace(
            report,
            trusted_store_verified=True,
            runtime_verified=True,
            execution_authorized=True,
            publication_authorized=True,
        )
        for value in (report, forged):
            with self.subTest(value=value), self.assertRaises(
                GenesisAuthorityBindingError
            ):
                require_genesis_execution_authorized(value)

    def test_every_authority_document_is_bound_to_exact_manifest_bytes(self) -> None:
        paths = (
            self.inputs.commit.approved_parent_path,
            self.inputs.approved_card.origin.receipt.relative_path,
            self.inputs.approved_card.origin.operation.relative_path,
            self.inputs.approved_card.origin.snapshot_authority.relative_path,
            self.inputs.approved_card.provenance.execution_policy.relative_path,
            "authority/generation-verification-v2.json",
        )
        for path in paths:
            artifacts = dict(self.inputs.artifact_bytes)
            artifacts[path] += b"\n"
            with self.subTest(path=path), self.assertRaises(
                GenesisAuthorityBindingError
            ):
                bind_genesis_r1_authority(self._replace(artifact_bytes=artifacts))

    def test_artifact_mapping_must_be_exact_and_immutable_bytes(self) -> None:
        missing = dict(self.inputs.artifact_bytes)
        missing.pop(self.inputs.commit.approved_parent_path)
        extra = dict(self.inputs.artifact_bytes)
        extra["future/banana.json"] = b"banana"
        nonbytes = dict(self.inputs.artifact_bytes)
        nonbytes[self.inputs.commit.approved_parent_path] = bytearray(
            nonbytes[self.inputs.commit.approved_parent_path]
        )
        for artifacts in (missing, extra, nonbytes):
            with self.subTest(paths=tuple(artifacts)), self.assertRaises(
                GenesisAuthorityBindingError
            ):
                bind_genesis_r1_authority(self._replace(artifact_bytes=artifacts))

    def test_all_four_policy_documents_are_exact_not_merely_manifest_hashed(
        self,
    ) -> None:
        groups = select_disjoint_generation_profile(self.inputs.commit).groups
        for artifact_class in (
            "initialization-execution-policy-v2",
            "repair-policy-v1",
            "quality-policy-v1",
            "fallback-policy-v1",
        ):
            row = groups[artifact_class][0]
            artifacts = dict(self.inputs.artifact_bytes)
            artifacts[row.path] = b"{}"
            with self.subTest(artifact_class=artifact_class), self.assertRaises(
                GenesisAuthorityBindingError
            ):
                bind_genesis_policy_bundle(self.inputs, groups, artifacts)

    def test_operation_snapshot_card_and_origin_drift_fail_closed(self) -> None:
        card = parse_genesis_approved_card_v2(
            changed(
                self.inputs.approved_card.document_json,
                ("origin", "operationDigest"),
                "0" * 64,
            )
        )
        receipt = parse_initialization_origin_receipt_v1(
            changed(
                self.inputs.origin_receipt.document_json,
                ("operation", "snapshotId"),
                "0" * 64,
            )
        )
        cases = (
            self._replace(approved_card=card),
            self._replace(origin_receipt=receipt),
            self._replace(
                snapshot_authority_json=self.inputs.snapshot_authority_json + b"\n"
            ),
            self._replace(
                operation=dataclasses.replace(
                    self.inputs.operation, operation_digest="0" * 64
                )
            ),
        )
        for value in cases:
            with self.subTest(value=value), self.assertRaises(
                GenesisAuthorityBindingError
            ):
                bind_genesis_r1_authority(value)

    def test_class_swaps_and_forged_wire_instances_reject(self) -> None:
        document = decoded(self.inputs.commit.document_json)
        origin = next(
            row
            for row in document["files"]
            if row["artifactClass"] == "initialization-origin-receipt-v1"
        )
        operation = next(
            row
            for row in document["files"]
            if row["artifactClass"] == "headless-operation-v1"
        )
        origin["artifactClass"], operation["artifactClass"] = (
            operation["artifactClass"],
            origin["artifactClass"],
        )
        swapped = parse_generation_commit(canonical(document))
        forged = dataclasses.replace(self.inputs.commit, request_digest="0" * 64)
        for commit in (swapped, forged):
            with self.subTest(commit=commit), self.assertRaises(
                GenesisAuthorityBindingError
            ):
                bind_genesis_r1_authority(self._replace(commit=commit))

    def test_card_current_values_cannot_disagree_with_origin(self) -> None:
        document = decoded(self.inputs.approved_card.document_json)
        document["plan"]["approvedPlanDigest"] = "0" * 64
        card = parse_genesis_approved_card_v2(canonical(document))
        with self.assertRaises(GenesisAuthorityBindingError):
            bind_genesis_r1_authority(self._replace(approved_card=card))

    def test_origin_runtime_manifest_cannot_diverge_from_the_card(self) -> None:
        receipt = parse_initialization_origin_receipt_v1(
            changed(
                self.inputs.origin_receipt.document_json,
                ("buildRuntime", "runtimeCapabilityManifest", "sha256"),
                "0" * 64,
            )
        )
        with self.assertRaisesRegex(GenesisAuthorityBindingError, "current card"):
            bind_genesis_current_card(self._replace(origin_receipt=receipt))


if __name__ == "__main__":
    unittest.main(verbosity=2)
