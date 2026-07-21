"""Adversarial disk tests for tagged versioned current-authority loading."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import unittest
from contextlib import nullcontext
from unittest.mock import patch

from _approved_parent_loader_values import canonical
from _common import pl  # noqa: F401
from _genesis_r1_fixture import genesis_r1_fixture
from _versioned_disk_authorities import (
    frozen_r0_quality_pass_disk_authority,
    quality_pass_v2_disk_authority,
)
from _versioned_disk_fixture import VersionedDiskFixture
from headless.generation_schema import parse_generation_commit
import headless.versioned_current_loader as loader_module
from headless.versioned_current_loader import (
    VersionedCurrentAuthorityLoadError,
    load_versioned_current_authority,
    require_versioned_current_execution_authorized,
)
from headless.versioned_current_loader_types import (
    FrozenR0CurrentSelectionV1,
    GenesisR1CurrentDocumentsV2,
    QualityPassV2CurrentDocumentsV2,
)
from headless.versioned_generation_reader import VersionedResolvedGenerationV2


def _replace_committed_artifact(
    commit: object, files: dict[str, bytes], path: str, raw: bytes
) -> tuple[object, dict[str, bytes]]:
    document = json.loads(commit.document_json)
    row = next(item for item in document["files"] if item["path"] == path)
    row["sizeBytes"] = len(raw)
    row["sha256"] = hashlib.sha256(raw).hexdigest()
    changed = dict(files)
    changed[path] = raw
    return parse_generation_commit(canonical(document)), changed


class VersionedCurrentLoaderDiskTests(unittest.TestCase):
    def _load(self, fixture: VersionedDiskFixture):
        return load_versioned_current_authority(
            str(fixture.authority), str(fixture.materialization)
        )

    def test_r1_genesis_documents_are_reobserved_but_not_authorized(self) -> None:
        value = genesis_r1_fixture()
        fixture = VersionedDiskFixture(value.inputs.commit, value.files, 1)
        try:
            with self._load(fixture) as result:
                self.assertIs(type(result), GenesisR1CurrentDocumentsV2)
                self.assertEqual(result.kind, "genesis-r1")
                self.assertEqual(result.approved_card, value.inputs.approved_card)
                self.assertEqual(result.origin_receipt, value.inputs.origin_receipt)
                self.assertTrue(result.manifest_bytes_materialized)
                self.assertTrue(result.authority_documents_bound)
                self.assertTrue(result.full_genesis_authority_bound)
                self.assertTrue(
                    result.payload_reobservation.complete_manifest_reobserved
                )
                self.assertEqual(
                    result.payload_reobservation.artifact_count,
                    len(value.inputs.commit.files),
                )
                self.assertTrue(result.structural_binding.manifest_bytes_bound)
                self.assertFalse(result.runtime_verified)
                self.assertFalse(result.execution_authorized)
                self.assertFalse(result.publication_authorized)
                self.assertEqual(len(result.document_refs), 9)
                self.assertEqual(
                    result.blockers[-1].code, "FINAL_CURRENT_AND_FENCE_RECHECK"
                )
                retained = result
            with self.assertRaises(VersionedCurrentAuthorityLoadError):
                require_versioned_current_execution_authorized(retained)
        finally:
            fixture.close()

    def test_quality_pass_v2_documents_bind_without_runtime_authority(self) -> None:
        value = quality_pass_v2_disk_authority()
        fixture = VersionedDiskFixture(value.inputs.commit, value.files, 2)
        try:
            with self._load(fixture) as result:
                self.assertIs(type(result), QualityPassV2CurrentDocumentsV2)
                self.assertEqual(result.kind, "quality-pass-v2")
                self.assertEqual(result.authority, value.inputs)
                self.assertEqual(result.binding.parent_authority.kind, "genesis-origin")
                self.assertEqual(len(result.document_refs), 3)
                self.assertEqual(
                    result.blockers[-1].code, "FINAL_CURRENT_AND_FENCE_RECHECK"
                )
                self.assertTrue(result.authority_documents_bound)
                self.assertFalse(result.runtime_verified)
                self.assertFalse(result.execution_authorized)
                self.assertFalse(result.publication_authorized)
                with self.assertRaises(VersionedCurrentAuthorityLoadError):
                    require_versioned_current_execution_authorized(result)
        finally:
            fixture.close()

    def test_frozen_r0_returns_only_an_explicit_legacy_tag(self) -> None:
        value = frozen_r0_quality_pass_disk_authority()
        fixture = VersionedDiskFixture(value.commit, value.files, 2)
        try:
            with self._load(fixture) as result:
                self.assertIs(type(result), FrozenR0CurrentSelectionV1)
                self.assertEqual(result.kind, "frozen-r0")
                self.assertEqual(result.approved_card_class, "approved-parent-v1")
                self.assertFalse(result.authority_documents_bound)
                self.assertFalse(hasattr(result, "approved_card"))
                self.assertEqual(result.blockers[0].code, "FROZEN_R0_LOADER_REQUIRED")
        finally:
            fixture.close()

    def test_committed_genesis_card_with_wrong_schema_version_rejects(self) -> None:
        value = genesis_r1_fixture()
        path = value.inputs.commit.approved_parent_path
        document = json.loads(value.files[path])
        document["schemaVersion"] = 1
        commit, files = _replace_committed_artifact(
            value.inputs.commit, value.files, path, canonical(document)
        )
        fixture = VersionedDiskFixture(commit, files, 1)
        try:
            with self.assertRaises(VersionedCurrentAuthorityLoadError), self._load(
                fixture
            ):
                self.fail("wrong genesis card version unexpectedly loaded")
        finally:
            fixture.close()

    def test_post_materialization_authority_byte_change_rejects(self) -> None:
        value = genesis_r1_fixture()
        fixture = VersionedDiskFixture(value.inputs.commit, value.files, 1)
        path = value.inputs.commit.approved_parent_path
        original = loader_module._assert_store_closure
        calls = []

        def mutate_then_check(store, artifacts):
            calls.append(True)
            if len(calls) == 2:
                target = fixture.materialization / path
                target.write_bytes(b"x" * len(value.files[path]))
            return original(store, artifacts)

        try:
            with patch.object(
                loader_module, "_assert_store_closure", mutate_then_check
            ), self.assertRaises(VersionedCurrentAuthorityLoadError), self._load(
                fixture
            ):
                self.fail("stale materialized card unexpectedly loaded")
        finally:
            fixture.close()

    def test_hostile_profile_string_subclass_cannot_change_dispatch(self) -> None:
        class EqualToEveryString(str):
            def __eq__(self, _other):
                return True

            __hash__ = str.__hash__

        value = genesis_r1_fixture()
        fixture = VersionedDiskFixture(value.inputs.commit, value.files, 1)
        try:
            with loader_module.read_versioned_current_generation(
                str(fixture.authority), str(fixture.materialization)
            ) as selected:
                forged = VersionedResolvedGenerationV2(
                    EqualToEveryString("forged-profile"),
                    selected.approved_card_class,
                    selected.generation,
                )
            with patch.object(
                loader_module,
                "read_versioned_current_generation",
                return_value=nullcontext(forged),
            ), self.assertRaises(VersionedCurrentAuthorityLoadError), self._load(
                fixture
            ):
                self.fail("hostile profile string unexpectedly changed dispatch")
        finally:
            fixture.close()

    def test_frozen_r0_post_materialization_byte_change_rejects(self) -> None:
        value = frozen_r0_quality_pass_disk_authority()
        fixture = VersionedDiskFixture(value.commit, value.files, 2)
        path = value.commit.approved_parent_path
        original = loader_module._assert_store_closure
        mutated = []

        def mutate_then_check(store, artifacts):
            if not mutated:
                target = fixture.materialization / path
                target.write_bytes(b"x" * len(value.files[path]))
                mutated.append(True)
            return original(store, artifacts)

        try:
            with patch.object(
                loader_module, "_assert_store_closure", mutate_then_check
            ), self.assertRaises(VersionedCurrentAuthorityLoadError), self._load(
                fixture
            ):
                self.fail("mutated frozen R0 materialization unexpectedly selected")
        finally:
            fixture.close()

    def test_forged_frozen_r0_selected_current_rejects(self) -> None:
        value = frozen_r0_quality_pass_disk_authority()
        fixture = VersionedDiskFixture(value.commit, value.files, 2)
        try:
            with loader_module.read_versioned_current_generation(
                str(fixture.authority), str(fixture.materialization)
            ) as selected:
                current = dataclasses.replace(
                    selected.generation.current, publication_seq=999
                )
                generation = dataclasses.replace(selected.generation, current=current)
                forged = VersionedResolvedGenerationV2(
                    selected.profile, selected.approved_card_class, generation
                )
            with patch.object(
                loader_module,
                "read_versioned_current_generation",
                return_value=nullcontext(forged),
            ), self.assertRaises(VersionedCurrentAuthorityLoadError), self._load(
                fixture
            ):
                self.fail("forged frozen R0 CURRENT unexpectedly selected")
        finally:
            fixture.close()

    def test_execution_guard_rejects_even_forged_true_result(self) -> None:
        value = genesis_r1_fixture()
        fixture = VersionedDiskFixture(value.inputs.commit, value.files, 1)
        try:
            with self._load(fixture) as result:
                forged = dataclasses.replace(
                    result,
                    runtime_verified=True,
                    execution_authorized=True,
                    publication_authorized=True,
                )
            with self.assertRaises(VersionedCurrentAuthorityLoadError):
                require_versioned_current_execution_authorized(forged)
        finally:
            fixture.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
