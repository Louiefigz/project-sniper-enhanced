"""Cross-process contracts for Palmier's sync-on-demand lock."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

PRODUCER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PRODUCER_DIR)

from palmier.sync_lock import (  # noqa: E402
    DIR_LOCK_NAME,
    PENDING_NAME,
    SyncLock,
    SyncLockState,
    SyncWaitReason,
)


ATTEMPT = """
import json, sys
sys.path.insert(0, sys.argv[1])
from palmier.sync_lock import SyncLock
r = SyncLock.acquire(sys.argv[2], sys.argv[3], sys.argv[4])
print(json.dumps({"state": r.state.value,
                  "reason": r.reason.value if r.reason else None,
                  "holderPid": r.holder_pid}), flush=True)
if r.lease:
    r.lease.release()
"""

NO_QUEUE_ATTEMPT = ATTEMPT.replace(
    "SyncLock.acquire(sys.argv[2], sys.argv[3], sys.argv[4])",
    "SyncLock.acquire(sys.argv[2], sys.argv[3], sys.argv[4], False)")


def _attempt(out_dir: str, plan_hash: str, global_path: str) -> dict:
    """Run one acquisition in a separate process and return its result."""
    proc = subprocess.run(
        [sys.executable, "-c", ATTEMPT, PRODUCER_DIR, out_dir, plan_hash,
         global_path], capture_output=True, text=True, check=True)
    return json.loads(proc.stdout)


def _attempt_without_queue(out_dir: str, plan_hash: str,
                           global_path: str) -> dict:
    proc = subprocess.run(
        [sys.executable, "-c", NO_QUEUE_ATTEMPT, PRODUCER_DIR, out_dir,
         plan_hash, global_path], capture_output=True, text=True, check=True)
    return json.loads(proc.stdout)


class SyncLockTests(unittest.TestCase):
    """Kernel-lock, queue, wait, and crash-recovery behavior."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out_a = os.path.join(self.temp.name, "a")
        self.out_b = os.path.join(self.temp.name, "b")
        os.mkdir(self.out_a)
        os.mkdir(self.out_b)
        self.global_path = os.path.join(self.temp.name, "global.lock")
        self.leases: list[SyncLock] = []
        self.addCleanup(self._release_all)

    def _acquire(self, out_dir: str, plan_hash: str) -> SyncLock:
        result = SyncLock.acquire(out_dir, plan_hash, self.global_path)
        self.assertIs(result.state, SyncLockState.ACQUIRED)
        self.assertIsNotNone(result.lease)
        self.leases.append(result.lease)
        return result.lease

    def _release_all(self) -> None:
        for lease in self.leases:
            lease.release()

    def test_same_dir_queue_is_one_slot_and_latest_wins(self) -> None:
        lease = self._acquire(self.out_a, "hash-1")
        first = _attempt(self.out_a, "hash-2", self.global_path)
        latest = _attempt(self.out_a, "hash-3", self.global_path)
        self.assertEqual(first["state"], "queued")
        self.assertEqual(latest["state"], "queued")
        with open(os.path.join(self.out_a, PENDING_NAME)) as handle:
            self.assertEqual(json.load(handle)["planHash"], "hash-3")
        self.assertEqual(lease.claim_pending(), "hash-3")
        self.assertEqual(
            _attempt(self.out_a, "hash-4", self.global_path)["state"],
            "queued")
        self.assertEqual(lease.claim_pending(), "hash-4")
        self.assertIsNone(lease.claim_pending())
        self.assertFalse(os.path.exists(os.path.join(self.out_a, PENDING_NAME)))

    def test_global_lock_makes_a_different_dir_wait(self) -> None:
        self._acquire(self.out_a, "hash-a")
        result = _attempt(self.out_b, "hash-b", self.global_path)
        self.assertEqual(result["state"], SyncLockState.WAITING.value)
        self.assertEqual(result["reason"], SyncWaitReason.PALMIER_BUSY.value)
        self.assertFalse(os.path.exists(os.path.join(self.out_b, PENDING_NAME)))

    def test_non_mirror_contender_waits_without_entering_mirror_queue(self) -> None:
        self._acquire(self.out_a, "mirror-hash")
        result = _attempt_without_queue(
            self.out_a, "native-request-hash", self.global_path)
        self.assertEqual(result["state"], SyncLockState.WAITING.value)
        self.assertEqual(result["reason"], SyncWaitReason.PALMIER_BUSY.value)
        self.assertFalse(os.path.exists(os.path.join(self.out_a, PENDING_NAME)))

    def test_live_assemble_returns_waiting_without_touching_marker(self) -> None:
        marker = os.path.join(self.out_a, ".assemble.lock")
        record = {"pid": os.getpid(), "startedAt": "kept-exactly"}
        with open(marker, "w") as handle:
            json.dump(record, handle)
        result = SyncLock.acquire(self.out_a, "hash-a", self.global_path)
        self.assertIs(result.state, SyncLockState.WAITING)
        self.assertIs(result.reason, SyncWaitReason.ASSEMBLE_ACTIVE)
        self.assertEqual(result.holder_pid, os.getpid())
        with open(marker) as handle:
            self.assertEqual(json.load(handle), record)

    def test_dead_assemble_marker_does_not_wedge_or_get_deleted(self) -> None:
        dead = subprocess.run([sys.executable, "-c", "pass"]).returncode
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        self.assertEqual(dead, 0)
        marker = os.path.join(self.out_a, ".assemble.lock")
        with open(marker, "w") as handle:
            json.dump({"pid": proc.pid}, handle)
        self._acquire(self.out_a, "hash-a")
        self.assertTrue(os.path.exists(marker))

    def test_kernel_recovers_after_holder_process_dies(self) -> None:
        script = ATTEMPT.replace(
            "if r.lease:\n    r.lease.release()",
            "if r.lease:\n    import os; os._exit(0)")
        proc = subprocess.run(
            [sys.executable, "-c", script, PRODUCER_DIR, self.out_a,
             "crashed", self.global_path], capture_output=True, text=True,
            check=True)
        self.assertEqual(json.loads(proc.stdout)["state"], "acquired")
        lease = self._acquire(self.out_a, "recovered")
        lease.release()
        self.assertTrue(os.path.exists(os.path.join(self.out_a, DIR_LOCK_NAME)))
        self.assertTrue(os.path.exists(self.global_path))

    def test_fork_child_cannot_release_parent_lease(self) -> None:
        lease = self._acquire(self.out_a, "parent")
        pid = os.fork()
        if pid == 0:
            try:
                lease.release()
            except RuntimeError:
                os._exit(0)
            os._exit(1)
        _pid, status = os.waitpid(pid, 0)
        self.assertEqual(os.waitstatus_to_exitcode(status), 0)
        result = _attempt(self.out_a, "still-locked", self.global_path)
        self.assertEqual(result["state"], SyncLockState.QUEUED.value)
        self.assertEqual(lease.claim_pending(), "still-locked")
        lease.claim_pending()

    def test_queue_check_and_release_have_no_lost_wakeup(self) -> None:
        for index in range(8):
            lease = self._acquire(self.out_a, f"owner-{index}")
            deadline = time.time() + 0.08
            script = "import time,sys;time.sleep(max(0,float(sys.argv[5])-time.time()));" + ATTEMPT
            proc = subprocess.Popen(
                [sys.executable, "-c", script, PRODUCER_DIR, self.out_a,
                 f"next-{index}", self.global_path, str(deadline)],
                stdout=subprocess.PIPE, text=True)
            time.sleep(max(0, deadline - time.time()))
            claimed = lease.claim_pending()
            child = json.loads(proc.communicate(timeout=5)[0])
            valid = ((claimed == f"next-{index}" and child["state"] == "queued")
                     or (claimed is None and child["state"] == "acquired"))
            self.assertTrue(valid, (claimed, child))
            if claimed is not None:
                lease.claim_pending()


if __name__ == "__main__":
    unittest.main(verbosity=2)
