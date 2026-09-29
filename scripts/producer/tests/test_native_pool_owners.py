"""Real NativeRun owners in separate supervisor processes share one TEST pool.

Each owner runs the production admission, resource sampling, guard, cleanup and lease
code over a synthetic child (64 MiB resident, one grandchild, bounded sleep). The pool
namespace and host qualification are TEST fixtures, never the host's canonical pool.
Requires the real host to admit native work (normal pressure, >=25% free memory).
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

import native_work_lease as work
import native_work_recovery as recovery
from native_render_resources import GIB
from _native_pool_fixture import isolate_pool, members, qualify_fixture_host

PRODUCER = Path(__file__).resolve().parents[1]
DRIVER = PRODUCER / 'tests/fixtures/native_pool_driver.py'


def epoch(value: str) -> float:
    """Receipt UTC timestamps as epoch seconds."""
    return datetime.fromisoformat(value).timestamp()


class PoolOwnerConcurrencyTests(unittest.TestCase):
    """Three heavy slots and one audio slot on a TEST-qualified 64 GiB fixture host."""

    def setUp(self) -> None:
        """Isolate the namespace and TEST record for this process and every driver."""
        self.root = isolate_pool(self)
        self.record = qualify_fixture_host(self, {'heavy': 3, 'audio': 1})
        temporary = tempfile.TemporaryDirectory(prefix='native-pool-owners-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()

    def start(self, name: str, lane: str, seconds: float) -> tuple[subprocess.Popen, Path]:
        """Launch one supervisor process running a real owner in a fresh attempt folder."""
        attempt = self.base / name
        attempt.mkdir()
        process = subprocess.Popen([sys.executable, '-B', str(DRIVER), 'owner', str(self.root),
                                    str(self.record), lane, str(attempt), str(seconds)],
                                   stdout=subprocess.DEVNULL, cwd=PRODUCER)
        self.addCleanup(self.stop, process)
        return process, attempt

    def stop(self, process: subprocess.Popen) -> None:
        """Kill and reap a supervisor that is still running."""
        if process.poll() is None:
            process.kill()
        process.wait(timeout=30)

    def receipt(self, attempt: Path, lane: str) -> dict:
        """Read the owner's durable receipt (atomically replaced by the owner)."""
        path = attempt / f'TEST-{lane}.render.json'
        return json.loads(path.read_text()) if path.exists() else {}

    def wait_for(self, attempt: Path, lane: str, predicate: object, timeout: float = 90) -> dict:
        """Poll the receipt until a condition holds; fail with the last receipt otherwise."""
        deadline = time.monotonic() + timeout
        value = {}
        while time.monotonic() < deadline:
            value = self.receipt(attempt, lane)
            if value and predicate(value):
                return value
            time.sleep(.1)
        self.fail(f'owner {attempt.name} never reached the condition: {value.get("status")}')

    def test_real_owners_overlap_and_queue_in_fifo_order(self) -> None:
        """Three heavy and one audio owner run together; later heavy owners queue in order."""
        running = [self.start(f'heavy-{index}', 'heavy', 8) for index in range(3)]
        running.append(self.start('audio-0', 'audio', 8))
        states = [self.wait_for(attempt, lane, lambda row: row.get('status') == 'running')
                  for (_process, attempt), lane in zip(running, ('heavy',) * 3 + ('audio',))]
        self.assertFalse(any(row.get('completedAt') for row in states))
        later = []
        for index in (3, 4):
            later.append(self.start(f'heavy-{index}', 'heavy', 1))
            self.wait_for(later[-1][1], 'heavy', lambda row: row.get('status') == 'waiting-for-capacity')
        for process, _attempt in running + later:
            self.assertEqual(process.wait(timeout=120), 0)
        receipts = [self.receipt(attempt, lane) for (_p, attempt), lane
                    in zip(running + later, ('heavy',) * 3 + ('audio',) + ('heavy',) * 2)]
        for row in receipts:
            self.assertEqual((row['status'], row.get('leaseCleanupVerified')), ('TEST synthetic owner complete', True),
                             (row.get('abortReason'), row.get('leaseCleanupReason'), row.get('failureCategory')))
            self.assertEqual(row['pool']['mode'], 'qualified')
        self.assertEqual([row['policy']['maximum_owned_gib'] for row in receipts], [6, 6, 6, 1, 6, 6])
        fourth, fifth = receipts[4], receipts[5]
        self.assertLess(fourth['queue']['ticket'], fifth['queue']['ticket'])
        self.assertLess(fourth['pool']['admittedAtEpoch'], fifth['pool']['admittedAtEpoch'])
        self.assertGreater(fourth['queueSeconds'], .5)
        first_done = min(epoch(row['completedAt']) for row in receipts[:3])
        self.assertGreaterEqual(fourth['pool']['admittedAtEpoch'], first_done - 1)
        self.assertEqual(members(self.root), [])

    def test_killed_owner_keeps_quarantine_until_child_absence_is_proved(self) -> None:
        """A SIGKILLed supervisor's child survives; its slot and 6 GiB stay charged meanwhile."""
        process, attempt = self.start('heavy-killed', 'heavy', 120)
        state = self.wait_for(attempt, 'heavy', lambda row: row.get('status') == 'running'
                              and len(row.get('ownerIdentities', [])) >= 1)
        child = state['pid']
        self.addCleanup(self._kill_group, child)
        process.send_signal(signal.SIGKILL)
        process.wait(timeout=30)
        other, other_attempt = self.start('heavy-other', 'heavy', 1)
        self.assertEqual(other.wait(timeout=120), 0)
        charged = self.receipt(other_attempt, 'heavy')['pool']['quarantinedChargedBytes']
        self.assertEqual(charged, 6 * GIB)
        nonce = state['pool']['member']
        with self.assertRaisesRegex(work.NativeWorkBusy, 'children are still alive'):
            recovery.recover(nonce)
        self._kill_group(child)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                self.assertEqual(recovery.recover(nonce)['kind'], 'pool-member')
                break
            except work.NativeWorkBusy:
                time.sleep(.2)
        self.assertEqual(members(self.root), [])

    @staticmethod
    def _kill_group(pid: int) -> None:
        """Kill a surviving TEST child's own process group; absence is fine."""
        try:
            os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


if __name__ == '__main__':
    unittest.main()
