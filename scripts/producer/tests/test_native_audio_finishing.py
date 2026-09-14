"""Shared dialogue cleanup and strict native decision tests; no listening approval."""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from scipy.io import wavfile

from audio import dialogue_cleanup as cleanup
from audio import native_audio_finishing as native
from audio.program_finish_contract import finishing_request
from cut_preview_io import file_hash

RATE = 48_000
SAMPLES = 4 * RATE
DECISION = {"schemaVersion": 1, "rationale": "Reduce steady fan noise in this recording.",
            "audioEnhance": {"preset": "voice"}}


class NativeAudioFinishingContractTests(unittest.TestCase):
    """Native metadata validates before any local processor can execute."""

    def reject(self, value: object, samples: int = SAMPLES) -> None:
        """Require a malformed decision to fail with no media command."""
        with patch.object(cleanup, "run_audio") as run:
            with self.assertRaises((ValueError, RuntimeError)):
                native.native_finishing_request(value, samples)
        run.assert_not_called()

    def test_installed_presets_use_the_ordinary_request_without_mutation(self) -> None:
        for preset in ("voice", "voice-strong", "voice-rnn"):
            value = {**DECISION, "audioEnhance": {"preset": preset}}
            before = copy.deepcopy(value)
            self.assertEqual(native.native_finishing_request(value, SAMPLES),
                             finishing_request(value, SAMPLES / RATE))
            self.assertEqual(value, before)

    def test_absent_finishing_preserves_source_without_creating_a_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = cleanup.DialogueSource(str(root / "existing.wav"), SAMPLES, "ffmpeg", "ffprobe")
            with patch.object(native, "render_clean_dialogue") as render:
                self.assertEqual(native.finish_native_audio(source, None, root / "finish"), Path(source.path))
            render.assert_not_called()
            self.assertFalse((root / "finish").exists())

    def test_integer_positive_clock_is_required_even_without_processing(self) -> None:
        for samples in (0, -1, True, 4.5, float("nan"), float("inf")):
            self.reject(DECISION, samples)
            self.reject(None, samples)

    def test_metadata_and_rationale_are_closed_and_versioned(self) -> None:
        invalid = [False, [], {}, {**DECISION, "schemaVersion": True},
                   {**DECISION, "schemaVersion": 2}, {**DECISION, "rationale": "  "},
                   {**DECISION, "rationale": "ab"}, {**DECISION, "rationale": "x" * 2401},
                   {**DECISION, "rationale": "fan\0noise"}, {**DECISION, "remote": True},
                   {"schemaVersion": 1, "rationale": "An unevaluated recording."}]
        for value in invalid:
            with self.subTest(value=value):
                self.reject(value)

    def test_unavailable_presets_and_hidden_enhancement_knobs_are_rejected(self) -> None:
        for value in (None, [], {}, {"preset": "separate"}, {"preset": "dereverb"},
                      {"preset": "VOICE"}, {"preset": "voice", "strength": 100}, {"preset": 1}):
            self.reject({**DECISION, "audioEnhance": value})

    def test_touching_gain_windows_accept_both_limits_and_preserve_order(self) -> None:
        value = {"schemaVersion": 1, "rationale": "Match the two microphone levels.",
                 "audioGain": [{"outStart": 0, "outEnd": 2, "dB": -12},
                               {"outStart": 2, "outEnd": 4, "dB": 12}]}
        request = native.native_finishing_request(value, SAMPLES)
        self.assertEqual([window.db for window in request.gain], [-12, 12])

    def test_gains_reject_overlap_order_duration_and_nonfinite_values(self) -> None:
        window = {"outStart": 0, "outEnd": 2, "dB": 3}
        invalid = [[{**window, "outStart": -0.001}], [{**window, "outEnd": 0}],
                   [{**window, "outEnd": 4.000001}], [window, {**window, "outStart": 1}],
                   [{**window, "outStart": 2, "outEnd": 3}, window],
                   [{**window, "dB": -12.001}], [{**window, "dB": 12.001}],
                   [{**window, "dB": float("nan")}], [{**window, "dB": float("inf")}],
                   [{**window, "dB": True}], [{**window, "outEnd": "2"}],
                   [{**window, "extra": "undeclared"}], [None], [], {}, None]
        for rows in invalid:
            with self.subTest(rows=rows):
                self.reject({**DECISION, "audioGain": rows})

    def test_gain_count_is_bounded(self) -> None:
        rows = [{"outStart": index, "outEnd": index + 1, "dB": 0} for index in range(128)]
        request = native.native_finishing_request({**DECISION, "audioGain": rows}, 128 * RATE)
        self.assertEqual(len(request.gain), 128)
        self.reject({**DECISION, "audioGain": rows + [{"outStart": 128, "outEnd": 129, "dB": 0}]}, 129 * RATE)


class NativeAudioFinishingFailureTests(unittest.TestCase):
    """Failed processors cannot leave an apparently processed receipt."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        path = self.root / "source.wav"
        path.write_bytes(b"TEST float source authority")
        self.source = cleanup.DialogueSource(str(path), SAMPLES, "ffmpeg", "ffprobe")

    def test_runtime_and_subprocess_failure_remain_explicitly_failed(self) -> None:
        errors = (RuntimeError("processor failed"), subprocess.TimeoutExpired("ffmpeg", 1))
        for index, error in enumerate(errors):
            directory = self.root / str(index)
            with patch.object(native, "render_clean_dialogue", side_effect=error):
                with self.assertRaises(type(error)):
                    native.finish_native_audio(self.source, DECISION, directory)
            receipt = json.loads((directory / "receipt.json").read_text())
            self.assertEqual(receipt["status"], "failed")
            self.assertFalse(receipt["humanListeningApproved"])
            self.assertNotIn("output", receipt)

    def test_mutated_source_is_rejected_by_shared_processor(self) -> None:
        request = native.native_finishing_request({**DECISION, "audioEnhance": {"preset": "voice"}}, SAMPLES)
        def mutate(command: list[str]) -> bytes:
            Path(command[-1]).write_bytes(b"TEST output")
            Path(self.source.path).write_bytes(b"changed source")
            return b""
        with patch.object(cleanup, "exact_float_audio_clock"), \
                patch.object(cleanup, "measure_chain_latency", return_value=1200), \
                patch.object(cleanup, "run_audio", side_effect=mutate), \
                self.assertRaisesRegex(RuntimeError, "source changed"):
            cleanup.render_clean_dialogue(self.source, request, self.root)

    def test_changed_model_cannot_produce_a_success_receipt(self) -> None:
        output = self.root / "mock-finished.wav"
        output.write_bytes(b"TEST output")
        value = {**DECISION, "audioEnhance": {"preset": "voice-rnn"}}
        with patch.object(native, "cleanup_model_binding", side_effect=[{"sha256": "a"}, {"sha256": "b"}]), \
                patch.object(native, "render_clean_dialogue", return_value=(str(output), 480)), \
                self.assertRaisesRegex(RuntimeError, "model changed"):
            native.finish_native_audio(self.source, value, self.root / "finish")
        receipt = json.loads((self.root / "finish/receipt.json").read_text())
        self.assertEqual(receipt["status"], "failed")


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "local FFmpeg required")
class NativeAudioFinishingMediaTests(unittest.TestCase):
    """Small real PCM passes prove gain, delay/tail preservation and exact source identity."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def source(self, samples: np.ndarray) -> cleanup.DialogueSource:
        """Write float stereo using the shared expected 48 kHz clock."""
        path = self.root / "source.wav"
        wavfile.write(path, RATE, np.asarray(samples, dtype=np.float32))
        return cleanup.DialogueSource(str(path), len(samples), shutil.which("ffmpeg"), shutil.which("ffprobe"))

    def test_gain_changes_only_authored_window_before_mastering(self) -> None:
        mono = np.sin(2 * np.pi * 440 * np.arange(2 * RATE) / RATE) * 0.04
        original = np.column_stack([mono, mono]).astype(np.float32)
        source = self.source(original)
        before = file_hash(Path(source.path))
        value = {"schemaVersion": 1, "rationale": "Lift the quiet middle sentence.",
                 "audioGain": [{"outStart": 0.5, "outEnd": 1.5, "dB": 6}]}
        output = native.finish_native_audio(source, value, self.root / "finish")
        rate, processed = wavfile.read(output)
        self.assertEqual((rate, processed.shape), (RATE, original.shape))
        np.testing.assert_allclose(processed[:RATE // 4], original[:RATE // 4], atol=1e-7)
        np.testing.assert_allclose(processed[7 * RATE // 4:], original[7 * RATE // 4:], atol=1e-7)
        middle = slice(3 * RATE // 4, 5 * RATE // 4)
        ratio = np.sqrt(np.mean(processed[middle] ** 2) / np.mean(original[middle] ** 2))
        self.assertAlmostEqual(float(ratio), 10 ** (6 / 20), places=5)
        self.assertEqual(file_hash(Path(source.path)), before)
        receipt = json.loads((self.root / "finish/receipt.json").read_text())
        self.assertEqual(receipt["status"], "processed")
        self.assertEqual(receipt["removedLatencySamples"], 0)
        self.assertEqual(receipt["outputSha256"], file_hash(output))
        self.assertFalse(receipt["humanListeningApproved"])

    def test_real_cleanup_keeps_final_impulse_and_exact_sample_clock(self) -> None:
        positions = (RATE, 2 * RATE - 60)
        original = np.zeros((2 * RATE, 2), dtype=np.float32)
        original[list(positions)] = 0.8
        source = self.source(original)
        output = native.finish_native_audio(source, DECISION, self.root / "finish")
        rate, processed = wavfile.read(output)
        self.assertEqual((rate, processed.shape), (RATE, original.shape))
        for position in positions:
            start, end = position - 2400, min(position + 2400, len(processed))
            peak = start + int(np.argmax(np.abs(processed[start:end, 0])))
            self.assertEqual(peak, position)
            self.assertGreater(abs(processed[position, 0]), 0.05)
        receipt = json.loads((self.root / "finish/receipt.json").read_text())
        self.assertGreater(receipt["removedLatencySamples"], 0)
        self.assertEqual(receipt["outputClock"]["samples"], len(original))
        np.testing.assert_allclose(processed[:, 0], processed[:, 1], atol=1e-7)


if __name__ == "__main__":
    unittest.main()
