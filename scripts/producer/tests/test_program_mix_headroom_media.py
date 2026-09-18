"""Synthetic headroom regression for the opt-in exact dialogue-program mixer.

This executes the real media renderer, not publication/admission or the normal
assemble music route. Two individually legal PCM stems intentionally produce an
over-0 dBFS sum. The float-only control changes the in-memory filter string and
codec, never production files. The existing public master filter is exercised
separately to demonstrate why delivery loudness cannot prove an unclipped mix.
"""
from __future__ import annotations

import array
import json
import math
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from audit.audit_probe import measure_loudness as measure_delivery_loudness
from audio import master
from audio.dialogue_program_media import _mix_graph, probe_program, render_dialogue_program_mix
from audio.dialogue_stem_contracts import DialogueStemRenderError


RATE = 48_000
DURATION = 3
FREQUENCY = 1_000
TOTAL = RATE * DURATION


def _ffmpeg(arguments: list[str]) -> bytes:
    """Run a bounded real media command, retaining diagnostics on failure."""
    result = subprocess.run(
        [shutil.which("ffmpeg") or "ffmpeg", "-nostdin", "-v", "error", *arguments],
        capture_output=True, check=False, timeout=30)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", "replace")[-2000:])
    return result.stdout


def _tone(path: Path, stereo: bool, amplitude: float = 0.8) -> None:
    """Create a legal 0.8-peak signed-PCM stem with no preexisting clipping."""
    source = f"aevalsrc={amplitude}*sin(2*PI*{FREQUENCY}*t):s={RATE}:d={DURATION}"
    audio_filter = "pan=stereo|c0=c0|c1=c0" if stereo else "anull"
    _ffmpeg(["-f", "lavfi", "-i", source, "-af", audio_filter,
             "-c:a", "pcm_s32le", str(path)])


def _left_samples(path: Path) -> array.array:
    """Decode channel zero as float, without downmix attenuation or clipping."""
    raw = _ffmpeg(["-i", str(path), "-map", "0:a:0", "-af", "pan=mono|c0=c0",
                   "-ar", str(RATE), "-c:a", "pcm_f32le", "-f", "f32le", "-"])
    samples = array.array("f")
    samples.frombytes(raw)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples


def _float_control(inputs: tuple[Path, Path], output: Path) -> None:
    """Keep the real sum/trim graph but preserve headroom at its final boundary."""
    graph = _mix_graph(2, TOTAL).replace("sample_fmts=s32", "sample_fmts=flt")
    _ffmpeg(["-i", str(inputs[0]), "-i", str(inputs[1]),
             "-filter_complex", graph, "-map", "[out]", "-ar", str(RATE),
             "-ac", "2", "-c:a", "pcm_f32le", str(output)])


def _actual_program(inputs: tuple[Path, Path], directory: Path) -> Path:
    """Invoke the actual mix/codec/probe seam with minimal media-only context."""
    tools = SimpleNamespace(ffmpeg_path=shutil.which("ffmpeg"),
                            ffprobe_path=shutil.which("ffprobe"))
    request = SimpleNamespace(
        tools=tools, dialogue_map={"projectSampleRate": RATE,
                                   "totalOutputSamples": TOTAL})
    auxiliary = (SimpleNamespace(stem=SimpleNamespace(path=str(inputs[1]))),)
    output, proof = render_dialogue_program_mix(
        request, str(inputs[0]), auxiliary, str(directory))
    if proof["decodedSamples"] != TOTAL:
        raise RuntimeError("real program mix changed the fixture sample clock")
    return Path(output)


def _master_audio(source: Path, output: Path) -> dict:
    """Use master's actual measurement/dispatch while keeping test output lossless."""
    measured = master.measure_loudness(str(source))
    chain, note = master.build_pass2_afilter(str(source), None, measured)
    _ffmpeg(["-i", str(source), "-af", chain, "-ar", str(RATE),
             "-c:a", "pcm_f32le", str(output)])
    loudness, true_peak = measure_delivery_loudness(str(output))
    return {"input": measured, "filter": chain, "note": note,
            "outputLufs": loudness, "outputTruePeakDbtp": true_peak}


def _distortion_ratio(samples: array.array) -> float:
    """Measure energy outside the known synthetic tone, independent of gain/phase."""
    center = samples[RATE // 2:RATE * 5 // 2]
    size = len(center)
    omega = 2 * math.pi * FREQUENCY / RATE
    sine = 2 * math.fsum(value * math.sin(omega * i)
                         for i, value in enumerate(center)) / size
    cosine = 2 * math.fsum(value * math.cos(omega * i)
                           for i, value in enumerate(center)) / size
    energy = math.fsum(value * value for value in center) / size
    return math.sqrt(max(0.0, energy - (sine * sine + cosine * cosine) / 2) / energy)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                     "installed FFmpeg and ffprobe required")
class ProgramMixHeadroomMediaTests(unittest.TestCase):
    """Preserve the sum until mastering; a compliant LUFS value is insufficient."""

    @classmethod
    def setUpClass(cls) -> None:
        """Render short synthetic stems and the current/control master paths."""
        cls.temporary = tempfile.TemporaryDirectory(prefix="program-headroom-")
        cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name)
        cls.inputs = (directory / "dialogue.wav", directory / "music.wav")
        _tone(cls.inputs[0], False)
        _tone(cls.inputs[1], True)
        cls.current = _actual_program(cls.inputs, directory)
        cls.control = directory / "float-control.wav"
        _float_control(cls.inputs, cls.control)
        cls.samples = {"current": _left_samples(cls.current),
                       "control": _left_samples(cls.control)}
        cls.mastered, cls.master_proof = {}, {}
        for name, source in (("current", cls.current), ("control", cls.control)):
            output = directory / f"{name}-mastered.wav"
            cls.master_proof[name] = _master_audio(source, output)
            cls.mastered[name] = _left_samples(output)

    def test_legal_stems_can_require_float_mix_headroom(self) -> None:
        """Neither input clips; their unity sum legitimately exceeds full scale."""
        for source in self.inputs:
            self.assertAlmostEqual(max(map(abs, _left_samples(source))), 0.8, places=6)
        self.assertGreater(max(map(abs, self.samples["control"])), 1.3)
        self.assertEqual(len(self.samples["control"]), TOTAL)

    def test_current_program_preserves_over_range_peaks_until_mastering(self) -> None:
        """The actual program renderer must not flatten the unclipped float sum."""
        actual, control = self.samples["current"], self.samples["control"]
        self.assertEqual(len(actual), len(control))
        difference = max(abs(left - right) for left, right in zip(actual, control))
        evidence = {"currentPeak": max(map(abs, actual)),
                    "floatPeak": max(map(abs, control)), "maximumError": difference}
        self.assertLess(difference, 1e-6, json.dumps(evidence))

    def test_float_control_remains_clean_through_existing_master_filter(self) -> None:
        """The proposed headroom boundary works without changing master DSP."""
        distortion = _distortion_ratio(self.mastered["control"])
        self.assertLess(distortion, 0.005, json.dumps(self.master_proof["control"]))
        self.assertAlmostEqual(self.master_proof["control"]["outputLufs"],
                               master.AUDIO["lufs_target"], delta=0.5)

    def test_compliant_master_loudness_must_not_hide_premix_distortion(self) -> None:
        """Post-master LUFS can pass even when the earlier integer mix clipped."""
        proof = self.master_proof["current"]
        self.assertAlmostEqual(proof["outputLufs"], master.AUDIO["lufs_target"], delta=0.5)
        self.assertLessEqual(proof["outputTruePeakDbtp"], master.AUDIO["true_peak_dbtp"])
        distortion = _distortion_ratio(self.mastered["current"])
        self.assertLess(distortion, 0.005,
                        json.dumps({"distortionRatio": distortion, **proof}))

    def test_low_level_float_mix_matches_legacy_nonclipping_waveform(self) -> None:
        """Removing the clamp must not alter timing, gain or channel policy."""
        directory = Path(self.temporary.name) / "low-level"
        directory.mkdir()
        inputs = (directory / "dialogue.wav", directory / "music.wav")
        _tone(inputs[0], False, 0.1)
        _tone(inputs[1], True, 0.1)
        current = _actual_program(inputs, directory)
        legacy = directory / "legacy.wav"
        graph = _mix_graph(2, TOTAL).replace(
            "sample_fmts=flt:channel_layouts=stereo[out]",
            "sample_fmts=s32:channel_layouts=stereo[out]")
        _ffmpeg(["-i", str(inputs[0]), "-i", str(inputs[1]), "-filter_complex", graph,
                 "-map", "[out]", "-ar", str(RATE), "-ac", "2", "-c:a", "pcm_s32le", str(legacy)])
        actual, reference = _left_samples(current), _left_samples(legacy)
        self.assertEqual(len(actual), TOTAL)
        self.assertEqual(len(actual), len(reference))
        self.assertLess(max(map(abs, actual)), 1.0)
        self.assertLess(max(abs(a - b) for a, b in zip(actual, reference)), 1e-6)

    def test_program_probe_rejects_legacy_integer_output(self) -> None:
        """A s32 file cannot acquire a float receipt by changing labels only."""
        request = SimpleNamespace(
            tools=SimpleNamespace(ffprobe_path=shutil.which("ffprobe")),
            dialogue_map={"projectSampleRate": RATE, "totalOutputSamples": TOTAL})
        with self.assertRaisesRegex(DialogueStemRenderError, "float PCM"):
            probe_program(str(self.inputs[1]), request)
        proof = probe_program(str(self.current), request)
        self.assertEqual((proof["codec"], proof["sampleFormat"]), ("pcm_f32le", "flt"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
