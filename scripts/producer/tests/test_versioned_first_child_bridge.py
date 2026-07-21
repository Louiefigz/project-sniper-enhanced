"""Adversarial parent-kind and base-continuity tests for the V2 bridge."""

from __future__ import annotations

import dataclasses
import unittest

from _assembly_receipt_fixture import assembly_fixture
from _common import pl  # noqa: F401
from _genesis_r1_fixture import genesis_r1_fixture
from _quality_pass_v2_fixture import build_quality_pass_v2_child
from headless.artifact_contract import ArtifactRefV1
from headless.repair_intent import ParentRefV1
from headless.versioned_parent_authority import ParentAuthorityV2
from headless.versioned_quality_pass_current_binding import (
    bind_quality_pass_current_authority_v2,
    require_quality_pass_v2_execution_authorized,
)
from headless.versioned_quality_pass_current_validation import (
    QualityPassCurrentBindingV2Error,
)
from headless.versioned_quality_pass_parent_binding import (
    QualityPassParentBridgeV2Error,
    bind_quality_pass_parent_bridge_v2,
    require_quality_pass_bridge_execution_authorized,
)
from headless.versioned_quality_pass_types import (
    QUALITY_PASS_V2_BRIDGE_STATUS,
    QUALITY_PASS_V2_CURRENT_STATUS,
    GenesisParentSnapshotV2,
    PriorAssemblyV1ParentSnapshotV2,
    PriorAssemblyV2ParentSnapshotV2,
    QualityPassParentBridgeInputsV2,
)


def _ref(commit: object, card: object, publication_seq: int) -> ParentRefV1:
    return ParentRefV1(
        commit.authority_id,
        publication_seq,
        commit.generation_id,
        commit.commit_digest,
        card.plan.approved_plan_digest,
    )


def _genesis_values() -> tuple:
    parent = genesis_r1_fixture().inputs
    ref = _ref(parent.commit, parent.approved_card, 1)
    authority = ParentAuthorityV2(
        "genesis-origin",
        "initialization-origin-receipt-v1",
        parent.approved_card.origin.receipt,
    )
    child = build_quality_pass_v2_child(ref, parent.approved_card, authority)
    snapshot = GenesisParentSnapshotV2(ref, parent)
    return parent, child, snapshot


def _prior_v1_values() -> tuple:
    parent = assembly_fixture()
    publication_seq = parent.commit.expected_parent.publication_seq + 1
    ref = _ref(parent.commit, parent.descriptor, publication_seq)
    authority = ParentAuthorityV2(
        "prior-assembly",
        "assembly-receipt-v1",
        parent.descriptor.output.assembly_receipt,
    )
    child = build_quality_pass_v2_child(ref, parent.descriptor, authority)
    snapshot = PriorAssemblyV1ParentSnapshotV2(
        ref, parent.commit, parent.descriptor, parent.receipt
    )
    return parent, child, snapshot


def _prior_v2_values() -> tuple:
    genesis, first, _snapshot = _genesis_values()
    parent = first.inputs
    ref = _ref(parent.commit, parent.approved_card, 2)
    authority = ParentAuthorityV2(
        "prior-assembly",
        "assembly-receipt-v2",
        parent.approved_card.output.assembly_receipt,
    )
    child = build_quality_pass_v2_child(
        ref, parent.approved_card, authority, identity_index=1
    )
    snapshot = PriorAssemblyV2ParentSnapshotV2(ref, parent)
    return genesis, child, snapshot


class QualityPassV2CurrentBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        _parent, self.child, _snapshot = _genesis_values()

    def test_current_card_is_structural_and_non_authorizing(self) -> None:
        report = bind_quality_pass_current_authority_v2(self.child.inputs)
        self.assertEqual(report.status, QUALITY_PASS_V2_CURRENT_STATUS)
        self.assertEqual(report.parent_authority.kind, "genesis-origin")
        self.assertFalse(report.runtime_verified)
        self.assertFalse(report.execution_authorized)
        self.assertFalse(report.publication_authorized)
        self.assertEqual(len(report.unresolved_authority), 7)

    def test_current_execution_gate_rejects_even_forged_true_report(self) -> None:
        report = bind_quality_pass_current_authority_v2(self.child.inputs)
        forged = dataclasses.replace(
            report,
            runtime_verified=True,
            execution_authorized=True,
            publication_authorized=True,
        )
        for value in (report, forged):
            with self.subTest(value=value), self.assertRaises(
                QualityPassCurrentBindingV2Error
            ):
                require_quality_pass_v2_execution_authorized(value)

    def test_receipt_card_or_verification_parent_drift_rejects(self) -> None:
        receipt = dataclasses.replace(
            self.child.inputs.assembly_receipt,
            parent_authority=ParentAuthorityV2(
                "prior-assembly",
                "assembly-receipt-v1",
                self.child.inputs.assembly_receipt.parent_authority.receipt,
            ),
        )
        card = dataclasses.replace(
            self.child.inputs.approved_card,
            expected_parent=dataclasses.replace(
                self.child.inputs.approved_card.expected_parent,
                commit_digest="0" * 64,
            ),
        )
        verification = dataclasses.replace(
            self.child.inputs.verification,
            payload_manifest_digest="0" * 64,
        )
        cases = (
            dataclasses.replace(self.child.inputs, assembly_receipt=receipt),
            dataclasses.replace(self.child.inputs, approved_card=card),
            dataclasses.replace(self.child.inputs, verification=verification),
        )
        for value in cases:
            with self.subTest(value=value), self.assertRaises(
                QualityPassCurrentBindingV2Error
            ):
                bind_quality_pass_current_authority_v2(value)


class GenesisFirstChildBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parent, self.child, self.snapshot = _genesis_values()

    def _bind(self, child: object | None = None, parent: object | None = None):
        return bind_quality_pass_parent_bridge_v2(
            QualityPassParentBridgeInputsV2(
                child or self.child.inputs, parent or self.snapshot
            )
        )

    def test_first_child_authenticates_exact_genesis_origin_not_assembly(self) -> None:
        report = self._bind()
        origin = self.parent.approved_card.origin.receipt
        self.assertEqual(report.status, QUALITY_PASS_V2_BRIDGE_STATUS)
        self.assertEqual(report.parent_authority.kind, "genesis-origin")
        self.assertEqual(
            report.parent_authority.artifact_class,
            "initialization-origin-receipt-v1",
        )
        self.assertEqual(report.parent_authority.receipt, origin)
        self.assertFalse(hasattr(self.parent.approved_card.output, "assembly_receipt"))
        self.assertTrue(report.parent_kind_authenticated)
        self.assertTrue(report.immediate_base_continuity_bound)
        self.assertFalse(report.recursive_lineage_verified)
        self.assertFalse(report.runtime_verified)
        self.assertFalse(report.execution_authorized)
        self.assertFalse(report.publication_authorized)

    def test_origin_as_assembly_alias_is_structurally_valid_but_bridge_rejects(
        self,
    ) -> None:
        alias = ParentAuthorityV2(
            "prior-assembly",
            "assembly-receipt-v1",
            self.parent.approved_card.origin.receipt,
        )
        child = build_quality_pass_v2_child(
            self.snapshot.ref, self.parent.approved_card, alias
        )
        bind_quality_pass_current_authority_v2(child.inputs)
        with self.assertRaisesRegex(
            QualityPassParentBridgeV2Error, "declared parent authority"
        ):
            self._bind(child=child.inputs)

    def test_wrong_origin_receipt_and_wrong_parent_ref_reject(self) -> None:
        origin = self.parent.approved_card.origin.receipt
        wrong_ref = ArtifactRefV1(origin.relative_path, "0" * 64, origin.size_bytes)
        wrong_authority = ParentAuthorityV2(
            "genesis-origin", "initialization-origin-receipt-v1", wrong_ref
        )
        wrong_receipt_child = build_quality_pass_v2_child(
            self.snapshot.ref, self.parent.approved_card, wrong_authority
        )
        wrong_parent = dataclasses.replace(self.snapshot.ref, commit_digest="0" * 64)
        wrong_parent_child = build_quality_pass_v2_child(
            wrong_parent,
            self.parent.approved_card,
            self.child.parent_authority,
        )
        for child in (wrong_receipt_child, wrong_parent_child):
            with self.subTest(child=child), self.assertRaises(
                QualityPassParentBridgeV2Error
            ):
                self._bind(child=child.inputs)

    def test_child_base_must_equal_authenticated_genesis_base(self) -> None:
        unrelated = assembly_fixture().descriptor
        child = build_quality_pass_v2_child(
            self.snapshot.ref,
            unrelated,
            self.child.parent_authority,
        )
        bind_quality_pass_current_authority_v2(child.inputs)
        with self.assertRaisesRegex(QualityPassParentBridgeV2Error, "base"):
            self._bind(child=child.inputs)

    def test_bridge_execution_gate_rejects_even_forged_true_report(self) -> None:
        report = self._bind()
        forged = dataclasses.replace(
            report,
            recursive_lineage_verified=True,
            runtime_verified=True,
            execution_authorized=True,
            publication_authorized=True,
        )
        for value in (report, forged):
            with self.subTest(value=value), self.assertRaises(
                QualityPassParentBridgeV2Error
            ):
                require_quality_pass_bridge_execution_authorized(value)


class PriorAssemblyBridgeTests(unittest.TestCase):
    def test_frozen_v1_prior_assembly_is_authenticated_without_relabeling(self) -> None:
        _parent, child, snapshot = _prior_v1_values()
        report = bind_quality_pass_parent_bridge_v2(
            QualityPassParentBridgeInputsV2(child.inputs, snapshot)
        )
        self.assertEqual(report.parent_authority.kind, "prior-assembly")
        self.assertEqual(report.parent_authority.artifact_class, "assembly-receipt-v1")
        self.assertTrue(report.immediate_base_continuity_bound)
        self.assertFalse(report.execution_authorized)

    def test_v2_prior_assembly_is_authenticated_for_the_next_child(self) -> None:
        _genesis, child, snapshot = _prior_v2_values()
        report = bind_quality_pass_parent_bridge_v2(
            QualityPassParentBridgeInputsV2(child.inputs, snapshot)
        )
        self.assertEqual(report.parent_authority.kind, "prior-assembly")
        self.assertEqual(report.parent_authority.artifact_class, "assembly-receipt-v2")
        self.assertTrue(report.parent_kind_authenticated)
        self.assertFalse(report.runtime_verified)
        self.assertFalse(report.publication_authorized)


if __name__ == "__main__":
    unittest.main(verbosity=2)
