"""Content-based transcription-input classification tests."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SCRIPTS_DIR))

from transcribe_input import TranscribeInputError, probe_transcribe_input


def _result(streams: list[dict], code: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        ["ffprobe"], code, json.dumps({"streams": streams}), "bad media")


class TranscribeInputTests(unittest.TestCase):
    @mock.patch("transcribe_input.subprocess.run")
    def test_extensionless_admitted_video_is_accepted(self, run: mock.Mock) -> None:
        run.return_value = _result([
            {"codec_type": "video"}, {"codec_type": "audio"}])
        found = probe_transcribe_input("/project/.sniper-external-media/a.media")
        self.assertTrue(found.is_video)
        self.assertTrue(found.is_audio)

    @mock.patch("transcribe_input.subprocess.run")
    def test_audio_only_input_is_accepted(self, run: mock.Mock) -> None:
        run.return_value = _result([{"codec_type": "audio"}])
        found = probe_transcribe_input("/project/audio-without-a-suffix")
        self.assertFalse(found.is_video)
        self.assertTrue(found.is_audio)

    @mock.patch("transcribe_input.subprocess.run")
    def test_video_without_audio_fails_before_whisper(self, run: mock.Mock) -> None:
        run.return_value = _result([{"codec_type": "video"}])
        with self.assertRaisesRegex(TranscribeInputError, "no audio stream"):
            probe_transcribe_input("/project/silent.media")

    @mock.patch("transcribe_input.subprocess.run")
    def test_decoder_rejection_is_not_reclassified_by_suffix(
            self, run: mock.Mock) -> None:
        run.return_value = _result([], code=1)
        with self.assertRaisesRegex(TranscribeInputError, "unreadable"):
            probe_transcribe_input("/project/fake.mp4")


if __name__ == "__main__":
    unittest.main(verbosity=2)
