"""Adversarial tests for full streamed genesis payload reobservation."""

from __future__ import annotations

import dataclasses
import os
import unittest
from contextlib import AbstractContextManager
from types import MappingProxyType
from unittest.mock import patch

from _common import pl  # noqa: F401
from _genesis_r1_fixture import genesis_r1_fixture
from _versioned_disk_fixture import VersionedDiskFixture
from headless.genesis_authority_validation import GenesisAuthorityBindingError
from headless.genesis_generation_profile import GENESIS_R1_MANIFEST_ROWS
from headless.genesis_payload_reobservation import (
    GenesisPayloadReobservationError,
    reobserve_genesis_payload,
    require_genesis_payload_execution_authorized,
)
from headless.genesis_streaming_authority import (
    bind_streamed_genesis_r1_authority,
)
from headless.versioned_current_loader import (
    VersionedCurrentAuthorityLoadError,
    load_versioned_current_authority,
)
from headless.versioned_generation_reader import (
    VersionedResolvedGenerationV2,
    read_versioned_current_generation,
)
import headless.generation_reader_fs as reader_fs
import headless.versioned_current_loader as loader_module

_SEMANTIC_CLASSES = frozenset(
    {
        "genesis-approved-card-v2",
        "initialization-origin-receipt-v1",
        "headless-operation-v1",
        "initialization-snapshot-authority-v1",
        "initialization-execution-policy-v2",
        "generation-verification-v2",
        "repair-policy-v1",
        "quality-policy-v1",
        "fallback-policy-v1",
    }
)


def _semantic_inputs(value: object) -> object:
    artifacts = {
        path: raw
        for path, raw in value.files.items()
        if value.classes[path] in _SEMANTIC_CLASSES
    }
    return dataclasses.replace(value.inputs, artifact_bytes=MappingProxyType(artifacts))


class GenesisPayloadReobservationTests(unittest.TestCase):
    def _reader(
        self, fixture: VersionedDiskFixture
    ) -> AbstractContextManager[VersionedResolvedGenerationV2]:
        return read_versioned_current_generation(
            str(fixture.authority), str(fixture.materialization)
        )

    def test_all_44_rows_stream_into_path_free_non_authorizing_evidence(self) -> None:
        value = genesis_r1_fixture()
        fixture = VersionedDiskFixture(value.inputs.commit, value.files, 1)
        original = reader_fs._stream
        streamed_inodes = []
        try:
            with self._reader(fixture) as selected:

                def record_stream(fd: int, destination: int | None) -> tuple[int, str]:
                    streamed_inodes.append(os.fstat(fd).st_ino)
                    return original(fd, destination)

                with patch.object(reader_fs, "_stream", record_stream):
                    result = reobserve_genesis_payload(selected)
            self.assertEqual(result.artifact_count, GENESIS_R1_MANIFEST_ROWS)
            self.assertEqual(len(result.artifacts), GENESIS_R1_MANIFEST_ROWS)
            self.assertEqual(len(streamed_inodes), GENESIS_R1_MANIFEST_ROWS)
            self.assertEqual(len(set(streamed_inodes)), GENESIS_R1_MANIFEST_ROWS)
            self.assertEqual(
                tuple(item.artifact.relative_path for item in result.artifacts),
                tuple(row.path for row in value.inputs.commit.files),
            )
            self.assertEqual(
                result.total_size_bytes,
                sum(row.size_bytes for row in value.inputs.commit.files),
            )
            self.assertTrue(result.exact_materialization_closure_bound)
            self.assertTrue(result.complete_manifest_reobserved)
            self.assertNotIn(str(fixture.materialization), repr(result))
            self.assertFalse(
                any(
                    os.path.isabs(item.artifact.relative_path)
                    for item in result.artifacts
                )
            )
            self.assertFalse(result.final_current_rechecked)
            self.assertFalse(result.runtime_verified)
            self.assertFalse(result.execution_authorized)
            self.assertFalse(result.publication_authorized)
        finally:
            fixture.close()

    def test_streamed_evidence_closes_structural_mapping_only(self) -> None:
        value = genesis_r1_fixture()
        fixture = VersionedDiskFixture(value.inputs.commit, value.files, 1)
        try:
            with self._reader(fixture) as selected:
                observation = reobserve_genesis_payload(selected)
            binding = bind_streamed_genesis_r1_authority(
                _semantic_inputs(value), observation
            )
            self.assertTrue(binding.manifest_bytes_bound)
            self.assertTrue(binding.structural_verification_bound)
            self.assertFalse(binding.trusted_store_verified)
            self.assertFalse(binding.runtime_verified)
            self.assertFalse(binding.execution_authorized)
            self.assertFalse(binding.publication_authorized)
        finally:
            fixture.close()

    def test_missing_extra_symlink_hardlink_and_mode_drift_reject(self) -> None:
        mutations = ("missing", "extra", "symlink", "hardlink", "mode")
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                value = genesis_r1_fixture()
                fixture = VersionedDiskFixture(value.inputs.commit, value.files, 1)
                try:
                    with self._reader(fixture) as selected:
                        self._mutate_materialization(fixture, value, mutation)
                        with self.assertRaises(GenesisPayloadReobservationError):
                            reobserve_genesis_payload(selected)
                finally:
                    fixture.close()

    def _mutate_materialization(
        self, fixture: VersionedDiskFixture, value: object, mutation: str
    ) -> None:
        relative = value.inputs.commit.approved_parent_path
        target = fixture.materialization / relative
        if mutation == "missing":
            target.unlink()
        elif mutation == "extra":
            (fixture.materialization / "extra-artifact").write_bytes(b"extra")
        elif mutation == "symlink":
            outside = fixture.root / "outside-artifact"
            outside.write_bytes(value.files[relative])
            target.unlink()
            target.symlink_to(outside)
        elif mutation == "hardlink":
            os.link(target, fixture.root / "second-link")
        elif mutation == "mode":
            target.chmod(0o644)

    def test_same_inode_mutation_during_stream_rejects(self) -> None:
        value = genesis_r1_fixture()
        fixture = VersionedDiskFixture(value.inputs.commit, value.files, 1)
        target = fixture.materialization / value.inputs.commit.approved_parent_path
        original = reader_fs._stream
        mutated = []
        try:
            with self._reader(fixture) as selected:
                target_inode = target.stat().st_ino

                def mutate_after_hash(
                    fd: int, destination: int | None
                ) -> tuple[int, str]:
                    observed = original(fd, destination)
                    if os.fstat(fd).st_ino == target_inode and not mutated:
                        with target.open("r+b", buffering=0) as handle:
                            handle.write(b"x")
                            os.fsync(handle.fileno())
                        mutated.append(True)
                    return observed

                with patch.object(
                    reader_fs, "_stream", mutate_after_hash
                ), self.assertRaises(GenesisPayloadReobservationError):
                    reobserve_genesis_payload(selected)
            self.assertTrue(mutated)
        finally:
            fixture.close()

    def test_post_copy_mutation_rejects_even_when_size_is_unchanged(self) -> None:
        value = genesis_r1_fixture()
        fixture = VersionedDiskFixture(value.inputs.commit, value.files, 1)
        relative = value.inputs.commit.approved_parent_path
        try:
            with self._reader(fixture) as selected:
                target = fixture.materialization / relative
                target.write_bytes(b"x" * len(value.files[relative]))
                with self.assertRaises(GenesisPayloadReobservationError):
                    reobserve_genesis_payload(selected)
        finally:
            fixture.close()

    def test_forged_observation_and_true_flags_never_authorize(self) -> None:
        value = genesis_r1_fixture()
        fixture = VersionedDiskFixture(value.inputs.commit, value.files, 1)
        try:
            with self._reader(fixture) as selected:
                observation = reobserve_genesis_payload(selected)
            forged = dataclasses.replace(
                observation,
                complete_manifest_reobserved=False,
                runtime_verified=True,
                execution_authorized=True,
                publication_authorized=True,
            )
            with self.assertRaises(GenesisAuthorityBindingError):
                bind_streamed_genesis_r1_authority(_semantic_inputs(value), forged)
            for candidate in (observation, forged):
                with self.assertRaises(GenesisPayloadReobservationError):
                    require_genesis_payload_execution_authorized(candidate)
        finally:
            fixture.close()

    def test_forged_selection_snapshot_dataclass_rejects(self) -> None:
        value = genesis_r1_fixture()
        fixture = VersionedDiskFixture(value.inputs.commit, value.files, 1)
        try:
            with self._reader(fixture) as selected:
                snapshots = dict(selected.generation.materialized_snapshots)
                path = value.inputs.commit.approved_parent_path
                snapshots[path] = tuple([*snapshots[path][:-1], 0])
                generation = dataclasses.replace(
                    selected.generation,
                    materialized_snapshots=MappingProxyType(snapshots),
                )
                forged = dataclasses.replace(selected, generation=generation)
                with self.assertRaises(GenesisPayloadReobservationError):
                    reobserve_genesis_payload(forged)
        finally:
            fixture.close()

    def test_semantic_mapping_must_be_exact_bounded_document_set(self) -> None:
        value = genesis_r1_fixture()
        fixture = VersionedDiskFixture(value.inputs.commit, value.files, 1)
        inputs = _semantic_inputs(value)
        try:
            with self._reader(fixture) as selected:
                observation = reobserve_genesis_payload(selected)
            missing = dict(inputs.artifact_bytes)
            missing.pop(next(iter(missing)))
            extra = dict(inputs.artifact_bytes)
            extra["uncommitted/extra.json"] = b"{}"
            for artifacts in (missing, extra):
                with self.subTest(paths=tuple(artifacts)), self.assertRaises(
                    GenesisAuthorityBindingError
                ):
                    bind_streamed_genesis_r1_authority(
                        dataclasses.replace(
                            inputs, artifact_bytes=MappingProxyType(artifacts)
                        ),
                        observation,
                    )
        finally:
            fixture.close()

    def test_semantic_document_limit_is_enforced_before_parsing(self) -> None:
        value = genesis_r1_fixture()
        fixture = VersionedDiskFixture(value.inputs.commit, value.files, 1)
        card_size = len(value.inputs.approved_card.document_json)
        try:
            with patch.object(
                loader_module, "_GENESIS_DOCUMENT_LIMIT", card_size - 1
            ), self.assertRaises(
                VersionedCurrentAuthorityLoadError
            ), load_versioned_current_authority(
                str(fixture.authority), str(fixture.materialization)
            ):
                self.fail("oversized semantic document unexpectedly loaded")
        finally:
            fixture.close()

    def test_reobservation_never_materializes_directory_listings(self) -> None:
        value = genesis_r1_fixture()
        fixture = VersionedDiskFixture(value.inputs.commit, value.files, 1)
        failure = AssertionError("unbounded directory list")
        try:
            with patch.object(
                reader_fs.os, "listdir", side_effect=failure
            ), self._reader(fixture) as selected:
                result = reobserve_genesis_payload(selected)
            self.assertEqual(result.artifact_count, GENESIS_R1_MANIFEST_ROWS)
        finally:
            fixture.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
