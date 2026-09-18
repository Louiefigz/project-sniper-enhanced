"""Pinned-image proof that video frame bounds never truncate qualification audio."""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


_LIVE = os.environ.get("RUN_LIVE_QUALIFICATION_TESTS") == "1"
_DOCKER = os.environ.get("SNIPER_DOCKER_PATH", "/usr/local/bin/docker")
_IMAGE = os.environ.get("SNIPER_RENDER_IMAGE_ID", "")
_USER = os.environ.get("SNIPER_RENDER_UID_GID", "501:20")


def _pinned_image(value: str) -> bool:
    return re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None


def _base(root: Path, entrypoint: str) -> list[str]:
    return [
        _DOCKER, "run", "--rm", "--pull", "never", "--platform", "linux/arm64",
        "--network", "none", "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges:true", "--user", _USER,
        "--pids-limit", "128", "--memory", "1g", "--memory-swap", "1g",
        "--cpus", "2", "--tmpfs", "/scratch:rw,nosuid,nodev,noexec,size=128m",
        "--mount", f"type=bind,src={root},dst=/output",
        "--entrypoint", entrypoint, _IMAGE,
    ]


def _run(root: Path, entrypoint: str, args: list[str]) -> str:
    result = subprocess.run(
        [*_base(root, entrypoint), *args],
        stdin=subprocess.DEVNULL, capture_output=True, text=True,
        timeout=180, check=False,
    )
    if result.returncode or result.stderr.strip():
        raise RuntimeError(result.stderr[-1000:])
    return result.stdout


def _render(root: Path, frames: int) -> tuple[int, int]:
    program = frames * 2000
    timeline = ((program + 47) // 48) * 48
    video_filter = (
        "fps=fps=24/1:start_time=0:round=near,"
        f"trim=end_frame={frames},setpts=PTS-STARTPTS,format=yuv420p"
    )
    audio_filter = (
        "aresample=48000:async=0:first_pts=0,"
        f"atrim=end_sample={program},apad=whole_len={timeline},"
        f"atrim=end_sample={timeline},asetpts=N/SR/TB"
    )
    _run(root, "/usr/bin/ffmpeg", [
        "-nostdin", "-hide_banner", "-v", "error", "-xerror",
        "-f", "lavfi", "-i",
        "testsrc2=size=320x180:rate=24000/1001:duration=3",
        "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=48000:duration=3",
        "-map", "0:v:0", "-map", "1:a:0", "-vf", video_filter,
        "-af", audio_filter, "-vsync", "cfr", "-c:v", "libx264",
        "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-video_track_timescale", "24", "-c:a", "aac", "-ar", "48000",
        "-ac", "2", "-map_metadata", "-1", "-map_chapters", "-1",
        "-n", f"/output/{frames}.mp4",
    ])
    return program, timeline


def _probe(root: Path, frames: int) -> tuple[dict, int]:
    media = f"/output/{frames}.mp4"
    document = json.loads(_run(root, "/usr/bin/ffprobe", [
        "-v", "error", "-count_frames", "-count_packets",
        "-show_streams", "-show_format", "-show_frames", "-show_entries",
        "stream:format:frame=media_type,pts,pkt_pts,best_effort_timestamp,"
        "duration,pkt_duration,nb_samples,interlaced_frame,top_field_first",
        "-of", "json", media,
    ]))
    samples = sum(
        int(row["nb_samples"]) for row in document["frames"]
        if row["media_type"] == "audio")
    _run(root, "/usr/bin/ffmpeg", [
        "-nostdin", "-v", "error", "-xerror", "-i", media,
        "-map", "0", "-f", "null", "-",
    ])
    return document, samples


class QualificationImagePinTests(unittest.TestCase):
    """Keep a mutable cached image tag from becoming acceptance evidence."""

    def test_only_exact_lowercase_sha256_image_ids_are_accepted(self) -> None:
        valid = "sha256:" + "a" * 64
        invalid = (
            "", "renderer:latest", "sha256:" + "a" * 63,
            "sha256:" + "A" * 64, valid + "0",
        )
        self.assertTrue(_pinned_image(valid))
        for value in invalid:
            with self.subTest(value=value):
                self.assertFalse(_pinned_image(value))

    def test_status_zero_decoder_stderr_is_not_acceptance_evidence(self) -> None:
        result = subprocess.CompletedProcess([], 0, "{}", "decode fault")
        with patch("subprocess.run", return_value=result), \
                tempfile.TemporaryDirectory() as raw, \
                self.assertRaisesRegex(RuntimeError, "decode fault"):
            _run(Path(raw), "/usr/bin/ffprobe", ["-v", "error"])


@unittest.skipUnless(_LIVE, "live qualification image proof disabled")
class QualificationOutputTerminationAcceptance(unittest.TestCase):
    """Exercise both non-integral AAC millisecond-alignment classes."""

    @classmethod
    def setUpClass(cls) -> None:
        if not _pinned_image(_IMAGE):
            raise RuntimeError(
                "live qualification proof requires a pinned sha256 image ID")

    def test_frame_trim_preserves_full_audio_program_for_49_and_50_frames(
            self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for frames in (49, 50):
                with self.subTest(frames=frames):
                    program, timeline = _render(root, frames)
                    document, decoded = _probe(root, frames)
                    streams = document["streams"]
                    video = next(row for row in streams
                                 if row["codec_type"] == "video")
                    audio = next(row for row in streams
                                 if row["codec_type"] == "audio")
                    self.assertEqual(int(video["nb_read_frames"]), frames)
                    self.assertEqual((video["start_pts"], video["time_base"]),
                                     (0, "1/24"))
                    self.assertEqual(int(video["duration_ts"]), frames)
                    self.assertEqual((audio["start_pts"], audio["time_base"]),
                                     (0, "1/48000"))
                    self.assertEqual(int(audio["duration_ts"]), timeline)
                    self.assertGreaterEqual(decoded, timeline)
                    self.assertLess(decoded - timeline, 1024)
                    self.assertLess(timeline - program, 48)
                    expected = max(frames / 24, timeline / 48000)
                    self.assertLessEqual(
                        abs(float(document["format"]["duration"]) - expected),
                        0.0000005,
                    )


if __name__ == "__main__":
    unittest.main()
