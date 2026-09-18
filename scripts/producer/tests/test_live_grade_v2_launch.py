"""Explicit TEST controls and mocked daemon only; no media or real launch authority."""
from __future__ import annotations

import json
import io
import os
import signal
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import live_grade_v2_launch as launch
from cut_preview_io import file_hash, write_new


class V2LaunchTests(unittest.TestCase):
    """Verify durable prelaunch ordering and exact reserved-resource restrictions."""

    def setUp(self) -> None:
        """Create fresh metadata, never an admitted source or observation."""
        self.tmp = tempfile.TemporaryDirectory(prefix="TEST-v2-launch-", dir="/private/tmp")
        self.root = Path(self.tmp.name)
        self.directory = self.root / "7758dfae-d894-4845-9bc5-b6870715640d"
        self.directory.mkdir(mode=0o700)
        (self.directory / "execution").mkdir(mode=0o700)
        write_new(self.directory / "input.json", {"TEST": True})
        self.life = {"kind": "TEST-grade-v2-lifecycle", "directory": str(self.directory),
            "containerName": "sniper-grade-observation-" + self.directory.name.replace("-", ""),
            "inputSha256": file_hash(self.directory / "input.json"), "pins": [],
            "source": {"path": "/TEST-source", "sha256": "a" * 64}, "runtime": {"TEST": "runtime"},
            "supervisor": {"pid": 12345}}
        write_new(self.directory / "TEST-lifecycle.json", self.life)
        self.expected = file_hash(self.directory / "TEST-lifecycle.json")
        self.runtime = SimpleNamespace()
        self.request = {"sourceSha256": "a" * 64}
        self.stack_request = None
        self.argv = ["/TEST-docker", "run", "--name", self.life["containerName"]]
        self.stack = __import__("contextlib").ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(launch, "runtime_record", return_value=self.life["runtime"]))
        self.stack.enter_context(patch.object(launch.policy, "_request", side_effect=lambda value: value))
        self.stack.enter_context(patch.object(launch.policy, "uuid", launch.policy.uuid))
        self.stack.enter_context(patch.object(launch.policy, "_launch_command", return_value=(self.argv, "b" * 64)))
        self.native = self.stack.enter_context(patch.object(launch.policy, "_launch", return_value="c" * 64))
        self.addCleanup(self.tmp.cleanup)

    def activate(self) -> None:
        """Exercise the actual local wrappers with explicitly fake control tools."""
        launch.install_launch_guard(self.directory, self.expected)
        generated = launch.policy.uuid.uuid4()
        self.assertEqual(generated.hex, self.directory.name.replace("-", ""))
        launch.policy._launch_command(self.runtime,
            (self.directory / "execution", self.life["containerName"], "/TEST-source"), self.request)

    def invoke(self) -> str:
        """Pass the exact command actually returned by the wrapped builder."""
        return launch.policy._launch(self.runtime, str(self.directory / "execution"), self.argv, self.life["containerName"])

    def test_publication_precedes_launch_and_id_is_separate(self) -> None:
        """A daemon callback sees complete durable intent before invocation."""
        def observed(*_args: object) -> str:
            """Observe real written metadata at the mocked daemon boundary."""
            value = json.loads((self.directory / "TEST-launch-intent.json").read_text())
            self.assertEqual(value["name"], self.life["containerName"])
            self.assertFalse((self.directory / "TEST-launch-result.json").exists())
            return "c" * 64
        self.native.side_effect = observed
        self.activate()
        self.assertEqual(self.invoke(), "c" * 64)
        self.assertEqual(json.loads((self.directory / "TEST-launch-result.json").read_text())["containerId"], "c" * 64)

    def test_lost_launch_response_retains_exact_intent(self) -> None:
        """Uncertain daemon failure preserves known-name cleanup, not success."""
        self.native.side_effect = RuntimeError("TEST lost launch response")
        self.activate()
        with self.assertRaisesRegex(RuntimeError, "lost launch"):
            self.invoke()
        self.assertTrue((self.directory / "TEST-launch-intent.json").exists())
        self.assertFalse((self.directory / "TEST-launch-result.json").exists())

    def test_publication_failure_never_calls_daemon(self) -> None:
        """New-only collision blocks launch even when a lookalike record exists."""
        self.activate()
        (self.directory / "TEST-launch-intent.json").write_text("{}")
        with self.assertRaises(FileExistsError):
            self.invoke()
        self.native.assert_not_called()

    def test_global_uuid_and_second_allocation(self) -> None:
        """The proxy touches no shared UUID module and cannot mint a second name."""
        original = launch.uuid.uuid4
        self.activate()
        self.assertIs(launch.uuid.uuid4, original)
        with self.assertRaisesRegex(RuntimeError, "exactly one"):
            launch.policy.uuid.uuid4()

    def test_mutated_input_blocks_before_daemon(self) -> None:
        """Previously accepted input cannot change between command and call."""
        self.activate()
        (self.directory / "input.json").chmod(0o600)
        (self.directory / "input.json").write_text('{"changed":true}')
        with self.assertRaises(RuntimeError):
            self.invoke()
        self.native.assert_not_called()

    def test_changed_command_or_name_blocks(self) -> None:
        """No arbitrary Docker command or resource can enter the callback."""
        self.activate()
        for argv, name in [(self.argv + ["extra"], self.life["containerName"]), (self.argv, "unrelated")]:
            with self.assertRaises(RuntimeError):
                launch.policy._launch(self.runtime, str(self.directory / "execution"), argv, name)
        self.native.assert_not_called()

    def test_in_place_command_alias_mutation_blocks(self) -> None:
        """The returned mutable argv cannot rewrite the held prelaunch command."""
        self.activate()
        self.argv.append("TEST-unrequested-control")
        with self.assertRaises(RuntimeError):
            self.invoke()
        self.native.assert_not_called()

    def test_cleanup_lost_response_calls_exact_reconciliation(self) -> None:
        """Mock cleanup must reconcile the original name, never enumerate resources."""
        self.activate()
        self.native.side_effect = RuntimeError("TEST uncertain")
        with self.assertRaises(RuntimeError):
            self.invoke()
        self.stack.enter_context(patch.object(launch, "_absent"))
        self.stack.enter_context(patch.object(launch, "required_runtime", return_value=self.runtime))
        reconcile = self.stack.enter_context(patch.object(launch, "reconcile_launch_abort"))
        remove = self.stack.enter_context(patch.object(launch, "remove_container", return_value={
            "containerRef": self.life["containerName"], "canonicalAbsenceProved": True}))
        # Restore original command constructor; recovery does not install a launch wrapper.
        self.stack.enter_context(patch.object(launch.policy, "_launch_command", return_value=(self.argv, "b" * 64)))
        result = launch.cleanup_exact(self.directory, self.expected, time.monotonic() + 1)
        self.assertTrue(result["cleanupVerified"])
        self.assertEqual(reconcile.call_args.args[-1], self.life["containerName"])
        self.assertEqual(remove.call_args.args[-1], self.life["containerName"])

    def test_missing_intent_still_reconciles_reserved_name(self) -> None:
        """A deleted/missing sidecar can never become a no-launch assertion."""
        self.stack.enter_context(patch.object(launch, "_absent"))
        self.stack.enter_context(patch.object(launch, "required_runtime", return_value=self.runtime))
        reconcile = self.stack.enter_context(patch.object(launch, "reconcile_launch_abort"))
        self.stack.enter_context(patch.object(launch, "remove_container", return_value={
            "containerRef": self.life["containerName"], "canonicalAbsenceProved": True}))
        result = launch.cleanup_exact(self.directory, self.expected, time.monotonic() + 1)
        self.assertEqual(result["state"], "reconciled")
        self.assertIsNone(result["intentSha256"])
        reconcile.assert_called_once()

    def test_cleanup_cli_owns_one_original_timer_through_actual_helper(self) -> None:
        """Exercise the real CLI branch, not only a timer-free helper call."""
        self.stack.enter_context(patch.object(launch, "_absent"))
        self.stack.enter_context(patch.object(launch, "required_runtime", return_value=self.runtime))
        def reconciled(*_args: object) -> None:
            """The existing cleanup operations must inherit one active bound."""
            self.assertGreater(signal.getitimer(signal.ITIMER_REAL)[0], 0)
        self.stack.enter_context(patch.object(launch, "reconcile_launch_abort", side_effect=reconciled))
        self.stack.enter_context(patch.object(launch, "remove_container", return_value={
            "containerRef": self.life["containerName"], "canonicalAbsenceProved": True}))
        self.stack.enter_context(patch.object(launch.sys, "argv", ["TEST-entry", str(self.directory), self.expected, "--cleanup", "1000"]))
        output = self.stack.enter_context(__import__("contextlib").redirect_stdout(io.StringIO()))
        launch.main()
        self.assertEqual(json.loads(output.getvalue())["state"], "reconciled")
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL), (0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
