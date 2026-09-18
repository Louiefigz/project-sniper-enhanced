"""Disk-real exact-dispatch regressions for selected versioned CURRENT."""

from __future__ import annotations

import json
import unittest

from _approved_parent_loader_documents import AuthorityDocuments
from _approved_parent_loader_values import canonical
from _common import pl  # noqa: F401
from _genesis_r1_fixture import genesis_r1_fixture
from _versioned_disk_authorities import (
    frozen_r0_quality_pass_disk_authority,
    quality_pass_v2_disk_authority,
)
from _versioned_disk_fixture import VersionedDiskFixture, assert_commit_files_match
from headless.generation_schema import parse_generation_commit
from headless.genesis_generation_profile import (
    GENESIS_R1_PROFILE,
    QUALITY_PASS_R0_PROFILE,
)
from headless.versioned_generation_reader import (
    VersionedGenerationReadError,
    read_versioned_current_generation,
)
from headless.versioned_quality_pass_profile import QUALITY_PASS_R1_PROFILE


class VersionedGenerationReaderDiskTests(unittest.TestCase):
    def _read(self, fixture: VersionedDiskFixture):
        return read_versioned_current_generation(
            str(fixture.authority), str(fixture.materialization)
        )

    def _reject(self, fixture: VersionedDiskFixture) -> None:
        with self.assertRaises(VersionedGenerationReadError), self._read(fixture):
            self.fail("invalid selected CURRENT unexpectedly materialized")

    def test_r1_genesis_current_is_selected_and_materialized(self) -> None:
        value = genesis_r1_fixture()
        assert_commit_files_match(value.inputs.commit, value.files)
        fixture = VersionedDiskFixture(value.inputs.commit, value.files, 1)
        try:
            with self._read(fixture) as selected:
                self.assertEqual(selected.profile, GENESIS_R1_PROFILE)
                self.assertEqual(
                    selected.approved_card_class, "genesis-approved-card-v2"
                )
                self.assertEqual(
                    set(selected.generation.materialized), set(value.files)
                )
        finally:
            fixture.close()

    def test_quality_pass_v2_and_frozen_r0_dispatch_are_disjoint(self) -> None:
        quality = quality_pass_v2_disk_authority()
        frozen = frozen_r0_quality_pass_disk_authority()
        values = (
            (
                quality.inputs.commit,
                quality.files,
                QUALITY_PASS_R1_PROFILE,
                "quality-pass-approved-card-v2",
            ),
            (
                frozen.commit,
                frozen.files,
                QUALITY_PASS_R0_PROFILE,
                "approved-parent-v1",
            ),
        )
        for commit, files, profile, card_class in values:
            fixture = VersionedDiskFixture(commit, files, 2)
            try:
                with self.subTest(profile=profile), self._read(fixture) as selected:
                    self.assertEqual(selected.profile, profile)
                    self.assertEqual(selected.approved_card_class, card_class)
            finally:
                fixture.close()

    def test_null_parent_r0_is_rejected_before_any_manifest_copy(self) -> None:
        legacy = AuthorityDocuments()
        fixture = VersionedDiskFixture(legacy.commit, legacy.files, 1)
        try:
            self._reject(fixture)
            self.assertEqual(tuple(fixture.materialization.iterdir()), ())
        finally:
            fixture.close()

    def test_genesis_r1_current_must_have_publication_sequence_one(self) -> None:
        value = genesis_r1_fixture()
        fixture = VersionedDiskFixture(value.inputs.commit, value.files, 2)
        try:
            self._reject(fixture)
            self.assertEqual(tuple(fixture.materialization.iterdir()), ())
        finally:
            fixture.close()

    def test_quality_pass_current_must_follow_parent_sequence(self) -> None:
        value = quality_pass_v2_disk_authority()
        fixture = VersionedDiskFixture(value.inputs.commit, value.files, 3)
        try:
            self._reject(fixture)
            self.assertEqual(tuple(fixture.materialization.iterdir()), ())
        finally:
            fixture.close()

    def test_card_class_profile_mismatch_rejects_before_tree_walk(self) -> None:
        value = genesis_r1_fixture()
        document = json.loads(value.inputs.commit.document_json)
        row = next(
            item
            for item in document["files"]
            if item["path"] == document["approvedParentPath"]
        )
        row["artifactClass"] = "approved-parent-v1"
        commit = parse_generation_commit(canonical(document))
        fixture = VersionedDiskFixture(commit, value.files, 1)
        try:
            self._reject(fixture)
            self.assertEqual(tuple(fixture.materialization.iterdir()), ())
        finally:
            fixture.close()

    def test_stale_bytes_and_unsafe_manifest_symlink_reject(self) -> None:
        for mutation in ("stale", "symlink"):
            value = genesis_r1_fixture()
            fixture = VersionedDiskFixture(value.inputs.commit, value.files, 1)
            target = value.inputs.commit.approved_parent_path
            try:
                if mutation == "stale":
                    fixture.corrupt_artifact(target, b"x" * len(value.files[target]))
                else:
                    fixture.replace_with_symlink(target)
                with self.subTest(mutation=mutation):
                    self._reject(fixture)
            finally:
                fixture.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
