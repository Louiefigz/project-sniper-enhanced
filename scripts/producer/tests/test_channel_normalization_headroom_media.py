"""Visible regression for the separate normal-music channel prepass.

This is deliberately independent of the private dialogue-program float fix.
The generated input is a synthetic floating-point intermediate, not a claim
that ordinary correctly limited AAC masters exceed full scale.
"""
from __future__ import annotations

import json
import copy
import contextlib
import io
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from audio.channel_normalization import (
    ChannelNormalizationError, observe_channel_authority, system_program_request,
)
from audio.channel_normalization_media import (
    materialize_normalized_program, verify_normalized_program,
)
from audio.audio_mix import MixSpec, remux_without, run_audio_mix
from edit.picture_lock_common import content_hash
from fingerprints import file_sha256
from test_program_mix_headroom_media import (
    DURATION, FREQUENCY, RATE, _distortion_ratio, _ffmpeg, _left_samples,
)


def _make_program(path: Path, amplitudes: tuple[float, ...],
                  codec: str = "pcm_f32le", sample_rate: int = RATE) -> None:
    """Create frame-copyable synthetic video with channel-coded PCM tones."""
    expression = "|".join(f"{value}*sin(2*PI*{FREQUENCY}*t)" for value in amplitudes)
    layout = {1: "mono", 2: "stereo", 6: "5.1"}[len(amplitudes)]
    tone = f"aevalsrc={expression}:s={sample_rate}:d={DURATION}:c={layout}"
    _ffmpeg(["-f", "lavfi", "-i", f"testsrc2=s=64x64:r=10:d={DURATION}",
             "-f", "lavfi", "-i", tone, "-map", "0:v:0", "-map", "1:a:0",
             "-c:v", "ffv1", "-c:a", codec, str(path)])


def _legacy_materialization(source: Path, destination: Path, audio_filter: str) -> None:
    """Exercise the historical integer boundary as a low-level parity control."""
    _ffmpeg(["-i", str(source), "-map", "0:v:0", "-c:v", "copy",
             "-map", "0:a:0", "-af", audio_filter, "-ar", str(RATE),
             "-ac", "2", "-c:a", "pcm_s32le", str(destination)])


def _picture_packets(path: Path) -> list[dict]:
    """Read coded-picture bytes and packet times, independent of audio format."""
    result = subprocess.run([
        shutil.which("ffprobe") or "ffprobe", "-v", "error",
        "-select_streams", "v:0", "-show_packets", "-show_data_hash", "sha256",
        "-show_entries", "packet=pts_time,dts_time,duration_time,data_hash",
        "-of", "json", str(path)], capture_output=True, check=True, text=True,
        timeout=30)
    return json.loads(result.stdout)["packets"]


def _rehash(value: dict) -> dict:
    """Let semantic rejection tests avoid merely failing the self-hash check."""
    value["receiptHash"] = content_hash(
        {key: item for key, item in value.items() if key != "receiptHash"})
    return value


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                     "installed FFmpeg and ffprobe required")
class ChannelNormalizationHeadroomMediaTests(unittest.TestCase):
    """Do not remove floating-point headroom before music normalization."""

    def test_channel_normalization_preserves_float_program_headroom(self) -> None:
        """A stereo passthrough prepass must preserve its admitted float signal."""
        with tempfile.TemporaryDirectory(prefix="channel-headroom-") as temporary:
            directory = Path(temporary)
            source, output = directory / "float-program.mkv", directory / "normalized.mkv"
            _make_program(source, (1.36568546, 1.36568546))
            authority = observe_channel_authority(system_program_request(str(source)))
            receipt = materialize_normalized_program(authority, str(output))
            self.assertEqual(verify_normalized_program(authority, receipt), receipt)
            self.assertEqual(receipt["schemaVersion"], 2)
            self.assertEqual(receipt["codec"], "pcm_f32le")
            self.assertFalse(receipt["policy"]["masteringApplied"])
            original, normalized = _left_samples(source), _left_samples(output)
            difference = max(abs(a - b) for a, b in zip(original, normalized))
            self.assertEqual(len(normalized), len(original))
            self.assertLess(difference, 1e-6, json.dumps({
                "inputPeak": max(map(abs, original)), "outputPeak": max(map(abs, normalized)),
                "maximumError": difference, "filter": authority.filter_for("stereo")}))

    def test_mono_and_dead_channel_headroom_is_not_attenuated_or_clipped(self) -> None:
        """The selected live leg remains unity-gain in both stereo outputs."""
        for amplitudes in ((1.3,), (0.0, 1.3), (1.3, 0.0)):
            with self.subTest(amplitudes=amplitudes), tempfile.TemporaryDirectory() as raw:
                source, output = Path(raw) / "source.mkv", Path(raw) / "output.mkv"
                _make_program(source, amplitudes)
                authority = observe_channel_authority(system_program_request(str(source)))
                materialize_normalized_program(authority, str(output))
                self.assertAlmostEqual(max(map(abs, _left_samples(output))), 1.3, places=6)
                left = _ffmpeg(["-i", str(output), "-af", "pan=mono|c0=c0",
                                "-c:a", "pcm_f32le", "-f", "f32le", "-"])
                right = _ffmpeg(["-i", str(output), "-af", "pan=mono|c0=c1",
                                 "-c:a", "pcm_f32le", "-f", "f32le", "-"])
                self.assertEqual(left, right)

    def test_multichannel_float_retains_headroom_and_normalized_matrix_gain(self) -> None:
        """Coefficient normalization is linear; it must not limit float peaks."""
        with tempfile.TemporaryDirectory() as raw:
            source, output = Path(raw) / "source.mkv", Path(raw) / "output.mkv"
            _make_program(source, (1.3,) * 6)
            authority = observe_channel_authority(system_program_request(str(source)))
            receipt = materialize_normalized_program(authority, str(output))
            self.assertIn("rematrix_maxval=1", receipt["appliedFilter"])
            self.assertAlmostEqual(max(map(abs, _left_samples(output))), 1.3, places=6)

    def test_ordinary_pcm_parity_including_asymmetric_multichannel_input(self) -> None:
        """The codec change must not silently amplify the established downmix."""
        cases = ((0.8,), (0.8, 0.4), (0.8,) * 6, (0.2, 0.3, 0.4, 0.5, 0.6, 0.7))
        for amplitudes in cases:
            with self.subTest(amplitudes=amplitudes), tempfile.TemporaryDirectory() as raw:
                source, output = Path(raw) / "source.mkv", Path(raw) / "output.mkv"
                control = Path(raw) / "legacy.mkv"
                _make_program(source, amplitudes, "pcm_s32le")
                authority = observe_channel_authority(system_program_request(str(source)))
                materialize_normalized_program(authority, str(output))
                _legacy_materialization(source, control, authority.filter_for("stereo"))
                actual, previous = _left_samples(output), _left_samples(control)
                self.assertEqual(len(actual), len(previous))
                self.assertLess(max(abs(a - b) for a, b in zip(actual, previous)), 1e-6)

    def test_resampling_keeps_sample_count_and_coded_picture_timing(self) -> None:
        """44.1 kHz to 48 kHz stays aligned without a cut/speed/picture rewrite."""
        with tempfile.TemporaryDirectory() as raw:
            source, output = Path(raw) / "source.mkv", Path(raw) / "output.mkv"
            control = Path(raw) / "legacy.mkv"
            _make_program(source, (0.1, 0.1), "pcm_s32le", 44_100)
            authority = observe_channel_authority(system_program_request(str(source)))
            materialize_normalized_program(authority, str(output))
            _legacy_materialization(source, control, authority.filter_for("stereo"))
            actual, previous = _left_samples(output), _left_samples(control)
            self.assertEqual(len(actual), RATE * DURATION)
            self.assertEqual(len(previous), len(actual))
            self.assertLess(max(abs(a - b) for a, b in zip(actual, previous)), 1e-6)
            self.assertEqual(_picture_packets(source), _picture_packets(output))

    def test_historical_or_rehashed_policy_receipts_are_not_float_authority(self) -> None:
        """The old ad-hoc proof and changed policy cannot be reused as v2."""
        with tempfile.TemporaryDirectory() as raw:
            source, output = Path(raw) / "source.mkv", Path(raw) / "output.mkv"
            _make_program(source, (0.1, 0.1))
            authority = observe_channel_authority(system_program_request(str(source)))
            receipt = materialize_normalized_program(authority, str(output))
            historical = {key: item for key, item in receipt.items()
                          if key not in {"schemaVersion", "kind", "policy", "appliedFilter",
                                         "sampleFormat", "receiptHash"}}
            historical["codec"] = "pcm_s32le"
            changed = copy.deepcopy(receipt)
            changed["appliedFilter"] += ",volume=0.5"
            changed = _rehash(changed)
            for tampered in (historical, changed):
                with self.subTest(tampered=tampered), self.assertRaises(ChannelNormalizationError):
                    verify_normalized_program(authority, tampered)

    def test_rehashed_integer_bytes_cannot_claim_the_float_output_format(self) -> None:
        """Live probing rejects an s32 file even when its receipt hash is valid."""
        with tempfile.TemporaryDirectory() as raw:
            source, output = Path(raw) / "source.mkv", Path(raw) / "output.mkv"
            legacy = Path(raw) / "legacy.mkv"
            _make_program(source, (0.1, 0.1))
            authority = observe_channel_authority(system_program_request(str(source)))
            receipt = materialize_normalized_program(authority, str(output))
            _legacy_materialization(source, legacy, authority.filter_for("stereo"))
            receipt["outputPath"] = str(legacy)
            receipt["outputSha256"] = file_sha256(str(legacy))
            with self.assertRaisesRegex(ChannelNormalizationError, "float stereo PCM"):
                verify_normalized_program(authority, _rehash(receipt))

    def test_over_range_program_reaches_existing_music_master_without_clipping(self) -> None:
        """The actual music route can master retained float peaks to AAC."""
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            fixture, source = directory / "fixture.mkv", directory / "program.mkv"
            music, output = directory / "music.wav", directory / "mixed.mp4"
            _make_program(fixture, (1.36568546, 1.36568546))
            _ffmpeg(["-i", str(fixture), "-c:v", "libx264", "-preset", "ultrafast",
                     "-c:a", "copy", str(source)])
            _ffmpeg(["-f", "lavfi", "-i", f"sine=f=180:r={RATE}:d={DURATION}",
                     "-c:a", "pcm_f32le", str(music)])
            with contextlib.redirect_stdout(io.StringIO()):
                result = run_audio_mix(MixSpec(
                    str(source), str(music), str(output),
                    work_dir=str(directory / "work"), gap_db=60))
            self.assertEqual(result["status"], "done", result)
            self.assertTrue(result["lufs_within_tolerance"], result)
            prepass = Path(result["channel_normalization"]["materialization"]["outputPath"])
            self.assertGreater(max(map(abs, _left_samples(prepass))), 1.3)
            final = _left_samples(output)
            self.assertLess(max(map(abs, final)), 1.0)
            self.assertLess(_distortion_ratio(final), 0.01)

    def test_over_range_without_copy_is_rejected_before_destination_write(self) -> None:
        """A raw float program is not silently sent to a delivery copy path."""
        with tempfile.TemporaryDirectory() as raw:
            source, output = Path(raw) / "source.mkv", Path(raw) / "prior.mkv"
            _make_program(source, (1.3, 1.3))
            shutil.copyfile(source, output)
            previous = file_sha256(str(output))
            result = remux_without(str(source), str(output))
            self.assertFalse(result["ok"])
            self.assertIn("over-range", result["stderr"])
            self.assertEqual(file_sha256(str(output)), previous)

    def test_rejected_without_variant_preflights_before_either_existing_output_changes(self) -> None:
        """Do not overwrite one variant before rejecting the other request."""
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            source, music = directory / "source.mkv", directory / "music.wav"
            mixed, without = directory / "with.mp4", directory / "without.mp4"
            _make_program(source, (1.3, 1.3))
            _ffmpeg(["-f", "lavfi", "-i", f"sine=f=180:r={RATE}:d={DURATION}",
                     "-c:a", "pcm_f32le", str(music)])
            shutil.copyfile(source, mixed)
            shutil.copyfile(source, without)
            previous = (file_sha256(str(mixed)), file_sha256(str(without)))
            with contextlib.redirect_stdout(io.StringIO()):
                result = run_audio_mix(MixSpec(
                    str(source), str(music), str(mixed), out_without=str(without)))
            self.assertEqual(result["status"], "error", result)
            self.assertIn("over-range", result["detail"])
            self.assertIsNone(result["with_music"])
            self.assertEqual(previous, (file_sha256(str(mixed)), file_sha256(str(without))))


if __name__ == "__main__":
    unittest.main(verbosity=2)
