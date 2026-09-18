from __future__ import annotations

import hashlib
import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path

PRODUCER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PRODUCER_DIR))

from headless.generation_schema import (  # noqa: E402
    GenerationSchemaError,
    generation_commit_digest,
    parse_current_pointer,
    parse_generation_commit,
)

GENERATION = "11111111-1111-4111-8111-111111111111"
ATTEMPT = "22222222-2222-4222-8222-222222222222"
UNIT = "33333333-3333-4333-8333-333333333333"


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True, allow_nan=False
    ).encode("ascii")


def _row(
    path: str = "authority/approved-parent.json",
    artifact_class: str = "approved-parent",
) -> dict:
    return {
        "artifactClass": artifact_class,
        "path": path,
        "sizeBytes": 123,
        "sha256": "a" * 64,
    }


def _current() -> dict:
    return {
        "schemaVersion": 1,
        "authorityId": "authority-mp4-v1",
        "publicationSeq": 7,
        "generationId": GENERATION,
        "commitDigest": "b" * 64,
    }


def _parent() -> dict:
    return {
        "authorityId": "authority-mp4-v1",
        "publicationSeq": 6,
        "generationId": "44444444-4444-4444-8444-444444444444",
        "commitDigest": "c" * 64,
        "planDigest": "d" * 64,
    }


def _commit(parent: dict | None = None) -> dict:
    return {
        "schemaVersion": 1,
        "authorityId": "authority-mp4-v1",
        "generationId": GENERATION,
        "attemptId": ATTEMPT,
        "unitId": UNIT,
        "requestDigest": "1" * 64,
        "expectedParent": parent,
        "executionPolicyId": "2" * 64,
        "repairPolicyId": "3" * 64,
        "qualityPolicyId": "4" * 64,
        "fallbackPolicyId": "5" * 64,
        "approvedParentPath": "authority/approved-parent.json",
        "files": [
            _row(),
            _row("media/final.mp4", "final-media"),
        ],
    }


class CurrentPointerTests(unittest.TestCase):
    def test_exact_object_and_canonical_bytes_parse(self) -> None:
        document = _current()
        parsed = parse_current_pointer(_canonical(document))
        self.assertEqual(parsed.authority_id, "authority-mp4-v1")
        self.assertEqual(parsed.publication_seq, 7)
        self.assertEqual(parsed.generation_id, GENERATION)
        self.assertEqual(parsed.document_json, _canonical(document))
        self.assertEqual(parse_current_pointer(document), parsed)

    def test_noncanonical_and_duplicate_json_reject(self) -> None:
        raw = _canonical(_current())
        with self.assertRaisesRegex(GenerationSchemaError, "canonical"):
            parse_current_pointer(raw + b"\n")
        duplicate = raw.replace(
            b'{"authorityId":', b'{"schemaVersion":1,"authorityId":', 1
        )
        with self.assertRaisesRegex(GenerationSchemaError, "duplicate"):
            parse_current_pointer(duplicate)

    def test_unknown_bad_sequence_uuid_and_digest_reject(self) -> None:
        cases = []
        for key, value in (
            ("publicationSeq", True),
            ("publicationSeq", 0),
            ("generationId", "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"),
            ("commitDigest", "A" * 64),
        ):
            changed = _current()
            changed[key] = value
            cases.append(changed)
        extra = _current()
        extra["legacyPath"] = "final.mp4"
        cases.append(extra)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(GenerationSchemaError):
                parse_current_pointer(value)


class GenerationCommitTests(unittest.TestCase):
    def test_r0_null_parent_and_exact_manifest_parse(self) -> None:
        document = _commit()
        raw = _canonical(document)
        parsed = parse_generation_commit(raw)
        expected = hashlib.sha256(
            b"sniper-mp4-generation-commit-v1\0" + raw
        ).hexdigest()
        self.assertIsNone(parsed.expected_parent)
        self.assertEqual(parsed.approved_parent_path, "authority/approved-parent.json")
        self.assertEqual(
            tuple(row.path for row in parsed.files),
            ("authority/approved-parent.json", "media/final.mp4"),
        )
        self.assertEqual(parsed.commit_digest, expected)
        self.assertEqual(generation_commit_digest(raw), expected)

    def test_exact_parent_object_parses_and_must_match_authority(self) -> None:
        parsed = parse_generation_commit(_commit(_parent()))
        self.assertEqual(parsed.expected_parent.plan_digest, "d" * 64)
        changed = _commit(_parent())
        changed["expectedParent"]["authorityId"] = "other-authority"
        with self.assertRaisesRegex(GenerationSchemaError, "does not match"):
            parse_generation_commit(changed)

    def test_commit_requires_canonical_bytes_without_duplicate_keys(self) -> None:
        raw = _canonical(_commit())
        with self.assertRaisesRegex(GenerationSchemaError, "canonical"):
            parse_generation_commit(b" " + raw)
        duplicate = raw.replace(
            b'{"approvedParentPath":', b'{"schemaVersion":1,"approvedParentPath":', 1
        )
        with self.assertRaisesRegex(GenerationSchemaError, "duplicate"):
            parse_generation_commit(duplicate)

    def test_exact_commit_and_row_keys_reject_extensions(self) -> None:
        top = _commit()
        top["publicationSeq"] = 1
        row = _commit()
        row["files"][0]["mode"] = 0o444
        for value in (top, row):
            with self.subTest(value=value), self.assertRaises(GenerationSchemaError):
                parse_generation_commit(value)

    def test_all_uuid_and_digest_fields_are_strict(self) -> None:
        cases = []
        for key, value in (
            ("generationId", "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"),
            ("attemptId", "bad"),
            ("unitId", "BBBBBBBB-BBBB-4BBB-8BBB-BBBBBBBBBBBB"),
            ("requestDigest", "A" * 64),
            ("executionPolicyId", "2" * 63),
            ("repairPolicyId", None),
            ("qualityPolicyId", "z" * 64),
            ("fallbackPolicyId", "5" * 65),
        ):
            changed = _commit()
            changed[key] = value
            cases.append(changed)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(GenerationSchemaError):
                parse_generation_commit(value)

    def test_unsafe_or_aliased_paths_reject(self) -> None:
        bad_paths = (
            "",
            "/absolute.json",
            "../escape.json",
            "a/../escape.json",
            "a/./file.json",
            "a//file.json",
            "a\\file.json",
            "a/file.json\x00",
            "a/file\n.json",
            "cafe\u0301/file.json",
            "a/\ud800.json",
        )
        for path in bad_paths:
            value = _commit()
            value["approvedParentPath"] = path
            value["files"][0]["path"] = path
            with self.subTest(path=path), self.assertRaises(GenerationSchemaError):
                parse_generation_commit(value)
        alias = _commit()
        alias["files"].append(_row("MEDIA/FINAL.MP4", "other-media"))
        with self.assertRaisesRegex(GenerationSchemaError, "closure"):
            parse_generation_commit(alias)

    def test_unique_rows_and_exact_approved_parent_presence(self) -> None:
        duplicate = _commit()
        duplicate["files"].append(deepcopy(duplicate["files"][0]))
        missing = _commit()
        missing["approvedParentPath"] = "authority/not-listed.json"
        empty = _commit()
        empty["files"] = []
        for value in (duplicate, missing, empty):
            with self.subTest(value=value), self.assertRaises(GenerationSchemaError):
                parse_generation_commit(value)

    def test_mutable_authority_and_commit_files_are_excluded(self) -> None:
        forbidden = (
            ("FENCE", "evidence"),
            ("CURRENT", "evidence"),
            ("state/publish-intent.json", "evidence"),
            ("commit.json", "evidence"),
            ("evidence/ok.json", "publication-receipt"),
        )
        for path, artifact_class in forbidden:
            value = _commit()
            value["files"].append(_row(path, artifact_class))
            with self.subTest(path=path), self.assertRaisesRegex(
                GenerationSchemaError, "closure"
            ):
                parse_generation_commit(value)

    def test_digest_is_bound_to_exact_commit_document(self) -> None:
        first = _canonical(_commit())
        changed = _commit()
        changed["files"][1]["sha256"] = "e" * 64
        second = _canonical(changed)
        self.assertNotEqual(
            generation_commit_digest(first), generation_commit_digest(second)
        )
        with self.assertRaisesRegex(GenerationSchemaError, "must be bytes"):
            generation_commit_digest(_commit())


if __name__ == "__main__":
    unittest.main()
