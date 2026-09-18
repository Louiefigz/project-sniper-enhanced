from __future__ import annotations

import fcntl
import os
import unittest
from pathlib import Path
from unittest import mock

from _common import pl  # noqa: F401
from _historical_generation_fixture import HistoricalAuthorityFixture
from headless.historical_generation_resolver import resolve_historical_generation
from headless.historical_generation_store import HistoricalSourceArtifactStoreV1
from headless.historical_generation_types import SELECTED_CURRENT_ANCESTRY_SCOPE


class HistoricalGenerationResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = HistoricalAuthorityFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def _resolve(self, index: int):
        return resolve_historical_generation(
            str(self.fixture.authority),
            str(self.fixture.destination),
            self.fixture.requested(index),
        )

    def test_resolves_middle_ancestor_and_proves_full_selected_chain(self) -> None:
        with self._resolve(1) as resolved:
            self.assertEqual(resolved.proof_scope, SELECTED_CURRENT_ANCESTRY_SCOPE)
            self.assertEqual(resolved.target.ref, self.fixture.requested(1))
            self.assertEqual(
                tuple(row.ref.publication_seq for row in resolved.lineage),
                (3, 2, 1),
            )
            self.assertEqual(
                tuple(row.ref for row in resolved.lineage),
                tuple(reversed([item.ref() for item in self.fixture.generations])),
            )
            expected = set(self.fixture.generations[1].files)
            self.assertEqual(set(resolved.materialized), expected)
            self.assertEqual(set(resolved.materialized_snapshots), expected)
            for relative, raw in self.fixture.generations[1].files.items():
                path = Path(resolved.materialized[relative])
                self.assertEqual(path.read_bytes(), raw)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertFalse((self.fixture.destination / "commit.json").exists())

    def test_current_middle_and_genesis_are_individually_resolvable(self) -> None:
        for index in (2, 1, 0):
            fixture = HistoricalAuthorityFixture()
            try:
                with resolve_historical_generation(
                    str(fixture.authority),
                    str(fixture.destination),
                    fixture.requested(index),
                ) as resolved:
                    self.assertEqual(resolved.target.ref, fixture.requested(index))
                    self.assertEqual(len(resolved.lineage), 3)
            finally:
                fixture.close()

    def test_result_mappings_are_immutable(self) -> None:
        with self._resolve(1) as resolved:
            with self.assertRaises(TypeError):
                resolved.materialized["new"] = "/tmp/new"  # type: ignore[index]
            with self.assertRaises(TypeError):
                resolved.materialized_snapshots["new"] = ()  # type: ignore[index]

    def test_shared_publish_flock_is_held_for_complete_walk(self) -> None:
        observed: list[bool] = []
        original = HistoricalSourceArtifactStoreV1.audit

        def checking_audit(commit, root, policy):
            if not observed:
                lock_fd = os.open(self.fixture.authority / ".publish.mutex", os.O_RDWR)
                try:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    observed.append(True)
                finally:
                    os.close(lock_fd)
            return original(commit, root, policy)

        with mock.patch.object(
            HistoricalSourceArtifactStoreV1,
            "audit",
            side_effect=checking_audit,
        ):
            with self._resolve(1):
                pass
        self.assertEqual(observed, [True])


if __name__ == "__main__":
    unittest.main()
