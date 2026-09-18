"""Actual ordinary source-float base/assembly/Audit B, using synthetic media."""
from __future__ import annotations

import contextlib
import copy
import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import assemble
import render as renderer
from audio.audio_mix_picture import packet_signature
from audio.assemble_source_audio import PROGRAM_AUDIO_POINTER
from audio.render_audio_authority import SOURCE_FLOAT_POLICY_V2
from cut_delivery_authority import seal_render_delivery, verify_delivered_cuts
from cut_preview_io import bound_json, file_hash
from test_render_audio_cache_media import with_synthetic_music
from test_render_source_audio_media import _context, _fixture


class SourceFloatAssemblyMediaTests(unittest.TestCase):
    """Keep generated cohort/media on disk for independent failure inspection."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(tempfile.mkdtemp(prefix="sniper-ordinary-assembly-", dir="/private/tmp"))
        cls.plan, cls.manifest = _fixture(cls.root)
        chord = ("aevalsrc='0.04*(sin(2*PI*(220+55*floor(t/0.5))*t)"
                 "+sin(2*PI*(277.18+69.295*floor(t/0.5))*t)"
                 "+sin(2*PI*(329.63+82.4075*floor(t/0.5))*t))':s=48000:d=3")
        cls.manifest = with_synthetic_music(cls.root, cls.manifest, chord)
        cls.ctx = _context(cls.root, cls.plan, cls.manifest, SOURCE_FLOAT_POLICY_V2)
        cls.ctx.skip_graphics = True
        cls.output = Path(cls.ctx.out_dir)
        with (cls.root / "base.log").open("w") as log, contextlib.redirect_stdout(log):
            renderer.render(cls.ctx, audit=True)
        cls.base = cls.output / "base.mp4"
        os.replace(cls.output / "final.mp4", cls.base)
        seal_render_delivery(str(cls.output), str(cls.base), cls.plan, True)
        cls.job = assemble.AssembleJob(str(cls.base), cls.plan, str(cls.output / "final.mp4"),
            None, fingerprint_path=str(cls.output / "base.fingerprint.json"),
            manifest=cls.manifest["_path"], audio_clock_policy=SOURCE_FLOAT_POLICY_V2,
            plan_path=cls.ctx.plan_path, source_bus_receipt_hash=cls.ctx.source_audio_bus.receipt["receiptHash"])
        with (cls.root / "assemble.log").open("w") as log, contextlib.redirect_stdout(log):
            cls.result = assemble.assemble(cls.job)

    def test_actual_assembly_full_qc_keeps_exact_picture_and_source_sample_clock(self) -> None:
        self.assertEqual(self.result["audioClockPolicy"], SOURCE_FLOAT_POLICY_V2)
        self.assertTrue(self.result["delivery"]["qualified"])
        self.assertEqual(packet_signature(str(self.base), "v:0"), packet_signature(self.job.out, "v:0"))
        pointer = bound_json(self.output / PROGRAM_AUDIO_POINTER)
        receipt = bound_json(Path(pointer["programMasterReceiptPath"]))
        self.assertEqual(receipt["totalSamples"], 192192)
        audit = bound_json(self.output / "audit_report.json")
        self.assertNotEqual(audit["overall"], "fail")
        self.assertEqual(audit["final"], self.job.out)
        self.assertEqual(audit["finalSha256"], file_hash(Path(self.job.out)))
        self.assertNotEqual(audit["measuredCandidatePath"], audit["final"])
        verify_delivered_cuts(str(self.output), self.job.out, self.plan)

    def test_failed_actual_candidate_audit_preserves_previous_final_and_sidecar(self) -> None:
        before = {name: (self.output / name).read_bytes()
                  for name in ("final.mp4", "final.mp4.assembled.json")}
        from audio import assemble_source_audio as source_assembly
        original = source_assembly.run_audit
        def failing(directory: str):
            report = original(directory)
            return replace(report, overall="fail", exit_code=1)
        with patch.object(source_assembly, "run_audit", side_effect=failing):
            with self.assertRaisesRegex(RuntimeError, "full Audit B failed"):
                assemble.assemble(self.job)
        for name, value in before.items():
            self.assertEqual((self.output / name).read_bytes(), value)

    def test_changed_cut_cannot_reuse_raw_bus_or_legacy_audio_rebuild(self) -> None:
        changed = copy.deepcopy(self.plan)
        changed["cutTrack"][0]["end"] = 0.9
        with self.assertRaisesRegex(RuntimeError, "current v2 base"):
            assemble.assemble(replace(self.job, plan=changed))
        self.assertEqual(assemble._base_state(str(self.base), self.plan,
            self.job.fingerprint_path, "legacy-v1"), "stale")

    def test_ungraphed_music_revision_renders_picture_and_builds_one_new_full_master(self) -> None:
        plan = {**copy.deepcopy(self.plan), "music": {
            "enabled": True, "assetId": "test-only-bed", "gapDb": 12}}
        before_picture = packet_signature(self.job.out, "v:0")
        before_pointer = bound_json(self.output / PROGRAM_AUDIO_POINTER)
        original_plan = Path(self.ctx.plan_path).read_bytes()
        Path(self.ctx.plan_path).write_text(json.dumps(plan))
        try:
            with patch("assemble._assemble_captioned", wraps=assemble._assemble_captioned) as compositor:
                result = assemble.assemble(replace(self.job, plan=plan))
            compositor.assert_called_once()
            self.assertFalse(result.get("pictureReusedForAudioRevision", False))
            self.assertTrue(result["delivery"]["qualified"])
            self.assertEqual(before_picture, packet_signature(self.job.out, "v:0"))
            after = bound_json(self.output / PROGRAM_AUDIO_POINTER)
            self.assertNotEqual(before_pointer["audioProgramInputHash"], after["audioProgramInputHash"])
            self.assertEqual(before_pointer["pictureReuseInputHash"], after["pictureReuseInputHash"])
            receipt = bound_json(Path(after["programMasterReceiptPath"]))
            self.assertEqual(receipt["totalSamples"], 192192)
            self.assertEqual(receipt["detectorReference"]["appliedTo"], "sidechain-only")
        finally:
            Path(self.ctx.plan_path).write_bytes(original_plan)

    def test_mutation_between_complete_audit_and_promotion_rejects(self) -> None:
        from audio import assemble_source_audio as source_assembly
        original = source_assembly._private_audit
        before = {name: (self.output / name).read_bytes()
                  for name in ("final.mp4", "final.mp4.assembled.json")}
        def mutate(candidate, output: str):
            result = original(candidate, output)
            with open(output, "ab") as handle:
                handle.write(b"TEST ONLY mutation after complete Audit B")
            return result
        with patch.object(source_assembly, "_private_audit", side_effect=mutate):
            with self.assertRaisesRegex(RuntimeError, "changed between audit and promotion"):
                assemble.assemble(self.job)
        for name, value in before.items():
            self.assertEqual((self.output / name).read_bytes(), value)


if __name__ == "__main__":
    unittest.main(verbosity=2)
