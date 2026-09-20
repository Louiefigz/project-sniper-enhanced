"""Measured speech edges: real silence becomes a real gap, and nothing else moves.

whisper.cpp's token times touch end to end, so the pause brain sees no gaps at all.
These tests build speech + silence with ffmpeg and check the measurement against
what was synthesised, then check every refusal (outward moves, entirely-silent
words, no measurement) leaves the transcript exactly as it was.

Run: .venv/bin/python -m unittest scripts.tests.test_local_whisper_speech_edges
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from local_whisper_speech_edges import (  # noqa: E402
    MIN_WORD_S, SpeechEdgeError, frame_levels, measure_silences, tighten_speech_edges)

FFMPEG = os.environ.get("HYPERFRAMES_FFMPEG_PATH") or shutil.which("ffmpeg") or "ffmpeg"


def _wav(path: Path, plan: list[tuple[float, bool]], quiet_db: float | None = None) -> None:
    """Write 16 kHz mono PCM: each (seconds, speaking) becomes tone or room tone.

    Speech is a tone at ``quiet_db`` (default full level); the gaps are quiet noise, as a
    real room is — digital silence would let any threshold pass.
    """
    speech = f"volume={quiet_db}dB," if quiet_db is not None else ""
    parts, filters = [], []
    for index, (seconds, speaking) in enumerate(plan):
        source = (f"sine=frequency=220:duration={seconds}:sample_rate=16000" if speaking
                  else f"anoisesrc=r=16000:d={seconds}:a=0.004:c=pink")
        parts += ["-f", "lavfi", "-i", source]
        filters.append(f"[{index}:a]{speech if speaking else ''}anull[a{index}];")
    graph = ("".join(filters)
             + "".join(f"[a{i}]" for i in range(len(plan)))
             + f"concat=n={len(plan)}:v=0:a=1[out]")
    done = subprocess.run([FFMPEG, "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
                           *parts, "-filter_complex", graph, "-map", "[out]",
                           "-ac", "1", "-ar", "16000", str(path)],
                          capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise AssertionError(f"test fixture audio failed: {done.stderr[-400:]}")


def _transcript(words: list[tuple[str, float, float]]) -> list[dict]:
    return [{"start": words[0][1], "end": words[-1][2], "text": " ".join(w[0] for w in words),
             "words": [{"word": text, "start": start, "end": end} for text, start, end in words]}]


class SpeechEdges(unittest.TestCase):
    """The measurement itself, and what it is allowed to change."""

    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="sniper-edges-"))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.wav = self.dir / "audio.wav"

    def test_a_real_pause_becomes_a_real_gap(self) -> None:
        """Two words with 1 s of silence between them: whisper's touching bounds open up."""
        _wav(self.wav, [(1.0, True), (1.0, False), (1.0, True)])
        transcript = _transcript([("one", 0.0, 2.0), ("two", 2.0, 3.0)])
        refined, report = tighten_speech_edges(transcript, str(self.wav))
        self.assertTrue(report["applied"], report)
        first, second = refined[0]["words"]
        self.assertAlmostEqual(first["end"], 1.0, delta=0.12)
        self.assertAlmostEqual(second["start"], 2.0, delta=0.12)
        self.assertGreater(second["start"] - first["end"], 0.8)
        self.assertEqual([w["word"] for w in refined[0]["words"]], ["one", "two"])
        self.assertEqual(report["gapsOpened"], 1)
        self.assertGreater(report["silenceExposedS"], 0.8)

    def test_it_only_ever_pulls_bounds_inward(self) -> None:
        """Speech throughout: nothing to expose, so no bound moves."""
        _wav(self.wav, [(2.0, True)])
        transcript = _transcript([("one", 0.0, 1.0), ("two", 1.0, 2.0)])
        refined, report = tighten_speech_edges(transcript, str(self.wav))
        self.assertEqual([(w["start"], w["end"]) for w in refined[0]["words"]],
                         [(0.0, 1.0), (1.0, 2.0)])
        self.assertEqual(report.get("gapsOpened", 0), 0)

    def test_a_word_measured_as_entirely_silent_is_left_alone(self) -> None:
        """A mis-timed token inside silence is not this module's to shorten or drop."""
        _wav(self.wav, [(1.0, True), (1.5, False), (1.0, True)])
        transcript = _transcript([("one", 0.0, 1.0), ("ghost", 1.2, 2.2), ("two", 2.5, 3.5)])
        refined, _ = tighten_speech_edges(transcript, str(self.wav))
        ghost = refined[0]["words"][1]
        self.assertEqual((ghost["start"], ghost["end"]), (1.2, 2.2))

    def test_a_word_is_never_shrunk_below_the_floor(self) -> None:
        _wav(self.wav, [(0.05, True), (1.5, False), (1.0, True)])
        transcript = _transcript([("one", 0.0, 1.0), ("two", 1.6, 2.6)])
        refined, _ = tighten_speech_edges(transcript, str(self.wav))
        for word in refined[0]["words"]:
            self.assertGreaterEqual(word["end"] - word["start"], MIN_WORD_S)

    def test_the_offset_moves_the_measurement_onto_the_transcripts_timeline(self) -> None:
        _wav(self.wav, [(1.0, True), (1.0, False), (1.0, True)])
        spans = measure_silences(str(self.wav), 10.0)
        self.assertTrue(spans, "silence was not measured")
        self.assertAlmostEqual(spans[0][0], 11.0, delta=0.12)

    def test_a_word_cannot_end_after_the_audio_does(self) -> None:
        """whisper's last token can run past the file; it is pulled back to the end."""
        _wav(self.wav, [(1.0, True), (0.5, False), (1.0, True)])
        transcript = _transcript([("one", 0.0, 1.0), ("two", 1.5, 4.0)])
        refined, report = tighten_speech_edges(transcript, str(self.wav))
        self.assertTrue(report["applied"], report)
        self.assertLessEqual(refined[0]["words"][-1]["end"], 2.51)

    def test_without_a_measurement_the_transcript_is_untouched(self) -> None:
        transcript = _transcript([("one", 0.0, 1.0), ("two", 1.0, 2.0)])
        refined, report = tighten_speech_edges(transcript, str(self.dir / "missing.wav"))
        self.assertFalse(report["applied"])
        self.assertIn("reason", report)
        self.assertEqual([(w["start"], w["end"]) for w in refined[0]["words"]],
                         [(0.0, 1.0), (1.0, 2.0)])

    def test_quiet_speech_over_room_tone_is_not_called_silence(self) -> None:
        """The failure this replaced: a word peaking ~-32 dB over a ~-39 dB floor.

        A fixed -30 dB gate calls it silence, and the trim built on that deleted the word.
        """
        _wav(self.wav, [(1.0, True), (0.5, False), (0.6, True), (0.5, False)], quiet_db=-32.0)
        _levels, gate = frame_levels(str(self.wav))
        self.assertLess(gate, -32.0, "the gate must sit below quietly spoken words")
        spans = measure_silences(str(self.wav))
        spoken = [(1.5, 2.1)]
        for start, end in spans:
            for speech_start, speech_end in spoken:
                overlap = min(end, speech_end) - max(start, speech_start)
                self.assertLess(overlap, 0.12, f"silence {start:.2f}-{end:.2f} covers quiet speech")

    def test_the_gate_is_never_louder_than_the_old_constant(self) -> None:
        _wav(self.wav, [(0.6, True), (0.4, False), (0.6, True)])   # loud room tone
        _levels, gate = frame_levels(str(self.wav))
        self.assertLessEqual(gate, -30.0)

    def test_a_broken_ffmpeg_is_reported_not_swallowed(self) -> None:
        os.environ["HYPERFRAMES_FFMPEG_PATH"] = str(self.dir / "not-ffmpeg")
        self.addCleanup(os.environ.pop, "HYPERFRAMES_FFMPEG_PATH", None)
        with self.assertRaises(SpeechEdgeError):
            measure_silences(str(self.wav))


if __name__ == "__main__":
    unittest.main()
