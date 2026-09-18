from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest

from headless.attempt_trace import LOCK_NAME, AttemptTrace, TornTraceTail
from test_attempt_trace import PRODUCER_DIR, _context, _frames

_CHILD_APPEND = """
import sys, time
sys.path.insert(0, sys.argv[1])
from headless.attempt_trace import AttemptTrace, TraceContext
context = TraceContext("unit-001", "attempt-001", "release-test", "build-test",
                       "boot-test-stable-001", "policy-test",
                       "generation-0:commit-0:sequence-0",
                       "{request_digest}", "authority-mp4-v1")
trace = AttemptTrace(sys.argv[2], context)
time.sleep(max(0.0, float(sys.argv[3]) - time.time()))
trace.append("{event}", {{"childIndex": int(sys.argv[4])}})
print("DURABLE", flush=True)
time.sleep(float(sys.argv[5]))
"""

_CHILD_TORN_WRITE = """
import fcntl, os, sys, time
lock_fd = os.open(os.path.join(sys.argv[1], ".trace.lock"), os.O_RDWR)
fcntl.flock(lock_fd, fcntl.LOCK_EX)
trace_fd = os.open(os.path.join(sys.argv[1], "trace.jsonl"),
                   os.O_WRONLY | os.O_APPEND)
os.write(trace_fd, b'{"incompleteCrashFrame":')
os.fsync(trace_fd)
print("TORN_DURABLE", flush=True)
time.sleep(30)
"""


class AttemptTraceProcessTests(unittest.TestCase):
    """Kernel-lock serialization and forced-process-death behavior."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.attempt_dir = os.path.join(self.temp.name, "attempt")
        os.mkdir(self.attempt_dir, 0o700)
        self.trace = AttemptTrace(self.attempt_dir, _context())

    def _child_script(self, event: str) -> str:
        return _CHILD_APPEND.format(
            request_digest=_context().request_digest, event=event
        )

    def test_admission_survives_forced_kill_after_durable_append(self) -> None:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-c",
                self._child_script("ADMITTED"),
                str(PRODUCER_DIR),
                self.attempt_dir,
                "0",
                "7",
                "30",
            ],
            stdout=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        self.assertEqual(proc.stdout.readline().strip(), "DURABLE")
        proc.kill()
        proc.communicate(timeout=5)
        self.assertEqual(self.trace.validate().record_count, 1)
        frame = _frames(self.attempt_dir)[0]
        self.assertEqual(frame["payload"]["event"], "ADMITTED")
        self.assertNotIn("TERMINAL_SEALED", frame["payload"]["event"])

    def test_killed_lock_holder_leaves_only_a_recoverable_final_tail(self) -> None:
        self.trace.append("ADMITTED")
        proc = subprocess.Popen(
            [sys.executable, "-c", _CHILD_TORN_WRITE, self.attempt_dir],
            stdout=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        self.assertEqual(proc.stdout.readline().strip(), "TORN_DURABLE")
        proc.kill()
        proc.communicate(timeout=5)

        with self.assertRaises(TornTraceTail):
            self.trace.validate()
        result = self.trace.append(
            "TERMINAL_SEALED", {"disposition": "FAILED", "resultDigest": "d" * 64}, True
        )
        self.assertGreater(result.recovered_tail_bytes, 0)
        self.assertEqual(self.trace.validate().record_count, 2)
        self.assertTrue(os.path.exists(os.path.join(self.attempt_dir, LOCK_NAME)))

    def test_concurrent_writers_form_one_monotonic_chain(self) -> None:
        self.trace.append("ADMITTED")
        deadline = time.time() + 0.4
        script = self._child_script("STAGE_END")
        processes = [
            subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    script,
                    str(PRODUCER_DIR),
                    self.attempt_dir,
                    str(deadline),
                    str(index),
                    "0",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for index in range(16)
        ]
        outputs = [proc.communicate(timeout=10) for proc in processes]
        self.assertTrue(all(proc.returncode == 0 for proc in processes), outputs)
        state = self.trace.validate()
        self.assertEqual((state.record_count, state.last_sequence), (17, 17))
        frames = _frames(self.attempt_dir)
        self.assertEqual([frame["sequence"] for frame in frames], list(range(1, 18)))
        children = frames[1:]
        self.assertEqual(
            len({frame["payload"]["details"]["childIndex"] for frame in children}), 16
        )
        for previous, current in zip(frames, frames[1:]):
            self.assertEqual(current["priorDigest"], previous["eventDigest"])
