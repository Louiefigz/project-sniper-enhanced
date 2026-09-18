"""Exact initialization-origin receipt schema regressions."""

from __future__ import annotations

import dataclasses
import unittest

from _common import pl  # noqa: F401
from _origin_fixture import changed, decoded, origin_fixture
from _approved_parent_loader_values import canonical
from headless.origin_receipt import (
    InitializationOriginReceiptSchemaError,
    parse_initialization_origin_receipt_v1,
    validate_initialization_origin_receipt_v1,
)


def _extra(raw: bytes, path: tuple) -> bytes:
    document = decoded(raw)
    target = document
    for key in path:
        target = target[key]
    target["legacy"] = True
    return canonical(document)


class InitializationOriginReceiptParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.receipt = origin_fixture().receipt
        self.raw = self.receipt.document_json

    def assertInvalid(self, raw: object) -> None:  # noqa: N802
        with self.assertRaises(InitializationOriginReceiptSchemaError):
            parse_initialization_origin_receipt_v1(raw)

    def test_exact_receipt_parses_and_direct_instance_revalidates(self) -> None:
        self.assertEqual(parse_initialization_origin_receipt_v1(self.raw), self.receipt)
        validate_initialization_origin_receipt_v1(self.receipt)
        self.assertIsNone(self.receipt.expected_parent)
        self.assertEqual(self.receipt.operation.kind, "initialize")

    def test_only_unique_exact_canonical_bytes_are_accepted(self) -> None:
        duplicate = b'{"schemaVersion":1,' + self.raw[1:]
        nonfinite = self.raw.replace(b'"durationSeconds":4.0', b'"durationSeconds":NaN')
        cases = (
            decoded(self.raw),
            self.raw + b"\n",
            duplicate,
            nonfinite,
        )
        for raw in cases:
            with self.subTest(raw=raw):
                self.assertInvalid(raw)

    def test_envelope_has_null_parent_and_no_publication_claim(self) -> None:
        document = decoded(self.raw)
        missing = dict(document)
        missing.pop("expectedParent")
        published = dict(document)
        published["publicationSeq"] = 1
        cases = (
            canonical(missing),
            canonical(published),
            changed(self.raw, ("schemaVersion",), True),
            changed(self.raw, ("expectedParent",), False),
            changed(self.raw, ("status",), "published"),
            changed(self.raw, ("realizationKind",), "alternate-renderer"),
        )
        for raw in cases:
            with self.subTest(raw=raw):
                self.assertInvalid(raw)

    def test_every_nested_section_is_closed(self) -> None:
        paths = (
            ("identity",),
            ("policies",),
            ("operation",),
            ("plan",),
            ("base",),
            ("base", "media"),
            ("base", "media", "facts"),
            ("graphics",),
            ("graphics", "assets", 0),
            ("buildRuntime",),
            ("output",),
            ("quality",),
            ("quality", "critics", 0),
        )
        for path in paths:
            with self.subTest(path=path):
                self.assertInvalid(_extra(self.raw, path))

    def test_operation_and_policy_fields_are_initialization_specific(self) -> None:
        document = decoded(self.raw)
        aliased = decoded(self.raw)
        aliased["operation"]["snapshotAuthority"]["path"] = aliased["operation"][
            "artifact"
        ]["path"].upper()
        assembly_alias = decoded(self.raw)
        assembly_alias["output"]["assemblyReceipt"] = assembly_alias["output"][
            "coverProof"
        ]
        cases = (
            changed(self.raw, ("operation", "kind"), "quality-pass"),
            changed(self.raw, ("operation", "digest"), "A" * 64),
            changed(
                self.raw,
                ("policies", "initializationExecutionPolicyId"),
                True,
            ),
            canonical(aliased),
            canonical(assembly_alias),
            canonical(document | {"assemblyReceipt": document["output"]["cover"]}),
        )
        for raw in cases:
            with self.subTest(raw=raw):
                self.assertInvalid(raw)

    def test_media_and_artifact_leaf_types_fail_closed(self) -> None:
        cases = (
            changed(self.raw, ("plan", "artifact", "sizeBytes"), True),
            changed(self.raw, ("base", "media", "facts", "frameCount"), 0),
            changed(self.raw, ("output", "final", "facts", "durationSeconds"), 4),
            changed(self.raw, ("quality", "critics", 0, "lens"), "editorial"),
            changed(
                self.raw,
                ("identity", "generationId"),
                "11111111-1111-4111-8111-11111111111A",
            ),
        )
        for raw in cases:
            with self.subTest(raw=raw):
                self.assertInvalid(raw)

    def test_direct_construction_cannot_override_wire_fields(self) -> None:
        forged = dataclasses.replace(self.receipt, status="published")
        with self.assertRaises(InitializationOriginReceiptSchemaError):
            validate_initialization_origin_receipt_v1(forged)
        operation = dataclasses.replace(self.receipt.operation, kind="quality-pass")
        forged = dataclasses.replace(self.receipt, operation=operation)
        with self.assertRaises(InitializationOriginReceiptSchemaError):
            validate_initialization_origin_receipt_v1(forged)


if __name__ == "__main__":
    unittest.main(verbosity=2)
