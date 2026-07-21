from __future__ import annotations

import dataclasses
import json
import sys
import unittest
from pathlib import Path

PRODUCER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PRODUCER_DIR))

from headless.artifact_contract import ArtifactRefV1  # noqa: E402
from headless.generation_profile import (  # noqa: E402
    R0_GENERATION_ARTIFACT_CLASS_COUNTS,
)
from headless.generation_schema import parse_generation_commit  # noqa: E402
from headless.generation_verification import (  # noqa: E402
    GenerationVerificationError,
    parse_generation_verification,
    payload_manifest_digest,
    validate_generation_verification,
)

GENERATION = "11111111-1111-4111-8111-111111111111"
ATTEMPT = "22222222-2222-4222-8222-222222222222"
UNIT = "33333333-3333-4333-8333-333333333333"


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True, allow_nan=False
    ).encode("ascii")


def _rows() -> list[dict]:
    rows = []
    ordinal = 1
    for artifact_class, count in R0_GENERATION_ARTIFACT_CLASS_COUNTS.items():
        for index in range(count):
            suffix = f"-{index}" if count > 1 else ""
            rows.append(
                {
                    "artifactClass": artifact_class,
                    "path": f"artifacts/{artifact_class}{suffix}.json",
                    "sha256": f"{ordinal:064x}",
                    "sizeBytes": ordinal + 10,
                }
            )
            ordinal += 1
    return rows


def _commit():
    rows = _rows()
    approved = next(row for row in rows if row["artifactClass"] == "approved-parent-v1")
    document = {
        "schemaVersion": 1,
        "authorityId": "authority-mp4-v1",
        "generationId": GENERATION,
        "attemptId": ATTEMPT,
        "unitId": UNIT,
        "requestDigest": "1" * 64,
        "expectedParent": None,
        "executionPolicyId": "2" * 64,
        "repairPolicyId": "3" * 64,
        "qualityPolicyId": "4" * 64,
        "fallbackPolicyId": "5" * 64,
        "approvedParentPath": approved["path"],
        "files": rows,
    }
    return parse_generation_commit(document)


def _approved(commit) -> ArtifactRefV1:
    row = next(
        row for row in commit.files if row.artifact_class == "approved-parent-v1"
    )
    return ArtifactRefV1(row.path, row.sha256, row.size_bytes)


def _document(commit) -> dict:
    payload = tuple(
        row
        for row in commit.files
        if row.artifact_class != "generation-verification-v1"
    )
    approved = _approved(commit)
    return {
        "schemaVersion": 1,
        "status": "pass",
        "profile": "deterministic-mp4-r0-v1",
        "authorityId": commit.authority_id,
        "generationId": commit.generation_id,
        "attemptId": commit.attempt_id,
        "unitId": commit.unit_id,
        "requestDigest": commit.request_digest,
        "executionPolicyId": commit.execution_policy_id,
        "repairPolicyId": commit.repair_policy_id,
        "qualityPolicyId": commit.quality_policy_id,
        "fallbackPolicyId": commit.fallback_policy_id,
        "approvedParent": {
            "path": approved.relative_path,
            "sha256": approved.sha256,
            "sizeBytes": approved.size_bytes,
        },
        "payloadManifestDigest": payload_manifest_digest(payload),
    }


class GenerationVerificationTests(unittest.TestCase):
    def test_exact_record_binds_complete_commit_payload(self) -> None:
        commit = _commit()
        document = _document(commit)
        parsed = parse_generation_verification(_canonical(document))
        validate_generation_verification(parsed, commit, _approved(commit))
        self.assertEqual(parse_generation_verification(document), parsed)

    def test_payload_digest_excludes_only_verification_row(self) -> None:
        commit = _commit()
        with self.assertRaisesRegex(GenerationVerificationError, "recursive"):
            payload_manifest_digest(commit.files)
        empty = tuple(
            row
            for row in commit.files
            if row.artifact_class == "generation-verification-v1"
        )
        with self.assertRaises(GenerationVerificationError):
            payload_manifest_digest(empty)

    def test_any_payload_row_change_invalidates_verification(self) -> None:
        first = _commit()
        parsed = parse_generation_verification(_document(first))
        rows = _rows()
        row = next(item for item in rows if item["artifactClass"] == "cover-image-v1")
        row["sha256"] = "f" * 64
        document = json.loads(first.document_json)
        document["files"] = rows
        changed = parse_generation_commit(document)
        with self.assertRaisesRegex(GenerationVerificationError, "does not bind"):
            validate_generation_verification(parsed, changed, _approved(changed))

    def test_policy_parent_and_generation_substitution_reject(self) -> None:
        commit = _commit()
        document = _document(commit)
        cases = []
        for key, value in (
            ("qualityPolicyId", "9" * 64),
            ("repairPolicyId", "8" * 64),
            ("executionPolicyId", "7" * 64),
            ("fallbackPolicyId", "6" * 64),
            ("requestDigest", "5" * 64),
            ("generationId", "44444444-4444-4444-8444-444444444444"),
        ):
            changed = dict(document)
            changed[key] = value
            cases.append(changed)
        parent = dict(document)
        parent["approvedParent"] = dict(parent["approvedParent"])
        parent["approvedParent"]["sha256"] = "7" * 64
        cases.append(parent)
        for value in cases:
            parsed = parse_generation_verification(value)
            with self.subTest(value=value), self.assertRaises(
                GenerationVerificationError
            ):
                validate_generation_verification(parsed, commit, _approved(commit))

    def test_unknown_noncanonical_duplicate_and_nonfinite_reject(self) -> None:
        document = _document(_commit())
        extra = dict(document)
        extra["commitDigest"] = "0" * 64
        with self.assertRaises(GenerationVerificationError):
            parse_generation_verification(extra)
        raw = _canonical(document)
        with self.assertRaisesRegex(GenerationVerificationError, "canonical"):
            parse_generation_verification(raw + b"\n")
        duplicate = raw.replace(
            b'{"approvedParent":', b'{"schemaVersion":1,"approvedParent":', 1
        )
        with self.assertRaisesRegex(GenerationVerificationError, "duplicate"):
            parse_generation_verification(duplicate)
        with self.assertRaises(GenerationVerificationError):
            parse_generation_verification(
                raw.replace(b'"schemaVersion":1', b'"schemaVersion":NaN')
            )

    def test_direct_dataclass_construction_cannot_forge_binding(self) -> None:
        commit = _commit()
        parsed = parse_generation_verification(_document(commit))
        forged = dataclasses.replace(parsed, payload_manifest_digest="0" * 64)
        with self.assertRaisesRegex(GenerationVerificationError, "identity"):
            validate_generation_verification(forged, commit, _approved(commit))


if __name__ == "__main__":
    unittest.main()
