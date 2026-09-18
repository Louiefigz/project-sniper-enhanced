from __future__ import annotations

import dataclasses
import json
import sys
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

PRODUCER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PRODUCER_DIR))

from headless.approved_parent_quality_binding import (  # noqa: E402
    ApprovedParentQualityBindingError,
    validate_approved_parent_quality_chain,
)
from headless.approved_parent_quality_receipts import (  # noqa: E402
    QualityReceiptSchemaError,
    parse_cover_proof_v1,
    parse_critic_receipt_v1,
    parse_final_approval_v3,
    parse_qc_receipt_v1,
    validate_cover_proof_v1,
    validate_critic_receipt_v1,
    validate_final_approval_v3,
    validate_qc_receipt_v1,
)
from headless.generation_schema import parse_generation_commit  # noqa: E402
from _approved_parent_schema_fixture import _artifact, _canonical  # noqa: E402
from _quality_receipt_fixture import (  # noqa: E402
    decoded,
    quality_chain_fixture,
)


def _changed(raw: bytes, key: str, value: object) -> bytes:
    document = decoded(raw)
    document[key] = value
    return _canonical(document)


class QualityReceiptParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = quality_chain_fixture()
        self.records = self.fixture.records

    def test_all_exact_records_parse_and_directly_revalidate(self) -> None:
        validators = (
            (self.records.cover_proof, validate_cover_proof_v1),
            (self.records.qc_receipt, validate_qc_receipt_v1),
            (self.records.critics[0], validate_critic_receipt_v1),
            (self.records.critics[1], validate_critic_receipt_v1),
            (self.records.final_approval, validate_final_approval_v3),
        )
        for value, validator in validators:
            with self.subTest(value=type(value).__name__):
                validator(value)

    def test_cover_proof_exactly_matches_compositor_wire_schema(self) -> None:
        raw = self.records.cover_proof.document_json
        cases = (
            _changed(raw, "frameIndex", True),
            _changed(raw, "frameIndex", 1),
            _changed(raw, "method", "seek-frame-zero"),
            _changed(raw, "schemaVersion", 2),
            _changed(raw, "sourceFinalSha256", "A" * 64),
            _changed(raw, "legacy", True),
        )
        for value in cases:
            with self.subTest(value=value), self.assertRaises(
                QualityReceiptSchemaError
            ):
                parse_cover_proof_v1(value)

    def test_qc_receipt_requires_pass_and_three_distinct_artifact_refs(self) -> None:
        raw = self.records.qc_receipt.document_json
        alias = decoded(raw)
        alias["effectProof"] = alias["audit"]
        cases = (
            _changed(raw, "verdict", "fail"),
            _changed(raw, "qualityPolicyId", "A" * 64),
            _changed(raw, "schemaVersion", True),
            _changed(raw, "extraProof", _artifact("extra.json", "a")),
            _canonical(alias),
        )
        for value in cases:
            with self.subTest(value=value), self.assertRaises(
                QualityReceiptSchemaError
            ):
                parse_qc_receipt_v1(value)

    def test_critic_receipt_has_only_one_closed_passing_lens(self) -> None:
        raw = self.records.critics[0].document_json
        cases = (
            _changed(raw, "lens", "brand"),
            _changed(raw, "verdict", "revise"),
            _changed(raw, "candidateSha256", "0" * 63),
            _changed(raw, "artifact", _artifact("self.json", "a")),
        )
        for value in cases:
            with self.subTest(value=value), self.assertRaises(
                QualityReceiptSchemaError
            ):
                parse_critic_receipt_v1(value)

    def test_final_approval_is_private_nonpublishing_and_ordered(self) -> None:
        raw = self.records.final_approval.document_json
        reversed_critics = list(reversed(decoded(raw)["critics"]))
        cases = (
            _changed(raw, "verdict", "fail"),
            _changed(raw, "candidateDisposition", "published"),
            _changed(raw, "fallbackPolicy", "legacy"),
            _changed(raw, "publicationClaim", True),
            _changed(raw, "publicationClaim", 0),
            _changed(raw, "critics", reversed_critics),
            _changed(raw, "generationId", "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"),
        )
        for value in cases:
            with self.subTest(value=value), self.assertRaises(
                QualityReceiptSchemaError
            ):
                parse_final_approval_v3(value)

    def test_final_approval_rejects_every_cyclic_or_publication_field(self) -> None:
        raw = self.records.final_approval.document_json
        forbidden = {
            "approvedParent": _artifact("approved-parent.json", "a"),
            "generationVerification": _artifact("verification.json", "b"),
            "commitDigest": "c" * 64,
            "publicationSeq": 1,
        }
        for key, value in forbidden.items():
            with self.subTest(key=key), self.assertRaises(QualityReceiptSchemaError):
                parse_final_approval_v3(_changed(raw, key, value))

    def test_every_parser_requires_exact_canonical_bytes(self) -> None:
        cases = (
            (parse_cover_proof_v1, self.records.cover_proof.document_json),
            (parse_qc_receipt_v1, self.records.qc_receipt.document_json),
            (parse_critic_receipt_v1, self.records.critics[0].document_json),
            (parse_final_approval_v3, self.records.final_approval.document_json),
        )
        for parser, raw in cases:
            self._assert_invalid_encodings(parser, raw)

    def _assert_invalid_encodings(
        self, parser: Callable[[object], object], raw: bytes
    ) -> None:
        duplicate = b'{"schemaVersion":1,' + raw[1:]
        nonfinite = raw.replace(b'"schemaVersion":1', b'"schemaVersion":NaN').replace(
            b'"schemaVersion":3', b'"schemaVersion":NaN'
        )
        for invalid in (decoded(raw), raw + b"\n", duplicate, nonfinite):
            with self.subTest(
                parser=parser.__name__, invalid=invalid
            ), self.assertRaises(QualityReceiptSchemaError):
                parser(invalid)

    def test_direct_construction_cannot_forge_semantic_fields(self) -> None:
        cases = (
            (
                dataclasses.replace(
                    self.records.cover_proof, source_final_sha256="0" * 64
                ),
                validate_cover_proof_v1,
            ),
            (
                dataclasses.replace(self.records.qc_receipt, plan_digest="0" * 64),
                validate_qc_receipt_v1,
            ),
            (
                dataclasses.replace(self.records.critics[0], lens="editorial"),
                validate_critic_receipt_v1,
            ),
            (
                dataclasses.replace(
                    self.records.final_approval, quality_policy_id="0" * 64
                ),
                validate_final_approval_v3,
            ),
        )
        for forged, validator in cases:
            with self.subTest(value=type(forged).__name__), self.assertRaises(
                QualityReceiptSchemaError
            ):
                validator(forged)


class QualityChainBindingTests(unittest.TestCase):
    def test_complete_chain_cross_binds_without_opening_paths(self) -> None:
        fixture = quality_chain_fixture()
        with patch("builtins.open", side_effect=AssertionError("path read")):
            validate_approved_parent_quality_chain(
                fixture.descriptor, fixture.commit, fixture.records
            )

    def test_cover_qc_critic_and_approval_semantic_drift_reject(self) -> None:
        fixtures = (
            quality_chain_fixture(cover_change=("sourceFinalSha256", "9" * 64)),
            quality_chain_fixture(qc_change=("planDigest", "9" * 64)),
            quality_chain_fixture(critic_change=("candidateSha256", "9" * 64)),
            quality_chain_fixture(approval_change=("planDigest", "9" * 64)),
        )
        for fixture in fixtures:
            with self.subTest(fixture=fixture), self.assertRaises(
                ApprovedParentQualityBindingError
            ):
                validate_approved_parent_quality_chain(
                    fixture.descriptor, fixture.commit, fixture.records
                )

    def test_qc_evidence_and_final_qc_refs_must_equal_descriptor(self) -> None:
        fixtures = (
            quality_chain_fixture(
                qc_change=("audit", _artifact("quality/wrong-audit.json", "a"))
            ),
            quality_chain_fixture(
                approval_change=(
                    "qcReceipt",
                    _artifact("quality/wrong-qc.json", "b"),
                )
            ),
        )
        for fixture in fixtures:
            with self.subTest(fixture=fixture), self.assertRaises(
                ApprovedParentQualityBindingError
            ):
                validate_approved_parent_quality_chain(
                    fixture.descriptor, fixture.commit, fixture.records
                )

    def test_two_critic_records_must_keep_descriptor_order(self) -> None:
        fixture = quality_chain_fixture()
        records = dataclasses.replace(
            fixture.records, critics=tuple(reversed(fixture.records.critics))
        )
        with self.assertRaisesRegex(ApprovedParentQualityBindingError, "order"):
            validate_approved_parent_quality_chain(
                fixture.descriptor, fixture.commit, records
            )

    def test_receipt_bytes_must_equal_descriptor_and_commit_refs(self) -> None:
        fixture = quality_chain_fixture()
        forged_qc = dataclasses.replace(
            fixture.records.qc_receipt,
            document_json=fixture.records.qc_receipt.document_json + b" ",
        )
        records = dataclasses.replace(fixture.records, qc_receipt=forged_qc)
        with self.assertRaises(ApprovedParentQualityBindingError):
            validate_approved_parent_quality_chain(
                fixture.descriptor, fixture.commit, records
            )

    def test_manifest_artifact_classes_cannot_be_swapped(self) -> None:
        fixture = quality_chain_fixture()
        document = json.loads(fixture.commit.document_json)
        cover = next(
            row for row in document["files"] if row["artifactClass"] == "cover-proof-v1"
        )
        effect = next(
            row
            for row in document["files"]
            if row["artifactClass"] == "effect-proof-v1"
        )
        cover["artifactClass"], effect["artifactClass"] = (
            effect["artifactClass"],
            cover["artifactClass"],
        )
        commit = parse_generation_commit(_canonical(document))
        with self.assertRaises(ApprovedParentQualityBindingError):
            validate_approved_parent_quality_chain(
                fixture.descriptor, commit, fixture.records
            )

    def test_directly_forged_commit_instance_rejects(self) -> None:
        fixture = quality_chain_fixture()
        commit = dataclasses.replace(fixture.commit, quality_policy_id="0" * 64)
        with self.assertRaisesRegex(ApprovedParentQualityBindingError, "construction"):
            validate_approved_parent_quality_chain(
                fixture.descriptor, commit, fixture.records
            )


if __name__ == "__main__":
    unittest.main()
