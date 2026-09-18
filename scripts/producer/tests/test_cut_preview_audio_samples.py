"""Real tiny PCM decodes exercise preview sample guards, not ingest/listening QA."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from array import array
from pathlib import Path

from _common import *  # noqa: F401,F403
from audio.render_audio_bus import fit_float_samples
from compile_timeline import compile_plan
from cut_preview_audio import AudioContext, _run, _segment_command


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg unavailable")
class PreviewAudioSamplesTests(unittest.TestCase):
    """Boolean channel presence is kernel-only; never fabricate admission proof."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="sniper-preview-samples-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "one-second.wav"
        _run([shutil.which("ffmpeg"), "-nostdin", "-v", "error", "-n", "-f", "lavfi",
              "-i", "aevalsrc=0.25|-0.25:s=48000:d=1", "-c:a", "pcm_f32le", str(self.source)])

    def _context(self, cuts: list[dict]) -> AudioContext:
        return AudioContext({"cutTrack": cuts}, {"sources": [{"id": "s", "path": str(self.source)}]},
                            self.root, {"fps": "30000/1001"}, {"ffmpeg": shutil.which("ffmpeg")}, {})

    def _raw(self, context: AudioContext) -> tuple[Path, str]:
        segments = compile_plan(context.plan).segments
        # True exercises the same filter kernel, without pretending to be a receipt.
        command, filters = _segment_command(context, segments[0],
            segments[1] if len(segments) > 1 else None, {str(self.source): True})
        target = self.root / "raw.f32"
        _run(command + ["-filter_complex", filters, "-map", "[combined]", "-c:a", "pcm_f32le",
                        "-ar", "48000", "-ac", "2", "-f", "f32le", str(target)])
        return target, filters

    def test_unity_decode_preserves_interior_and_uses_unpadded_own_and_lead(self) -> None:
        context = self._context([{"sourceId": "s", "start": 0, "end": 1},
                                 {"sourceId": "s", "start": 1, "end": 2, "audioLeadMs": 200}])
        raw, filters = self._raw(context)
        for forbidden in ("apad", "async", "atempo"):
            self.assertNotIn(forbidden, filters)
        data = array("f")
        data.frombytes(raw.read_bytes())
        self.assertEqual(len(data), 48000 * 2)
        for sample in (2000, 20000, 41000, 45000):
            self.assertEqual(data[sample * 2:sample * 2 + 2], array("f", [0.25, -0.25]))
        for sample in (0, 38399, 38400, 47999):
            self.assertLess(abs(data[sample * 2]), 0.001)
        self.assertEqual(fit_float_samples(raw, self.root / "fitted.f32", 48048, 1603), 48)

    def test_short_own_source_is_measured_not_padded(self) -> None:
        raw, _ = self._raw(self._context([{"sourceId": "s", "start": 0, "end": 2}]))
        self.assertEqual(raw.stat().st_size, 48000 * 8)
        with self.assertRaisesRegex(RuntimeError, "more than one frame"):
            fit_float_samples(raw, self.root / "fitted.f32", 96000, 1603)

    def test_unavailable_lead_cannot_silently_fill_a_complete_picture_window(self) -> None:
        context = self._context([{"sourceId": "s", "start": 0, "end": 1},
                                 {"sourceId": "s", "start": 1.3, "end": 2.3, "audioLeadMs": 200}])
        raw, _ = self._raw(context)
        self.assertEqual(raw.stat().st_size, 38400 * 8)
        with self.assertRaisesRegex(RuntimeError, "more than one frame"):
            fit_float_samples(raw, self.root / "fitted.f32", 48000, 1603)

    def test_missing_channel_proof_or_missing_source_is_not_silence(self) -> None:
        context = self._context([{"sourceId": "s", "start": 0, "end": 1}])
        segment = compile_plan(context.plan).segments[0]
        with self.assertRaisesRegex(RuntimeError, "missing its channel proof"):
            _segment_command(context, segment, None, {})
        self.source.unlink()
        with self.assertRaises(RuntimeError):
            _segment_command(context, segment, None, {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
