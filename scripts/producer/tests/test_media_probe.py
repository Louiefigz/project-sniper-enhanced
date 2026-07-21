"""Adversarial checks for the stable headless media-probe boundary."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from _common import pl  # noqa: F401
from headless import media_probe as probe

FFPROBE = "/test/runtime/ffprobe"


def _video() -> dict:
    return {
        "codec_type": "video", "codec_name": "h264", "profile": "High",
        "pix_fmt": "yuv420p", "width": 1080, "height": 1920,
        "avg_frame_rate": "30/1", "nb_read_packets": "60",
        "duration": "2.000000",
    }


def _audio() -> dict:
    return {"codec_type": "audio", "codec_name": "aac"}


def _payload(streams: list[dict] | None = None) -> dict:
    selected = streams if streams is not None else [_video(), _audio()]
    return {"streams": selected,
            "format": {"duration": "2.000000"}}


def _completed(request: object, value: object,
               returncode: int = 0) -> subprocess.CompletedProcess:
    stdout = value if isinstance(value, str) else json.dumps(value)
    return subprocess.CompletedProcess(
        getattr(request, "command", ()), returncode, stdout,
        "controlled ffprobe failure" if returncode else "")


class MediaProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary_root = os.path.realpath(tempfile.gettempdir())
        self.temporary = tempfile.TemporaryDirectory(dir=temporary_root)
        self.root = os.path.realpath(self.temporary.name)
        self.path = os.path.join(self.root, "candidate.mp4")
        self.content = b"stable synthetic media bytes"
        with open(self.path, "wb") as handle:
            handle.write(self.content)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _probe(self, value: object | None = None,
               callback: object | None = None) -> probe.ProbeResultV1:
        result = _payload() if value is None else value

        def runner(request: object) -> subprocess.CompletedProcess:
            if callback is not None:
                callback()
            return _completed(request, result)

        with mock.patch.object(probe, "run_text", side_effect=runner):
            return probe.probe_media_artifact(self.path, FFPROBE, 4.0)

    def test_returns_hash_bound_neutral_facts_and_closed_request(self) -> None:
        seen = []

        def runner(request: object) -> subprocess.CompletedProcess:
            seen.append(request)
            return _completed(request, _payload())

        with mock.patch.object(probe, "run_text", side_effect=runner):
            result = probe.probe_media_artifact(self.path, FFPROBE, 4.0)

        expected = hashlib.sha256(self.content).hexdigest()
        self.assertEqual(result.sha256, expected)
        self.assertEqual(result.size_bytes, len(self.content))
        self.assertEqual((result.width, result.height), (1080, 1920))
        rate = (result.fps_numerator, result.fps_denominator)
        self.assertEqual(rate, (30, 1))
        self.assertEqual((result.frame_count, result.audio_codec), (60, "aac"))
        request = seen[0]
        self.assertEqual(request.command[0], FFPROBE)
        self.assertEqual(request.command[-1], self.path)
        self.assertIn("-count_packets", request.command)
        self.assertEqual((request.stdin_text, request.cwd), ("", "/"))
        self.assertEqual(request.environment, {})
        self.assertEqual(request.timeout_seconds, 4.0)

    def test_reduces_rational_fps_without_float_identity_loss(self) -> None:
        value = _payload([_video()])
        value["streams"][0]["avg_frame_rate"] = "60000/2002"
        value["streams"][0]["duration"] = "2.002000"
        value["format"]["duration"] = "2.002000"
        result = self._probe(value)
        self.assertEqual((result.fps_numerator, result.fps_denominator),
                         (30000, 1001))
        self.assertIsNone(result.audio_codec)

    def test_artifact_sha256_uses_same_stable_file_rules(self) -> None:
        expected = hashlib.sha256(self.content).hexdigest()
        self.assertEqual(probe.artifact_sha256(self.path), expected)
        with self.assertRaisesRegex(probe.MediaProbeError, "canonical"):
            probe.artifact_sha256(os.path.relpath(self.path))

    def test_rejects_symlink_fifo_and_hardlink(self) -> None:
        symlink = os.path.join(self.root, "linked.mp4")
        os.symlink(self.path, symlink)
        fifo = os.path.join(self.root, "media.fifo")
        os.mkfifo(fifo)
        hardlink = os.path.join(self.root, "hard.mp4")
        os.link(self.path, hardlink)
        for path in (symlink, fifo, self.path, hardlink):
            with self.subTest(path=path):
                with self.assertRaises(probe.MediaProbeError):
                    probe.artifact_sha256(path)

    def test_rejects_content_change_during_ffprobe(self) -> None:
        def mutate() -> None:
            with open(self.path, "wb") as handle:
                handle.write(b"changed synthetic media bytes")

        with self.assertRaisesRegex(
                probe.MediaProbeError, "changed during ffprobe"):
            self._probe(callback=mutate)

    def test_rejects_path_replacement_during_ffprobe(self) -> None:
        replacement = os.path.join(self.root, "replacement.mp4")

        def replace() -> None:
            with open(replacement, "wb") as handle:
                handle.write(self.content)
            os.replace(replacement, self.path)

        with self.assertRaisesRegex(
                probe.MediaProbeError, "changed during ffprobe"):
            self._probe(callback=replace)

    def test_rejects_invalid_or_multiple_stream_sets(self) -> None:
        invalid_sets = (
            [], [_audio()], [_video(), _video()],
            [_video(), _audio(), _audio()],
            [_video(), {"codec_type": "subtitle", "codec_name": "mov_text"}],
            ["not-a-stream"],
        )
        for streams in invalid_sets:
            with self.subTest(streams=streams):
                with self.assertRaisesRegex(
                        probe.MediaProbeError, "stream|video"):
                    self._probe(_payload(streams))

    def test_rejects_invalid_rational_frame_count_and_duration(self) -> None:
        cases = []
        for field, value in (("avg_frame_rate", "0/0"),
                             ("avg_frame_rate", "29.97"),
                             ("nb_read_packets", "N/A"),
                             ("nb_read_packets", "060")):
            document = _payload()
            document["streams"][0][field] = value
            cases.append(document)
        inconsistent = _payload()
        inconsistent["format"]["duration"] = "8.0"
        cases.append(inconsistent)
        stream_mismatch = _payload()
        stream_mismatch["streams"][0]["duration"] = "8.0"
        cases.append(stream_mismatch)
        for document in cases:
            with self.subTest(document=document):
                with self.assertRaises(probe.MediaProbeError):
                    self._probe(document)

    def test_rejects_missing_or_malformed_required_video_facts(self) -> None:
        mutations = (
            ("codec_name", ""), ("profile", None), ("pix_fmt", " yuv420p"),
            ("width", True), ("height", 0),
        )
        for field, value in mutations:
            document = copy.deepcopy(_payload())
            document["streams"][0][field] = value
            with self.subTest(field=field, value=value):
                with self.assertRaises(probe.MediaProbeError):
                    self._probe(document)

    def test_rejects_process_failure_and_invalid_json(self) -> None:
        with mock.patch.object(
                probe, "run_text",
                side_effect=lambda request: _completed(request, "", 9)):
            with self.assertRaisesRegex(
                    probe.MediaProbeError, "ffprobe failed"):
                probe.probe_media_artifact(self.path, FFPROBE)
        with self.assertRaisesRegex(probe.MediaProbeError, "invalid JSON"):
            self._probe("not-json")

    def test_rejects_invalid_process_request(self) -> None:
        with self.assertRaisesRegex(
                probe.MediaProbeError, "request is invalid"):
            probe.probe_media_artifact(self.path, "ffprobe")
        with self.assertRaisesRegex(
                probe.MediaProbeError, "request is invalid"):
            probe.probe_media_artifact(self.path, FFPROBE, float("nan"))


if __name__ == "__main__":
    unittest.main()
