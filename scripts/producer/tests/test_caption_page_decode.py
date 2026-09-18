"""Pure runner/FD/deadline faults for the draft single-decode page adapter."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import captions.caption_page_decode as decoder
from _caption_page_proof_fixture import PageProcessStub, expected, progress_text
from headless.process_runner import ProcessDeadlineError, ProcessOutputLimitError


class CaptionPageDecodeTests(unittest.TestCase):
    """Stub all tool processes; only private small metadata files are real."""

    def setUp(self) -> None:
        """Create a TEST-only input sentinel and explicit nonexistent tool paths."""
        self.root = tempfile.TemporaryDirectory(prefix="caption-page-draft-test-")
        self.addCleanup(self.root.cleanup)
        self.path = str(Path(self.root.name, "TEST-not-media.mov"))
        Path(self.path).write_bytes(b"TEST-only-not-decoded-media")
        self.facts = expected()
        self.tools = {"ffmpeg": {"path": "/TEST/ffmpeg"}, "ffprobe": {"path": "/TEST/ffprobe"}}
        self.runner = PageProcessStub(self.facts)

    def _decode(self) -> dict:
        """Run the adapter using the current patched fake process only."""
        return decoder.decode_caption_page(self.path, self.tools, self.facts)

    def test_metadata_probe_then_exactly_one_bounded_decode(self) -> None:
        """No-count probe and one split decode retain the expected proof shape."""
        before = Path(self.path).read_bytes()
        with patch.object(decoder, "run_text", self.runner):
            result = self._decode()
        self.assertEqual(result["stream"], self.facts)
        self.assertEqual(result["alphaMax"], 255.0)
        self.assertEqual(len(self.runner.requests), 2)
        probe, decode = self.runner.requests
        self.assertNotIn("-count_frames", probe.command)
        self.assertEqual(decode.command.count("-i"), 1)
        self.assertEqual(decode.command.count("-filter_complex"), 1)
        self.assertIn("-xerror", decode.command)
        self.assertIn("-err_detect", decode.command)
        self.assertEqual(decode.command.count("passthrough"), 2)
        self.assertEqual(decode.stdin_text, "")
        self.assertEqual(decode.max_output_bytes, 16 * 1024 * 1024)
        self.assertEqual(len(decode.pass_fds), 1)
        with self.assertRaises(OSError):
            os.fstat(decode.pass_fds[0])
        self.assertEqual(os.listdir(self.root.name), ["TEST-not-media.mov"])
        self.assertEqual(Path(self.path).read_bytes(), before)

    def test_original_remainder_decreases_across_probe_decode_and_parse(self) -> None:
        """The adapter consumes the caller deadline instead of renewing each command."""
        remainder = iter((90.0, 80.0, 70.0, 60.0, 50.0, 40.0, 30.0, 20.0))
        with patch.object(decoder, "run_text", self.runner), \
                patch.object(decoder, "process_timeout", side_effect=lambda: next(remainder)) as clock:
            self._decode()
        self.assertEqual([row.timeout_seconds for row in self.runner.requests], [90.0, 60.0])
        self.assertEqual(clock.call_count, 8)

    def test_final_guard_after_all_proof_parsing_rejects_expiry(self) -> None:
        """A successful process and valid channels cannot publish after the original expiry."""
        calls = iter([30.0] * 7 + [ProcessDeadlineError("TEST original deadline")])

        def remaining() -> float:
            """Inject exact final observation failure without sleeping."""
            result = next(calls)
            if isinstance(result, Exception):
                raise result
            return result

        with patch.object(decoder, "run_text", self.runner), \
                patch.object(decoder, "process_timeout", side_effect=remaining):
            with self.assertRaisesRegex(ProcessDeadlineError, "original"):
                self._decode()
        self.assertEqual(len(self.runner.requests), 2)

    def test_deadline_and_output_limit_errors_never_fallback(self) -> None:
        """Existing owned-runner failure is terminal; no additional decode is attempted."""
        for error in (ProcessDeadlineError("TEST timeout"), ProcessOutputLimitError("TEST overflow")):
            with self.subTest(error=type(error).__name__), \
                    patch.object(decoder, "run_text", side_effect=error) as runner, \
                    self.assertRaises(type(error)):
                self._decode()
            self.assertEqual(runner.call_count, 1)

    def test_bad_metadata_never_starts_decoder(self) -> None:
        """Malformed, nonzero, foreign-stream and diagnostic probe results cannot qualify."""
        measured = {key: value for key, value in self.facts.items() if key != "nb_read_frames"}
        returns = [(0, "{", ""), (1, "{}", "failure"), (0, "[]", ""),
                   (0, json.dumps({"streams": [measured, measured]}), ""),
                   (0, json.dumps({"streams": [measured]}), "decoder warning"),
                   (0, json.dumps({"streams": [{**measured, "width": 99}]}), "")]
        for code, stdout, stderr in returns:
            result = subprocess.CompletedProcess([], code, stdout, stderr)
            with self.subTest(stdout=stdout), patch.object(decoder, "run_text", return_value=result) as run, \
                    self.assertRaises(RuntimeError):
                self._decode()
            self.assertEqual(run.call_count, 1)

    def test_partial_or_mixed_decode_channels_never_return_proof(self) -> None:
        """A normal process return cannot rescue absent frames or mixed error text."""
        for name in ("frame_text", "alpha_text"):
            self.runner = PageProcessStub(self.facts)
            setattr(self.runner, name, getattr(self.runner, name) + "TEST decoder error\n")
            with self.subTest(channel=name), patch.object(decoder, "run_text", self.runner), \
                    self.assertRaises(RuntimeError):
                self._decode()

    def test_progress_fd_requires_bounded_single_link_real_bytes(self) -> None:
        """Empty, oversized and hardlinked progress cannot claim terminal completion."""
        with decoder._progress_file() as (descriptor, path):
            with self.assertRaises(RuntimeError):
                decoder._progress_bytes(descriptor, path)
            os.write(descriptor, b"x" * (64 * 1024 + 1))
            with self.assertRaises(RuntimeError):
                decoder._progress_bytes(descriptor, path)
            os.ftruncate(descriptor, 1)
            link = str(Path(path).with_name("hardlink"))
            os.link(path, link)
            with self.assertRaises(RuntimeError):
                decoder._progress_bytes(descriptor, path)
            os.unlink(link)

    def test_progress_held_name_cannot_be_swapped_for_symlink(self) -> None:
        """The held descriptor is not enough when the named output has changed."""
        with self.assertRaisesRegex(RuntimeError, "changed"):
            with decoder._progress_file() as (descriptor, path):
                os.write(descriptor, progress_text(3).encode())
                os.rename(path, path + ".held")
                os.symlink(self.path, path)
                decoder._progress_bytes(descriptor, path)
        self.assertEqual(Path(self.path).read_bytes(), b"TEST-only-not-decoded-media")

    def test_progress_bytes_growth_during_read_is_rejected(self) -> None:
        """The final fstat comparison rejects mutation after the first size check."""
        real_read = os.read

        def read_then_grow(descriptor: int, size: int) -> bytes:
            """Mutate only the TEST held descriptor after its bounded read."""
            result = real_read(descriptor, size)
            os.write(descriptor, b"x")
            return result

        with decoder._progress_file() as (descriptor, path):
            os.write(descriptor, progress_text(3).encode())
            with patch.object(decoder.os, "read", side_effect=read_then_grow), \
                    self.assertRaisesRegex(RuntimeError, "changed"):
                decoder._progress_bytes(descriptor, path)


if __name__ == "__main__":
    unittest.main()
