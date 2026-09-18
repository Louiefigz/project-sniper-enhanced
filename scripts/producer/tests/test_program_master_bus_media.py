"""Actual synthetic full-program PCM/ducking tests, not perceptual approval."""
from __future__ import annotations

import contextlib
import copy
import array
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import render as renderer
from audio.program_master_bus import build_program_master, float_audio_clock, verify_program_master
from audio.program_master_delivery import deliver_program_master
from audio.program_master_cache import load_program_master
from audio.audio_mix_picture import packet_signature
from audio.master import MasterSpec, encode_picture_only
from audio.render_audio_authority import run_audio
from audio.render_audio_authority import SOURCE_FLOAT_POLICY_V2, admit_audio
from cut_preview_io import digest, file_hash
from test_render_audio_cache_media import with_synthetic_music
from test_render_source_audio_media import _context, _fixture


class ProgramMasterMediaTests(unittest.TestCase):
    """Prove retained float clock, whole-program measurement and explicit mix identity."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(tempfile.mkdtemp(prefix="sniper-program-master-", dir="/private/tmp"))
        cls.plan, cls.manifest = _fixture(cls.root)
        cls.manifest = with_synthetic_music(cls.root, cls.manifest)
        cls.ctx = _context(cls.root, cls.plan, cls.manifest, SOURCE_FLOAT_POLICY_V2)
        cls.ctx.audio_admission = admit_audio(cls.plan, cls.manifest, (SOURCE_FLOAT_POLICY_V2, False))
        with (cls.root / "cut.log").open("w") as log, contextlib.redirect_stdout(log):
            renderer.compile_stage(cls.ctx)
            cls.picture = renderer.cut_stage(cls.ctx)
        cls.bus = cls.ctx.source_audio_bus
        mastered_picture = cls.root / "picture-master.mp4"
        rendered = encode_picture_only(MasterSpec(src=cls.picture, out=str(mastered_picture),
            fps=30, fps_exact="30000/1001", frame_count=cls.bus.frames, duration=4.004))
        if not rendered["ok"]:
            raise RuntimeError(rendered)
        cls.picture = str(mastered_picture)
        cls.plain = build_program_master(cls.bus, cls.plan)
        cls.music_plan = {**copy.deepcopy(cls.plan),
            "music": {"enabled": True, "assetId": "test-only-bed", "gapDb": 12}}
        cls.mixed = build_program_master(cls.bus, cls.music_plan)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.root)

    def test_plain_master_retains_source_clock_and_full_output_measurement(self) -> None:
        receipt = self.plain.receipt
        self.assertEqual(receipt["totalSamples"], 192192)
        self.assertEqual(receipt["masteredAudio"]["codec"], "pcm_f32le")
        self.assertTrue(receipt["wholeProgramMeasurement"]["qualified"])
        self.assertTrue(receipt["wholeProgramMeasurement"]["audioDecodeSucceeded"])
        self.assertIsNone(receipt["detectorReference"])
        self.assertEqual(receipt["premaster"]["sha256"], self.bus.sha256)
        self.assertEqual(receipt["scope"], "full-program-audio-not-delivery-approval")
        verify_program_master(self.plain, self.plan)

    def test_music_is_float_whole_sum_and_never_changes_audible_source_bus(self) -> None:
        receipt = self.mixed.receipt
        self.assertEqual(file_hash(Path(self.bus.path)), self.bus.sha256)
        self.assertNotEqual(receipt["premaster"]["sha256"], self.bus.sha256)
        self.assertEqual(float_audio_clock(receipt["premaster"]["path"], self.bus)["samples"], self.bus.samples)
        self.assertEqual(receipt["detectorReference"]["appliedTo"], "sidechain-only")
        self.assertTrue(receipt["wholeProgramMeasurement"]["qualified"])
        self.assertNotEqual(receipt["audioProgramInputHash"], self.plain.receipt["audioProgramInputHash"])
        verify_program_master(self.mixed, self.music_plan)

    def test_changed_music_settings_and_bytes_invalidate_held_master(self) -> None:
        plan = copy.deepcopy(self.music_plan)
        plan["music"]["gapDb"] = 11
        with self.assertRaisesRegex(RuntimeError, "settings changed"):
            verify_program_master(self.mixed, plan)
        source = Path(self.mixed.receipt["music"]["path"])
        before = source.read_bytes()
        try:
            source.write_bytes(before + b"TEST ONLY music drift")
            with self.assertRaisesRegex(RuntimeError, "music source changed"):
                verify_program_master(self.mixed, self.music_plan)
        finally:
            source.write_bytes(before)

    def test_unmastered_mix_contains_exact_raw_dialogue_plus_bed_only(self) -> None:
        record = self.mixed.receipt
        def decoded(path: str) -> array.array:
            value = array.array("f")
            value.frombytes(run_audio(["ffmpeg", "-nostdin", "-v", "error", "-i", path,
                "-map", "0:a:0", "-c:a", "pcm_f32le", "-f", "f32le", "-"]))
            return value
        raw = decoded(self.bus.path)
        bed = decoded(record["music"]["bedPath"])
        mixed = decoded(record["premaster"]["path"])
        self.assertEqual(len(raw), len(bed))
        self.assertEqual(len(raw), len(mixed))
        error = max(abs(output - (speech + music)) for speech, music, output in zip(raw, bed, mixed))
        self.assertLess(error, 5e-8, "detector normalization must never boost the audible dialogue bus")

    def test_actual_aac_uses_same_master_with_exact_picture_packets_and_sample_clock(self) -> None:
        """Require actual AAC continuity against the master before publication."""
        output = self.root / "qualified-program.mp4"
        result = deliver_program_master(self.mixed, self.music_plan, (self.picture, str(output)))
        self.assertTrue(result["delivery"]["qualified"])
        self.assertEqual(result["audioClock"]["presentedSamples"], self.bus.samples)
        self.assertTrue(result["localSignal"]["passed"])
        self.assertEqual(result["localSignal"]["failedWindowCount"], 0)
        self.assertTrue(result["localSignal"]["inputsStable"])
        self.assertEqual(result["localSignal"]["candidateSha256"], result["measuredCandidateSha256"])
        self.assertTrue(result["audioClock"]["packetClock"]["allPacketsChecked"])
        self.assertLessEqual(result["audioClock"]["trailingPaddingSamples"], 1023)
        self.assertEqual(packet_signature(self.picture, "v:0"), packet_signature(str(output), "v:0"))
        self.assertEqual(result["programMasterReceiptHash"], self.mixed.receipt["receiptHash"])

    def test_failed_aac_gate_keeps_existing_final_and_sidecar(self) -> None:
        output, sidecar = self.root / "approved.mp4", self.root / "approved.mp4.assembled.json"
        output.write_bytes(b"TEST ONLY approved final sentinel")
        sidecar.write_bytes(b"TEST ONLY approved sidecar sentinel")
        with patch("audio.audio_mix_delivery.measure_delivery", return_value={"qualified": False,
                   "lufsResidual": 5, "truePeakExcessDb": 0}):
            with self.assertRaisesRegex(RuntimeError, "delivery unqualified"):
                deliver_program_master(self.mixed, self.music_plan, (self.picture, str(output)))
        self.assertEqual(output.read_bytes(), b"TEST ONLY approved final sentinel")
        self.assertEqual(sidecar.read_bytes(), b"TEST ONLY approved sidecar sentinel")

    def test_changed_master_bytes_reject_without_touching_previous_master(self) -> None:
        path = Path(self.mixed.path)
        before = path.read_bytes()
        try:
            path.write_bytes(before + b"TEST ONLY master drift")
            with self.assertRaisesRegex(RuntimeError, "master bytes changed"):
                verify_program_master(self.mixed, self.music_plan)
        finally:
            path.write_bytes(before)

    def test_old_mix_policy_and_missing_clock_cannot_be_relabelled_as_current(self) -> None:
        """Even self-consistent old policy/clock metadata is not a current bus contract."""
        path = Path(self.mixed.directory) / 'master-receipt.json'
        before = path.read_bytes()
        try:
            for mutate in ('old-policy', 'missing-clock'):
                record = copy.deepcopy(self.mixed.receipt)
                if mutate == 'old-policy':
                    record['audioMixPolicyVersion'] = 1
                else:
                    record['masteredAudio'].pop('samples')
                record['receiptHash'] = digest({key: value for key, value in record.items() if key != 'receiptHash'})
                path.write_text(json.dumps(record))
                with self.subTest(mutate=mutate), self.assertRaisesRegex(RuntimeError, 'stale|malformed'):
                    load_program_master(self.bus, self.music_plan, (str(path), record['receiptHash']))
        finally:
            path.write_bytes(before)

    def test_failed_whole_program_measurement_retains_unapproved_candidate(self) -> None:
        before = set(Path(self.bus.directory).glob(".program-master-v2-*"))
        with patch("audio.program_master_bus.measure_delivery", return_value={"qualified": False}):
            with self.assertRaisesRegex(RuntimeError, "unqualified; retained candidate"):
                build_program_master(self.bus, self.plan)
        added = set(Path(self.bus.directory).glob(".program-master-v2-*")) - before
        self.assertEqual(len(added), 1)
        self.assertTrue((added.pop() / "master-failed.json").is_file())
        verify_program_master(self.plain, self.plan)


if __name__ == "__main__":
    unittest.main(verbosity=2)
