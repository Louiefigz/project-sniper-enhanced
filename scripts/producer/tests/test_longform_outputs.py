"""longform_outputs tests — the SRT sidecar (now wired into render.py so longform
actually ships captions) + chapters."""
import os
import tempfile
import unittest
from unittest import mock

from _common import *  # noqa: F401,F403
from captions import longform_outputs as lo
import render as renderer


class SrtSidecarTests(unittest.TestCase):
    WORDS = [{"word": "Hello", "start": 0.0, "end": 0.4},
             {"word": "world", "start": 0.5, "end": 0.9},
             {"word": "again", "start": 2.0, "end": 2.4}]

    def test_build_srt_has_numbered_cues_and_timestamps(self) -> None:
        srt = lo.build_srt(self.WORDS)
        self.assertIn("00:00:00,000 -->", srt)          # SRT time format
        self.assertRegex(srt, r"^1\r?\n", )              # first cue numbered 1
        self.assertIn("Hello", srt)

    def test_write_srt_writes_file_and_returns_cue_count(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "captions.srt")
            n = lo.write_srt(self.WORDS, path)
            self.assertTrue(os.path.exists(path))
            self.assertGreaterEqual(n, 1)
            self.assertEqual(n, lo.build_srt(self.WORDS).count(" --> "))

    def test_empty_words_write_no_cues(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "e.srt")
            self.assertEqual(lo.write_srt([], path), 0)

    def test_longform_sidecar_applies_plan_caption_corrections(self) -> None:
        words = [{"word": "Hermosibot.", "start": 0.0, "end": 0.8}]
        plan = {"target": {"mode": "longform"},
                "captions": {"burn": False,
                             "corrections": {"Hermosibot": "Hormozi bot"}}}
        with tempfile.TemporaryDirectory() as d:
            ctx = renderer.RenderCtx(plan, {}, d, d)
            with mock.patch.object(renderer, "kept_words", return_value=words), \
                 mock.patch.object(renderer, "emit"):
                renderer.longform_sidecar_stage(ctx, mock.Mock())
            with open(os.path.join(d, "captions.srt"), encoding="utf-8") as fh:
                srt = fh.read()
        self.assertIn("Hormozi bot.", srt)
        self.assertNotIn("Hermosibot", srt)

    def test_longform_sidecar_honors_caption_lane_off(self) -> None:
        plan = {"target": {"mode": "longform", "scope": "produced",
                           "lanes": {"captions": "off"}}}
        with tempfile.TemporaryDirectory() as d:
            ctx = renderer.RenderCtx(plan, {}, d, d)
            with mock.patch.object(renderer, "kept_words", return_value=self.WORDS), \
                 mock.patch.object(renderer, "emit"):
                result = renderer.longform_sidecar_stage(ctx, mock.Mock())
            self.assertIsNone(result)
            self.assertFalse(os.path.exists(os.path.join(d, "captions.srt")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
