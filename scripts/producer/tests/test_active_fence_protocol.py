"""Nominal, replay, conflict, and non-authority active-fence contracts."""

from __future__ import annotations

import json
import os
import unittest

from _active_fence_fixture import ActiveFenceFixture
from _common import pl  # noqa: F401
from headless.active_fence_protocol import (
    cancel_active_generation_fence_v1,
    reserve_active_generation_fence_v1,
)
from headless.active_fence_schema import parse_active_fence_document_v1
from headless.active_fence_types import (
    ActiveFenceConflictError,
    ActiveFenceError,
)


class ActiveFenceProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ActiveFenceFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def assert_nonauthorizing(self, result: object) -> None:
        """Require every authority-bearing result flag to remain false."""
        flags = (
            result.execution_authorized,
            result.publication_authorized,
            result.release_authorized,
            result.current_advanced,
            result.work_launched,
        )
        self.assertEqual(flags, (False,) * 5)

    def test_bootstrap_creates_exact_inactive_revision_zero(self) -> None:
        result = self.fixture.bootstrap()
        self.assertTrue(result.created)
        self.assertFalse(result.replayed)
        self.assertEqual(result.operation, "BOOTSTRAP")
        self.assertEqual(result.state.fence_revision, 0)
        self.assertIsNone(result.state.active_attempt_id)
        row = json.loads(self.fixture.fence_bytes())
        self.assertEqual(
            set(row),
            {
                "schemaVersion",
                "authorityId",
                "fenceRevision",
                "fenceToken",
                "activeAttemptId",
            },
        )
        self.assertEqual(len(self.fixture.journal_bytes().splitlines()), 1)
        self.assertFalse(
            os.path.exists(os.path.join(self.fixture.root, "CURRENT"))
        )
        self.assert_nonauthorizing(result)

    def test_bootstrap_replay_preserves_token_bytes_and_lock_inode(
        self,
    ) -> None:
        first = self.fixture.bootstrap()
        before = (
            self.fixture.journal_bytes(),
            self.fixture.fence_bytes(),
            os.stat(self.fixture.lock_path).st_ino,
        )
        second = self.fixture.bootstrap()
        after = (
            self.fixture.journal_bytes(),
            self.fixture.fence_bytes(),
            os.stat(self.fixture.lock_path).st_ino,
        )
        self.assertEqual(before, after)
        self.assertEqual(first.state, second.state)
        self.assertFalse(second.created)
        self.assertTrue(second.replayed)
        self.assert_nonauthorizing(second)

    def test_reserve_rotates_once_and_exact_replay_is_stable(self) -> None:
        bootstrap = self.fixture.bootstrap()
        first = self.fixture.reserve()
        before = self.fixture.journal_bytes()
        replay = self.fixture.reserve()
        self.assertEqual(first.state.fence_revision, 1)
        self.assertNotEqual(
            bootstrap.state.fence_token, first.state.fence_token
        )
        self.assertEqual(first.state.active_attempt_id, self.fixture.attempt_a)
        self.assertEqual(first.state, replay.state)
        self.assertEqual(before, self.fixture.journal_bytes())
        self.assertFalse(replay.created)
        self.assert_nonauthorizing(first)

    def test_conflicting_reserve_is_side_effect_free(self) -> None:
        self.fixture.bootstrap()
        active = self.fixture.reserve()
        before = (self.fixture.journal_bytes(), self.fixture.fence_bytes())
        with self.assertRaises(ActiveFenceConflictError):
            self.fixture.reserve(self.fixture.attempt_b)
        self.assertEqual(
            before, (self.fixture.journal_bytes(), self.fixture.fence_bytes())
        )
        self.assertEqual(
            parse_active_fence_document_v1(self.fixture.fence_bytes()),
            active.state,
        )

    def test_cancel_rotates_clears_and_exact_replay_is_stable(self) -> None:
        self.fixture.bootstrap()
        active = self.fixture.reserve()
        canceled = self.fixture.cancel()
        before = self.fixture.journal_bytes()
        replay = self.fixture.cancel()
        self.assertEqual(canceled.state.fence_revision, 2)
        self.assertNotEqual(
            active.state.fence_token, canceled.state.fence_token
        )
        self.assertIsNone(canceled.state.active_attempt_id)
        self.assertEqual(canceled.state, replay.state)
        self.assertEqual(before, self.fixture.journal_bytes())
        self.assertFalse(replay.created)
        self.assert_nonauthorizing(canceled)

    def test_canceled_attempt_identity_cannot_be_resurrected(self) -> None:
        self.fixture.bootstrap()
        self.fixture.reserve()
        self.fixture.cancel()
        before = self.fixture.journal_bytes()
        with self.assertRaises(ActiveFenceConflictError):
            self.fixture.reserve()
        self.assertEqual(before, self.fixture.journal_bytes())
        fresh = self.fixture.reserve(self.fixture.attempt_b)
        self.assertEqual(fresh.state.active_attempt_id, self.fixture.attempt_b)

    def test_cancel_without_exact_active_or_replay_conflicts(self) -> None:
        self.fixture.bootstrap()
        before = self.fixture.journal_bytes()
        with self.assertRaises(ActiveFenceConflictError):
            self.fixture.cancel()
        self.assertEqual(before, self.fixture.journal_bytes())
        self.fixture.reserve()
        with self.assertRaises(ActiveFenceConflictError):
            self.fixture.cancel(self.fixture.attempt_b)

    def test_mutations_require_existing_bootstrap_without_creation(
        self,
    ) -> None:
        with self.assertRaises(ActiveFenceError):
            self.fixture.reserve()
        self.assertFalse(os.path.exists(self.fixture.lock_path))
        with self.assertRaises(ActiveFenceError):
            self.fixture.cancel()
        self.assertEqual(os.listdir(self.fixture.root), [])

    def test_invalid_public_inputs_fail_before_state_mutation(self) -> None:
        with self.assertRaises(ActiveFenceError):
            reserve_active_generation_fence_v1(
                self.fixture.root, self.fixture.authority_id, "NOT-A-UUID"
            )
        self.assertEqual(os.listdir(self.fixture.root), [])
        self.fixture.bootstrap()
        before = self.fixture.journal_bytes()
        with self.assertRaises(ActiveFenceError):
            cancel_active_generation_fence_v1(
                self.fixture.root, "bad authority!", self.fixture.attempt_a
            )
        self.assertEqual(before, self.fixture.journal_bytes())


if __name__ == "__main__":
    unittest.main(verbosity=2)
