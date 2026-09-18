"""Adversarial runtime/build/assembly/quality structural binding tests."""

from __future__ import annotations

import dataclasses
import json
import unittest

from _common import pl  # noqa: F401
from _assembly_receipt_fixture import canonical
from _runtime_capability_fixture import runtime_capability_fixture
from headless.approved_parent_schema import parse_approved_parent_descriptor
from headless.generation_schema import parse_generation_commit
from headless.runtime_capability_binding import (
    RUNTIME_STRUCTURAL_STATUS,
    RuntimeCapabilityBindingError,
    RuntimeCapabilityBindingV1,
    bind_runtime_capability_manifest,
)


class _AlwaysEqual:
    def __eq__(self, value: object) -> bool:
        return True


def _binding(**changes: object) -> RuntimeCapabilityBindingV1:
    original = runtime_capability_fixture().binding
    return dataclasses.replace(original, **changes)


class RuntimeCapabilityBindingTests(unittest.TestCase):
    def test_valid_binding_is_structural_and_explicitly_non_authorizing(self) -> None:
        report = bind_runtime_capability_manifest(_binding())
        self.assertEqual(report.status, RUNTIME_STRUCTURAL_STATUS)
        self.assertTrue(report.structural_manifest_bound)
        self.assertFalse(report.runtime_verified)
        self.assertFalse(report.execution_reobserved)
        self.assertFalse(report.dynamic_library_closure_verified)
        self.assertFalse(report.publication_authorized)
        self.assertEqual(
            tuple(item.code for item in report.unresolved_authority),
            (
                "EXECUTABLE_REOBSERVATION_AND_INODE_STABILITY",
                "DYNAMIC_LIBRARY_AND_AUXILIARY_RUNTIME_CLOSURE",
                "BUILD_RECEIPT_SEMANTICS",
                "PROCESS_EXECUTION_ATTESTATION",
                "MEASUREMENT_REOBSERVATION",
            ),
        )

    def test_runtime_tool_drift_rejects_even_when_manifest_is_self_consistent(
        self,
    ) -> None:
        def mutate(stage: str, row: dict) -> None:
            if stage == "runtime":
                row["tools"]["ffmpeg"]["sha256"] = "6" * 64

        binding = runtime_capability_fixture(mutate).binding
        with self.assertRaisesRegex(RuntimeCapabilityBindingError, "tool identity"):
            bind_runtime_capability_manifest(binding)

    def test_decode_tool_drift_rejects_even_when_evidence_is_rehashed(self) -> None:
        def mutate(stage: str, row: dict) -> None:
            if stage == "full-decode":
                row["tools"]["ffprobeSha256"] = "6" * 64

        binding = runtime_capability_fixture(mutate).binding
        with self.assertRaisesRegex(RuntimeCapabilityBindingError, "tool identity"):
            bind_runtime_capability_manifest(binding)

    def test_compositor_and_render_build_drift_reject(self) -> None:
        def compositor(stage: str, row: dict) -> None:
            if stage == "runtime":
                row["builds"]["compositor"]["buildDigest"] = "6" * 64

        def render(stage: str, row: dict) -> None:
            if stage == "runtime":
                row["builds"]["render"]["buildDigest"] = "6" * 64

        cases = ((compositor, "compositor build"), (render, "render build"))
        for mutator, message in cases:
            binding = runtime_capability_fixture(mutator).binding
            with self.subTest(message=message), self.assertRaisesRegex(
                RuntimeCapabilityBindingError, message
            ):
                bind_runtime_capability_manifest(binding)

    def test_all_quality_runtime_reference_drift_rejects(self) -> None:
        for target in ("full-decode", "effect-proof", "audit-b"):

            def mutate(stage: str, row: dict, selected: str = target) -> None:
                if stage == selected:
                    row["runtimeCapabilityManifest"] = {
                        "path": f"stale/{selected}.json",
                        "sha256": "6" * 64,
                        "sizeBytes": 9,
                    }

            binding = runtime_capability_fixture(mutate).binding
            with self.subTest(target=target), self.assertRaisesRegex(
                RuntimeCapabilityBindingError, "runtime ref"
            ):
                bind_runtime_capability_manifest(binding)

    def test_manifested_build_receipt_reference_drift_rejects(self) -> None:
        for target in ("compositor", "render"):

            def mutate(stage: str, row: dict, selected: str = target) -> None:
                if stage == "runtime":
                    row["builds"][selected]["artifact"]["sha256"] = "6" * 64

            binding = runtime_capability_fixture(mutate).binding
            with self.subTest(target=target), self.assertRaisesRegex(
                RuntimeCapabilityBindingError, "does not match class"
            ):
                bind_runtime_capability_manifest(binding)

    def test_manifested_build_role_class_swap_rejects(self) -> None:
        binding = _binding()
        document = json.loads(binding.commit.document_json)
        compositor = next(
            row
            for row in document["files"]
            if row["artifactClass"] == "compositor-build-receipt-v1"
        )
        render = next(
            row
            for row in document["files"]
            if row["artifactClass"] == "render-build-receipt-v1"
        )
        compositor["artifactClass"], render["artifactClass"] = (
            render["artifactClass"],
            compositor["artifactClass"],
        )
        commit = parse_generation_commit(canonical(document))
        with self.assertRaises(RuntimeCapabilityBindingError):
            bind_runtime_capability_manifest(
                dataclasses.replace(binding, commit=commit)
            )

    def test_role_digest_reused_by_unrelated_manifest_row_rejects(self) -> None:
        binding = _binding()
        document = json.loads(binding.commit.document_json)
        runtime = next(
            row
            for row in document["files"]
            if row["artifactClass"] == "runtime-capability-manifest-v1"
        )
        unrelated = next(
            row
            for row in document["files"]
            if row["artifactClass"] == "generation-verification-v1"
        )
        unrelated["sha256"] = runtime["sha256"]
        commit = parse_generation_commit(canonical(document))
        value = dataclasses.replace(binding, commit=commit)
        with self.assertRaisesRegex(RuntimeCapabilityBindingError, "role bytes alias"):
            bind_runtime_capability_manifest(value)

    def test_stale_effect_quality_policy_rejects(self) -> None:
        def mutate(stage: str, row: dict) -> None:
            if stage == "effect-proof":
                row["qualityPolicyId"] = "6" * 64

        binding = runtime_capability_fixture(mutate).binding
        with self.assertRaisesRegex(RuntimeCapabilityBindingError, "policy is stale"):
            bind_runtime_capability_manifest(binding)

    def test_every_direct_construction_and_hostile_equality_forgery_rejects(
        self,
    ) -> None:
        value = _binding()
        identity = dataclasses.replace(
            value.descriptor.identity, request_digest=_AlwaysEqual()
        )
        descriptor = dataclasses.replace(value.descriptor, identity=identity)
        commit = dataclasses.replace(value.commit, request_digest=_AlwaysEqual())
        runtime = dataclasses.replace(
            value.runtime_manifest, request_digest=_AlwaysEqual()
        )
        assembly = dataclasses.replace(
            value.assembly_receipt, request_digest=_AlwaysEqual()
        )
        full = dataclasses.replace(
            value.quality_evidence.full_decode, quality_policy_id=_AlwaysEqual()
        )
        evidence = dataclasses.replace(value.quality_evidence, full_decode=full)
        cases = (
            _binding(descriptor=descriptor),
            _binding(commit=commit),
            _binding(runtime_manifest=runtime),
            _binding(assembly_receipt=assembly),
            _binding(quality_evidence=evidence),
        )
        for forged in cases:
            with self.subTest(value=forged), self.assertRaises(
                RuntimeCapabilityBindingError
            ):
                bind_runtime_capability_manifest(forged)

    def test_stale_runtime_raw_reference_rejects(self) -> None:
        value = _binding()
        document = json.loads(value.descriptor.document_json)
        document["provenance"]["runtimeCapabilityManifest"]["sizeBytes"] += 1
        descriptor = parse_approved_parent_descriptor(canonical(document))
        with self.assertRaises(RuntimeCapabilityBindingError):
            bind_runtime_capability_manifest(_binding(descriptor=descriptor))


if __name__ == "__main__":
    unittest.main(verbosity=2)
