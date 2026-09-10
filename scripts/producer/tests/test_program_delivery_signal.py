"""Local signal delivery tests using synthetic PCM files and mocked decoding."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from scipy.io import wavfile

from audio import program_delivery_signal as signal
from audio import program_master_delivery as delivery
from render_effect_discovery import local_python_import_closure


class ProgramDeliverySignalTests(unittest.TestCase):
    """Exercise the real comparison and failure records without media processes."""

    def setUp(self) -> None:
        """Make a tiny intended master and a separate encoded-byte sentinel."""
        scratch = tempfile.TemporaryDirectory(prefix="sniper-signal-test-")
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name).resolve()
        t = np.arange(96000) / 48000
        self.reference = np.column_stack((.1 * np.sin(t * 700), .1 * np.sin(t * 1100))).astype(np.float32)
        self.expected = self.root / "master.wav"
        wavfile.write(self.expected, 48000, self.reference)
        self.candidate = self.root / "candidate.mp4"
        self.candidate.write_bytes(b"synthetic encoded sentinel")
        self.master = SimpleNamespace(path=str(self.expected), source_bus=SimpleNamespace(
            samples=len(self.reference), admission=SimpleNamespace(tools={"ffmpeg": {"path": "/pinned/ffmpeg"}})))

    def compare(self, actual: np.ndarray, rate: int = 48000) -> dict:
        """Write mock decoder output while retaining production file checks."""
        def decode(command: list[str]) -> bytes:
            """Stand in for decoding without silently changing the signal format."""
            wavfile.write(command[-1], rate, actual)
            self.assertEqual(command[0], "/pinned/ffmpeg")
            self.assertNotIn("-af", command)
            self.assertNotIn("-ar", command)
            self.assertNotIn("-ac", command)
            return b""
        with patch.object(signal, "run_audio", side_effect=decode):
            return signal.verify_program_delivery_signal(self.master, str(self.candidate))

    def test_identity_binds_bytes_and_cleans_decode(self) -> None:
        """A valid result retains window evidence and leaves no decode scratch."""
        result = self.compare(self.reference)
        self.assertTrue(result["passed"])
        self.assertTrue(result["inputsStable"])
        self.assertTrue(result["activeEvidenceAvailable"])
        self.assertEqual(len(result["referenceSha256"]), 64)
        self.assertEqual(len(result["candidateSha256"]), 64)
        self.assertEqual(list(self.root.glob(".program-signal-*")), [])
        json.dumps(result, allow_nan=False)

    def test_quiet_identity_is_explicitly_quiet(self) -> None:
        """Do not demand or fabricate active speech for a silent reference."""
        quiet = np.zeros_like(self.reference)
        wavfile.write(self.expected, 48000, quiet)
        result = self.compare(quiet)
        self.assertTrue(result["passed"])
        self.assertFalse(result["activeEvidenceAvailable"])
        self.assertGreater(result["quietChannelWindows"], 0)

    def test_dropout_preserves_failed_windows(self) -> None:
        """A one-channel dropout is a prepublication error with its measurements."""
        actual = self.reference.copy()
        actual[24000:72000, 1] = 0
        with self.assertRaises(signal.ProgramDeliverySignalError) as caught:
            self.compare(actual)
        self.assertFalse(caught.exception.evidence["passed"])
        self.assertGreater(caught.exception.evidence["failedWindowCount"], 0)
        self.assertTrue(caught.exception.evidence["windows"])
        self.assertEqual(list(self.root.glob(".program-signal-*")), [])

    def test_rate_channels_dtype_and_counts_are_not_coerced(self) -> None:
        """Malformed decoder outputs cannot be aligned or normalized into passing."""
        for actual, rate in [(self.reference, 44100), (self.reference[:, 0], 48000),
                             (self.reference.astype(np.int16), 48000), (self.reference[:-1], 48000),
                             (np.pad(self.reference, ((0, 1024), (0, 0))), 48000)]:
            with self.subTest(shape=actual.shape, rate=rate), self.assertRaises(signal.ProgramDeliverySignalError):
                self.compare(actual, rate)

    def test_padding_is_finite_and_explicitly_bounded(self) -> None:
        """The codec tail is counted separately and never exempted from finiteness."""
        actual = np.pad(self.reference, ((0, 1023), (0, 0)))
        self.assertEqual(self.compare(actual)["decodedPaddingSamples"], 1023)
        actual[-1, 0] = np.nan
        with self.assertRaises(signal.ProgramDeliverySignalError):
            self.compare(actual)

    def test_timeout_and_decoder_errors_retain_diagnostics(self) -> None:
        """A failed or expired command cannot produce local signal approval."""
        errors = [subprocess.TimeoutExpired(["fake"], 1, stderr=b"deadline"),
                  subprocess.CalledProcessError(1, ["fake"], stderr=b"bad decode")]
        for error in errors:
            with (self.subTest(error=type(error).__name__),
                  patch.object(signal, "run_audio", side_effect=error),
                  self.assertRaises(signal.ProgramDeliverySignalError) as caught):
                signal.verify_program_delivery_signal(self.master, str(self.candidate))
            self.assertEqual(caught.exception.evidence["errorType"], type(error).__name__)
            self.assertIsNotNone(caught.exception.evidence["stderr"])
        self.assertEqual(list(self.root.glob(".program-signal-*")), [])

    def test_disk_bound_is_a_rejection_not_a_trim(self) -> None:
        """A decoder that reaches its output cap never qualifies partial output."""
        def oversized(command: list[str]) -> bytes:
            """Create a sparse cap-sized output without starting a decoder."""
            limit = int(command[command.index("-fs") + 1])
            with Path(command[-1]).open("wb") as handle:
                handle.truncate(limit)
            return b""
        with patch.object(signal, "run_audio", side_effect=oversized):
            with self.assertRaises(signal.ProgramDeliverySignalError) as caught:
                signal.verify_program_delivery_signal(self.master, str(self.candidate))
        self.assertIn("disk bound", caught.exception.evidence["error"])

    def test_budget_is_checked_before_decode(self) -> None:
        """No implicit unlimited budget or over-budget expanded PCM job."""
        for maximum in [True, 0, -1, 1.5, 1024]:
            with (self.subTest(maximum=maximum), patch.object(signal, "run_audio") as run,
                  self.assertRaises(signal.ProgramDeliverySignalError)):
                signal.verify_program_delivery_signal(self.master, str(self.candidate), maximum)
            run.assert_not_called()

    def test_changed_encoded_or_reference_bytes_fail(self) -> None:
        """The output and intended master must remain the compared bytes."""
        for path in [self.candidate, self.expected]:
            before = path.read_bytes()
            def mutate(command: list[str]) -> bytes:
                """Change one bound input during the mocked decode."""
                wavfile.write(command[-1], 48000, self.reference)
                path.write_bytes(before + b"changed")
                return b""
            with (self.subTest(path=path.name), patch.object(signal, "run_audio", side_effect=mutate),
                  self.assertRaises(signal.ProgramDeliverySignalError)):
                signal.verify_program_delivery_signal(self.master, str(self.candidate))
            path.write_bytes(before)

    def test_receipt_bound_fails_closed(self) -> None:
        """A record too large to retain must not qualify the candidate."""
        with patch.object(signal, "MAX_JSON", 100):
            with self.assertRaises(signal.ProgramDeliverySignalError) as caught:
                self.compare(self.reference)
        self.assertNotIn("windows", caught.exception.evidence)
        self.assertGreater(caught.exception.evidence["windowCount"], 0)
        self.assertIn("record-budget-exceeded", caught.exception.evidence["windowDetailsOmitted"])

    def test_gate_is_in_existing_static_import_closure(self) -> None:
        """The existing ordinary-delivery source closure sees both new modules."""
        paths = local_python_import_closure([Path(delivery.__file__)])
        self.assertIn(Path(signal.__file__).resolve(), paths)
        self.assertIn(Path(signal.__file__).with_name("pcm_local_comparison.py").resolve(), paths)


if __name__ == "__main__":
    unittest.main()
