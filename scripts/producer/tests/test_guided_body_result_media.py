"""Tiny real body result-adapter roundtrip over held ordinary base/master/QC.

Actual empty-graph prefix, picture copy, full AAC/master decode and Audit B.
No body activation, human approval, creator listening or OCI is simulated as
qualified. This verifies the adapter's real media/schema seam only.
"""
from __future__ import annotations

import contextlib
import json
import shutil
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from assemble import assemble
from audio import assemble_source_audio as source
from audio.assemble_publication import copy_verified
from cut_preview_io import digest, file_hash, write_new
from graphics.owned_execution import GraphicsComposition, OwnedGraphicsExecution
from guided_body_result import _delivery, observe_body_media, verify_body_media_files
from guided_opening_inputs import OpeningInputs
from opening_prefix_composition import PrefixCompositionJob, compose_verified_prefix
from opening_prefix_contract import CompositorPrefixRequest, PrefixClock, PrefixOracleRuntime, PrefixRanges
import test_held_program_preparation as preparation_fixture
from test_opening_prefix_contract import held


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires FFmpeg")
class BodyResultActualMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        """A new tiny actually admitted preparation, no prior fixtures overwritten."""
        class BodyPreparation(preparation_fixture.HeldPreparationTests):
            pass
        BodyPreparation.setUpClass()
        cls.fixture = BodyPreparation()

    def _compose(self, root: Path, value: GraphicsComposition) -> dict:
        """Real oracle + ordinary encode; TEST empty graph carries no template claim."""
        self.assertEqual(value.clips, ())
        runtime = PrefixOracleRuntime(held(Path(shutil.which("ffmpeg"))),
            held(Path(shutil.which("ffprobe"))), str(root), 30)
        request = CompositorPrefixRequest(held(Path(value.video_in)), (), value.clips, (),
            PrefixClock(*value.frame_clock, *value.canvas), PrefixRanges((0, 30), (0, 60)))
        end = time.monotonic() + 30
        proof = compose_verified_prefix(PrefixCompositionJob(request, runtime, value.video_out, lambda: end - time.monotonic()))
        picture = root / "picture-only.mp4"
        copy_verified(Path(value.video_out), picture, proof["output"]["sha256"])
        return {**proof, "retainedPicture": {"path": str(picture),
            "sha256": file_hash(picture), "sizeBytes": picture.stat().st_size}}

    def _reject_signal_drift(self, root: Path, evidence: dict, final: dict) -> None:
        """Resealed receipt mutations still must match actual current audio samples."""
        reference = evidence["programDeliveryReceipt"]
        path = Path(reference["path"])
        original = path.read_bytes()
        mutations = (
            lambda row: row.pop("localSignal"),
            lambda row: row["localSignal"].update(passed=False),
            lambda row: row["localSignal"].update(referenceSha256="0" * 64),
            lambda row: row["localSignal"].update(candidateSha256="0" * 64),
            lambda row: row["localSignal"].update(unexpected=True),
            lambda row: row["localSignal"]["thresholds"].update(minimum_snr_db=0),
            lambda row: row["localSignal"]["windows"].pop(),
            lambda row: row["localSignal"].update(elapsedSeconds=-1),
            lambda row: row["localSignal"].update(elapsedSeconds=True),
        )
        try:
            for index, mutate in enumerate(mutations):
                row = json.loads(original)
                mutate(row)
                row["receiptHash"] = digest({key: value for key, value in row.items() if key != "receiptHash"})
                path.write_text(json.dumps(row))
                changed = {**reference, "receiptHash": row["receiptHash"]}
                with self.subTest(signal_mutation=index), self.assertRaisesRegex(RuntimeError, "body local signal"):
                    _delivery(root, (changed, evidence["composition"], self.fixture.selection), final)
        finally:
            path.write_bytes(original)

    def test_actual_assembly_result_decodes_and_rebinds_full_master_qc_and_cut_support(self) -> None:
        root = self.fixture.root / "body-result-adapter"
        root.mkdir(mode=0o700)
        job = self.fixture.job("body-result-adapter/body-candidate")
        bus = self.fixture.selection.master.source_bus
        job.graphic_frame_clock = (bus.frame_rate, bus.frames)
        job.owned_graphics = OwnedGraphicsExecution(
            lambda _entry, _order: self.fail("empty graph may not render"),
            lambda value: self._compose(root, value), lambda: None)
        with patch.object(source, "build_program_master", side_effect=AssertionError("no remaster")), \
                (root / "TEST-actual-assembly.log").open("w") as log, contextlib.redirect_stdout(log):
            summary = assemble(job)
        inputs = OpeningInputs(Path(job.plan_path), file_hash(Path(job.plan_path)), {"TEST": "not worker authority"},
            {"candidatePlan": job.plan, "authority": {"frameRate": bus.frame_rate,
                "totalFrames": bus.frames, "target": job.plan["target"]}})
        evidence = {"composition": summary["ownedCompositionEvidence"],
                    "programDeliveryReceipt": summary["programDeliveryReceipt"]}
        started = time.monotonic()
        actual = observe_body_media(root, inputs, self.fixture.selection, evidence)
        elapsed = time.monotonic() - started
        write_new(root / "TEST-body-media-observation.json", actual)
        print(f"TEST actual body result adapter: {elapsed:.3f}s; retained {root}", flush=True)
        self.assertEqual(actual["final"]["frames"], bus.frames)
        self.assertEqual(actual["final"]["audioClock"]["presentedSamples"], bus.samples)
        self.assertTrue(actual["final"]["audioDelivery"]["qualified"])
        self.assertEqual(actual["programDelivery"]["audiblePathAacEncodes"], 1)
        self.assertFalse(actual["programDelivery"]["approved"])
        self.assertEqual(actual["cutDelivery"]["frames"], bus.frames)
        verify_body_media_files(root, actual)
        again = observe_body_media(root, inputs, self.fixture.selection, evidence)
        self.assertEqual(digest(again), digest(actual))
        self._reject_signal_drift(root, evidence, actual["final"])
        cut = root / "body-candidate/cut_delivery.v1.json"
        original = cut.read_bytes()
        try:
            cut.write_bytes(original + b" TEST post-QC mutation")
            with self.assertRaisesRegex(RuntimeError, "bytes changed"):
                verify_body_media_files(root, actual)
        finally:
            cut.write_bytes(original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
