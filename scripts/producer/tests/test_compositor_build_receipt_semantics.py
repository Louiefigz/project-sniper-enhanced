"""Frozen compositor build manifest and receipt semantic tests."""

from __future__ import annotations

import dataclasses
import json
import unittest
from unittest import mock

from _common import pl  # noqa: F401
from _build_receipt_semantics_fixture import (
    compositor_manifest_document,
    compositor_receipt_bytes,
    recanonical_receipt,
)
from headless import prebound_compositor_build as live_build
from headless.compositor_build_manifest_v1_contract import (
    COMPOSITOR_BUILD_V1_IMPLEMENTATION_PATHS,
)
from headless.compositor_build_manifest_semantics import (
    CompositorBuildManifestSchemaError,
    parse_compositor_build_manifest_v1,
)
from headless.compositor_build_receipt_semantics import (
    CompositorBuildReceiptSchemaError,
    parse_compositor_build_receipt_v1,
    validate_compositor_build_receipt_v1,
)
from headless.prebound_compositor_build import compositor_build_manifest_digest


class _AlwaysEqual:
    def __eq__(self, value: object) -> bool:
        return True


def _receipt() -> bytes:
    return compositor_receipt_bytes(compositor_manifest_document())


def _rehash(document: dict) -> bytes:
    document["buildDigest"] = compositor_build_manifest_digest(
        document["manifest"]
    )
    return recanonical_receipt(document)


class CompositorBuildReceiptSemanticTests(unittest.TestCase):
    def test_exact_receipt_recomputes_frozen_source_digest(self) -> None:
        value = parse_compositor_build_receipt_v1(_receipt())
        self.assertEqual(value.build_digest, value.manifest.build_digest)
        self.assertEqual(
            tuple(row.path for row in value.manifest.implementation),
            COMPOSITOR_BUILD_V1_IMPLEMENTATION_PATHS,
        )
        validate_compositor_build_receipt_v1(value)

    def test_historical_parser_does_not_follow_live_catalog_changes(
        self,
    ) -> None:
        raw = _receipt()
        with mock.patch.object(
            live_build, "_IMPLEMENTATION_FILES", ("future.py",)
        ), mock.patch.object(
            live_build,
            "compositor_build_manifest_digest",
            side_effect=AssertionError("live digest called"),
        ):
            parsed = parse_compositor_build_receipt_v1(raw)
        self.assertEqual(parsed.document_json, raw)

    def test_source_reorder_duplicate_and_path_substitution_reject(
        self,
    ) -> None:
        for case in ("reorder", "duplicate", "substitute"):
            document = json.loads(_receipt())
            rows = document["manifest"]["implementation"]
            if case == "reorder":
                rows[0], rows[1] = rows[1], rows[0]
            elif case == "duplicate":
                rows[1]["path"] = rows[0]["path"]
            else:
                rows[0]["path"] = "scripts/producer/headless/../bad.py"
            with self.subTest(case=case), self.assertRaisesRegex(
                CompositorBuildReceiptSchemaError, "manifest is invalid"
            ):
                parse_compositor_build_receipt_v1(_rehash(document))

    def test_noncanonical_duplicate_trailing_and_self_claim_reject(
        self,
    ) -> None:
        raw = _receipt()
        declared = json.loads(raw)["buildDigest"].encode("ascii")
        duplicate = raw.replace(
            b'{"buildDigest":',
            b'{"buildDigest":"' + declared + b'","buildDigest":',
            1,
        )
        document = json.loads(raw)
        document["buildDigest"] = "0" * 64
        cases = (
            raw[:-1],
            raw + b"\n",
            duplicate,
            recanonical_receipt(document),
        )
        for forged in cases:
            with self.subTest(raw=forged[:50]), self.assertRaises(
                CompositorBuildReceiptSchemaError
            ):
                parse_compositor_build_receipt_v1(forged)

    def test_oversized_manifest_rejects_before_json_decode(self) -> None:
        oversized = b" " * (2 * 1024 * 1024 + 1)
        with mock.patch(
            "headless.compositor_build_manifest_semantics.json.loads",
            side_effect=AssertionError("oversized JSON decoded"),
        ), self.assertRaises(CompositorBuildManifestSchemaError):
            parse_compositor_build_manifest_v1(oversized)

    def test_direct_construction_and_hostile_equality_reject(self) -> None:
        value = parse_compositor_build_receipt_v1(_receipt())
        row = dataclasses.replace(
            value.manifest.implementation[0], sha256=_AlwaysEqual()
        )
        manifest = dataclasses.replace(
            value.manifest,
            implementation=(row, *value.manifest.implementation[1:]),
        )
        for forged in (
            dataclasses.replace(value, build_digest=_AlwaysEqual()),
            dataclasses.replace(value, manifest=manifest),
        ):
            with self.subTest(forged=forged), self.assertRaises(
                CompositorBuildReceiptSchemaError
            ):
                validate_compositor_build_receipt_v1(forged)


if __name__ == "__main__":
    unittest.main(verbosity=2)
