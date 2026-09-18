"""Grade publication parsing and exact cleanup under fake daemon observations."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from headless import grade_observation_policy as policy
from headless import owned_result_wait as wait
from test_external_media_probe import _runtime
from test_external_media_probe_wait import CONTAINER, EXITED
from test_grade_observation_policy import REQUEST, SHA


class GradeWaitFileTests(unittest.TestCase):
    """Keep the existing bounded no-follow file reader and closed status union."""

    def setUp(self) -> None:
        """Create only a new private metadata fixture, never source or media."""
        temporary = tempfile.TemporaryDirectory(prefix="sniper-grade-wait-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        (self.root / "result").mkdir(mode=0o700)
        self.path = self.root / "result/result.json"

    def read(self) -> dict:
        """Use the actual grade adapter and fail if it reaches the daemon."""
        with patch.object(wait, "_state", side_effect=AssertionError("unexpected daemon call")):
            return policy._wait(_runtime(), str(self.root), CONTAINER, time.monotonic() + 10)

    def test_published_success_partial_and_failure_remain_exact_documents(self) -> None:
        """A structured worker failure remains evidence for the owner to reject."""
        for status in ("complete", "partial", "failed"):
            value = {"status": status, "error": "TEST retained detail"}
            self.path.write_text(json.dumps(value))
            with self.subTest(status=status):
                self.assertEqual(self.read(), value)

    def test_malformed_json_or_status_is_never_a_worker_result(self) -> None:
        """No truthy status or valid but non-object JSON is accepted."""
        for raw in ("not-json", "[]", '{"status":"unknown"}', '{"status":true}', '{"status":[]}', '{"status":{}}'):
            self.path.write_text(raw)
            with self.subTest(raw=raw), self.assertRaises((RuntimeError, ValueError)):
                self.read()

    def test_fifo_symlink_hardlink_and_oversize_reject_without_wait(self) -> None:
        """Retain canonical-parent and regular-file checks before any blocking read."""
        os.mkfifo(self.path, 0o600)
        with self.assertRaisesRegex(RuntimeError, "bounded regular"):
            self.read()
        self.path.unlink()
        target = self.root / "outside.json"
        target.write_text('{"status":"complete"}')
        self.path.symlink_to(target)
        with self.assertRaises(OSError):
            self.read()
        self.path.unlink()
        os.link(target, self.path)
        with self.assertRaisesRegex(RuntimeError, "bounded regular"):
            self.read()
        self.path.unlink()
        self.path.write_bytes(b" " * (64 * 1024 + 1))
        with self.assertRaisesRegex(RuntimeError, "exceeds byte limit: 65537 > 65536"):
            self.read()

    def test_linked_result_parent_and_changed_file_reject(self) -> None:
        """Neither parent replacement nor an in-read truncation can supply success."""
        self.path.write_text('{"status":"complete"}')
        original_read = os.read
        def truncate(descriptor: int, size: int) -> bytes:
            """Change actual held fixture bytes during the original read."""
            value = original_read(descriptor, size)
            self.path.write_bytes(b"{}")
            return value
        with patch("cut_preview_io.os.read", side_effect=truncate), self.assertRaises(RuntimeError):
            self.read()
        (self.root / "result").rename(self.root / "held-result")
        (self.root / "result").symlink_to(self.root / "held-result", target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "canonical"):
            self.read()

    def test_expired_json_parse_cannot_publish_success(self) -> None:
        """The adapter checks the same original deadline after JSON work too."""
        now = [100.0]
        self.path.write_text('{"status":"complete"}')
        original_loads = json.loads
        def late_parse(raw: str) -> dict:
            """Spend virtual time inside successful decoding."""
            now[0] = 101
            return original_loads(raw)
        with patch.object(wait.time, "monotonic", side_effect=lambda: now[0]), \
                patch.object(policy.json, "loads", side_effect=late_parse), \
                self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
            policy._wait(_runtime(), str(self.root), CONTAINER, 100.5)


class GradeWaitCleanupTests(unittest.TestCase):
    """Execute the actual owner/finally seam; every daemon action is a stub."""

    def execute(self, changes: dict) -> tuple[dict, dict]:
        """Run real wait, result parsing, cleanup and failed-receipt publication."""
        with tempfile.TemporaryDirectory(prefix="sniper-grade-wait-owner-") as temporary, ExitStack() as stack:
            root = Path(temporary).resolve()
            source = root / "TEST-inert-source"
            source.write_bytes(b"not media, never decoded")
            attempt = root / "attempt"
            attempt.mkdir(mode=0o700)
            defaults = {"required_runtime": _runtime(), "_launch_command": (["TEST launch"], SHA),
                "implementation_sources": [], "file_hash": SHA, "attest_image": {"Id": "sha256:" + SHA},
                "_launch": CONTAINER, "attest_probe_container": {}, "probe_container": {},
                "remove_container": {"canonicalAbsenceProved": True}, "reconcile_launch_abort": None}
            mocks = self.controls(stack, {**defaults, **changes.get("controls", {})})
            state = stack.enter_context(patch.object(wait, "_state", **changes.get("state", {"return_value": EXITED})))
            stack.enter_context(patch.object(policy, "_read_worker_result", side_effect=changes.get("reads", [None, None])))
            evidence = self.invoke(source, attempt, changes.get("success", False))
            self.assertEqual(json.loads((attempt / "execution.json").read_text()), evidence)
            self.assertFalse(evidence["gradeApplicable"] or evidence["deliveryApproved"])
            mocks["remove_container"].assert_called_once_with(_runtime(), str(attempt), CONTAINER)
            self.assertEqual(state.call_args.args[2], CONTAINER)
            self.assertEqual(evidence["cleanupBudgetSeconds"], 90)
            self.assertGreaterEqual(evidence["cleanupMs"], 0)
            return evidence, mocks

    def invoke(self, source: Path, attempt: Path, success: bool) -> dict:
        """A positive case must actually return; failures retain the owned receipt."""
        if success:
            return policy.run_isolated_grade(str(source), REQUEST, attempt)
        with self.assertRaises(policy.GradeIsolationError) as raised:
            policy.run_isolated_grade(str(source), REQUEST, attempt)
        return raised.exception.evidence

    def controls(self, stack: ExitStack, values: dict) -> dict:
        """Stub trusted daemon and byte observations without replacing the owner."""
        mocks = {}
        for name, value in values.items():
            options = {"side_effect": value} if isinstance(value, BaseException) else {"return_value": value}
            mocks[name] = stack.enter_context(patch.object(policy, name, **options))
        return mocks

    def test_oom_failure_still_retains_actual_exact_cleanup_observation(self) -> None:
        """Early terminal failure is preserved after proved exact-ID removal."""
        evidence, _mocks = self.execute({"state": {"return_value": {**EXITED, "OOMKilled": True, "ExitCode": 137}}})
        self.assertIn("OOMKilled", evidence["error"])
        self.assertTrue(evidence["cleanupVerified"])
        self.assertEqual(evidence["status"], "failed")

    def test_structured_terminal_race_failure_is_retained_before_rejection(self) -> None:
        """The actual grade postcheck, not the waiter, rejects worker failure."""
        worker = {"status": "failed", "request": REQUEST, "policy": policy.POLICY, "error": "TEST decode failed"}
        evidence, _mocks = self.execute({"reads": [None, json.dumps(worker)]})
        self.assertEqual(evidence["worker"], worker)
        self.assertIn("TEST decode failed", evidence["error"])
        self.assertTrue(evidence["cleanupVerified"])

    def test_valid_terminal_race_keeps_owner_postchecks_and_cleanup(self) -> None:
        """The waiter cannot skip actual owner validation before returned success."""
        worker = {"status": "complete", "request": REQUEST, "policy": policy.POLICY}
        evidence, _mocks = self.execute({"reads": [None, json.dumps(worker)], "success": True})
        self.assertEqual(evidence["worker"], worker)
        self.assertTrue(evidence["cleanupVerified"])
        self.assertEqual(evidence["status"], "complete")
        self.assertEqual(evidence["sourceAfterSha256"], SHA)

    def test_unknown_inspect_and_timeout_do_not_imply_cleanup(self) -> None:
        """Even uncertain observations still go through the exact cleanup owner."""
        for state in ({"return_value": None}, {"side_effect": subprocess.TimeoutExpired(["TEST/docker"], .1)}):
            with self.subTest(state=state):
                evidence, _mocks = self.execute({"state": state, "reads": [None]})
            self.assertTrue(evidence["cleanupVerified"])
            self.assertIn("state", evidence["error"])

    def test_unproved_or_throwing_cleanup_cannot_release_valid_race_result(self) -> None:
        """A valid complete publication never substitutes for canonical absence."""
        worker = {"status": "complete", "request": REQUEST, "policy": policy.POLICY}
        for removal in ({"canonicalAbsenceProved": False}, RuntimeError("TEST removal unavailable")):
            with self.subTest(removal=removal):
                evidence, _mocks = self.execute({"reads": [None, json.dumps(worker)],
                    "controls": {"remove_container": removal}})
            self.assertFalse(evidence["cleanupVerified"])
            self.assertEqual(evidence["worker"], worker)
            self.assertEqual(evidence["status"], "failed")


if __name__ == "__main__":
    unittest.main()
