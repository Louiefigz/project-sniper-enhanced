"""Real bounded output, Unicode and owned-group regressions; no providers."""
from __future__ import annotations

import json
import os
import signal
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from _common import pl  # noqa: F401
from headless.process_runner import ProcessDeadlineError, ProcessOutputLimitError, ProcessRequest, run_text
from test_process_runner import _assert_gone, _environment


class BoundedProcessRunnerTests(unittest.TestCase):
    """A plausible output prefix never hides overflow, timeout or a surviving child."""

    def test_unicode_chunks_are_counted_as_bytes_and_decoded_after_capture(self) -> None:
        script = "import os,time; os.write(1,b'\\xe2'); time.sleep(.02); os.write(1,b'\\x82\\xac'); os.write(2,b'!')"
        with tempfile.TemporaryDirectory() as root:
            request = ProcessRequest((sys.executable, "-c", script), "", root, _environment(), 2,
                                     max_output_bytes=4)
            result = run_text(request)
            self.assertEqual((result.stdout, result.stderr), ("€", "!"))
            with self.assertRaises(ProcessOutputLimitError):
                run_text(replace(request, max_output_bytes=3))

    def test_bounded_mode_rejects_nonempty_stdin_and_invalid_caps_before_spawn(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            request = ProcessRequest((sys.executable, "-c", "pass"), "", root, _environment(), 1,
                                     max_output_bytes=1)
            for value in (0, -1, True, 1.5, 16 * 1024 * 1024 + 1):
                with self.subTest(cap=value), self.assertRaisesRegex(RuntimeError, "byte cap"):
                    run_text(replace(request, max_output_bytes=value))
            with self.assertRaisesRegex(RuntimeError, "empty stdin"):
                run_text(replace(request, stdin_text="not accepted"))

    def _child_case(self, root: str, suffix: str, timeout: float) -> None:
        pid_file, ledger = Path(root) / "child.pid", Path(root) / "ledger.jsonl"
        child = "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(30)"
        script = ("import os,signal,subprocess,sys,time; "
            "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
            f"p=subprocess.Popen([sys.executable,'-c',{child!r}]); "
            f"open({str(pid_file)!r},'w').write(str(p.pid)); time.sleep(.05); " + suffix)
        request = ProcessRequest((sys.executable, "-c", script), "", root, _environment(), timeout,
                                 termination_grace_seconds=.1, max_output_bytes=128)
        expected = ProcessOutputLimitError if "os.write" in suffix else ProcessDeadlineError
        with patch.dict(os.environ, {"SNIPER_OWNED_PROCESS_LEDGER": str(ledger)}):
            with self.assertRaises(expected):
                run_text(request)
        rows = [json.loads(line) for line in ledger.read_text().splitlines()]
        self.assertEqual([row["event"] for row in rows], ["intent", "spawned", "reaped"])
        _assert_gone(self, rows[1]["pid"], "bounded leader remains")
        _assert_gone(self, int(pid_file.read_text()), "bounded descendant remains")
        with self.assertRaises(ProcessLookupError):
            os.killpg(rows[1]["pid"], 0)

    def test_overflow_reaps_term_resistant_group_without_unbounded_cleanup_capture(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            self._child_case(root, "os.write(1,b'x'*65536); time.sleep(30)", 2)

    def test_deadline_reaps_term_resistant_group_holding_output_pipes(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            self._child_case(root, "time.sleep(30)", .3)

    def test_successful_capped_command_reaps_ignored_stdio_descendant(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            pid_file = Path(root) / "child.pid"
            script = ("import subprocess,sys; "
                "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],"
                "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
                f"open({str(pid_file)!r},'w').write(str(p.pid)); print('ok')")
            result = run_text(ProcessRequest((sys.executable, "-c", script), "", root, _environment(), 2,
                termination_grace_seconds=.1, max_output_bytes=3))
            self.assertEqual(result.stdout, "ok\n")
            _assert_gone(self, int(pid_file.read_text()), "successful bounded command leaked descendant")


if __name__ == "__main__":
    unittest.main(verbosity=2)
