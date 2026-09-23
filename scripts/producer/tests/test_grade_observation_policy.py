"""Host lifecycle and evidence-reader fault injection; no actual worker proof."""
from __future__ import annotations

import hashlib
import os
import signal
import threading
import tempfile
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from color.grade_observation_read import _lines
from headless import grade_observation_policy as policy

SHA = "a" * 64
REQUEST = {"sourceSha256": SHA, "frameCount": 180, "timeoutSeconds": 120}


class GradeObservationRequestTests(unittest.TestCase):
    """Request data cannot choose paths/binaries, work ceilings or stale outputs."""

    def test_closed_request_and_limits_before_attempt_write(self) -> None:
        changes = [("frameCount", True), ("frameCount", 0), ("frameCount", 1_296_001),
                   ("timeoutSeconds", 121), ("timeoutSeconds", 29), ("sourceSha256", "../source"),
                   ("binary", "/arbitrary/tool")]
        for key, value in changes:
            with self.subTest(key=key), self.assertRaises(ValueError):
                policy._request({**REQUEST, key: value})

    def test_existing_or_public_attempt_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "human-note").write_text("retain")
            with self.assertRaisesRegex(RuntimeError, "empty private"):
                policy._directory(root)
            self.assertEqual((root / "human-note").read_text(), "retain")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            root.chmod(0o755)
            with self.assertRaisesRegex(RuntimeError, "empty private"):
                policy._directory(root)

    def test_prelaunch_failure_can_prove_no_owned_worker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "source.media"
            source.write_bytes(b"synthetic")
            attempt = root / "attempt"
            attempt.mkdir(mode=0o700)
            with patch.object(policy, "_execute", side_effect=RuntimeError("before launch")):
                with self.assertRaises(policy.GradeIsolationError) as raised:
                    policy.run_isolated_grade(str(source), REQUEST, attempt)
            self.assertTrue(raised.exception.cleanup_verified)
            self.assertEqual(raised.exception.evidence["status"], "failed")
            self.assertTrue((attempt / "execution.json").exists())
            self.assertEqual(source.read_bytes(), b"synthetic")

    def test_unproved_cleanup_stays_uncertain_in_retained_failure(self) -> None:
        def fail(_source, _request, _directory, evidence):
            evidence["launchAttempted"] = True
            raise RuntimeError("removal observation unavailable")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "source.media"
            source.write_bytes(b"synthetic")
            attempt = root / "attempt"
            attempt.mkdir(mode=0o700)
            with patch.object(policy, "_execute", side_effect=fail):
                with self.assertRaises(policy.GradeIsolationError) as raised:
                    policy.run_isolated_grade(str(source), REQUEST, attempt)
            self.assertFalse(raised.exception.cleanup_verified)
            self.assertFalse(raised.exception.evidence["gradeApplicable"])

    def test_external_deadline_can_only_shorten_the_existing_invocation_ceiling(self) -> None:
        for seconds in (40, 300):
            with self.subTest(seconds=seconds), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                source = root / "source.media"
                source.write_bytes(b"inert")
                attempt = root / "attempt"
                attempt.mkdir(mode=0o700)
                before = time.monotonic()
                captured = []
                def execute(_source, _request, _directory, evidence):
                    captured.append(int(evidence["workDeadlineMonotonicNs"]) / 1_000_000_000)
                    evidence["cleanupVerified"] = True
                with patch.object(policy, "_execute", side_effect=execute):
                    policy.run_isolated_grade(str(source), REQUEST, attempt, before + seconds)
                self.assertLessEqual(captured[0], before + min(seconds, 120) + .01)
                self.assertGreater(captured[0], before + min(seconds, 120) - .01)

    def test_already_expired_external_clock_does_not_probe_runtime_or_launch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "source.media"
            source.write_bytes(b"inert")
            attempt = root / "attempt"
            attempt.mkdir(mode=0o700)
            with patch.object(policy, "required_runtime") as runtime, self.assertRaises(policy.GradeIsolationError) as raised:
                policy.run_isolated_grade(str(source), REQUEST, attempt, time.monotonic() - 1)
            runtime.assert_not_called()
            self.assertTrue(raised.exception.cleanup_verified)


class GradeObservationCleanupTests(unittest.TestCase):
    """Readback of exact absence is required even after a nominal remove result."""

    def execute(self, overrides: dict) -> tuple[dict, dict]:
        defaults = {"required_runtime": object(), "_launch_command": (["fixed"], SHA),
            "implementation_sources": [], "file_hash": SHA,
            "attest_image": {"Id": "sha256:" + SHA}, "_launch": "b" * 64,
            "attest_probe_container": {}, "probe_container": {},
            "_wait": {"status": "complete", "request": REQUEST, "policy": policy.POLICY},
            "remove_container": {"canonicalAbsenceProved": True}, "reconcile_launch_abort": None}
        defaults.update(overrides)
        evidence = {"launchAttempted": False, "cleanupVerified": False,
                    "workDeadlineMonotonicNs": str(time.monotonic_ns() + 120_000_000_000)}
        with ExitStack() as stack:
            mocks = {}
            for name, value in defaults.items():
                options = {"side_effect": value} if isinstance(value, BaseException) else {"return_value": value}
                mocks[name] = stack.enter_context(patch.object(policy, name, **options))
            try:
                policy._execute("/fixed/source", REQUEST, Path("/private/tmp/fixed"), evidence)
            except RuntimeError as error:
                evidence["testError"] = str(error)
            return evidence, mocks

    def test_successful_removal_without_positive_observation_does_not_release(self) -> None:
        evidence, _mocks = self.execute({"remove_container": {"canonicalAbsenceProved": False}})
        self.assertFalse(evidence["cleanupVerified"])
        self.assertIn("absence", evidence["testError"])

    def test_worker_failure_still_observes_successful_cleanup(self) -> None:
        evidence, mocks = self.execute({"_wait": RuntimeError("decode timeout")})
        self.assertTrue(evidence["cleanupVerified"])
        self.assertEqual(evidence["testError"], "decode timeout")
        mocks["remove_container"].assert_called_once()

    def test_launch_abort_reconciles_late_creation_before_absence(self) -> None:
        evidence, mocks = self.execute({"_launch": RuntimeError("launch interrupted")})
        self.assertTrue(evidence["cleanupVerified"])
        mocks["reconcile_launch_abort"].assert_called_once()
        self.assertEqual(evidence["testError"], "launch interrupted")

    def test_removal_exception_never_fabricates_verified_cleanup(self) -> None:
        evidence, _mocks = self.execute({"remove_container": RuntimeError("remove timed out")})
        self.assertFalse(evidence["cleanupVerified"])
        self.assertIn("timed out", evidence["testError"])
        self.assertEqual(evidence["cleanupBudgetSeconds"], 90)
        self.assertGreaterEqual(evidence["cleanupMs"], 0)

    def test_real_owner_signal_waits_for_exact_daemon_cleanup_then_cancels(self) -> None:
        events, evidence = [], {"cleanupVerified": False}
        previous = signal.getsignal(signal.SIGUSR1)
        def expired(_signal, _frame):
            events.append("cancelled")
            raise RuntimeError("owner work deadline")
        def remove(*_args):
            # The production grade worker is single-threaded, so the owner's
            # process-directed USR1 can only land on its main thread. Direct it
            # there: in this shared test process, threads left by earlier tests
            # could otherwise take the signal and handle it after cleanup
            # (reproduced: 248/300 runs with four stray threads, 0/300 without).
            signal.pthread_kill(threading.main_thread().ident, signal.SIGUSR1)
            events.append("exact absence observed")
            return {"canonicalAbsenceProved": True}
        try:
            signal.signal(signal.SIGUSR1, expired)
            with patch.object(policy, "remove_container", side_effect=remove):
                with self.assertRaisesRegex(RuntimeError, "owner work deadline"):
                    policy._cleanup((object(), Path("/unused"), "name", "exact-id"), evidence)
            self.assertEqual(events, ["exact absence observed", "cancelled"])
            self.assertTrue(evidence["cleanupVerified"])
            self.assertEqual(evidence["cleanupBudgetSeconds"], 90)
            self.assertGreaterEqual(evidence["cleanupMs"], 0)
        finally:
            signal.signal(signal.SIGUSR1, previous)


class GradeObservationReaderTests(unittest.TestCase):
    """Actual FIFO/link/UTF-8/race boundaries are independent of JSON self-hashes."""

    def test_fifo_rejects_before_blocking_and_hardlinks_are_not_regular_authority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "frames.ffprobe"
            os.mkfifo(path, 0o600)
            started = time.monotonic()
            with self.assertRaises(RuntimeError):
                list(_lines(path, {"bytes": 1, "sha256": SHA}))
            self.assertLess(time.monotonic() - started, .5)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "frames.ffprobe"
            path.write_bytes(b"frame\n")
            os.link(path, path.with_name("alias"))
            with self.assertRaises(RuntimeError):
                list(_lines(path, {"bytes": 6, "sha256": SHA}))

    def test_strict_utf8_and_midstream_changes_reject(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "frames.ffprobe"
            raw = b"\xff\n"
            path.write_bytes(raw)
            with self.assertRaises(UnicodeDecodeError):
                list(_lines(path, {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}))
            raw = b"first\nsecond\n"
            path.write_bytes(raw)
            lines = _lines(path, {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
            self.assertEqual(next(lines), "first\n")
            path.write_bytes(b"wrong\nsecond\n")
            with self.assertRaises(RuntimeError):
                list(lines)


if __name__ == "__main__":
    unittest.main()
