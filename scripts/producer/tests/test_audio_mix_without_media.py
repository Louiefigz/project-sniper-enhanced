"""Synthetic AAC/PTS/picture proofs for both without-music delivery routes."""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from audio.audio_mix import MixSpec, run_audio_mix
from audio import audio_mix_picture, master
from audio.audio_mix_delivery import measure_delivery
from audio.audio_mix_without import (
    WithoutDeliveryPlan, _packet_signature, _probe,
    prepare_without_delivery, render_without_delivery,
)
from audio.channel_normalization import observe_channel_authority, system_program_request
from audio.channel_normalization_media import materialize_normalized_program
from fingerprints import file_sha256
from test_program_mix_headroom_media import RATE, _ffmpeg, _left_samples


def _source(root: Path, levels: tuple[float, float],
            codec: str = "aac", rate: int = RATE) -> Path:
    """Use non-decimal 24 fps picture times so millisecond remux drift is visible."""
    suffix = "mp4" if codec == "aac" else "mkv"
    source = root / f"source.{suffix}"
    expression = "|".join(f"{value}*sin(2*PI*1000*t)" for value in levels)
    _ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=64x64:r=24:d=3",
             "-f", "lavfi", "-i", f"aevalsrc={expression}:s={rate}:d=3:c=stereo",
             "-c:v", "libx264", "-preset", "ultrafast", "-c:a", codec,
             "-b:a", "256k", "-t", "3", str(source)])
    return source


def _plan(source: Path, root: Path) -> WithoutDeliveryPlan:
    """Use the real source authority and float materialization seams."""
    authority = observe_channel_authority(system_program_request(str(source)))
    normalized = root / "normalized.mkv"
    materialize_normalized_program(authority, str(normalized))
    return prepare_without_delivery(authority, str(normalized), 3)


def _assert_aac_clock(test: unittest.TestCase, path: Path) -> None:
    """AAC presents exactly the three-second program, with bounded codec padding."""
    row = _probe(str(path))["audio"]
    test.assertEqual(row["codec_name"], "aac")
    test.assertEqual(int(row["sample_rate"]), RATE)
    test.assertEqual(row["channels"], 2)
    test.assertEqual(row["duration_ts"], RATE * 3)
    test.assertEqual(row["time_base"], "1/48000")
    test.assertEqual(row["start_pts"], 0)
    decoded = len(_left_samples(path))
    test.assertGreaterEqual(decoded, RATE * 3)
    test.assertLess(decoded, RATE * 3 + 1024)


def _corrupt_audio_tail(path: Path) -> None:
    """Damage only owned synthetic AAC packet payloads, preserving the container."""
    observed = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "a:0", "-show_packets",
        "-show_entries", "packet=pos,size", "-of", "json", str(path),
    ], capture_output=True, text=True, check=True)
    packets = json.loads(observed.stdout)["packets"][-5:]
    with open(path, "r+b") as handle:
        for packet in packets:
            handle.seek(int(packet["pos"]))
            handle.write(b"\xff" * int(packet["size"]))


class PacketClockUnitTests(unittest.TestCase):
    """Do not let printed decimal timestamps erase fine-grained clock drift."""

    def test_integer_pts_exposes_submicrosecond_difference(self) -> None:
        observed = {"streams": [{"time_base": "1/10000000"}],
                    "packets": [{"pts": 0, "duration": 1, "data_hash": "same",
                                 "pts_time": "0.000000"}]}
        result = mock.Mock(returncode=0, stdout=json.dumps(observed))
        with mock.patch.object(audio_mix_picture, "_run", return_value=result):
            original = _packet_signature("synthetic-probe-only", "v:0")
        observed["packets"][0]["pts"] = 1
        result.stdout = json.dumps(observed)
        with mock.patch.object(audio_mix_picture, "_run", return_value=result):
            changed = _packet_signature("synthetic-probe-only", "v:0")
        self.assertNotEqual(original, changed)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                     "installed FFmpeg and ffprobe required")
class WithoutDeliveryMediaTests(unittest.TestCase):
    """Actual stream/packet checks; no claim of browser listening qualification."""

    def test_qualified_original_aac_is_packet_and_decoded_sample_identical(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source, output = _source(root, (0.2, 0.2)), root / "without.mp4"
            plan = _plan(source, root)
            self.assertTrue(plan.copy_aac)
            result = render_without_delivery(plan, str(output))
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["media"]["route"], "verified-original-aac-copy")
            self.assertEqual(_packet_signature(str(source), "v:0"),
                             _packet_signature(str(output), "v:0"))
            self.assertEqual(_packet_signature(str(source), "a:0"),
                             _packet_signature(str(output), "a:0"))
            self.assertEqual(_left_samples(source), _left_samples(output))
            _assert_aac_clock(self, output)

    def test_dead_channel_repair_encodes_aac_but_copies_original_picture_pts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source, output = _source(root, (0.0, 0.2)), root / "without.mp4"
            plan = _plan(source, root)
            self.assertFalse(plan.copy_aac)
            result = render_without_delivery(plan, str(output))
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["media"]["route"], "qualified-aac-encode")
            self.assertEqual(_packet_signature(str(source), "v:0"),
                             _packet_signature(str(output), "v:0"))
            self.assertGreater(max(map(abs, _left_samples(output))), 0.1)
            observed = observe_channel_authority(system_program_request(str(output)))
            peaks = list(map(float, observed.receipt["stream"]["peakDbfs"]))
            self.assertAlmostEqual(peaks[0], peaks[1], delta=0.1)
            _assert_aac_clock(self, output)

    def test_float_and_non_delivery_rate_sources_encode_qualified_aac(self) -> None:
        for codec, rate in (("pcm_f32le", RATE), ("aac", 44_100)):
            with self.subTest(codec=codec, rate=rate), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                source, output = _source(root, (0.2, 0.2), codec, rate), root / "without.mp4"
                plan = _plan(source, root)
                self.assertFalse(plan.copy_aac)
                result = render_without_delivery(plan, str(output))
                self.assertTrue(result["ok"], result)
                self.assertTrue(result["delivery"]["qualified"])
                self.assertEqual(_packet_signature(str(source), "v:0"),
                                 _packet_signature(str(output), "v:0"))
                _assert_aac_clock(self, output)

    def test_changed_source_preserves_existing_output_and_is_not_published(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source, output = _source(root, (0.2, 0.2)), root / "without.mp4"
            plan = _plan(source, root)
            shutil.copyfile(source, output)
            previous = file_sha256(str(output))
            replacement = root / "other"
            replacement.mkdir()
            shutil.copyfile(_source(replacement, (0.1, 0.1)), source)
            result = render_without_delivery(plan, str(output))
            self.assertFalse(result["ok"], result)
            self.assertFalse(result["published"])
            self.assertIn("source bytes changed", result["stderr"])
            self.assertEqual(file_sha256(str(output)), previous)

    def test_actual_two_variant_music_job_returns_two_qualified_aac_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source, music = _source(root, (0.2, 0.2)), root / "music.wav"
            mixed, without = root / "with.mp4", root / "without.mp4"
            _ffmpeg(["-f", "lavfi", "-i", f"sine=f=180:r={RATE}:d=3",
                     "-c:a", "pcm_f32le", str(music)])
            with contextlib.redirect_stdout(io.StringIO()):
                result = run_audio_mix(MixSpec(
                    str(source), str(music), str(mixed), out_without=str(without)))
            self.assertEqual(result["status"], "done", result)
            self.assertTrue(result["delivery"]["qualified"])
            self.assertTrue(result["without_delivery"]["delivery"]["qualified"])
            _assert_aac_clock(self, mixed)
            _assert_aac_clock(self, without)
            self.assertEqual(_packet_signature(str(source), "v:0"),
                             _packet_signature(str(without), "v:0"))
            self.assertEqual(_packet_signature(str(source), "v:0"),
                             _packet_signature(str(mixed), "v:0"))

    def test_corrupt_tail_cannot_qualify_from_partial_loudness_statistics(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = _source(Path(raw), (0.2, 0.2))
            _corrupt_audio_tail(source)
            legacy = master.measure_loudness(str(source))
            self.assertIsNotNone(legacy)
            self.assertAlmostEqual(float(legacy["input_i"]), -14, delta=1)
            evidence = measure_delivery(str(source))
            self.assertFalse(evidence["qualified"])
            self.assertFalse(evidence["audioDecodeSucceeded"])
            self.assertNotEqual(evidence["audioDecodeExitCode"], 0)
            self.assertTrue(evidence["audioDecodeError"])

    def test_silent_aac_is_not_mislabeled_as_a_qualified_delivery(self) -> None:
        """-inf peaks are harmless headroom, but not proof of target loudness."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source, output = _source(root, (0.0, 0.0)), root / "without.mp4"
            plan = _plan(source, root)
            self.assertFalse(plan.copy_aac)
            result = render_without_delivery(plan, str(output))
            self.assertFalse(result["ok"])
            self.assertFalse(result["delivery"]["qualified"])
            self.assertTrue(result["delivery"]["audioDecodeSucceeded"])
            self.assertIsNone(result["delivery"]["integratedLufs"])
            self.assertFalse(output.exists())
            self.assertTrue(Path(result["unapprovedCandidate"]).is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
