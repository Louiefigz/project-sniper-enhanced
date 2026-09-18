"""Strict count authority and real owned-process faults, without media/providers."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import guided_picture_decode as decoder
from headless.process_runner import ProcessDeadlineError, ProcessOutputLimitError, ProcessRequest, run_text

PROGRESS = "frame=3\nout_time_us=100000\nprogress=end\n"


class DecodeProgressTests(unittest.TestCase):
    """Malformed or incomplete output cannot borrow container count as authority."""

    def test_complete_progress_requires_exact_count(self) -> None:
        """Only the single last terminal block owns decoded count."""
        decoder.require_decoded_frames("frame=1\nprogress=continue\n" + PROGRESS, 3)
        for expected in (2, 4, 0, -1, True, 3.0):
            with self.subTest(expected=expected), self.assertRaises(RuntimeError):
                decoder.require_decoded_frames(PROGRESS, expected)

    def test_malformed_terminal_progress_fails(self) -> None:
        """Keep the reused parser's torn/duplicate/missing completion defects closed."""
        rows = ("", "frame=3\nprogress=continue\n", PROGRESS + "frame=3\n",
            PROGRESS + PROGRESS, PROGRESS.replace("frame=3", "frame=3\nframe=3"),
            PROGRESS.replace("progress=end", "progress=unknown"), PROGRESS.replace("frame=3", "frame=NaN"),
            PROGRESS.replace("out_time_us=100000", "out_time_us=0"), "frame=4\nprogress=continue\n" + PROGRESS,
            PROGRESS.replace("out_time_us=100000\n", ""), "foreign diagnostic\n" + PROGRESS)
        for row in rows:
            with self.subTest(row=row), self.assertRaises(RuntimeError):
                decoder.require_decoded_frames(row, 3)

    def test_stdout_byte_bound_and_nontext_reject(self) -> None:
        """The cap is bytes, including multibyte text; no truncated success."""
        for value in (b"not text", "\u20ac" * (decoder.MAX_DECODE_LOG_BYTES // 3 + 1)):
            with self.assertRaises(RuntimeError):
                decoder.require_decoded_frames(value, 3)

    def test_command_preserves_strict_full_passthrough_and_original_remaining(self) -> None:
        """No seek, rate, filter, frame cap, audio decode or fresh timeout is added."""
        result = subprocess.CompletedProcess([], 0, PROGRESS, "")
        with tempfile.TemporaryDirectory() as raw, patch.object(decoder, "run_text", return_value=result) as run, \
                patch.object(decoder, "process_timeout", side_effect=[.7, .6, .5]) as clock:
            decoder.decode_picture_frames(Path(raw) / "picture.mp4", sys.executable, 3)
        request = run.call_args.args[0]
        self.assertEqual((request.timeout_seconds, request.stdin_text, request.max_output_bytes), (.7, "", 1048576))
        command = request.command
        for key, value in (("-map", "0:v:0"), ("-err_detect", "explode"),
                           ("-fps_mode", "passthrough"), ("-progress", "pipe:1")):
            self.assertEqual(command[command.index(key) + 1], value)
        self.assertTrue({"-xerror", "-an", "-nostdin", "-nostats"}.issubset(command))
        self.assertFalse({"-ss", "-t", "-r", "-vf", "-frames:v", "-count_frames"}.intersection(command))
        self.assertEqual(clock.call_count, 3)

    def test_nonzero_exit_or_late_deadline_never_qualifies_valid_stdout(self) -> None:
        """Exit status and final enclosing-clock checks win over plausible progress."""
        with tempfile.TemporaryDirectory() as raw:
            result = subprocess.CompletedProcess([], 1, PROGRESS, "TEST decoder failure")
            with patch.object(decoder, "run_text", return_value=result), self.assertRaisesRegex(RuntimeError, "failed"):
                decoder.decode_picture_frames(Path(raw) / "picture.mp4", sys.executable, 3)
            result.returncode = 0
            with patch.object(decoder, "run_text", return_value=result), \
                    patch.object(decoder, "process_timeout", side_effect=[1, RuntimeError("TEST expired")]), \
                    self.assertRaisesRegex(RuntimeError, "expired"):
                decoder.decode_picture_frames(Path(raw) / "picture.mp4", sys.executable, 3)


class DecodeOwnedProcessTests(unittest.TestCase):
    """The new adapter actually uses capped, deadline-owned process capture."""

    def _fault(self, script: str, expected: type[Exception]) -> None:
        """Launch only a TEST Python child, then verify actual ledger/group absence."""
        with tempfile.TemporaryDirectory() as raw:
            ledger = Path(raw) / "ledger.jsonl"
            def actual(request: ProcessRequest) -> subprocess.CompletedProcess:
                """Exercise the real owned runner while substituting only the TEST command."""
                return run_text(replace(request, command=(sys.executable, "-c", script),
                    termination_grace_seconds=.1, max_output_bytes=128))
            with patch.dict(os.environ, {"SNIPER_OWNED_PROCESS_LEDGER": str(ledger)}), \
                    patch.object(decoder, "run_text", side_effect=actual), \
                    patch.object(decoder, "process_timeout", return_value=.3), self.assertRaises(expected):
                decoder.decode_picture_frames(Path(raw) / "TEST.mp4", sys.executable, 3)
            rows = [json.loads(line) for line in ledger.read_text().splitlines()]
            self.assertEqual([row["event"] for row in rows], ["intent", "spawned", "reaped"])
            with self.assertRaises(ProcessLookupError):
                os.killpg(rows[1]["pid"], 0)

    def test_actual_overflow_cannot_keep_a_valid_terminal_prefix(self) -> None:
        """Overflow is failure even when terminal-looking stdout arrived first."""
        self._fault(f"import os,time; os.write(1,{PROGRESS.encode()!r}); os.write(2,b'x'*65536); time.sleep(30)",
                    ProcessOutputLimitError)

    def test_actual_term_resistant_timeout_is_reaped(self) -> None:
        """The new invocation cannot outlive its original small test allowance."""
        self._fault("import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(30)",
                    ProcessDeadlineError)


if __name__ == "__main__":
    unittest.main(verbosity=2)
