"""Forgery, concurrency, lock-capability, and inode attacks on FENCE."""

from __future__ import annotations

import dataclasses
import fcntl
import json
import multiprocessing
import os
import unittest
from unittest.mock import patch

from _active_fence_fixture import ActiveFenceFixture
from _common import pl  # noqa: F401
from headless.active_fence_lock import (
    ActiveFenceLockError,
    locked_publish_mutex_v1,
    validate_active_fence_lock_v1,
)
from headless.active_fence_protocol import (
    reserve_active_generation_fence_v1,
)
from headless.active_fence_types import (
    ActiveFenceConflictError,
    ActiveFenceError,
)


def _fork_validate(lock: object, output: object) -> None:
    try:
        validate_active_fence_lock_v1(lock)
    except ActiveFenceLockError:
        output.send("rejected")
    else:
        output.send("accepted")
    output.close()


def _reserve_worker(
    root: str, authority: str, attempt: str, output: object
) -> None:
    try:
        result = reserve_active_generation_fence_v1(root, authority, attempt)
        output.put(("reserved", result.state.active_attempt_id))
    except ActiveFenceConflictError:
        output.put(("conflict", attempt))
    except Exception as exc:  # pragma: no cover - reported in parent
        output.put((type(exc).__name__, attempt))


def _canonical(value: dict) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("ascii")


class ActiveFenceAdversarialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ActiveFenceFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_forged_stale_and_fork_inherited_witnesses_fail(self) -> None:
        context = multiprocessing.get_context("fork")
        stale = None
        with locked_publish_mutex_v1(self.fixture.root) as lock:
            with self.assertRaises(ActiveFenceLockError):
                validate_active_fence_lock_v1(dataclasses.replace(lock))
            receiver, sender = context.Pipe(duplex=False)
            process = context.Process(
                target=_fork_validate, args=(lock, sender)
            )
            process.start()
            self.assertEqual(receiver.recv(), "rejected")
            process.join(5)
            self.assertEqual(process.exitcode, 0)
            stale = lock
        with self.assertRaises(ActiveFenceLockError):
            validate_active_fence_lock_v1(stale)

    def test_explicit_unlock_and_named_inode_replacement_fail(self) -> None:
        with self.assertRaises(ActiveFenceLockError):
            with locked_publish_mutex_v1(self.fixture.root) as lock:
                fcntl.flock(lock.lock_fd, fcntl.LOCK_UN)
                validate_active_fence_lock_v1(lock)
        with self.assertRaises(ActiveFenceLockError):
            with locked_publish_mutex_v1(self.fixture.root) as lock:
                os.unlink(self.fixture.lock_path)
                with open(self.fixture.lock_path, "wb"):
                    pass
                os.chmod(self.fixture.lock_path, 0o600)
                validate_active_fence_lock_v1(lock)

    def test_root_path_replacement_fails_before_success(self) -> None:
        moved = os.path.join(self.fixture.temporary.name, "moved")
        with self.assertRaises(ActiveFenceLockError):
            with locked_publish_mutex_v1(self.fixture.root) as lock:
                os.rename(self.fixture.root, moved)
                os.mkdir(self.fixture.root, 0o700)
                os.chmod(self.fixture.root, 0o700)
                validate_active_fence_lock_v1(lock)

    def test_concurrent_distinct_reserves_have_one_winner(self) -> None:
        self.fixture.bootstrap()
        context = multiprocessing.get_context("fork")
        output = context.Queue()
        processes = [
            context.Process(
                target=_reserve_worker,
                args=(
                    self.fixture.root,
                    self.fixture.authority_id,
                    attempt,
                    output,
                ),
            )
            for attempt in (self.fixture.attempt_a, self.fixture.attempt_b)
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join(5)
            self.assertEqual(process.exitcode, 0)
        results = [output.get(timeout=2) for _ in processes]
        self.assertEqual(
            {item[0] for item in results}, {"reserved", "conflict"}
        )
        winner = next(item[1] for item in results if item[0] == "reserved")
        self.assertEqual(
            json.loads(self.fixture.fence_bytes())["activeAttemptId"], winner
        )

    def test_journal_symlink_fifo_and_hardlink_fail_closed(self) -> None:
        for kind in ("symlink", "fifo", "hardlink"):
            with self.subTest(kind=kind):
                fixture = ActiveFenceFixture()
                self.addCleanup(fixture.close)
                fixture.bootstrap()
                original = fixture.journal_path + ".original"
                os.rename(fixture.journal_path, original)
                if kind == "symlink":
                    os.symlink(
                        os.path.basename(original), fixture.journal_path
                    )
                elif kind == "fifo":
                    os.mkfifo(fixture.journal_path, 0o600)
                else:
                    os.link(original, fixture.journal_path)
                with self.assertRaises(ActiveFenceError):
                    fixture.reserve()

    def test_fence_symlink_fifo_and_noncanonical_bytes_fail_closed(
        self,
    ) -> None:
        for kind in ("symlink", "fifo", "bytes"):
            with self.subTest(kind=kind):
                fixture = ActiveFenceFixture()
                self.addCleanup(fixture.close)
                fixture.bootstrap()
                os.unlink(fixture.fence_path)
                if kind == "symlink":
                    os.symlink("authority.json", fixture.fence_path)
                elif kind == "fifo":
                    os.mkfifo(fixture.fence_path, 0o600)
                else:
                    with open(fixture.fence_path, "wb") as output:
                        output.write(b"{}")
                    os.chmod(fixture.fence_path, 0o600)
                with self.assertRaises(ActiveFenceError):
                    fixture.bootstrap()

    def test_forged_valid_fence_not_in_journal_fails(self) -> None:
        result = self.fixture.bootstrap()
        row = json.loads(result.state.document_json)
        row["fenceRevision"] = 999
        with open(self.fixture.fence_path, "wb") as output:
            output.write(_canonical(row))
        os.chmod(self.fixture.fence_path, 0o600)
        before = self.fixture.journal_bytes()
        with self.assertRaises(ActiveFenceError):
            self.fixture.reserve()
        self.assertEqual(before, self.fixture.journal_bytes())

    def test_stale_inactive_prefix_recovers_to_explicit_active_tail(
        self,
    ) -> None:
        bootstrap = self.fixture.bootstrap()
        active = self.fixture.reserve()
        with open(self.fixture.fence_path, "wb") as output:
            output.write(bootstrap.state.document_json)
        os.chmod(self.fixture.fence_path, 0o600)
        replay = self.fixture.reserve()
        self.assertEqual(replay.state, active.state)
        self.assertEqual(
            self.fixture.fence_bytes(), active.state.document_json
        )

    def test_reordered_or_mutated_complete_journal_fails(self) -> None:
        for attack in ("reverse", "mutate"):
            with self.subTest(attack=attack):
                fixture = ActiveFenceFixture()
                self.addCleanup(fixture.close)
                fixture.bootstrap()
                fixture.reserve()
                lines = fixture.journal_bytes().splitlines()
                raw = b"\n".join(reversed(lines)) + b"\n"
                if attack == "mutate":
                    raw = fixture.journal_bytes().replace(
                        b'"frameVersion":1', b'"frameVersion":2', 1
                    )
                with open(fixture.journal_path, "wb") as output:
                    output.write(raw)
                os.chmod(fixture.journal_path, 0o600)
                with self.assertRaises(ActiveFenceError):
                    fixture.bootstrap()

    def test_pending_projection_with_current_fence_is_impossible(self) -> None:
        self.fixture.bootstrap()
        pending = os.path.join(self.fixture.root, ".FENCE.pending")
        with open(pending, "wb") as output:
            output.write(self.fixture.fence_bytes())
        os.chmod(pending, 0o600)
        with self.assertRaises(ActiveFenceError):
            self.fixture.bootstrap()

    def test_reused_fence_token_fails_without_transition(self) -> None:
        bootstrap = self.fixture.bootstrap()
        before = self.fixture.journal_bytes()
        with patch(
            "headless.active_fence_protocol._new_token",
            return_value=bootstrap.state.fence_token,
        ), self.assertRaises(ActiveFenceError):
            self.fixture.reserve()
        self.assertEqual(before, self.fixture.journal_bytes())


if __name__ == "__main__":
    unittest.main(verbosity=2)
