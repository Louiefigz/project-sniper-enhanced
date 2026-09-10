"""Real-media dead-left/dead-right receipt and dialogue-decode gates."""
from __future__ import annotations

import copy
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _channel_normalization_fixture import (
    FFMPEG,
    FFPROBE,
    available,
    dead_stereo_wav,
)
from audio.channel_normalization import (
    ChannelTools,
    observe_channel_authority,
    system_program_request,
    verify_channel_receipt,
)
from audio.dialogue_stem_contracts import (
    DialogueSourceSnapshot,
    DialogueStemTools,
)
from audio.dialogue_stem_probe import decode_source
from edit.picture_lock_common import content_hash
from fingerprints import file_sha256


def _tools() -> DialogueStemTools:
    ffmpeg = os.path.realpath(str(FFMPEG))
    ffprobe = os.path.realpath(str(FFPROBE))
    return DialogueStemTools(
        ffmpeg, file_sha256(ffmpeg), ffprobe, file_sha256(ffprobe))


def _render_filter(source: str, destination: str, audio_filter: str) -> None:
    subprocess.run([
        str(FFMPEG), "-nostdin", "-v", "error", "-y", "-i", source,
        "-af", audio_filter, "-c:a", "pcm_s24le", destination,
    ], check=True)


@unittest.skipUnless(available(), "ffmpeg and ffprobe are required")
class ChannelNormalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_dead_left_and_right_produce_balanced_stereo(self) -> None:
        for dead in (0, 1):
            with self.subTest(dead=dead):
                source = os.path.join(self.temp.name, f"dead-{dead}.wav")
                output = os.path.join(self.temp.name, f"fixed-{dead}.wav")
                dead_stereo_wav(source, dead)
                authority = observe_channel_authority(
                    system_program_request(source))
                decision = authority.receipt["decision"]
                self.assertEqual(decision["status"], "dead-channel-repaired")
                self.assertIs(type(decision["floorDb"]), int)
                self.assertIs(type(decision["minimumDeltaDb"]), int)
                self.assertEqual(decision["deadChannel"], dead)
                self.assertEqual(decision["liveChannel"], 1 - dead)
                _render_filter(
                    source, output, authority.filter_for("stereo"))
                observed = observe_channel_authority(
                    system_program_request(output))
                self.assertEqual(
                    observed.receipt["decision"]["status"],
                    "stereo-verified")
                peaks = [
                    float(value)
                    for value in observed.receipt["stream"]["peakDbfs"]
                ]
                self.assertLess(abs(peaks[0] - peaks[1]), 0.01)

    def test_rehashed_filter_substitution_is_rejected(self) -> None:
        source = os.path.join(self.temp.name, "dead.wav")
        dead_stereo_wav(source, 0)
        authority = observe_channel_authority(
            system_program_request(source))
        tampered = copy.deepcopy(authority.receipt)
        tampered["decision"]["stereoFilter"] = \
            "aformat=channel_layouts=stereo"
        body = {
            key: value for key, value in tampered.items()
            if key != "receiptHash"
        }
        tampered["receiptHash"] = content_hash(body)
        with self.assertRaisesRegex(
                RuntimeError, "decision is not reproducible"):
            verify_channel_receipt(tampered)

    def test_dialogue_decode_repairs_before_mono_downmix(self) -> None:
        tools = _tools()
        channel_tools = ChannelTools(
            tools.ffmpeg_path, tools.ffmpeg_sha256,
            tools.ffprobe_path, tools.ffprobe_sha256)
        self.assertTrue(channel_tools.ffmpeg_sha256)
        for dead in (0, 1):
            with self.subTest(dead=dead):
                source_path = os.path.join(
                    self.temp.name, f"dialogue-{dead}.wav")
                output = os.path.join(
                    self.temp.name, f"dialogue-{dead}-mono.wav")
                dead_stereo_wav(source_path, dead)
                source = DialogueSourceSnapshot(
                    f"source-{dead}", source_path,
                    file_sha256(source_path), 0)
                decoded = decode_source(source, 48_000, output, tools)
                receipt = decoded.proof["channelNormalization"]
                self.assertEqual(
                    receipt["decision"]["status"],
                    "dead-channel-repaired")
                self.assertEqual(receipt["decision"]["deadChannel"], dead)
                result = subprocess.run([
                    str(FFMPEG), "-hide_banner", "-nostats", "-i", output,
                    "-af", "volumedetect", "-f", "null", "-",
                ], capture_output=True, text=True, check=False)
                self.assertIn("mean_volume:", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
