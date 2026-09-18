"""Actual held assembly through owned prefix hooks and whole-output audio/QC.

Tiny generated media only. No OCI/template qualification, original opening
approval, current body activation or creator listening is claimed by this test.
"""
from __future__ import annotations

import contextlib
import shutil
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from assemble import AssembleJob, assemble
from audio import assemble_source_audio as source
from audio.assemble_publication import copy_verified
from audio.audio_mix_picture import packet_signature
from audio.program_audio_clock import aac_audio_clock
from cut_preview_io import bound_json, file_hash
from graphics.owned_execution import GraphicsComposition, OwnedGraphicsExecution
from opening_prefix_composition import PrefixCompositionJob, compose_verified_prefix
from opening_prefix_contract import CompositorPrefixRequest, PrefixClock, PrefixOracleRuntime, PrefixRanges
import test_held_program_preparation as preparation_fixture
from test_opening_prefix_contract import held


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires FFmpeg")
class OwnedAssemblyMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        """Reuse the existing real admitted source/master fixture, not fake receipts."""
        preparation_fixture.HeldPreparationTests.setUpClass()
        cls.fixture = preparation_fixture.HeldPreparationTests()

    def owned_job(self, label: str) -> tuple[AssembleJob, list[tuple[dict, Path]], Mock]:
        """Bind only actual call geometry to a TEST empty-prefix oracle."""
        job = self.fixture.job(label)
        bus = self.fixture.selection.master.source_bus
        job.graphic_frame_clock = (bus.frame_rate, bus.frames)
        runtime = PrefixOracleRuntime(held(Path(shutil.which("ffmpeg"))),
            held(Path(shutil.which("ffprobe"))), str(self.fixture.root), 30)
        observed, guard, render = [], Mock(), Mock(side_effect=AssertionError("empty graph has no render"))

        def compose(value: GraphicsComposition) -> dict:
            """Execute an empty prefix graph and retain exact pre-AAC picture bytes."""
            self.assertEqual(value.clips, ())
            request = CompositorPrefixRequest(held(Path(value.video_in)), (), value.clips, (),
                PrefixClock(*value.frame_clock, *value.canvas), PrefixRanges((0, 30), (0, 60)))
            end = time.monotonic() + 30
            result = compose_verified_prefix(PrefixCompositionJob(request, runtime, value.video_out, lambda: end - time.monotonic()))
            picture = self.fixture.root / f"{label}-TEST-picture.mp4"
            copy_verified(Path(value.video_out), picture, result["output"]["sha256"])
            observed.append((result, picture))
            return result

        job.owned_graphics = OwnedGraphicsExecution(render, compose, guard)
        return job, observed, guard

    def test_owned_picture_passes_real_whole_assembly_qc_with_same_master_and_one_aac(self) -> None:
        """Check whole actual media, source-master reuse and one audible AAC encode."""
        job, observed, guard = self.owned_job("owned-body")
        with patch.object(source, "build_program_master", side_effect=AssertionError("no remaster")), \
                (self.fixture.root / "owned-body.log").open("w") as log, contextlib.redirect_stdout(log):
            result = assemble(job)
        self.assertEqual(len(observed), 1)
        proof, picture = observed[0]
        self.assertEqual(proof["output"]["sha256"], file_hash(picture))
        self.assertEqual(packet_signature(str(picture), "v:0"), packet_signature(job.out, "v:0"))
        self.assertEqual(result["programAudio"]["programMasterReceiptHash"], self.fixture.selection.master.receipt["receiptHash"])
        self.assertFalse(result["preparationReuse"]["programRemastered"])
        self.assertFalse(result["preparationReuse"]["baseAudioSelected"])
        self.assertTrue(result["delivery"]["qualified"])
        delivery = bound_json(Path(result["programDeliveryReceipt"]["path"]))
        self.assertEqual(delivery["receiptHash"], result["programDeliveryReceipt"]["receiptHash"])
        self.assertFalse(delivery["approved"])
        self.assertEqual(delivery["audiblePathAacEncodes"], 1)
        audit = bound_json(Path(job.out).parent / "audit_report.json")
        self.assertEqual(audit["finalSha256"], file_hash(Path(job.out)))
        self.assertEqual(audit["counts"]["fail"], 0)
        self.assertTrue(audit["audioDelivery"]["audioDecodeSucceeded"])
        bus = self.fixture.selection.master.source_bus
        self.assertEqual(aac_audio_clock(job.out, bus)["presentedSamples"], bus.samples)
        self.assertGreater(guard.call_count, 10)

    def test_expired_live_owner_after_actual_audit_cannot_publish_candidate(self) -> None:
        """A real audit pass does not authorize publication after owner expiry."""
        job, observed, guard = self.owned_job("owned-expired")
        audit = source._private_audit

        def expire_after_audit(candidate: source._AssemblyCandidate, output: str) -> source._QualifiedCandidate:
            """Expire only after the real audit has returned its qualified candidate."""
            qualified = audit(candidate, output)
            guard.side_effect = RuntimeError("TEST live owner expired after real audit")
            return qualified

        with patch.object(source, "_private_audit", side_effect=expire_after_audit), \
                (self.fixture.root / "owned-expired.log").open("w") as log, contextlib.redirect_stdout(log):
            with self.assertRaisesRegex(RuntimeError, "expired after real audit"):
                assemble(job)
        self.assertEqual(len(observed), 1)
        self.assertFalse(Path(job.out).exists())
        self.assertFalse((Path(job.out).parent / "audit_report.json").exists())
        self.assertTrue(any(Path(job.out).parent.glob(".source-assembly-v2-*/audit_report.json")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
