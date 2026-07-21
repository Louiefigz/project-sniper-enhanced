from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

PRODUCER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PRODUCER_DIR))

from headless.generation_profile import (  # noqa: E402
    GenerationProfileError,
    R0_ARTIFACT_CLASS_BYTE_CAPS,
    R0_GENERATION_ARTIFACT_CLASS_COUNTS,
    R0_MANIFEST_ROWS,
    R0_MAX_AGGREGATE_BYTES,
    R0_MAX_PATH_DEPTH,
    R0_SINGLETON_ARTIFACT_CLASSES,
    verify_r0_generation_profile,
)
from headless.generation_schema import (  # noqa: E402
    GenerationCommitV1,
    parse_generation_commit,
)

GENERATION = "11111111-1111-4111-8111-111111111111"
ATTEMPT = "22222222-2222-4222-8222-222222222222"
UNIT = "33333333-3333-4333-8333-333333333333"

EXPECTED_SINGLETONS = (
    "approved-parent-v1",
    "generation-verification-v1",
    "request-identity-v1",
    "execution-policy-v1",
    "repair-policy-v1",
    "quality-policy-v1",
    "fallback-policy-v1",
    "admission-inputs-v1",
    "realization-inputs-v1",
    "generation-inputs-v1",
    "source-snapshot-manifest-v1",
    "operator-intent-v1",
    "cut-approval-v1",
    "asset-closure-v1",
    "runtime-capability-manifest-v1",
    "repair-state-v1",
    "realization-v1",
    "template-usage-approval-v1",
    "proxy-disposition-v1",
    "refit-disposition-v1",
    "plan-v1",
    "base-media-v1",
    "base-plan-v1",
    "base-receipt-v1",
    "base-fingerprint-v1",
    "timeline-map-v1",
    "prebound-clips-v1",
    "render-build-receipt-v1",
    "compositor-build-receipt-v1",
    "final-media-v1",
    "assembly-receipt-v1",
    "cover-image-v1",
    "cover-proof-v1",
    "audit-b-receipt-v1",
    "full-decode-proof-v1",
    "effect-proof-v1",
    "qc-receipt-v1",
    "final-approval-v3",
)


def _row(artifact_class: str, ordinal: int = 0) -> dict:
    return {
        "artifactClass": artifact_class,
        "path": f"artifacts/{artifact_class}-{ordinal}.json",
        "sizeBytes": 10 + ordinal,
        "sha256": f"{ordinal + 1:064x}",
    }


def _files() -> list[dict]:
    rows = []
    for artifact_class, count in R0_GENERATION_ARTIFACT_CLASS_COUNTS.items():
        rows.extend(_row(artifact_class, ordinal) for ordinal in range(count))
    return sorted(rows, key=lambda row: row["path"])


def _commit_document() -> dict:
    files = _files()
    approved = next(
        row for row in files if row["artifactClass"] == "approved-parent-v1"
    )
    return {
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
        "files": files,
    }


def _commit(document: dict | None = None) -> GenerationCommitV1:
    return parse_generation_commit(document or _commit_document())


def _replace_class(document: dict, old: str, new: str) -> None:
    row = next(item for item in document["files"] if item["artifactClass"] == old)
    row["artifactClass"] = new
    row["path"] = f"artifacts/{new}.json"


class R0GenerationProfileTests(unittest.TestCase):
    def test_valid_profile_returns_immutable_ordered_groups(self) -> None:
        groups = verify_r0_generation_profile(_commit())
        self.assertEqual(tuple(groups), tuple(R0_GENERATION_ARTIFACT_CLASS_COUNTS))
        self.assertEqual(len(groups["critic-receipt-v1"]), 2)
        self.assertTrue(groups["critic-receipt-v1"][0].path.endswith("-0.json"))
        self.assertTrue(groups["critic-receipt-v1"][1].path.endswith("-1.json"))
        with self.assertRaises(TypeError):
            groups["banana"] = ()
        with self.assertRaises(TypeError):
            R0_GENERATION_ARTIFACT_CLASS_COUNTS["banana"] = 1

    def test_arbitrary_banana_class_rejects(self) -> None:
        document = _commit_document()
        _replace_class(document, "effect-proof-v1", "banana")
        with self.assertRaisesRegex(GenerationProfileError, "unknown.*banana"):
            verify_r0_generation_profile(_commit(document))

    def test_missing_singleton_rejects(self) -> None:
        document = _commit_document()
        document["files"] = [
            row
            for row in document["files"]
            if row["artifactClass"] != "base-fingerprint-v1"
        ]
        with self.assertRaisesRegex(GenerationProfileError, "exactly"):
            verify_r0_generation_profile(_commit(document))

    def test_approved_parent_path_row_must_have_approved_parent_class(self) -> None:
        document = _commit_document()
        approved_path = document["approvedParentPath"]
        row = next(item for item in document["files"] if item["path"] == approved_path)
        row["artifactClass"] = "final-media-v1"
        with self.assertRaisesRegex(GenerationProfileError, "approvedParentPath row"):
            verify_r0_generation_profile(_commit(document))

    def test_duplicate_singleton_rejects(self) -> None:
        document = _commit_document()
        row = next(
            item
            for item in document["files"]
            if item["artifactClass"] == "graphic-media-v1"
        )
        row["artifactClass"] = "final-approval-v3"
        with self.assertRaisesRegex(GenerationProfileError, "final-approval-v3.*2"):
            verify_r0_generation_profile(_commit(document))

    def test_critic_and_graphic_r0_count_errors_reject(self) -> None:
        cases = (
            ("critic-receipt-v1", "graphic-media-v1"),
            ("graphic-media-v1", "critic-receipt-v1"),
            ("graphic-media-v1", "graphic-render-receipt-v1"),
            ("graphic-render-receipt-v1", "graphic-media-v1"),
        )
        for source_class, replacement_class in cases:
            document = _commit_document()
            row = next(
                item
                for item in document["files"]
                if item["artifactClass"] == source_class
            )
            row["artifactClass"] = replacement_class
            with self.subTest(source_class=source_class):
                with self.assertRaisesRegex(GenerationProfileError, source_class):
                    verify_r0_generation_profile(_commit(document))

    def test_known_class_plus_unknown_extra_rejects(self) -> None:
        document = _commit_document()
        document["files"].append(_row("future-preview"))
        with self.assertRaisesRegex(GenerationProfileError, "unknown.*future-preview"):
            verify_r0_generation_profile(_commit(document))

    def test_manifest_rows_must_be_path_ordered(self) -> None:
        document = _commit_document()
        document["files"][0], document["files"][1] = (
            document["files"][1],
            document["files"][0],
        )
        with self.assertRaisesRegex(GenerationProfileError, "path ordered"):
            verify_r0_generation_profile(_commit(document))

    def test_only_exact_r0_classes_and_counts_are_admitted(self) -> None:
        self.assertEqual(R0_SINGLETON_ARTIFACT_CLASSES, EXPECTED_SINGLETONS)
        self.assertEqual(R0_GENERATION_ARTIFACT_CLASS_COUNTS["critic-receipt-v1"], 2)
        self.assertEqual(R0_GENERATION_ARTIFACT_CLASS_COUNTS["graphic-media-v1"], 1)
        self.assertEqual(
            R0_GENERATION_ARTIFACT_CLASS_COUNTS["graphic-render-receipt-v1"], 1
        )
        self.assertEqual(R0_MANIFEST_ROWS, 42)
        encoded = json.dumps(tuple(R0_GENERATION_ARTIFACT_CLASS_COUNTS))
        self.assertNotIn("banana", encoded)

    def test_nonempty_depth_and_class_byte_caps_are_closed(self) -> None:
        cases = []
        empty = _commit_document()
        empty["files"][0]["sizeBytes"] = 0
        cases.append((empty, "nonempty"))
        deep = _commit_document()
        deep_row = next(
            row for row in deep["files"] if row["artifactClass"] == "effect-proof-v1"
        )
        deep_row["path"] = "/".join(
            str(index) for index in range(R0_MAX_PATH_DEPTH + 1)
        )
        deep["files"].sort(key=lambda row: row["path"])
        cases.append((deep, "too deep"))
        oversized = _commit_document()
        media = next(
            row for row in oversized["files"] if row["artifactClass"] == "base-media-v1"
        )
        media["sizeBytes"] = R0_ARTIFACT_CLASS_BYTE_CAPS["base-media-v1"] + 1
        cases.append((oversized, "class byte cap"))
        for document, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(
                GenerationProfileError, message
            ):
                verify_r0_generation_profile(_commit(document))

    def test_aggregate_cap_and_512_mib_media_limit(self) -> None:
        document = _commit_document()
        for row in document["files"]:
            row["sizeBytes"] = R0_ARTIFACT_CLASS_BYTE_CAPS[row["artifactClass"]]
        with self.assertRaisesRegex(GenerationProfileError, "aggregate"):
            verify_r0_generation_profile(_commit(document))
        media_cap = 512 * 1024 * 1024
        self.assertEqual(R0_ARTIFACT_CLASS_BYTE_CAPS["base-media-v1"], media_cap)
        self.assertEqual(R0_ARTIFACT_CLASS_BYTE_CAPS["final-media-v1"], media_cap)
        self.assertEqual(R0_ARTIFACT_CLASS_BYTE_CAPS["graphic-media-v1"], media_cap)
        self.assertEqual(R0_MAX_AGGREGATE_BYTES, 2 * 1024 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
