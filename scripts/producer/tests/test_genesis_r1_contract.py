"""Exact-schema and disjoint-profile tests for genesis R1."""

from __future__ import annotations

import dataclasses
import unittest

from _approved_parent_loader_documents import AuthorityDocuments
from _approved_parent_loader_values import canonical
from _assembly_receipt_fixture import assembly_fixture
from _common import pl  # noqa: F401
from _genesis_r1_fixture import changed, decoded, genesis_r1_fixture
from headless.generation_profile import R0_MANIFEST_ROWS
from headless.generation_schema import parse_generation_commit
from headless.genesis_approved_card import (
    GenesisApprovedCardError,
    parse_genesis_approved_card_v2,
    validate_genesis_approved_card_v2,
)
from headless.genesis_execution_policy import (
    GenesisExecutionPolicyError,
    bind_initialize_operation_policy_v2,
    current_initialization_execution_policy_v2,
    parse_initialization_execution_policy_v2,
    validate_initialization_execution_policy_v2,
)
from headless.genesis_generation_profile import (
    GENESIS_R1_ARTIFACT_CLASS_BYTE_CAPS,
    GENESIS_R1_GENERATION_ARTIFACT_CLASS_COUNTS,
    GENESIS_R1_MANIFEST_ROWS,
    GENESIS_R1_PROFILE,
    GENESIS_R1_SEMANTIC_DOCUMENT_MAX_BYTES,
    GenesisGenerationProfileError,
    select_disjoint_generation_profile,
    verify_genesis_r1_generation_profile,
)
from headless.genesis_generation_verification import (
    GenesisGenerationVerificationError,
    parse_genesis_generation_verification_v2,
    validate_genesis_generation_verification_v2,
)


class InitializationExecutionPolicyV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = genesis_r1_fixture()
        self.policy = self.fixture.inputs.initialization_policy

    def test_exact_policy_is_initialize_capable_but_not_a_runtime_gate(self) -> None:
        parsed = parse_initialization_execution_policy_v2(self.policy.document_json)
        validate_initialization_execution_policy_v2(parsed)
        self.assertEqual(parsed, current_initialization_execution_policy_v2())
        binding = bind_initialize_operation_policy_v2(
            self.fixture.inputs.operation, parsed
        )
        self.assertTrue(binding.policy_compatible)
        self.assertFalse(binding.runtime_verified)
        self.assertFalse(binding.execution_authorized)
        self.assertFalse(binding.publication_authorized)

    def test_policy_is_exact_canonical_and_closed(self) -> None:
        document = decoded(self.policy.document_json)
        extra = decoded(self.policy.document_json)
        extra["initialization"]["baseRebuildAllowed"] = False
        integer_bool = decoded(self.policy.document_json)
        integer_bool["executionPath"]["guiAllowed"] = 0
        quality = decoded(self.policy.document_json)
        quality["initialization"]["operation"] = "quality-pass"
        duplicate = b'{"schemaVersion":2,' + self.policy.document_json[1:]
        cases = (
            document,
            self.policy.document_json + b"\n",
            duplicate,
            canonical(extra),
            canonical(integer_bool),
            canonical(quality),
        )
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(GenesisExecutionPolicyError):
                parse_initialization_execution_policy_v2(raw)

    def test_forged_policy_and_stale_operation_reject(self) -> None:
        forged = dataclasses.replace(self.policy, publication_allowed=True)
        with self.assertRaises(GenesisExecutionPolicyError):
            validate_initialization_execution_policy_v2(forged)
        operation = dataclasses.replace(
            self.fixture.inputs.operation, execution_policy_id="0" * 64
        )
        with self.assertRaises(GenesisExecutionPolicyError):
            bind_initialize_operation_policy_v2(operation, self.policy)


class GenesisApprovedCardV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.card = genesis_r1_fixture().inputs.approved_card

    def test_exact_genesis_card_references_origin_and_never_assembly(self) -> None:
        parsed = parse_genesis_approved_card_v2(self.card.document_json)
        validate_genesis_approved_card_v2(parsed)
        document = decoded(parsed.document_json)
        self.assertIsNone(parsed.expected_parent)
        self.assertIn("origin", document)
        self.assertNotIn("assemblyReceipt", document["output"])
        self.assertNotIn("assemblyReceipt", document)

    def test_card_envelope_and_every_new_section_are_closed(self) -> None:
        origin_extra = decoded(self.card.document_json)
        origin_extra["origin"]["assemblyReceipt"] = origin_extra["origin"]["receipt"]
        output_extra = decoded(self.card.document_json)
        output_extra["output"]["assemblyReceipt"] = output_extra["output"]["cover"]
        top_extra = decoded(self.card.document_json)
        top_extra["publicationSeq"] = 1
        cases = (
            self.card.document_json + b"\n",
            b'{"schemaVersion":2,' + self.card.document_json[1:],
            changed(self.card.document_json, ("schemaVersion",), 1),
            changed(self.card.document_json, ("expectedParent",), False),
            changed(self.card.document_json, ("status",), "published"),
            canonical(origin_extra),
            canonical(output_extra),
            canonical(top_extra),
        )
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(GenesisApprovedCardError):
                parse_genesis_approved_card_v2(raw)

    def test_origin_paths_cannot_alias_and_direct_construction_cannot_forge(
        self,
    ) -> None:
        document = decoded(self.card.document_json)
        document["origin"]["snapshotAuthority"]["path"] = document["origin"][
            "operation"
        ]["path"].upper()
        with self.assertRaises(GenesisApprovedCardError):
            parse_genesis_approved_card_v2(canonical(document))
        forged = dataclasses.replace(self.card, status="published")
        with self.assertRaises(GenesisApprovedCardError):
            validate_genesis_approved_card_v2(forged)


class DisjointGenesisProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = genesis_r1_fixture()

    def test_exact_44_row_profile_replaces_r0_assembly_authorities(self) -> None:
        groups = verify_genesis_r1_generation_profile(self.fixture.inputs.commit)
        self.assertEqual(len(self.fixture.inputs.commit.files), 44)
        self.assertEqual(GENESIS_R1_MANIFEST_ROWS, 44)
        self.assertEqual(R0_MANIFEST_ROWS, 42)
        self.assertEqual(
            tuple(groups), tuple(GENESIS_R1_GENERATION_ARTIFACT_CLASS_COUNTS)
        )
        for name in (
            "approved-parent-v1",
            "generation-verification-v1",
            "execution-policy-v1",
            "assembly-receipt-v1",
        ):
            self.assertNotIn(name, groups)

    def test_expected_parent_alone_selects_the_disjoint_profile(self) -> None:
        genesis = select_disjoint_generation_profile(self.fixture.inputs.commit)
        quality = select_disjoint_generation_profile(assembly_fixture().commit)
        self.assertEqual(genesis.profile, GENESIS_R1_PROFILE)
        self.assertTrue(genesis.expected_parent_is_null)
        self.assertFalse(quality.expected_parent_is_null)
        with self.assertRaises(GenesisGenerationProfileError):
            select_disjoint_generation_profile(AuthorityDocuments().commit)

    def test_semantic_document_cap_is_profile_authority(self) -> None:
        artifact_class = "genesis-approved-card-v2"
        self.assertEqual(
            GENESIS_R1_ARTIFACT_CLASS_BYTE_CAPS[artifact_class],
            GENESIS_R1_SEMANTIC_DOCUMENT_MAX_BYTES,
        )
        document = decoded(self.fixture.inputs.commit.document_json)
        row = next(
            item
            for item in document["files"]
            if item["artifactClass"] == artifact_class
        )
        row["sizeBytes"] = GENESIS_R1_SEMANTIC_DOCUMENT_MAX_BYTES + 1
        with self.assertRaises(GenesisGenerationProfileError):
            verify_genesis_r1_generation_profile(parse_generation_commit(document))

    def test_r1_with_parent_and_wrong_card_class_reject(self) -> None:
        document = decoded(self.fixture.inputs.commit.document_json)
        document["expectedParent"] = decoded(assembly_fixture().commit.document_json)[
            "expectedParent"
        ]
        with self.assertRaises(GenesisGenerationProfileError):
            verify_genesis_r1_generation_profile(parse_generation_commit(document))
        forged = dataclasses.replace(
            self.fixture.inputs.commit,
            expected_parent=assembly_fixture().commit.expected_parent,
        )
        with self.assertRaises(GenesisGenerationProfileError):
            select_disjoint_generation_profile(forged)
        document = decoded(self.fixture.inputs.commit.document_json)
        card = next(
            row
            for row in document["files"]
            if row["artifactClass"] == "genesis-approved-card-v2"
        )
        card["artifactClass"] = "approved-parent-v1"
        with self.assertRaises(GenesisGenerationProfileError):
            verify_genesis_r1_generation_profile(parse_generation_commit(document))


class GenesisVerificationV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = genesis_r1_fixture()
        self.value = self.fixture.inputs.verification

    def test_exact_structural_verification_binds_without_runtime_claim(self) -> None:
        parsed = parse_genesis_generation_verification_v2(self.value.document_json)
        validate_genesis_generation_verification_v2(parsed, self.fixture.inputs.commit)
        self.assertEqual(parsed.status, "structural-pass-runtime-unverified")
        self.assertIsNone(parsed.expected_parent)

    def test_verification_is_closed_and_payload_tamper_rejects(self) -> None:
        with self.assertRaises(GenesisGenerationVerificationError):
            parse_genesis_generation_verification_v2(self.value.document_json + b"\n")
        changed_value = parse_genesis_generation_verification_v2(
            changed(self.value.document_json, ("payloadManifestDigest",), "0" * 64)
        )
        with self.assertRaises(GenesisGenerationVerificationError):
            validate_genesis_generation_verification_v2(
                changed_value, self.fixture.inputs.commit
            )
        forged = dataclasses.replace(self.value, status="pass")
        with self.assertRaises(GenesisGenerationVerificationError):
            validate_genesis_generation_verification_v2(
                forged, self.fixture.inputs.commit
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
