"""Internal passed-output capabilities preserve bounds, ownership and group cleanup."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from _common import pl  # noqa: F401
from headless import process_runner
from headless.process_runner import ProcessDeadlineError, ProcessRequest, run_text
from test_process_runner import _assert_gone, _environment


def _output(root: str, name: str = "output") -> int:
    """Create one test-owned regular output; tests retain its close responsibility."""
    return os.open(Path(root) / name, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o600)


def _request(root: str, script: str, descriptors: tuple[int, ...]) -> ProcessRequest:
    return ProcessRequest((sys.executable, "-c", script), "", root, _environment(), 2,
                          termination_grace_seconds=.1, max_output_bytes=1024, pass_fds=descriptors)


class PassedOutputDescriptorTests(unittest.TestCase):
    """No sockets/directories/stdio or implicit inheritance become child capabilities."""

    def _reject_before_spawn(self, request: ProcessRequest) -> None:
        with patch.object(process_runner, "_ledger_note") as ledger, \
                patch.object(process_runner.subprocess, "Popen") as spawn:
            with self.assertRaisesRegex(RuntimeError, "descriptor"):
                run_text(request)
            ledger.assert_not_called()
            spawn.assert_not_called()

    def test_malformed_duplicate_stdio_and_closed_descriptors_fail_before_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            descriptor = _output(root)
            closed = os.dup(descriptor)
            os.close(closed)
            values = ([descriptor], (True,), (2,), (-1,), (1.5,), (descriptor, descriptor),
                      (3, 4, 5, 6, 7), (closed,))
            try:
                for value in values:
                    with self.subTest(descriptors=value):
                        self._reject_before_spawn(_request(root, "pass", value))
            finally:
                os.close(descriptor)

    def test_readonly_directory_pipe_and_multilink_outputs_are_not_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            output = _output(root)
            os.close(_output(root, "readonly"))
            readonly = os.open(Path(root) / "readonly", os.O_RDONLY)
            directory = os.open(root, os.O_RDONLY)
            reader, writer = os.pipe()
            os.link(Path(root) / "output", Path(root) / "second-name")
            descriptors = (output, readonly, directory, reader, writer)
            try:
                for descriptor in descriptors:
                    with self.subTest(descriptor=descriptor):
                        self._reject_before_spawn(_request(root, "pass", (descriptor,)))
            finally:
                for descriptor in descriptors:
                    os.close(descriptor)

    def test_four_valid_output_descriptors_are_passed_without_changing_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            descriptors = tuple(_output(root, f"output-{index}") for index in range(4))
            script = "import os; " + "; ".join(f"os.write({value},b'held')" for value in descriptors)
            try:
                self.assertEqual(run_text(_request(root, script, descriptors)).returncode, 0)
                self.assertEqual([os.fstat(value).st_size for value in descriptors], [4] * 4)
            finally:
                for descriptor in descriptors:
                    os.close(descriptor)

    def test_actual_child_writes_only_explicit_fd_and_caller_keeps_it_open(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            output, other = _output(root), _output(root, "not-passed")
            os.set_inheritable(other, True)
            script = (f"import os; os.write({output},b'actual child'); "
                f"\ntry: os.fstat({other})\nexcept OSError: print('not inherited')\n"
                "else: raise RuntimeError('unrequested descriptor leaked')")
            try:
                before = os.fstat(output)
                result = run_text(_request(root, script, (output,)))
                self.assertEqual((result.returncode, result.stdout), (0, "not inherited\n"))
                self.assertEqual(os.fstat(output).st_ino, before.st_ino)
                os.write(output, b' + caller')
                self.assertEqual((Path(root) / "output").read_bytes(), b'actual child + caller')
                self.assertEqual((Path(root) / "not-passed").stat().st_size, 0)
            finally:
                os.close(output)
                os.close(other)

    def test_default_does_not_inherit_even_explicitly_inheritable_output(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            output = _output(root)
            os.set_inheritable(output, True)
            script = (f"import os\ntry: os.fstat({output})\nexcept OSError: print('closed')\n"
                      "else: raise RuntimeError('default leaked descriptor')")
            try:
                self.assertEqual(run_text(_request(root, script, ())).stdout, "closed\n")
                os.fstat(output)
            finally:
                os.close(output)

    def test_timeout_reaps_fd_holding_group_without_closing_caller_output(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            output, ledger = _output(root), Path(root) / "ledger.jsonl"
            child = "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(30)"
            script = ("import os,signal,subprocess,sys,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
                f"p=subprocess.Popen([sys.executable,'-c',{child!r}],pass_fds=({output},)); "
                f"os.write({output},str(p.pid).encode()); time.sleep(30)")
            try:
                request = replace(_request(root, script, (output,)), timeout_seconds=.3)
                with patch.dict(os.environ, {process_runner.LEDGER_ENV: str(ledger)}):
                    with self.assertRaises(ProcessDeadlineError):
                        run_text(request)
                rows = [json.loads(line) for line in ledger.read_text().splitlines()]
                self.assertEqual([row["event"] for row in rows], ["intent", "spawned", "reaped"])
                _assert_gone(self, rows[1]["pid"], "passed-fd leader remains")
                _assert_gone(self, int((Path(root) / "output").read_text()), "passed-fd descendant remains")
                with self.assertRaises(ProcessLookupError):
                    os.killpg(rows[1]["pid"], 0)
                os.write(output, b' caller still owns this descriptor')
            finally:
                os.close(output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
