"""Exact runtime-capability wire regressions."""

from __future__ import annotations

import dataclasses
import json
import unittest
from collections.abc import Callable

from _common import pl  # noqa: F401
from _assembly_receipt_fixture import canonical
from _runtime_capability_fixture import runtime_capability_fixture
from headless.runtime_capability_manifest import (
    RuntimeCapabilitySchemaError,
    parse_runtime_capability_manifest_v1,
    validate_runtime_capability_manifest_v1,
)


class _AlwaysEqual:
    def __eq__(self, value: object) -> bool:
        return True


def _changed(raw: bytes, callback: Callable[[dict], None]) -> bytes:
    document = json.loads(raw)
    callback(document)
    return canonical(document)


class RuntimeCapabilityManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = runtime_capability_fixture().binding.runtime_manifest
        self.raw = self.manifest.document_json

    def assertInvalid(self, raw: object) -> None:  # noqa: N802
        with self.assertRaises(RuntimeCapabilitySchemaError):
            parse_runtime_capability_manifest_v1(raw)

    def test_exact_manifest_parses_and_directly_revalidates(self) -> None:
        self.assertEqual(parse_runtime_capability_manifest_v1(self.raw), self.manifest)
        validate_runtime_capability_manifest_v1(self.manifest)

    def test_only_unique_exact_canonical_bytes_are_accepted(self) -> None:
        duplicate = b'{"schemaVersion":1,' + self.raw[1:]
        nonfinite = self.raw.replace(b'"sizeBytes":100', b'"sizeBytes":NaN', 1)
        for raw in (json.loads(self.raw), self.raw + b"\n", duplicate, nonfinite):
            with self.subTest(raw=raw):
                self.assertInvalid(raw)

    def test_envelope_is_closed_and_bool_is_not_schema_integer(self) -> None:
        cases = (
            _changed(self.raw, lambda row: row.pop("status")),
            _changed(self.raw, lambda row: row.update(legacy=True)),
            _changed(self.raw, lambda row: row.update(schemaVersion=True)),
            _changed(self.raw, lambda row: row.update(status="runtime-verified")),
            _changed(self.raw, lambda row: row.update(realizationKind="gui")),
        )
        for raw in cases:
            with self.subTest(raw=raw):
                self.assertInvalid(raw)

    def test_tool_roles_are_exact_ordered_and_closed(self) -> None:
        cases = (
            _changed(self.raw, lambda row: row["tools"]["ffmpeg"].pop("roles")),
            _changed(self.raw, lambda row: row["tools"]["ffmpeg"].update(extra=True)),
            _changed(
                self.raw,
                lambda row: row["tools"]["ffmpeg"]["roles"].reverse(),
            ),
            _changed(
                self.raw,
                lambda row: row["tools"]["ffprobe"]["roles"].append("legacy"),
            ),
            _changed(
                self.raw,
                lambda row: row["tools"]["ffprobe"]["roles"].__setitem__(0, True),
            ),
        )
        for raw in cases:
            with self.subTest(raw=raw):
                self.assertInvalid(raw)

    def test_closure_cannot_claim_unproved_runtime_authority(self) -> None:
        keys = (
            "staticManifest",
            "executableReobservation",
            "dynamicLibraryClosure",
            "executionAttestation",
        )
        for key in keys:
            raw = _changed(
                self.raw,
                lambda row, target=key: row["closure"].update({target: "proved"}),
            )
            with self.subTest(key=key):
                self.assertInvalid(raw)

    def test_tool_build_and_digest_roles_cannot_alias(self) -> None:
        def tool_alias(row: dict) -> None:
            row["tools"]["ffprobe"]["sha256"] = row["tools"]["ffmpeg"]["sha256"]

        def build_path_alias(row: dict) -> None:
            row["builds"]["render"]["artifact"]["path"] = row["builds"]["compositor"][
                "artifact"
            ]["path"]

        def build_byte_alias(row: dict) -> None:
            row["builds"]["render"]["artifact"]["sha256"] = row["builds"]["compositor"][
                "artifact"
            ]["sha256"]

        def digest_alias(row: dict) -> None:
            row["builds"]["render"]["buildDigest"] = row["builds"]["compositor"][
                "buildDigest"
            ]

        def cross_role_alias(row: dict) -> None:
            row["builds"]["render"]["buildDigest"] = row["tools"]["ffprobe"]["sha256"]

        callbacks = (
            tool_alias,
            build_path_alias,
            build_byte_alias,
            digest_alias,
            cross_role_alias,
        )
        for callback in callbacks:
            with self.subTest(callback=callback):
                self.assertInvalid(_changed(self.raw, callback))

    def test_build_artifact_scalars_are_exact(self) -> None:
        cases = (
            _changed(
                self.raw,
                lambda row: row["builds"]["render"]["artifact"].update(sizeBytes=True),
            ),
            _changed(
                self.raw,
                lambda row: row["builds"]["render"]["artifact"].update(sizeBytes=0),
            ),
            _changed(
                self.raw,
                lambda row: row["builds"]["render"].update(buildDigest="A" * 64),
            ),
        )
        for raw in cases:
            with self.subTest(raw=raw):
                self.assertInvalid(raw)

    def test_direct_construction_and_hostile_equality_cannot_forge(self) -> None:
        forged = dataclasses.replace(self.manifest, request_digest=_AlwaysEqual())
        with self.assertRaises(RuntimeCapabilitySchemaError):
            validate_runtime_capability_manifest_v1(forged)
        tool = dataclasses.replace(self.manifest.ffmpeg, sha256=_AlwaysEqual())
        forged = dataclasses.replace(self.manifest, ffmpeg=tool)
        with self.assertRaises(RuntimeCapabilitySchemaError):
            validate_runtime_capability_manifest_v1(forged)


if __name__ == "__main__":
    unittest.main(verbosity=2)
