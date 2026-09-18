"""Exact wire and non-authorizing assembly-card binding regressions."""

from __future__ import annotations

import dataclasses
import unittest
from collections.abc import Callable

from _common import pl  # noqa: F401
from _assembly_receipt_fixture import (
    assembly_fixture,
    canonical,
    changed,
    decoded,
)
from headless.approved_parent_assembly_binding import (
    STRUCTURAL_STATUS,
    ApprovedParentAssemblyBindingError,
    bind_approved_parent_assembly_receipt,
)
from headless.approved_parent_assembly_receipt import (
    AssemblyReceiptSchemaError,
    parse_assembly_receipt_v1,
    validate_assembly_receipt_v1,
)
from headless.generation_schema import parse_generation_commit


def _mutated(raw: bytes, callback: Callable[[dict], None]) -> bytes:
    document = decoded(raw)
    callback(document)
    return canonical(document)


class AssemblyReceiptParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.receipt = assembly_fixture().receipt
        self.raw = self.receipt.document_json

    def assertInvalid(self, raw: object) -> None:  # noqa: N802
        with self.assertRaises(AssemblyReceiptSchemaError):
            parse_assembly_receipt_v1(raw)

    def test_exact_emitter_output_parses_and_directly_revalidates(self) -> None:
        validate_assembly_receipt_v1(self.receipt)
        self.assertEqual(parse_assembly_receipt_v1(self.raw), self.receipt)

    def test_only_exact_canonical_bytes_with_unique_keys_are_accepted(self) -> None:
        duplicate = b'{"schemaVersion":1,' + self.raw[1:]
        nonfinite = self.raw.replace(b'"duplicateRatio":0.01', b'"duplicateRatio":NaN')
        nested_duplicate = self.raw.replace(
            b'"passed":true', b'"passed":true,"passed":true'
        )
        for raw in (
            decoded(self.raw),
            self.raw + b"\n",
            duplicate,
            nonfinite,
            nested_duplicate,
        ):
            with self.subTest(raw=raw):
                self.assertInvalid(raw)

    def test_envelope_is_closed_and_private(self) -> None:
        document = decoded(self.raw)
        missing = dict(document)
        missing.pop("status")
        extra = dict(document)
        extra["publicationSeq"] = 9
        cases = (
            canonical(missing),
            canonical(extra),
            changed(self.raw, ("schemaVersion",), True),
            changed(self.raw, ("status",), "published"),
        )
        for raw in cases:
            with self.subTest(raw=raw):
                self.assertInvalid(raw)

    def test_every_nested_object_rejects_unknown_or_missing_keys(self) -> None:
        paths = (
            ("parent",),
            ("plan",),
            ("base",),
            ("graphics",),
            ("graphics", "assets", 0),
            ("base", "media"),
            ("base", "media", "facts"),
            ("compositor",),
            ("compositor", "alphaOccupancy", 0),
            ("compositor", "encode"),
            ("compositor", "smoothness"),
            ("compositor", "fullDecode"),
            ("compositor", "audio"),
            ("output",),
        )
        for path in paths:

            def add_extra(document: dict, target_path: tuple = path) -> None:
                target = document
                for key in target_path:
                    target = target[key]
                target["legacy"] = True

            with self.subTest(path=path):
                self.assertInvalid(_mutated(self.raw, add_extra))

    def test_media_timing_and_aliases_are_exactly_typed(self) -> None:
        alias = decoded(self.raw)
        alias["output"]["cover"]["path"] = alias["output"]["final"]["artifact"]["path"]
        cases = (
            changed(self.raw, ("base", "media", "facts", "durationSeconds"), 4),
            changed(self.raw, ("base", "media", "facts", "fps"), [30, True]),
            changed(self.raw, ("output", "final", "facts", "frameCount"), 0),
            canonical(alias),
        )
        for raw in cases:
            with self.subTest(raw=raw):
                self.assertInvalid(raw)

    def test_compositor_constants_and_observation_types_fail_closed(self) -> None:
        cases = (
            changed(self.raw, ("compositor", "fullDecode", "passed"), 1),
            changed(self.raw, ("compositor", "encode", "eofAction"), "repeat"),
            changed(self.raw, ("compositor", "audio", "method"), "decoded"),
            changed(self.raw, ("compositor", "audio", "finalSha256"), "8" * 64),
            changed(self.raw, ("compositor", "smoothness", "duplicateRatio"), 0),
            changed(self.raw, ("compositor", "smoothness", "duplicateRatio"), 0.08),
            changed(
                self.raw, ("compositor", "alphaOccupancy", 0, "peakMeanAlpha8"), 255
            ),
            changed(
                self.raw, ("compositor", "alphaOccupancy", 0, "meaningfulFrames"), 1
            ),
        )
        for raw in cases:
            with self.subTest(raw=raw):
                self.assertInvalid(raw)

    def test_parent_artifact_and_graphic_digests_are_strict(self) -> None:
        cases = (
            changed(self.raw, ("parent", "publicationSeq"), True),
            changed(
                self.raw,
                ("parent", "generationId"),
                "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",
            ),
            changed(self.raw, ("graphics", "assets", 0, "renderBuildDigest"), "A" * 64),
            changed(self.raw, ("plan", "artifact", "sizeBytes"), 0),
        )
        for raw in cases:
            with self.subTest(raw=raw):
                self.assertInvalid(raw)

    def test_direct_construction_cannot_override_canonical_fields(self) -> None:
        forged = dataclasses.replace(self.receipt, request_digest="0" * 64)
        with self.assertRaises(AssemblyReceiptSchemaError):
            validate_assembly_receipt_v1(forged)
        proof = dataclasses.replace(self.receipt.compositor, passes=2)
        forged = dataclasses.replace(self.receipt, compositor=proof)
        with self.assertRaises(AssemblyReceiptSchemaError):
            validate_assembly_receipt_v1(forged)


class AssemblyCurrentCardBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = assembly_fixture()

    def _bind(self, receipt: object | None = None, commit: object | None = None):
        return bind_approved_parent_assembly_receipt(
            self.fixture.descriptor,
            commit or self.fixture.commit,
            receipt or self.fixture.receipt,
        )

    def test_valid_binding_is_explicitly_non_authorizing(self) -> None:
        report = self._bind()
        self.assertEqual(report.status, STRUCTURAL_STATUS)
        self.assertFalse(report.runtime_verified)
        self.assertFalse(report.publication_authorized)
        codes = tuple(item.code for item in report.unresolved_authority)
        self.assertEqual(
            codes,
            (
                "IMMEDIATE_PARENT_AND_BASE_CONTINUITY",
                "RECURSIVE_LINEAGE_AND_GENESIS_ORIGIN",
                "PLAN_CLIP_AND_FILTER_BYTES",
                "COMPOSITOR_BUILD_RUNTIME_AND_TOOLS",
                "MEDIA_AUDIO_ALPHA_DECODE_AND_COVER",
                "RETAINED_YDIF_REOBSERVATION",
                "GRAPHIC_RENDER_BUILD_SEMANTICS",
            ),
        )

    def test_identity_parent_and_genesis_drift_reject(self) -> None:
        cases = (
            changed(self.fixture.receipt.document_json, ("requestDigest",), "0" * 64),
            changed(self.fixture.receipt.document_json, ("qualityPolicyId",), "0" * 64),
            changed(
                self.fixture.receipt.document_json, ("parent", "commitDigest"), "0" * 64
            ),
        )
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(
                ApprovedParentAssemblyBindingError
            ):
                self._bind(parse_assembly_receipt_v1(raw))
        document = decoded(self.fixture.commit.document_json)
        document["expectedParent"] = None
        with self.assertRaisesRegex(ApprovedParentAssemblyBindingError, "genesis"):
            self._bind(commit=parse_generation_commit(canonical(document)))

    def test_plan_base_graphics_timing_and_output_drift_reject(self) -> None:
        mutations = (
            (("plan", "planDigest"), "0" * 64),
            (("base", "baseReceiptSha256"), "0" * 64),
            (("graphics", "assetSetDigest"), "0" * 64),
            (("compositor", "framesOut"), 119),
            (("compositor", "smoothness", "failThreshold"), 0.09),
            (("output", "cover", "sha256"), "0" * 64),
        )
        for path, value in mutations:
            receipt = parse_assembly_receipt_v1(
                changed(self.fixture.receipt.document_json, path, value)
            )
            with self.subTest(path=path), self.assertRaises(
                ApprovedParentAssemblyBindingError
            ):
                self._bind(receipt)

    def test_manifest_class_swap_and_raw_byte_drift_reject(self) -> None:
        document = decoded(self.fixture.commit.document_json)
        assembly = next(
            row
            for row in document["files"]
            if row["artifactClass"] == "assembly-receipt-v1"
        )
        cover = next(
            row for row in document["files"] if row["artifactClass"] == "cover-image-v1"
        )
        assembly["artifactClass"], cover["artifactClass"] = (
            cover["artifactClass"],
            assembly["artifactClass"],
        )
        commit = parse_generation_commit(canonical(document))
        with self.assertRaises(ApprovedParentAssemblyBindingError):
            self._bind(commit=commit)
        raw = changed(
            self.fixture.receipt.document_json,
            ("parentAssemblyReceiptSha256",),
            "8" * 64,
        )
        with self.assertRaisesRegex(ApprovedParentAssemblyBindingError, "bytes"):
            self._bind(parse_assembly_receipt_v1(raw))

    def test_directly_forged_descriptor_and_commit_instances_reject(self) -> None:
        identity = dataclasses.replace(
            self.fixture.descriptor.identity, request_digest="0" * 64
        )
        descriptor = dataclasses.replace(self.fixture.descriptor, identity=identity)
        with self.assertRaisesRegex(ApprovedParentAssemblyBindingError, "construction"):
            bind_approved_parent_assembly_receipt(
                descriptor, self.fixture.commit, self.fixture.receipt
            )
        commit = dataclasses.replace(self.fixture.commit, request_digest="0" * 64)
        with self.assertRaisesRegex(ApprovedParentAssemblyBindingError, "construction"):
            self._bind(commit=commit)


if __name__ == "__main__":
    unittest.main(verbosity=2)
