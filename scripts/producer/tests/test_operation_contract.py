"""Disjoint initialize/quality-pass operation contract regressions."""

from __future__ import annotations

import dataclasses
import json
import unittest

from _common import pl  # noqa: F401
from headless.artifact_contract import ArtifactRefV1
from headless.generation_policy_documents import current_execution_policy
from headless.operation_contract import (
    InitializeOperationV1,
    OperationContractError,
    QualityPassOperationV1,
    parse_headless_mp4_operation_v1,
    validate_headless_mp4_operation_v1,
)
from headless.operation_policy import (
    OperationPolicyError,
    bind_operation_execution_policy,
    require_executable_operation_policy,
)
from headless.operation_wire import (
    canonical,
    initialization_snapshot_id,
)
from headless.quality_policy import current_deterministic_quality_policy
from headless.repair_intent import approved_plan_digest, current_accent_policy

UNIT = "11111111-1111-4111-8111-111111111111"
PARENT_GENERATION = "22222222-2222-4222-8222-222222222222"
REQUEST_ID = "33333333-3333-4333-8333-333333333333"


def _artifact(path: str, marker: str) -> ArtifactRefV1:
    return ArtifactRefV1(path, marker * 64, 100)


def _artifact_document(value: ArtifactRefV1) -> dict:
    return {
        "path": value.relative_path,
        "sha256": value.sha256,
        "sizeBytes": value.size_bytes,
    }


def _parent() -> dict:
    plan = {"planVersion": 3, "graphicsTrack": []}
    return {
        "authorityId": "authority-mp4-v1",
        "publicationSeq": 7,
        "generationId": PARENT_GENERATION,
        "commitDigest": "4" * 64,
        "planDigest": approved_plan_digest(plan),
    }


def _quality_pass(parent: dict | None = None) -> dict:
    parent = parent or _parent()
    return {
        "schemaVersion": 1,
        "operation": "quality-pass",
        "realizationKind": "deterministic-mp4",
        "fallbackPolicy": "none",
        "repairPolicyId": current_accent_policy().policy_id,
        "qualityPolicyId": current_deterministic_quality_policy().policy_id,
        "repairIntent": {
            "schemaVersion": 1,
            "effectClass": "SECTION_MARKER_ACCENT_V1",
            "realizationKind": "deterministic-mp4",
            "expectedParent": parent,
            "requestId": REQUEST_ID,
            "target": {"lane": "graphicsTrack", "id": "g-00000001"},
            "op": "replace",
            "relativePointer": "/spec/accent",
            "expectedOld": "#054BC9",
            "value": "#FFD400",
        },
    }


def _snapshot(archive: ArtifactRefV1 | None = None) -> dict:
    archive = archive or _artifact("snapshot/input.tar", "a")
    manifest = _artifact("snapshot/manifest.json", "b")
    seal = _artifact("snapshot/seal.json", "c")
    return {
        "authorityKind": "presealed-immutable-snapshot-v1",
        "snapshotId": initialization_snapshot_id(archive, manifest, seal),
        "archive": _artifact_document(archive),
        "manifest": _artifact_document(manifest),
        "sealReceipt": _artifact_document(seal),
    }


def _initialize() -> dict:
    return {
        "schemaVersion": 1,
        "operation": "initialize",
        "realizationKind": "deterministic-mp4",
        "unitId": UNIT,
        "expectedParent": None,
        "executionPolicyId": current_execution_policy().policy_id,
        "initialBaseBuild": "from-presealed-snapshot",
        "writerRebuildAllowed": False,
        "fallbackPolicy": "none",
        "initializationSnapshot": _snapshot(),
    }


def _quality_operation(parent: dict | None = None) -> dict:
    parent = parent or _parent()
    return {
        "schemaVersion": 1,
        "operation": "quality-pass",
        "realizationKind": "deterministic-mp4",
        "unitId": UNIT,
        "expectedParent": parent,
        "executionPolicyId": current_execution_policy().policy_id,
        "baseRebuildAllowed": False,
        "writerRebuildAllowed": False,
        "fallbackPolicy": "none",
        "qualityPass": _quality_pass(parent),
    }


def _changed(document: dict, path: tuple[str, ...], value: object) -> bytes:
    clone = json.loads(canonical(document))
    target = clone
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return canonical(clone)


class OperationContractTests(unittest.TestCase):
    def test_initialize_and_quality_pass_are_disjoint_exact_types(self) -> None:
        initialize = parse_headless_mp4_operation_v1(canonical(_initialize()))
        quality = parse_headless_mp4_operation_v1(canonical(_quality_operation()))
        self.assertIs(type(initialize), InitializeOperationV1)
        self.assertIsNone(initialize.expected_parent)
        self.assertIs(type(quality), QualityPassOperationV1)
        self.assertEqual(
            quality.expected_parent, quality.quality_pass.repair.expected_parent
        )
        self.assertNotEqual(initialize.operation_digest, quality.operation_digest)
        validate_headless_mp4_operation_v1(initialize)
        validate_headless_mp4_operation_v1(quality)

    def test_only_canonical_bytes_with_unique_closed_keys_are_accepted(self) -> None:
        raw = canonical(_initialize())
        duplicate = b'{"schemaVersion":1,' + raw[1:]
        extra = _initialize()
        extra["qualityPass"] = _quality_pass()
        missing = _initialize()
        missing.pop("expectedParent")
        for value in (
            json.loads(raw),
            raw + b"\n",
            duplicate,
            canonical(extra),
            canonical(missing),
        ):
            with self.subTest(value=value), self.assertRaises(OperationContractError):
                parse_headless_mp4_operation_v1(value)

    def test_initialize_requires_null_parent_and_exact_snapshot_authority(self) -> None:
        alias = _initialize()
        alias["initializationSnapshot"] = _snapshot(
            _artifact("SNAPSHOT/manifest.json", "a")
        )
        cases = (
            _changed(_initialize(), ("expectedParent",), _parent()),
            _changed(_initialize(), ("schemaVersion",), True),
            _changed(_initialize(), ("writerRebuildAllowed",), 0),
            _changed(_initialize(), ("initialBaseBuild",), "rebuild-parent"),
            _changed(_initialize(), ("initializationSnapshot", "snapshotId"), "0" * 64),
            _changed(
                _initialize(), ("initializationSnapshot", "authorityKind"), "live-root"
            ),
            canonical(alias),
        )
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(OperationContractError):
                parse_headless_mp4_operation_v1(raw)

    def test_snapshot_paths_and_bytes_cannot_alias(self) -> None:
        for field in ("path", "sha256"):
            document = _initialize()
            snapshot = document["initializationSnapshot"]
            snapshot["manifest"][field] = snapshot["archive"][field]
            archive = ArtifactRefV1(
                **{
                    "relative_path": snapshot["archive"]["path"],
                    "sha256": snapshot["archive"]["sha256"],
                    "size_bytes": snapshot["archive"]["sizeBytes"],
                }
            )
            manifest = ArtifactRefV1(
                snapshot["manifest"]["path"],
                snapshot["manifest"]["sha256"],
                snapshot["manifest"]["sizeBytes"],
            )
            seal = ArtifactRefV1(
                snapshot["sealReceipt"]["path"],
                snapshot["sealReceipt"]["sha256"],
                snapshot["sealReceipt"]["sizeBytes"],
            )
            snapshot["snapshotId"] = initialization_snapshot_id(archive, manifest, seal)
            with self.subTest(field=field), self.assertRaises(OperationContractError):
                parse_headless_mp4_operation_v1(canonical(document))

    def test_quality_pass_requires_parent_no_rebuild_and_no_fallback(self) -> None:
        cases = (
            _changed(_quality_operation(), ("expectedParent",), None),
            _changed(_quality_operation(), ("baseRebuildAllowed",), True),
            _changed(_quality_operation(), ("baseRebuildAllowed",), 0),
            _changed(_quality_operation(), ("writerRebuildAllowed",), True),
            _changed(_quality_operation(), ("fallbackPolicy",), "legacy"),
            _changed(
                _quality_operation(), ("qualityPass", "fallbackPolicy"), "alternate"
            ),
        )
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(OperationContractError):
                parse_headless_mp4_operation_v1(raw)

    def test_outer_and_nested_quality_parent_must_be_identical(self) -> None:
        document = _quality_operation()
        document["expectedParent"] = dict(document["expectedParent"])
        document["expectedParent"]["commitDigest"] = "9" * 64
        with self.assertRaisesRegex(OperationContractError, "parent"):
            parse_headless_mp4_operation_v1(canonical(document))

    def test_direct_construction_cannot_forge_operation_fields(self) -> None:
        value = parse_headless_mp4_operation_v1(canonical(_quality_operation()))
        forged = dataclasses.replace(value, base_rebuild_allowed=True)
        with self.assertRaisesRegex(OperationContractError, "identity"):
            validate_headless_mp4_operation_v1(forged)


class OperationPolicyTests(unittest.TestCase):
    def test_quality_pass_is_executable_under_current_policy(self) -> None:
        operation = parse_headless_mp4_operation_v1(canonical(_quality_operation()))
        binding = require_executable_operation_policy(
            operation, current_execution_policy()
        )
        self.assertTrue(binding.executable)
        self.assertEqual(binding.operation, "quality-pass")
        self.assertEqual(binding.gaps, ())

    def test_initialize_is_typed_blocked_by_policy_v1_gaps(self) -> None:
        operation = parse_headless_mp4_operation_v1(canonical(_initialize()))
        binding = bind_operation_execution_policy(operation, current_execution_policy())
        self.assertFalse(binding.executable)
        self.assertEqual(
            tuple(gap.code for gap in binding.gaps),
            (
                "OPERATION_DISCRIMINANT",
                "INITIAL_BASE_BUILD_DISPOSITION",
                "INITIALIZATION_SNAPSHOT_AUTHORITY",
            ),
        )
        with self.assertRaises(OperationPolicyError):
            require_executable_operation_policy(operation, current_execution_policy())

    def test_stale_policy_id_or_direct_policy_forgery_rejects(self) -> None:
        document = _quality_operation()
        document["executionPolicyId"] = "0" * 64
        operation = parse_headless_mp4_operation_v1(canonical(document))
        with self.assertRaisesRegex(OperationPolicyError, "stale"):
            bind_operation_execution_policy(operation, current_execution_policy())
        policy = dataclasses.replace(current_execution_policy(), policy_id="0" * 64)
        valid = parse_headless_mp4_operation_v1(canonical(_quality_operation()))
        with self.assertRaisesRegex(OperationPolicyError, "identity"):
            bind_operation_execution_policy(valid, policy)


if __name__ == "__main__":
    unittest.main(verbosity=2)
