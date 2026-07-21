from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest import mock

from _common import pl  # noqa: F401
from _historical_generation_fixture import (
    ORPHAN_ID,
    HistoricalAuthorityFixture,
)
import headless.historical_generation_store as store_module
import headless.historical_generation_walk as walk_module
from headless.historical_generation_resolver import (
    HistoricalGenerationResolutionError,
    resolve_historical_generation,
)
from headless.historical_generation_types import SELECTED_CURRENT_ANCESTRY_SCOPE
from headless.repair_intent import ParentRefV1


class HistoricalGenerationAdversarialTests(unittest.TestCase):
    def _reject(
        self, fixture: HistoricalAuthorityFixture, requested: ParentRefV1
    ) -> None:
        with self.assertRaises(HistoricalGenerationResolutionError):
            with resolve_historical_generation(
                str(fixture.authority), str(fixture.destination), requested
            ):
                pass

    def test_sequence_gap_fails_closed(self) -> None:
        fixture = HistoricalAuthorityFixture()
        try:
            fixture.rewrite(
                2,
                lambda document: document["expectedParent"].__setitem__(
                    "publicationSeq", 1
                ),
            )
            self._reject(fixture, fixture.requested(1))
        finally:
            fixture.close()

    def test_child_signed_commit_id_and_plan_mismatches_fail(self) -> None:
        mutations = (
            ("commitDigest", "0" * 64),
            ("generationId", ORPHAN_ID),
            ("planDigest", "0" * 64),
        )
        for key, value in mutations:
            fixture = HistoricalAuthorityFixture(include_orphan=True)
            try:
                fixture.rewrite(
                    2,
                    lambda document, key=key, value=value: document[
                        "expectedParent"
                    ].__setitem__(key, value),
                )
                self._reject(fixture, fixture.requested(1))
            finally:
                fixture.close()

    def test_cycle_and_non_genesis_null_parent_fail(self) -> None:
        for mutation in ("cycle", "null"):
            fixture = HistoricalAuthorityFixture()
            try:
                current_ref = fixture.generations[2].ref()

                def mutate(document: dict) -> None:
                    if mutation == "null":
                        document["expectedParent"] = None
                        return
                    document["expectedParent"] = {
                        "authorityId": current_ref.authority_id,
                        "publicationSeq": 1,
                        "generationId": current_ref.generation_id,
                        "commitDigest": current_ref.commit_digest,
                        "planDigest": current_ref.plan_digest,
                    }

                fixture.rewrite(1, mutate)
                self._reject(fixture, fixture.requested(0))
            finally:
                fixture.close()

    def test_missing_symlink_and_writable_generation_fail(self) -> None:
        for mutation in ("missing", "symlink", "writable"):
            fixture = HistoricalAuthorityFixture()
            try:
                target = fixture.generation_path(1)
                if mutation == "missing":
                    target.chmod(0o700)
                    os.rename(target, fixture.root / "removed-generation")
                elif mutation == "symlink":
                    outside = fixture.root / "outside-generation"
                    target.chmod(0o700)
                    os.rename(target, outside)
                    target.symlink_to(outside, target_is_directory=True)
                else:
                    target.chmod(0o700)
                self._reject(fixture, fixture.requested(1))
            finally:
                fixture.close()

    def test_valid_orphan_is_not_an_ancestor_and_is_not_materialized(self) -> None:
        fixture = HistoricalAuthorityFixture(include_orphan=True)
        try:
            self.assertIsNotNone(fixture.orphan)
            self._reject(fixture, fixture.orphan.ref())  # type: ignore[union-attr]
            self.assertEqual(tuple(fixture.destination.iterdir()), ())
        finally:
            fixture.close()

    def test_orphaned_fork_does_not_upgrade_proof_scope(self) -> None:
        fixture = HistoricalAuthorityFixture(include_orphan=True)
        try:
            with resolve_historical_generation(
                str(fixture.authority),
                str(fixture.destination),
                fixture.requested(1),
            ) as resolved:
                self.assertEqual(resolved.proof_scope, SELECTED_CURRENT_ANCESTRY_SCOPE)
                self.assertNotIn(
                    ORPHAN_ID,
                    tuple(row.ref.generation_id for row in resolved.lineage),
                )
        finally:
            fixture.close()

    def test_hostile_parent_subclass_is_rejected(self) -> None:
        class HostileParent(ParentRefV1):
            def __eq__(self, other: object) -> bool:
                return True

        fixture = HistoricalAuthorityFixture()
        try:
            ref = fixture.requested(1)
            hostile = HostileParent(
                ref.authority_id,
                ref.publication_seq,
                ref.generation_id,
                ref.commit_digest,
                ref.plan_digest,
            )
            self._reject(fixture, hostile)
        finally:
            fixture.close()

    def test_source_replacement_during_hash_fails(self) -> None:
        fixture = HistoricalAuthorityFixture()
        original = store_module._stream
        changed: list[bool] = []

        def replacing_stream(source_fd: int, destination_fd: int | None):
            result = original(source_fd, destination_fd)
            if changed:
                return result
            source_inode = os.fstat(source_fd).st_ino
            root = fixture.generation_path(2)
            target = next(
                path
                for path in root.rglob("*")
                if path.is_file() and path.stat().st_ino == source_inode
            )
            target.parent.chmod(0o700)
            replacement = target.parent / ".replacement"
            replacement.write_bytes(target.read_bytes())
            replacement.chmod(0o400)
            os.replace(replacement, target)
            target.parent.chmod(0o500)
            changed.append(True)
            return result

        try:
            with mock.patch.object(store_module, "_stream", replacing_stream):
                self._reject(fixture, fixture.requested(1))
        finally:
            fixture.close()

    def test_current_inode_substitution_during_walk_fails(self) -> None:
        fixture = HistoricalAuthorityFixture()
        original = store_module.HistoricalSourceArtifactStoreV1.audit
        changed: list[bool] = []

        def replacing_current(commit, root, policy):
            result = original(commit, root, policy)
            if not changed:
                fixture.replace_current_inode()
                changed.append(True)
            return result

        try:
            with mock.patch.object(
                store_module.HistoricalSourceArtifactStoreV1,
                "audit",
                side_effect=replacing_current,
            ):
                self._reject(fixture, fixture.requested(1))
        finally:
            fixture.close()

    def test_materialized_leaf_substitution_before_return_fails(self) -> None:
        fixture = HistoricalAuthorityFixture()
        original = walk_module._revalidate

        def replace_output(context) -> None:
            original(context)
            target = fixture.destination / "plan/edit-plan.json"
            replacement = fixture.root / "replacement-plan"
            replacement.write_bytes(target.read_bytes())
            replacement.chmod(0o600)
            os.replace(replacement, target)

        try:
            with mock.patch.object(walk_module, "_revalidate", replace_output):
                self._reject(fixture, fixture.requested(1))
        finally:
            fixture.close()


if __name__ == "__main__":
    unittest.main()
