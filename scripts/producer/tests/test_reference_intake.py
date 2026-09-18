"""Reference fetch privacy/subtitle contract tests."""

from __future__ import annotations

import os
import json
import tempfile
import unittest
from unittest import mock

from _common import *  # noqa: F401,F403
from study import fetch_reference as fetch
from study import study_transcribe_local as local_study


class FetchArgvTests(unittest.TestCase):
    def test_subtitles_are_always_requested_without_cookies(self) -> None:
        argv = fetch.build_argv("yt-dlp", "/tmp/out", None)
        self.assertIn("--write-auto-subs", argv)
        self.assertIn("--write-subs", argv)
        self.assertIn("vtt", argv)
        self.assertIn("--max-filesize", argv)
        self.assertIn("--match-filter", argv)
        filter_value = argv[argv.index("--match-filter") + 1]
        self.assertEqual(filter_value, "duration <=? 3600")
        self.assertIn("best[height<=1080]/best", argv)
        self.assertEqual(argv[argv.index("--downloader") + 1], "native")
        self.assertIn("--hls-prefer-native", argv)
        self.assertEqual(argv[argv.index("--fixup") + 1], "never")
        self.assertNotIn("ffmpeg", " ".join(argv).lower())
        self.assertNotIn("ffprobe", " ".join(argv).lower())
        self.assertNotIn("--remux-video", argv)
        self.assertNotIn("--no-part", argv)
        self.assertNotIn("--cookies-from-browser", argv)

    def test_cookie_argv_only_when_explicitly_supplied(self) -> None:
        argv = fetch.build_argv("yt-dlp", "/tmp/out", "chrome")
        self.assertIn("--cookies-from-browser", argv)
        self.assertIn("chrome", argv)


class FetchPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    @mock.patch.object(fetch, "resolve_ytdlp", return_value="yt-dlp")
    @mock.patch.object(fetch, "run_once", return_value=(1, "sign in required", True))
    def test_auth_wall_never_reads_cookies_without_permission(self, run, _resolve) -> None:
        self.assertEqual(fetch.fetch("https://youtu.be/x", self.tmp.name, "chrome"), 1)
        self.assertEqual(run.call_count, 1)

    @mock.patch.object(fetch, "resolve_ytdlp", return_value="yt-dlp")
    @mock.patch.object(fetch, "validate_download", return_value=None)
    @mock.patch.object(fetch, "find_video", return_value="/tmp/video.mp4")
    @mock.patch.object(fetch, "run_once", side_effect=[
        (1, "sign in required", True), (0, "", False)])
    def test_explicit_permission_enables_one_cookie_retry(self, run, _video, _validate, _resolve) -> None:
        self.assertEqual(fetch.fetch("https://youtu.be/x", self.tmp.name, "chrome", True), 0)
        self.assertEqual(run.call_count, 2)
        self.assertIn("--cookies-from-browser", run.call_args_list[1].args[0])

    def test_download_bytes_are_bounded_before_sandbox_admission(self) -> None:
        video = os.path.join(self.tmp.name, "too-large.mp4")
        with open(video, "wb") as handle:
            handle.truncate(fetch.MAX_REFERENCE_BYTES + 1)
        self.assertIn("maximum", fetch.validate_download(video) or "")

    def test_newest_vtt_is_discovered(self) -> None:
        older = os.path.join(self.tmp.name, "ref.en.vtt")
        newer = os.path.join(self.tmp.name, "ref.en-orig.vtt")
        open(older, "w").close()
        open(newer, "w").close()
        os.utime(older, (1, 1))
        os.utime(newer, (2, 2))
        self.assertEqual(fetch.find_transcript(self.tmp.name), newer)

    def test_unsafe_vtt_is_rejected_instead_of_left_unregistered(self) -> None:
        transcript = os.path.join(self.tmp.name, "oversized.vtt")
        with open(transcript, "wb") as handle:
            handle.truncate(32 * 1024 ** 2 + 1)
        with self.assertRaisesRegex(ValueError, "unsafe"):
            fetch.find_transcript(self.tmp.name)

    def test_direct_cli_url_policy_matches_the_product_allowlist(self) -> None:
        self.assertEqual(
            fetch.validate_url("https://www.youtube.com/watch?v=x"),
            "https://www.youtube.com/watch?v=x",
        )
        for rejected in (
                "http://youtube.com/watch?v=x",
                "https://youtube.com.evil.test/watch?v=x",
                "https://user:secret@youtube.com/watch?v=x",
                f"https://youtube.com/{'x' * 2049}"):
            with self.assertRaises(ValueError):
                fetch.validate_url(rejected)


class LocalStudyTranscriptTests(unittest.TestCase):
    @mock.patch.object(local_study, "transcribe_media")
    def test_word_payload_is_persisted_for_deep_study(self, transcribe) -> None:
        transcribe.return_value = {
            "status": "done", "model": "whisper.cpp:test",
            "transcript": [{"text": "hello", "words": [
                {"word": "hello", "start": 0.1, "end": 0.4}]}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            output = os.path.join(tmp, "study", "transcript.json")
            local_study.write_transcript("/tmp/reference.mp4", output)
            with open(output, encoding="utf-8") as handle:
                payload = json.load(handle)
        self.assertEqual(payload["transcript"][0]["words"][0]["start"], 0.1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
