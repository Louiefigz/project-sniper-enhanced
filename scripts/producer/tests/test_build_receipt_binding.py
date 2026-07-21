"""Adversarial build-receipt/runtime/generation cross-binding tests."""

from __future__ import annotations

import dataclasses
import json
import unittest

from _common import pl  # noqa: F401
from _assembly_receipt_fixture import canonical
from _build_receipt_semantics_fixture import (
    build_receipt_fixture,
    recanonical_receipt,
)
from headless.build_receipt_binding import (
    BUILD_RECEIPT_BLOCKED_STATUS,
    BuildReceiptBindingError,
    bind_build_receipt_semantics,
    require_build_receipt_execution_authorized,
)
from headless.compositor_build_receipt_semantics import (
    parse_compositor_build_receipt_v1,
)
from headless.prebound_compositor_build import compositor_build_manifest_digest
from headless.render_build import render_build_manifest_digest
from headless.render_build_receipt_semantics import (
    parse_render_build_receipt_v1,
)
from headless.runtime_capability_manifest import (
    parse_runtime_capability_manifest_v1,
)


class _AlwaysEqual:
    def __eq__(self, value: object) -> bool:
        return True


class BuildReceiptBindingTests(unittest.TestCase):
    def test_supported_claims_bind_but_never_authorize(self) -> None:
        report = bind_build_receipt_semantics(build_receipt_fixture())
        self.assertEqual(report.status, BUILD_RECEIPT_BLOCKED_STATUS)
        self.assertTrue(report.runtime_claims_bound)
        self.assertTrue(report.render_receipt_semantics_bound)
        self.assertTrue(report.compositor_receipt_semantics_bound)
        self.assertTrue(report.graphic_receipt_semantics_bound)
        self.assertEqual(
            tuple(row.graphic_id for row in report.graphic_receipts),
            ("g-00000001",),
        )
        self.assertFalse(report.source_bytes_reobserved)
        self.assertFalse(report.runtime_verified)
        self.assertFalse(report.execution_authorized)
        self.assertFalse(report.publication_authorized)
        self.assertEqual(
            tuple(item.code for item in report.unresolved_authority),
            (
                "BUILD_SOURCE_AND_TOOL_BYTES_NOT_REOBSERVED",
                "BUILD_EXECUTION_ATTESTATION_UNAVAILABLE",
            ),
        )
        forged = dataclasses.replace(
            report, execution_authorized=True, publication_authorized=True
        )
        with self.assertRaisesRegex(
            BuildReceiptBindingError, BUILD_RECEIPT_BLOCKED_STATUS
        ):
            require_build_receipt_execution_authorized(forged)

    def test_compositor_raw_mutation_without_ref_update_rejects(self) -> None:
        value = build_receipt_fixture()
        document = json.loads(value.compositor_receipt.document_json)
        document["manifest"]["implementation"][0]["sha256"] = "9" * 64
        document["buildDigest"] = compositor_build_manifest_digest(document["manifest"])
        changed = parse_compositor_build_receipt_v1(recanonical_receipt(document))
        forged = dataclasses.replace(value, compositor_receipt=changed)
        with self.assertRaisesRegex(BuildReceiptBindingError, "bytes are stale"):
            bind_build_receipt_semantics(forged)

    def test_render_raw_mutation_without_ref_update_rejects(self) -> None:
        value = build_receipt_fixture()
        document = json.loads(value.render_receipt.document_json)
        document["manifest"]["implementation"][0]["sha256"] = "9" * 64
        document["buildDigest"] = render_build_manifest_digest(document["manifest"])
        receipt = parse_render_build_receipt_v1(recanonical_receipt(document))
        with self.assertRaisesRegex(BuildReceiptBindingError, "bytes are stale"):
            bind_build_receipt_semantics(
                dataclasses.replace(value, render_receipt=receipt)
            )

    def test_manifest_class_ref_swap_rejects(self) -> None:
        value = build_receipt_fixture()
        runtime = json.loads(value.runtime_binding.runtime_manifest.document_json)
        builds = runtime["builds"]
        builds["compositor"]["artifact"], builds["render"]["artifact"] = (
            builds["render"]["artifact"],
            builds["compositor"]["artifact"],
        )
        parsed = parse_runtime_capability_manifest_v1(canonical(runtime))
        nested = dataclasses.replace(value.runtime_binding, runtime_manifest=parsed)
        with self.assertRaisesRegex(
            BuildReceiptBindingError, "runtime build authority"
        ):
            bind_build_receipt_semantics(
                dataclasses.replace(value, runtime_binding=nested)
            )

    def test_self_consistent_render_source_claim_remains_blocked(self) -> None:
        def mutate(manifest: dict) -> None:
            manifest["implementation"][0]["sha256"] = "9" * 64

        report = bind_build_receipt_semantics(build_receipt_fixture(mutate))
        self.assertTrue(report.render_receipt_semantics_bound)
        self.assertFalse(report.source_bytes_reobserved)
        self.assertFalse(report.execution_authorized)

    def test_self_consistent_compositor_source_claim_remains_blocked(
        self,
    ) -> None:
        def mutate(manifest: dict) -> None:
            manifest["implementation"][0]["sha256"] = "9" * 64

        report = bind_build_receipt_semantics(
            build_receipt_fixture(compositor_mutator=mutate)
        )
        self.assertTrue(report.compositor_receipt_semantics_bound)
        self.assertFalse(report.source_bytes_reobserved)
        self.assertFalse(report.execution_authorized)

    def test_compositor_semantics_are_bound_but_still_non_authorizing(
        self,
    ) -> None:
        value = build_receipt_fixture()
        report = bind_build_receipt_semantics(value)
        self.assertEqual(
            report.compositor_receipt.semantic_status,
            "EXACT_STATIC_SOURCE_MANIFEST_BOUND",
        )
        self.assertGreater(report.compositor_receipt.source_count, 0)
        self.assertTrue(report.compositor_receipt_semantics_bound)
        self.assertFalse(report.publication_authorized)

    def test_render_proof_tool_self_claim_rejects_cross_binding(self) -> None:
        def mutate(manifest: dict) -> None:
            manifest["tools"][1]["sha256"] = "6" * 64

        with self.assertRaisesRegex(BuildReceiptBindingError, "tool identities"):
            bind_build_receipt_semantics(build_receipt_fixture(mutate))

    def test_direct_construction_and_hostile_equality_reject(self) -> None:
        value = build_receipt_fixture()
        render = dataclasses.replace(value.render_receipt, build_digest=_AlwaysEqual())
        runtime = dataclasses.replace(
            value.runtime_binding.runtime_manifest,
            request_digest=_AlwaysEqual(),
        )
        cases = (
            dataclasses.replace(value, render_receipt=render),
            dataclasses.replace(
                value,
                runtime_binding=dataclasses.replace(
                    value.runtime_binding, runtime_manifest=runtime
                ),
            ),
        )
        for forged in cases:
            with self.subTest(value=forged), self.assertRaises(
                BuildReceiptBindingError
            ):
                bind_build_receipt_semantics(forged)


if __name__ == "__main__":
    unittest.main(verbosity=2)
