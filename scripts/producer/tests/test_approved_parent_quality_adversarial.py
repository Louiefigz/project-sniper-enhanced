from __future__ import annotations

import dataclasses
import hashlib
import json
import sys
import unittest
from pathlib import Path

PRODUCER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PRODUCER_DIR))

from headless.approved_parent_quality_binding import (  # noqa: E402
    ApprovedParentQualityBindingError,
    validate_approved_parent_quality_chain,
)
from headless.approved_parent_quality_receipts import (  # noqa: E402
    QualityReceiptSchemaError,
    parse_qc_receipt_v1,
    validate_cover_proof_v1,
    validate_critic_receipt_v1,
    validate_final_approval_v3,
    validate_qc_receipt_v1,
)
from headless.approved_parent_schema import (  # noqa: E402
    parse_approved_parent_descriptor,
)
from headless.generation_schema import parse_generation_commit  # noqa: E402
from _approved_parent_schema_fixture import _artifact, _canonical  # noqa: E402
from _quality_receipt_fixture import decoded, quality_chain_fixture  # noqa: E402


class _AlwaysEqual:
    def __eq__(self, value: object) -> bool:
        return True


class QualityReceiptAdversarialTests(unittest.TestCase):
    def test_hostile_equality_cannot_forge_direct_construction(self) -> None:
        records = quality_chain_fixture().records
        cases = (
            (
                dataclasses.replace(
                    records.cover_proof, source_final_sha256=_AlwaysEqual()
                ),
                validate_cover_proof_v1,
            ),
            (
                dataclasses.replace(records.qc_receipt, plan_digest=_AlwaysEqual()),
                validate_qc_receipt_v1,
            ),
            (
                dataclasses.replace(
                    records.critics[0], candidate_sha256=_AlwaysEqual()
                ),
                validate_critic_receipt_v1,
            ),
            (
                dataclasses.replace(
                    records.final_approval, request_digest=_AlwaysEqual()
                ),
                validate_final_approval_v3,
            ),
        )
        for forged, validator in cases:
            with self.subTest(value=type(forged).__name__), self.assertRaises(
                QualityReceiptSchemaError
            ):
                validator(forged)

    def test_hostile_equality_cannot_forge_descriptor_or_commit(self) -> None:
        fixture = quality_chain_fixture()
        identity = dataclasses.replace(
            fixture.descriptor.identity, request_digest=_AlwaysEqual()
        )
        descriptor = dataclasses.replace(fixture.descriptor, identity=identity)
        commit = dataclasses.replace(fixture.commit, request_digest=_AlwaysEqual())
        for changed_descriptor, changed_commit in (
            (descriptor, fixture.commit),
            (fixture.descriptor, commit),
        ):
            with self.assertRaises(ApprovedParentQualityBindingError):
                validate_approved_parent_quality_chain(
                    changed_descriptor, changed_commit, fixture.records
                )

    def test_hostile_equality_cannot_forge_whole_record_chain(self) -> None:
        fixture = quality_chain_fixture()
        qc = dataclasses.replace(fixture.records.qc_receipt, plan_digest=_AlwaysEqual())
        records = dataclasses.replace(fixture.records, qc_receipt=qc)
        with self.assertRaises(ApprovedParentQualityBindingError):
            validate_approved_parent_quality_chain(
                fixture.descriptor, fixture.commit, records
            )

    def test_qc_proof_roles_cannot_reuse_identical_bytes(self) -> None:
        raw = quality_chain_fixture().records.qc_receipt.document_json
        document = decoded(raw)
        shared = _artifact("quality/shared-proof.json", "a")
        document["audit"] = shared
        document["fullDecode"] = {**shared, "path": "quality/shared-full.json"}
        document["effectProof"] = {**shared, "path": "quality/shared-effect.json"}
        with self.assertRaisesRegex(QualityReceiptSchemaError, "bytes alias"):
            parse_qc_receipt_v1(_canonical(document))

    def test_qc_proof_bytes_cannot_alias_final_or_assembly_product(self) -> None:
        fixture = quality_chain_fixture(
            qc_change=("audit", _artifact("quality/final-as-audit.mp4", "c"))
        )
        descriptor_document = json.loads(fixture.descriptor.document_json)
        descriptor_document["quality"]["audit"] = _artifact(
            "quality/final-as-audit.mp4", "c"
        )
        descriptor_raw = _canonical(descriptor_document)
        descriptor = parse_approved_parent_descriptor(descriptor_raw)
        commit_document = json.loads(fixture.commit.document_json)
        approved = next(
            row
            for row in commit_document["files"]
            if row["artifactClass"] == "approved-parent-v1"
        )
        approved["sha256"] = hashlib.sha256(descriptor_raw).hexdigest()
        approved["sizeBytes"] = len(descriptor_raw)
        audit = next(
            row
            for row in commit_document["files"]
            if row["artifactClass"] == "audit-b-receipt-v1"
        )
        audit.update({"path": "quality/final-as-audit.mp4", "sha256": "c" * 64})
        commit_document["files"].sort(key=lambda row: row["path"])
        commit = parse_generation_commit(_canonical(commit_document))
        with self.assertRaisesRegex(ApprovedParentQualityBindingError, "product bytes"):
            validate_approved_parent_quality_chain(descriptor, commit, fixture.records)


if __name__ == "__main__":
    unittest.main()
