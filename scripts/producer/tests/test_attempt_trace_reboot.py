"""Cross-reboot invariants for the crash-safe attempt trace."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PRODUCER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PRODUCER_DIR))

from headless.attempt_trace import (  # noqa: E402
    TRACE_NAME,
    AttemptTrace,
    TraceContext,
    TraceCorruption,
)
from headless.trace_state import TERMINAL_DISPOSITIONS  # noqa: E402


def _context(boot_id: str) -> TraceContext:
    return TraceContext(
        unit_id="unit-reboot", attempt_id="attempt-reboot",
        release_id="release-test", build_id="build-test", boot_id=boot_id,
        policy_id="policy-test", expected_parent="generation-0:commit-0:sequence-0",
        request_digest=hashlib.sha256(b"reboot-request").hexdigest(),
        authority_id="authority-mp4-v1",
    )


class AttemptTraceRebootTests(unittest.TestCase):
    """A reboot cannot strand a trace or silently reset its monotonic clock."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.attempt_dir = os.path.join(self.temp.name, "attempt")
        os.mkdir(self.attempt_dir, 0o700)
        self.boot_a = AttemptTrace(self.attempt_dir, _context("boot-a"))
        self.boot_b = AttemptTrace(self.attempt_dir, _context("boot-b"))

    def _events(self) -> list[dict]:
        path = os.path.join(self.attempt_dir, TRACE_NAME)
        with open(path, encoding="utf-8") as handle:
            return [json.loads(line)["payload"] for line in handle]

    def test_typed_recovery_allows_new_boot_then_normal_events(self) -> None:
        self.boot_a.append("ADMITTED")
        self.boot_b.append("RECOVERY_RESUMED", {"reasonCode": "HOST_REBOOT"})
        self.boot_b.append("TERMINAL_SEALED", {
            "disposition": "FAILED", "resultDigest": "d" * 64})
        self.assertEqual(self.boot_a.validate().record_count, 3)
        payloads = self._events()
        self.assertEqual([item["bootId"] for item in payloads],
                         ["boot-a", "boot-b", "boot-b"])

    def test_ordinary_cross_boot_append_is_rejected_without_mutation(self) -> None:
        self.boot_a.append("ADMITTED")
        before = Path(os.path.join(self.attempt_dir, TRACE_NAME)).read_bytes()
        with self.assertRaisesRegex(TraceCorruption, "boot transition"):
            self.boot_b.append("STAGE_END")
        self.assertEqual(Path(os.path.join(
            self.attempt_dir, TRACE_NAME)).read_bytes(), before)

    def test_direct_cross_boot_terminal_is_an_explicit_recovery_boundary(self) -> None:
        self.boot_a.append("ADMITTED")
        self.boot_b.append("TERMINAL_SEALED", {
            "disposition": "FAILED", "resultDigest": "d" * 64})
        self.assertEqual(self.boot_a.validate().record_count, 2)

    def test_same_boot_monotonic_rollback_is_rejected(self) -> None:
        with mock.patch("headless.attempt_trace.time.monotonic_ns",
                        return_value=100):
            self.boot_a.append("ADMITTED")
        with mock.patch("headless.attempt_trace.time.monotonic_ns",
                        return_value=99):
            with self.assertRaisesRegex(TraceCorruption, "moved backward"):
                self.boot_a.append("STAGE_END")

    def test_boot_identity_cannot_bounce_back(self) -> None:
        self.boot_a.append("ADMITTED")
        self.boot_b.append("RECOVERY_RESUMED", {"reasonCode": "HOST_REBOOT"})
        with self.assertRaisesRegex(TraceCorruption, "cannot recur"):
            self.boot_a.append("RECOVERY_RESUMED", {"reasonCode": "HOST_REBOOT"})

    def test_terminal_is_closed_and_absorbing(self) -> None:
        self.boot_a.append("ADMITTED")
        with self.assertRaisesRegex(TraceCorruption, "invalid disposition"):
            self.boot_a.append("TERMINAL_SEALED", {})
        self.boot_a.append("TERMINAL_SEALED", {
            "disposition": "FAILED", "resultDigest": "d" * 64})
        with self.assertRaisesRegex(TraceCorruption, "absorbing"):
            self.boot_a.append("STAGE_END")
        state = self.boot_a.validate()
        self.assertEqual(state.last_event, "TERMINAL_SEALED")
        self.assertEqual(state.terminal_disposition, "FAILED")

    def test_terminal_dispositions_match_the_controller_contract(self) -> None:
        expected = {"BLOCKED", "CANCELED", "FAILED", "STALE", "SUCCEEDED"}
        self.assertEqual(TERMINAL_DISPOSITIONS, expected)
        for disposition in sorted(expected):
            with self.subTest(accepted=disposition):
                attempt_dir = os.path.join(self.temp.name, disposition.lower())
                os.mkdir(attempt_dir, 0o700)
                trace = AttemptTrace(attempt_dir, _context("boot-a"))
                trace.append("ADMITTED")
                if disposition == "SUCCEEDED":
                    trace.append("WORKER_START")
                    trace.append("VERIFIED")
                    trace.append("PUBLISH_INTENT")
                    trace.append("POINTER_COMMITTED")
                trace.append("TERMINAL_SEALED", {
                    "disposition": disposition, "resultDigest": "d" * 64})
                expected_count = 6 if disposition == "SUCCEEDED" else 2
                self.assertEqual(trace.validate().record_count, expected_count)
        for legacy in ("CANCELLED", "SUPERSEDED"):
            with self.subTest(rejected=legacy):
                attempt_dir = os.path.join(self.temp.name, legacy.lower())
                os.mkdir(attempt_dir, 0o700)
                trace = AttemptTrace(attempt_dir, _context("boot-a"))
                trace.append("ADMITTED")
                with self.assertRaisesRegex(TraceCorruption, "invalid disposition"):
                    trace.append("TERMINAL_SEALED", {
                        "disposition": legacy, "resultDigest": "d" * 64})

    def test_success_requires_the_complete_publish_sequence(self) -> None:
        self.boot_a.append("ADMITTED")
        with self.assertRaisesRegex(TraceCorruption, "committed pointer"):
            self.boot_a.append("TERMINAL_SEALED", {
                "disposition": "SUCCEEDED", "resultDigest": "d" * 64})
        self.boot_a.append("WORKER_START")
        self.boot_a.append("VERIFIED")
        self.boot_a.append("PUBLISH_INTENT")
        self.boot_a.append("POINTER_COMMITTED")
        self.boot_a.append("TERMINAL_SEALED", {
            "disposition": "SUCCEEDED", "resultDigest": "d" * 64})
        self.assertEqual(self.boot_a.validate().record_count, 6)

    def test_phase_order_and_initial_admission_are_closed(self) -> None:
        fresh_dir = os.path.join(self.temp.name, "fresh")
        os.mkdir(fresh_dir, 0o700)
        fresh = AttemptTrace(fresh_dir, _context("boot-a"))
        with self.assertRaisesRegex(TraceCorruption, "first trace event"):
            fresh.append("POINTER_COMMITTED")
        fresh.append("ADMITTED")
        with self.assertRaisesRegex(TraceCorruption, "invalid after ADMITTED"):
            fresh.append("POINTER_COMMITTED")
        fresh.append("WORKER_START")
        fresh.append("VERIFIED")
        fresh.append("PUBLISH_INTENT")
        fresh.append("POINTER_COMMITTED")
        with self.assertRaisesRegex(TraceCorruption, "invalid after POINTER_COMMITTED"):
            fresh.append("WORKER_START")
        fresh.append("TERMINAL_SEALED", {
            "disposition": "SUCCEEDED", "resultDigest": "d" * 64})

    def test_duplicate_admission_and_recovery_before_admission_fail(self) -> None:
        fresh_dir = os.path.join(self.temp.name, "empty-recovery")
        os.mkdir(fresh_dir, 0o700)
        fresh = AttemptTrace(fresh_dir, _context("boot-a"))
        with self.assertRaisesRegex(TraceCorruption, "recovery requires"):
            fresh.append("RECOVERY_RESUMED", {"reasonCode": "PROCESS_CRASH"})
        fresh.append("ADMITTED")
        with self.assertRaisesRegex(TraceCorruption, "invalid after ADMITTED"):
            fresh.append("ADMITTED")

    def test_ordinary_event_cannot_repair_a_torn_tail(self) -> None:
        self.boot_a.append("ADMITTED")
        path = os.path.join(self.attempt_dir, TRACE_NAME)
        with open(path, "ab") as handle:
            handle.write(b'{"partial":')
            handle.flush()
            os.fsync(handle.fileno())
        before = Path(path).read_bytes()
        with self.assertRaisesRegex(TraceCorruption, "torn-tail repair"):
            self.boot_a.append("STAGE_END", {}, True)
        self.assertEqual(Path(path).read_bytes(), before)
        self.boot_a.append("RECOVERY_RESUMED", {"reasonCode": "TORN_TAIL"}, True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
