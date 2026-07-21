"""Exact schema/profile regressions for the genesis-to-first-child bridge."""

from __future__ import annotations

import dataclasses
import unittest

from _approved_parent_loader_documents import AuthorityDocuments
from _approved_parent_loader_values import canonical
from _assembly_receipt_fixture import assembly_fixture
from _common import pl  # noqa: F401
from _genesis_r1_fixture import genesis_r1_fixture
from _quality_pass_v2_fixture import build_quality_pass_v2_child, changed, decoded
from headless.approved_parent_assembly_receipt import (
    AssemblyReceiptSchemaError,
    parse_assembly_receipt_v1,
)
from headless.approved_parent_schema import (
    ApprovedParentSchemaError,
    parse_approved_parent_descriptor,
)
from headless.generation_profile import R0_MANIFEST_ROWS
from headless.genesis_approved_card import parse_genesis_approved_card_v2
from headless.genesis_generation_profile import GENESIS_R1_PROFILE
from headless.repair_intent import ParentRefV1
from headless.versioned_assembly_receipt import (
    AssemblyReceiptV2Error,
    parse_assembly_receipt_v2,
    validate_assembly_receipt_v2,
)
from headless.versioned_generation_profile_dispatch import (
    VersionedGenerationProfileDispatchError,
    select_versioned_generation_profile,
)
from headless.versioned_parent_authority import (
    ParentAuthorityV2,
    VersionedParentAuthorityError,
    parent_authority_document,
    parse_parent_authority_v2,
)
from headless.versioned_quality_pass_card import (
    QualityPassApprovedCardV2Error,
    parse_quality_pass_approved_card_v2,
    validate_quality_pass_approved_card_v2,
)
from headless.versioned_quality_pass_profile import (
    QUALITY_PASS_R1_CLASS_COUNTS,
    QUALITY_PASS_R1_MANIFEST_ROWS,
    QUALITY_PASS_R1_PROFILE,
    QualityPassGenerationProfileV2Error,
    verify_quality_pass_r1_profile,
)
from headless.versioned_quality_pass_verification import (
    QualityPassGenerationVerificationV2Error,
    parse_quality_pass_generation_verification_v2,
    validate_quality_pass_generation_verification_v2,
)


def _genesis_child() -> tuple:
    parent = genesis_r1_fixture().inputs
    ref = ParentRefV1(
        parent.commit.authority_id,
        1,
        parent.commit.generation_id,
        parent.commit.commit_digest,
        parent.approved_card.plan.approved_plan_digest,
    )
    authority = ParentAuthorityV2(
        "genesis-origin",
        "initialization-origin-receipt-v1",
        parent.approved_card.origin.receipt,
    )
    return parent, build_quality_pass_v2_child(ref, parent.approved_card, authority)


class FrozenV1IncompatibilityTests(unittest.TestCase):
    def test_v1_requires_parent_assembly_while_genesis_has_only_origin(self) -> None:
        parent, child = _genesis_child()
        genesis_document = decoded(parent.approved_card.document_json)
        self.assertNotIn("assemblyReceipt", genesis_document["output"])
        self.assertIn("receipt", genesis_document["origin"])
        self.assertTrue(
            hasattr(assembly_fixture().receipt, "parent_assembly_receipt_sha256")
        )
        v2_document = decoded(child.inputs.assembly_receipt.document_json)
        self.assertNotIn("parentAssemblyReceiptSha256", v2_document)
        self.assertEqual(v2_document["parentAuthority"]["kind"], "genesis-origin")
        with self.assertRaises(AssemblyReceiptSchemaError):
            parse_assembly_receipt_v1(child.inputs.assembly_receipt.document_json)

    def test_v1_cannot_accept_parent_authority_as_a_field_alias(self) -> None:
        parent, _child = _genesis_child()
        document = decoded(assembly_fixture().receipt.document_json)
        document.pop("parentAssemblyReceiptSha256")
        document["parentAuthority"] = {
            "kind": "genesis-origin",
            "artifactClass": "initialization-origin-receipt-v1",
            "receipt": {
                "path": parent.approved_card.origin.receipt.relative_path,
                "sha256": parent.approved_card.origin.receipt.sha256,
                "sizeBytes": parent.approved_card.origin.receipt.size_bytes,
            },
        }
        with self.assertRaises(AssemblyReceiptSchemaError):
            parse_assembly_receipt_v1(canonical(document))


class ParentAuthorityV2SchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parent, self.child = _genesis_child()
        self.origin = self.child.parent_authority

    def test_only_exact_kind_and_artifact_class_pairs_are_valid(self) -> None:
        v1 = assembly_fixture().descriptor.output.assembly_receipt
        v2 = self.child.inputs.approved_card.output.assembly_receipt
        values = (
            self.origin,
            ParentAuthorityV2("prior-assembly", "assembly-receipt-v1", v1),
            ParentAuthorityV2("prior-assembly", "assembly-receipt-v2", v2),
        )
        for value in values:
            with self.subTest(value=value):
                document = parent_authority_document(value)
                self.assertEqual(parse_parent_authority_v2(document), value)

    def test_origin_can_never_be_labeled_as_assembly_or_conversely(self) -> None:
        document = parent_authority_document(self.origin)
        cases = []
        for kind, artifact_class in (
            ("prior-assembly", "initialization-origin-receipt-v1"),
            ("genesis-origin", "assembly-receipt-v1"),
            ("genesis-origin", "assembly-receipt-v2"),
        ):
            changed_document = dict(document)
            changed_document["kind"] = kind
            changed_document["artifactClass"] = artifact_class
            cases.append(changed_document)
        extra = dict(document)
        extra["parentAssemblyReceiptSha256"] = self.origin.receipt.sha256
        cases.append(extra)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(
                VersionedParentAuthorityError
            ):
                parse_parent_authority_v2(value)


class AssemblyReceiptV2SchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.receipt = _genesis_child()[1].inputs.assembly_receipt
        self.raw = self.receipt.document_json

    def test_exact_v2_receipt_revalidates_and_has_no_legacy_parent_digest(self) -> None:
        validate_assembly_receipt_v2(self.receipt)
        self.assertEqual(parse_assembly_receipt_v2(self.raw), self.receipt)
        self.assertFalse(hasattr(self.receipt, "parent_assembly_receipt_sha256"))
        self.assertEqual(self.receipt.parent_authority.kind, "genesis-origin")

    def test_v2_envelope_and_parent_discriminant_are_closed(self) -> None:
        legacy = decoded(self.raw)
        legacy["parentAssemblyReceiptSha256"] = "0" * 64
        wrong = decoded(self.raw)
        wrong["parentAuthority"]["artifactClass"] = "assembly-receipt-v1"
        cases = (
            self.raw + b"\n",
            b'{"schemaVersion":2,' + self.raw[1:],
            changed(self.raw, ("schemaVersion",), 1),
            changed(self.raw, ("status",), "published"),
            canonical(legacy),
            canonical(wrong),
        )
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(AssemblyReceiptV2Error):
                parse_assembly_receipt_v2(raw)

    def test_direct_construction_cannot_forge_parent_kind(self) -> None:
        authority = dataclasses.replace(
            self.receipt.parent_authority,
            kind="prior-assembly",
            artifact_class="assembly-receipt-v1",
        )
        forged = dataclasses.replace(self.receipt, parent_authority=authority)
        with self.assertRaises(AssemblyReceiptV2Error):
            validate_assembly_receipt_v2(forged)


class QualityPassCardAndProfileV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.parent, self.child = _genesis_child()
        self.inputs = self.child.inputs

    def test_card_is_disjoint_from_both_v1_and_genesis_cards(self) -> None:
        validate_quality_pass_approved_card_v2(self.inputs.approved_card)
        with self.assertRaises(ApprovedParentSchemaError):
            parse_approved_parent_descriptor(self.inputs.approved_card.document_json)
        with self.assertRaises(RuntimeError):
            parse_genesis_approved_card_v2(self.inputs.approved_card.document_json)
        document = decoded(self.inputs.approved_card.document_json)
        self.assertIn("assemblyReceipt", document["output"])
        self.assertNotIn("origin", document)

    def test_card_requires_non_null_exact_parent_and_closed_envelope(self) -> None:
        extra = decoded(self.inputs.approved_card.document_json)
        extra["origin"] = {"legacy": True}
        cases = (
            changed(self.inputs.approved_card.document_json, ("expectedParent",), None),
            changed(self.inputs.approved_card.document_json, ("schemaVersion",), 1),
            canonical(extra),
        )
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(
                QualityPassApprovedCardV2Error
            ):
                parse_quality_pass_approved_card_v2(raw)

    def test_exact_profile_replaces_only_card_assembly_and_verification(self) -> None:
        groups = verify_quality_pass_r1_profile(self.inputs.commit)
        self.assertEqual(QUALITY_PASS_R1_MANIFEST_ROWS, 42)
        self.assertEqual(R0_MANIFEST_ROWS, 42)
        self.assertEqual(tuple(groups), tuple(QUALITY_PASS_R1_CLASS_COUNTS))
        for name in (
            "approved-parent-v1",
            "assembly-receipt-v1",
            "generation-verification-v1",
        ):
            self.assertNotIn(name, groups)

    def test_pure_dispatch_is_explicit_and_has_no_null_parent_r0_fallback(self) -> None:
        genesis = select_versioned_generation_profile(self.parent.commit)
        quality = select_versioned_generation_profile(self.inputs.commit)
        frozen = select_versioned_generation_profile(assembly_fixture().commit)
        self.assertEqual(genesis.profile, GENESIS_R1_PROFILE)
        self.assertEqual(quality.profile, QUALITY_PASS_R1_PROFILE)
        self.assertEqual(frozen.approved_card_class, "approved-parent-v1")
        with self.assertRaises(VersionedGenerationProfileDispatchError):
            select_versioned_generation_profile(AuthorityDocuments().commit)

    def test_genesis_commit_cannot_enter_quality_pass_profile(self) -> None:
        with self.assertRaises(QualityPassGenerationProfileV2Error):
            verify_quality_pass_r1_profile(self.parent.commit)


class QualityPassVerificationV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.inputs = _genesis_child()[1].inputs

    def test_exact_verification_binds_parent_authority_and_payload(self) -> None:
        value = self.inputs.verification
        validate_quality_pass_generation_verification_v2(value, self.inputs.commit)
        self.assertEqual(
            value.parent_authority, self.inputs.assembly_receipt.parent_authority
        )
        self.assertEqual(value.status, "structural-pass-runtime-unverified")

    def test_payload_or_parent_authority_tamper_rejects(self) -> None:
        payload = parse_quality_pass_generation_verification_v2(
            changed(
                self.inputs.verification.document_json,
                ("payloadManifestDigest",),
                "0" * 64,
            )
        )
        with self.assertRaises(QualityPassGenerationVerificationV2Error):
            validate_quality_pass_generation_verification_v2(
                payload, self.inputs.commit
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
