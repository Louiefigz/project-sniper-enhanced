"""Held-lock mutation and exact active-fence reobservation contracts."""

from __future__ import annotations

import dataclasses
import fcntl
import multiprocessing
import os
import unittest
from unittest.mock import patch

from _active_fence_fixture import ActiveFenceFixture
from _common import pl  # noqa: F401
from headless.active_fence_lock import locked_existing_publish_mutex_v1
from headless.active_fence_protocol import (
    reobserve_active_generation_fence_under_lock_v1,
    reobserve_exact_active_generation_fence_under_lock_v1,
    reserve_active_generation_fence_under_lock_v1,
)
from headless.active_fence_types import (
    ActiveFenceConflictError,
    ActiveFenceError,
)

_PUBLIC_LOCK_TARGET = (
    "headless.active_fence_protocol.locked_existing_publish_mutex_v1"
)


def _fork_locked_reserve(
    lock: object, authority: str, attempt: str, output
) -> None:
    try:
        reserve_active_generation_fence_under_lock_v1(lock, authority, attempt)
    except ActiveFenceError:
        output.send("rejected")
    else:
        output.send("accepted")
    output.close()


class _HostileExpected:
    def __eq__(self, other: object) -> bool:
        raise AssertionError("attacker equality must not run")


class ActiveFenceUnderLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ActiveFenceFixture()
        self.bootstrap = self.fixture.bootstrap()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_live_reserve_replay_and_bounded_reads_are_exact(self) -> None:
        with locked_existing_publish_mutex_v1(self.fixture.root) as lock:
            inactive = reobserve_active_generation_fence_under_lock_v1(lock)
            first = reserve_active_generation_fence_under_lock_v1(
                lock, self.fixture.authority_id, self.fixture.attempt_a
            )
            before = self.fixture.journal_bytes()
            replay = reserve_active_generation_fence_under_lock_v1(
                lock, self.fixture.authority_id, self.fixture.attempt_a
            )
            observed = reobserve_exact_active_generation_fence_under_lock_v1(
                lock, first.state
            )
        self.assertEqual(inactive, self.bootstrap.state)
        self.assertEqual(first.state, replay.state)
        self.assertEqual(first.state, observed)
        self.assertEqual(first.state.fence_token, replay.state.fence_token)
        self.assertEqual(before, self.fixture.journal_bytes())
        self.assertTrue(first.created)
        self.assertTrue(replay.replayed)
        flags = (
            first.execution_authorized,
            first.publication_authorized,
            first.release_authorized,
            first.current_advanced,
            first.work_launched,
        )
        self.assertEqual(flags, (False,) * 5)

    def test_under_lock_paths_do_not_reacquire_public_mutex(self) -> None:
        with locked_existing_publish_mutex_v1(self.fixture.root) as lock:
            with patch(
                _PUBLIC_LOCK_TARGET,
                side_effect=AssertionError("unexpected lock reacquisition"),
            ):
                reserved = reserve_active_generation_fence_under_lock_v1(
                    lock, self.fixture.authority_id, self.fixture.attempt_a
                )
                observed = reobserve_active_generation_fence_under_lock_v1(
                    lock
                )
                exact = reobserve_exact_active_generation_fence_under_lock_v1(
                    lock, observed
                )
        self.assertEqual(observed, reserved.state)
        self.assertEqual(exact, reserved.state)

    def test_invalid_ids_fail_without_mutating_journal(self) -> None:
        before = self.fixture.journal_bytes()
        with locked_existing_publish_mutex_v1(self.fixture.root) as lock:
            for authority, attempt in (
                ("bad authority!", self.fixture.attempt_a),
                (self.fixture.authority_id, "NOT-A-UUID"),
            ):
                with self.subTest(authority=authority, attempt=attempt):
                    with self.assertRaises(ActiveFenceError):
                        reserve_active_generation_fence_under_lock_v1(
                            lock, authority, attempt
                        )
        self.assertEqual(before, self.fixture.journal_bytes())

    def test_forged_stale_and_released_witnesses_fail(self) -> None:
        with locked_existing_publish_mutex_v1(self.fixture.root) as lock:
            forged = dataclasses.replace(lock)
            with self.assertRaises(ActiveFenceError):
                reserve_active_generation_fence_under_lock_v1(
                    forged, self.fixture.authority_id, self.fixture.attempt_a
                )
            stale = lock
        with self.assertRaises(ActiveFenceError):
            reobserve_active_generation_fence_under_lock_v1(stale)
        with self.assertRaises(ActiveFenceError):
            with locked_existing_publish_mutex_v1(self.fixture.root) as lock:
                fcntl.flock(lock.lock_fd, fcntl.LOCK_UN)
                reobserve_active_generation_fence_under_lock_v1(lock)

    def test_fork_inherited_witness_fails(self) -> None:
        context = multiprocessing.get_context("fork")
        with locked_existing_publish_mutex_v1(self.fixture.root) as lock:
            receiver, sender = context.Pipe(duplex=False)
            process = context.Process(
                target=_fork_locked_reserve,
                args=(
                    lock,
                    self.fixture.authority_id,
                    self.fixture.attempt_a,
                    sender,
                ),
            )
            process.start()
            self.assertEqual(receiver.recv(), "rejected")
            process.join(5)
            self.assertEqual(process.exitcode, 0)
            observed = reobserve_active_generation_fence_under_lock_v1(lock)
        self.assertEqual(observed, self.bootstrap.state)

    def test_exact_read_rejects_any_different_full_state(self) -> None:
        with locked_existing_publish_mutex_v1(self.fixture.root) as lock:
            active = reserve_active_generation_fence_under_lock_v1(
                lock, self.fixture.authority_id, self.fixture.attempt_a
            )
            with self.assertRaises(ActiveFenceConflictError):
                reobserve_exact_active_generation_fence_under_lock_v1(
                    lock, self.bootstrap.state
                )
            with self.assertRaises(ActiveFenceConflictError):
                reobserve_exact_active_generation_fence_under_lock_v1(
                    lock, _HostileExpected()  # type: ignore[arg-type]
                )
            observed = reobserve_exact_active_generation_fence_under_lock_v1(
                lock, active.state
            )
        self.assertEqual(observed, active.state)

    def test_torn_tail_and_stale_projection_recover_exactly(self) -> None:
        active = self.fixture.reserve()
        journal = self.fixture.journal_bytes()
        with open(self.fixture.fence_path, "wb") as output:
            output.write(self.bootstrap.state.document_json)
        os.chmod(self.fixture.fence_path, 0o600)
        with open(self.fixture.journal_path, "ab") as output:
            output.write(b'{"frameVersion":1')
            output.flush()
            os.fsync(output.fileno())
        with locked_existing_publish_mutex_v1(self.fixture.root) as lock:
            observed = reobserve_exact_active_generation_fence_under_lock_v1(
                lock, active.state
            )
        self.assertEqual(observed, active.state)
        self.assertEqual(self.fixture.journal_bytes(), journal)
        self.assertEqual(
            self.fixture.fence_bytes(), active.state.document_json
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
