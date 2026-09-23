"""Actual synthetic finishing on the retained float bus; numbers, not listening approval."""
from __future__ import annotations

import array
import contextlib
import copy
import json
import tempfile
import unittest
from unittest import mock
from dataclasses import replace
from pathlib import Path

import render as renderer
from audio.audio_enhance import build_filter
from audio.program_finish_bus import measure_chain_latency, render_finishing, _sfx_sources, _render_program
from audio.program_finish_contract import finishing_request, SfxCue
from audio.program_master_bus import build_program_master, verify_program_master
from audio.program_mix_bus import build_program_mix
from audio.program_master_cache import load_program_master
from audio.program_master_excerpt import ExcerptRanges, extract_master_audio
from audio.program_master_selection import SelectionContext, capture_master_selection
from audio.render_audio_authority import SOURCE_FLOAT_POLICY_V2, admit_audio, run_audio
from audio.render_audio_cache import write_source_bus_pointer
from audio.sfx_library import sfx_path
from cut_preview_io import digest, file_hash
from producer_config import AUDIO
from test_render_audio_cache_media import with_synthetic_music
from test_render_source_audio_media import _context, _fixture

RATE = 48_000
GAIN = [{"outStart": 1.0, "outEnd": 1.5, "dB": 6}]
FINISHING = {"audioEnhance": {"preset": "voice"}, "audioGain": GAIN}


def decoded(path: str) -> array.array:
    """Whole stereo float program through an independent decode, never production trims."""
    value = array.array("f")
    value.frombytes(run_audio(["ffmpeg", "-nostdin", "-v", "error", "-i", path, "-map", "0:a:0",
        "-af", "aformat=sample_fmts=flt:channel_layouts=stereo", "-ar", str(RATE),
        "-c:a", "pcm_f32le", "-f", "f32le", "-"]))
    return value


def rms(samples: array.array, start_s: float, end_s: float) -> float:
    """Left-channel RMS over an output-time window."""
    lo, hi = round(start_s * RATE), round(end_s * RATE)
    return (sum(samples[2 * i] ** 2 for i in range(lo, hi)) / (hi - lo)) ** 0.5


def max_diff(a: array.array, b: array.array, start_s: float, end_s: float) -> float:
    lo, hi = round(start_s * RATE), round(end_s * RATE)
    return max(abs(a[2 * i + c] - b[2 * i + c]) for i in range(lo, hi) for c in (0, 1))


class ProgramFinishMediaTests(unittest.TestCase):
    """Retain artifacts for inspection; assert exact clocks, sums and invalidation."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(tempfile.mkdtemp(prefix="sniper-finishing-", dir="/private/tmp"))
        print(f"Synthetic finishing evidence: {cls.root}", flush=True)
        cls.plan, cls.manifest = _fixture(cls.root)
        cls.manifest = with_synthetic_music(cls.root, cls.manifest)
        cls.ctx = _context(cls.root, cls.plan, cls.manifest, SOURCE_FLOAT_POLICY_V2)
        cls.ctx.audio_admission = admit_audio(cls.plan, cls.manifest, (SOURCE_FLOAT_POLICY_V2, False))
        with (cls.root / "cut.log").open("w") as log, contextlib.redirect_stdout(log):
            renderer.compile_stage(cls.ctx)
            cls.base = renderer.cut_stage(cls.ctx)
        cls.bus = cls.ctx.source_audio_bus
        write_source_bus_pointer(cls.base, cls.ctx.out_dir, cls.bus)
        cls.ffmpeg = cls.bus.admission.tools["ffmpeg"]["path"]
        cls.raw = decoded(cls.bus.path)
        cls.finished_plan = {**copy.deepcopy(cls.plan), **copy.deepcopy(FINISHING),
                             "music": {"enabled": True, "assetId": "test-only-bed", "gapDb": 12}}
        cls.plain = build_program_master(cls.bus, cls.plan)
        cls.finished = build_program_master(cls.bus, cls.finished_plan)

    def _directory(self) -> Path:
        return Path(tempfile.mkdtemp(prefix=".finish-test-", dir=self.bus.directory))

    def test_01_measured_cleanup_latency_is_removed_for_every_installed_chain(self) -> None:
        click = self.root / "click-bus.wav"
        positions = (30_000, 90_000, 150_000, self.bus.samples - 60)   # the last one sits inside the filter delay
        expression = "+".join(f"if(eq(n,{p}),0.8,0)" for p in positions)
        run_audio([self.ffmpeg, "-nostdin", "-v", "error", "-f", "lavfi", "-i",
            f"aevalsrc='{expression}|{expression}':s={RATE}:d={self.bus.samples / RATE:.6f}",
            "-af", f"atrim=end_sample={self.bus.samples}", "-c:a", "pcm_f32le", str(click)])
        fake = replace(self.bus, path=str(click), sha256=file_hash(click))
        latencies = {}
        for preset in ("voice", "voice-strong", "voice-rnn"):
            with self.subTest(preset=preset):
                lag = measure_chain_latency(self.ffmpeg, build_filter(preset))
                latencies[preset] = lag
                self.assertGreater(lag, 0, "these installed chains are known to delay the signal")
                finished = render_finishing(fake, {**self.plan, "audioEnhance": {"preset": preset}}, self._directory())
                self.assertEqual(finished.receipt["cleanup"]["measuredLatencySamples"], lag)
                samples = decoded(finished.dialogue_path)
                self.assertEqual(len(samples), 2 * self.bus.samples)
                for position in positions:
                    window = range(position - 2400, min(position + 2400, self.bus.samples))
                    peak = max(window, key=lambda i: abs(samples[2 * i]))
                    self.assertEqual(peak, position, f"{preset}: click moved by {peak - position} samples")
                    self.assertGreater(abs(samples[2 * position]), 0.05,
                                       f"{preset}: the click at {position} must survive, even inside the filter delay")
        (self.root / "measured-latency.json").write_text(json.dumps(latencies))

    def test_01b_cleanup_never_silences_the_final_moments_of_the_program(self) -> None:
        """Codex pre-integration QC request: the audio tail must be processed source, not padding."""
        end = self.bus.samples / RATE
        for preset in ("voice", "voice-strong", "voice-rnn"):
            with self.subTest(preset=preset):
                finished = render_finishing(self.bus, {**self.plan, "audioEnhance": {"preset": preset}}, self._directory())
                out = decoded(finished.dialogue_path)
                latency = finished.receipt["cleanup"]["measuredLatencySamples"]
                tail, before_tail = rms(out, end - latency / RATE, end), rms(out, end - 2 * latency / RATE, end - latency / RATE)
                self.assertGreater(tail, 0.5 * before_tail,
                                   f"{preset}: the last {latency} samples collapsed ({tail:.5f} vs {before_tail:.5f})")
                self.assertGreater(tail, 0.05 * rms(self.raw, end - latency / RATE, end), f"{preset}: tail is silence")

    def test_01c_tail_boundary_equals_expected_filtered_response_not_padding(self) -> None:
        """Codex-confirmed boundary defect: the cleanup chain's delayed tail must be preserved.

        Fixture: impulses inside the final 480 and 1200 source samples plus a speech-like
        modulated harmonic burst over the last 200 ms, on a quiet 440 Hz bed. Oracle: the
        same installed chain run on the program padded far beyond its delay, then sliced by
        the measured delay. A causal filter's output for the program range cannot depend on
        later input, so the finished program must equal that expected filtered response over
        its WHOLE length (no offset, no change to unaffected audio, no added duration). The
        negative control reproduces the defect: without input padding the final samples are
        not the expected response (digital silence for the FFT chains)."""
        from audio.audio_mix_bed import AFMT
        total = self.bus.samples
        click = self.root / "tail-click-bus.wav"
        positions = (total - 900, total - 300)
        speech_like = (f"if(gte(n,{total - 9600}),0.3*(sin(2*PI*180*t)+0.5*sin(2*PI*360*t)+0.3*sin(2*PI*720*t))"
                       f"*(0.5+0.5*sin(2*PI*8*t)),0)")
        expression = "+".join(f"if(eq(n,{p}),0.8,0)" for p in positions) + "+0.02*sin(2*PI*440*t)+" + speech_like
        run_audio([self.ffmpeg, "-nostdin", "-v", "error", "-f", "lavfi", "-i",
            f"aevalsrc='{expression}|{expression}':s={RATE}:d={total / RATE:.6f}",
            "-af", f"atrim=end_sample={total}", "-c:a", "pcm_f32le", str(click)])
        fake = replace(self.bus, path=str(click), sha256=file_hash(click))
        report = {}
        for preset in ("voice", "voice-strong", "voice-rnn"):
            with self.subTest(preset=preset):
                chain = build_filter(preset)
                lag = measure_chain_latency(self.ffmpeg, chain)
                finished = decoded(render_finishing(fake, {**self.plan, "audioEnhance": {"preset": preset}},
                                                    self._directory()).dialogue_path)
                oracle = array.array("f")
                oracle.frombytes(run_audio([self.ffmpeg, "-nostdin", "-v", "error", "-i", str(click), "-af",
                    f"apad=pad_len={8 * lag + 48000},{chain},{AFMT}", "-c:a", "pcm_f32le", "-f", "f32le", "-"]))
                expected = oracle[2 * lag:2 * (lag + total)]
                self.assertEqual(len(finished), 2 * total, f"{preset}: no added or missing output duration")
                self.assertEqual(len(finished), len(expected))
                whole = max(abs(a - b) for a, b in zip(finished, expected))
                self.assertLess(whole, 1e-6, f"{preset}: whole program must equal the expected filtered response")
                tail = slice(2 * (total - 1200), 2 * total)
                self.assertGreater(max(abs(v) for v in expected[tail]), 0.05, f"{preset}: oracle tail carries content")
                for position in positions:
                    self.assertGreater(abs(finished[2 * position]), 0.05, f"{preset}: impulse at {position} survived")
                control = array.array("f")
                control.frombytes(run_audio([self.ffmpeg, "-nostdin", "-v", "error", "-i", str(click), "-af",
                    f"{chain},atrim=start_sample={lag},asetpts=N/SR/TB,{AFMT},apad=whole_len={total},atrim=end_sample={total}",
                    "-c:a", "pcm_f32le", "-f", "f32le", "-"]))
                lost = slice(2 * (total - lag), 2 * total)
                control_error = max(abs(a - b) for a, b in zip(control[lost], expected[lost]))
                control_peak = max(abs(v) for v in control[lost])
                self.assertGreater(control_error, 0.05, f"{preset}: unpadded control must reproduce the tail defect")
                report[preset] = {"measuredLatencySamples": lag, "wholeProgramMaxError": whole,
                                  "unpaddedTailMaxError": control_error, "unpaddedTailPeak": control_peak}
        (self.root / "tail-boundary-report.json").write_text(json.dumps(report, indent=2))
        print("tail boundary report:", json.dumps(report), flush=True)

    def test_02_gain_window_hits_requested_edited_interval_with_smooth_edges(self) -> None:
        finished = render_finishing(self.bus, {**self.plan, "audioGain": GAIN}, self._directory())
        self.assertEqual(finished.dialogue_path, finished.program_path)
        out = decoded(finished.dialogue_path)
        self.assertEqual(len(out), len(self.raw))
        target = 10 ** (6 / 20)
        # Output [1.0, 1.5] is source right-2 [1.5, 2.0]: raw-1's 1.0..3.5 was cut away.
        self.assertAlmostEqual(rms(out, 1.08, 1.42) / rms(self.raw, 1.08, 1.42), target, delta=0.02)
        self.assertAlmostEqual(rms(out, 1.29, 1.33) / rms(self.raw, 1.29, 1.33), target, delta=0.03)
        self.assertLess(max_diff(out, self.raw, 0.0, 0.99), 1e-7)
        self.assertLess(max_diff(out, self.raw, 1.51, self.bus.samples / RATE), 1e-7)
        early = rms(out, 1.005, 1.015) / rms(self.raw, 1.005, 1.015)
        late = rms(out, 1.035, 1.045) / rms(self.raw, 1.035, 1.045)
        self.assertTrue(1.03 < early < late < target - 0.03, f"edges must ramp, not step: {early} {late}")
        self.assertEqual(finished.receipt["gain"]["rampS"], 0.05)

    def test_03_audio_kernel_synthetic_cues_sum_after_cleanup_on_exact_samples(self) -> None:
        # Audio-kernel test only: synthetic DTOs never admit a retired visual plan.
        plan = {**self.plan, "audioEnhance": {"preset": "voice"}}
        directory = self._directory()
        finished = render_finishing(self.bus, plan, directory)
        request = replace(finishing_request(plan, self.bus.samples / RATE), sfx=(
            SfxCue(1.0, True, 0.3, None), SfxCue(2.5, "click", 0.01, sfx_path("click"))))
        sources = _sfx_sources(request, directory)
        output = _render_program(self.bus, (request, finished.dialogue_path, sources), directory)
        dialogue, program = decoded(finished.dialogue_path), decoded(output)
        self.assertEqual(len(program), 2 * self.bus.samples)
        whoosh, click = decoded(sources["engine-whoosh"]["path"]), decoded(sfx_path("click"))
        self.assertEqual(sources["click"]["path"], sfx_path("click"))
        expected = array.array("f", dialogue)
        for start, effect in ((33_600, whoosh), (119_520, click)):
            for index in range(min(len(effect), len(expected) - 2 * start)):
                expected[2 * start + index] += effect[index]
        self.assertLess(max(abs(a - b) for a, b in zip(program, expected)), 1e-5,
                        "program must be the cleaned dialogue plus the delayed SFX, nothing else")
        residual = [program[i] - dialogue[i] for i in range(0, 2 * self.bus.samples, 2)]
        self.assertLess(max(abs(v) for v in residual[:33_600]), 1e-7, "no SFX before its exact start sample")
        self.assertGreater(max(abs(v) for v in residual[33_600:33_600 + 4800]), 1e-4, "whoosh starts at its start sample")
        # Existing engine semantics: playback starts WHOOSH_LEAD_S (0.30 s) before the seam so the
        # swell lands on it. The file's own loudest 10 ms window must therefore appear in the
        # program exactly that many samples after the start sample, never re-timed by the sum.
        def loudest(values: list[float], offset: int, length: int) -> int:
            return max(range(0, length - 480, 480), key=lambda i: sum(v ** 2 for v in values[offset + i:offset + i + 480]))
        whoosh_left = [whoosh[i] for i in range(0, len(whoosh), 2)]
        self.assertEqual(loudest(residual, 33_600, len(whoosh_left)), loudest(whoosh_left, 0, len(whoosh_left)))

    def test_04_finished_music_master_keeps_float_sum_ducks_on_finished_dialogue_and_qualifies(self) -> None:
        receipt = self.finished.receipt
        finishing = receipt["finishing"]
        self.assertEqual(finishing["settings"]["audioGain"], [{"outStart": 1.0, "outEnd": 1.5, "dB": 6.0}])
        self.assertEqual(finishing["settings"]["audioEnhance"], {"preset": "voice"})
        self.assertEqual(finishing["settings"]["sfx"], [])
        self.assertIsNone(finishing["sfx"])
        self.assertEqual(finishing["order"], "cleanup->gain->sfx->music->master")
        self.assertEqual(receipt["detectorReference"]["keySource"], "finished-dialogue-without-sfx")
        self.assertEqual(receipt["detectorReference"]["keySha256"], finishing["dialogue"]["sha256"])
        self.assertEqual(receipt["detectorReference"]["appliedTo"], "sidechain-only")
        program, bed, premaster = (decoded(finishing["program"]["path"]), decoded(receipt["music"]["bedPath"]),
                                   decoded(receipt["premaster"]["path"]))
        self.assertEqual(len(program), len(bed))
        self.assertEqual(len(program), len(premaster))
        self.assertLess(max(abs(out - (voice + music)) for voice, music, out in zip(program, bed, premaster)), 5e-8,
                        "premaster must be the exact float sum; no master before the whole-program master")
        depth = receipt["music"]["duckDepth"]
        self.assertTrue(depth["measured"], depth)
        # A steady synthetic tone is not speech: depth here only proves the bed is never louder
        # under the finished dialogue than in its silence gap. Real-speech depth is measured in
        # the retained listenable evidence run, not asserted from this fixture.
        self.assertLessEqual(depth["bed_speech_db"], depth["bed_gap_db"] + 0.1, depth)
        measured = receipt["wholeProgramMeasurement"]
        self.assertTrue(measured["qualified"], measured)
        self.assertEqual((measured["lufsTarget"], measured["truePeakCeilingDbtp"]), (AUDIO["lufs_target"], AUDIO["true_peak_dbtp"]))
        self.assertEqual(receipt["totalSamples"], self.bus.samples)
        self.assertNotEqual(receipt["audioProgramInputHash"], self.plain.receipt["audioProgramInputHash"])
        verify_program_master(self.finished, self.finished_plan)
        reopened = load_program_master(self.bus, self.finished_plan,
            (str(Path(self.finished.directory) / "master-receipt.json"), receipt["receiptHash"]))
        self.assertEqual(reopened.receipt, receipt)
        other = copy.deepcopy(self.finished_plan)
        other["audioGain"][0]["dB"] = 3
        third = build_program_master(self.bus, other)
        self.assertNotEqual(third.receipt["audioProgramInputHash"], receipt["audioProgramInputHash"])
        self.assertNotEqual(third.receipt["finishing"]["program"]["sha256"], finishing["program"]["sha256"])

    def test_05_no_finishing_keeps_pristine_bus_and_null_finishing(self) -> None:
        receipt = self.plain.receipt
        self.assertIsNone(receipt["finishing"])
        self.assertIsNone(receipt["detectorReference"])
        self.assertEqual(receipt["premaster"], {"path": self.bus.path, "sha256": self.bus.sha256})
        self.assertEqual(file_hash(Path(self.bus.path)), self.bus.sha256)
        verify_program_master(self.plain, self.plan)

    def test_06_changed_settings_or_finished_stems_invalidate_retained_master(self) -> None:
        for mutate in ({"audioGain": [{"outStart": 1.0, "outEnd": 1.5, "dB": 5}]},
                       {"audioEnhance": {"preset": "voice-strong"}}, {"audioEnhance": None}):
            plan = {**copy.deepcopy(self.finished_plan), **mutate}
            plan = {key: value for key, value in plan.items() if value is not None}
            with self.subTest(mutate=mutate), self.assertRaisesRegex(RuntimeError, "finishing settings changed"):
                verify_program_master(self.finished, plan)
        path = Path(self.finished.receipt["finishing"]["dialogue"]["path"])
        before = path.read_bytes()
        try:
            path.write_bytes(before + b"TEST ONLY stem drift")
            with self.assertRaisesRegex(RuntimeError, "bytes changed"):
                verify_program_master(self.finished, self.finished_plan)
        finally:
            path.write_bytes(before)
        verify_program_master(self.finished, self.finished_plan)

    def test_07_opening_excerpt_is_exact_slice_of_the_finished_master(self) -> None:
        plan_path = Path(self.ctx.plan_path)
        original = plan_path.read_bytes()
        try:
            plan_path.write_text(json.dumps(self.finished_plan))
            context = SelectionContext(plan_path, Path(self.manifest["_path"]), Path(self.ctx.out_dir),
                Path(self.base), Path(self.finished.directory) / "selection-event.json")
            selection = capture_master_selection(self.finished, self.finished_plan, context)
            self.assertEqual(selection.master.receipt["finishing"]["settings"], self.finished.receipt["finishing"]["settings"])
            output = Path(tempfile.mkdtemp(prefix="attempt-", dir=self.root))
            result = extract_master_audio(selection, ExcerptRanges((0, 30), (0, 30), "a" * 64), output, lambda: None)
            core = result["core"]
            self.assertEqual((core["startSample"], core["endSampleExclusive"]), (0, 48_048))
            whole = decoded(self.finished.path)
            self.assertEqual(decoded(core["path"]).tobytes(), whole[:2 * 48_048].tobytes())
            self.assertFalse(result["normalizationApplied"])
        finally:
            plan_path.write_bytes(original)

    def test_08_retired_transitions_fail_before_media_and_keep_prior_master(self) -> None:
        before = set(Path(self.bus.directory).iterdir())
        for kind in ("white-flash", "light-leak", "zoom-pull"):
            plan = {**self.plan, "transitions": [{"outTime": 1.0, "kind": kind, "sfx": True}]}
            with self.subTest(kind=kind), mock.patch("subprocess.run") as run:
                with self.assertRaisesRegex(RuntimeError, "retired"):
                    build_program_master(self.bus, plan)
                run.assert_not_called()
            self.assertEqual(set(Path(self.bus.directory).iterdir()), before)
            target = self.root / f"TEST-retired-mix-{kind}"
            with mock.patch("audio.program_mix_bus.verify_source_bus") as verify, mock.patch("subprocess.run") as run:
                with self.assertRaisesRegex(RuntimeError, "retired"):
                    build_program_mix(self.bus, plan, target)
                verify.assert_not_called()
                run.assert_not_called()
            self.assertFalse(target.exists())
            self.assertEqual(set(Path(self.bus.directory).iterdir()), before)
        with self.assertRaisesRegex(RuntimeError, "could not be established"):
            measure_chain_latency(self.ffmpeg, "volume=0")
        with self.assertRaisesRegex(RuntimeError, "sample count"):
            measure_chain_latency(self.ffmpeg, "atrim=start_sample=10")
        verify_program_master(self.finished, self.finished_plan)

    def test_09_relabelled_finishing_receipt_cannot_load(self) -> None:
        path = Path(self.finished.directory) / "master-receipt.json"
        before = path.read_bytes()
        try:
            record = copy.deepcopy(self.finished.receipt)
            record["finishing"]["settings"]["audioGain"][0]["dB"] = 5.0
            record["receiptHash"] = digest({key: value for key, value in record.items() if key != "receiptHash"})
            path.write_text(json.dumps(record))
            with self.assertRaisesRegex(RuntimeError, "input hash changed|settings changed"):
                load_program_master(self.bus, self.finished_plan, (str(path), record["receiptHash"]))
        finally:
            path.write_bytes(before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
